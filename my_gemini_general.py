import random
import threading
import traceback

from google.ai.generativelanguage_v1beta import types as protos
from sqlitedict import SqliteDict

import cfg
import my_db
import my_log
import utils


# таймаут в запросе к джемини
TIMEOUT = 120

# сколько запросов + ответов помнить
MAX_CHAT_LINES = 30 # 20

# MAX_CHAT_MEM_CHARS = 20000*3 # 20000 токенов по 3 символа на токен. +8000 токенов на ответ остается 4000 токенов на системный промпт и прочее
MAX_CHAT_MEM_CHARS = 60000 # 40000

# сколько символов в запросе
MAX_SUM_REQUEST = 300000 # 200000

LOCKS = {}

# удаленные ключи
REMOVED_KEYS = []


# каждый юзер дает свои ключи и они используются совместно со всеми
# каждый ключ дает всего 50 запросов в день так что чем больше тем лучше
# другие ограничения - 32к токенов в минуту, 2 запроса в минуту
# {full_chat_id as str: list of keys as list of str}
# {'[9123456789] [0]': ['key1','key2','key3'], ...}
USER_KEYS = SqliteDict('db/gemini_user_keys.db', autocommit=True)
# list of all users keys


ALL_KEYS = []
ROUND_ROBIN_KEYS = []

USER_KEYS_LOCK = threading.Lock()


def remove_key(key: str):
    """
    Removes a given key from the ALL_KEYS list and from the USER_KEYS dictionary.

    Args:
        key (str): The key to be removed.

    Returns:
        None
    """
    try:
        if key in ALL_KEYS:
            try:
                ALL_KEYS.remove(key) # Использовать remove для более безопасного удаления из списка
                if key not in REMOVED_KEYS:
                    REMOVED_KEYS.append(key)
            except ValueError:
                my_log.log_keys(f'my_gemini_general.remove_key: Invalid key {key} not found in ALL_KEYS list') # Логировать, если ключ не найден в ALL_KEYS

        users_to_update = [] # Список для хранения пользователей, чьи записи нужно обновить

        with USER_KEYS_LOCK:
            for user in USER_KEYS:
                if key in USER_KEYS[user]:
                    users_to_update.append(user) # Добавить пользователя в список на обновление

            for user in users_to_update: # Выполнить обновление после основной итерации
                USER_KEYS[user] = [x for x in USER_KEYS[user] if x != key] # Обновить список ключей для каждого пользователя
                my_log.log_keys(f'my_gemini_general.remove_key:Invalid key {key} removed from user {user}')

    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_keys(f'my_gemini_general.remove_key:Failed to remove key {key}: {error}\n\n{error_traceback}')


def get_next_key():
    '''
    Дает один ключ из всех, последовательно перебирает доступные ключи
    '''
    global ROUND_ROBIN_KEYS

    if not ROUND_ROBIN_KEYS:
        keys = cfg.gemini_keys[:] + ALL_KEYS[:]
        random.shuffle(keys)
        badkeys = ['b3470eb3b2055346b76f2ce3b11aadf2f6fdccf5703ad853b4a5b0cf46f1cf16',]
        for key in keys[:]:
            if utils.fast_hash(key) in badkeys:
                keys.remove(key)
                remove_key(key)
        ROUND_ROBIN_KEYS = keys[:]

    return ROUND_ROBIN_KEYS.pop(0)


def load_users_keys():
    """
    Load users' keys into memory and update the list of all keys available.
    """
    with USER_KEYS_LOCK:
        for user in USER_KEYS:
            for key in USER_KEYS[user]:
                if key not in ALL_KEYS:
                    ALL_KEYS.append(key)


def transform_mem2(mem):
    '''переделывает словари в объекты, для совместимости, потом надо будет удалить'''
    mem_ = []
    for x in mem:
        if isinstance(x, dict):
            text = x['parts'][0]['text']
            if not text.strip():
                text = '...'
            u = protos.Content(role=x['role'], parts=[protos.Part(text=text)])
            mem_.append(u)
        else:
            # my_log.log_gemini(f'transform_mem2:debug: {type(x)} {str(x)}')
            if not x.parts[0].text.strip():
                x.parts[0].text = '...'
            mem_.append(x)
    return mem_


def get_mem_for_llama(chat_id: str, lines_amount: int = 3, model: str = ''):
    """
    Retrieves the recent chat history for a given chat_id. For using with llama.

    Parameters:
        chat_id (str): The unique identifier for the chat session.
        lines_amount (int, optional): The number of lines to retrieve. Defaults to 3.
        model (str, optional): The name of the model.

    Returns:
        list: The recent chat history as a list of dictionaries with role and content.
    """
    res_mem = []
    lines_amount = lines_amount * 2

    mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_gemini')) or []

    mem = transform_mem2(mem)
    mem = mem[-lines_amount:]

    for x in mem:
        role = x.role
        try:
            if len(x.parts) == 1:
                text = x.parts[0].text.split(']: ', maxsplit=1)[1]
            else:
                text = x.parts[-1].text.split(']: ', maxsplit=1)[1]
        except IndexError:
            if len(x.parts) == 1:
                text = x.parts[0].text
            else:
                text = x.parts[-1].text
        if role == 'user':
            res_mem += [{'role': 'user', 'content': text}]
        else:
            res_mem += [{'role': 'assistant', 'content': text}]

    try:
        res_mem = [x for x in res_mem if x['content']]
    except Exception as error:
        my_log.log_gemini(f'my_gemini_general:get_mem_for_llama: {error}')
        return []

    return res_mem

