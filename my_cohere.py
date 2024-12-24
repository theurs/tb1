#!/usr/bin/env python3
# pip install -U cohere
# hosts: 50.7.85.220 api.cohere.com

import random
import threading
import traceback

import cohere

import cfg
import my_db
import my_log


# MAX_SUM_REQUEST = 128 * 1000 * 3
MAX_QUERY_LENGTH = 100000
MAX_SUM_REQUEST = 100000
MAX_REQUEST = 20000
DEFAULT_MODEL = 'command-r-plus'
FALLBACK_MODEL = 'command-r'
MAX_MEM_LINES = 20
MAX_HIST_CHARS = 60000

# блокировка чатов что бы не испортить историю
# {id:lock}
LOCKS = {}


def ai(
    prompt: str = '',
    mem_ = None,
    user_id: str = '',
    system: str = '',
    model_ = '',
    temperature: float = 1,
    max_tokens_: int = 4000,
    timeout: int = 120,
    key_: str = '',
    json_output: bool = False,
    ) -> str:
    """
    Generates a response using the cohere AI model.

    Args:
        prompt (str, optional): The user's input prompt. Defaults to ''.
        mem_ (list, optional): The list of previous messages. Defaults to [].
        user_id (str, optional): The user's ID. Defaults to ''.
        system (str, optional): The system's initial message. Defaults to ''.
        model_ (str, optional): The name of the cohere model to use. Defaults to DEFAULT_MODEL.
        temperature (float, optional): The randomness of the generated response. Defaults to 1.
        max_tokens_ (int, optional): The maximum number of tokens in the generated response. Defaults to 2000.
        timeout (int, optional): The timeout for the request in seconds. Defaults to 120.
        key_ (str, optional): The API key for the cohere model. Defaults to ''.
        json_output (bool, optional): Whether to return the response as a JSON object. Defaults to False.

    Returns:
        str: The generated response from the cohere AI model. Returns an empty string if error.

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
            keys = cfg.COHERE_AI_KEYS
            random.shuffle(keys)
            keys = keys[:4]

        model = model_ if model_ else DEFAULT_MODEL

        while count_tokens(mem) > MAX_QUERY_LENGTH + 100:
            mem = mem[2:]

        for key in keys:
            client = cohere.ClientV2(cfg.COHERE_AI_KEYS[0], timeout = timeout)

            if json_output:
                resp_type = 'json_object'
            else:
                resp_type = 'text'
            try:
                response = client.chat(
                    messages=mem,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens_,
                    response_format = {"type": resp_type},
                )
            except Exception as error:
                my_log.log_cohere(f'ai: {error}\n\n{prompt}\n\n{system}\n\n{mem_}\n{temperature}\n{model_}\n{max_tokens_}\n{key_}\n{key}')
                continue
            try:
                resp = response.message.content[0].text.strip()
            except Exception as error2:
                my_log.log_cohere(f'ai: {error2}\n\n{prompt}\n\n{system}\n\n{mem_}\n{temperature}\n{model_}\n{max_tokens_}\n{key_}\n{key}')
                resp = ''
            if resp:
                if user_id:
                    my_db.add_msg(user_id, model)
                return resp
        return ''
    except Exception as error2:
        error_traceback = traceback.format_exc()
        my_log.log_cohere(f'my_groq:ai: {error2}\n\n{error_traceback}\n\n{prompt}\n\n{system}\n\n{mem_}\n{temperature}\n{model_}\n{max_tokens_}\n{key_}')

    return ''


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
        my_log.log_cohere(f'update_mem: {error}\n\n{error_traceback}\n\n{query}\n\n{resp}\n\n{mem}')

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
        text = ai(query, mem_, user_id=chat_id, temperature = temperature, system=system, model_=model)

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
        my_log.log_cohere(f'force:Failed to force message in chat {chat_id}: {error}\n\n{error_traceback}')


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
        my_log.log_cohere(f'undo: Failed to undo chat {chat_id}: {error}\n\n{error_traceback}')


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
        my_log.log_cohere(f'get_mem_as_string: {error}\n\n{error_traceback}')
        return ''


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
    r = ai(query, temperature=temperature, model_ = model)
    if not r and model == DEFAULT_MODEL:
        r = ai(query, temperature=temperature, model_ = FALLBACK_MODEL)
    return r


if __name__ == '__main__':
    pass

    # r = ai('привет как дела')
    # print(r)

    chat_cli()

    # with open('C:/Users/user/Downloads/2.txt', 'r', encoding='utf-8') as f:
    #     text = f.read()
    # print(sum_big_text(text, 'сделай подробный пересказ по тексту'))
