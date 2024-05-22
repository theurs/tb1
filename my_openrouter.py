#!/usr/bin/env python3

import json
import requests
import threading
import traceback

import langcodes
from sqlitedict import SqliteDict

import cfg
import my_log


# keys {user_id(str):key(str)}
KEYS = SqliteDict('db/open_router_keys.db', autocommit=True)
# {user_id(str):list(model, temperature, max_tokens, maxhistlines, maxhistchars)}
PARAMS = SqliteDict('db/open_router_params.db', autocommit=True)
PARAMS_DEFAULT = ['mistralai/mistral-7b-instruct:free', 1, 2000, 5, 6000]

# сколько запросов хранить
MAX_MEM_LINES = 10


# блокировка чатов что бы не испортить историю 
# {id:lock}
LOCKS = {}

# не принимать запросы больше чем, это ограничение для телеграм бота, в этом модуле оно не используется
MAX_REQUEST = 1000000
MAX_SUM_REQUEST = 30000

# хранилище диалогов {id:list(mem)}
CHATS = SqliteDict('db/openrouter_dialogs.db', autocommit=True)


def clear_mem(mem, user_id: str):
    if user_id not in PARAMS:
        PARAMS[user_id] = ['meta-llama/llama-3-8b-instruct:free', 1, 2000, 5, 6000]
    model, temperature, max_tokens, maxhistlines, maxhistchars = PARAMS[user_id]

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
    #return mem[-MAX_MEM_LINES*2:]


def count_tokens(mem) -> int:
    return sum([len(m['content']) for m in mem])


def ai(prompt: str = '',
       mem = None,
       user_id: str = '',
       system: str = '',
       model = '',
       temperature: float = 0.1,
       max_tokens: int = 8000,
       timeout: int = 120) -> str:

    if not prompt and not mem:
        return 0, ''
    # if not model:
    #     # model = 'gpt-3.5-turbo'
    #     model = 'google/gemma-7b-it:free'
    #     # model = 'openchat-7b:free'
    #     # model = 'mistral-7b-instruct:free'
    #     # model = 'llama-3-8b-instruct:free'

    if user_id not in PARAMS:
        PARAMS[user_id] = PARAMS_DEFAULT
    model, temperature, max_tokens, maxhistlines, maxhistchars = PARAMS[user_id]

    mem_ = mem or []
    if system:
        mem_ = [{'role': 'system', 'content': system}] + mem_
    if prompt:
        mem_ = mem_ + [{'role': 'user', 'content': prompt}]

    if hasattr(cfg, 'OPEN_ROUTER_KEY') and cfg.OPEN_ROUTER_KEY and user_id == 'test':
        key = cfg.OPEN_ROUTER_KEY
    elif user_id not in KEYS or not KEYS[user_id]:
        return 0, ''
    else:
        key = KEYS[user_id]

    YOUR_SITE_URL = 'https://t.me/kun4sun_bot'
    YOUR_APP_NAME = 'kun4sun_bot'

    response = requests.post(
        url="https://openrouter.ai/api/v1/chat/completions",
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
    # print(response)
    status = response.status_code
    if status == 200:
        text = response.json()['choices'][0]['message']['content'].strip()
    else:
        text = ''
    return status, text


def update_mem(query: str, resp: str, chat_id: str):
    if chat_id not in CHATS:
        CHATS[chat_id] = []
    mem = CHATS[chat_id]
    mem += [{'role': 'user', 'content': query}]
    mem += [{'role': 'assistant', 'content': resp}]
    mem = clear_mem(mem, chat_id)

    mem__ = []
    try:
        i = 0
        while i < len(mem):
            if i == 0 or mem[i] != mem[i-1]:
                mem__.append(mem[i])
            i += 1
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_openrouter(f'my_openrouter:update_mem: {error}\n\n{error_traceback}\n\n{query}\n\n{resp}\n\n{mem}')

    CHATS[chat_id] = mem__


def chat(query: str, chat_id: str = '', temperature: float = 0.1, system: str = '') -> str:
    global LOCKS, CHATS
    if chat_id in LOCKS:
        lock = LOCKS[chat_id]
    else:
        lock = threading.Lock()
        LOCKS[chat_id] = lock
    with lock:
        if chat_id not in CHATS:
            CHATS[chat_id] = []
        mem = CHATS[chat_id]
        status_code, text = ai(query, mem, user_id=chat_id, temperature = temperature, system=system)
        if text:
            mem += [{'role': 'user', 'content': query}]
            mem += [{'role': 'assistant', 'content': text}]
            mem = clear_mem(mem, chat_id)
            CHATS[chat_id] = mem
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
        global LOCKS, CHATS

        if chat_id in LOCKS:
            lock = LOCKS[chat_id]
        else:
            lock = threading.Lock()
            LOCKS[chat_id] = lock
        with lock:
            if chat_id in CHATS:
                mem = CHATS[chat_id]
                # remove 2 last lines from mem
                mem = mem[:-2]
                CHATS[chat_id] = mem
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_openrouter(f'Failed to undo chat {chat_id}: {error}\n\n{error_traceback}')


def reset(chat_id: str):
    """
    Resets the chat history for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to reset.

    Returns:
        None
    """
    global CHATS
    CHATS[chat_id] = []


def get_mem_as_string(chat_id: str) -> str:
    """
    Returns the chat history as a string for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to get the history for.

    Returns:
        str: The chat history as a string.
    """
    global CHATS
    if chat_id not in CHATS:
        CHATS[chat_id] = []
    mem = CHATS[chat_id]
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


def translate(text: str, from_lang: str = '', to_lang: str = '', help: str = '') -> str:
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
        my_log.log_translate(f'my_openrouter:translate:error1: {error1}\n\n{error_traceback}')
        
    try:
        to_lang = langcodes.Language.make(language=to_lang).display_name(language='en')
    except Exception as error2:
        error_traceback = traceback.format_exc()
        my_log.log_translate(f'my_openrouter:translate:error2: {error2}\n\n{error_traceback}')

    if help:
        query = f'Translate from language [{from_lang}] to language [{to_lang}], this can help you to translate better [{help}]:\n\n{text}'
    else:
        query = f'Translate from language [{from_lang}] to language [{to_lang}]:\n\n{text}'
    s, translated = ai(query, user_id='test',temperature=0.1)
    return translated


def sum_big_text(text:str, query: str, temperature: float = 0.1) -> str:
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
    query = f'''{query}\n\n{text[:MAX_SUM_REQUEST]}'''
    s, r = ai(query, user_id='test', temperature=temperature)
    return r


if __name__ == '__main__':
    # print(ai('hi'))
    # print(chat('hi'))
    # print(chat('1+1='))
    
    reset('test')
    chat_cli()
    
    # print(chat('1+1', 'test'))
    # print(chat('1+2', 'test'))
    # print(chat('1+3', 'test'))
    # print(CHATS['test'])


    # for x in range(50,100):
    #     s,r = chat(f'напиши рассказ на 10 слов про цифру {x}', 'test', temperature=1.5, system = 'отвечай всегда на английском языке')
    #     mem = CHATS['test']
    #     tokens_count = count_tokens(mem)
    #     print(len(r), r[:40].replace('\n', ' '), '...', r[-20:].replace('\n', ' '), len(mem), tokens_count)

    # print(translate('здорово как ты сам', from_lang='ru', to_lang='en'))

    # print(sum_big_text(open('1.txt','r', encoding='utf-8').read(), 'кратко перескажи текст, уложись в 1000 слов', temperature=1.5))
