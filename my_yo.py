#!/usr/bin/env python3
## -*- coding: utf-8 -*-


import re


DATA_PATH = "my_yo.txt"

TEXT = open(DATA_PATH, "r", encoding="utf-8").read().replace('\r', '').split('\n')

DATA = [x.strip() for x in TEXT if x[0] != "*"]
DATA = [x for x in DATA if len(x) > 1]
DATA_CLEANED = [x.replace('ё', 'е') for x in DATA]

# DATA_NOT_SURE = [x.replace("*", "").strip() for x in TEXT if x[0] == "*"]
# DATA_NOT_SURE = [x for x in DATA_NOT_SURE if len(x) > 1]    

# print(len(DATA))
# print(DATA_NOT_SURE[:100])


def yo_text(text: str) -> str:
    """заменяет слова на версии с буквой ё в однозначных случаях"""
    # заменить все символы кроме русских букв на пробелы
    text2 = re.sub(r"[^а-яА-ЯёЁ]+", " ", text)
    # заменить 2 и более пробела на 1
    text2 = re.sub(r"\s+", " ", text2)
    for word in text2.split():
        word_lower = word.lower()
        if word_lower in DATA_CLEANED:
            yo_word = DATA[DATA_CLEANED.index(word_lower)]
            # заменить это слово в исходном тексте, менять только слово целиком
            text = re.sub(f'\\b{word}\\b', yo_word, text, flags=re.I)
    return text


if __name__ == '__main__':
    text = """него(тещу).
 
переездами звездный звезды звезд
– Ага! – злорадно усмехнулась Кива. – Так ты собирался избавиться от тещи? Ну и сволочь!

"""
    print(yo_text(text))
