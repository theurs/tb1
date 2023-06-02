#!/usr/bin/env python3

import re

# диалог всегда начинается одинаково

gpt_start_message = [{"role":    "system",
                      "content": "Ты информационная система отвечающая на запросы юзера."}]


# шутливый вариант, используется рандомно, иногда, что бы вставить шутку
gpt_start_message2= [{"role":       "system",
                      "content":    "Ты информационная система отвечающая на запросы юзера."},
 
                     {"role":       "user",
                      "content":    "Отвечай с подходящим к запросу типом юмора или иронии."},

                     {"role":       "assistant",
                      "content":    "Ок!"}

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
    #pattern = r"([_*\[\]()~|`])"
    pattern = r"([_*\[\]~|`])"
    return re.sub(pattern, r"\\\1", text)


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
    print(count_tokens(gpt_start_message))
