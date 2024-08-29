#!/usr/bin/env python3

import pickle
import re
from collections import Counter

import my_log


TRIGRAM_RU = ''
TRIGRAM_EN = ''


LAYOUT_MAP = {
    'q': 'й', 'w': 'ц', 'e': 'у', 'r': 'к',
    't': 'е', 'y': 'н', 'u': 'г', 'i': 'ш',
    'o': 'щ', 'p': 'з', '[': 'х', ']': 'ъ',
    'a': 'ф', 's': 'ы', 'd': 'в', 'f': 'а',
    'g': 'п', 'h': 'р', 'j': 'о', 'k': 'л',
    'l': 'д', ';': 'ж', "'": 'э', 'z': 'я',
    'x': 'ч', 'c': 'с', 'v': 'м', 'b': 'и',
    'n': 'т', 'm': 'ь', ',': 'б', '.': 'ю',
    '/': '.', '`': 'ё', '~': 'Ё', 'Q': 'Й',
    'W': 'Ц', 'E': 'У', 'R': 'К', 'T': 'Е',
    'Y': 'Н', 'U': 'Г', 'I': 'Ш', 'O': 'Щ',
    'P': 'З', '{': 'Х', '}': 'Ъ', 'A': 'Ф',
    'S': 'Ы', 'D': 'В', 'F': 'А', 'G': 'П',
    'H': 'Р', 'J': 'О', 'K': 'Л', 'L': 'Д',
    ':': 'Ж', '"': 'Э', 'Z': 'Я', 'X': 'Ч',
    'C': 'С', 'V': 'М', 'B': 'И', 'N': 'Т',
    'M': 'Ь', '<': 'Б', '>': 'Ю', '?': ',',
    '!': '!', '@': '"', '#': '№', '$': ';',
    '%': '%', '^': ':', '&': '?', '*': '*',
    '(': '(', ')': ')', '_': '_', '+': '+',
    '|': '/', '=': '='
}
## Создаем обратный словарь для перевода с русской раскладки на английскую
# REVERSE_LAYOUT_MAP = {value: key for key, value in LAYOUT_MAP.items()}
REVERSE_LAYOUT_MAP = {
    'й': 'q', 'ц': 'w', 'у': 'e', 'к': 'r', 'е': 't',
    'н': 'y', 'г': 'u', 'ш': 'i', 'щ': 'o', 'з': 'p',
    'х': '[', 'ъ': ']', 'ф': 'a', 'ы': 's', 'в': 'd',
    'а': 'f', 'п': 'g', 'р': 'h', 'о': 'j', 'л': 'k',
    'д': 'l', 'ж': ';', 'э': "'", 'я': 'z', 'ч': 'x',
    'с': 'c', 'м': 'v', 'и': 'b', 'т': 'n', 'ь': 'm',
    'б': ',', 'ю': '.', '.': '/', 'ё': '`', 'Ё': '~',
    'Й': 'Q', 'Ц': 'W', 'У': 'E', 'К': 'R', 'Е': 'T',
    'Н': 'Y', 'Г': 'U', 'Ш': 'I', 'Щ': 'O', 'З': 'P',
    'Х': '{', 'Ъ': '}', 'Ф': 'A', 'Ы': 'S', 'В': 'D',
    'А': 'F', 'П': 'G', 'Р': 'H', 'О': 'J', 'Л': 'K',
    'Д': 'L', 'Ж': ':', 'Э': '"', 'Я': 'Z', 'Ч': 'X',
    'С': 'C', 'М': 'V', 'И': 'B', 'Т': 'N', 'Ь': 'M',
    'Б': '<', 'Ю': '>', ',': '?', '!': '!', '"': '@',
    '№': '#', ';': '$', '%': '%', ':': '^', '?': '&',
    '*': '*', '(': '(', ')': ')', '_': '_', '+': '+',
    '/': '|', '=': '='}


FORCE_TRANSLATE = {
    'tot': 'еще',
    'еще': 'еще',
    'to`': 'ещё',
}


def correct_layout(text: str) -> str:
    """
    Corrects text typed in the wrong keyboard layout (Russian/English).

    This function detects and corrects text that has been accidentally typed in the wrong keyboard
    layout (e.g., typing Russian using an English keyboard layout).

    It uses a trigram-based approach, comparing the frequency of trigrams in the input text with
    pre-calculated trigram frequencies for both Russian and English languages. If the text is
    likely typed in the wrong layout, it is corrected using a layout mapping.

    Args:
        text (str): The input text to be checked and corrected.

    Returns:
        str: The corrected text if a wrong layout is detected, otherwise the original text.

    Example:
        >>> correct_layout("Ghbdtn")
        "Привет"

        >>> correct_layout("Hello")
        "Hello"
    """
    original_text = text

    text = text.lower()


    if text in FORCE_TRANSLATE:
        new = FORCE_TRANSLATE[text]  # 'tot' -> 'еще'
        result = ""
        for i, char in enumerate(new):
            result += char.upper() if original_text[i].isupper() else char
        my_log.log_layout_switcher(original_text, result)
        return result


    text = re.sub(r'[^a-zа-яё]', '', text)

    russian_count = len(re.findall(r'[а-яё]', text))
    english_count = len(re.findall(r'[a-z]', text))


    total_letters = russian_count + english_count
    if total_letters == 0:
        return original_text

    russian_percent = (russian_count / total_letters) * 100
    english_percent = (english_count / total_letters) * 100

    if russian_percent > 20 and english_percent > 20:
        return original_text


    if english_count > russian_count:
        # Если больше английских букв:
        # 1. Считаем триграммы и их суммы для английского языка от исходного текста
        trigrams = [text[i:i+3] for i in range(len(text) - 2)]
        eng_score_original = sum(TRIGRAM_EN.get(trigram, 0) for trigram in trigrams)

        # 2. Пробуем перевести текст и посчитать для русского
        possible_russian_text = ''.join([LAYOUT_MAP.get(c, c) for c in text])
        trigrams = [possible_russian_text[i:i+3] for i in range(len(possible_russian_text) - 2)]
        rus_score = sum(TRIGRAM_RU.get(trigram, 0) for trigram in trigrams)

        # Сравниваем результаты
        if rus_score > eng_score_original:
            result = ''.join([LAYOUT_MAP.get(c, c) for c in original_text])
            my_log.log_layout_switcher(original_text, result)
            return result
        else:
            return original_text

    elif english_count < russian_count:
        # Если больше русских букв:
        # 1. Считаем триграммы и их суммы для русского языка от исходного текста
        trigrams = [text[i:i+3] for i in range(len(text) - 2)]
        rus_score_original = sum(TRIGRAM_RU.get(trigram, 0) for trigram in trigrams)

        # 2. Пробуем перевести текст и посчитать для английского
        possible_english_text = ''.join([REVERSE_LAYOUT_MAP.get(c, c) for c in text])
        trigrams = [possible_english_text[i:i+3] for i in range(len(possible_english_text) - 2)]
        eng_score = sum(TRIGRAM_EN.get(trigram, 0) for trigram in trigrams)

        # Сравниваем результаты
        if eng_score > rus_score_original:
            result = ''.join([REVERSE_LAYOUT_MAP.get(c, c) for c in original_text])
            my_log.log_layout_switcher(original_text, result)
            return result
        else:
            return original_text

    else:
        return original_text


def init():
    '''
    Initializes the trigram frequency data for Russian and English languages.

    This function processes text corpora for Russian and English languages to calculate
    the frequency of trigrams (sequences of three letters). The calculated trigram frequencies
    are then saved to pickle files ('trigram_eng.dat' and 'trigram_rus.dat') for
    later use in layout correction.

    The function assumes the availability of text files ('d:/downloads/eng.txt' and 'd:/downloads/rus.txt')
    containing English and Russian text corpora, respectively.  These files should contain a substantial
    amount of text, ideally the equivalent of several large books combined into a single text file,
    to ensure accurate trigram frequency calculations.

    Note: This function needs to be run only once to generate the trigram data files.
    '''

    with open('d:/downloads/eng.txt', 'r', encoding='utf8') as f:
        text = f.read()

    result = re.sub(r'[^a-zA-Z]', '', text).lower()

    trigrams = []
    for i in range(len(result) - 2):
        trigrams.append(result[i:i+3])

    trigram_counts = Counter(trigrams)

    total_trigrams = len(trigrams)

    trigram_weights = {}
    for trigram, count in trigram_counts.items():
        trigram_weights[trigram] = count / total_trigrams * 100

    # Сохраняем результаты в файл trigram_eng.dat
    with open('trigram_eng.dat', 'wb') as f:
        pickle.dump(trigram_weights, f)

    print("Результаты сохранены в файл trigram_eng.dat")




    with open('d:/downloads/rus.txt', 'r', encoding='utf8') as f:
        text = f.read()

    result = re.sub(r'[^а-яА-ЯёЁ]', '', text).lower()

    trigrams = []
    for i in range(len(result) - 2):
        trigrams.append(result[i:i+3])

    trigram_counts = Counter(trigrams)

    total_trigrams = len(trigrams)

    trigram_weights = {}
    for trigram, count in trigram_counts.items():
        trigram_weights[trigram] = count / total_trigrams * 100

    # Сохраняем результаты в файл trigram_rus.dat
    with open('trigram_rus.dat', 'wb') as f:
        pickle.dump(trigram_weights, f)

    print("Результаты сохранены в файл trigram_rus.dat")


def load():
    global TRIGRAM_RU, TRIGRAM_EN

    with open('trigram_rus.dat', 'rb') as f:
        TRIGRAM_RU = pickle.load(f)

    with open('trigram_eng.dat', 'rb') as f:
        TRIGRAM_EN = pickle.load(f)


if __name__ == '__main__':

    init()
    load()

    t = [
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
        'Ytnrf yt gjcktlyz vs ghbdt',
        '~, ndj. yfktdj',
        'Lf ,kznm ye xj jgznm',
    ]

    for x in t:
         print(correct_layout(x))
