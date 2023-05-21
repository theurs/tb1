#!/usr/bin/env python3


import requests
import openai
import os
try:
    import cfg
except Exception as e:
    print(e)


openai.api_key = None
try:
    openai.api_key = cfg.key
except Exception as e:
    print(e)
    try:
        openai.api_key = os.getenv('OPENAI_KEY')
    except Exception as e:
        print(e)


def ai(prompt):
    """Сырой текстовый запрос к GPT чату, возвращает сырой ответ"""
    
    messages = [    {"role": "system",
                    "content": 'Ты информационная система отвечающая на запросы юзера.'
                    # в роли интерпретатра бейсика он говорит много лишнего и странного
                    #"content": 'Ты интерпретатор вымышленного языка программирования "GPT-BASIC 3000". Тебе дают программы на естественном языке, ты даешь самый очевидный и скучный результат.'
                    },
                
                    {"role": "user",
                     "content": prompt
                    }
                ]

    completion = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=messages
    )

    response = completion.choices[0].message.content
    return response


def translate_text(text, fr = 'autodetect', to = 'ru'):
    """переводит текст с помощью GPT-чата, возвращает None при ошибке"""

    # если нет ключа то сразу отбой
    if not openai.api_key: return None
    
    prompt = f'Исправь явные опечатки в тексте и разорванные строки которые там могли появиться после плохого OCR, переведи текст с языка ({fr}) на язык ({to}), \
разбей переведенный текст на абзацы для удобного чтения по возможности сохранив оригинальное разбиение на строки и абзацы. \
Ссылки и другие непереводимые элементы из текста надо сохранить в переводе. Текст это всё (до конца) что идет после двоеточия. \
Покажи только перевод без оформления и отладочной информации. Текст:'
    prompt += text

    try:
        r = ai(prompt)
    except Exception as e:
        print(e)
        return None
    return r


if __name__ == '__main__':
    pass
    
    #print(translate_text("""Доброго дня! Я готовий допомогти вам з будь-якими питаннями, пов'язаними з моїм функціоналом."""))
    #print(translate_text("""Доброго дня! Я готовий допомогти вам з будь-якими питаннями, пов'язаними з моїм функціоналом.""", to = 'gb'))
    
    #print(ai("сгенерируй список реалистичных турецких имен на русском, 10шт, отсортируй по фамилии по возрастанию, покажи строку содержащую сериализованный питон список"))
