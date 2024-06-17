#!/usr/bin/env python3


import cachetools.func
import concurrent.futures
import io
import re
import threading
from PIL import Image


import enchant
import pymupdf
import pytesseract

import my_gemini


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
@cachetools.func.ttl_cache(maxsize=10, ttl=10 * 60)
def get_text_from_image(data: bytes, language: str = 'rus+eng') -> str:
    """
    Extracts text from an image.

    Args:
        data (bytes): The image data as bytes.

    Returns:
        str: The extracted text from the image.
    """

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

    # if 'Windows' not in utils.platform():
    #     if find_words(result) < 4: return ''

    return result


@cachetools.func.ttl_cache(maxsize=10, ttl=10 * 60)
def ocr_image(index: int, image_bytes: bytes, lang: str) -> tuple[int, str]:
    """ 
    Perform OCR on an image and return the text.
    """
    t = my_gemini.ocr(image_bytes, lang)
    if not t:
        t = get_text_from_image(image_bytes, lang)
    if t:
        return index, t
    else:
        return index, ''


def get_text_from_pdf(data: bytes, lang: str = 'rus+eng') -> str:
    """
    Extracts text from a PDF file.

    Args:
        data (bytes): The PDF file data as bytes.
        lang (str): The language to use for OCR. Default is 'rus+eng'.

    Returns:
        str: The extracted text from the PDF file.
    """
    images = []

    doc = pymupdf.open(stream=data, filetype="pdf")
    n = 1
    for page_index, page in enumerate(doc): # iterate over pdf pages
        page = doc[page_index] # get the page
        image_list = page.get_images()
        for im in image_list:
            xref = im[0]
            base = doc.extract_image(xref)
            image_bytes = base["image"]
            image_ext = base["ext"]
            image = Image.open(io.BytesIO(image_bytes))

            # Append image to images list for OCR processing
            image_bytes = io.BytesIO()
            image.save(image_bytes, format=image_ext.upper())
            images.append((n, image_bytes.getvalue()))
            n += 1

    if images:
        text = ''
    else:
        return ''

    # Use concurrent futures for parallel OCR processing
    with concurrent.futures.ThreadPoolExecutor() as executor:
        # Limit to 50 images for OCR processing, if longer, process only the first 50
        future_to_image = {executor.submit(ocr_image, idx, im, lang): idx for idx, im in images[:50]}
        results = []
        for future in concurrent.futures.as_completed(future_to_image):
            try:
                results.append(future.result())
            except Exception as exc:
                results.append((future_to_image[future], f"Exception occurred during OCR processing: {exc}n"))

        # Sort results by index to ensure the correct order
        results.sort(key=lambda x: x[0])
        for _, value in results:
            text += value

    return text


if __name__ == '__main__':
    pass

    data = open('1.pdf', 'rb').read()
    print(get_text_from_pdf(data))
