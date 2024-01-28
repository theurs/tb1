#!/usr/bin/env python3


import datetime
import hashlib
import html
import os
import multiprocessing
import random
import re
import requests
import string
import subprocess
import tempfile
import traceback
import platform as platform_module
from urllib.request import urlopen

import qrcode
import prettytable
import telebot
from bs4 import BeautifulSoup
from pylatexenc.latex2text import LatexNodes2Text

import my_log


def count_tokens(messages):
    """
    Count the number of tokens in the given messages.

    Parameters:
        messages (list): A list of messages.

    Returns:
        int: The number of tokens in the messages. Returns 0 if messages is empty.
    """
    # токенты никто из пиратов не считает, так что просто считаем символы
    if messages:
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


def split_text(text: str, chunk_limit: int = 1500):
    """ Splits one string into multiple strings, with a maximum amount of chars_per_string
        characters per string. This is very useful for splitting one giant message into multiples.
        If chars_per_string > 4096: chars_per_string = 4096. Splits by '\n', '. ' or ' ' in exactly
        this priority.

        :param text: The text to split
        :type text: str

        :param chars_per_string: The number of maximum characters per part the text is split to.
        :type chars_per_string: int

        :return: The splitted text as a list of strings.
        :rtype: list of str
    """
    return telebot.util.smart_split(text, chunk_limit)


def split_text_my(text: str, chunk_limit: int = 1500):
    """разбивает текст на части заданной длины не разрывая слова,
    в результате куски могут быть больше чем задано, если в тексте нет пробелов то намного больше Ж)"""
    # создаем пустой список для хранения частей текста
    chunks = []
    # создаем переменную для хранения текущей позиции в тексте
    position = 0
    # пока позиция меньше длины текста
    while position < len(text):
        # находим индекс пробела после лимита
        space_index = text.find(" ", position + chunk_limit)
        # если пробел не найден, то берем весь оставшийся текст
        if space_index == -1:
            space_index = len(text)
        # добавляем часть текста от текущей позиции до пробела в список
        chunks.append(text[position:space_index])
        # обновляем текущую позицию на следующий символ после пробела
        position = space_index + 1
    # возвращаем список частей текста
    return chunks


def platform() -> str:
    """
    Return the platform information.
    """
    return platform_module.platform()


def convert_to_mp3(input_file: str) -> str:
    """
    Converts an audio file to the MP3 format.

    Args:
        input_file (str): The path to the input audio file.

    Returns:
        str: The path to the converted MP3 file.
    """
    # Создаем временный файл с расширением .mp3
    temp_file = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
    temp_file.close()
    output_file = temp_file.name
    os.remove(output_file)
    # Конвертируем аудиофайл в wav с помощью ffmpeg
    command = ["ffmpeg", "-i", input_file, '-b:a', '96k', '-map', 'a', output_file]
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Проверяем, успешно ли прошла конвертация
    if os.path.exists(output_file):
        return output_file
    else:
        return None


def bot_markdown_to_tts(text: str) -> str:
    """меняет текст от ботов так что бы можно было зачитать с помощью функции TTS"""
    
    # переделываем списки на более красивые
    new_text = ''
    for i in text.split('\n'):
        ii = i.strip()
        if ii.startswith('* '):
            i = i.replace('* ', '• ', 1)
        if ii.startswith('- '):
            i = i.replace('- ', '• ', 1)
        new_text += i + '\n'
    text = new_text.strip()

    # 1 или 2 * в 0 звездочек *bum* -> bum
    text = re.sub('\*\*?(.*?)\*\*?', '\\1', text)

    # tex в unicode
    matches = re.findall("\$\$?(.*?)\$\$?", text, flags=re.DOTALL)
    for match in matches:
        new_match = LatexNodes2Text().latex_to_text(match.replace('\\\\', '\\'))
        text = text.replace(f'$${match}$$', new_match)
        text = text.replace(f'${match}$', new_match)

    return text


def bot_markdown_to_html(text: str) -> str:
    # переделывает маркдаун от чатботов в хтмл для телеграма
    # сначала делается полное экранирование
    # затем меняются маркдаун теги и оформление на аналогичное в хтмл
    # при этом не затрагивается то что внутри тегов код, там только экранирование
    # латекс код в тегах $ и $$ меняется на юникод текст

    # экранируем весь текст для html
    text = html.escape(text)
    
    # найти все куски кода между ``` и заменить на хеши
    # спрятать код на время преобразований
    matches = re.findall('```(.*?)```', text, flags=re.DOTALL)
    list_of_code_blocks = []
    for match in matches:
        random_string = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(16))
        list_of_code_blocks.append([match, random_string])
        text = text.replace(f'```{match}```', random_string)

    # тут могут быть одиночные поворяющиеся `, меняем их на '
    text = text.replace('```', "'''")

    matches = re.findall('`(.*?)`', text, flags=re.DOTALL)
    list_of_code_blocks2 = []
    for match in matches:
        random_string = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(16))
        list_of_code_blocks2.append([match, random_string])
        text = text.replace(f'`{match}`', random_string)

    # переделываем списки на более красивые
    new_text = ''
    for i in text.split('\n'):
        ii = i.strip()
        if ii.startswith('* '):
            i = i.replace('* ', '• ', 1)
        if ii.startswith('- '):
            i = i.replace('- ', '• ', 1)
        new_text += i + '\n'
    text = new_text.strip()

    # 1 или 2 * в <b></b>
    text = re.sub('\*\*(.+?)\*\*', '<b>\\1</b>', text)

    # tex в unicode
    matches = re.findall("\$\$?(.*?)\$\$?", text, flags=re.DOTALL)
    for match in matches:
        new_match = LatexNodes2Text().latex_to_text(match.replace('\\\\', '\\'))
        text = text.replace(f'$${match}$$', new_match)
        text = text.replace(f'${match}$', new_match)

    # меняем маркдаун ссылки на хтмл
    text = re.sub(r'\[([^\]]*)\]\(([^\)]*)\)', r'<a href="\2">\1</a>', text)
    # меняем все ссылки на ссылки в хтмл теге кроме тех кто уже так оформлен
    text = re.sub(r'(?<!<a href=")(https?://\S+)(?!">[^<]*</a>)', r'<a href="\1">\1</a>', text)

    # меняем таблицы до возвращения кода
    text = replace_tables(text)

    # меняем обратно хеши на блоки кода
    for match, random_string in list_of_code_blocks2:
        # new_match = html.escape(match)
        new_match = match
        text = text.replace(random_string, f'<code>{new_match}</code>')

    # меняем обратно хеши на блоки кода
    for match, random_string in list_of_code_blocks:
        new_match = match
        text = text.replace(random_string, f'<code>{new_match}</code>')

    text = replace_code_lang(text)

    # text = replace_tables(text)

    return text


def replace_code_lang(t: str) -> str:
    """
    Replaces the code language in the given string with appropriate HTML tags.

    Parameters:
        t (str): The input string containing code snippets.

    Returns:
        str: The modified string with code snippets wrapped in HTML tags.
    """
    result = ''
    state = 0
    for i in t.split('\n'):
        if i.startswith('<code>') and len(i) > 7 and '</code>' not in i:
            result += f'<pre><code class = "language-{i[6:]}">'
            state = 1
        else:
            if state == 1:
                if i == '</code>':
                    result += '</code></pre>'
                    state = 0
                else:
                    result += i + '\n'
            else:
                result += i + '\n'
    return result


def replace_tables(text: str) -> str:
    text += '\n'
    state = 0
    table = ''
    results = []
    for line in text.split('\n'):
        if line.count('|') > 2 and len(line) > 4:
            if state == 0:
                state = 1
            table += line + '\n'
        else:
            if state == 1:
                results.append(table[:-1])
                table = ''
                state = 0

    for table in results:
        x = prettytable.PrettyTable(align = "l",
                                    set_style = prettytable.MSWORD_FRIENDLY,
                                    hrules = prettytable.HEADER,
                                    junction_char = '|')

        lines = table.split('\n')
        header = [x.strip().replace('<b>', '').replace('</b>', '') for x in lines[0].split('|') if x]
        header = [split_long_string(x, header = True) for x in header]
        try:
            x.field_names = header
        except Exception as error:
            my_log.log2(f'tb:replace_tables: {error}')
            continue
        for line in lines[2:]:
            row = [x.strip().replace('<b>', '').replace('</b>', '') for x in line.split('|') if x]
            row = [split_long_string(x) for x in row]
            try:
                x.add_row(row)
            except Exception as error2:
                my_log.log2(f'tb:replace_tables: {error2}')
                continue
        new_table = x.get_string()
        text = text.replace(table, f'<pre><code>{new_table}\n</code></pre>')

    return text


def split_html(text: str, max_length: int = 1500) -> list:
    """
    Split the given HTML text into chunks of maximum length specified by `max_length`.

    Parameters:
        text (str): The HTML text to be split into chunks.
        max_length (int, optional): The maximum length of each chunk. Defaults to 1500.

    Returns:
        list: A list of chunks, where each chunk is a string.
    """
    code_tag = ''
    in_code_mode = 0

    chunks = []
    chunk = ''

    for line in text.split('\n'):
        if line.startswith('<pre><code') and line.find('</code></pre>') == -1:
            in_code_mode = 1
            code_tag = line[:line.find('>', 10) + 1]

        elif line.startswith('<code>') and line.find('</code>') == -1:
            in_code_mode = 2
            code_tag = '<code>'

        elif line.startswith('<b>') and line.find('</b>') == -1:
            in_code_mode = 3
            code_tag = '<b>'

        elif line == '</code></pre>' or line == '</code>' or line == '</b>':
            code_tag = ''
            in_code_mode = 0

        else:
            if len(chunk) + len(line) + 20 > max_length:

                if in_code_mode == 1:
                    chunk += '</code></pre>\n'
                    chunks.append(chunk)
                    chunk = code_tag

                if in_code_mode == 2:
                    chunk += '</code>\n'
                    chunks.append(chunk)
                    chunk = code_tag

                if in_code_mode == 3:
                    chunk += '</b>\n'
                    chunks.append(chunk)
                    chunk = code_tag

                elif in_code_mode == 0:
                    chunks.append(chunk)
                    chunk = ''

        chunk += line + '\n'

    chunks.append(chunk)

    chunks2 = []
    for chunk in chunks:
        if len(chunk) > max_length:
            chunks2 += split_text(chunk, max_length)
        else:
            chunks2.append(chunk)

    return chunks2


def text_to_qrcode(text: str) -> str:
    """Преобразует текст в qr-код"""
    try:
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        return img
    except Exception as error:
        print(f'utils:qr: {error}')
        my_log.log2(f'utils:qr: {error}')
    return None


def get_tmp_fname() -> str:
    """
    Generate a temporary file name.

    Returns:
        str: The name of the temporary file.
    """
    with tempfile.NamedTemporaryFile(delete=True) as temp_file:
        return temp_file.name


def split_long_string(long_string: str, header = False, MAX_LENGTH = 24) -> str:
    if len(long_string) <= MAX_LENGTH:
        return long_string
    if header:
        return long_string[:MAX_LENGTH-2] + '..'
    split_strings = []
    while len(long_string) > MAX_LENGTH:
        split_strings.append(long_string[:MAX_LENGTH])
        long_string = long_string[MAX_LENGTH:]

    if long_string:
        split_strings.append(long_string)

    result = "\n".join(split_strings) 
    return result


def get_page_name(url: str) -> str:
    try:
        soup = BeautifulSoup(urlopen(url), features="lxml")
        return soup.title.get_text()
    except:
        return ''


def get_page_names(urls):
    with multiprocessing.Pool(processes=10) as pool:
        results = pool.map(get_page_name, urls)
    return results
    # return [x for x in map(get_page_name, urls)]


def is_image_link(url: str) -> bool:
  """Проверяет, является ли URL-адрес ссылкой на картинку.

  Args:
    url: URL-адрес изображения.

  Returns:
    True, если URL-адрес ссылается на картинку, иначе False.
  """

  try:
    # response = requests.get(url, timeout=2, stream=True)
    content = b''
    response = requests.get(url, stream=True, timeout=10)
    # Ограничиваем размер
    for chunk in response.iter_content(chunk_size=1024):
        content += chunk
        if len(content) > 50000:
            break
    content_type = response.headers['Content-Type']
    return content_type.startswith('image/')
  except:
    return False


def download_image_as_bytes(url: str) -> bytes:
    """Загружает изображение по URL-адресу и возвращает его в виде байтов.

    Args:
        url: URL-адрес изображения.

    Returns:
        Изображение в виде байтов.
    """

    try:
        response = requests.get(url, timeout=10)
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log2(f'download_image_as_bytes: {error}\n\n{error_traceback}')
        return None
    return response.content


def nice_hash(s: str, l: int = 12) -> str:
    """
    Generate a nice hash of the given string.

    Parameters:
        s (str): The string to hash.

    Returns:
        str: The nice hash of the string.
    """
    hash_object = hashlib.sha224(s.encode())
    return f'{hash_object.hexdigest()[:l]}'


def get_full_time() -> str:
    """
    Get the current time with a GMT time offset.

    Returns:
        str: A string representing the current time in the format "YYYY-MM-DD HH:MM:SS TZ".
    """
    now = datetime.datetime.now()
    time_string = now.strftime("%Y-%m-%d %H:%M:%S %Z")
    return time_string


def mime_from_buffer(data: bytes) -> str:
    """
    Get the MIME type of the given buffer.

    Parameters:
        data (bytes): The buffer to get the MIME type of.

    Returns:
        str: The MIME type of the buffer.
    """
    pdf_signature = b'%PDF-1.'
    epub_signature = b'%!PS-Adobe-3.0'
    docx_signature = b'\x00\x00\x00\x0c'
    doc_signature = b'PK\x03\x04'
    html_signature = b'<!DOCTYPE html>'
    odt_signature = b'<!DOCTYPE html>'
    rtf_signature = b'<!DOCTYPE html>'
    xlsx_signature = b'\x50\x4b\x03\x04'

    if data.startswith(pdf_signature):
        return 'application/pdf'
    elif data.startswith(epub_signature):
        return 'application/epub+zip'
    elif data.startswith(docx_signature):
        return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    elif data.startswith(doc_signature):
        return 'application/msword'
    elif data.startswith(html_signature):
        return 'text/html'
    elif data.startswith(odt_signature):
        return 'application/vnd.oasis.opendocument.text'
    elif data.startswith(rtf_signature):
        return 'text/rtf'
    elif data.startswith(xlsx_signature):
        return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    else:
        return 'plain'


def seconds_to_str(seconds: float) -> str:
    """
    Convert seconds to a string in the format "HH:MM:SS".

    Parameters:
        seconds (float): The number of seconds to convert.

    Returns:
        str: A string representing the time in the format "HH:MM:SS".
    """
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    return f'{hours:02}:{minutes:02}:{seconds:02}'


if __name__ == '__main__':
    
    print(seconds_to_str('360,20'))