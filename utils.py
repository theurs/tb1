#!/usr/bin/env python3


import datetime
import functools
import hashlib
import io
import html
import os
import pathlib
import pytz
import random
import re
import regex
import requests
import string
import subprocess
import sys
import tempfile
import threading
import platform as platform_module

import PIL
import prettytable
import telebot
from pylatexenc.latex2text import LatexNodes2Text

import my_log


def async_run(func):
    '''Декоратор для запуска функции в отдельном потоке, асинхронно'''
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        thread = threading.Thread(target=func, args=args, kwargs=kwargs)
        thread.start()
    return wrapper


def get_file_ext(fname: str) -> str:
    '''return extension of file using pathlib'''
    try:
        p = pathlib.Path(fname)
        return p.suffix
    except Exception as error:
        my_log.log2(f'utils:get_file_ext {error}\n{fname}')
        return ''


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
    matches = re.findall(r"(?:\$\$?|\\\[|\\\(|\\\[)(.*?)(?:\$\$?|\\\]|\\\)|\\\])", text, flags=re.DOTALL)
    for match in matches:
        new_match = LatexNodes2Text().latex_to_text(match.replace('\\\\', '\\'))
        text = text.replace(f'$${match}$$', new_match)
        text = text.replace(f'${match}$', new_match)
        text = text.replace(f'\[{match}\]', new_match)
        text = text.replace(f'\({match}\)', new_match)

    # Регулярное выражение для поиска всех символов, кроме букв, цифр и знаков препинания
    pattern = regex.compile(r'[^\p{L}\p{N}\p{P} ]', re.UNICODE)
    # Замена всех найденных символов на пустую строку
    text = pattern.sub('', text)

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
    matches = re.findall('```(.*?)```\n', text, flags=re.DOTALL)
    list_of_code_blocks = []
    for match in matches:
        random_string = str(hash(match))
        list_of_code_blocks.append([match, random_string])
        text = text.replace(f'```{match}```', random_string)

    matches = re.findall('```(.*?)```', text, flags=re.DOTALL)
    for match in matches:
        random_string = str(hash(match))
        list_of_code_blocks.append([match, random_string])
        text = text.replace(f'```{match}```', random_string)

    # тут могут быть одиночные поворяющиеся `, меняем их на '
    text = text.replace('```', "'''")

    matches = re.findall('`(.*?)`', text)
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
            i = i.replace('- ', '– ', 1)
        new_text += i + '\n'
    text = new_text.strip()

    # 2,3,4 # в начале строки меняем всю строку на жирный текст
    text = re.sub('^#### (.*)$', '<b>\\1</b>', text, flags=re.MULTILINE)
    text = re.sub('^### (.*)$', '<b>\\1</b>', text, flags=re.MULTILINE)
    text = re.sub('^## (.*)$', '<b>\\1</b>', text, flags=re.MULTILINE)
    # точка пробел три хеша и пробел в начале тоже делать жирным
    text = re.sub('^\. ### (.*)$', '<b>\\1</b>', text, flags=re.MULTILINE)
    text = re.sub('^\.  ## (.*)$', '<b>\\1</b>', text, flags=re.MULTILINE)
    text = re.sub('^\.  ### (.*)$', '<b>\\1</b>', text, flags=re.MULTILINE)
    text = re.sub('^\.  #### (.*)$', '<b>\\1</b>', text, flags=re.MULTILINE)

    # 1 или 2 * в <b></b>
    text = re.sub('\*\*(.+?)\*\*', '<b>\\1</b>', text)

    # tex в unicode
    matches = re.findall(r"(?:\$\$?|\\\[|\\\(|\\\[)(.*?)(?:\$\$?|\\\]|\\\)|\\\])", text, flags=re.DOTALL)
    for match in matches:
        new_match = LatexNodes2Text().latex_to_text(match.replace('\\\\', '\\'))
        text = text.replace(f'$${match}$$', new_match)
        text = text.replace(f'${match}$', new_match)
        text = text.replace(f'\[{match}\]', new_match)
        text = text.replace(f'\({match}\)', new_match)


    # меняем маркдаун ссылки на хтмл
    # text = re.sub(r'\[([^\]]*)\]\(([^\)]*)\)', r'<a href="\2">\1</a>', text)
    text = re.sub('''\[(.*?)\]\((https?://\S+)\)''', r'<a href="\2">\1</a>', text)

    # меняем все ссылки на ссылки в хтмл теге кроме тех кто уже так оформлен
    # а зачем собственно? text = re.sub(r'(?<!<a href=")(https?://\S+)(?!">[^<]*</a>)', r'<a href="\1">\1</a>', text)

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
                    result += '</code></pre>\n'
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
        response = requests.get(url, timeout=30)
    except Exception as error:
        # error_traceback = traceback.format_exc()
        # my_log.log2(f'download_image_as_bytes: {error}\n\n{error_traceback}')
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
    now = datetime.datetime.now(pytz.timezone('Europe/Moscow'))
    time_string = now.strftime("%Y-%m-%d %H:%M:%S %Z")
    return time_string


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


def get_username_for_log(message) -> str:
    """
    Returns the username for logging purposes based on the given message.

    Args:
        message: The message object to extract the username from.
                 My be a group of messages (list).

    Returns:
        str: The username for logging.
    """
    if isinstance(message, list):
        message = message[0]

    if message.chat.type == 'private':
        return message.from_user.full_name or message.from_user.username or 'noname'
    else:
        if message.is_topic_message:
            return f'[{message.chat.title or message.chat.username or message.chat.first_name or "nonamechat"}] [{message.message_thread_id}]'
        else:
            return message.chat.title or message.chat.username or message.chat.first_name or 'nonamechat'


def safe_fname(s: str) -> str:
    """Return a safe filename for the given string, truncated to 250 bytes in UTF-8 encoding."""
    
    # Replace invalid characters
    s = re.sub(r'[\\/*?:"<>|]', '_', s)
    
    # Encode to UTF-8 and check length
    encoded_s = s.encode('utf-8')
    if len(encoded_s) <= 250:
        return s
    
    # Shorten filename if longer than 250 bytes
    while len(encoded_s) > 247:
        s = s[:len(s)//2-3] + '___' + s[len(s)//2+3:]
        encoded_s = s.encode('utf-8')
    return s


def remove_file(fname: str):
    '''Удаляет файл по имени'''
    try:
        os.unlink(fname)
        return True
    except Exception as error:
        # my_log.log2(f'utils:remove_file: {fname}\n\n{error}')
        return False


def mime_from_buffer(data: bytes) -> str:
    """
    Get the MIME type of the given buffer.

    Parameters:
        data (bytes): The buffer to get the MIME type of.

    Returns:
        str: The MIME type of the buffer.
    """
    pdf_signature = b'%PDF-1.'

    if data.startswith(pdf_signature):
        return 'application/pdf'
    return 'plain'


def get_codepage():
    if 'windows' in platform().lower():
        result = subprocess.getoutput("chcp")
        return f'cp{result.split()[-1]}'
    else:
        result = subprocess.getoutput("locale charmap")
        return result.lower()


def make_collage(images: list) -> bytes:
    """Создает коллаж из списка изображений, располагая их по 2 картинки в ряд. 
    Учитывает разный размер картинок, чтобы избежать наплывания.

    Args:
        images (list): Список байтовых строк, представляющих изображения.

    Returns:
        bytes: Байтовая строка, представляющая итоговое изображение коллажа.
    """

    images = [PIL.Image.open(io.BytesIO(img)) for img in images]

    collage_width = 0
    collage_height = 0
    x_offset = 0
    y_offset = 0

    for i, img in enumerate(images):
        # Вычисляем ширину ряда (2 картинки)
        if i % 2 == 0:
            row_width = sum([img.width for img in images[i:i+2]])
            collage_width = max(collage_width, row_width)  # Обновляем ширину коллажа

        # Размещаем картинку
        collage_height = max(collage_height, y_offset + img.height)
        x_offset += img.width

        # Переходим на следующий ряд
        if (i + 1) % 2 == 0:
            y_offset += max([img.height for img in images[i-1:i+1]])  # Максимальная высота картинок в ряду
            x_offset = 0

        # Создаем новый образ для коллажа с учетом вычисленных размеров после обработки всех картинок
        if i == len(images) - 1:
            collage = PIL.Image.new('RGB', (collage_width, collage_height))

            # Вставляем изображения в коллаж
            x_offset = 0
            y_offset = 0
            for j, img in enumerate(images):
                collage.paste(img, (x_offset, y_offset))
                x_offset += img.width
                if (j + 1) % 2 == 0:
                    y_offset += max([img.height for img in images[j-1:j+1]])  # Максимальная высота картинок в ряду
                    x_offset = 0

    # Сохраняем результат в буфер
    result_image_as_bytes = io.BytesIO()
    collage.save(result_image_as_bytes, format='PNG')
    result_image_as_bytes.seek(0)
    return result_image_as_bytes.read()


if __name__ == '__main__':
    pass

    print(bot_markdown_to_tts("Привет, мир! Hello, world! 123 こんにちは 你好 В этом примере регулярноwor😘😗☺️😚😙🥲😋😛😜🤪😝🤑🤗🤭🫢🫣🤫🤔🫡🤐🤨😐😑😶🫥😶‍🌫️😏😒🙄😬😮‍💨🤥🫨😌😔ldе выражение r'[^\p{L}\p{N}\p{P}]' находит все символы, которые не являются буквами, цифрами или знаками препинания, и заменяет их на пустую строку. Класс символов \p{L} соответствует всем буквам, \p{N} — всем цифрам, а \p{P} — всем знакам препинания."))

    # print(get_codepage())
    # print(get_file_ext('c:\\123\123123.23'))
    # print(safe_fname('dfgdшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшггггггггггггггггггггггггггггшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшfg\/dfg.tb'))
    t=r"""рш еруку

## Реализовать распознавание голосовых команд пользователя с помощью библиотеки Vosk и ресурса https://speechpad.ru/.

.  ## Для этого необходимо настроить библиотеку Vosk и подключиться к ресурсу https://speechpad.ru/. Затем необходимо создать функцию, которая будет принимать на вход аудиоданные и возвращать распознанный текст.
[hi](https://example.com/123(123))
[hi](https://example.com/123123)

**Шаг 3:**
. ### 135 выберите библиотеку Vosk
    """
    # print(bot_markdown_to_html(t))


    # print(get_full_time())

    # counter = MessageCounter()
    # print(counter.status('user1'))
    # counter.increment('user1', 5)
    # print(counter.status('user1'))
    # counter.increment('user1', 1)
    # print(counter.status('user1'))

    pass
