#!/usr/bin/env python3


import io
import re
import fitz
import pytesseract
from PIL import Image
import enchant
import gpt_basic


def replace_non_letters_with_spaces(text):
    # Заменяем все символы кроме букв русского, английского и украинского алфавитов на пробелы
    return re.sub(r'[^a-zA-Zа-яА-ЯіІїЇєЄ]+', ' ', text)


#считаем количество распознанных слов
def find_words(text):
    text = replace_non_letters_with_spaces(text)
    # Создаем объект словаря для нужного языка
    en = enchant.Dict("en_US")  # для английского языка
    ru = enchant.Dict("ru_RU")  # для русского языка
    uk = enchant.Dict("uk_UA")  # для украинского языка
    
    r = e = u = 0
    for i in text.split():
        if ru.check(i):
            r += 1
        elif en.check(i):
            e += 1
        elif uk.check(i):
            u += 1
        else:
            pass
            #print(i)
    return r + e + u


#распознаем  текст с картинки из байтовой строки
def get_text_from_image(b):
    language = 'rus+eng+ukr'
    f = io.BytesIO(b)
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
    #if find_words(result) < 5: return ''
    result_cleared = gpt_basic.clear_after_ocr(result)
    return result_cleared


# Определяем функцию для извлечения текста из PDF-файла
def get_text(fileobj):
    text = ''
    with fitz.open(stream=fileobj) as doc:
        for i, page in enumerate(doc):
            p = page.get_pixmap()
            b = p.tobytes()
            text += get_text_from_image(b)
    return text


def detect_image_lang(img_path):
    try:
        osd = pytesseract.image_to_osd(img_path)
        print(osd)
    except Exception as e:
        print(e)


if __name__ == '__main__':
    pass


    #text = replace_non_letters_with_spaces("""one two три
    #                                       раз два опять
    #                                       Что не так""")
    #print(text)
    
    #fo = io.BytesIO(open('1.pdf', 'rb').read())
    #t = get_text(fo)
    #print(t)

    #text="""# выводим результат
    #for paragraph in sentences:
    #for sentence in paragraph:
    #    print(sentence)
    #print()"""
    #print(find_words(text))
