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


# сколько запросов хранить
MAX_MEM_LINES = 20
MAX_HIST_CHARS = 40000

# блокировка чатов что бы не испортить историю
# {id:lock}
LOCKS = {}

# не принимать запросы больше чем, это ограничение для телеграм бота, в этом модуле оно не используется
MAX_REQUEST = 50000


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
       model = 'nousresearch/hermes-3-llama-3.1-405b:free',
       temperature: float = 1,
       max_tokens: int = 4000,
       timeout: int = 120) -> str:

    if not model:
        model = 'nousresearch/hermes-3-llama-3.1-405b:free'

    if not model.endswith(':free') and 'google/gemini-flash-1.5-exp' not in model:
        return ''

    if not prompt and not mem:
        return ''

    if not hasattr(cfg, 'OPEN_ROUTER_FREE_KEYS') or len(cfg.OPEN_ROUTER_FREE_KEYS) < 1:
        return ''

    if not temperature:
        temperature = 0.1
    if 'llama' in model and temperature > 0:
        temperature = temperature / 2

    mem_ = mem or []
    if system:
        mem_ = [{'role': 'system', 'content': system}] + mem_
    if prompt:
        mem_ = mem_ + [{'role': 'user', 'content': prompt}]

    YOUR_SITE_URL = 'https://t.me/kun4sun_bot'
    YOUR_APP_NAME = 'kun4sun_bot'

    result = ''

    start_time = time.time()

    for _ in range(3):
        if time.time() - start_time > timeout:
            return ''
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {random.choice(cfg.OPEN_ROUTER_FREE_KEYS)}",
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
                result = response.json()['choices'][0]['message']['content'].strip()
                break
            except Exception as error:
                my_log.log_openrouter_free(f'Failed to parse response: {error}\n\n{str(response)}')
                result = ''
                time.sleep(2)
        else:
            my_log.log_openrouter_free(f'Bad response.status_code\n\n{str(response)[:2000]}')
            time.sleep(2)

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
        my_log.log_openrouter_free(f'my_openrouter:update_mem: {error}\n\n{error_traceback}\n\n{query}\n\n{resp}\n\n{mem}')

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
            if 'llama-3.1-405b' in model:
                my_db.add_msg(chat_id, 'llama405')
            elif 'llama-3.1-8b' in model:
                my_db.add_msg(chat_id, 'llama31-8b')
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
            if mem:
                # update last bot answer
                if len(mem) > 1:
                    mem[-1]['content'] = text
                    my_db.set_user_property(chat_id, 'dialog_openrouter', my_db.obj_to_blob(mem))
            else:
                my_db.set_user_property(chat_id, 'dialog_openrouter', my_db.obj_to_blob([text]))
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_openrouter_free(f'Failed to force message in chat {chat_id}: {error}\n\n{error_traceback}')


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
        my_log.log_openrouter_free(f'Failed to undo chat {chat_id}: {error}\n\n{error_traceback}')


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
        my_log.log_openrouter_free(f'my_openrouter:get_mem_as_string: {error}\n\n{error_traceback}')
        return ''


def img2txt(
    image_data: bytes,
    prompt: str = 'Describe picture',
    model = 'mistralai/pixtral-12b:free',
    temperature: float = 1,
    max_tokens: int = 2000,
    timeout: int = 120,
    chat_id: str = '',
    ) -> str:
    """
    Describes an image using the specified model and parameters.

    Args:
        image_data: The image data as bytes.
        prompt: The prompt to guide the description. Defaults to 'Describe picture'.
        model: The model to use for generating the description. Defaults to 'mistralai/pixtral-12b:free'.
        temperature: The temperature parameter for controlling the randomness of the output. Defaults to 1.
        max_tokens: The maximum number of tokens to generate. Defaults to 2000.
        timeout: The timeout for the request in seconds. Defaults to 120.

    Returns:
        A string containing the description of the image, or an empty string if an error occurs.
    """

    if isinstance(image_data, str):
        with open(image_data, 'rb') as f:
            image_data = f.read()

    if not model:
        model = 'mistralai/pixtral-12b:free'

    if not model.endswith(':free'):
        return ''

    if not prompt:
        prompt = 'Describe picture'
        return ''

    if not hasattr(cfg, 'OPEN_ROUTER_FREE_KEYS'):
        return ''

    if 'llama' in model and temperature > 0:
        temperature = temperature / 2

    base64_image = base64.b64encode(image_data).decode()

    YOUR_SITE_URL = 'https://t.me/kun4sun_bot'
    YOUR_APP_NAME = 'kun4sun_bot'

    result = ''

    for _ in range(3):
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {random.choice(cfg.OPEN_ROUTER_FREE_KEYS)}",
                "HTTP-Referer": f"{YOUR_SITE_URL}",  # Optional, for including your app on openrouter.ai rankings.
                "X-Title": f"{YOUR_APP_NAME}",  # Optional. Shows in rankings on openrouter.ai.
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
                my_log.log_openrouter_free(f'Failed to parse response: {error}\n\n{str(response)}')
                result = ''
                time.sleep(2)
        else:
            my_log.log_openrouter_free(f'Bad response.status_code\n\n{str(response)[:2000]}')
            time.sleep(2)
    if chat_id:
        my_db.add_msg(chat_id, model)
    return result


# def voice2txt(
#     voice_data: bytes,
#     model = 'google/gemini-flash-8b-1.5-exp',
#     temperature: float = 0,
#     max_tokens: int = 2000,
#     timeout: int = 120) -> str:
#     """
#     Transcribes audio data to text using the specified model and parameters.

#     Args:
#         voice_data: The audio data as bytes.
#         model: The model to use for generating the transcription. Defaults to 'google/gemini-flash-8b-1.5-exp'.
#         temperature: The temperature parameter for controlling the randomness of the output. Defaults to 0.
#         max_tokens: The maximum number of tokens to generate. Defaults to 2000.
#         timeout: The timeout for the request in seconds. Defaults to 120.

#     Returns:
#         A string containing the transcribed text, or an empty string if an error occurs.
#     """

#     if isinstance(voice_data, str):
#         with open(voice_data, 'rb') as f:
#             voice_data = f.read()

#     if not model:
#         model = 'google/gemini-flash-8b-1.5-exp'

#     # if not model.endswith(':free'):
#     #     return ''

#     if not hasattr(cfg, 'OPEN_ROUTER_FREE_KEYS'):
#         return ''

#     base64_voice = base64.b64encode(voice_data).decode()

#     YOUR_SITE_URL = 'https://t.me/kun4sun_bot'
#     YOUR_APP_NAME = 'kun4sun_bot'

#     result = ''

#     for _ in range(3):
#         response = requests.post(
#             url="https://openrouter.ai/api/v1/chat/completions",
#             headers={
#                 "Authorization": f"Bearer {random.choice(cfg.OPEN_ROUTER_FREE_KEYS)}",
#                 "HTTP-Referer": f"{YOUR_SITE_URL}",  # Optional, for including your app on openrouter.ai rankings.
#                 "X-Title": f"{YOUR_APP_NAME}",  # Optional. Shows in rankings on openrouter.ai.
#             },
#             data=json.dumps({

#                 "model": model,
#                 "temperature": temperature,
#                 "messages": [
#                     {
#                     "role": "user",
#                     "content": [
#                         {
#                             "type": "text",
#                             "text": 'transcribe it'
#                         },
#                         {
#                             "type": "voice_url",
#                             "voice_url": {
#                                 "url": f"data:audio/mpeg;base64,{base64_voice}"
#                             }
#                         }
#                     ]
#                     }
#                 ],
#                 "max_tokens": max_tokens

#             }),
#             timeout=timeout,
#         )

#         status = response.status_code
#         if status == 200:
#             try:
#                 result = response.json()['text'].strip()
#                 break
#             except Exception as error:
#                 my_log.log_openrouter_free(f'Failed to parse response: {error}\n\n{str(response)}')
#                 result = ''
#                 time.sleep(2)
#         else:
#             my_log.log_openrouter_free(f'Bad response.status_code\n\n{str(response)[:2000]}')
#             time.sleep(2)

#     return result


if __name__ == '__main__':
    pass
    my_db.init(backup=False)

    # reset('test')
    # chat_cli()

    print(img2txt('d:/downloads/1.jpg', 'что тут происходит, ответь по-русски', model='meta-llama/llama-3.2-11b-vision-instruct:free'))
    # print(voice2txt('d:/downloads/1.ogg'))

    my_db.close()
