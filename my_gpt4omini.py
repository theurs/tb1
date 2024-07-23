#!/usr/bin/env python3

import cachetools.func
import base64
import json
import requests
import threading
import traceback

import langcodes
from sqlitedict import SqliteDict

import cfg
import my_db
import my_log


# сколько запросов хранить
MAX_MEM_LINES = 20


# блокировка чатов что бы не испортить историю 
# {id:lock}
LOCKS = {}

# не принимать запросы больше чем, это ограничение для телеграм бота, в этом модуле оно не используется
MAX_REQUEST = 10000
MAX_SUM_REQUEST = 30000

maxhistchars = 20000
maxhistlines = MAX_MEM_LINES


# {user_id:bool} в каких чатах добавлять разблокировку цензуры
# не работает с гпт 4о мини
MEM_UNCENSORED = []


def clear_mem(mem):
    while 1:
        sizeofmem = count_tokens(mem)
        if sizeofmem <= maxhistchars:
            break
        try:
            mem = mem[2:]
        except IndexError:
            mem = []
            break
    return mem[-maxhistlines*2:]


def count_tokens(mem) -> int:
    return sum([len(m['content']) for m in mem])


def ai(prompt: str = '',
       mem = None,
       user_id: str = '',
       system: str = '',
       model = '',
       temperature: float = 1,
       max_tokens: int = 16000,
       timeout: int = 120) -> str:

    if not prompt and not mem:
        return 0, ''
    if not model:
        model = 'openai/gpt-4o-mini'

    if not hasattr(cfg, 'GPT4OMINI_KEY') or not hasattr(cfg, 'GPT4OMINI_URL'):
        return 0, ''

    key = cfg.GPT4OMINI_KEY
    url = cfg.GPT4OMINI_URL

    mem_ = mem or []
    if system:
        mem_ = [{'role': 'system', 'content': system}] + mem_
    if prompt:
        mem_ = mem_ + [{'role': 'user', 'content': prompt}]

    YOUR_SITE_URL = 'https://t.me/kun4sun_bot'
    YOUR_APP_NAME = 'kun4sun_bot'

    response = requests.post(
        url=url,
        headers={
            "Authorization": f"Bearer {key}",
            "HTTP-Referer": f"{YOUR_SITE_URL}", # Optional, for including your app on openrouter.ai rankings.
            "X-Title": f"{YOUR_APP_NAME}", # Optional. Shows in rankings on openrouter.ai.
        },
        data=json.dumps({
            "model": model, # Optional
            "messages": mem_,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }),
        timeout = timeout,
    )

    status = response.status_code
    if status == 200:
        try:
            text = response.json()['choices'][0]['message']['content'].strip()
        except Exception as error:
            my_log.log_gpt4omini(f'Failed to parse response: {error}\n\n{str(response)}')
            text = ''
    else:
        text = ''
    return status, text


def update_mem(query: str, resp: str, chat_id: str):
    mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_gpt4omini')) or []
    mem += [{'role': 'user', 'content': query}]
    mem += [{'role': 'assistant', 'content': resp}]
    mem = clear_mem(mem)

    mem__ = []
    try:
        i = 0
        while i < len(mem):
            if i == 0 or mem[i] != mem[i-1]:
                mem__.append(mem[i])
            i += 1
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_gpt4omini(f'my_gpt4omini:update_mem: {error}\n\n{error_traceback}\n\n{query}\n\n{resp}\n\n{mem}')

    my_db.set_user_property(chat_id, 'dialog_gpt4omini', my_db.obj_to_blob(mem__))


def chat(query: str, chat_id: str = '', temperature: float = 1, system: str = '', model: str = '') -> str:
    global LOCKS
    if chat_id in LOCKS:
        lock = LOCKS[chat_id]
    else:
        lock = threading.Lock()
        LOCKS[chat_id] = lock
    with lock:
        mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_gpt4omini')) or []
        status_code, text = ai(query, mem, user_id=chat_id, temperature = temperature, system=system, model=model)
        if text:
            my_db.add_msg(chat_id, 'gpt_4o_mini')
            mem += [{'role': 'user', 'content': query}]
            mem += [{'role': 'assistant', 'content': text}]
            mem = clear_mem(mem)
            my_db.set_user_property(chat_id, 'dialog_gpt4omini', my_db.obj_to_blob(mem))
        return status_code, text


def chat_cli():
    while 1:
        q = input('>')
        if q == 'mem':
            print(get_mem_as_string('test'))
            continue
        s, r = chat(f'(отвечай всегда на языке [ru]) ' + q, 'test')
        print(r)


def undo(chat_id: str):
    """
    Undo the last two lines of chat history for a given chat ID.

    Args:
        chat_id (str): The ID of the chat.

    Raises:
        Exception: If there is an error while undoing the chat history.

    Returns:
        None
    """
    try:
        global LOCKS

        if chat_id in LOCKS:
            lock = LOCKS[chat_id]
        else:
            lock = threading.Lock()
            LOCKS[chat_id] = lock
        with lock:
            mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_gpt4omini')) or []
            # remove 2 last lines from mem
            mem = mem[:-2]
            my_db.set_user_property(chat_id, 'dialog_gpt4omini', my_db.obj_to_blob(mem))
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_gpt4omini(f'Failed to undo chat {chat_id}: {error}\n\n{error_traceback}')


def reset(chat_id: str):
    """
    Resets the chat history for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to reset.

    Returns:
        None
    """
    mem = []
    my_db.set_user_property(chat_id, 'dialog_gpt4omini', my_db.obj_to_blob(mem))


def get_mem_as_string(chat_id: str) -> str:
    """
    Returns the chat history as a string for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to get the history for.

    Returns:
        str: The chat history as a string.
    """
    try:
        mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_gpt4omini')) or []
        result = ''
        for x in mem:
            role = x['role']
            if role == 'user': role = '𝐔𝐒𝐄𝐑'
            if role == 'assistant': role = '𝐁𝐎𝐓'
            if role == 'system': role = '𝐒𝐘𝐒𝐓𝐄𝐌'
            text = x['content']
            if text.startswith('[Info to help you answer'):
                end = text.find(']') + 1
                text = text[end:].strip()
            result += f'{role}: {text}\n'
            if role == '𝐁𝐎𝐓':
                result += '\n'
        return result 
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_gpt4omini(f'my_gpt4omini:get_mem_as_string: {error}\n\n{error_traceback}')
        return ''


def sum_big_text(text:str, query: str, temperature: float = 1, model: str = '', max_size: int = None) -> str:
    """
    Generates a response from an AI model based on a given text,
    query, and temperature.

    Args:
        text (str): The complete text to be used as input.
        query (str): The query to be used for generating the response.
        temperature (float, optional): The temperature parameter for controlling the randomness of the response. Defaults to 0.1.

    Returns:
        str: The generated response from the AI model.
    """
    query = f'''{query}\n\n{text[:max_size or MAX_SUM_REQUEST]}'''
    s, r = ai(query, user_id='test', temperature=temperature, model=model)
    return r


def reprompt_image(prompt: str, censored: bool = True, pervert: bool = False) -> str:
    _pervert = ', very pervert' if pervert else ''
    query = f'''Rewrite the prompt for drawing a picture using a neural network,
make it bigger and better as if your are a real image prompt engeneer{_pervert}, keep close to the original, into English,
answer with a single long sentence 50-300 words, start with the words Create image of...\n\nPrompt: {prompt}
'''
    if censored:
        result = ai(query, user_id='test', temperature=1)
    else:
        for _ in range(5):
            result = ai(query, user_id='test', temperature=1, mem=MEM_UNCENSORED)
            if result[0] == 200 and len(result[1]) > 200:
                return result[1]
        return prompt
    if result[0] == 200 and result[1]:
        return result[1]
    else:
        return prompt


def translate(text: str, from_lang: str = '', to_lang: str = '', help: str = '', censored: bool = False, model: str = '') -> str:
    """
    Translates the given text from one language to another.
    
    Args:
        text (str): The text to be translated.
        from_lang (str, optional): The language of the input text. If not specified, the language will be automatically detected.
        to_lang (str, optional): The language to translate the text into. If not specified, the text will be translated into Russian.
        help (str, optional): Help text for tranlator.
        
    Returns:
        str: The translated text.
    """
    if from_lang == '':
        from_lang = 'autodetect'
    if to_lang == '':
        to_lang = 'ru'
    try:
        from_lang = langcodes.Language.make(language=from_lang).display_name(language='en') if from_lang != 'autodetect' else 'autodetect'
    except Exception as error1:
        error_traceback = traceback.format_exc()
        my_log.log_translate(f'my_gemini:translate:error1: {error1}\n\n{error_traceback}')
        
    try:
        to_lang = langcodes.Language.make(language=to_lang).display_name(language='en')
    except Exception as error2:
        error_traceback = traceback.format_exc()
        my_log.log_translate(f'my_gemini:translate:error2: {error2}\n\n{error_traceback}')

    if help:
        query = f'Translate from language [{from_lang}] to language [{to_lang}], your reply should only be the translated text, this can help you to translate better [{help}]:\n\n{text}'
    else:
        query = f'Translate from language [{from_lang}] to language [{to_lang}], your reply should only be the translated text:\n\n{text}'

    if censored:
        translated = ai(query, user_id = 'test', temperature=1, max_tokens=8000, model=model)
    else:
        translated = ai(query, user_id = 'test', temperature=1, max_tokens=8000, model=model, mem=MEM_UNCENSORED)
    if translated[0] == 200:
        return translated[1]
    else:
        return ''


# Function to encode the image
def encode_image(data: bytes) -> str:
    return base64.b64encode(data).decode('utf-8')


@cachetools.func.ttl_cache(maxsize=10, ttl=10 * 60)
def img2txt(data_: bytes, prompt: str = "Что на картинке, подробно?", temp: float = 1, timeout: int = 120) -> str:
    """Получает описание изображения от модели gpt-4o-mini.

    Args:
        data_: Картинка в байтах или путь к ней.
        prompt: Подсказка для модели.
        temp: Температура модели.
        timeout: Сколько ждать ответа.

    Returns:
        Описание изображения.
    """

    if not hasattr(cfg, 'GPT4OMINI_KEY') or not hasattr(cfg, 'GPT4OMINI_URL'):
        return ''
    key = cfg.GPT4OMINI_KEY
    url = cfg.GPT4OMINI_URL

    if isinstance(data_, str):
        with open(data_, 'rb') as f:
            data_ = f.read()

    # Getting the base64 string
    base64_image = encode_image(data_)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}"
    }

    payload = {
        "model": "gpt-4o-mini",
        "temperature": temp,
        "messages": [
            {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": prompt
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}"
                    }
                }
            ]
            }
        ],
        "max_tokens": 1000
    }

    response = requests.post(url, headers=headers, json=payload, timeout = timeout)

    try:
        resp = response.json()['choices'][0]['message']['content']
    except:
        resp = ''
    return resp


if __name__ == '__main__':
    pass
    # my_db.init(backup=False)
    # chat_cli()
    # my_db.close()
    print(img2txt('d:/downloads/1.png'))
