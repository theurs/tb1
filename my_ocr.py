#!/usr/bin/env python3


import io
import re
import threading
from PIL import Image

import enchant
import fitz
import pytesseract

import gpt_basic
import utils
import my_log


# запрещаем запускать больше чем 1 процесс распознавания
lock = threading.Lock()


def replace_non_letters_with_spaces(text):
    # Заменяем все символы кроме букв русского, английского и украинского алфавитов на пробелы
    return re.sub(r'[^a-zA-Zа-яА-ЯіІїЇєЄ]+', ' ', text)


#считаем количество распознанных слов
def find_words(text):
    """
    Find the number of words in the given text that belong to different languages.
    
    Args:
        text (str): The input text.
        
    Returns:
        int: The total count of words that belong to different languages.
    """
    text = replace_non_letters_with_spaces(text)
    # Создаем объект словаря для нужного языка
    en = enchant.Dict("en_US")  # для английского языка
    ru = enchant.Dict("ru_RU")  # для русского языка
    #uk = enchant.Dict("uk_UA")  # для украинского языка
    
    r = e = u = 0
    for i in text.split():
        if ru.check(i):
            r += 1
        elif en.check(i):
            e += 1
        #elif uk.check(i):
        #    u += 1
        else:
            pass

    return r + e + u


#распознаем  текст с картинки из байтовой строки
def get_text_from_image(data: bytes) -> str:
    """
    Extracts text from an image.

    Args:
        data (bytes): The image data as bytes.

    Returns:
        str: The extracted text from the image.
    """

    #language = 'rus+eng+ukr'
    language = 'rus+eng'
    f = io.BytesIO(data)

    with lock:
        r1 = pytesseract.image_to_string(Image.open(f), lang=language)
    
    # склеиваем разорванные предложения
    lines = r1.split('\n')
    result = lines[0] + ' '
    for i in lines[1:]:
        if i == '':
            result = result[:-1]
            result += '\n\n'
            continue
        result += i + ' '

    result = result[:-1]

    if 'Windows' not in utils.platform():
        if find_words(result) < 4: return ''

    result_cleared = gpt_basic.clear_after_ocr(result)
    return result_cleared


# Определяем функцию для извлечения текста из PDF-файла
def get_text(fileobj):
    """
    Extracts text from a PDF file.

    Parameters:
        fileobj (file-like object): The PDF file object to extract text from.

    Returns:
        str: The extracted text from the PDF file.
    """
    text = ''
    max = 5 # распознаем не больше 5 страниц
    with fitz.open(stream=fileobj) as doc:
        for i, page in enumerate(doc):

            max -= 1
            if max == 0: break

            p = page.get_pixmap()
            b = p.tobytes()
            text += get_text_from_image(b)
    return text


def ocr(input_file):
    """распознает текст из файла"""
    return get_text_from_image(open(input_file, 'rb').read())


if __name__ == '__main__':
    pass

    print(ocr('1.jpg'))
