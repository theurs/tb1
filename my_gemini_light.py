#!/usr/bin/env python3


########## SKILLS ##########
import re
import math
import datetime
import decimal
import numbers
import numpy
import numpy as np
import random
import re
import traceback
from math import *
from decimal import *
from numbers import *

# it will import word random and broke code
# from random import *
from random import betavariate, choice, choices, expovariate, gammavariate, gauss, getrandbits, getstate, lognormvariate, normalvariate, paretovariate, randbytes, randint, randrange, sample, seed, setstate, shuffle, triangular, uniform, vonmisesvariate, weibullvariate

import my_sum
import my_google
########## SKILLS ##########




import cachetools.func
import io
import PIL
import random
import sys
import time
import threading
import traceback

import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold, GenerationConfig
from google.generativeai.types import RequestOptions
from google.ai.generativelanguage_v1beta import types as protos
from sqlitedict import SqliteDict

import cfg
import my_log

import utils


# {id: mem,}
CHATS = SqliteDict('db/gemini_light_chats.db', autocommit=True)


ALL_KEYS = cfg.gemini_keys


SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    # это не работает HarmCategory.HARM_CATEGORY_UNSPECIFIED: HarmBlockThreshold.BLOCK_NONE,
}

# таймаут в запросе к джемини
TIMEOUT = 120

LOCKS = {}
CHATS = {}
MAX_CHAT_LINES = 20
if hasattr(cfg, 'GEMINI_MAX_CHAT_LINES'):
    MAX_CHAT_LINES = cfg.GEMINI_MAX_CHAT_LINES
MAX_CHAT_MEM_CHARS = 20000*3 # 20000 токенов по 3 символа на токен. +8000 токенов на ответ остается 4000 токенов на системный промпт и прочее
# не принимать запросы больше чем, это ограничение для телеграм бота, в этом модуле оно не используется
MAX_REQUEST = 20000
MAX_SUM_REQUEST = 250000


def chat(query: str,
         chat_id: str = '',
         temperature: float = 1,
         model: str = '',
         system: str = '',
         max_tokens: int = 8000,
         insert_mem = None,
         key__: str = '',
         use_skills: bool = False,
         json_output: bool = False,
         do_not_update_history=False) -> str:
    '''Chat with AI model.
    Args:
        query (str): The query to be used for generating the response.
        chat_id (str, optional): The ID of the chat. Defaults to ''.
        temperature (float, optional): Controls the randomness of the output. Must be positive.
                                       Typical values are in the range: [0.0,2.0]. Higher values
                                       produce a more random and varied response.
                                       A temperature of zero will be deterministic.
                                       The temperature parameter for controlling the randomness of the response.
                                       Defaults to 0.1.
        model (str, optional): The model to use for generating the response. Defaults to '' = gemini-1.5-flash.
                               gemini-1.5-flash-latest,
                               gemini-1.0-pro,
                               gemini-1.0-pro-001,
                               gemini-1.0-pro-latest,
                               gemini-1.5-flash-latest,
                               gemini-1.5-pro,
                               gemini-1.5-pro-latest,
                               gemini-pro
        system (str, optional): The system instruction to use for generating the response. Defaults to ''.
        max_tokens (int, optional): The maximum number of tokens to generate. Defaults to 8000. Range: [10,8000]
        insert_mem: (list, optional): The history of the chat. Defaults to None.
        json_output: (bool, optional): Return json STRING, require something
        like this in prompt - Using this JSON schema: Recipe = {"recipe_name": str} Return a `list[Recipe]`
        Defaults to False.

    Returns:
        str: The generated response from the AI model.
    '''
    try:
        global ALL_KEYS

        chat_id = str(chat_id)

        query = query[:MAX_SUM_REQUEST]
        if temperature < 0:
            temperature = 0
        if temperature > 2:
            temperature = 2
        if max_tokens < 10:
            max_tokens = 10
        if max_tokens > 8000:
            max_tokens = 8000

        if not model:
            model = cfg.gemini_flash_model

        if chat_id:
            mem = CHATS[chat_id] if chat_id in CHATS else []
        else:
            mem = []

        if not mem and insert_mem:
            mem = insert_mem

        mem = transform_mem2(mem)

        if system == '':
            system = None

        system = f'user_id: {chat_id}\n\n{str(system)}'

        if not key__:
            keys = cfg.gemini_keys[:] + ALL_KEYS
        else:
            keys = [key__,]

        random.shuffle(keys)
        keys = keys[:4]
        badkeys = ['b3470eb3b2055346b76f2ce3b11aadf2f6fdccf5703ad853b4a5b0cf46f1cf16',]
        for key in keys[:]:
            if utils.fast_hash(key) in badkeys:
                keys.remove(key)
                ALL_KEYS.remove(key)

        time_start = time.time()
        for key in keys:
            if time.time() > time_start + (TIMEOUT-1):
                my_log.log_gemini_lite(f'my_gemini:chat: stop after timeout {round(time.time() - time_start, 2)}\n{model}\n{key}\nRequest size: {sys.getsizeof(query) + sys.getsizeof(mem)} {query[:100]}')
                return ''

            genai.configure(api_key = key)

            if json_output:
                GENERATION_CONFIG = GenerationConfig(
                    temperature = temperature,
                    max_output_tokens = max_tokens,
                    response_mime_type = "application/json",
                )
            else:
                GENERATION_CONFIG = GenerationConfig(
                    temperature = temperature,
                    max_output_tokens = max_tokens,
                )

            SKILLS = [
                search_google,
                download_text_from_url,
                calc,
                ]

            if use_skills:
                model_ = genai.GenerativeModel(
                    model,
                    tools = SKILLS,
                    generation_config = GENERATION_CONFIG,
                    safety_settings=SAFETY_SETTINGS,
                    system_instruction = system,
                )
            else:
                model_ = genai.GenerativeModel(
                    model,
                    generation_config = GENERATION_CONFIG,
                    safety_settings=SAFETY_SETTINGS,
                    system_instruction = system,
                )
 
            request_options = RequestOptions(timeout=TIMEOUT)
            chat = model_.start_chat(history=mem, enable_automatic_function_calling=True)
            try:
                resp = chat.send_message(query,
                                    safety_settings=SAFETY_SETTINGS,
                                    request_options=request_options,
                                    )
            except Exception as error:
                my_log.log_gemini_lite(f'my_gemini:chat: {error}\n{model}\n{key}\nRequest size: {sys.getsizeof(query) + sys.getsizeof(mem)} {query[:100]}')
                if 'reason: "CONSUMER_SUSPENDED"' in str(error) or \
                   'reason: "API_KEY_INVALID"' in str(error):
                    ALL_KEYS.remove(key)
                if 'finish_reason: ' in str(error) or 'block_reason: ' in str(error) or 'User location is not supported for the API use.' in str(error):
                    return ''
                time.sleep(2)
                continue

            try:
                result = chat.history[-1].parts[-1].text
            except Exception as error3:
                my_log.log_gemini_lite(f'my_gemini:chat: {error3}\nresult: {result}\nchat history: {str(chat.history)}')
                result = resp.text

            # пытается вызвать функцию неправильно
            if result:
                if 'print(default_api.' in result[:100]:
                    return ''

            # флеш (и не только) иногда такие тексты в которых очень много повторов выдает,
            # куча пробелов, и возможно другие тоже. укарачиваем
            result_ = utils.shorten_all_repeats(result)
            if len(result_)+100 < len(result): # удалось сильно уменьшить
                result = result_
                try:
                    result = chat.history[-1].parts[-1].text = result
                except Exception as error4:
                    my_log.log_gemini_lite(f'my_gemini:chat: {error4}\nresult: {result}\nchat history: {str(chat.history)}')

            result = result.strip()

            if result:
                if chat_id and do_not_update_history is False:
                    mem = chat.history[-MAX_CHAT_LINES*2:]
                    while count_chars(mem) > MAX_CHAT_MEM_CHARS:
                        mem = mem[2:]
                    CHATS[chat_id] = mem
                return result

        my_log.log_gemini_lite(f'my_gemini:chat:no results after 4 tries, query: {query}\n{model}')
        return ''
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_gemini_lite(f'my_gemini:chat: {error}\n\n{traceback_error}\n{model}')
        return ''


# @cachetools.func.ttl_cache(maxsize=10, ttl=10 * 60)
def img2txt(data_: bytes,
            prompt: str = "Что на картинке, подробно?",
            temp: float = 1,
            model: str = cfg.gemini_flash_model,
            json_output: bool = False,
            chat_id: str = '',
            use_skills: str = False
            ) -> str:
    '''Convert image to text.
    '''
    chat_id = str(chat_id)
    for _ in range(4):
        try:
            data = io.BytesIO(data_)
            img = PIL.Image.open(data)
            q = [prompt, img]
            res = chat(q, temperature=temp, model = model, json_output = json_output, use_skills=use_skills)
            return res
        except Exception as error:
            traceback_error = traceback.format_exc()
            my_log.log_gemini_lite(f'my_gemini:img2txt: {error}\n\n{traceback_error}')
        time.sleep(2)
    my_log.log_gemini_lite(f'my_gemini:img2txt 4 tries done and no result')
    return ''


def ai(q: str,
       mem = [],
       temperature: float = 1,
       model: str = '',
       tokens_limit: int = 8000,
       chat_id: str = '',
       system: str = '') -> str:
    chat_id = str(chat_id)
    return chat(q,
                chat_id=chat_id,
                temperature=temperature,
                model=model,
                max_tokens=tokens_limit,
                system=system,
                insert_mem=mem)


def chat_cli(user_id: str = 'test', model: str = ''):
    reset(user_id, model)
    while 1:
        q = input('>')
        if q == 'mem':
            print(get_mem_as_string(user_id, model = model))
            continue
        if '.jpg' in q or '.png' in q or '.webp' in q:
            img = PIL.Image.open(open(q, 'rb'))
            q = ['опиши картинку', img]
        # r = chat(q, user_id, model=model, use_skills=True)
        r = chat(q, user_id, model=model)
        print(r)


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
            # my_log.log_gemini_lite(f'transform_mem2:debug: {type(x)} {str(x)}')
            if not x.parts[0].text.strip():
                x.parts[0].text == '...'
            mem_.append(x)
    return mem_


def update_mem(query: str, resp: str, mem, model: str = ''):
    """
    Update the memory with the given query and response.

    Parameters:
        query (str): The input query.
        resp (str): The response to the query.
        mem: The memory object to update, if str than mem is a chat_id
        model (str): The model name.

    Returns:
        list: The updated memory object.
    """
    chat_id = ''
    if isinstance(mem, int):
        mem = str(mem)
    if isinstance(mem, str): # if mem - chat_id
        chat_id = mem
        mem = CHATS[mem] if mem in CHATS else []
        mem = transform_mem2(mem)

    u = protos.Content(role='user', parts=[protos.Part(text=query)])
    b = protos.Content(role='model', parts=[protos.Part(text=resp)])
    mem.append(u)
    mem.append(b)

    mem = mem[-MAX_CHAT_LINES*2:]
    while count_chars(mem) > MAX_CHAT_MEM_CHARS:
        mem = mem[2:]

    if chat_id:
        CHATS[chat_id] = mem
    return mem


def force(chat_id: str, text: str, model: str = ''):
    '''update last bot answer with given text'''
    try:
        chat_id = str(chat_id)
        if chat_id in LOCKS:
            lock = LOCKS[chat_id]
        else:
            lock = threading.Lock()
            LOCKS[chat_id] = lock
        with lock:
            mem = CHATS[chat_id] if chat_id in CHATS else []
            mem = transform_mem2(mem)
            # remove last bot answer and append new
            if len(mem) > 1:
                if len(mem[-1].parts) == 1:
                    mem[-1].parts[0].text = text
                else:
                    for p in mem[-1].parts:
                        if p.text != mem[-1].parts[-1].text:
                            p.text = ''
                    mem[-1].parts[-1].text = text
                CHATS[chat_id] = mem
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_gemini_lite(f'Failed to force text in chat {chat_id}: {error}\n\n{error_traceback}\n\n{text}')


def undo(chat_id: str, model: str = ''):
    """
    Undo the last two lines of chat history for a given chat ID.

    Args:
        chat_id (str): The ID of the chat.
        model (str): The model name.

    Raises:
        Exception: If there is an error while undoing the chat history.

    Returns:
        None
    """
    try:
        chat_id = str(chat_id)
        if chat_id in LOCKS:
            lock = LOCKS[chat_id]
        else:
            lock = threading.Lock()
            LOCKS[chat_id] = lock
        with lock:
            mem = CHATS[chat_id] if chat_id in CHATS else []
            mem = transform_mem2(mem)
            # remove 2 last lines from mem
            mem = mem[:-2]
            CHATS[chat_id] = mem
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_gemini_lite(f'Failed to undo chat {chat_id}: {error}\n\n{error_traceback}')


def reset(chat_id: str, model: str = ''):
    """
    Resets the chat history for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to reset.
        model (str): The model name.

    Returns:
        None
    """
    chat_id = str(chat_id)
    mem = []
    CHATS[chat_id] = mem


def get_last_mem(chat_id: str, model: str = '') -> str:
    """
    Returns the last answer for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to get the history for.
        model (str, optional): The name of the model.

    Returns:
        str:
    """
    chat_id = str(chat_id)
    mem = CHATS[chat_id] if chat_id in CHATS else []

    mem = transform_mem2(mem)
    last = mem[-1]
    if last:
        if len(last.parts) == 1:
            return last.parts[0].text
        else:
            return last.parts[-1].text


def get_mem_as_string(chat_id: str, md: bool = False, model: str = '') -> str:
    """
    Returns the chat history as a string for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to get the history for.
        md (bool, optional): Whether to format the output as Markdown. Defaults to False.
        model (str, optional): The name of the model.

    Returns:
        str: The chat history as a string.
    """
    chat_id = str(chat_id)
    mem = CHATS[chat_id] if chat_id in CHATS else []

    mem = transform_mem2(mem)

    result = ''
    for x in mem:
        role = x.role
        if role == 'user': role = '𝐔𝐒𝐄𝐑'
        if role == 'model': role = '𝐁𝐎𝐓'
        try:
            if len(x.parts) == 1:
                text = x.parts[0].text.split(']: ', maxsplit=1)[1]
            else:
                text = ''
                for p in x.parts:
                    text += p.text + '\n\n'
                text = text.strip()
                # text = text.split(']: ', maxsplit=1)[1]
        except IndexError:
            if len(x.parts) == 1:
                text = x.parts[0].text
            else:
                text = x.parts[-1].text
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


def count_chars(mem) -> int:
    '''считает количество символов в чате'''
    mem = transform_mem2(mem)

    total = 0
    for x in mem:
        for i in x.parts:
            total += len(i.text)
    return total


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

    if censored:
        translated = chat(query, temperature=0.1, model=model, json_output = True)
    else:
        translated = chat(query, temperature=0.1, insert_mem=[], model=model, json_output = True)
    translated_dict = utils.string_to_dict(translated)
    if translated_dict:
        return translated_dict['translation']
    return text


@cachetools.func.ttl_cache(maxsize=10, ttl=10 * 60)
def sum_big_text(text:str, query: str, temperature: float = 1) -> str:
    """
    Generates a response from an AI model based on a given text,
    query, and temperature. Split big text into chunks of 15000 characters.

    Args:
        text (str): The complete text to be used as input.
        query (str): The query to be used for generating the response.
        temperature (float, optional): The temperature parameter for controlling the randomness of the response. Defaults to 0.1.

    Returns:
        str: The generated response from the AI model.
    """
    query = f'''{query}\n\n{text[:MAX_SUM_REQUEST]}'''
    r = ai(query, temperature=temperature, model=cfg.gemini_flash_model)
    if not r:
        r = ai(query, temperature=temperature, model=cfg.gemini_flash_model_fallback)
    return r


########## SKILLS ##########

@cachetools.func.ttl_cache(maxsize=10, ttl=60 * 60)
def search_google(query: str, lang: str = 'ru') -> str:
    """
    Searches Google for the given query and returns the search results.

    Args:
        query: The search query string.
        lang: The language for the search (defaults to 'ru').

    Returns:
        A string containing the search results.
        In case of an error, returns a string 'ERROR' with the error description.
    """
    query = decode_string(query)
    try:
        r = my_google.search_v3(query, lang)[0]
        return r
    except Exception as error:
        return f'ERROR {error}'


@cachetools.func.ttl_cache(maxsize=10, ttl=60 * 60)
def download_text_from_url(url: str, language: str = 'ru') -> str:
    '''Download text from url if user asked to.
    Accept web pages and youtube urls (it can read subtitles)
    language code is 2 letters code, it is used for youtube subtitle download
    '''
    try:
        result = my_sum.summ_url(url, download_only = True, lang = language)
        return result[:MAX_REQUEST]
    except Exception as error:
        return f'ERROR {error}'


def decode_string(s: str) -> str:
    if isinstance(s, str) and s.count('\\') > 2:
        try:
            s = s.replace('\\\\', '\\')
            s = str(bytes(s, "utf-8").decode("unicode_escape").encode("latin1").decode("utf-8"))
            return s
        except Exception as error:
            return s
    else:
        return s


@cachetools.func.ttl_cache(maxsize=10, ttl = 60*60)
def calc(expression: str) -> str:
    '''Calculate expression with pythons eval(). Use it for all calculations.
    Available modules: decimal, math, numbers, numpy, random, datetime.
    Use only one letter variables.
    Avoid text in math expressions.

    return str(eval(expression))
    Examples: calc("56487*8731") -> '493187997'
              calc("pow(10, 2)") -> '100'
              calc("math.sqrt(2+2)/3") -> '0.6666666666666666'
              calc("decimal.Decimal('0.234234')*2") -> '0.468468'
              calc("numpy.sin(0.4) ** 2 + random.randint(12, 21)")
    '''
    allowed_words = [
        'math', 'decimal', 'random', 'numbers', 'numpy', 'np',
        'print', 'str', 'int', 'float', 'bool', 'type', 'len', 'range',
        'round', 'pow', 'sum', 'min', 'max', 'divmod',
        'for', 'not', 'in', 'and', 'if', 'or', 'next',
        'digit',

        'list','tuple','sorted','reverse','True','False',

        'datetime', 'days', 'seconds', 'microseconds', 'milliseconds', 'minutes', 'hours', 'weeks',
        ]
    allowed_words += [x for x in dir(random) + dir(math) + dir(decimal) + dir(numbers) + dir(datetime) + dir(datetime.date) + dir(numpy) if not x.startswith('_')]
    allowed_words = sorted(list(set(allowed_words)))
    # get all words from expression
    words = re.findall(r'[^\d\W]+', expression)
    for word in words:
        if len(word) == 1:
            continue
        if word not in allowed_words:
            return f'Error: Invalid expression. Forbidden word: {word}'
    try:
        expression_ = expression.replace('math.factorial', 'my_factorial')
        r = str(eval(expression_))
        return r
    except Exception as error:
        return f'Error: {error}'


def my_factorial(n: int) -> int:
    '''Calculate factorial of n.
    return int(math.factorial(n))
    '''
    if n > 1500:
        raise ValueError('factorial > 1500, too big number')
    return math.factorial(n)

########## SKILLS ##########



if __name__ == '__main__':
    pass

    print(chat('привет'))

    chat_cli(model=cfg.gemini_flash_model)
