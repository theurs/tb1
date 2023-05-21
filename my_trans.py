#!/usr/bin/env python3


from py_trans import PyTranslator
from langdetect import detect, detect_langs
import subprocess
import gpt_basic


def detect_lang(text):
    """ Возвращает None если не удалось определить, 2 буквенное определение языка если получилось 'en', 'ru' итп """
    # смотрим список вероятностей, и если в списке есть русский то возвращаем None (с русского на русский не переводим)
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
        # этот вариант почему то заметно хуже работает, хотя вроде бы тот же самый гугл переводчик
        #return translate_text(text)

        #у этого варианта есть проблемы с кодировками в докере Ж)
        #return translate_text2(text)
        
        return gpt_basic.translate_text(text) or translate_text2(text) or None
    return None
    

if __name__ == "__main__":
    #text="""Звичайно, я можу написати два речення на українській мові."""
    
    
    text = """Тарифи на електроенергію збільшуватимуть лише через пошкоджену енергосистему

Міненерго шукає різні механізми для відновлення пошкодженої ворогом енергосистеми, заявив Фарід Сафаров, заступник міністра енергетики. 

За його словами, наразі в енергетиці існує велика кількість проблем і потрібно знайти механізми, щоб у енергокомпаній були кошти на ремонти. Він підкреслив, що внаслідок атак було пошкоджено 66% теплоелектроцентралей. 

Наразі Міністерство аналізує, наскільки необхідно підняти тариф для населення, щоб у енергетиків вистачило грошей на відновлення.
ㅤ (https://t.me/+UATyHogngJZiMzZi)
Надіслати новину @novosti_kieva_bot"""
    
    #print(detect_lang('пато hello how are you going'))
    
    #print(translate_text(text))
    #print(translate_text2(text))

    print(translate(text))
