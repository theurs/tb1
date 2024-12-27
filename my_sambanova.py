#!/usr/bin/env python3

import base64
import random
import requests
import time
import threading
import traceback

import openai

import cfg
import my_db
import my_log


BASE_URL = 'https://api.sambanova.ai/v1'


# сколько запросов хранить
MAX_MEM_LINES = 20
MAX_HIST_CHARS = 12000


# блокировка чатов что бы не испортить историю
# {id:lock}
LOCKS = {}

# не принимать запросы больше чем, это ограничение для телеграм бота, в этом модуле оно не используется
MAX_REQUEST = 6000


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


def ai(
    prompt: str = '',
    mem = None,
    user_id: str = '',
    system: str = '',
    model = '',
    temperature: float = 1,
    max_tokens: int = 4000, # :(
    timeout: int = 120
    ) -> str:

    if not hasattr(cfg, 'SAMBANOVA_KEYS'):
        return ''

    if not temperature:
        temperature = 1
    if temperature > 0:
        temperature = temperature/2

    if not model:
        # 'Meta-Llama-3.1-70B-Instruct', 'Meta-Llama-3.1-8B-Instruct', 'Meta-Llama-3.1-405B-Instruct', 'Qwen2.5-72B-Instruct'
        model = 'Meta-Llama-3.1-405B-Instruct'

    messages = mem or []
    if system:
        messages.insert(0, {"role": "system", "content": system})
    if prompt:
        messages.append({"role": "user", "content": prompt})

    text = ''
    for _ in range(3):
        try:
            client = openai.OpenAI(
                api_key = random.choice(cfg.SAMBANOVA_KEYS),
                base_url = BASE_URL,
            )
            response = client.chat.completions.create(
                model = model,
                messages = messages,
                temperature = temperature,
                max_tokens=2000,
                timeout = timeout,
            )
            try:
                text = response.choices[0].message.content.strip()
            except Exception as error:
                my_log.log_sambanova(f'ai:Failed to parse response: {error}\n\n{str(response)}')
                text = ''
            if text:
                my_db.add_msg(user_id, model)
                break  # Exit loop if successful
            else:
                time.sleep(2)
        except Exception as e:
            if 'The maximum context length' in str(e):
                messages = []
                if system:
                    messages.append({"role": "system", "content": system})
                messages += mem[-4:]
                continue
            my_log.log_sambanova(f'ai: {e}')
            time.sleep(2)

    return text


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
        my_log.log_sambanova(f'update_mem: {error}\n\n{error_traceback}\n\n{query}\n\n{resp}\n\n{mem}')

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

        mem_ = mem[:]
        text = ai(query, mem_, user_id=chat_id, temperature = temperature, system=system, model=model)

        if text:
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
        r = chat(q, 'test', model = model, system='отвечай всегда по-русски')
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
        my_log.log_sambanova(f'force:Failed to force message in chat {chat_id}: {error}\n\n{error_traceback}')


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
        my_log.log_sambanova(f'undo: Failed to undo chat {chat_id}: {error}\n\n{error_traceback}')


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


def get_mem_as_string(chat_id: str, md: bool = False) -> str:
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
            if md:
                result += f'{role}:\n\n{text}\n\n'
            else:
                result += f'{role}: {text}\n'
            if role == '𝐁𝐎𝐓':
                if md:
                    result += '\n\n'
                else:
                    result += '\n'
        return result 
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_sambanova(f'get_mem_as_string: {error}\n\n{error_traceback}')
        return ''


# def stt(input_file: str, lang: str = 'ru', chat_id: str = '_', prompt: str = '') -> str:

#     if isinstance(input_file, str):
#         with open(input_file, 'rb') as f:
#             data = f.read()
#     else:
#         data = input_file

#     base64_audio = base64.b64encode(data).decode('utf-8')

#     headers = {
#         "Content-Type": "application/json",
#         "Authorization": f"Bearer {random.choice(cfg.SAMBANOVA_KEYS)}"
#     }

#     data = {
#         "messages": [
#             {"role":"assistant","content":"You are a helpful assistant"},
#             {"role":"user","content":[
#                 {"type":"text","text":"Transcribe the audio"},
#                 {"type":"audio_content","audio_content":{"content":base64_audio}},
#                 ]
#              }
#             ],
#         "model": 'Qwen2-Audio-7B-Instruct',
#         "max_tokens": 1600,
#         "temperature": 0.01,
#         "stream": False,
#     }

#     response = requests.post(
#         "https://api.sambanova.ai/v1/audio/reasoning",
#         headers=headers,
#         json=data
#     )

#     return response.json()


if __name__ == '__main__':
    pass
    my_db.init(backup=False)

    chat_cli()

    # r = stt('C:/Users/user/Downloads/1.ogg')
    # print(r)

    my_db.close()