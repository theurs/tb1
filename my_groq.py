#!/usr/bin/env python3
# install from PyPI
# pip install groq

import base64
import cachetools.func
import random
import re
import requests
import time
import threading
import traceback
from typing import Union

import httpx
from groq import Groq, PermissionDeniedError
from sqlitedict import SqliteDict

import cfg
import my_db
import my_log
import my_skills
import my_skills_storage
import my_sum
import utils


# каждый юзер дает свои ключи и они используются совместно со всеми
# каждый ключ дает всего 6000 токенов в минуту для ллама3 так что чем больше тем лучше
# {full_chat_id as str: key}
# {'[9123456789] [0]': 'key', ...}
USER_KEYS = SqliteDict('db/groq_user_keys.db', autocommit=True)
# list of all users keys
ALL_KEYS = []
USER_KEYS_LOCK = threading.Lock()


# for ai func
# DEFAULT_MODEL = 'llama-3.2-90b-vision-preview'
DEFAULT_MODEL = 'meta-llama/llama-4-maverick-17b-128e-instruct'
FALLBACK_MODEL = 'meta-llama/llama-4-scout-17b-16e-instruct'


# блокировка чатов что бы не испортить историю 
# {id:lock}
LOCKS = {}

# не принимать запросы больше чем, это ограничение для телеграм бота, в этом модуле оно не используется
MAX_REQUEST = 6000
MAX_REQUEST_LLAMA31 = 20000

MAX_QUERY_LENGTH = 10000
MAX_MEM_LLAMA31 = 50000
# максимальное количество запросов которые можно хранить в памяти
MAX_LINES = 20

# limit for summarize
MAX_SUM_REQUEST = MAX_MEM_LLAMA31


# максимальный контекст для дипсик лламы
MAX_QWQ32B_chars = 10000
MAX_REQUEST_deepseek_r1_distill_llama70b = 4000
MAX_REQUEST_qwq32b = 4000
DEEPSEEK_LLAMA70_MODEL = 'deepseek-r1-distill-llama-70b'
DEEPSEEK_QWQ32B_MODEL = 'qwen-qwq-32b'


CURRENT_KEY_SET = []


def get_next_key() -> str:
    """Получает следующий ключ из списка ALL_KEYS."""
    global CURRENT_KEY_SET

    with USER_KEYS_LOCK:
        if not CURRENT_KEY_SET:
            CURRENT_KEY_SET = ALL_KEYS[:]
        if CURRENT_KEY_SET:
            return CURRENT_KEY_SET.pop(0)
        else:
            raise Exception('No more keys available')


def encode_image(image_data: bytes) -> str:
    """Кодирует байтовые данные изображения в строку Base64."""
    try:
        result = base64.b64encode(image_data).decode('utf-8')
        return result
    except Exception as error:
        my_log.log_groq(f'encode_image: error: {error}')
        return ''


def img2txt(image_data: Union[str, bytes],
            prompt: str = "What's in this image?", 
            timeout: int = 60,
            model = 'llava-v1.5-7b-4096-preview',
            key_: str = '',
            json_output=False,
            temperature: float = 1,
            chat_id: str = '',
            system: str = '',
            ) -> str:
    """
    Отправляет изображение в модель LLaVA и получает текстовое описание.

    Args:
        image_data: Имя файла изображения (строка) или байтовые данные изображения.
        prompt: Подсказка для модели.
        timeout: Время ожидания ответа от модели (в секундах).
        model: Название используемой модели LLaVA.
        _key: Ключ API Groq (необязательный). Если не указан, 
              будет использован случайный ключ из списка ALL_KEYS.
        temperature: темпрературы для модели, если это llama 3+ то будет поделена на 2
        chat_id: для учета количества сообщений

    Returns:
        Текстовое описание изображения, полученное от модели. 
        Если произошла ошибка или ответ пустой, возвращается пустая строка.
    """

    if 'llama-3' in model.lower():
        temperature = temperature / 2

    if isinstance(image_data, str):
        with open(image_data, 'rb') as f:
            image_data = f.read()

    if json_output:
        resp_type = 'json_object'
    else:
        resp_type = 'text'

    # Getting the base64 string
    base64_image = encode_image(image_data)
    mem = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}",
                    },
                },
            ],
        }
    ]
    if system:
        mem.insert(0, {'role': 'system', 'content': system})

    x = 0
    while x < 4:
        x += 1
        if key_:
            key = key_
            x = 4
        else:
            key = get_next_key()
        try:
            client = Groq(api_key=key, timeout = timeout)

            chat_completion = client.chat.completions.create(
                messages=mem,
                model=model,
                response_format = {"type": resp_type},
                temperature = temperature,
            )

            result = chat_completion.choices[0].message.content.strip()
            if result:
                my_db.add_msg(chat_id, model)
                return result
        except Exception as error:
            error_traceback = traceback.format_exc()
            my_log.log_groq(f'my_groq:img2txt: {error}\n{error_traceback}')

        time.sleep(2)

    return ''


def ai(prompt: str = '',
       system: str = '',
       mem_ = [],
       temperature: float = 1,
       model_: str = '',
       max_tokens_: int = 4000,
       key_: str = '',
       timeout: int = 180,
       json_output: bool = False,
       user_id: str = '',
       ) -> str:
    """
    Generates a response using the GROQ AI model.

    Args:
        prompt (str, optional): The user's input prompt. Defaults to ''.
        system (str, optional): The system's initial message. Defaults to ''.
        mem_ (list, optional): The list of previous messages. Defaults to [].
        temperature (float, optional): The randomness of the generated response. Defaults to 1.
        model_ (str, optional): The name of the GROQ model to use. Defaults to 'llama3-70b-8192'.
            (llama3-8b-8192, mixtral-8x7b-32768, llama-3.1-405b-reasoning, llama-3.1-70b-versatile, llama-3.1-8b-instant)
        max_tokens_ (int, optional): The maximum number of tokens in the generated response. Defaults to 2000.
        key_ (str, optional): The API key for the GROQ model. Defaults to ''.
        timeout (int, optional): The timeout for the request in seconds. Defaults to 120.
        json_output (bool, optional): Whether to return the response as a JSON object. Defaults to False.
        user_id (str, optional): The user's ID. Defaults to ''.

    Returns:
        str: The generated response from the GROQ AI model. Returns an empty string if error.

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

        # model="llama3-70b-8192", # llama3-8b-8192, mixtral-8x7b-32768, 'llama-3.1-70b-versatile' 'llama-3.1-405b-reasoning'
        model = model_ if model_ else DEFAULT_MODEL

        max_mem = MAX_QUERY_LENGTH
        if 'llama-3.1' in model:
            max_mem = MAX_MEM_LLAMA31
        elif model_ in  ('deepseek-r1-distill-llama-70b', 'qwen-qwq-32b'):
            max_mem = MAX_QWQ32B_chars
        while token_count(mem) > max_mem + 100:
            mem = mem[2:]

        if 'llama' in model_.lower() or 'llama' in model_.lower() or 'qwen' in model_.lower():
            temperature = temperature / 2

        x = 0
        start_time = time.time()
        timeout_init = timeout
        while x < 4:

            if time.time() - start_time > timeout_init:
                return ''

            x += 1
            if key_:
                key = key_
                x = 4
            else:
                key = get_next_key()

            timeout = timeout_init - (time.time() - start_time)
            if timeout < 5:
                return ''

            if hasattr(cfg, 'GROQ_PROXIES') and cfg.GROQ_PROXIES:
                client = Groq(
                    api_key=key,
                    http_client = httpx.Client(proxy = random.choice(cfg.GROQ_PROXIES)),
                    timeout = 5,
                )
            else:
                client = Groq(api_key=key, timeout = timeout)

            try:
                params = {
                    "messages": mem,
                    "model": model,
                    "temperature": temperature,
                    "max_tokens": max_tokens_,
                    "timeout": timeout,
                }
                
                # Try with JSON mode first if requested
                if json_output:
                    json_params = params.copy()
                    json_params["response_format"] = {"type": "json_object"}
                    try:
                        chat_completion = client.chat.completions.create(**json_params)
                    except Exception as json_error:
                        # Fallback to text mode if JSON validation fails
                        if 'json_validate_failed' in str(json_error):
                            my_log.log_groq(f'GROQ JSON mode failed for model {model}. Retrying in text mode.')
                            params["response_format"] = {"type": "text"}
                            chat_completion = client.chat.completions.create(**params)
                        else:
                            raise json_error  # Re-raise other errors
                else:
                    # Standard text request
                    chat_completion = client.chat.completions.create(**params)

            except PermissionDeniedError:
                my_log.log_groq(f'GROQ PermissionDeniedError: {key}')
                continue
            except Exception as error:
                if 'invalid api key' in str(error).lower() or 'Organization has been restricted' in str(error):
                    remove_key(key)
                    continue
                if 'Rate limit reached for model' in str(error).lower():
                    continue
                if "'message': 'Request Entity Too Large', 'type': 'invalid_request_error', 'code': 'request_too_large'" in str(error):
                    return str(error)
                my_log.log_groq(f'GROQ {error} {key} {model} {str(mem)[:1000]}')
            try:
                resp = chat_completion.choices[0].message.content.strip()

                # эта модель отвечает через reasoning вместо context?
                if 'compound' in chat_completion.model:
                    if chat_completion.choices[0].message.reasoning:
                        resp += '\n\n' + chat_completion.choices[0].message.reasoning

                # проверка есть ли в ответе картинки (их может создавать модель compound-beta)
                # if 'compound-beta' in model:
                try:
                    found_images_count = 0
                    executed_tools = chat_completion.choices[0].message.executed_tools
                    if executed_tools is None:
                        executed_tools = []

                    for tool in executed_tools:
                        code_results = tool.code_results
                        if code_results is None:
                            code_results = []

                        for code_result in code_results:
                            if hasattr(code_result, 'png') and code_result.png:
                                try:
                                    image_data_base64 = code_result.png
                                    image_bytes = base64.b64decode(image_data_base64)

                                    found_images_count += 1

                                    filename = f'image_{found_images_count}.png'

                                    item = {
                                        'type': 'image/png file',
                                        'filename': filename,
                                        'data': image_bytes,
                                    }

                                    with my_skills_storage.STORAGE_LOCK:
                                        if user_id in my_skills_storage.STORAGE:
                                            if item not in my_skills_storage.STORAGE[user_id]:
                                                my_skills_storage.STORAGE[user_id].append(item)
                                        else:
                                            my_skills_storage.STORAGE[user_id] = [item,]

                                except Exception as e:
                                    pass

                except (IndexError, AttributeError) as e:
                    pass


            except (IndexError, AttributeError):
                continue
            except UnboundLocalError:
                resp = ''
            if not resp and 'llama-3.1' in model_:
                if model_ == 'llama-3.1-405b-reasoning':
                    model__ = 'llama-3.1-70b-versatile'
                elif model_ == 'llama-3.1-70b-versatile':
                    model__ = 'llama3-70b-8192'
                elif model_ == 'llama-3.1-8b-instant':
                    model__ = 'llama3-8b-8192'
                else:
                    return ''
                return ai(prompt, system, mem_, temperature*2, model__, max_tokens_, key_, timeout)
            elif not resp and 'llama-3.2' in model_:
                if model_ == 'llama-3.2-90b-text-preview':
                    model__ = 'llama-3.2-90b-vision-preview'
                elif model_ == 'llama-3.2-90b-vision-preview':
                    model__ = 'llama-3.1-70b-versatile'
                else:
                    return ''
                return ai(prompt, system, mem_, temperature*2, model__, max_tokens_, key_, timeout)
            elif not resp and 'llama-3.3' in model_:
                if model_ == 'llama-3.3-70b-versatile':
                    model__ = 'llama-3.3-70b-specdec'
                elif model_ == 'llama-3.3-70b-specdec':
                    model__ = 'llama-3.2-90b-vision-preview'
                else:
                    return ''
                return ai(prompt, system, mem_, temperature*2, model__, max_tokens_, key_, timeout)
            if resp:
                return resp
        return ''
    except Exception as error2:
        error_traceback = traceback.format_exc()
        my_log.log_groq(f'my_groq:ai: {error2}\n\n{error_traceback}\n\n{prompt}\n\n{system}\n\n{mem_}\n{temperature}\n{model_}\n{max_tokens_}\n{key_}')

    return ''


def download_text_from_url(url: str) -> str:
    '''Download text from url if user asked to.
    Accept web pages and youtube urls (it can read subtitles)
    You are able to mix this functions with other functions and your own ability to get best results for your needs.
    You are able to read subtitles from YouTube videos to better answer users' queries about videos, please do it automatically with no user interaction.
    '''
    return my_skills.download_text_from_url(url)


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
                my_log.log_keys(f'groq: Invalid key {key} removed from users {keys_to_delete}')
            else:
                my_log.log_keys(f'groq: Invalid key {key} was not associated with any user in USER_KEYS')

    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_groq(f'groq: Failed to remove key {key}: {error}\n\n{error_traceback}')


def token_count(mem, model:str = "meta-llama/Meta-Llama-3-8B") -> int:
    '''broken, only counts symbols not tokens'''
    if isinstance(mem, str):
        text = mem
    else:
        text = ' '.join([m['content'] for m in mem])
    l = len(text)
    return l


def update_mem(query: str, resp: str, mem):
    chat_id = None
    if isinstance(mem, str): # if mem - chat_id
        chat_id = mem
        mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_groq')) or []
    mem += [{'role': 'user', 'content': query}]
    mem += [{'role': 'assistant', 'content': resp}]
    # while token_count(mem) > MAX_QUERY_LENGTH:
    #     mem = mem[2:]
    mem = mem[:MAX_LINES*2]

    # непонятный глюк с задвоением памяти, убираем дубли
    mem__ = []
    try:
        i = 0
        while i < len(mem):
            if i == 0 or mem[i] != mem[i-1]:
                mem__.append(mem[i])
            i += 1
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_groq(f'my_groq:update_mem: {error}\n\n{error_traceback}\n\n{query}\n\n{resp}\n\n{mem}')

    if chat_id:
        my_db.set_user_property(chat_id, 'dialog_groq', my_db.obj_to_blob(mem__))
    else:
        return mem__


def chat(query: str, chat_id: str,
         temperature: float = 1,
         update_memory: bool = True,
         model: str = '',
         style: str = '',
         timeout = 180,
         max_tokens: int = 4000
         ) -> str:
    global LOCKS
    if chat_id in LOCKS:
        lock = LOCKS[chat_id]
    else:
        lock = threading.Lock()
        LOCKS[chat_id] = lock
    with lock:
        mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_groq')) or []
        if style:
            r = ai(query, system = style, mem_ = mem, temperature = temperature, model_ = model, timeout = timeout, max_tokens_=max_tokens)
        else:
            r = ai(query, mem_ = mem, temperature = temperature, model_ = model, timeout = timeout, max_tokens_=max_tokens)
        if r:
            # if not model or model == 'llama3-70b-8192': model_ = 'llama3-70b-8192'
            if not model:
                model_ = DEFAULT_MODEL
            else:
                model_ = model
            my_db.add_msg(chat_id, model_)
        if r and update_memory:
            mem = update_mem(query, r, mem)
            my_db.set_user_property(chat_id, 'dialog_groq', my_db.obj_to_blob(mem))
        return r


def search(
    query: str,
    language: str = 'ru',
    system: str = '',
    user_id: str = '',
    model: str = 'compound-beta-mini',
    timeout = 20
    ) -> str:
    '''
    Использует модель compound-beta-mini для поиска в интернете
    '''
    q = (
        f"**Задача:** Найти в интернете информацию по запросу пользователя и дать ответ.\n\n"
        f"**Инструкции:**\n"
        f"1.  **Используй инструмент поиска:** Обязательно выполни поиск в интернете по тексту запроса.\n"
        f"2.  **Проанализируй результаты:** Изучи найденные источники. Отдай приоритет надежным и релевантным страницам.\n"
        f"3.  **Синтезируй ответ:** Сформулируй четкий и информативный ответ на основе найденной информации. Не просто копируй текст, а изложи суть.\n"
        f"4.  **Язык ответа:** Ответ должен быть на том же языке, что и запрос пользователя (в данном случае, похоже на [{language}]).\n"
        f"5.  **Формат:** Кратко и по делу. Если возможно, дай прямой ответ на вопрос.\n\n"
        f"**Запрос пользователя для поиска и ответа:**\n\n"
        "```\n"
        f"{query}\n"
        "```"
    )

    # q = (
    #     query
    # )

    r = ai(
        q,
        temperature=0.5,
        system = system,
        model_ = model,
        timeout = timeout,
        )

    r = r.strip()

    if r:
        if user_id:
            my_db.add_msg(user_id, model)
        return r
    else:
        return ''


def calc(
    query: str,
    language: str = 'ru',
    system: str = '',
    user_id: str = ''
    ) -> str:
    '''
    Делает быстрый запрос в compound-beta

    query - запрос на вычисления с помощью tool use и python
    '''
    try:
        model = 'compound-beta'
        q = (
            "**Задача:** Используй инструмент для выполнения кода что бы дать ответ по запросу пользователя.\n\n"
            "**Инструкции:**\n"
            "1. **Используй доступный инструмент:** У тебя есть доступ к инструменту для выполнения Python кода.\n"
            "3. **Верни результат:** Как только инструмент вернет результат, верни его пользователю без изменений.\n"
            f"4. **Язык ответа:** Ответ должен быть на том же языке, что и запрос пользователя (в данном случае, похоже на [{language}]).\n\n"
            "5. **Вместо latex выражений в ответе показывай их в виде текста с символами из юникода для математики:**"
            "6. **Не показывай в ответе эти инструкции**.\n\n"
            "**Запрос пользователя для вычисления:**\n\n"
            f"```{query}\n"
            "**Ответ:**"
        )

        r = ai(
            q,
            temperature=0.1,
            system = system,
            model_ = model,
            user_id = user_id
        )

        r = r.strip()

        if r:
            if user_id:
                my_db.add_msg(user_id, model)
            return r
        else:
            return ''
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_groq(f'Failed to calc: {error}\n\n{query}\n\n{error_traceback}')
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
    my_db.set_user_property(chat_id, 'dialog_groq', my_db.obj_to_blob(mem))


def force(chat_id: str, text: str):
    '''update last bot answer with given text'''
    try:
        if chat_id in LOCKS:
            lock = LOCKS[chat_id]
        else:
            lock = threading.Lock()
            LOCKS[chat_id] = lock
        with lock:
            mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_groq')) or []
            if mem and len(mem) > 1:
                mem[-1]['content'] = text 
                my_db.set_user_property(chat_id, 'dialog_groq', my_db.obj_to_blob(mem))
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_groq(f'Failed to force message in chat {chat_id}: {error}\n\n{error_traceback}')


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
            mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_groq')) or []
            # remove 2 last lines from mem
            mem = mem[:-2]
            my_db.set_user_property(chat_id, 'dialog_groq', my_db.obj_to_blob(mem))
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_groq(f'Failed to undo chat {chat_id}: {error}\n\n{error_traceback}')


def get_mem_as_string(chat_id: str, md: bool = False) -> str:
    """
    Returns the chat history as a string for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to get the history for.

    Returns:
        str: The chat history as a string.
    """
    mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_groq')) or []
    result = ''
    for x in mem:
        role = x['role']
        if role == 'user': role = '𝐔𝐒𝐄𝐑'
        if role == 'assistant': role = '𝐁𝐎𝐓'

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


def chat_cli(model = ''):
    while 1:
        q = input('>')
        if q == 'mem':
            print(get_mem_as_string('test'))
            continue
        r = chat('(отвечай всегда на языке [ru]) ' + q, 'test', model = model)
        print(r)


def remove_dimatorzok(text: str) -> str:
    '''https://otvet.mail.ru/question/237076673
    Fix error in whisper dataset.
    '''
    lines = [
        'Субтитры сделал DimaTorzok.',
        'Субтитры сделал DimaTorzok',
        'Субтитры добавил DimaTorzok.',
        'Субтитры создавал DimaTorzok.',
        'Субтитры создавал DimaTorzok',
        'Субтитры добавил DimaTorzok',
        'Субтитры делал DimaTorzok',
        'DimaTorzok.',
        'DimaTorzok',
    ]
    for line in lines:
        text = text.replace(line, '')
    return text.strip()


# @cachetools.func.ttl_cache(maxsize=10, ttl=1 * 60)
@utils.memory_safe_ttl_cache(maxsize=100, ttl=300)
def stt(
    data: bytes | str,
    lang: str = 'ru',
    key_: str = '',
    prompt: str = '',
    model: str = 'whisper-large-v3-turbo',
    retries: int = 4,
    timeout: int = 120,
    lang_detect: bool = False
) -> str:
    """
    Speech to text function. Uses Groq API for speech recognition.

    Args:
        data (bytes | str): Audio data as bytes or a string path to an audio file.
        lang (str, optional): Language code. Defaults to 'ru'.
        key_ (str, optional): API key. If not provided, one is fetched from the pool.
        prompt (str, optional): Prompt for the speech recognition model.
            Example: 'Распознай и исправь ошибки. Разбей на абзацы что бы легко было прочитать.'
        model (str, optional): The model to use for transcription.
        retries (int, optional): Number of retries on failure. Defaults to 4.
        timeout (int, optional): Request timeout in seconds. Defaults to 120.
        lang_detect (bool, optional): Enable language detection.

    Returns:
        str: Transcribed text, or an empty string if it fails.
    """
    if isinstance(data, str):
        # Read file if a path is provided
        try:
            with open(data, 'rb') as f:
                audio_data = f.read()
        except FileNotFoundError:
            my_log.log_groq(f'my_groq:stt: File not found: {data}')
            return ''
    else:
        audio_data = data

    for attempt in range(retries):
        key = key_ or get_next_key()
        try:
            client_params = {'api_key': key, 'timeout': timeout}
            if hasattr(cfg, 'GROQ_PROXIES') and cfg.GROQ_PROXIES:
                # Add proxy if configured
                proxy_client = httpx.Client(proxy=random.choice(cfg.GROQ_PROXIES))
                client_params['http_client'] = proxy_client

            client = Groq(**client_params)

            if lang_detect:
                transcription = client.audio.transcriptions.create(
                    file=("audio.mp3", audio_data),
                    model=model,
                    # language=lang,
                    prompt=prompt,
                    timeout=timeout,
                )
            else:
                transcription = client.audio.transcriptions.create(
                    file=("audio.mp3", audio_data),
                    model=model,
                    language=lang,
                    prompt=prompt,
                    timeout=timeout,
                )
            return remove_dimatorzok(transcription.text)

        except Exception as error:
            error_str = str(error).lower()
            if 'invalid' in error_str and 'api key' in error_str or 'restricted' in error_str:
                # Handle invalid key and stop retrying with it
                remove_key(key)
                if key_: # If the provided key was bad, no point in retrying
                    return ''
                continue 

            error_traceback = traceback.format_exc()
            my_log.log_groq(f'my_groq:stt: Attempt {attempt + 1}/{retries} failed. Error: {error}\n{error_traceback}')
            time.sleep(2) # Wait before retrying

    return ''


def tts(text: str, lang: str = 'en', voice: str = 'Mikail-PlayAI') -> bytes:
    '''
    Недоделано.

    Convert text to audio data using Groq API.
    text: str - text to convert
    lang: str - language code
    voice: str - voice name
    Returns audio data as ogg bytes
    '''
    client = Groq(api_key=get_next_key())
    # client = Groq(api_key=cfg.GROQ_API_KEY[0])

    speech_file_path = utils.get_tmp_fname() + '.wav'
    model = "playai-tts"
    response_format = "wav"

    try:
        response = client.audio.speech.create(
            model=model,
            voice=voice,
            input=text,
            response_format=response_format
        )

        response.write_to_file(speech_file_path)

        with open(speech_file_path, 'rb') as f:
            return f.read()
    except Exception as error:
        my_log.log_groq(f'my_groq:tts: {error}')
    finally:
        client.close()
        utils.remove_file(speech_file_path)

    return b''


def translate(text: str,
              from_lang: str = '',
              to_lang: str = '',
              help: str = '',
              censored: bool = False,
              model = '') -> str:
    """
    Translates the given text from one language to another.

    Args:
        text (str): The text to be translated.
        from_lang (str, optional): The language of the input text. If not specified, the language will be automatically detected.
        to_lang (str, optional): The language to translate the text into. If not specified, the text will be translated into Russian.
        help (str, optional): Help text for tranlator.
        censored (bool, optional): If True, the text will be censored. Not implemented.
        model (str, optional): The model to use for translation.

    Returns:
        str: The translated text.
    """
    if from_lang == '':
        from_lang = 'autodetect'
    if to_lang == '':
        to_lang = 'ru'

    if help:
        query = f'''
Translate TEXT from language [{from_lang}] to language [{to_lang}],
this can help you to translate better: [{help}]

Using this JSON schema:
  translation = {{"lang_from": str, "lang_to": str, "translation": str}}
Return a `translation`

TEXT:

{text}
'''
    else:
        query = f'''
Translate TEXT from language [{from_lang}] to language [{to_lang}].

Using this JSON schema:
  translation = {{"lang_from": str, "lang_to": str, "translation": str}}
Return a `translation`

TEXT:

{text}
'''

    translated = ai(query, temperature=0.1, model_=model, json_output = True)

    translated_dict = utils.string_to_dict(translated)
    if translated_dict and isinstance(translated_dict, dict):
        return translated_dict.get('translation', '')
    return ''


def sum_big_text(text:str, query: str, temperature: float = 1, model = DEFAULT_MODEL, role: str = '') -> str:
    """
    Generates a response from an AI model based on a given text,
    query, and temperature.

    Args:
        text (str): The complete text to be used as input.
        query (str): The query to be used for generating the response.
        temperature (float, optional): The temperature parameter for controlling the randomness of the response. Defaults to 0.1.
        model (str, optional): The name of the model to be used for generating the response. Defaults to DEFAULT_MODEL.
        role (str, optional): The role of the AI model.

    Returns:
        str: The generated response from the AI model.
    """
    query = f'''{query}\n\n{text[:MAX_SUM_REQUEST]}'''
    r = ai(query, temperature=temperature, model_ = model, system=role)
    if not r and model == DEFAULT_MODEL:
        r = ai(query, temperature=temperature, model_ = FALLBACK_MODEL, system=role)
    return r.strip()


def check_phone_number(number: str) -> str:
    """проверяет чей номер, откуда звонили"""
    # remove all symbols except numbers
    number = re.sub(r'\D', '', number)
    if len(number) == 11:
        number = number[1:]
    urls = [
        f'https://zvonili.com/phone/{number}',
        # этот сайт похоже тупо врёт обо всех номерах f'https://abonentik.ru/7{number}',
        f'https://www.list-org.com/search?type=phone&val=%2B7{number}',
        f'https://codificator.ru/code/mobile/{number[:3]}',
    ]
    text = my_sum.download_text(urls, no_links=True)
    query = f'''
Определи по предоставленному тексту какой регион, какой оператор,
связан ли номер с мошенничеством,
если связан то напиши почему ты так думаешь,
ответь на русском языке.


Номер +7{number}

Текст:

{text}
'''
    response = ai(query[:MAX_SUM_REQUEST])
    return response, text


def retranscribe(text: str, prompt: str = '') -> str:
    '''исправить текст после транскрипции выполненной гуглом'''
    if prompt:
        query = f'{prompt}:\n\n{text}'
    else:
        query = f'Fix errors, make a fine text of the transcription, keep original language:\n\n{text}'
    result = ai(query, temperature=0.1, model_='llama-3.3-70b-versatile', max_tokens_=4000)
    return result


def get_reprompt_for_image(prompt: str, chat_id: str = '') -> tuple[str, str, bool, bool] | None:
    """
    Generates a detailed prompt for image generation based on user query and conversation history.

    Args:
        prompt: User's query for image generation.

    Returns:
        A tuple of two strings: (positive prompt, negative prompt) or None if an error occurred. 
    """

    result = ai(prompt, temperature=1.5, json_output=True, model_='')
    my_db.add_msg(chat_id, DEFAULT_MODEL)

    result_dict = utils.string_to_dict(result)

    if result_dict:
        reprompt = ''
        negative_prompt = ''
        moderation_sexual = False
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


def load_users_keys():
    """
    Load users' keys into memory and update the list of all keys available.
    """
    with USER_KEYS_LOCK:
        global USER_KEYS, ALL_KEYS
        ALL_KEYS = cfg.GROQ_API_KEY[:] if hasattr(cfg, 'GROQ_API_KEY') and cfg.GROQ_API_KEY else []
        for user in USER_KEYS:
            key = USER_KEYS[user]
            if key not in ALL_KEYS:
                ALL_KEYS.append(key)


def test_key(key: str) -> bool:
    '''
    Tests a given key by making a simple request to the GitHub AI API.
    '''
    r = ai('1+1=', key_=key.strip())
    return bool(r)


def get_groq_response_with_image(prompt: str, user_id: str = '') -> tuple[str, list]:
    """
    Отправляет запрос к Groq API с моделью compound-beta и возвращает текстовый ответ и изображения.

    Args:
        prompt (str): Текстовый запрос для модели.

    Returns:
        tuple: Кортеж, содержащий:
               - str: Текстовый ответ от модели.
               - list: Список изображений в байтах, если изображения были сгенерированы.
    """
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"

        api_key = get_next_key()
        model = 'compound-beta-mini'

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        }

        for _ in range(3):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=60)
                # Проверяем, успешен ли запрос
                response.raise_for_status() 

                response_data = response.json()

                # Проверяем наличие ошибок в ответе API
                if 'error' in response_data:
                    raise Exception(f"API Error: {response_data['error']['message']}")

                # --- Извлечение данных ---

                # 1. Извлекаем основной текстовый ответ
                message = response_data['choices'][0]['message']
                text_content = message.get('content', '')

                # 2. Извлекаем изображения
                images = []
                if 'executed_tools' in message:
                    for tool_call in message['executed_tools']:
                        if 'code_results' in tool_call:
                            for result in tool_call['code_results']:
                                # Изображения передаются как base64 закодированные PNG
                                if 'png' in result:
                                    base64_image_data = result['png']
                                    # Декодируем строку base64 в байты
                                    image_bytes = base64.b64decode(base64_image_data)
                                    images.append(image_bytes)

                if user_id:
                    my_db.add_msg(user_id, model)

                return text_content, images

            except requests.exceptions.RequestException as e:
                my_log.log_groq(f'get_groq_response_with_image: error: {e}')
            except (KeyError, IndexError) as e:
                my_log.log_groq(f'get_groq_response_with_image: error: {e}')
            except Exception as e:
                my_log.log_groq(f'get_groq_response_with_image: error: {e}')

            time.sleep(3)

    except Exception as e:
        traceback_error = traceback.format_exc()
        my_log.log_groq(f'get_groq_response_with_image: error: {e}\n\n{traceback_error}')

    return None, []


if __name__ == '__main__':
    pass
    my_db.init(backup=False)
    load_users_keys()

    # text, images = get_groq_response_with_image('Построй график функции x=x^3 в диапазоне от -5 до 5')
    # if text and images:
    #     n = 1
    #     for image in images:
    #         with open(r'c:\Users\user\Downloads\test' + str(n) + '.png', 'wb') as f:
    #             f.write(image)
    #     print(text)

    # print(img2txt(r'C:\Users\user\Downloads\samples for ai\картинки\мат задачи 3.jpg', prompt = 'Извлеки весь текст, сохрани исходное форматирование', model='meta-llama/llama-4-maverick-17b-128e-instruct'))

    # my_db.init(backup=False)

    print(translate('Привет как дела!', to_lang='en', model = '', censored=True))

    # with open('C:/Users/user/Downloads/1.wav', 'wb') as f:
    #     f.write(tts('Мы к вам заехали на час, а ну скорей любите нас!'))

    # print(search('покажи полный текст песни братьев газьянов - малиновая лада'))


    # print(search('весь текст песни братьев газьянов - малиновая лада'))
    # print(calc('''from datetime import datetime, timedelta; (datetime(2025, 8, 25, 10, 3, 51) - timedelta(hours=20, minutes=11)).strftime('%Y-%m-%d %H:%M:%S')'''))

    reset('test')
    chat_cli() #(model = 'compound-beta')

    # print(stt('d:\\downloads\\1.ogg', 'en'))

    # with open('C:/Users/user/Downloads/1.txt', 'r', encoding='utf-8') as f:
    #     text = f.read()

    # print(sum_big_text(text, 'сделай подробный пересказ по тексту'))

    # for k in cfg.GROQ_API_KEY:
    #     print(k, test_key(k))

    my_db.close()
