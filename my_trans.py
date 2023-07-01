#!/usr/bin/env python3


from py_trans import PyTranslator
from langdetect import detect, detect_langs
import subprocess
import gpt_basic
import re
import enchant


def count_russian_words_not_in_ukrainian_dict(text):
    """Считаем количество русских слов в тексте, эти слова не должны быть в украинском и белорусском"""
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


def translate_text(text, lang = 'ru'):
    """ Возвращает None если не удалось перевести и текст перевода если удалось """
    x = PyTranslator()
    r = x.translate(text, lang)
    if r['status'] == 'success':
        return r['translation']
    return None
    

def translate_text2(text, lang = 'ru'):
    """ Переводит text на язык lang с помощью утилиты trans. Возвращает None если не удалось перевести и текст перевода если удалось """
    process = subprocess.Popen(['trans', f':{lang}', '-b', text], stdout = subprocess.PIPE)
    output, error = process.communicate()
    r = output.decode('utf-8').strip()
    if error != None:
        return None
    return r


def translate(text):
    """ Проверяем надо ли переводить на русский и переводим если надо.
    Возвращает None если не удалось перевести и текст перевода если удалось """
    if text:
        d = detect_lang(text)
    else:
        return None
    # переводим если язык не русский но определился успешно
    if d and d != 'ru':
        # этот вариант почему то заметно хуже работает, хотя вроде бы тот же самый гугл переводчик
        #return translate_text(text)
        
        #return gpt_basic.translate_text(text) or translate_text2(text) or None
        # отключил ГПТ, он часто включает цензуру
        return translate_text2(text) or translate_text(text) or None
    return None
    

if __name__ == "__main__":
    text = "Вітаю! Я - інфармацыйная сістэма, якая можа адказаць на запытанні ў вас. Я не магу размаўляць на людскай мове, але вы можаце пісаць мне паведамленні на любой мове, якую вы ведаеце. Дзякуй за карыстанне мной!"

    
    #print(translate_text2(text, 'en'))
    
    #print(translate_text(text))
    #print(translate_text2(text))

    #print(translate(text))

    #print(detect_lang('історією та культурою. Только не говори что надо'))
    #print(detect_langs(text)[0].lang)

    print(translate_text('@', 'en'))