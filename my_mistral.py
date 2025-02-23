#!/usr/bin/env python3


import base64
import time
import threading
import traceback

import openai
from sqlitedict import SqliteDict

import cfg
import my_db
import my_log
import utils


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

# каждый юзер дает свои ключи и они используются совместно со всеми
# каждый ключ дает всего 500000 токенов в минуту так что чем больше тем лучше
# {full_chat_id as str: key}
# {'[9123456789] [0]': 'key', ...}
ALL_KEYS = []
USER_KEYS = SqliteDict('db/mistral_user_keys.db', autocommit=True)
USER_KEYS_LOCK = threading.Lock()

# не принимать запросы больше чем, это ограничение для телеграм бота, в этом модуле оно не используется
MAX_REQUEST = 40000

# максимальный размер суммаризации
# MAX_SUM_REQUEST = 128*1000*3 # 128k tokens, 3 char per token
MAX_SUM_REQUEST = 100000


DEFAULT_MODEL = 'mistral-large-latest'
CODE_MODEL = 'codestral-latest'
CODE_MODEL_FALLBACK = 'codestral-2405'
FALLBACK_MODEL = 'pixtral-large-latest'
VISION_MODEL = 'pixtral-large-latest'
SMALL_MODEL = 'mistral-small-latest'


CURRENT_KEYS_SET = []


def get_next_key() -> str:
    '''
    Return round robin key from ALL_KEYS
    '''
    global CURRENT_KEYS_SET
    if not CURRENT_KEYS_SET:
        if ALL_KEYS:
            CURRENT_KEYS_SET = ALL_KEYS[:]

    if CURRENT_KEYS_SET:
        return CURRENT_KEYS_SET.pop(0)
    else:
        raise Exception('mistral_keys is empty')


def ai(
    prompt: str = '',
    mem = None,
    user_id: str = '',
    system: str = '',
    model = '',
    temperature: float = 1,
    max_tokens: int = 8000,
    timeout: int = 120,
    key_: str = '',
    json_output: bool = False,
    ) -> str:

    if not len(ALL_KEYS) and not key_:
        return ''

    if not model:
        model = DEFAULT_MODEL

    messages = mem or []
    if system:
        messages.insert(0, {"role": "system", "content": system})
    if prompt:
        messages.append({"role": "user", "content": prompt})

    text = ''
    key = ''
    start_time = time.time()
    for _ in range(3):
        time_left = timeout - (time.time() - start_time)
        if time_left < 0:
            my_log.log_mistral(f'ai:0: timeout | {key} | {user_id}\n\n{messages}\n\n{model}\n\n{prompt}')
            break
        try:
            key = get_next_key() if not key_ else key_
            client = openai.OpenAI(
                api_key = key,
                base_url = BASE_URL,
            )
            if json_output:
                response = client.chat.completions.create(
                    model = model,
                    messages = messages,
                    temperature = int(temperature/2),
                    max_tokens=max_tokens,
                    timeout = timeout,
                    response_format = { "type": "json_object" },
                )
            else:
                response = client.chat.completions.create(
                    model = model,
                    messages = messages,
                    temperature = int(temperature/2),
                    max_tokens=max_tokens,
                    timeout = timeout,
                )
            try:
                text = response.choices[0].message.content.strip()
            except Exception as error:
                my_log.log_mistral(f'ai:1:Failed to parse response: {error}\n\n{str(response)} | {key} | {user_id}')
                text = ''
            if text:
                if user_id:
                    my_db.add_msg(user_id, model)
                break  # Exit loop if successful
            else:
                if key_:
                    break
                time.sleep(2)
        except Exception as error2:
            if 'The maximum context length' in str(error2):
                messages = []
                if system:
                    messages.append({"role": "system", "content": system})
                messages += mem[-4:]
                continue
            if 'Unauthorized' in str(error2):
                remove_key(key)
                my_log.log_mistral(f'ai:2: {error2} | {key} | {user_id}')
            my_log.log_mistral(f'ai:3: {error2} | {key} | {user_id}\n\n{messages}\n\n{model}\n\n{prompt}')
            time.sleep(2)

    if not text and model == DEFAULT_MODEL:
        text = ai(prompt, mem, user_id, system, FALLBACK_MODEL, temperature, max_tokens, timeout - (time.time() - start_time), key_, json_output)

    return text


def img2txt(
    image_data: bytes,
    prompt: str = 'Describe picture',
    model = VISION_MODEL,
    temperature: float = 1,
    max_tokens: int = 8000,
    timeout: int = 120,
    chat_id: str = '',
    system: str = '',
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
    if not len(ALL_KEYS):
        return ''

    if not model:
        model = VISION_MODEL

    if isinstance(image_data, str):
        with open(image_data, 'rb') as f:
            image_data = f.read()

    img_base = base64.b64encode(image_data).decode('utf-8')

    mem = [
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
    if system:
        mem.insert(0, {'role': 'system', 'content': system})

    key = ''
    for _ in range(3):
        try:
            key = get_next_key()
            client = openai.OpenAI(
                api_key = key,
                base_url = BASE_URL,
            )
            response = client.chat.completions.create(
                model = model,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                messages = mem,
            )
            result = response.choices[0].message.content
            if chat_id:
                my_db.add_msg(chat_id, model)
            break
        except Exception as error:
            if 'Unauthorized' in str(error):
                remove_key(key)
                my_log.log_mistral(f'img2txt: {error} {key}')
            my_log.log_glm(f'img2txt: Failed to parse response: {error}')
            result = ''
            time.sleep(2)

    return result


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


def chat(query: str, chat_id: str = '', temperature: float = 1, system: str = '', model: str = '', do_not_update_history: bool = False) -> str:
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

        if text and not do_not_update_history:
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


def remove_key(key: str):
    '''Removes a given key from the ALL_KEYS list and from the USER_KEYS dictionary.'''
    try:
        if not key:
            return
        if key in ALL_KEYS:
            try:
                ALL_KEYS.remove(key)
            except ValueError:
                my_log.log_keys(f'remove_key: Invalid key {key} not found in ALL_KEYS list')

        keys_to_delete = []
        with USER_KEYS_LOCK:
            # remove key from USER_KEYS
            for user in USER_KEYS:
                if USER_KEYS[user] == key:
                    keys_to_delete.append(user)

            for user_key in keys_to_delete:
                del USER_KEYS[user_key]

            if keys_to_delete:
                my_log.log_keys(f'mistral: Invalid key {key} removed from users {keys_to_delete}')
            else:
                my_log.log_keys(f'mistral: Invalid key {key} was not associated with any user in USER_KEYS')

    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_mistral(f'mistral: Failed to remove key {key}: {error}\n\n{error_traceback}')


def load_users_keys():
    """
    Load users' keys into memory and update the list of all keys available.
    """
    with USER_KEYS_LOCK:
        global USER_KEYS, ALL_KEYS
        ALL_KEYS = cfg.MISTRALAI_KEYS if hasattr(cfg, 'MISTRALAI_KEYS') and cfg.MISTRALAI_KEYS else []
        for user in USER_KEYS:
            key = USER_KEYS[user]
            if key not in ALL_KEYS:
                ALL_KEYS.append(key)


def test_key(key: str) -> bool:
    '''
    Tests a given key by making a simple request to the Mistral AI API.
    '''
    r = ai('1+1=', key_=key.strip())
    return bool(r)


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


def get_reprompt_for_image(prompt: str, chat_id: str = '') -> tuple[str, str, bool, bool] | None:
    """
    Generates a detailed prompt for image generation based on user query and conversation history.

    Args:
        prompt: User's query for image generation.

    Returns:
        A tuple of four elements: (positive prompt, negative prompt, moderation_sexual, moderation_hate)
        or None if an error occurred.
    """

    result = ai(
        prompt,
        temperature=1.5,
        json_output=True,
        model=DEFAULT_MODEL,
        user_id=chat_id,
        )
    result_dict = utils.string_to_dict(result)
    if result_dict:
        reprompt = ''
        negative_prompt = ''
        moderation_sexual = False
        moderation_hate = False
        if 'reprompt' in result_dict:
            reprompt = result_dict['reprompt']
        if 'negative_reprompt' in result_dict:
            negative_prompt = result_dict['negative_reprompt']
        if 'negative_prompt' in result_dict:
            negative_prompt = result_dict['negative_prompt']
        if 'moderation_sexual' in result_dict:
            moderation_sexual = result_dict['moderation_sexual']
            if moderation_sexual:
                my_log.log_huggin_face_api(f'MODERATION image reprompt failed: {prompt}')
        if 'moderation_hate' in result_dict:
            moderation_hate = result_dict['moderation_hate']
            if moderation_hate:
                my_log.log_huggin_face_api(f'MODERATION image reprompt failed: {prompt}')

        if reprompt and negative_prompt:
            return reprompt, negative_prompt, moderation_sexual, moderation_hate
    return None


if __name__ == '__main__':
    pass
    my_db.init(backup=False)
    load_users_keys()

    # print(ai('сделай хороший перевод на английский этого текста:\n\n"Привет, как дела?"'))

    # print(img2txt('C:/Users/user/Downloads/3.jpg', 'извлеки весь текст с картинки, сохрани форматирование'))
    # print(img2txt('C:/Users/user/Downloads/2.jpg', 'реши все задачи, ответ по-русски'))
    # print(img2txt('C:/Users/user/Downloads/3.png', 'какой ответ и почему, по-русски'))

    # with open('C:/Users/user/Downloads/1.txt', 'r', encoding='utf-8') as f:
    #     text = f.read()

    # print(sum_big_text(text, 'сделай подробный пересказ по тексту'))

    chat_cli(model = '')
    # print(get_reprompt_for_image(''))

    my_db.close()
