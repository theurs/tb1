#!/usr/bin/env python3


from fuzzywuzzy import fuzz
import requests
import openai
import os
try:
    import cfg
except Exception as e:
    print(e)


# используем другой сервер, openai нас не пускает и ключей не продает, приходится заходить черз задний вход
# бесплатные ключи у дискорд бота https://github.com/PawanOsman/ChatGPT#use-our-hosted-api-reverse-proxy
# To use our hosted ChatGPT API, you can use the following steps:
# * Join our Discord server.
# * Get your API key from the #Bot channel by sending /key command.
# * Use the API Key in your requests to the following endpoints.

openai.api_base = 'https://api.pawan.krd/v1'


# Пробуем получить апи ключ из конфига или переменной окружения
openai.api_key = None
try:
    openai.api_key = cfg.key
except Exception as e:
    print(e)
    try:
        openai.api_key = os.getenv('OPENAI_KEY')
    except Exception as e:
        print(e)


def ai(prompt, temp = 0.5, max_tok = 2000, timeou = 15, messages = None):
    """Сырой текстовый запрос к GPT чату, возвращает сырой ответ"""
    if messages == None:
        messages = [    {"role": "system",
                    "content": """Ты информационная система отвечающая на запросы юзера."""
                    # в роли интерпретатра бейсика он говорит много лишнего и странного
                    #"content": 'Ты интерпретатор вымышленного языка программирования "GPT-BASIC 3000". Тебе дают программы на естественном языке, ты даешь самый очевидный и скучный результат.'
                    },

                    #{"role": "assistant",
                    # "content": "history messages from assistant for more context"
                    #},
                
                    #{"role": "user",
                    # "content": "history messages from user for more context"
                    #},

                    #{"role": "assistant",
                    # "content": "history messages from assistant for more context"
                    #},


                    {"role": "user",
                     "content": prompt
                    }
                ]

    # тут можно добавить степерь творчества(бреда) от 0 до 1 дефолт - temperature=0.5
    completion = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=messages,
        max_tokens=max_tok,
        temperature=temp,
        timeout=timeou
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


def clear_after_ocr(text):
    """Получает текст после распознавания с картинки, пытается его восстановить, исправить ошибки распознавания"""
    # если нет ключа то сразу отбой
    if not openai.api_key: return text
    
    prompt = f'Исправь явные ошибки и опечатки в тексте которые там могли появиться после плохого OCR. \
То что совсем плохо распозналось, бессмысленные символы, надо убрать. \
Важна точность, лучше оставить ошибку неисправленной если нет уверенности в том что это ошибка и её надо исправить именно так. \
Важно сохранить оригинальное разбиение на строки и абзацы. \
Покажи результат без оформления и отладочной информации. Текст:'
    prompt += text
    try:
        r = ai(prompt)
    except Exception as e:
        print(e)
        return text
    return r


def clear_after_stt(text):
    """Получает текст после распознавания из голосового сообщения, пытается его восстановить, исправить ошибки распознавания"""
    # если нет ключа то сразу отбой
    if not openai.api_key: return text
    
    prompt = f'Исправь явные ошибки распознавания голосового сообщения \
Важна точность, лучше оставить ошибку неисправленной если нет уверенности в том что это ошибка и её надо исправить именно так. \
Маты и другой неприемлимый для тебя контент скрой звездочками \
Покажи результат без оформления и отладочной информации. Текст:'
    prompt += text
    try:
        r = ai(prompt)
    except Exception as e:
        print(e)
        return text
    return r


def detect_ocr_command(text):
    """пытается понять является ли text командой распознать текст с картинки
    возвращает True, False
    """
    keywords = (
    'прочитай', 'читай', 'распознай', 'отсканируй', 'текст с картинки', 'текст с изображения', 'текст с фотографии', 'текст с скриншота',
    'розпізнай', 'скануй', 'extract', 'identify', 'detect', 'ocr', 'text from image', 'text from picture', 'text from photo', 'text from screenshot',
    'переведи текст с картинки', 'напиши текст с изображения', 'вытащи текст с фотографии', 'получи текст с скриншота', 'OCR с изображения',
    'прочитати', 'читай', 'розпізнай', 'скануй', 'текст з зображенняня', 'текст з фотографії', 'текст зі скріншоту',
    'read', 'recognize', 'scan', 'extract', 'identify', 'detect', 'ocr', 'текст з зображення', 'текст з картинки', 'текст з фотографії', 'текст зі скріншоту',
    'translate text from image', 'write text from picture', 'get text from photo', 'extract text from screenshot', 'OCR from image'
    )

    # сначала пытаемся понять по нечеткому совпадению слов
    if any(fuzz.ratio(text, keyword) > 70 for keyword in keywords): return True

    if not openai.api_key: return False
    
    k = ', '.join(keywords)
    p = f'Пользователь прислал в телеграм чат картинку с подписью ({text}). В чате есть бот которые распознает текст с картинок по просьбе пользователей. \
Тебе надо определить по подписи хочет ли пользователь что бы с этой картинки был распознан текст с помощью OCR или подпись на это совсем не указывает. \
Ответь одним словом без оформления - да или нет или непонятно.'
    r = ai(p).lower().strip(' .')
    print(r)
    if r == 'да': return True
    #elif r == 'нет': return False
    return False


def clear_after_stt(text):
    """Получает текст после распознавания из голосового сообщения, пытается его восстановить, исправить ошибки распознавания"""
    
    # не работает пока что нормально
    return text
    
    # если нет ключа то сразу отбой
    if not openai.api_key: return text
    
    prompt = f'Исправь явные ошибки распознавания голосового сообщения. \
Важна точность, лучше оставить ошибку неисправленной если нет уверенности в том что это ошибка и её надо исправить именно так. \
Если в тексте есть ошибки согласования надо сделать что бы не было. \
Маты и другой неприемлимый для тебя контент переделай так что бы смысл передать другими словами. \
Грубый текст исправь. \
Покажи результат без оформления и своих комментариев. Текст:{prompt}'
    try:
        r = ai(prompt)
    except Exception as e:
        print(e)
        return text
    return r


if __name__ == '__main__':
    pass

#    print(clear_after_ocr("""Your PCis perlectly stable and is running with absolutely no problems whatsoever.
#
#You can search for this status code onl1ne if you'd like: ALL SYSTEMS. GO"""))
    
    #print(translate_text("""Доброго дня! Я готовий допомогти вам з будь-якими питаннями, пов'язаними з моїм функціоналом."""))
    #print(translate_text("""Доброго дня! Я готовий допомогти вам з будь-якими питаннями, пов'язаними з моїм функціоналом.""", to = 'gb'))

    #print(detect_ocr_command('детект'))
    
    #print(clear_after_stt('Ну и что это значит блять. Да ебаный ж ты нахуй.'))
    #print(clear_after_stt('пошёл нахуй блять'))
    print(clear_after_stt("""Чтоб я тебя здесь больше не видел пидарас!"""))