#!/usr/bin/env python3
# pip install zhipuai

import base64
import random
import threading
import time
import traceback

from zhipuai import ZhipuAI

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

# модель по умолчанию
DEFAULT_MODEL = 'glm-4-plus' # 'glm-4-flash'
DEFAULT_VISION_MODEL = 'glm-4v-plus'
DEFAULT_PIC_MODEL = "cogView-3-plus"


def count_tokens(mem) -> int:
    return sum([len(m['content']) for m in mem])


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


def update_mem(query: str, resp: str, chat_id: str):
    mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_glm')) or []
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
        my_log.log_glm(f'update_mem: {error}\n\n{error_traceback}\n\n{query}\n\n{resp}\n\n{mem}')

    my_db.set_user_property(chat_id, 'dialog_glm', my_db.obj_to_blob(mem__))


def force(chat_id: str, text: str):
    '''update last bot answer with given text'''
    try:
        if chat_id in LOCKS:
            lock = LOCKS[chat_id]
        else:
            lock = threading.Lock()
            LOCKS[chat_id] = lock
        with lock:
            mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_glm')) or []
            if mem:
                # update last bot answer
                if len(mem) > 1:
                    mem[-1]['content'] = text
                    my_db.set_user_property(chat_id, 'dialog_glm', my_db.obj_to_blob(mem))
            else:
                my_db.set_user_property(chat_id, 'dialog_glm', my_db.obj_to_blob([text]))
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_glm(f'force: Failed to force message in chat {chat_id}: {error}\n\n{error_traceback}')


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
            mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_glm')) or []
            # remove 2 last lines from mem
            mem = mem[:-2]
            my_db.set_user_property(chat_id, 'dialog_glm', my_db.obj_to_blob(mem))
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_glm(f'undo: Failed to undo chat {chat_id}: {error}\n\n{error_traceback}')

    
def ai(prompt: str = '',
       mem = None,
       user_id: str = 'test_56486734657',
       system: str = '',
       model = 'glm-4-flash',
       temperature: float = 1,
       max_tokens: int = 4000,
       timeout: int = 120) -> str:

    if not hasattr(cfg, 'GLM4_KEYS') or len(cfg.GLM4_KEYS) < 1:
        return ''

    if not prompt and not mem:
        return ''

    if not model:
        model = DEFAULT_MODEL

    mem_ = mem or []
    if system:
        mem_ = [{'role': 'system', 'content': system}] + mem_
    if prompt:
        mem_ = mem_ + [{'role': 'user', 'content': prompt}]

    result = ''

    for _ in range(3):
        try:
            client = ZhipuAI(api_key=random.choice(cfg.GLM4_KEYS))
            response = client.chat.completions.create(
                model = model, # glm-4-flash (free?), glm-4-plus, glm-4, glm-4v-plus
                messages = mem_,
                temperature = temperature,
                max_tokens = max_tokens,
                timeout = timeout,
            )
            result = response.choices[0].message.content
            my_db.add_msg(user_id, model)
            break
        except Exception as error:
            my_log.log_glm(f'ai: Failed to parse response: {error}\n\n{str(response)}')
            result = ''
            time.sleep(2)

    return result


def chat(query: str, chat_id: str = '', temperature: float = 1, system: str = '', model: str = '') -> str:
    global LOCKS
    if chat_id in LOCKS:
        lock = LOCKS[chat_id]
    else:
        lock = threading.Lock()
        LOCKS[chat_id] = lock
    with lock:
        mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_glm')) or []

        text = ai(query, mem, user_id=chat_id, temperature = temperature, system=system, model=model)

        if text:
            mem += [{'role': 'user', 'content': query}]
            mem += [{'role': 'assistant', 'content': text}]
            mem = clear_mem(mem, chat_id)
            my_db.set_user_property(chat_id, 'dialog_glm', my_db.obj_to_blob(mem))
        return text
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
        mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_glm')) or []
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
        my_log.log_glm(f'get_mem_as_string: {error}\n\n{error_traceback}')
        return ''


def reset(chat_id: str):
    """
    Resets the chat history for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to reset.

    Returns:
        None
    """
    mem = []
    my_db.set_user_property(chat_id, 'dialog_glm', my_db.obj_to_blob(mem))


def get_last_mem(chat_id: str) -> str:
    """
    Returns the last answer for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to get the history for.

    Returns:
        str:
    """
    mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_glm')) or []

    last = mem[-1]
    if last:
        return last['content']
    else:
        return ''


def chat_cli(model: str = ''):
    while 1:
        q = input('>')
        if q == 'mem':
            print(get_mem_as_string('test'))
            continue
        r = chat(q, 'test', model = model)
        print(r)


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

    img_base = base64.b64encode(image_data).decode('utf-8')

    if not model:
        model = DEFAULT_VISION_MODEL

    for _ in range(3):
        try:
            client = ZhipuAI(api_key=random.choice(cfg.GLM4_KEYS))
            response = client.chat.completions.create(
                model = model,
                temperature=temperature,
                # max_tokens=max_tokens, # не работает
                timeout=timeout,
                messages=[
                {
                    "role": "user",
                    "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": img_base
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                    ]
                }
                ]
            )
            result = response.choices[0].message.content
            my_db.add_msg(chat_id, model)
            break
        except Exception as error:
            my_log.log_glm(f'img2txt: Failed to parse response: {error}\n\n{str(response)}')
            result = ''
            time.sleep(2)

    return result


def txt2img(prompt: str, amount: int = 1, model: str = DEFAULT_PIC_MODEL, user_id: str = '-', timeout: int = 120) -> list[str]:
    """
    Generates images from a text prompt using ZhipuAI.

    Args:
        prompt: The text prompt to generate images from.
        amount: The number of images to generate (currently not functional).
        model: The ZhipuAI model to use.
        user_id: user id for accounting.
        timeout: The timeout for the request.

    Returns:
        A list of image URLs, or an empty list if an error occurred.
    """
    try:
        client = ZhipuAI(api_key=random.choice(cfg.GLM4_KEYS))  # Initialize ZhipuAI client with a randomly selected API key.

        response = client.images.generations(
            model=model,
            prompt=prompt,
            size="1024x1024",
            # n = amount, # The 'n' parameter seems to be not working. Setting to 1 for now.
            timeout=timeout
        )
        # Extract image URLs from the response
        image_urls = [item.url for item in response.data]
        if user_id != '-':
            my_db.add_msg(user_id, f'img {model}')
        return image_urls

    except Exception as error:
        my_log.log_glm(f'txt2img: Failed to generate image: {error}\nResponse: {response}')
        return []


if __name__ == '__main__':
    pass
    my_db.init(backup=False)

    # reset('test')
    # chat_cli()

    # print(img2txt('d:/downloads/1.jpg', 'извлеки весь текст с картинки, сохрани форматирование'))
    # print(img2txt('d:/downloads/2.jpg', 'реши все задачи, ответ по-русски'))
    # print(img2txt('d:/downloads/3.png', 'какой ответ и почему, по-русски'))
    
    # print(txt2img('реалистичное лицо крупным планом - удивленная гермиона грейнджер', amount=4))    

    my_db.close()
