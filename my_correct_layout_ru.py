#!/usr/bin/env python3


import binascii
import pickle
import re
import threading
import traceback

import my_correct_layout_ru_v2
import my_log
import my_groq


LOCK = threading.Lock()


RU_WORDS = ''


def count_russian_words(text: str) -> int:
    """Считаем количество русских слов в тексте"""
    global RU_WORDS
    with LOCK:
        if isinstance(RU_WORDS, str):
            with open('russian_words_crc.dat', 'rb') as f:
                RU_WORDS = pickle.load(f)
            # RU_WORDS = set(RU_WORDS)
            # RU_WORDS = [binascii.crc32(x.encode('cp1251', errors='replace')) for x in RU_WORDS]
            # with open('russian_words_crc.dat', 'wb') as f:
            #     pickle.dump(RU_WORDS, f)

    russian_words = []
    # Заменяем все символы, которых нет в алфавитах, на пробелы
    text = re.sub(r"[^а-яА-ЯіІїЇєЄёЁ]+", " ", text)
    for word in text.split():
        # Проверяем, является ли слово русским
        if binascii.crc32(word.encode('cp1251', errors='replace')) in RU_WORDS:
            if len(word) > 2:
                russian_words.append(word)
    return len(russian_words)


def count_english_chars(text: str) -> int:
    """Считаем количество английских символов в тексте"""
    count = 0
    for char in text:
        if 'a' <= char <= 'z' or 'A' <= char <= 'Z':
            count += 1
    return count


def is_mostly_english(text: str) -> bool:
    """Проверяет, что количество английских букв в тексте больше 60%"""
    english_chars = count_english_chars(text)
    total_chars = len(text)
    if total_chars == 0:
        return False  # Avoid division by zero
    return (english_chars / total_chars) > 0.6


def convert_eng_to_rus(text: str) -> str:
    """Заменяет в тексте английские буквы на русские"""
    layout_mapping = {
        'q': 'й', 'w': 'ц', 'e': 'у', 'r': 'к',
        't': 'е', 'y': 'н', 'u': 'г', 'i': 'ш',
        'o': 'щ', 'p': 'з', '[': 'х', ']': 'ъ',
        'a': 'ф', 's': 'ы', 'd': 'в', 'f': 'а',
        'g': 'п', 'h': 'р', 'j': 'о', 'k': 'л',
        'l': 'д', ';': 'ж', '\'': 'э', 'z': 'я',
        'x': 'ч', 'c': 'с', 'v': 'м', 'b': 'и',
        'n': 'т', 'm': 'ь', ',': 'б', '.': 'ю',
        '/': '.', '`':'ё', '~': 'Ё',
        'Q': 'Й', 'W': 'Ц', 'E': 'У', 'R': 'К',
        'T': 'Е', 'Y': 'Н', 'U': 'Г', 'I': 'Ш',
        'O': 'Щ', 'P': 'З', '{': 'Х', '}': 'Ъ',
        'A': 'Ф', 'S': 'Ы', 'D': 'В', 'F': 'А',
        'G': 'П', 'H': 'Р', 'J': 'О', 'K': 'Л',
        'L': 'Д', ':': 'Ж', '"': 'Э', 'Z': 'Я',
        'X': 'Ч', 'C': 'С', 'V': 'М', 'B': 'И',
        'N': 'Т', 'M': 'Ь', '<': 'Б', '>': 'Ю',
        '?': ',',
    }
    result = ""
    for char in text:
        result += layout_mapping.get(char, char)
    return result


def count_all_words(text):
    """Подсчитывает количество слов в тексте, включая русские и английские."""
    words = re.findall(r"[a-zA-Zа-яА-ЯёЁ]+", text)
    return len(words)


def ai(one: str, two: str) -> str:
    '''определяет с помощью ИИ какой вариант правильный на случай если
    словарный и частотный методы не сошлись во мнении'''
    s = '''Надо определить какой из вариантов правильный а какой - набран в неправильной раскладке,
    когда человек набрал текст забыв переключить раскладку.
    Твой ответ должен содержать только одну цифру - какой вариант выглядит более правильным.'''
    q = f'''
1. {one}

2. {two}
'''
    # print('!AI POWER!', one, two)
    # result = my_groq.ai(q, temperature = 0.1, system = s, model_ = 'llama3-70b-8192', max_tokens_ = 1, timeout = 5)
    result = my_groq.ai(q, temperature = 0.1, system = s, model_ = 'gemma2-9b-it', max_tokens_ = 1, timeout = 5)
    if '2' in result:
        return two
    return one


def correct_layout_(text: str) -> str:
    '''Исправляет раскладку в тексте ghbdtn->привет'''
    try:
        if is_mostly_english(text):
            converted = convert_eng_to_rus(text)
            all_words = count_all_words(text)
            rus_words = count_russian_words(converted)
            if rus_words >= all_words/2:
                return converted
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:my_correct_layout_ru: {error}\n\n{traceback_error}')
    return text


def correct_layout(text: str) -> str:
    '''Исправляет раскладку в тексте ghbdtn->привет'''
    if len(text) < 4:
        return text

    one = correct_layout_(text)
    two = my_correct_layout_ru_v2.correct_layout(text)
    if one == two:
        result = one
    else:
        result = ai(one, two)

    if text != result:
        my_log.log_layout_switcher(text, result)

    return result


if __name__ == '__main__':

    my_correct_layout_ru_v2.load()
    my_groq.load_users_keys()

    l = [
        'Перевод Beni sevdiğini söylediğine göre boşanacaksın',
        'напиши эту инструкцию сам',
        'tOT',
        'еще',
        'to`',
        'ещё',
        'Global Unicast IPv6 адрес компьютера - fe80::1038:64bc:8e3b:fd25',
        'fkb',
        'али',
        '..ghbdtn',
        '...руддщ',
        'https://example.com',
        'реезыЖ..учфьздуюсщь',
        'при',
        'ghb',
        'git',
        'пше',
        'руддщ',
        'ghbdtn',
        'привет',
        'ghtdtn',
        'превет',
        'нарисуй коня',
        'yfhbceq rjyz',
        'ye b xt',
        'Съешь ещё этих мягких французских булок, да выпей чаю',
        'The quick brown fox jumps over the lazy dog.',
        'This is a mixed text with both English and Russian words: привет!',
        'Ghbdtn, rfr ltkf ghjcnj',
        'Привет, это тест на русском языке.',
        'This is another test, but in English.',
        'Just some random English words: keyboard, mouse, monitor.',
        'Ещё немного русских слов: солнце, небо, облака.',
        'Ytnrf yt gjcktlyz vs ghbdt', # !
        '~, ndj. yfktdj',
        'Lf ,kznm ye xj jgznm',
        ]


    for x in l:
        print(correct_layout(x))
