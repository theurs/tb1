#!/usr/bin/env python3


import base64
import json
import random
import requests
import time
import threading
import traceback

import cfg
import my_db
import my_log


DEFAULT_MODEL = 'grok-2-latest'
FALLBACK_MODEL = 'grok-beta'
VISION_MODEL = 'grok-vision-beta'
FALLBACK_VISION_MODEL = 'grok-2-vision-1212'

BASE_URL = "https://api.x.ai/v1/chat/completions"

# сколько запросов хранить
MAX_MEM_LINES = 20
MAX_HIST_CHARS = 80000

# блокировка чатов что бы не испортить историю
# {id:lock}
LOCKS = {}

# не принимать запросы больше чем, это ограничение для телеграм бота, в этом модуле оно не используется
MAX_REQUEST = 50000

MAX_SUM_REQUEST = 100000


def clear_mem(mem, user_id: str):
    while 1:
        sizeofmem = count_tokens(mem)
        if sizeofmem <= MAX_HIST_CHARS:
            break
        try:
            mem = mem[2:]
        except IndexError:
            mem = []
            break

    return mem[-MAX_MEM_LINES*2:]


def count_tokens(mem) -> int:
    return sum([len(m['content']) for m in mem])


def ai(prompt: str = '',
       mem = None,
       user_id: str = '',
       system: str = '',
       model = '',
       temperature: float = 1,
       max_tokens: int = 4000,
       timeout: int = 120) -> str:

    if not hasattr(cfg, 'GROK_KEYS') or len(cfg.GROK_KEYS) < 1:
        return ''

    if not model:
        model = DEFAULT_MODEL

    if not prompt and not mem:
        return ''

    mem_ = mem or []
    if system:
        mem_ = [{'role': 'system', 'content': system}] + mem_
    if prompt:
        mem_ = mem_ + [{'role': 'user', 'content': prompt}]

    result = ''

    start_time = time.time()

    for _ in range(3):
        if time.time() - start_time > timeout:
            return ''
        response = requests.post(
            url=BASE_URL,
            headers={
                "Authorization": f"Bearer {random.choice(cfg.GROK_KEYS)}",
                "Content-Type": "application/json",
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
                result = response.json()['choices'][0]['message']['content'].strip()
                break
            except Exception as error:
                my_log.log_grok(f'Failed to parse response: {error}\n\n{str(response)}')
                result = ''
                time.sleep(2)
        else:
            my_log.log_grok(f'Bad response.status_code\n\n{str(response)[:2000]}')
            time.sleep(2)

    if not result:
        if model == DEFAULT_MODEL:
            return ai(prompt, mem, user_id, system, FALLBACK_MODEL, temperature, max_tokens, timeout)

    return result


def update_mem(query: str, resp: str, chat_id: str):
    mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_openrouter')) or []
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
        my_log.log_grok(f'my_openrouter:update_mem: {error}\n\n{error_traceback}\n\n{query}\n\n{resp}\n\n{mem}')

    my_db.set_user_property(chat_id, 'dialog_openrouter', my_db.obj_to_blob(mem__))


def chat(query: str, chat_id: str = '', temperature: float = 1, system: str = '', model: str = '') -> str:
    global LOCKS
    if chat_id in LOCKS:
        lock = LOCKS[chat_id]
    else:
        lock = threading.Lock()
        LOCKS[chat_id] = lock
    with lock:
        mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_openrouter')) or []

        text = ai(query, mem, user_id=chat_id, temperature = temperature, system=system, model=model)

        if text:
            my_db.add_msg(chat_id, model or DEFAULT_MODEL)
            mem += [{'role': 'user', 'content': query}]
            mem += [{'role': 'assistant', 'content': text}]
            mem = clear_mem(mem, chat_id)
            my_db.set_user_property(chat_id, 'dialog_openrouter', my_db.obj_to_blob(mem))
        return text
    return ''


def chat_cli(model: str = ''):
    while 1:
        q = input('>')
        if q == 'mem':
            print(get_mem_as_string('test'))
            continue
        r = chat(f'(отвечай всегда на языке [ru]) ' + q, 'test', model = model)
        print(r)


def force(chat_id: str, text: str):
    '''update last bot answer with given text'''
    try:
        if chat_id in LOCKS:
            lock = LOCKS[chat_id]
        else:
            lock = threading.Lock()
            LOCKS[chat_id] = lock
        with lock:
            mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_openrouter')) or []
            if mem and len(mem) > 1:
                mem[-1]['content'] = text
                my_db.set_user_property(chat_id, 'dialog_openrouter', my_db.obj_to_blob(mem))
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_grok(f'Failed to force message in chat {chat_id}: {error}\n\n{error_traceback}')


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
        if chat_id in LOCKS:
            lock = LOCKS[chat_id]
        else:
            lock = threading.Lock()
            LOCKS[chat_id] = lock
        with lock:
            mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_openrouter')) or []
            # remove 2 last lines from mem
            mem = mem[:-2]
            my_db.set_user_property(chat_id, 'dialog_openrouter', my_db.obj_to_blob(mem))
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_grok(f'Failed to undo chat {chat_id}: {error}\n\n{error_traceback}')


def reset(chat_id: str):
    """
    Resets the chat history for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to reset.

    Returns:
        None
    """
    mem = []
    my_db.set_user_property(chat_id, 'dialog_openrouter', my_db.obj_to_blob(mem))


def get_last_mem(chat_id: str) -> str:
    """
    Returns the last answer for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to get the history for.

    Returns:
        str:
    """
    mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_openrouter')) or []

    last = mem[-1]
    if last:
        return last['content']
    else:
        return ''


def get_mem_as_string(chat_id: str) -> str:
    """
    Returns the chat history as a string for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to get the history for.

    Returns:
        str: The chat history as a string.
    """
    try:
        mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_openrouter')) or []
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
        my_log.log_grok(f'my_openrouter:get_mem_as_string: {error}\n\n{error_traceback}')
        return ''


def img2txt(
    image_data: bytes,
    prompt: str = 'Describe picture',
    model = '',
    temperature: float = 1,
    max_tokens: int = 4000,
    timeout: int = 120,
    chat_id: str = '',
    ) -> str:
    """
    Describes an image using the specified model and parameters.

    Args:
        image_data: The image data as bytes.
        prompt: The prompt to guide the description. Defaults to 'Describe picture'.
        model: The model to use for generating the description.
        temperature: The temperature parameter for controlling the randomness of the output. Defaults to 1.
        max_tokens: The maximum number of tokens to generate. Defaults to 4000.
        timeout: The timeout for the request in seconds. Defaults to 120.

    Returns:
        A string containing the description of the image, or an empty string if an error occurs.
    """
    if not hasattr(cfg, 'GROK_KEYS'):
        return ''

    if isinstance(image_data, str):
        with open(image_data, 'rb') as f:
            image_data = f.read()

    if not model:
        model = VISION_MODEL

    if not prompt:
        prompt = 'Describe picture'
        return ''

    base64_image = base64.b64encode(image_data).decode()

    result = ''

    for _ in range(3):
        response = requests.post(
            url=BASE_URL,
            headers={
                "Authorization": f"Bearer {random.choice(cfg.GROK_KEYS)}",
                "Content-Type": "application/json",
            },
            data=json.dumps({

                "model": model,
                "temperature": temperature,
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
                "max_tokens": max_tokens

            }),
            timeout=timeout,
        )

        status = response.status_code
        if status == 200:
            try:
                result = response.json()['choices'][0]['message']['content'].strip()
                break
            except Exception as error:
                my_log.log_grok(f'Failed to parse response: {error}\n\n{str(response)}')
                result = ''
                time.sleep(2)
        else:
            my_log.log_grok(f'Bad response.status_code\n\n{str(response)[:2000]}')
            time.sleep(2)

    if not result:
        if model == VISION_MODEL:
            return img2txt(image_data, prompt, FALLBACK_VISION_MODEL, temperature, max_tokens, timeout, chat_id)

    if chat_id:
        my_db.add_msg(chat_id, model)

    return result


if __name__ == '__main__':
    pass
    my_db.init(backup=False)

    # reset('test')
    # chat_cli()

    # print(ai('напиши 5 самых популярных слов в русском языке'))

    # print(img2txt('C:/Users/user/Downloads/1.jpg', 'текст с картинки'))

    my_db.close()
