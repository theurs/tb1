#!/usr/bin/env python3


import base64
import random
import time
import threading
import traceback

import openai

import cfg
import my_db
import my_log


BASE_URL = 'https://api.mistral.ai/v1'


#
# память диалога храниться в базе openrouter тк совместима с ним
#
#

# сколько запросов хранить
MAX_MEM_LINES = 20
MAX_HIST_CHARS = 60000


# блокировка чатов что бы не испортить историю
# {id:lock}
LOCKS = {}

# не принимать запросы больше чем, это ограничение для телеграм бота, в этом модуле оно не используется
MAX_REQUEST = 40000

# максимальный размер суммаризации
# MAX_SUM_REQUEST = 128*1000*3 # 128k tokens, 3 char per token
MAX_SUM_REQUEST = 300000


DEFAULT_MODEL = 'mistral-large-latest'
FALLBACK_MODEL = 'pixtral-large-latest'
VISION_MODEL = 'pixtral-large-latest'


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
    max_tokens: int = 8000,
    timeout: int = 120
    ) -> str:

    if not hasattr(cfg, 'MISTRALAI_KEYS'):
        return ''

    if not model:
        model = DEFAULT_MODEL

    messages = mem or []
    if system:
        messages.insert(0, {"role": "system", "content": system})
    if prompt:
        messages.append({"role": "user", "content": prompt})

    text = ''
    for _ in range(3):
        try:
            client = openai.OpenAI(
                api_key = random.choice(cfg.MISTRALAI_KEYS),
                base_url = BASE_URL,
            )
            response = client.chat.completions.create(
                model = model,
                messages = messages,
                temperature = temperature,
                max_tokens=max_tokens,
                timeout = timeout,
            )
            try:
                text = response.choices[0].message.content.strip()
            except Exception as error:
                my_log.log_mistral(f'ai:Failed to parse response: {error}\n\n{str(response)}')
                text = ''
            if text:
                if user_id:
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
            my_log.log_mistral(f'ai: {e}')
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
        my_log.log_mistral(f'update_mem: {error}\n\n{error_traceback}\n\n{query}\n\n{resp}\n\n{mem}')

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
        my_log.log_mistral(f'force:Failed to force message in chat {chat_id}: {error}\n\n{error_traceback}')


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
        my_log.log_mistral(f'undo: Failed to undo chat {chat_id}: {error}\n\n{error_traceback}')


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
        my_log.log_mistral(f'get_mem_as_string: {error}\n\n{error_traceback}')
        return ''


def img2txt(
    image_data: bytes,
    prompt: str = 'Describe picture',
    model = VISION_MODEL,
    temperature: float = 1,
    max_tokens: int = 8000,
    timeout: int = 120,
    chat_id: str = '',
    ) -> str:
    """
    Describes an image using the specified model and parameters.

    Args:
        image_data: The image data as bytes.
        prompt: The prompt to guide the description. Defaults to 'Describe picture'.
        model: The model to use for generating the description. Defaults to VISION_MODEL.
        temperature: The temperature parameter for controlling the randomness of the output. Defaults to 1.
        max_tokens: The maximum number of tokens to generate. Defaults to 8000.
        timeout: The timeout for the request in seconds. Defaults to 120.

    Returns:
        A string containing the description of the image, or an empty string if an error occurs.
    """
    if not hasattr(cfg, 'MISTRALAI_KEYS'):
        return ''

    if not model:
        model = VISION_MODEL

    if isinstance(image_data, str):
        with open(image_data, 'rb') as f:
            image_data = f.read()

    img_base = base64.b64encode(image_data).decode('utf-8')

    for _ in range(3):
        try:
            client = openai.OpenAI(
                api_key = random.choice(cfg.MISTRALAI_KEYS),
                base_url = BASE_URL,
            )
            response = client.chat.completions.create(
                model = model,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                messages = [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": f"data:image/jpeg;base64,{img_base}" 
                            }
                        ]
                    }
                ]
            )
            result = response.choices[0].message.content
            if chat_id:
                my_db.add_msg(chat_id, model)
            break
        except Exception as error:
            my_log.log_glm(f'img2txt: Failed to parse response: {error}\n\n{str(response)}')
            result = ''
            time.sleep(2)

    return result


def sum_big_text(text:str, query: str, temperature: float = 1, model = DEFAULT_MODEL) -> str:
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
    r = ai(query, temperature=temperature, model = model)
    if not r and model == DEFAULT_MODEL:
        r = ai(query, temperature=temperature, model = FALLBACK_MODEL)
    return r


if __name__ == '__main__':
    pass
    my_db.init(backup=False)

    # print(ai('сделай хороший перевод на английский этого текста:\n\n"Привет, как дела?"'))

    # print(img2txt('C:/Users/user/Downloads/3.jpg', 'извлеки весь текст с картинки, сохрани форматирование'))
    # print(img2txt('C:/Users/user/Downloads/2.jpg', 'реши все задачи, ответ по-русски'))
    # print(img2txt('C:/Users/user/Downloads/3.png', 'какой ответ и почему, по-русски'))

    # with open('C:/Users/user/Downloads/1.txt', 'r', encoding='utf-8') as f:
    #     text = f.read()

    # print(sum_big_text(text, 'сделай подробный пересказ по тексту'))

    chat_cli(model = '')

    my_db.close()
