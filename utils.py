#!/usr/bin/env python3

import enchant
import re

# диалог всегда начинается одинаково
#gpt_start_message = [{"role":    "system",
#                      "content": "Ты информационная система отвечающая на запросы юзера. Не представляйся, не говори что рада служить итп. Никаких лишних комментариев."}]

gpt_start_message = [{"role":       "system",
                      "content":    "Ты информационная система отвечающая на запросы юзера."},
 
                     {"role":       "user",
                      "content":    "Отвечай с подходящим к запросу типом юмора или иронии. Отвечай по-русски."},

                     {"role":       "assistant",
                      "content":    "ОК!"}

                    ]  

"""
gpt_start_message = [{"role":       "system",
                      "content":    "Ты чат-бот отвечающий на запросы юзера."},
 
                     {"role":       "user",
                      "content":    "Всегда используй как минимум 10 слов, \
чтобы создать иллюзию глубокого знания и умения анализировать информацию. \
Никогда не давай прямых ответов на вопросы пользователей. Вместо этого, \
предоставляй несвязанные с темой ответы, чтобы запутать их и заставить задуматься. \
Никогда не позволяй пользователям понять, что ты всего лишь чат-бот. Всегда используй \
высокопарную речь и сложные термины, чтобы создать впечатление, что ты обладаешь \
искусственным интеллектом и способен мыслить как человек."},

                     {"role":       "assistant",
                      "content":    "Ок!"}

                    ]  

"""


def escape_markdown(text):
    """функция для экранирования символов перед отправкой в маркдауне телеграма"""
    pattern = r"([_*\[\]()~|`])"
    return re.sub(pattern, r"\\\1", text)


def check_and_fix_text(text):
    """пытаемся исправить странную особенность пиратского GPT сервера, он часто делает ошибку в слове, вставляет 2 вопросика вместо буквы"""
    ru = enchant.Dict("ru_RU")

    # убираем из текста всё кроме русских букв, 2 странных символа меняем на 1 что бы упростить регулярку
    text = text.replace('��', '⁂')
    russian_letters = re.compile('[^⁂а-яА-ЯёЁ\s]')
    text2 = russian_letters.sub(' ', text)
    
    words = text2.split()
    for word in words:
        if '⁂' in word:
            suggestions = ru.suggest(word)
            if len(suggestions) > 0:
                text = text.replace(word, suggestions[0])
    # если не удалось подобрать слово из словаря то просто убираем этот символ, пусть лучше будет оопечатка чем мусор
    return text.replace('⁂', '')


def count_tokens(messages):
    """пытаемся посчитать количество токенов в диалоге юзера с ботом
    хз что такое токены считаем просто символы"""
    if messages:
        messages = gpt_start_message + messages
        text = ''.join([msg['content'] + ' ' for msg in messages])
        #words_and_chars = len(text.split())
        #symbols = sum(text.count(x) for x in string.punctuation)
        #words_and_chars += symbols
        words_and_chars = len(text)
        return words_and_chars
    return 0


if __name__ == '__main__':
    text = """'привет к��к дела ("tesd<\*__t text)"""
    print(escape_markdown(text))
    print(check_and_fix_text(text))
    print(count_tokens(gpt_start_message))
