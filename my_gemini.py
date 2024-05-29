#!/usr/bin/env python3
# https://ai.google.dev/
# pip install langcodes[data]


import base64
import random
import threading
import time
import requests
import traceback

import langcodes
from sqlitedict import SqliteDict

import cfg
import my_sum
import my_log


# каждый юзер дает свои ключи и они используются совместно со всеми
# каждый ключ дает всего 50 запросов в день так что чем больше тем лучше
# другие ограничения - 32к токенов в минуту, 2 запроса в минуту
# {full_chat_id as str: list of keys as list of str}
# {'[9123456789] [0]': ['key1','key2','key3'], ...}
USER_KEYS = SqliteDict('db/gemini_user_keys.db', autocommit=True)
# list of all users keys
ALL_KEYS = []
USER_KEYS_LOCK = threading.Lock()


# максимальное время для запросов к gemini
TIMEOUT = 120


# блокировка чатов что бы не испортить историю 
# {id:lock}
LOCKS = {}


# не принимать запросы больше чем, это ограничение для телеграм бота, в этом модуле оно не используется
MAX_REQUEST = 25000


# максимальный размер истории (32к ограничение Google?)
# MAX_CHAT_SIZE = 25000
MAX_CHAT_SIZE = 31000
# сколько последних запросов помнить, для экономии токенов
MAX_CHAT_LINES = 40
if hasattr(cfg, 'GEMINI_MAX_CHAT_LINES'):
    MAX_CHAT_LINES = cfg.GEMINI_MAX_CHAT_LINES


# можно сделать 2 запроса по 15000 в сумме получится запрос размером 30000
# может быть полезно для сумморизации текстов
MAX_SUM_REQUEST = 300000
# MAX_SUM_REQUEST = 31000


# хранилище диалогов {id:list(mem)}
CHATS = SqliteDict('db/gemini_dialogs.db', autocommit=True)


# magic string
CANDIDATES = '78fgh892890df@d7gkln2937DHf98723Dgh'


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
            ],
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
                },
            ],
            }

        result = ''
        keys = cfg.gemini_keys[:]  + ALL_KEYS
        random.shuffle(keys)
        keys = keys[:4]

        proxies = cfg.gemini_proxies if hasattr(cfg, 'gemini_proxies') else None
        if proxies:
            random.shuffle(proxies)

        for api_key in keys:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro-vision:generateContent?key={api_key}"

            if proxies:
                for proxy in proxies:
                    session = requests.Session()
                    session.proxies = {"http": proxy, "https": proxy}
                    try:
                        response = session.post(url, json=data, timeout=TIMEOUT).json()
                        if 'promptFeedback' in response and response['promptFeedback']['blockReason']:
                                return ''
                        try:
                            result = response['candidates'][0]['content']['parts'][0]['text']
                            if result == '' or result:
                                return result.strip()
                        except Exception as error_ca:
                            if 'candidates' not in str(error_ca) and 'content' in str(error_ca):
                                my_log.log2(f'my_gemini:img2txt:{error_ca}')
                                return ''
                        if result:
                            break
                        if result == '':
                            break
                    except (requests.exceptions.ProxyError, requests.exceptions.ConnectionError) as error:
                        continue
            else:
                try:
                    response = requests.post(url, json=data, timeout=TIMEOUT).json()
                    if 'promptFeedback' in response and response['promptFeedback']['blockReason']:
                        return ''
                    try:
                        result = response['candidates'][0]['content']['parts'][0]['text']
                        if result == '' or result:
                            return result.strip()
                    except Exception as error_ca:
                        if 'candidates' not in str(error_ca) and 'content' in str(error_ca):
                            my_log.log2(f'my_gemini:img2txt:{error_ca}')
                            return ''
                except Exception as error:
                    if 'content' in str(error):
                        return ''
                    my_log.log2(f'img2txt:{error}')
        return result.strip()
    except Exception as unknown_error:
        if 'content' not in str(unknown_error):
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
    mem = mem[-MAX_CHAT_LINES*2:]
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
        # gemini-1.0-pro
        # gemini-1.0-pro-001
        # gemini-1.0-pro-latest
        # gemini-1.0-pro-vision-latest
        # gemini-1.5-flash-latest
        # gemini-1.5-pro
        # gemini-1.5-pro-latest
        # gemini-pro
        # gemini-pro-vision

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
                },
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
        keys = keys[:4]

    result = ''

    if proxy_str == 'probe':
        proxies = []
    elif proxy_str:
        proxies = [proxy_str, ]
    else:
        proxies = cfg.gemini_proxies if hasattr(cfg, 'gemini_proxies') else None
        if proxies:
            random.shuffle(proxies)

    proxy = ''
    try:
        for key in keys:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

            if proxies:
                for proxy in proxies:
                    session = requests.Session()
                    session.proxies = {"http": proxy, "https": proxy}

                    n = 6
                    c_s = False
                    while n > 0:
                        n -= 1
                        try:
                            response = session.post(url, json=mem_, timeout=TIMEOUT)
                        except (requests.exceptions.ProxyError, requests.exceptions.ConnectionError) as error:
                            c_s = True
                            break
                        if response.status_code == 503 and 'The model is overloaded. Please try again later.' in str(response.text):
                            time.sleep(5)
                        elif response.status_code == 400 and 'API_KEY_INVALID' in str(response.text):
                            remove_key(key)
                            continue
                        elif response.status_code == 400:
                            my_log.log2(f'my_gemini:ai:{proxy} {key} {response.text[:500]}\n\n{q}')
                            return ''
                        else:
                            break
                    if c_s:
                        continue

                    if response.status_code == 200:
                        try:
                            result = response.json()['candidates'][0]['content']['parts'][0]['text']
                        except KeyError:
                            return ''
                        except Exception as error_:
                            if 'candidates' in str(error_):
                                result = CANDIDATES
                        break
                    elif response.status_code == 400 and 'API_KEY_INVALID' in str(response.text):
                        remove_key(key)
                        continue
                    else:
                        my_log.log_gemini(f'my_gemini:ai:{proxy} {key} {response.text[:500]}\n\n{q}')
            else:
                n = 6
                while n > 0:
                    n -= 1
                    response = requests.post(url, json=mem_, timeout=TIMEOUT)
                    if response.status_code == 200:
                        try:
                            result = response.json()['candidates'][0]['content']['parts'][0]['text']
                        except KeyError:
                            return ''
                        except Exception as error_:
                            if 'candidates' in str(error_):
                                result = CANDIDATES
                        break
                    elif response.status_code == 400 and 'API_KEY_INVALID' in str(response.text):
                        remove_key(key)
                        continue
                    elif response.status_code == 400:
                        my_log.log2(f'my_gemini:ai:{proxy} {key} {response.text[:500]}\n\n{q}')
                        return ''
                    else:
                        my_log.log_gemini(f'my_gemini:ai:{key} {response.text[:500]}\n\n{q}')
                        if response.status_code == 503 and 'The model is overloaded. Please try again later.' in str(response.text):
                            time.sleep(5)
                        else:
                            break
            if result:
                break
    except Exception as unknown_error:
        error_traceback = traceback.format_exc()
        my_log.log_gemini(f'my_gemini:ai:{unknown_error}\n\n{error_traceback}')

    try:
        answer = result.strip()
    except:
        return ''

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
        r = ''
        try:
            r = ai(query, mem, temperature, model = model)
        except Exception as error:
            my_log.log_gemini(f'my_gemini:chat:{error}\n\n{query[:500]}')
            time.sleep(5)
            try:
                r = ai(query, mem, temperature, model = model)
            except Exception as error:
                my_log.log_gemini(f'my_gemini:chat:{error}\n\n{query[:500]}')
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


def get_mem_for_llama(chat_id: str, l: int = 3):
    """
    Retrieves the recent chat history for a given chat_id. For using with llama.

    Parameters:
        chat_id (str): The unique identifier for the chat session.
        l (int, optional): The number of lines to retrieve. Defaults to 3.

    Returns:
        list: The recent chat history as a list of dictionaries with role and content.
    """
    global CHATS

    res_mem = []
    l = l*2

    if chat_id not in CHATS:
        CHATS[chat_id] = []
    mem = CHATS[chat_id]
    mem = mem[-l:]

    for x in mem:
        role = x['role']
        try:
            text = x['parts'][0]['text'].split(']: ', maxsplit=1)[1]
        except IndexError:
            text = x['parts'][0]['text']
        if role == 'user':
            res_mem += [{'role': 'user', 'content': text}]
        else:
            res_mem += [{'role': 'assistant', 'content': text}]

    return res_mem


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
        query = f'Translate from language [{from_lang}] to language [{to_lang}], your reply should only be the translated text, this can help you to translate better [{help}]:\n\n{text}'
    else:
        query = f'Translate from language [{from_lang}] to language [{to_lang}], your reply should only be the translated text:\n\n{text}'
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
    text = my_sum.download_text(urls, no_links=True)
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
    return response, text


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
        result = ai('1+1= answer very short', model = 'gemini-1.0-pro', key__=key)
        # result = ai('1+1= answer very short', key__=key)
        if result.strip():
            return True
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log2(f'my_gemini:test_new_key: {error}\n\n{error_traceback}')

    return False


def detect_intent(text: str) -> dict:
    """
    Анализирует последний запрос пользователя и определяет его намерение:
        - хочет ли пользователь сгенерировать изображение,
        - хочет ли пользователь найти ответ в Google,
        - хочет ли пользователь задать вопрос по содержимому ссылки.

    Args:
        text (str): Журнал переписки с пользователем.

    Returns:
        dict: Словарь с ключами 'image', 'google', 'link',
              значения которых (True/False) указывают на наличие соответствующего намерения.
    """
    result = {
        'image':    False, # юзер хочет генерировать изображения
        'google':   False, # юзер хочет искать ответ в гугле
        'link':     False, # юзер хочет задать вопрос по содержимому ссылки
              }

    query = f'''
Определи по журналу чата есть ли у юзера желание выполнить один из 3 сценариев,
1. Юзер хочет генерировать изображения
2. Юзер хочет искать ответ в гугле (надо понять нужно ли гуглить что бы ответить на запрос юзера)
3. Юзер хочет задать вопрос по содержимому ссылки

Анализировать надо последний запрос юзера.

В твоем ответе должны быть только слова из списка (image, google, link)

Журнал переписки:

{text[-10000:]}
'''
    r = ai(query, temperature=0.1, model='gemini-1.5-flash-latest', tokens_limit=100)
    if 'image' in r.lower():
        result['image'] = True
    if 'google' in r.lower():
        result['google'] = True
    if 'link' in r.lower():
        result['link'] = True

    return result


def detect_lang(text: str) -> str:
    q = f'''Detect language of the text, anwser supershort in 1 word iso_code_639_1 like
text = The quick brown fox jumps over the lazy dog.
answer = (en)
text = "Я люблю программировать"
answer = (ru)

Text to be detected: {text[:100]}
'''
    result = ai(q, temperature=0, model='gemini-1.5-flash-latest', tokens_limit=10)
    result = result.replace('"', '').replace(' ', '').replace("'", '').replace('(', '').replace(')', '').strip()
    return result


if __name__ == '__main__':
    load_users_keys()
    # chat_cli()
    # print(ai('1+1= answer very short'))

    # print(img2txt(open('1.jpg', 'rb').read()))
    # print(img2txt(open('2.png', 'rb').read()))
    
    # print(detect_lang('Чудова днина, правда?') )

    print(ai('1+1', model='gemini-1.5-pro'))
