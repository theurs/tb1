#!/usr/bin/env python3
# install from PyPI
# pip install groq

import random
import time
import threading
import traceback

import httpx
from groq import Groq, PermissionDeniedError
from groq.types.chat.completion_create_params import ResponseFormat
from sqlitedict import SqliteDict

import cfg
import my_log


# list of all users keys
ALL_KEYS = []


# for ai func
# DEFAULT_MODEL = 'llama-3.2-90b-vision-preview'
DEFAULT_MODEL = 'llama-3.3-70b-versatile'
FALLBACK_MODEL = 'llama-3.2-90b-vision-preview'


# блокировка чатов что бы не испортить историю 
# {id:lock}
LOCKS = {}

# не принимать запросы больше чем, это ограничение для телеграм бота, в этом модуле оно не используется
MAX_REQUEST = 6000
MAX_REQUEST_LLAMA31 = 20000

MAX_QUERY_LENGTH = 10000
MAX_MEM_LLAMA31 = 50000
# максимальное количество запросов которые можно хранить в памяти
MAX_LINES = 20

# {chat_id:mem}
CHATS = {}


def ai(prompt: str = '',
       system: str = '',
       mem_ = [],
       temperature: float = 1,
       model_: str = '',
       max_tokens_: int = 4000,
       key_: str = '',
       timeout: int = 180,
       json_output: bool = False,
       ) -> str:
    """
    Generates a response using the GROQ AI model.

    Args:
        prompt (str, optional): The user's input prompt. Defaults to ''.
        system (str, optional): The system's initial message. Defaults to ''.
        mem_ (list, optional): The list of previous messages. Defaults to [].
        temperature (float, optional): The randomness of the generated response. Defaults to 1.
        model_ (str, optional): The name of the GROQ model to use. Defaults to 'llama3-70b-8192'.
            (llama3-8b-8192, mixtral-8x7b-32768, llama-3.1-405b-reasoning, llama-3.1-70b-versatile, llama-3.1-8b-instant)
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

        if key_:
            keys = [key_, ]
        else:
            keys = ALL_KEYS
            random.shuffle(keys)
            keys = keys[:4]

        # model="llama3-70b-8192", # llama3-8b-8192, mixtral-8x7b-32768, 'llama-3.1-70b-versatile' 'llama-3.1-405b-reasoning'
        model = model_ if model_ else DEFAULT_MODEL

        max_mem = MAX_QUERY_LENGTH
        if 'llama-3.1' in model:
            max_mem = MAX_MEM_LLAMA31
        while token_count(mem) > max_mem + 100:
            mem = mem[2:]

        if 'llama-3' in model_ or 'llama3' in model_:
            temperature = temperature / 2

        for key in keys:
            if hasattr(cfg, 'GROQ_PROXIES') and cfg.GROQ_PROXIES:
                client = Groq(
                    api_key=key,
                    http_client = httpx.Client(proxy = random.choice(cfg.GROQ_PROXIES)),
                    timeout = timeout,
                )
            else:
                client = Groq(api_key=key, timeout = timeout)

            if json_output:
                resp_type = 'json_object'
            else:
                resp_type = 'text'
            try:
                chat_completion = client.chat.completions.create(
                    messages=mem,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens_,
                    response_format = ResponseFormat(type = resp_type),
                )
            except PermissionDeniedError:
                my_log.log_groq(f'GROQ PermissionDeniedError: {key}')
                continue
            except Exception as error:
                if 'Rate limit reached for model' in str(error).lower():
                    continue
            try:
                resp = chat_completion.choices[0].message.content.strip()
            except UnboundLocalError:
                resp = ''
            if not resp and 'llama-3.1' in model_:
                if model_ == 'llama-3.1-405b-reasoning':
                    model__ = 'llama-3.1-70b-versatile'
                elif model_ == 'llama-3.1-70b-versatile':
                    model__ = 'llama3-70b-8192'
                elif model_ == 'llama-3.1-8b-instant':
                    model__ = 'llama3-8b-8192'
                else:
                    return ''
                return ai(prompt, system, mem_, temperature*2, model__, max_tokens_, key_, timeout)
            elif not resp and 'llama-3.2' in model_:
                if model_ == 'llama-3.2-90b-text-preview':
                    model__ = 'llama-3.2-90b-vision-preview'
                elif model_ == 'llama-3.2-90b-vision-preview':
                    model__ = 'llama-3.1-70b-versatile'
                else:
                    return ''
                return ai(prompt, system, mem_, temperature*2, model__, max_tokens_, key_, timeout)
            elif not resp and 'llama-3.3' in model_:
                if model_ == 'llama-3.3-70b-versatile':
                    model__ = 'llama-3.3-70b-specdec'
                elif model_ == 'llama-3.3-70b-specdec':
                    model__ = 'llama-3.2-90b-vision-preview'
                else:
                    return ''
                return ai(prompt, system, mem_, temperature*2, model__, max_tokens_, key_, timeout)
            if resp:
                return resp
        return ''
    except Exception as error2:
        error_traceback = traceback.format_exc()
        my_log.log_groq(f'my_groq:ai: {error2}\n\n{error_traceback}\n\n{prompt}\n\n{system}\n\n{mem_}\n{temperature}\n{model_}\n{max_tokens_}\n{key_}')

    return ''


def token_count(mem, model:str = "meta-llama/Meta-Llama-3-8B") -> int:
    '''broken, only counts symbols not tokens'''
    if isinstance(mem, str):
        text = mem
    else:
        text = ' '.join([m['content'] for m in mem])
    l = len(text)
    return l


def update_mem(query: str, resp: str, mem):
    chat_id = None
    if isinstance(mem, str): # if mem - chat_id
        chat_id = mem
        mem = CHATS[chat_id] if chat_id in CHATS else []
    mem += [{'role': 'user', 'content': query}]
    mem += [{'role': 'assistant', 'content': resp}]

    mem = mem[:MAX_LINES*2]

    # непонятный глюк с задвоением памяти, убираем дубли
    mem__ = []
    try:
        i = 0
        while i < len(mem):
            if i == 0 or mem[i] != mem[i-1]:
                mem__.append(mem[i])
            i += 1
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_groq(f'my_groq:update_mem: {error}\n\n{error_traceback}\n\n{query}\n\n{resp}\n\n{mem}')
    
    if chat_id:
        CHATS[chat_id] = mem__
    else:
        return mem__


def chat(query: str, chat_id: str,
         temperature: float = 1,
         update_memory: bool = True,
         model: str = '',
         style: str = '',
         timeout = 60,
         max_tokens = 500,
         ) -> str:
    global LOCKS
    if chat_id in LOCKS:
        lock = LOCKS[chat_id]
    else:
        lock = threading.Lock()
        LOCKS[chat_id] = lock

    style += "\nОтвечай всегда по-русски, в разговорном стиле, кратко, как будто ты общаешься в голосовом чате."

    with lock:
        mem = CHATS[chat_id] if chat_id in CHATS else []
        if style:
            r = ai(query, system = style, mem_ = mem, temperature = temperature, model_ = model, timeout = timeout, max_tokens_=max_tokens)
        else:
            r = ai(query, mem_ = mem, temperature = temperature, model_ = model, timeout = timeout, max_tokens_=max_tokens)

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
    mem = []
    CHATS[chat_id] = mem


def chat_cli(model = ''):
    while 1:
        q = input('>')
        r = chat(query=q,
                 chat_id='test',
                 model = model)
        print(r)


def remove_dimatorzok(text: str) -> str:
    '''https://otvet.mail.ru/question/237076673
    Fix error in whisper dataset.
    '''
    lines = [
        'Субтитры сделал DimaTorzok.',
        'Субтитры сделал DimaTorzok',
        'Субтитры добавил DimaTorzok.',
        'Субтитры создавал DimaTorzok.',
        'Субтитры создавал DimaTorzok',
        'Субтитры добавил DimaTorzok',
        'Субтитры делал DimaTorzok',
        'DimaTorzok.',
        'DimaTorzok',
    ]
    for line in lines:
        text = text.replace(line, '')
    return text.strip()


def stt(data: bytes = None,
        lang: str = '',
        key_: str = '',
        prompt: str = '',
        last_try: bool = False,
        model: str = 'whisper-large-v3-turbo',
        ) -> str:
    """Speech to text function. Uses Groq API for speech recognition.
    Caches the results to avoid redundant API calls.
    The cache can store up to 10 results and they expire after 10 minutes.

    Args:
        data (bytes, optional): Audio data or filename. Defaults to None.
        lang (str, optional): Language code. Defaults to '' = 'ru'.
        key_ (str, optional): API key. Defaults to '' = random.choice(ALL_KEYS).
        prompt (str, optional): Prompt for the speech recognition model. Defaults to 'Распознай и исправь ошибки. Разбей на абзацы что бы легко было прочитать.'.

    Returns:
        str: Transcribed text.
    """
    try:
        if not data:
            with open('1.ogg', 'rb') as f:
                data = f.read()
        if isinstance(data, str):
            with open(data, 'rb') as f:
                data = f.read()
        if not lang:
            lang = 'ru'

        if key_:
            key = key_
        else:
            key = random.choice(ALL_KEYS)

        if hasattr(cfg, 'GROQ_PROXIES') and cfg.GROQ_PROXIES:
            client = Groq(
                api_key=key,
                http_client = httpx.Client(proxy = random.choice(cfg.GROQ_PROXIES)),
                timeout = 120,
            )
        else:
            client = Groq(api_key=key, timeout = 120,)
        transcription = client.audio.transcriptions.create(
            file=("123.mp3", data),
            model = model,
            # language=lang,
            language='ru',
            prompt=prompt,
            timeout=120,
            )
        return remove_dimatorzok(transcription.text)
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_groq(f'my_groq:stt: {error}\n\n{error_traceback}\n\n{lang}\n{model}\n{key_}')
        if not last_try and "'type': 'internal_server_error'" in str(error):
            time.sleep(4)
            return stt(data, lang, key_, prompt, True, model)

    return ''


def load_users_keys():
    """
    Load users' keys into memory and update the list of all keys available.
    """

    # каждый юзер дает свои ключи и они используются совместно со всеми
    # каждый ключ дает всего 6000 токенов в минуту для ллама3 так что чем больше тем лучше
    # {full_chat_id as str: key}
    # {'[9123456789] [0]': 'key', ...}
    USER_KEYS = SqliteDict('db/groq_user_keys.db')

    global ALL_KEYS
    ALL_KEYS = cfg.GROQ_API_KEY if hasattr(cfg, 'GROQ_API_KEY') and cfg.GROQ_API_KEY else []
    for user in USER_KEYS:
        key = USER_KEYS[user]
        if key not in ALL_KEYS:
            ALL_KEYS.append(key)


if __name__ == '__main__':
    pass

    load_users_keys()

    chat_cli()
