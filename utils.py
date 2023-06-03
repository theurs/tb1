#!/usr/bin/env python3

import re

# диалог всегда начинается одинаково

gpt_start_message = [{"role":    "system",
                      "content": "Ты информационная система отвечающая на запросы юзера. Отвечай в мужском роде"}]


def escape_markdown(text):
    """функция для экранирования символов перед отправкой в маркдауне телеграма"""
    #pattern = r"([_*\[\]()~|`])"
    pattern = r"([_*\[\]~|`])"
    return re.sub(pattern, r"\\\1", text)


def count_tokens(messages):
    """пытаемся посчитать количество символов в диалоге юзера с ботом
    хз что такое токены считаем просто символы"""
    if messages:
        # тут будет некоторое количество лишнего но пусть будет
       return len(str(messages))
    return 0


if __name__ == '__main__':
    text = """'привет к��к дела ("tesd<\*__t text)"""
    print(escape_markdown(text))
    print(count_tokens(gpt_start_message))
