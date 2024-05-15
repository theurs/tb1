#!/usr/bin/env python3
# https://ai.google.dev/
# pip install Proxy-List-Scrapper
# pip install langcodes[data]


import concurrent.futures
import base64
import random
import threading
import time
import requests
import traceback

import langcodes
from sqlitedict import SqliteDict

import cfg
import my_dic
import my_google
import my_log
import my_proxy


STOP_DAEMON = False


# каждый юзер дает свои ключи и они используются совместно со всеми
# каждый ключ дает всего 50 запросов в день так что чем больше тем лучше
# другие ограничения - 32к токенов в минуту, 2 запроса в минуту
# {full_chat_id as str: list of keys as list of str}
# {'[2654672534] [0]': ['key1','key2','key3'], ...}
USER_KEYS = SqliteDict('db/gemini_user_keys.db', autocommit=True)
# list of all users keys
ALL_KEYS = []
USER_KEYS_LOCK = threading.Lock()


# максимальное время для запросов к gemini
TIMEOUT = 120


# блокировка чатов что бы не испортить историю 
# {id:lock}
LOCKS = {}

# memory save lock
SAVE_LOCK = threading.Lock()

# не принимать запросы больше чем, это ограничение для телеграм бота, в этом модуле оно не используется
MAX_REQUEST = 25000

# максимальный размер истории (32к ограничение Google?)
# MAX_CHAT_SIZE = 25000
MAX_CHAT_SIZE = 31000
# сколько последних запросов помнить, для экономии токенов (Должно быть >2 и кратно 2)
# 20 - значит помнить последние 10 запросов и ответов
MAX_CHAT_LINES = 20
if hasattr(cfg, 'GEMINI_MAX_CHAT_LINES'):
    MAX_CHAT_LINES = cfg.GEMINI_MAX_CHAT_LINES

# можно сделать 2 запроса по 15000 в сумме получится запрос размером 30000
# может быть полезно для сумморизации текстов
MAX_SUM_REQUEST = 150000
# MAX_SUM_REQUEST = 31000

# хранилище диалогов {id:list(mem)}
CHATS = SqliteDict('db/gemini_dialogs.db', autocommit=True)

# magic string
CANDIDATES = '78fgh892890df@d7gkln2937DHf98723Dgh'


##################################################################################
# If no proxies are specified in the config, then we first try to work directly
# and if that doesn't work, we start looking for free proxies using
# a constantly running daemon
PROXY_POOL = my_dic.PersistentList('db/gemini_proxy_pool_v2.pkl')
PROXY_POLL_SPEED = SqliteDict('db/gemini_proxy_pool_speed_v2.pkl')
# PROXY_POOL_REMOVED = my_dic.PersistentList('db/gemini_proxy_pool_removed_v2.pkl')
PROXY_POOL_REMOVED = [] # не надо наверное помнить всегда все удаленные прокси

# искать и добавлять прокси пока не найдется хотя бы 10 проксей
MAX_PROXY_POOL = 10
# начинать повторный поиск если осталось всего 5 проксей
MAX_PROXY_POOL_LOW_MARGIN = 5

SAVE_LOCK = threading.Lock()
POOL_MAX_WORKERS = 50
##################################################################################


def img2txt(data_: bytes, prompt: str = "Что на картинке, подробно?") -> str:
    """
    Generates a textual description of an image based on its contents.

    Args:
        data_: The image data as bytes.
        prompt: The prompt to provide for generating the description. Defaults to "Что на картинке, подробно?".

    Returns:
        A textual description of the image.

    Raises:
        None.
    """
    global PROXY_POOL
    try:
        img_data = base64.b64encode(data_).decode("utf-8")
        data = {
            "contents": [
                {
                "parts": [
                    {"text": prompt},
                    {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": img_data
                    }
                    }
                ]
                }
            ]
            }

        result = ''
        keys = cfg.gemini_keys[:]  + ALL_KEYS
        random.shuffle(keys)

        proxies = PROXY_POOL[:]
        random.shuffle(proxies)

        for api_key in keys:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro-vision:generateContent?key={api_key}"

            if proxies:
                sort_proxies_by_speed(proxies)
                for proxy in proxies:
                    start_time = time.time()
                    session = requests.Session()
                    session.proxies = {"http": proxy, "https": proxy}
                    try:
                        response = session.post(url, json=data, timeout=TIMEOUT).json()
                        try:
                            result = response['candidates'][0]['content']['parts'][0]['text']
                            if result == '' or result:
                                return result.strip()
                        except Exception as error_ca:
                            if 'candidates' in str(error_ca) or 'content' in str(error_ca):
                                my_log.log2(f'my_gemini:img2txt:{error_ca}')
                                return ''
                        if result:
                            end_time = time.time()
                            total_time = end_time - start_time
                            if total_time > 45:
                                remove_proxy(proxy)
                            break
                        if result == '':
                            break
                    except (requests.exceptions.ProxyError, requests.exceptions.ConnectionError) as error:
                        remove_proxy(proxy)
                        continue
            else:
                try:
                    response = requests.post(url, json=data, timeout=TIMEOUT).json()
                    try:
                        result = response['candidates'][0]['content']['parts'][0]['text']
                        if result == '' or result:
                            return result.strip()
                    except Exception as error_ca:
                        if 'candidates' in str(error_ca) or 'content' in str(error_ca):
                            my_log.log2(f'my_gemini:img2txt:{error_ca}')
                            return ''
                except Exception as error:
                    if 'content' in str(error):
                        return ''
                    my_log.log2(f'img2txt:{error}')
        return result.strip()
    except Exception as unknown_error:
        if 'content' not in str(error):
            my_log.log2(f'my_gemini:img2txt:{unknown_error}')
        return ''


def update_mem(query: str, resp: str, mem):
    """
    Update the memory with the given query and response.

    Parameters:
        query (str): The input query.
        resp (str): The response to the query.
        mem: The memory object to update, if str than mem is a chat_id

    Returns:
        list: The updated memory object.
    """
    global CHATS
    chat_id = ''
    if isinstance(mem, str): # if mem - chat_id
        chat_id = mem
        if mem not in CHATS:
            CHATS[mem] = []
        mem = CHATS[mem]

    mem.append({"role": "user", "parts": [{"text": query}]})
    mem.append({"role": "model", "parts": [{"text": resp}]})
    size = 0
    for x in mem:
        text = x['parts'][0]['text']
        size += len(text)
    while size > MAX_CHAT_SIZE:
        mem = mem[2:]
        size = 0
        for x in mem:
            text = x['parts'][0]['text']
            size += len(text)
    mem = mem[-MAX_CHAT_LINES:]
    if chat_id:
        CHATS[chat_id] = mem
    return mem


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
        global LOCKS, CHATS

        if chat_id in LOCKS:
            lock = LOCKS[chat_id]
        else:
            lock = threading.Lock()
            LOCKS[chat_id] = lock
        with lock:
            if chat_id in CHATS:
                mem = CHATS[chat_id]
                # remove 2 last lines from mem
                mem = mem[:-2]
                CHATS[chat_id] = mem
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_gemini(f'Failed to undo chat {chat_id}: {error}\n\n{error_traceback}')


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
            del ALL_KEYS[ALL_KEYS.index(key)]
        with USER_KEYS_LOCK:
            # remove key from USER_KEYS
            for user in USER_KEYS:
                if key in USER_KEYS[user]:
                    USER_KEYS[user] = [x for x in USER_KEYS[user] if x != key]
                    my_log.log_gemini(f'Invalid key {key} removed from user {user}')
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_gemini(f'Failed to remove key {key}: {error}\n\n{error_traceback}')


def ai(q: str, mem = [],
       temperature: float = 0.1,
       proxy_str: str = '',
       model: str = '',
       key__: str = None,
       tokens_limit: int = 8000) -> str:
    """
    Generates a response to a given question using the Generative AI model.
    
    Args:
        q (str): The question to be answered.
        mem (list, optional): The memory to be used for generating the response. Defaults to [].
        temperature (float, optional): The temperature parameter for the model. Defaults to 0.1.
        proxy_str (str, optional): The proxy to be used for the request. Defaults to ''.
        model (str, optional): The model to be used for generating the response. Defaults to ''.
        key__ (str, optional): The API key to be used for the request. Defaults to None.
        
    Returns:
        str: The generated response to the question.
        
    Raises:
        Exception: If an error occurs during the request or response handling.
    """
    if model == '':
        model = 'gemini-1.5-flash-latest'
        # models/gemini-1.0-pro
        # models/gemini-1.0-pro-001
        # models/gemini-1.0-pro-latest
        # models/gemini-1.0-pro-vision-latest
        # models/gemini-1.5-flash-latest
        # models/gemini-1.5-pro-latest
        # models/gemini-pro
        # models/gemini-pro-vision
    global PROXY_POOL, PROXY_POLL_SPEED
    # bugfix температура на самом деле от 0 до 1 а не от 0 до 2
    temperature = round(temperature / 2, 2)

    mem_ = {"contents": mem + [{"role": "user", "parts": [{"text": q}]}],
            "safetySettings": [
                {
                    "category": "HARM_CATEGORY_HARASSMENT",
                    "threshold": "BLOCK_NONE"
                },
                {
                    "category": "HARM_CATEGORY_HATE_SPEECH",
                    "threshold": "BLOCK_NONE"
                },
                {
                    "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "threshold": "BLOCK_NONE"
                },
                {
                    "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                    "threshold": "BLOCK_NONE"
                }
            ],
            "generationConfig": {
                # "stopSequences": [
                #     "Title"
                # ],
                "temperature": temperature,
                "maxOutputTokens": tokens_limit,
                # "topP": 0.8,
                # "topK": 10
                }
            }

    if key__:
        keys = [key__, ]
    else:
        keys = cfg.gemini_keys[:] + ALL_KEYS
        random.shuffle(keys)

    result = ''

    if proxy_str == 'probe':
        proxies = []
    elif proxy_str:
        proxies = [proxy_str, ]
    else:
        proxies = PROXY_POOL[:]
        random.shuffle(proxies)

    proxy = ''
    try:
        for key in keys:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

            if proxies:
                sort_proxies_by_speed(proxies)
                for proxy in proxies:
                    start_time = time.time()
                    session = requests.Session()
                    session.proxies = {"http": proxy, "https": proxy}

                    n = 6
                    c_s = False
                    while n > 0:
                        n -= 1
                        try:
                            response = session.post(url, json=mem_, timeout=TIMEOUT)
                        except (requests.exceptions.ProxyError, requests.exceptions.ConnectionError) as error:
                            remove_proxy(proxy)
                            c_s = True
                            break
                        if response.status_code == 503 and 'The model is overloaded. Please try again later.' in str(response.text):
                            time.sleep(5)
                        else:
                            break
                    if c_s:
                        continue

                    if response.status_code == 200:
                        try:
                            result = response.json()['candidates'][0]['content']['parts'][0]['text']
                        except Exception as error_:
                            if 'candidates' in str(error_):
                                result = CANDIDATES
                        end_time = time.time()
                        total_time = end_time - start_time
                        if total_time > 50:
                            remove_proxy(proxy)
                        else:
                            PROXY_POLL_SPEED[proxy] = total_time
                        break
                    elif response.status_code == 400 and 'API_KEY_INVALID' in str(response.text):
                        remove_key(key)
                        continue
                    else:
                        remove_proxy(proxy)
                        my_log.log_gemini(f'my_gemini:ai:{proxy} {key} {str(response)} {response.text[:10000]}\n\n{q}')
            else:
                n = 6
                while n > 0:
                    n -= 1
                    response = requests.post(url, json=mem_, timeout=TIMEOUT)
                    if response.status_code == 200:
                        try:
                            result = response.json()['candidates'][0]['content']['parts'][0]['text']
                        except Exception as error_:
                            if 'candidates' in str(error_):
                                result = CANDIDATES
                        break
                    elif response.status_code == 400 and 'API_KEY_INVALID' in str(response.text):
                        remove_key(key)
                        continue
                    else:
                        my_log.log_gemini(f'my_gemini:ai:{key} {str(response)} {response.text[:10000]}\n\n{q}')
                        if response.status_code == 503 and 'The model is overloaded. Please try again later.' in str(response.text):
                            time.sleep(5)
                        else:
                            break
            if result:
                break
    except Exception as unknown_error:
        error_traceback = traceback.format_exc()
        my_log.log_gemini(f'my_gemini:ai:{unknown_error}\n\n{error_traceback}')

    answer = result.strip()
    if not answer and model == 'gemini-1.5-pro-latest':
        answer = ai(q, mem, temperature, proxy_str, 'gemini-1.0-pro-latest')

    if answer.startswith('[Info to help you answer.'):
        pos = answer.find('"]')
        answer = answer[pos + 2:]
    if answer == CANDIDATES:
        return ''
    return answer


def get_models() -> str:
    """some error, return 404"""
    global PROXY_POOL
    keys = cfg.gemini_keys[:]
    random.shuffle(keys)
    result = ''

    proxies = PROXY_POOL[:] + ALL_KEYS
    random.shuffle(proxies)

    proxy = ''
    try:
        for key in keys:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro?key={key}"

            if proxies:
                sort_proxies_by_speed(proxies)
                for proxy in proxies:
                    session = requests.Session()
                    session.proxies = {"http": proxy, "https": proxy}
                    try:
                        response = session.post(url, timeout=TIMEOUT)
                    except (requests.exceptions.ProxyError, requests.exceptions.ConnectionError) as error:
                        continue

                    if response.status_code == 200:
                        result = response.json()###################
                        break
                    else:
                        remove_proxy(proxy)
                        my_log.log2(f'my_gemini:get_models:{proxy} {key} {str(response)} {response.text}')
            else:
                response = requests.post(url, timeout=TIMEOUT)
                if response.status_code == 200:
                    result = response.json()###############
                else:
                    my_log.log2(f'my_gemini:get_models:{key} {str(response)} {response.text}')

            if result:
                break
    except Exception as unknown_error:
        my_log.log2(f'my_gemini:get_models:{unknown_error}')

    return result.strip()


def chat(query: str, chat_id: str, temperature: float = 0.1, update_memory: bool = True, model: str = '') -> str:
    """
    A function that facilitates a chatbot conversation given a query, chat ID, and optional parameters. 
    Utilizes a global locks and chats dictionary to keep track of chat sessions. 
    Returns the response generated by the chatbot.
    Parameters:
        query (str): The input query for the chatbot.
        chat_id (str): The unique identifier for the chat session.
        temperature (float, optional): The temperature parameter for text generation.
        update_memory (bool, optional): Flag indicating whether to update the chat memory.
        model (str, optional): The model to use for generating responses.
    Returns:
        str: The response generated by the chatbot.
    """
    global LOCKS, CHATS
    if chat_id in LOCKS:
        lock = LOCKS[chat_id]
    else:
        lock = threading.Lock()
        LOCKS[chat_id] = lock
    with lock:
        if chat_id not in CHATS:
            CHATS[chat_id] = []
        mem = CHATS[chat_id]
        r = ai(query, mem, temperature, model = model)
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
    global CHATS
    CHATS[chat_id] = []


def get_mem_as_string(chat_id: str) -> str:
    """
    Returns the chat history as a string for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to get the history for.

    Returns:
        str: The chat history as a string.
    """
    global CHATS
    if chat_id not in CHATS:
        CHATS[chat_id] = []
    mem = CHATS[chat_id]
    result = ''
    for x in mem:
        role = x['role']
        if role == 'user': role = '𝐔𝐒𝐄𝐑'
        if role == 'model': role = '𝐁𝐎𝐓'
        try:
            text = x['parts'][0]['text'].split(']: ', maxsplit=1)[1]
        except IndexError:
            text = x['parts'][0]['text']
        if text.startswith('[Info to help you answer'):
            end = text.find(']') + 1
            text = text[end:].strip()
        result += f'{role}: {text}\n'
        if role == '𝐁𝐎𝐓':
            result += '\n'
    return result    


def translate(text: str, from_lang: str = '', to_lang: str = '', help: str = '') -> str:
    """
    Translates the given text from one language to another.
    
    Args:
        text (str): The text to be translated.
        from_lang (str, optional): The language of the input text. If not specified, the language will be automatically detected.
        to_lang (str, optional): The language to translate the text into. If not specified, the text will be translated into Russian.
        help (str, optional): Help text for tranlator.
        
    Returns:
        str: The translated text.
    """
    if from_lang == '':
        from_lang = 'autodetect'
    if to_lang == '':
        to_lang = 'ru'
    try:
        from_lang = langcodes.Language.make(language=from_lang).display_name(language='en') if from_lang != 'autodetect' else 'autodetect'
    except Exception as error1:
        error_traceback = traceback.format_exc()
        my_log.log_translate(f'my_gemini:translate:error1: {error1}\n\n{error_traceback}')
        
    try:
        to_lang = langcodes.Language.make(language=to_lang).display_name(language='en')
    except Exception as error2:
        error_traceback = traceback.format_exc()
        my_log.log_translate(f'my_gemini:translate:error2: {error2}\n\n{error_traceback}')

    if help:
        query = f'Translate from language [{from_lang}] to language [{to_lang}], this can help you to translate better [{help}]:\n\n{text}'
    else:
        query = f'Translate from language [{from_lang}] to language [{to_lang}]:\n\n{text}'
    # inject_explicit_content(chat_id)
    translated = ai(query, temperature=0.1)
    return translated


def chat_cli():
    # inject_explicit_content('test')
    # style = '[пиши грубо с матами как троль в интернете]'
    # style = '[ты работаешь в сексе по телефону и твоя задача доставить клиенту сексуальное удовольствие]'
    # style = '[пиши так будто ты немец который плохо знает русский язык, вставляй иногда оригинальные немецкие слова, пиши по-русски с ошибками характерными для немцев]'
    style = ''
    while 1:
        q = input('>')
        if q == 'mem':
            print(get_mem_as_string('test'))
            continue
        r = chat(f'{style} {q}', 'test')
        print(r)


def check_phone_number(number: str) -> str:
    """проверяет чей номер, откуда звонили"""
    urls = [
        f'https://zvonili.com/phone/{number}',
        # этот сайт похоже тупо врёт обо всех номерах f'https://abonentik.ru/7{number}',
        f'https://www.list-org.com/search?type=phone&val=%2B7{number}'
    ]
    text = my_google.download_text(urls, no_links=True)
    query = f'''
Определи по тексту какой регион, какой оператор, и не связан ли он с мошенничеством,
ответь в удобной для чтения форме с разделением на абзацы и с использованием
жирного текста для акцентирования внимания,
ответь кратко, но если связано с мошенничеством то напиши почему ты так решил подробно.

Номер +7{number}

Текст:

{text}
'''
    response = ai(query)
    return response


def remove_proxy(proxy: str):
    """
    Remove a proxy from the proxy pool and add it to the removed proxy pool.

    Args:
        proxy (str): The proxy to be removed.

    Returns:
        None
    """
    global PROXY_POOL, PROXY_POOL_REMOVED
    # не удалять прокси из конфига
    try:
        if proxy in cfg.gemini_proxies:
            return
    except AttributeError:
        pass

    PROXY_POOL.remove_all(proxy)

    PROXY_POOL_REMOVED.append(proxy)
    try:
        PROXY_POOL_REMOVED.deduplicate()
    except: # это обычный список а не постоянный, у него нет такого метода
        PROXY_POOL_REMOVED = list(set(PROXY_POOL_REMOVED))


def sort_proxies_by_speed(proxies):
    """
    Sort proxies by speed.

    Args:
        proxies (list): The list of proxies to be sorted.

    Returns:
        list: The sorted list of proxies.
    """
    global PROXY_POOL, PROXY_POLL_SPEED
    # неопробованные прокси считаем что имеют скорость как было при поиске = 5 секунд(или менее)
    for x in PROXY_POOL:
        if x not in PROXY_POLL_SPEED:
            PROXY_POLL_SPEED[x] = 5

    try:
        proxies.sort(key=lambda x: PROXY_POLL_SPEED[x])
    except KeyError as key_error:
        # my_log.log2(f'sort_proxies_by_speed: {key_error}')
        pass


def test_proxy_for_gemini(proxy: str = '') -> bool:
    """
    A function that tests a proxy for the Gemini API.

    Parameters:
        proxy (str): The proxy to be tested (default is an empty string).

    Returns:
        Если proxy = '', то проверяем работу напрямую и отвечает True/False.
        Если proxy != '', то заполняем пул новыми проксями.

    Description:
        This function tests a given proxy for the Gemini API by sending a query to the AI
        with the specified proxy. The query is set to '1+1= answer very short'. The function
        measures the time it takes to get an answer from the AI and stores it in the variable
        'total_time'. If the proxy parameter is not provided, the function checks if the answer
        from the AI is True. If it is, the function returns True, otherwise it returns False.
        If the proxy parameter is provided and the answer from the AI is not in the list
        'PROXY_POOL_REMOVED', and the total time is less than 5 seconds, the proxy is added
        to the 'PROXY_POOL' list.

    Note:
        - The 'ai' function is assumed to be defined elsewhere in the code.
        - The 'PROXY_POOL_REMOVED' and 'PROXY_POOL' variables are assumed to be defined elsewhere in the code.
        - The 'time' module is assumed to be imported.
    """
    global PROXY_POOL, PROXY_POOL_REMOVED, PROXY_POLL_SPEED
    query = '1+1= answer very short'
    start_time = time.time()
    answer = ai(query, proxy_str=proxy or 'probe')
    total_time = time.time() - start_time

    # если проверяем работу напрямую то нужен ответ - True/False
    if not proxy:
        if answer:
            return True
        else:
            return False
    # если с прокси то ответ не нужен
    else:
        if answer and answer not in PROXY_POOL_REMOVED:
            if total_time < 5:
                PROXY_POOL.append(proxy)
                PROXY_POLL_SPEED[proxy] = total_time


def get_proxies():
    """
        Retrieves a list of proxies and tests them for usability.

        Returns:
            None
    """
    global PROXY_POOL
    try:
        proxies = my_proxy.get_proxies()

        n = 0
        maxn = len(proxies)
        step = POOL_MAX_WORKERS

        while n < maxn:
            if len(PROXY_POOL) > MAX_PROXY_POOL:
                break
            if len(PROXY_POOL) == 0:
                step = 500
            else:
                step = POOL_MAX_WORKERS
            chunk = proxies[n:n+step]
            n += step
            print(f'Proxies found: {len(PROXY_POOL)} (processing {n} of {maxn})')
            with concurrent.futures.ThreadPoolExecutor(max_workers=step) as executor:
                futures = [executor.submit(test_proxy_for_gemini, proxy) for proxy in chunk]
                for future in futures:
                    future.result()

    except Exception as error:
        my_log.log2(f'my_gemini:get_proxies: {error}')


def update_proxy_pool_daemon():
    """
        Update the proxy pool daemon.

        This function continuously updates the global `PROXY_POOL` list with new proxies.
        It ensures that the number of proxies in the pool is maintained below the maximum
        limit specified by the `MAX_PROXY_POOL` constant.

        Parameters:
        None

        Returns:
        None
    """
    global PROXY_POOL
    while not STOP_DAEMON:
        if len(PROXY_POOL) < MAX_PROXY_POOL_LOW_MARGIN:
                get_proxies()
                PROXY_POOL.deduplicate()
                time.sleep(60*60)
        else:
            time.sleep(2)


def load_users_keys():
    """
    Load users' keys into memory and update the list of all keys available.
    """
    with USER_KEYS_LOCK:
        global USER_KEYS, ALL_KEYS
        for user in USER_KEYS:
            for key in USER_KEYS[user]:
                if key not in ALL_KEYS:
                    ALL_KEYS.append(key)


def run_proxy_pool_daemon():
    """
    Run the proxy pool daemon.

    This function checks if there are any proxies available. If there are no proxies,
    it checks if direct connection to the server is possible. If direct connection is
    not available, the function logs a message indicating that direct connection is
    unavailable.

    If there are proxies available, the proxy pool is recreated with the provided
    proxies.

    If the proxy pool is empty and direct connection is not available, a new thread is
    started to update the proxy pool. The function waits until at least 1 proxy is
    found before returning.

    Parameters:
    None

    Returns:
    None
    """

    # сначала загрузить ключи юзеров
    load_users_keys()


    global PROXY_POOL
    try:
        proxies = cfg.gemini_proxies
    except AttributeError:
        proxies = []

    # если проксей нет то проверяем возможна ли работа напрямую
    if not proxies:
        direct_connect_available = test_proxy_for_gemini()
        # вторая попытка
        if not direct_connect_available:
            time.sleep(2)
            direct_connect_available = test_proxy_for_gemini()
            if not direct_connect_available:
                my_log.log2('proxy:run_proxy_pool_daemon: direct connect unavailable')
    else:
        PROXY_POOL.recreate(proxies)

    if not proxies and not direct_connect_available:
        thread = threading.Thread(target=update_proxy_pool_daemon)
        thread.start()
        # # Waiting until at least 1 proxy is found
        # while len(PROXY_POOL) < 1:
        #     time.sleep(1)


def sum_big_text(text:str, query: str, temperature: float = 0.1) -> str:
    """
    Generates a response from an AI model based on a given text,
    query, and temperature. Split big text into chunks of 15000 characters.
    Up to 30000 characters.

    Args:
        text (str): The complete text to be used as input.
        query (str): The query to be used for generating the response.
        temperature (float, optional): The temperature parameter for controlling the randomness of the response. Defaults to 0.1.

    Returns:
        str: The generated response from the AI model.
    """
    query = f'''{query}\n\n{text[:MAX_SUM_REQUEST]}'''
    # t1 = text[:int(MAX_SUM_REQUEST/2)]
    # t2 = text[int(MAX_SUM_REQUEST/2):MAX_SUM_REQUEST] if len(text) > int(MAX_SUM_REQUEST/2) else ''
    # mem = []
    # if t2:
    #     mem.append({"role": "user", "parts": [{"text": f'Dont answer before get part 2 and question.\n\nPart 1:\n\n{t1}'}]})
    #     mem.append({"role": "model", "parts": [{"text": 'Ok.'}]})
    #     mem.append({"role": "user", "parts": [{"text": f'Part 2:\n\n{t2}'}]})
    #     mem.append({"role": "model", "parts": [{"text": 'Ok.'}]})
    # else:
    #     mem.append({"role": "user", "parts": [{"text": f'Dont answer before get part 1 and question.\n\nPart 1:\n\n{t1}'}]})
    #     mem.append({"role": "model", "parts": [{"text": 'Ok.'}]})

    # return ai(query, mem=mem, temperature=temperature)
    return ai(query, temperature=temperature, model='gemini-1.5-flash-latest')


def repair_text_after_speech_to_text(text: str) -> str:
    """
    Repairs the given text after speech-to-text conversion.

    Args:
        text (str): The input text to be repaired.

    Returns:
        str: The repaired text after speech-to-text conversion.
    """
    if len(text) > 5000:
        return text
    query1 = f"Anwser super short if this text has any content you can't work with, yes or no:\n\n{text}"
    r1 = ai(query1).lower()
    if r1 and 'no' in r1:
        query2 = f"Repair this text after speech-to-text conversion:\n\n{text}"
        r2 = ai(query2, temperature=0.1)
        if r2:
            return r2
    return text


def test_new_key(key: str) -> bool:
    """
    Test if a new key is valid.

    Args:
        key (str): The key to be tested.

    Returns:
        bool: True if the key is valid, False otherwise.
    """
    try:
        result = ai('1+1= answer very short', model = 'gemini-1.0-pro-latest', key__=key)
        # result = ai('1+1= answer very short', key__=key)
        if result.strip():
            return True
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log2(f'my_gemini:test_new_key: {error}\n\n{error_traceback}')

    return False


def detect_intent(text: str) -> str:
    pass


if __name__ == '__main__':

    run_proxy_pool_daemon()

    # print(sum_big_text(open('1.txt', 'r', encoding='utf-8').read(), 'Перескажи кратко о чем этот текст, уложись в 1000 слов'))

    # print(get_models())

    chat_cli()

    # for _ in range(100):
    #     t1 = time.time()
    #     r = ai('напиши рассказ про слона 4000 слов', temperature=1, model='gemini-1.5-flash-latest')
    #     t2 = time.time()
    #     print(len(r), round(t2 - t1, 2), f'{r[:20]}...{r[-20:]}'.replace('\n', ' '))

    # print(test_new_key('123'))

    # print(translate('مرحبا', to_lang='nl'))
    # print(translate('Γεια σας', 'el', 'pt'))
    # print(translate('Голос: Ynd муж.', to_lang='en', help = 'это текст на кнопке, он должен быть коротким что бы уместится на кнопке по-этому сокращен, полный текст - Голос: Yandex мужской, тут имеется в виду мужской голос для TTS от яндекса'))
    # print(translate('', to_lang='en'))
    # print(translate('', to_lang='en', help=''))

    # data = open('1.jpg', 'rb').read()
    # print(img2txt(data))
