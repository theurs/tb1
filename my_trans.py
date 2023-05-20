#!/usr/bin/env python3

from py_trans import PyTranslator
from langdetect import detect, detect_langs
import subprocess


def detect_lang(text):
    """ Возвращает None если не удалось определить, 2 буквенное определение языка если получилось 'en', 'ru' итп """
    # смотрим список вероятностей, и если в списке есть русский то возвращаем 'ru'
    #print(detect_langs(text))
    try:
        for i in detect_langs(text):
            if i.lang == 'ru':
                return None
    except Exception as e:
        print(e)
        return None
    # минимальное количество слов для определения языка = 4. на коротких текстах детектор сильно врёт, возможно 4 это тоже мало
    if sum(1 for word in text.split() if len(word) >= 2) < 5:
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
    

def translate_text2(text):
    """ Возвращает None если не удалось перевести и текст перевода если удалось """
    process = subprocess.Popen(['trans', ':ru', '-b', text], stdout = subprocess.PIPE)
    output, error = process.communicate()
    r = output.decode('utf-8').strip()
    if error != None:
        return None
    return r


def translate(text):
    """ Проверяем надо ли переводить на русский и переводим если надо.
    Возвращает None если не удалось перевести и текст перевода если удалось """
    d = detect_lang(text)
    # переводим если язык не русский но определился успешно
    if d and d != 'ru':
        #return translate_text(text)
        return translate_text2(text)
    return None
    

if __name__ == "__main__":
    text_de="""Natürlich, hier ist ein kurzer Witz auf Deutsch:

Warum können Skelette nicht lügen?
Weil sie immer die Wahrheit sagen."""
    #print(detect_lang('пато hello how are you going'))
    print(translate(text_de))