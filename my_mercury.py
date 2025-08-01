#!/usr/bin/env python3
# pip install -U mistralai pysrt


import time
import threading

import traceback

import openai

import cfg
import my_db
import my_log
# import my_skills_general
import utils


BASE_URL = 'https://api.inceptionlabs.ai/v1'


#
# память диалога храниться в базе openrouter тк совместима с ним
#
#

# сколько запросов хранить
MAX_MEM_LINES = 20
MAX_HIST_CHARS = 50000


# блокировка чатов что бы не испортить историю
# {id:lock}
LOCKS = {}


# не принимать запросы больше чем, это ограничение для телеграм бота, в этом модуле оно не используется
MAX_REQUEST = 40000


# максимальный размер суммаризации
MAX_SUM_REQUEST = 200000 # 128k tokens
# MAX_SUM_REQUEST = 100000


DEFAULT_MODEL = 'mercury'
FALLBACK_MODEL = 'mercury-small'
CODE_MODEL = 'mercury-coder'
FALLBACK_CODE_MODEL = 'mercury-coder-small'


CURRENT_KEYS_SET = []


def get_next_key() -> str:
    '''
    Return round robin key from cfg.MERCURY_KEYS
    '''
    global CURRENT_KEYS_SET
    if not CURRENT_KEYS_SET:
        if not hasattr(cfg, 'MERCURY_KEYS') or not cfg.MERCURY_KEYS:
            raise Exception('cfg.MERCURY_KEYS is empty')
        CURRENT_KEYS_SET = cfg.MERCURY_KEYS[:]

    if CURRENT_KEYS_SET:
        return CURRENT_KEYS_SET.pop(0)
    else:
        raise Exception('cfg.MERCURY_KEYS is empty')


def ai(
    prompt: str = '',
    mem = None,
    user_id: str = '',
    system: str = '',
    model = '',
    temperature: float = 1,
    max_tokens: int = 16000,
    timeout: int = 60,
    key_: str = '',
    json_output: bool = False,
    use_skills: bool = False
    ) -> str:


    # не реализовано тут пока
    use_skills = False


    if not len(cfg.MERCURY_KEYS) and not key_:
        return ''

    if not model:
        model = DEFAULT_MODEL

    messages = list(mem) if mem is not None else []

    # Системные промпты (без изменений)
    now = utils.get_full_time()
    systems = (
        f'Current date and time: {now}\n',
        f'Telegram user id you talking with: {user_id}\n',
        'Ask again if something is unclear in the request\n',
        'You (assistant) are currently working in a Telegram bot. The Telegram bot automatically extracts text from any type of files sent to you by the user, such as documents, images, audio recordings, etc., so that you can fully work with any files.\n',
        "If the user's request cannot be fulfilled using the available tools or direct actions, the assistant(you) must treat the request as a request to generate text (e.g., providing code as text), not a request to perform an action (e.g., executing code or interacting with external systems not directly supported by tools) (intention mismatch).\n",
        "To edit image user can send image with caption starting ! symbol\n",
    )

    if system:
        messages.insert(0, {"role": "system", "content": system})
    for s in reversed(systems):
        messages.insert(0, {"role": "system", "content": s})
    if prompt:
        messages.append({"role": "user", "content": prompt})

    text = ''
    key = ''
    start_time = time.time()

    # Внешний цикл для повторных попыток при ошибках сети
    for _ in range(3):
        time_left = timeout - (time.time() - start_time)
        if time_left <= 0:
            my_log.log_mercury(f'ai:0: timeout | {key} | {user_id}\n\n{model}\n\n{prompt}')
            break

        try:
            key = get_next_key() if not key_ else key_
            client = openai.OpenAI(api_key=key, base_url=BASE_URL)

            for _ in range(3):

                api_params = {
                    'model': model,
                    'messages': messages,
                    'temperature': int(temperature/2),
                    'max_tokens': max_tokens,
                    'timeout': int(time_left),
                }

                if json_output:
                    api_params['response_format'] = {"type": "json_object"}

                response = client.chat.completions.create(**api_params)
                response_message = response.choices[0].message

                text = response_message.content.strip() if response_message.content else ''
                break

            if text:
                if user_id:
                    my_db.add_msg(user_id, model)
                break  # Выходим из внешнего цикла повторных попыток

            # Если вышли из цикла по лимиту шагов, а текста нет
            if not text:
                 my_log.log_mercury(f'ai: Exceeded max tool steps (3) | {key} | {user_id}')
                 break # Прерываем попытки

        except Exception as error2:
            if 'You exceeded the maximum context length' in str(error2):
                messages = [msg for msg in messages if msg['role'] == 'system']
                messages += (mem or [])[-4:] # Берем только последние сообщения
                if prompt: messages.append({"role": "user", "content": prompt})
                continue # Повторяем попытку с урезанной историей
            if 'Unauthorized' in str(error2):
                remove_key(key)
                my_log.log_mercury(f'ai:2: {error2} | {key} | {user_id}')
            my_log.log_mercury(f'ai:3: {error2} | {key} | {user_id}\n\n{model}\n\n{prompt}')
            time.sleep(2)

    # Вызов резервной модели, если основная не справилась
    if not text and model == DEFAULT_MODEL:
        # Убедимся, что не передаем историю с вызовами инструментов в резервную модель
        final_mem = list(mem) if mem is not None else []
        return ai(prompt, final_mem, user_id, system, FALLBACK_MODEL, temperature, max_tokens, time_left, key_, json_output)

    return text


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
        my_log.log_mercury(f'update_mem: {error}\n\n{error_traceback}\n\n{query}\n\n{resp}\n\n{mem}')

    my_db.set_user_property(chat_id, 'dialog_openrouter', my_db.obj_to_blob(mem__))


def chat(
    query: str,
    chat_id: str = '',
    temperature: float = 1,
    system: str = '',
    model: str = '',
    do_not_update_history: bool = False,
    timeout: int = 120,
    use_skills: bool = False
    ) -> str:
    global LOCKS
    if chat_id in LOCKS:
        lock = LOCKS[chat_id]
    else:
        lock = threading.Lock()
        LOCKS[chat_id] = lock
    with lock:
        mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_openrouter')) or []

        mem_ = mem[:]
        text = ai(query, mem_, user_id=chat_id, temperature = temperature, system=system, model=model, timeout=timeout, use_skills=use_skills)

        if text and not do_not_update_history:
            mem += [{'role': 'user', 'content': query}]
            mem += [{'role': 'assistant', 'content': text}]
            mem = clear_mem(mem, chat_id)
            my_db.set_user_property(chat_id, 'dialog_openrouter', my_db.obj_to_blob(mem))
        return text
    return ''


def chat_cli(model: str = ''):
    reset('test')
    while 1:
        q = input('>')
        if q == 'mem':
            print(get_mem_as_string('test'))
            continue
        r = chat(q, 'test', model = model, system='отвечай всегда по-русски', use_skills = True)
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
        my_log.log_mercury(f'force:Failed to force message in chat {chat_id}: {error}\n\n{error_traceback}')


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
        my_log.log_mercury(f'undo: Failed to undo chat {chat_id}: {error}\n\n{error_traceback}')


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
        my_log.log_mercury(f'get_mem_as_string: {error}\n\n{error_traceback}')
        return ''


def remove_key(key: str):
    '''Removes a given key from the cfg.MERCURY_KEYS list and from the USER_KEYS dictionary.'''
    try:
        if not key:
            return
        if key in cfg.MERCURY_KEYS:
            try:
                cfg.MERCURY_KEYS.remove(key)
            except ValueError:
                my_log.log_keys(f'remove_key: Invalid key {key} not found in cfg.MERCURY_KEYS list')

    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_mercury(f'remove_key: Failed to remove key {key}: {error}\n\n{error_traceback}')


def sum_big_text(text:str, query: str, temperature: float = 0.2, model = DEFAULT_MODEL) -> str:
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
        temperature=0.7,
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
                my_log.log_reprompt_moderation(f'MODERATION image reprompt failed: {prompt}')
        if 'moderation_hate' in result_dict:
            moderation_hate = result_dict['moderation_hate']
            if moderation_hate:
                my_log.log_reprompt_moderation(f'MODERATION image reprompt failed: {prompt}')

        if reprompt and negative_prompt:
            return reprompt, negative_prompt, moderation_sexual, moderation_hate
    return None


if __name__ == '__main__':
    pass
    my_db.init(backup=False)

    print(ai('сделай хороший перевод на английский этого текста:\n\n"Привет, как дела?"'))


    # with open(r'C:\Users\user\Downloads\samples for ai\myachev_Significant_Digits_-_znachaschie_tsifryi_106746.txt', 'r', encoding='utf-8', errors='ignore') as f:
    #     text = f.read()
    # print(sum_big_text(text, 'сделай подробный пересказ по тексту, по-русски'))


    chat_cli()

    my_db.close()
