#!/usr/bin/env python3
# install from PyPI
# pip install groq


import random
import time
import threading
import traceback

import httpx
from groq import Groq
from sqlitedict import SqliteDict

import cfg
import my_log


# блокировка чатов что бы не испортить историю 
# {id:lock}
LOCKS = {}

# не принимать запросы больше чем, это ограничение для телеграм бота, в этом модуле оно не используется
MAX_REQUEST = 6000

MAX_QUERY_LENGTH = 10000
# максимальное количество запросов которые можно хранить в памяти
MAX_LINES = 20

# хранилище диалогов {id:list(mem)}
CHATS = SqliteDict('db/groq_dialogs.db', autocommit=True)

def ai(prompt: str = '',
       system: str = '',
       mem_ = [],
       temperature: float = 0.1,
       model_: str = '',
       max_tokens_: int = 2000,
       key_: str = '',
       ) -> str:
    """
    Generates a response using the GROQ AI model.

    Args:
        prompt (str, optional): The user's input prompt. Defaults to ''.
        system (str, optional): The system's initial message. Defaults to ''.
        mem_ (list, optional): The list of previous messages. Defaults to [].
        temperature (float, optional): The randomness of the generated response. Defaults to 0.1.
        model_ (str, optional): The name of the GROQ model to use. Defaults to 'llama3-70b-8192'.
        max_tokens_ (int, optional): The maximum number of tokens in the generated response. Defaults to 2000.
        key_ (str, optional): The API key for the GROQ model. Defaults to ''.

    Returns:
        str: The generated response from the GROQ AI model. Returns an empty string if error.

    Raises:
        Exception: If an error occurs during the generation of the response. The error message and traceback are logged.
    """
    try:
        mem = []
        if mem_:
            if system:
                mem.append({'role': 'system', 'content': system})
                mem += mem_
                if prompt:
                    mem.append({'role': 'user', 'content': prompt})
            else:
                mem = mem_
                if prompt:
                    mem.append({'role': 'user', 'content': prompt})
        else:
            if system:
                mem.append({'role': 'system', 'content': system})
            if prompt:
                mem.append({'role': 'user', 'content': prompt})

        if not mem:
            return ''

        key = key_ if key_ else random.choice(cfg.GROQ_API_KEY)
        if hasattr(cfg, 'GROQ_PROXIES') and cfg.GROQ_PROXIES:
            client = Groq(
                api_key=key,
                http_client = httpx.Client(proxy = random.choice(cfg.GROQ_PROXIES)),
                timeout = 120,
            )
        else:
            client = Groq(api_key=key, timeout = 120,)

        # model="llama3-70b-8192", # llama3-8b-8192, mixtral-8x7b-32768, gemma-7b-it, whisper-large-v3??
        model = model_ if model_ else 'llama3-70b-8192'

        chat_completion = client.chat.completions.create(
            messages=mem,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens_,
        )

        resp = chat_completion.choices[0].message.content
        return resp
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_groq(f'my_groq:ai: {error}\n\n{error_traceback}\n\n{prompt}\n\n{system}\n\n{mem_}\n{temperature}\n{model_}\n{max_tokens_}\n{key_}')

    return ''


def token_count(mem, model:str = "meta-llama/Meta-Llama-3-8B") -> int:
    '''broken, only counts symbols not tokens'''
    if isinstance(mem, str):
        text = mem
    else:
        text = ' '.join([m['content'] for m in mem])
    return len(text)


def update_mem(query: str, resp: str, mem):
    chat_id = None
    if isinstance(mem, str): # if mem - chat_id
        chat_id = mem
        if mem not in CHATS:
            CHATS[mem] = []
        mem = CHATS[mem]
    mem += [{'role': 'user', 'content': query}]
    mem += [{'role': 'assistant', 'content': resp}]
    while token_count(mem) > MAX_QUERY_LENGTH:
        mem = mem[2:]
    mem = mem[:MAX_LINES*2]
    if chat_id:
        CHATS[chat_id] = mem
    else:
        return mem


def chat(query: str, chat_id: str,
         temperature: float = 0.1,
         update_memory: bool = True,
         model: str = '',
         style: str = '') -> str:
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
        if style:
            r = ai(query, system = style, mem_ = mem, temperature = temperature, model_ = model)
        else:
            r = ai(query, mem_ = mem, temperature = temperature, model_ = model)
        if r and update_memory:
            mem = update_mem(query, r, mem)
            CHATS[chat_id] = mem
        return r


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
        my_log.log_groq(f'Failed to undo chat {chat_id}: {error}\n\n{error_traceback}')


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

        text = x['content']

        if text.startswith('[Info to help you answer'):
            end = text.find(']') + 1
            text = text[end:].strip()
        result += f'{role}: {text}\n'
        if role == '𝐁𝐎𝐓':
            result += '\n'
    return result


def chat_cli():
    while 1:
        q = input('>')
        if q == 'mem':
            print(get_mem_as_string('test'))
            continue
        r = chat(q, 'test')
        print(r)


def stt(data: bytes = None, lang: str = '', key_: str = '') -> str:
    '''not work - need access to groq cloud'''
    try:
        if not data:
            with open('1.ogg', 'rb') as f:
                data = f.read()

        key = key_ if key_ else random.choice(cfg.GROQ_API_KEY)
        if hasattr(cfg, 'GROQ_PROXIES') and cfg.GROQ_PROXIES:
            client = Groq(
                api_key=key,
                http_client = httpx.Client(proxy = random.choice(cfg.GROQ_PROXIES)),
                timeout = 120,
            )
        else:
            client = Groq(api_key=key, timeout = 120,)
        transcription = client.audio.transcriptions.create(file=("123.ogg", data),
                                                           model="whisper-large-v3",
                                                           language=lang,
                                                           response_format = 'text',
                                                           timeout=120,)
        return transcription.text
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_groq(f'my_groq:stt: {error}\n\n{error_traceback}\n\n{lang}\n\n{key_}')

    return ''


def reprompt_image(prompt: str) -> str:
    '''плохо работает'''
    query = f'''Rewrite the prompt for drawing a picture using a neural network,
make it bigger but keep close to the original, into English,
answer with a single long sentence, start with the words Create image of...\n\nPrompt: {prompt}
'''
    result = ai(query, temperature=1)
    if result:
        return result
    else:
        return prompt


def translate_text(text: str, lang: str = 'ru') -> str:
    """
    Translates the given text to the specified language using the Groq API.

    Args:
        text (str): The text to be translated.
        lang (str, optional): The target language for translation. Defaults to 'ru'.

    Returns:
        str: The translated text.

    Raises:
        None

    Examples:
        >>> translate_text("Hello, world!", "es")
        "¡Hola, mundo!"
    """
    query = f'Translate the following text to language "{lang}", in your answer should be only the translated text:\n\n{text}'
    return ai(query, temperature=0, max_tokens_ = 8000)


# def summ_text_file(path: str) -> str:
#     with open(path, 'r', encoding='utf-8') as f:
#         text = f.read()
#     prompt = f'Перескажи текст:\n\n{text[:MAX_QUERY_LENGTH]}'
#     system = 'Отвечай на русском языке в удобном для чтения формате, 500-3000 слов.'
#     return ai(prompt, system)


if __name__ == '__main__':
    # print(ai('привет как дела'))
    # print(summ_text_file('1.txt'))

    # chat_cli()

    for _ in range(100):
        t1 = time.time()
        r = ai('напиши рассказ про слона 4000 слов', temperature=1, max_tokens_ = 8000)
        t2 = time.time()
        print(len(r), round(t2 - t1, 2), f'{r[:20]}...{r[-20:]}'.replace('\n', ' '))

    # stt()

    # test_cases = [
    #     'print("Hello, World!")',
    #     'Let me learn how to code in Python.',
    # ]
    # for x in test_cases:
    #     print(x, '->', translate_text(x, 'ru'))