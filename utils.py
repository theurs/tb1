#!/usr/bin/env python3

import re

# диалог всегда начинается одинаково

gpt_start_message = [{"role":    "system",
                      "content": "Ты искусственный интеллект отвечающий на запросы юзера."}]

#gpt_start_message = [{"role":    "system",
#                      "content": "Ты искусственный интеллект отвечающий на запросы юзера. Отвечай с подходящим к запросу типом иронии или юмора но не перегибай палку."}]

#gpt_start_message = [{"role":    "system",
#                      "content": "Ты искусственный интеллект отвечающий на запросы юзера. Отвечай с сильной иронией и токсичностью."}]


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


def remove_vowels(text: str) -> str:
    """
    Функция для удаления из текста русских и английских гласных букв "а", "о", "e" и "a".
    :param text: текст, в котором нужно удалить гласные буквы
    :type text: str
    :return: текст без указанных гласных букв
    :rtype: str
    """
    vowels = [  'а', 'о',   # русские
                'a', 'e']   # английские. не стоит наверное удалять слишком много
    for vowel in vowels:
        text = text.replace(vowel, '') # заменяем гласные буквы на пустую строку
    return text


if __name__ == '__main__':
    text = """'привет к��к дела ("tesd<\*__t text)"""
    print(escape_markdown(text))
    print(count_tokens(gpt_start_message))
