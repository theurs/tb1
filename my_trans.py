#!/usr/bin/env python3
# pip install -U deepl
# pip install -U lingua-language-detector

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
from fuzzywuzzy import fuzz
from lingua import Language, LanguageDetectorBuilder

import cfg
import my_log
import utils


# {key '(text, from, to)' :value 'translated'}
deepl_cache = SqliteDict('db/deepl_cache.db', autocommit=True)
# {unique_id: (current_date, len(text), auth_key)}
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


def check_deepl_limit(auth_key: str) -> int:
    # Проверка лимита токенов
    current_date = datetime.now()
    thirty_days_ago = current_date - timedelta(days=30)
    tokens_used_last_30_days = 0
    for key, value in list(deepl_api_counter.items()):
        try:
            date_used, tokens, used_key = value
        except ValueError:
            date_used, tokens = value
            used_key = cfg.DEEPL_KEYS[0]
            del deepl_api_counter[key]
            deepl_api_counter[key] = (date_used, tokens, used_key)

        if used_key == auth_key:
            if date_used >= thirty_days_ago:
                tokens_used_last_30_days += tokens
            else:
                del deepl_api_counter[key]

    return tokens_used_last_30_days


def get_deepl_stats() -> str:
    result = ''
    with deepl_lock:
        if hasattr(cfg, 'DEEPL_KEYS') and cfg.DEEPL_KEYS:
            for key in cfg.DEEPL_KEYS:
                result += f'Deepl {key[:5]}: {check_deepl_limit(key)} of {per_month_tokens_limit}\n'
    return result


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
        tokens_used_last_30_days = check_deepl_limit(auth_key)
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

    # supported_source_langs = ['ar', 'bg', 'cs', 'da', 'de', 'el', 'en', 'es', 'et',
    #                           'fi', 'fr', 'hu', 'id', 'it', 'ja', 'ko', 'lt', 'lv',
    #                           'nb', 'nl', 'pl', 'pt', 'ro', 'ru', 'sk', 'sl', 'sv',
    #                           'tr', 'uk', 'zh']
    # supported_target_langs = ['ar', 'bg', 'cs', 'da', 'de', 'el', 'en', 'en-gb',
    #                           'en-us', 'es', 'et', 'fi', 'fr', 'hu', 'id', 'it',
    #                           'ja', 'ko', 'lt', 'lv', 'nb', 'nl', 'pl', 'pt',
    #                           'pt-br', 'pt-pt', 'ro', 'ru', 'sk', 'sl', 'sv',
    #                           'tr', 'uk', 'zh']

    try:
        unique_id = str(uuid.uuid4())
        deepl_api_counter[unique_id] = (current_date, len(text), auth_key)
        result = translator.translate_text(text, target_lang=target_lang)
        # не удалось перевести?
        ratio = fuzz.ratio(text, result.text)
        if ratio > 90:
            return ''
        with deepl_lock:
            deepl_cache[cache_key] = result.text
        # Запись события перевода
        # my_log.log_translate(f'{unique_id}: {text} -> {result.text}\n\ntokens_used_last_30_days: {tokens_used_last_30_days}\nper_month_tokens_limit: {per_month_tokens_limit}\n\n{from_lang}\n\n{to_lang}')
        return result.text
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'my_trans:translate_deepl: {error}\n\n{text}\n\n{to_lang}\n\n{traceback_error}')
        return ''


def detect_lang_v2(text: str) -> str:
    """
    Detects the language of the given text and returns the ISO 639-1 language code.
    
    Args:
        text (str): The text to be analyzed.
        
    Returns:
        str: The ISO 639-1 language code of the detected language. Returns an empty string if no language is detected.
        
    Raises:
        Exception: If an error occurs during language detection.
    """
    try:
        detector = LanguageDetectorBuilder.from_all_languages().build()
        result = detector.detect_language_of(text)
        return result.iso_code_639_1.name.lower() if result != None else ''
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'my_trans:detect_lang_v2: {error}\n\n{text}\n\n{traceback_error}')
        return ''


if __name__ == "__main__":
    pass
    # print(detect_lang_v2("""привiт"""))
    print(translate_deepl('.אבל אשים רבים נהנים לבלו', to_lang='ru'))
    # print(translate_deepl('три6', to_lang='de'))
    # print(get_deepl_stats())
