#!/usr/bin/env python3
# pip install --upgrade deepl

import random
import re
import subprocess
import threading
import traceback
import uuid
from datetime import datetime, timedelta

import deepl
import enchant
from langdetect import detect, detect_langs
from duckduckgo_search import DDGS
from sqlitedict import SqliteDict

import cfg
import my_log
import utils


# {key '(text, from, to)' :value 'translated'}
deepl_cache = SqliteDict('db/deepl_cache.db', autocommit=True)
# {unique_id: (current_date, len(text))}
deepl_api_counter = SqliteDict('db/deepl_api_counter.db', autocommit=True)
per_month_tokens_limit = 400000
deepl_lock = threading.Lock()


# keep in memory the translation
TRANSLATE_CACHE = {}


def count_russian_words_not_in_ukrainian_dict(text):
    """Считаем количество русских слов в тексте, эти слова не должны быть в украинском и белорусском"""
    platform = utils.platform().lower()
    if 'wind' in platform:
        return len(text.split())
    d_ru = enchant.Dict("ru_RU")
    d_uk = enchant.Dict("uk_UA")
    russian_words = []
    # Заменяем все символы, которых нет в алфавитах, на пробелы
    text = re.sub(r"[^а-яА-ЯіІїЇєЄёЁ]+", " ", text)
    for word in text.split():
        # Проверяем, является ли слово русским
        if d_ru.check(word) and not d_uk.check(word):
            russian_words.append(word)
    return len(russian_words)


def count_ukr_words(text):
    """Считаем количество украинских слов не пересекающихся с русскими"""
    d_uk = enchant.Dict("uk_UA")
    d_ru = enchant.Dict("ru_RU")
    words = []
    # Заменяем все символы, которых нет в алфавитах, на пробелы
    text = re.sub(r"[^а-яА-ЯіІїЇєЄёЁ]+", " ", text)
    for word in text.split():
        # Проверяем, является ли слово русским
        if d_uk.check(word) and not d_ru.check(word):
            words.append(word)
    return len(words)


def detect_lang(text):
    """ Возвращает None если не удалось определить, 2 буквенное определение языка если получилось 'en', 'ru' итп """
    # минимальное количество слов для определения языка = 8. на коротких текстах детектор сильно врёт, возможно 8 это тоже мало
    if sum(1 for word in text.split() if len(word) >= 2) < 8:
        # если пробелов очень мало то возможно это язык типа японского
        if len(text) < 20 or text.count(' ') > len(text)/20:
            return None
    
    # cчитаем белорусские буквы
    pattern = r'[ЎўІіЎў]'
    if len(re.findall(pattern, text)) > 3:
        return 'be' # возможно украинский но нам всё равно, главное что не русский
    
    # если в тексте больше 2 русских слов возвращаем None
    if count_russian_words_not_in_ukrainian_dict(text) > 2:
        return None

    # если в тексте больше 2 чисто украинских слов возвращаем 'uk'
    if count_ukr_words(text) > 2:
        return 'uk'

    # смотрим список вероятностей, и если в списке есть русский то возвращаем None (с русского на русский не переводим)
    #print(detect_langs(text))
    try:
        for i in detect_langs(text):
            if i.lang == 'ru':
                return None
    except Exception as e:
        print(e)
        return None

    try:
        language = detect(text)
    except Exception as e:
        print(e)
        return None
    return language


def ddg_translate(text: str, lang = 'ru'):
    """
    Translates the given text into the specified language using the DuckDuckGo translation service.

    Args:
        text (str): The text to be translated.
        lang (str, optional): The language to translate the text to. Defaults to 'ru'.

    Returns:
        str: The translated text, or the original text if translation fails.
    """
    if lang == 'ua':
        lang = 'uk'
    keywords = [text, ]
    try:
        results = DDGS().translate(keywords, to=lang)
        return results[0]['translated']
    except:
        return text


def translate_text2(text, lang = 'ru'):
    """
    Translates the given text into the specified language using an external 
    translation service. Requires the `trans` command to be installed.

    Args:
        text (str): The text to be translated.
        lang (str, optional): The language to translate the text to. Defaults to 'ru'.
    
    Returns:
        str: The translated text.
    """
    if lang == 'ua':
        lang = 'uk'
    if 'windows' in utils.platform().lower():
        return ddg_translate(text, lang)
    text = text.strip()
    startswithslash = False
    if text.startswith('/'):
        text = text.replace('/', '@', 1)
        startswithslash = True
    key = str((text, lang))
    if key in TRANSLATE_CACHE:
        return TRANSLATE_CACHE[key]
    process = subprocess.Popen(['trans', f':{lang}', '-b', text], stdout = subprocess.PIPE)
    output, error = process.communicate()
    result = output.decode('utf-8').strip()
    if error:
        my_log.log2(f'my_trans:translate_text2: {error}\n\n{text}\n\n{lang}')
        return None
    if startswithslash:
        if result.startswith('@'):
            result = result.replace('@', '/', 1)
    TRANSLATE_CACHE[key] = result
    return result


def translate(text):
    """ Проверяем надо ли переводить на русский и переводим если надо.
    Возвращает None если не удалось перевести и текст перевода если удалось """
    if text:
        d = detect_lang(text)
    else:
        return None
    # переводим если язык не русский но определился успешно
    if d and d != 'ru':
        return translate_text2(text) or None
        # return translate_text2(text) or translate_text(text) or None
    return None


def translate_deepl(text: str, from_lang: str = None, to_lang: str = '') -> str:
    auth_key = random.choice(cfg.DEEPL_KEYS) if hasattr(cfg, 'DEEPL_KEYS') and cfg.DEEPL_KEYS else None
    if not auth_key:
        return ''

    if to_lang == 'en':
        to_lang = 'EN-US'

    cache_key = str((text, from_lang, to_lang))
    if cache_key in deepl_cache:
        return deepl_cache[cache_key]

    with deepl_lock:
         # Проверка лимита токенов
        current_date = datetime.now()
        thirty_days_ago = current_date - timedelta(days=30)
        tokens_used_last_30_days = 0
        for key in list(deepl_api_counter.keys()):
            date_used, tokens = deepl_api_counter[key]
            if date_used >= thirty_days_ago:
                tokens_used_last_30_days += tokens
            else:
                del deepl_api_counter[key]
        if tokens_used_last_30_days >= per_month_tokens_limit:
            my_log.log_translate(f'translate_deepl: The limit on the number of translated characters has been exceeded. The limit is valid for 30 days.\n\n{text}\n\n{from_lang}\n\n{to_lang}')
            return ''

        translator = deepl.Translator(auth_key)
        target_lang = None
        for x in translator.get_target_languages():
            code = x.code
            if to_lang.upper() in code:
                target_lang = x
                break

        if not target_lang:
            return ''

        try:
            unique_id = str(uuid.uuid4())
            deepl_api_counter[unique_id] = (current_date, len(text))
            result = translator.translate_text(text, target_lang=target_lang)
            deepl_cache[cache_key] = result.text
            # Запись события перевода
            return result.text
        except Exception as error:
            traceback_error = traceback.format_exc()
            my_log.log2(f'my_trans:translate_deepl: {error}\n\n{text}\n\n{to_lang}\n\n{traceback_error}')
            return ''


if __name__ == "__main__":
    pass
    print(translate_deepl('три', to_lang='en'))
