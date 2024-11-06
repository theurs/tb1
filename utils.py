#!/usr/bin/env python3

import ast
import concurrent.futures
import datetime
import functools
import hashlib
import io
import json
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
import traceback
import platform as platform_module
from typing import Union, Optional

import json_repair
import PIL
import prettytable
import telebot
from pylatexenc.latex2text import LatexNodes2Text
from pillow_heif import register_heif_opener
from prettytable import PrettyTable
from textwrap import wrap

import my_log


register_heif_opener()


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


    # Словарь подстрочных символов
    subscript_map = {
        '0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄', '5': '₅',
        '6': '₆', '7': '₇', '8': '₈', '9': '₉',
        '+': '₊', '-': '₋', '=': '₌', '(': '₍', ')': '₎',
        'a': 'ₐ',
        # 'b': '♭', 
        'c': '꜀',
        # 'd': 'ᑯ',
        'e': 'ₑ',
        # 'f': '⨍',
        'g': '₉',
        'h': 'ₕ',
        'i': 'ᵢ',
        'j': 'ⱼ',
        'k': 'ₖ',
        'l': 'ₗ',
        'm': 'ₘ',
        'n': 'ₙ',
        'o': 'ₒ',
        'p': 'ₚ',
        # 'q': '૧',
        'r': 'ᵣ',
        's': 'ₛ',
        't': 'ₜ',
        'u': 'ᵤ',
        'v': 'ᵥ',
        # 'w': 'w',
        'x': 'ₓ',
        'y': 'ᵧ',
        'z': '₂'
    }

    # Словарь надстрочных символов
    superscript_map = {
        '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵',
        '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
        '+': '⁺', '-': '⁻', '=': '⁼', '(': '⁽', ')': '⁾',
        'a': 'ᵃ',
        'b': 'ᵇ',
        'c': 'ᶜ',
        'd': 'ᵈ',
        'e': 'ᵉ',
        'f': 'ᶠ',
        'g': 'ᵍ',
        'h': 'ʰ',
        'i': 'ⁱ',
        'j': 'ʲ',
        'k': 'ᵏ',
        'l': 'ˡ',
        'm': 'ᵐ',
        'n': 'ⁿ',
        'o': 'ᵒ',
        'p': 'ᵖ',
        'q': '𐞥', 
        'r': 'ʳ',
        's': 'ˢ',
        't': 'ᵗ',
        'u': 'ᵘ',
        'v': 'ᵛ',
        'w': 'ʷ',
        'x': 'ˣ',
        'y': 'ʸ',
        'z': 'ᶻ'
    }

    # экранируем весь текст для html
    text = html.escape(text)

    # заменяем странный способ обозначения кода когда идет 0-6 пробелов в начале потом ` или `` или ``` и название языка
    pattern = r"^ {0,6}`{1,3}(\w+)\n(.*?)\n  {0,6}`{1,3}$"
    # replacement = r"```\1\n\2\n```"
    replacement = lambda match: f"```{match.group(1)}\n{re.sub(r'^ {1,6}', '', match.group(2), flags=re.MULTILINE)}\n```"
    text = re.sub(pattern, replacement, text, flags=re.MULTILINE | re.DOTALL)


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

    # замена тегов <sub> <sup> на подстрочные и надстрочные символы
    text = re.sub(r'&lt;sup&gt;(.*?)&lt;/sup&gt;', lambda m: ''.join(superscript_map.get(c, c) for c in m.group(1)), text)
    text = re.sub(r'&lt;sub&gt;(.*?)&lt;/sub&gt;', lambda m: ''.join(subscript_map.get(c, c) for c in m.group(1)), text)

    # тут могут быть одиночные поворяющиеся `, меняем их на '
    text = text.replace('```', "'''")

    matches = re.findall('`(.*?)`', text)
    list_of_code_blocks2 = []
    for match in matches:
        random_string = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(16))
        list_of_code_blocks2.append([match, random_string])
        text = text.replace(f'`{match}`', random_string)

    # переделываем списки на более красивые
    text = re.sub(r"^(\s*)\*\s", r"\1• ", text, flags=re.MULTILINE)
    text = re.sub(r"^(\s*)-\s", r"\1– ", text, flags=re.MULTILINE)

    # 1,2,3,4 # в начале строки меняем всю строку на жирный текст
    # text = re.sub(r"^(?:\.\s)?#(?:#{2,})\s(.*)$", r"<b>▏\1</b>", text, flags=re.MULTILINE)  # 3+ hashes
    # text = re.sub(r"^(?:\.\s)?##\s(.*)$", r"<b>▌ \1</b>", text, flags=re.MULTILINE)  # 2 hashes
    # text = re.sub(r"^(?:\.\s)?#\s(.*)$", r"<b>█ \1</b>", text, flags=re.MULTILINE)  # 1 hash
    text = re.sub(r"^(?:\.\s)?#(?:#{0,})\s(.*)$", r"<b>\1</b>", text, flags=re.MULTILINE)  # 1+ hashes

    # цитаты начинаются с &gt; их надо заменить на <blockquote></blockquote>
    # &gt; должен быть либо в начале строки, либо сначала пробелы потом &gt;
    # если несколько подряд строк начинаются с &gt; то их всех надо объединить в один блок <blockquote>
    def process_quotes(text):
        # Разбиваем текст на строки
        lines = text.split('\n')
        result = []
        quote_lines = []
        
        for line in lines:
            # Проверяем, является ли строка цитатой (с учетом пробелов в начале)
            if re.match('^\s*&gt;\s*(.*)$', line):
                # Извлекаем текст после &gt;
                quote_content = re.sub('^\s*&gt;\s*(.*)$', '\\1', line)
                quote_lines.append(quote_content)
            else:
                # Если накопились цитаты, добавляем их в результат
                if quote_lines:
                    quote_text = '\n'.join(quote_lines)
                    result.append(f'<blockquote>{quote_text}</blockquote>')
                    quote_lines = []
                result.append(line)
        
        # Добавляем оставшиеся цитаты в конце текста
        if quote_lines:
            quote_text = '\n'.join(quote_lines)
            result.append(f'<blockquote>{quote_text}</blockquote>')
        
        return '\n'.join(result)

    text = process_quotes(text)


    # заменить двойные и тройные пробелы в тексте (только те что между буквами и знаками препинания)
    text = re.sub(r"(?<=\S) {2,}(?=\S)", " ", text)

    # 2 * в <b></b>
    text = re.sub('\*\*(.+?)\*\*', '<b>\\1</b>', text)
    text = re.sub(r'^\*\*(.*?)\*\*$', r'<b>\1</b>', text, flags=re.MULTILINE | re.DOTALL)

    # 2 _ в <i></i>
    text = re.sub('\_\_(.+?)\_\_', '<i>\\1</i>', text)
    text = re.sub(r'^\_\_(.*?)\_\_$', r'<i>\1</i>', text, flags=re.MULTILINE | re.DOTALL)

    # Замена _*текст*_ на <i>текст</i>
    text = re.sub(r"(?<!\w)_\*([^\n\s].*?[^\n\s])\*_(?!\w)", r"<i>\1</i>", text)

    # 1 _ в <i></i>
    text = re.sub(r"(?<!\w)_([^\n\s_*][^\n*_]*[^\n\s_*])_(?!\w)", r"<i>\1</i>", text)

    # Замена *текст* на <i>текст</i>
    text = re.sub(r"(?<!\w)\*(?!\s)([^\n*]+?)(?<!\s)\*(?!\w)", r"<i>\1</i>", text)

    # Замена ~~текст~~ на <s>текст</s>
    text = re.sub(r"(?<!\w)~~(?!\s)([^\n*]+?)(?<!\s)~~(?!\w)", r"<s>\1</s>", text)

    # Замена ||текст|| на <tg-spoiler>текст</tg-spoiler>
    text = re.sub(r"(?<!\w)\|\|(?!\s)([^\n*]+?)(?<!\s)\|\|(?!\w)", r"<tg-spoiler>\1</tg-spoiler>", text)

    # замена <b><i> ... </b></i> на <b><i> ... </i></b>
    text = re.sub(r"<b><i>(.+?)</b></i>", r"<b><i>\1</i></b>", text)
    text = re.sub(r"<i><b>(.+?)</i></b>", r"<i><b>\1</b></i>", text)

    # tex в unicode
    matches = re.findall(r"(?:\$\$?|\\\[|\\\(|\\\[)(.*?)(?:\$\$?|\\\]|\\\)|\\\])", text, flags=re.DOTALL)
    for match in matches:
        new_match = LatexNodes2Text().latex_to_text(match.replace('\\\\', '\\'))
        text = text.replace(f'$${match}$$', new_match)
        text = text.replace(f'${match}$', new_match)
        text = text.replace(f'\[{match}\]', new_match)
        text = text.replace(f'\({match}\)', new_match)

    def latex_to_text(latex_formula):
        # Здесь должна быть реализация преобразования LaTeX в текст
        # В данном примере просто возвращаем формулу без изменений
        r = LatexNodes2Text().latex_to_text(latex_formula).strip()
        return r

    def replace_function_lt1(match):
        latex_code = match.group(2) if match.group(2) is not None else match.group(3) if match.group(3) is not None else match.group(4)
        return latex_to_text(latex_code)

    pattern = r"\\begin\{(.*?)\}(.*?)\\end\{\1\}|\\\[(.*?)\\\]|\\begin(.*?)\\end"
    text = re.sub(pattern, replace_function_lt1, text, flags=re.DOTALL)


    # меняем маркдаун ссылки на хтмл
    text = re.sub('''\[(.*?)\]\((https?://\S+)\)''', r'<a href="\2">\1</a>', text)

    # меняем все ссылки на ссылки в хтмл теге кроме тех кто уже так оформлен
    # а зачем собственно? text = re.sub(r'(?<!<a href=")(https?://\S+)(?!">[^<]*</a>)', r'<a href="\1">\1</a>', text)

    # хз откуда это
    text = text.replace('&#x27;', "'")
    text = text.replace('   #x27;', "'")
    text = text.replace('#x27;', "'")

    # меняем обратно хеши на блоки кода
    for match, random_string in list_of_code_blocks2:
        # new_match = html.escape(match)
        new_match = match
        text = text.replace(random_string, f'<code>{new_match}</code>')

    # меняем обратно хеши на блоки кода
    for match, random_string in list_of_code_blocks:
        new_match = match
        text = text.replace(random_string, f'<code>{new_match}</code>')

    # меняем таблицы до возвращения кода
    text = replace_tables(text)

    text = replace_code_lang(text)

    text = text.replace('<pre><code class="language-plaintext">\n<pre><code>', '<pre><code class="language-plaintext">')

    # убрать 3 и более пустые сроки подряд (только после блоков кода или любых тегов)
    # text = re.sub(r"^\s*$", r"\n", text, flags=re.MULTILINE)
    # text = re.sub(r'>\n{4,}', '>\n\n\n', text)
    def replace_newlines(match):
        return '\n\n'
    text = re.sub(r"(?<!<pre>)(?<!<code>)\n{3,}(?!</code>)(?!</pre>)", replace_newlines, text, flags=re.DOTALL)
    # text = re.sub(r">\n{2,}", ">\n", text)
    # text = re.sub(r"code>\n{2,}", "code>\n", text)
    text = re.sub(r"pre>\n{2,}", "pre>\n", text)

    return text


def replace_code_lang(t: str) -> str:
    """
    Replaces the code language in the given string with appropriate HTML tags.
    Adds "language-plaintext" class if no language is specified but <code> tags are present.
    Does not add language class for single-line code snippets.
    Parameters:
        t (str): The input string containing code snippets.
    Returns:
        str: The modified string with code snippets wrapped in HTML tags.
    """
    result = ''
    code_content = ''
    state = 0
    lines = t.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]
        if state == 0 and line.startswith('<code>'):
            # Начало блока кода
            if '</code>' in line:
                # Однострочный код
                result += line + '\n'  # Оставляем без изменений
            else:
                lang = line[6:].strip().lower()
                if lang == 'c++':
                    lang = 'cpp'
                elif not lang:
                    lang = 'plaintext'
                result += f'<pre><code class="language-{lang}">'
                state = 1
                code_content = ''  # Не добавляем первую строку, так как она содержит только тег
        elif state == 1:
            if '</code>' in line:
                # Конец блока кода
                code_content += line[:line.index('</code>')]
                result += code_content + '</code></pre>\n'
                state = 0
            else:
                code_content += line + '\n'
        else:
            result += line + '\n'
        i += 1
    result = re.sub(r"\n{2,}</code>", "\n</code>", result)
    return result


def replace_tables(text: str, max_width: int = 80, max_cell_width: int = 20, ) -> str:
    """
    Заменяет markdown таблицы на их prettytable представление.
    Улучшена обработка различных форматов таблиц, включая ограничение ширины и обрезание длинных заголовков.
    
    :param text: Исходный текст с markdown таблицами
    :param max_width: Максимальная ширина таблицы в символах
    :param max_cell_width: Максимальная ширина ячейки в символах
    :return: Текст с замененными таблицами
    """
    text += '\n'

    def is_valid_separator(line: str) -> bool:
        if not line or not line.strip('| '):
            return False
        parts = line.strip().strip('|').split('|')
        return all(part.strip().replace('-', '').replace(':', '') == '' for part in parts)

    def is_valid_table_row(line: str) -> bool:
        return line.strip().startswith('|') and line.strip().endswith('|')

    def strip_tags(text: str) -> str:
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        text = text.replace('&quot;', '"')
        text = text.replace('&#x27;', "'")
        text = text.replace('<b>', '   ')
        text = text.replace('<i>', '   ')
        text = text.replace('</b>', '    ')
        text = text.replace('</i>', '    ')
        text = text.replace('<br>', '    ')
        return text

    def truncate_text(text: str, max_width: int) -> str:
        text = strip_tags(text)
        if len(text) <= max_width:
            return text
        return text[:max_width-3] + '...'

    def wrap_long_text(text: str, max_width: int) -> str:
        text = strip_tags(text)
        if len(text) <= max_width:
            return text
        return '\n'.join(wrap(text, max_width))

    def process_table(table_text: str) -> str:
        lines = table_text.strip().split('\n')
        x = PrettyTable()
        x.header = True
        x.hrules = 1

        # Находим заголовок и разделитель
        header_index = next((i for i, line in enumerate(lines) if is_valid_table_row(line)), None)
        if header_index is None:
            return table_text

        separator_index = next((i for i in range(header_index + 1, len(lines)) if is_valid_separator(lines[i])), None)
        if separator_index is None:
            return table_text

        # Обработка заголовка
        header = [truncate_text(cell.strip(), max_cell_width) for cell in lines[header_index].strip('|').split('|') if cell.strip()]
        x.field_names = header

        # Настройка выравнивания на основе разделителя
        alignments = []
        for cell in lines[separator_index].strip('|').split('|'):
            cell = cell.strip()
            if cell.startswith(':') and cell.endswith(':'):
                alignments.append('c')
            elif cell.endswith(':'):
                alignments.append('r')
            else:
                alignments.append('l')
        
        for i, align in enumerate(alignments):
            x.align[x.field_names[i]] = align

        # Обработка данных
        seen_rows = set()
        for line in lines[separator_index + 1:]:
            if is_valid_table_row(line) and not is_valid_separator(line):
                row = [wrap_long_text(cell.strip(), max_cell_width) for cell in line.strip('|').split('|') if cell.strip()]
                row += [''] * (len(header) - len(row))
                row = tuple(row[:len(header)])
                if row not in seen_rows:
                    seen_rows.add(row)
                    x.add_row(row)

        # Установка максимальной ширины таблицы
        x.max_width = max_width

        return f'\n\n<pre><code>{x.get_string()}\n</code></pre>'

    # Находим все таблицы в тексте
    table_pattern = re.compile(r'(\n|^)\s*\|.*\|.*\n\s*\|[-:\s|]+\|\s*\n(\s*\|.*\|.*\n)*', re.MULTILINE)

    # Заменяем каждую найденную таблицу
    text = table_pattern.sub(lambda m: process_table(m.group(0)), text)

    text = re.sub(r'(?<=\|)(.*?)(?=\|)', lambda match: match.group(1).replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&#x27;'), text)

    return text


def split_html(text: str, max_length: int = 1500) -> list:
    """
    Splits HTML text into chunks with a maximum length, respecting code blocks, bold, and italic tags.

    Args:
        text: The HTML text to split.
        max_length: The maximum length of each chunk.

    Returns:
        A list of HTML chunks.
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
        elif line.startswith('<i>') and line.find('</i>') == -1:
            in_code_mode = 4
            code_tag = '<i>'
        elif line == '</code></pre>' or line == '</code>' or line == '</b>' or line == '</i>':
            code_tag = ''
            in_code_mode = 0
        else:
            if len(chunk) + len(line) + 20 > max_length:
                if in_code_mode == 1:
                    chunk += '</code></pre>\n'
                    chunks.append(chunk)
                    chunk = code_tag
                elif in_code_mode == 2:
                    chunk += '</code>\n'
                    chunks.append(chunk)
                    chunk = code_tag
                elif in_code_mode == 3:
                    chunk += '</b>\n'
                    chunks.append(chunk)
                    chunk = code_tag
                elif in_code_mode == 4:
                    chunk += '</i>\n'
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


def download_image_as_bytes(url_or_urls):
    """Загружает изображение(я) по URL-адресу(ам) и возвращает его(их) в виде байтов.

    Args:
        url_or_urls: URL-адрес изображения или список URL-адресов изображений.

    Returns:
        Изображение в виде байтов или список изображений в виде байтов.
    """

    if isinstance(url_or_urls, str):
        try:
            response = requests.get(url_or_urls, timeout=30)
        except Exception as error:
            return None
        return response.content

    elif isinstance(url_or_urls, list):
        with concurrent.futures.ThreadPoolExecutor() as executor:
            results = list(executor.map(lambda url: requests.get(url, timeout=30).content if requests.get(url, timeout=30).status_code == 200 else None, url_or_urls))
        return results

    else:
        return None


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
    Учитывает разный размер картинок, приводя их к одному размеру перед склейкой,
    сохраняя пропорции. Фон коллажа белый.

    Args:
        images (list): Список байтовых строк, представляющих изображения.

    Returns:
        bytes: Байтовая строка, представляющая итоговое изображение коллажа.
    """

    images = [PIL.Image.open(io.BytesIO(img)) for img in images]

    # Находим максимальную ширину и высоту среди всех картинок
    max_width = max(img.width for img in images)
    max_height = max(img.height for img in images)

    # Изменяем размер всех картинок до максимального, сохраняя пропорции
    resized_images = []
    for img in images:
        # Вычисляем коэффициент масштабирования
        scale_factor = min(max_width / img.width, max_height / img.height)

        # Вычисляем новые размеры с сохранением пропорций
        new_width = int(img.width * scale_factor)
        new_height = int(img.height * scale_factor)

        # Изменяем размер картинки с использованием метода LANCZOS
        resized_img = img.resize((new_width, new_height), PIL.Image.LANCZOS)

        # Если картинка не имеет альфа-канала, добавляем его
        if resized_img.mode != 'RGBA':
            resized_img = resized_img.convert('RGBA')

        resized_images.append(resized_img)

    # Создаем коллаж из картинок одинакового размера с белым фоном
    collage_width = max_width * 2  # Ширина коллажа - 2 картинки в ряд
    collage_height = max_height * (len(images) // 2 + len(images) % 2)  # Высота коллажа - количество рядов * высота картинки

    collage = PIL.Image.new('RGB', (collage_width, collage_height), (255, 255, 255))  # Белый фон

    x_offset = 0
    y_offset = 0
    for i, img in enumerate(resized_images):
        collage.paste(img, (x_offset, y_offset)) # Вставляем картинку
        if (i + 1) % 2 == 0:
            y_offset += max_height
            x_offset = 0
        else:
            x_offset += max_width

    # Сохраняем результат в буфер
    result_image_as_bytes = io.BytesIO()
    collage.save(result_image_as_bytes, format='JPEG', quality=95, optimize=True, subsampling=0)
    result_image_as_bytes.seek(0)
    return result_image_as_bytes.read()


def get_image_size(data: bytes) -> tuple[int, int]:
    """
    Определяет размеры изображения из байтовых данных.

    Args:
        data: Байтовые данные изображения.

    Returns:
        Кортеж (ширина, высота) изображения. 
        В случае ошибки возвращает (0, 0).
    """
    try:
        image = PIL.Image.open(io.BytesIO(data))
        width, height = image.size
        return width, height
    except Exception as error:
        my_log.log2(f'utils:get_image_size: {error}')
        return 0, 0


def string_to_dict(input_string: str):
    """
    Преобразует строку в словарь.

    Args:
        input_string: Строка, которую нужно преобразовать в словарь.

    Returns:
        Словарь, полученный из строки, или None, если возникли ошибки.
    """
    try:
        decoded_object = json_repair.loads(input_string)
        if decoded_object:
            return decoded_object
    except Exception as error:
        my_log.log2(f'utils:string_to_dict: {error}')
    if input_string:
        my_log.log2(f'utils:string_to_dict: {input_string}')
    return None


def heic2jpg(data: Union[bytes, str]) -> bytes:
    """Converts HEIC/HEIF image data (bytes or filepath) to JPEG bytes.

    Args:
        data: The image data as bytes or a string representing the filepath.

    Returns:
        The JPEG image data as bytes if the image was HEIC/HEIF,
        or the original data if it's not HEIC/HEIF,
        or an empty bytes object if conversion fails.
    """

    try:
        if isinstance(data, str):
            with open(data, 'rb') as f:
                data = f.read()

        if data[4:12] == b'ftypheic' or data[4:12] == b'ftypmif1':
            with PIL.Image.open(io.BytesIO(data)) as image:
                with io.BytesIO() as output:
                    image.save(output, format="JPEG", quality=80, optimize=True, progressive=True, subsampling="4:4:4")
                    contents = output.getvalue()
                    return contents
        else:
            return data

    except Exception as error:
        my_log.log2(f'utils:heic2jpg {error}')
        return b''


def compress_png_bytes(image_bytes: bytes) -> bytes:
    """Compresses a PNG image provided as bytes as much as possible.

    Args:
        image_bytes: The PNG image data as bytes.

    Returns:
        The compressed PNG image bytes, or the original 
        image_bytes if compression fails. Returns source if input is invalid.
    """
    try:
        # Open image from bytes
        img = PIL.Image.open(io.BytesIO(image_bytes))

        # Ensure the image is in PNG format
        if img.format != "PNG":
            return image_bytes  # Return original bytes if it's not a PNG

        # Convert image to RGB for color counting, if necessary
        if img.mode != "RGB":
            img = img.convert("RGB")

        # Count the number of unique colors
        unique_colors = len(img.getcolors(maxcolors=2**24))  # maxcolors to handle large images

        # If there are more than 256 unique colors, quantize the image
        if unique_colors < 256:
            img = img.quantize(colors=256)

        # Save with maximum compression and optimization
        with io.BytesIO() as compressed_buf:
            img.save(compressed_buf, "PNG", compress_level=9, optimize=True)
            compressed_image_bytes = compressed_buf.getvalue()

        return compressed_image_bytes

    except Exception as e:
        my_log.log2(f"utils:compress_png_bytes: Compression error: {e}")
        return image_bytes  # Return original bytes on error


def resize_image(image_bytes: bytes, max_size: int = 10 * 1024 * 1024) -> bytes:
    """
    Resizes the image to a maximum size in bytes, specifically for Telegram.
    Converts the image to JPEG regardless of the original format to ensure compatibility and reduce size.

    Args:
        image_bytes: Image bytes.
        max_size: Maximum size in bytes (default is 10MB).

    Returns:
        Resized image bytes in JPEG format.
        Returns original bytes if any error occurs or if image is already smaller than max_size.
    """
    if len(image_bytes) <= max_size:
        return image_bytes # Already small enough

    try:
        img = PIL.Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return image_bytes  # Return original bytes if open fails

    quality = 95
    while True:
      output = io.BytesIO()
      try:
          img.save(output, format="JPEG", quality=quality, optimize=True, subsampling=0) # optimize and preserve text
      except Exception:
          return image_bytes # Return original bytes if save fails

      size = output.tell()

      if size <= max_size:
        return output.getvalue()

      if quality <= 10:  # Minimum quality
        return output.getvalue()
      
      quality -= 5


def truncate_text(text: str, max_lines: int = 10, max_chars: int = 300) -> str:
    try:
        text = html.escape(text)
        if len(text) < max_chars and text.count('\n') < max_lines:
            return text
        text = '<blockquote expandable>' + text + '</blockquote>'
        return text
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'utils:truncate_text {error}\n{text}\n{max_lines} {max_chars}\n\n{traceback_error}')
        return text


if __name__ == '__main__':
    pass

    # print(bot_markdown_to_tts("Привет, мир! Hello, world! 123 こんにちは 你好 В этом примере регулярноwor😘😗☺️😚😙🥲😋😛😜🤪😝🤑🤗🤭🫢🫣🤫🤔🫡🤐🤨😐😑😶🫥😶‍🌫️😏😒🙄😬😮‍💨🤥🫨😌😔ldе выражение r'[^\p{L}\p{N}\p{P}]' находит все символы, которые не являются буквами, цифрами или знаками препинания, и заменяет их на пустую строку. Класс символов \p{L} соответствует всем буквам, \p{N} — всем цифрам, а \p{P} — всем знакам препинания."))

    # print(get_codepage())
    # print(get_file_ext('c:\\123\123123.23'))
    # print(safe_fname('dfgdшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшггггггггггггггггггггггггггггшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшшfg\/dfg.tb'))
    t1=r"""рш еруку

## Реализовать распознавание голосовых команд пользователя с помощью библиотеки Vosk и ресурса https://speechpad.ru/.

.  ## Для этого необходимо настроить библиотеку Vosk и подключиться к ресурсу https://speechpad.ru/. Затем необходимо создать функцию, которая будет принимать на вход аудиоданные и возвращать распознанный текст.
[hi](https://example.com/123(123))
[hi](https://example.com/123123)

**Шаг 3:**
. ### 135 выберите библиотеку Vosk

привет  я   медвед    ва

1. [a(x<sub>i</sub>) = j]: Это значит, что алгоритм определил, к какому кластеру (j) относится объект (x<sub>i</sub>).

W(j) = Σ<sub>j=1</sub><sup>k</sup> Σ<sub>i=1</sub><sup>n</sup> [d(c<sub>j</sub>, x<sub>i</sub>)]<sup>2</sup>Π[a(x<sub>i</sub>) = j] → min;

Ну __вот и наклонный__ текст.



1. **Отсутствует **`begin`** после заголовка программы:**
    `pascal
    program Program1;

    {... объявления переменных и процедур ...}

    {* Здесь должен быть begin *}

    end.  // <- Строка 24
    `

   **Решение:** Добавьте `begin` перед строкой 24 (или там, где должен начинаться основной блок кода программы).


Это _наклонный _ шрифт
Это _наклонный_ шрифт
Это _ наклонный _ шрифт
Это _наклонный шрифт_ да?
Это _наклонный шрифт больше чем
на 1 строку_ да?
Это _наклонный шрифт_да?
Это наклонный шрифт (_да_?

Это *наклонный * шрифт
Это *наклонный* шрифт
Это * наклонный * шрифт
Это *наклонный шрифт* да?
Это *наклонный шрифт больше чем
на 1 строку* да?
Это *наклонный шрифт*да?
Это *1* + *2* наклонный шрифт да?
Это наклонный шрифт (*да*?

Это _*наклонный *_ шрифт
Это _*наклонный*_ шрифт
Это _* наклонный *_ шрифт
Это _*наклонный шрифт*_ да?
Это _*наклонный шрифт больше чем
на 1 строку*_ да?
Это _*наклонный шрифт*_да?
Это наклонный шрифт (_*да*_?

Это ~~перечеркнутый~~ шрифт
Это [||спойлер||, шрифт

ОХ*ЕЛИ ОТ ПИ*ДАТОСТИ

   ```python
   plt.xticks(rotation=45, ha="right", fontsize=8)



   ```

Прямая, по которой пересекаются плоскости A<sub>1</sub>BC и A<sub>1</sub>AD — это прямая A<sub>1</sub>A.
Прямая, по которой пересекаются плоскости A<sub>1</sub>BC и A<sup>1</sup>AD — это прямая A<sub>1</sub>A.

текст
> цитата строка *1*
> цитата строка *2*

> цитата строка *3*
текст
> цитата строка *4*



text



# Заголовок первого уровня
## Заголовок второго уровня
### Заголовок 3 уровня
#### Заголовок 4 уровня

Изображение      представляет      собой рисунок девушки     с короткими каштановыми волосами, одетой в серую толстовку с капюшоном. Она выглядит грустной или уставшей, её глаза опухшие, а взгляд опущен. В руке она держит зажжённую сигарету, от которой идёт дым.  Рисунок выполнен в мультяшном стиле, линии несколько неровные, что придаёт ему небрежный, но при этом  милый характер. В правом нижнем углу изображения есть подпись: `@PANI_STRAWBERRY`.

Подпись на рисунке:

`@PANI_STRAWBERRY`

Пример запроса для генерации подобного изображения:

```prompt
/img a cartoon drawing of a sad girl with short brown hair wearing a grey hoodie, holding a cigarette with smoke coming out of it. Her eyes are droopy and she looks tired. The style should be slightly messy and cute, like a quick sketch.  Include the watermark "@PANI_STRAWBERRY" in the bottom right corner.
```

| Столбец 1 | Столбец 2 | Столбец 3 |
|---|---|---|
| данные1 | данные2 | данные3 |
| данные4 | данные5 | данные6 |
| данные7 | данные8 | данные9 |
| данные10 | данные11 | данные12 |
| данные13 | данные14 | данные15 |
| данные16 | данные17 | данные18 |
| данные19 | данные20 | данные21 |
| данные22 | данные23 | данные24 |
| данные25 | данные26 | данные27 |
| данные28 | данные29 | данные30 |


```prompt
/img A photorealistic image of a young woman with long black hair, wearing traditional samurai armor, holding a katana, in a dramatic pose. The scene is set in a Japanese garden with a traditional temple in the background. The image is in black and white and has a gritty, cinematic feel.  The lighting is dramatic and the focus is on the woman's face and the katana.  The image is full of details, including the woman's sharp eyes, the intricate patterns on her armor, and the texture of the stone of the temple.
```

`(x + 1) / ((x - 1)(x + 1)) + 2(x - 1) / ((x - 1)(x + 1)) = 3 / ((x - 1)(x + 1))`


* элемент 1
  * вложенный элемент 1
    - еще один вложенный
  - вложенный элемент 2
- элемент 2

\begin{equation}
\int_{-\infty}^{\infty} e^{-x^2} dx = \sqrt{\pi}
\end{equation}

\[ E=mc^2 \]

\begin
\int_{-\infty}^{\infty} e^{-x^2} dx = \sqrt{\pi}
\end

\begin{enumerate}
    \item Сложение: $2 + 3 = 5$
    \item Вычитание: $10 - 5 = 5$
    \item Умножение: $4 \times 6 = 24$
    \item Деление: $\frac{12}{3} = 4$
    \item Возведение в степень: $2^3 = 8$
    \item Квадратный корень: $\sqrt{16} = 4$
    \item Дробь: $\frac{1}{2} + \frac{1}{4} = \frac{3}{4}$
    \item Тригонометрия: $\sin(30^\circ) = \frac{1}{2}$
    \item Логарифм: $\log_{10} 100 = 2$
    \item Интеграл: $\int x^2 dx = \frac{x^3}{3} + C$
\end{enumerate}

$e^{i\pi} + 1 = 0$

$$ \int_{-\infty}^{\infty} e^{-x^2} dx = \sqrt{\pi} $$

\[ \frac{d}{dx} \sin(x) = \cos(x) \]

\begin{equation}
a^2 + b^2 = c^2
\end{equation}

$\sum_{i=1}^{n} i = \frac{n(n+1)}{2}$

$$
\begin{pmatrix}
1 & 2 \\
3 & 4
\end{pmatrix}
$$

\[
\begin{cases}
x + y = 5 \\
x - y = 1
\end{cases}
\]


Semoga bermanfaat dan menginspirasi.


**Задание 6**

| Параметр | Кабамазепин | Этосуксимид | Вальпроевая кислота | Фенитоин |
|---|---|---|---|---|
| Блокада Na+ каналов | + |  | + | + |
| Блокада Ca2+ каналов Т-типа |  | + | + |  |
| Активация ГАМК |  |  | + | + |
| Ингибирование CYP | 3A4 |  | 2C9 | 2C9, 2C19 |
| Угнетение кроветворения | + |  | + | itiuy kduhfg difug kdufg kd dddddddddddddddddddddddddd |
| Гиперплазия десен | + |  | + | + |
| Сонливость | + | + | + | + |


**Задание 7**

## Сравнительная таблица: Советская и Кубинская модели государственной службы

| Признак | Советская модель | Кубинская модель |
|---|---|---|
| **Идеологическая основа** | Марксизм-ленинизм | Марксизм-ленинизм, адаптированный к кубинским условиям (идеи Фиделя Кастро, Че Гевары) |
| **Политическая система** | Однопартийная система,  господствующая роль КПСС | Однопартийная система,  ведущая роль Коммунистической партии Кубы |
| **Государственное устройство** | Союзная республика,  формально федеративное устройство, фактически централизованное | Унитарное государство |
| **Экономическая система** | Централизованно-плановая экономика | Плановая экономика с элементами рыночного регулирования (после распада СССР) |
| **Организация госслужбы** | Строгая иерархия,  централизованное управление кадрами (номенклатурная система) | Иерархическая структура,  влияние партийных органов на назначение кадров,  большая роль общественных организаций |
| **Гражданское участие** | Ограниченное,  формальное  участие  через  общественные  организации,  контролируемые  партией |  Более активное  участие  граждан  через  местные  органы  власти  и  массовые  организации |
| **Отношения с другими странами** |  Противостояние  с  капиталистическим  миром,  поддержка  коммунистических  и  социалистических  движений |  Длительная  экономическая  и  политическая  блокада  со  стороны  США,  тесные  связи  с  странами  Латинской  Америки  и  другими  социалистическими  государствами |
| **Контроль и надзор** |  Развитая  система  партийного  и  государственного  контроля,  органы  безопасности |  Высокий  уровень  контроля  со  стороны  партии  и  государства |


**Примечания:**

Состав Антанты (Тройственное Согласие):

| Страна        | Дата присоединения |
|----------------|--------------------|
| **Франция**       | 1892 (военно-политический союз с Россией), 1904 (сердечное согласие с Великобританией), 1907 (образование Тройственной Антанты) |
| **Российская Империя** | 1892 (военно-политический союз с Францией), 1907 (образование Тройственной Антанты) |
| **Великобритания** | 1904 (сердечное согласие с Францией), 1907 (образование Тройственной Антанты)|



"""

    t2 = '''**Таблица 3. Морфология опухолей и опухолеподобных образований из меланинсодержащей ткани.**

| Номенклатура | Локализация | Морфологическая характеристика |
|---|---|---|
| Пограничный | Эпидермис |  Меланоциты располагаются в базальном слое эпидермиса, не проникая глубже. |
| Внутридермальный | Дерма |  Меланоциты находятся в дерме. |
| Сложный | Эпидермис и дерма |  Меланоциты находятся как в эпидермисе, так и в дерме. |
| Эпителиоидный невус |  Различные участки кожи |  Составлен из крупных эпителиоидных клеток. |
| Голубой | Дерма |  Синеватый или голубовато-серый цвет из-за расположения меланина в глубоких слоях дермы. |
| Диспластический | Различные участки кожи |  Неправильная форма, неравномерная окраска, нечеткие границы. |
| Меланома |  <10 Различные участки кожи, может метастазировать в другие органы |  1. Типы роста: радиальный, вертикальный. <br> 2.  <br> 3. Состоит из злокачественных меланоцитов. <br> 4. <br> 5. Метастазирует лимфогенным и гематогенным путем. |
'''

    t3 = '''The component doesn't need to know the specific structure of the store; it only needs the functions to access and modify the state.
Remember to adjust the type of `useDispatch` to match your application's `AppDispatch` type.
This is a clean and efficient way to create a reusable component that interacts with Redux without hardcoding store dependencies.

| Показания к применению | Лекарственные средства |
|---|---|
| 1) Лечение свежего инфаркта миокарда (первые 5 ч) | Алтеплаза, Стрептокиназа, Ацетилсалициловая кислота |
| 2) Лечение острой тромбоэмболии легочной артерии | Алтеплаза, Стрептокиназа, Гепарин, Надропарин кальция |
| 3) Лечение внутрисосудистого тромбоза | Гепарин, Надропарин кальция, Тромбин |
| 4) Лечение варикозного расширения вен нижних конечностей | Гепариновая мазь, Этамзилат |
| 5) Лечение кровотечений внутренних органов (маточных, желудочных, геморрагических) | Этамзилат, Аминокапроновая кислота |
| 6) Остановка капиллярных кровотечений | Этамзилат, Гепариновая мазь |
| 7) Профилактика "инфаркта" миокарда | Ацетилсалициловая кислота |

**Пояснения:**
'''

    print(bot_markdown_to_html(t3))
    # print(truncate_text(t3))

    pass
