#!/usr/bin/env python3

import cachetools.func
import concurrent.futures
import datetime
import functools
import hashlib
import io
import json
import html
import os
import pathlib
import pickle
import pysrt
import pytz
import random
import re
import regex
import requests
import shutil
import string
import subprocess
import tempfile
import threading
import time
import traceback
import platform as platform_module
from typing import Any, Union, List, Tuple

import json_repair
import markdownify
import PIL
import telebot
from bs4 import BeautifulSoup

from pylatexenc.latex2text import LatexNodes2Text
from pillow_heif import register_heif_opener
from prettytable import PrettyTable
from textwrap import wrap

import cfg
import my_log


register_heif_opener()


LOCK_TRANSCODE = threading.Lock()


def async_run(func):
    '''Декоратор для запуска функции в отдельном потоке, асинхронно'''
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        thread = threading.Thread(target=func, args=args, kwargs=kwargs)
        thread.start()
    return wrapper


def async_run_with_limit(max_threads: int):
    """
    Decorator to run a function in a separate thread asynchronously,
    with a limit on the number of concurrent threads.

    Args:
        max_threads: The maximum number of threads allowed to run concurrently.
    """
    semaphore = threading.Semaphore(max_threads)

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            def task():
                try:
                    func(*args, **kwargs)
                finally:
                    semaphore.release()

            semaphore.acquire()
            thread = threading.Thread(target=task)
            thread.start()
            return thread  # Optionally return the thread object
        return wrapper
    return decorator


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


# гребаный маркдаун ###################################################################

def replace_math_byte_sequences(text: str) -> str:
    """
    Replaces byte sequences like <0xXX><0xYY><0xZZ> with their corresponding Unicode characters.

    Args:
        text: The input string containing the byte sequences.

    Returns:
        The string with the byte sequences replaced by Unicode characters.
    """
    def replace(match: re.Match) -> str:
        hex_byte1 = match.group(1)
        hex_byte2 = match.group(2)
        hex_byte3 = match.group(3)
        byte_values = [int(hex_byte1, 16), int(hex_byte2, 16), int(hex_byte3, 16)]
        try:
            return bytes(byte_values).decode('utf-8')
        except UnicodeDecodeError:
            return match.group(0)

    pattern = r'<0x([0-9a-fA-F]{2})><0x([0-9a-fA-F]{2})><0x([0-9a-fA-F]{2})>'
    replaced_text = re.sub(pattern, replace, text)
    return replaced_text


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

    # меняем трехбайтовые утф8 символы для математики которые бот иногда вставляет вместо самих символов
    text = replace_math_byte_sequences(text)

    # экранируем весь текст для html, потом надо будет вернуть теги <u>
    text = html.escape(text)

    # надо заранее найти в таблицах блоки кода (однострочного `кода`) и заменить ` на пробелы
    text = clear_tables(text)

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

    # меняем латекс выражения
    text = replace_latex(text)

    # сохраняем 3 звезды что бы их не испортил конвертер списков
    def replace_3_stars(match):
        indent = match.group(0).split('*')[0] # Получаем все пробелы в начале
        return indent + '• • •'
    text = re.sub(r"^\s*\*\s*\*\s*\*\s*$", replace_3_stars, text, flags=re.MULTILINE)

    # переделываем списки на более красивые
    text = re.sub(r"^(\s*)\*\s", r"\1• ", text, flags=re.MULTILINE)
    # text = re.sub(r"^(\s*)-\s", r"\1– ", text, flags=re.MULTILINE)

    # 1,2,3,4 # в начале строки меняем всю строку на жирный текст
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

    # заменить записи типа \boxed{1.7} на 【1.7】
    text = re.sub(r"\\boxed\{([^}]*)\}", r"【\1】", text)

    # удалить странные записи вида <binary data, 1 bytes>
    text = text.replace('&lt;binary data, 1 bytes&gt;', '')

    # First handle _*text*_ pattern (italic-bold combined)
    text = re.sub(r"(?<!\w)_\*([^\n\s].*?[^\n\s])\*_(?!\w)", r"<i><b>\1</b></i>", text)

    # Handle **_text_** pattern (bold-italic combined)
    text = re.sub(r"\*\*_(.+?)_\*\*", r"<b><i>\1</i></b>", text)

    # Handle _**text**_ pattern (italic-bold combined)
    text = re.sub(r"_\*\*(.+?)\*\*_", r"<i><b>\1</b></i>", text)

    # Handle *_text_* pattern (bold-italic combined)
    text = re.sub(r"\*_(.+?)_\*", r"<i><b>\1</b></i>", text)

    # Handle standalone bold (**text**)
    text = re.sub(r'\*\*([^*]+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'^\*\*(.*?)\*\*$', r'<b>\1</b>', text, flags=re.MULTILINE | re.DOTALL)

    # Handle standalone italics (_text_ or *text*)
    text = re.sub(r"(?<!\w)_([^\n\s_*][^\n*_]*[^\n\s_*])_(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)\*(?!\s)([^\n*]+?)(?<!\s)\*(?!\w)", r"<i>\1</i>", text)



    # 2 _ в <i></i>
    text = re.sub('\_\_(.+?)\_\_', '<i>\\1</i>', text)
    text = re.sub(r'^\_\_(.*?)\_\_$', r'<i>\1</i>', text, flags=re.MULTILINE | re.DOTALL)

    # Замена _*текст*_ на <i>текст</i>
    text = re.sub(r"(?<!\w)_\*([^\n\s].*?[^\n\s])\*_(?!\w)", r"<i>\1</i>", text)

    # Замена ~~текст~~ на <s>текст</s>
    text = re.sub(r"(?<!\w)~~(?!\s)([^\n*]+?)(?<!\s)~~(?!\w)", r"<s>\1</s>", text)

    # Замена ||текст|| на <tg-spoiler>текст</tg-spoiler>
    text = re.sub(r"(?<!\w)\|\|(?!\s)([^\n*]+?)(?<!\s)\|\|(?!\w)", r"<tg-spoiler>\1</tg-spoiler>", text)

    # замена <b><i> ... </b></i> на <b><i> ... </i></b>
    text = re.sub(r"<b><i>(.+?)</b></i>", r"<b><i>\1</i></b>", text)
    text = re.sub(r"<i><b>(.+?)</i></b>", r"<i><b>\1</b></i>", text)

    # Удаление парных знаков $ в пределах одной строки
    text = re.sub(r'\$(\S[^\$\n]*?\S)\$', r'\1', text)

    # меняем маркдаун ссылки на хтмл
    text = re.sub('''\[(.*?)\]\((https?://\S+)\)''', r'<a href="\2">\1</a>', text)

    # меняем все ссылки на ссылки в хтмл теге кроме тех кто уже так оформлен
    # а зачем собственно? text = re.sub(r'(?<!<a href=")(https?://\S+)(?!">[^<]*</a>)', r'<a href="\1">\1</a>', text)

    # хз откуда это
    text = text.replace('&#x27;', "'")
    text = text.replace('   #x27;', "'")
    text = text.replace('#x27;', "'")


    # меняем теги &lt;u&gt;  &lt;/u&gt; на <u></u>
    text = re.sub(r'&lt;u&gt;(.+?)&lt;/u&gt;', r'<u>\1</u>', text)

    # меняем таблицы до возвращения кода
    text = replace_tables(text)

    # возвращаем 3 звезды
    def replace_3_stars2(match):
        indent = match.group(0).split('•')[0] # Получаем все пробелы в начале
        return indent + '* * *'
    text = re.sub(r"^\s*•\s*•\s*•\s*$", replace_3_stars2, text, flags=re.MULTILINE)


    def replace_asterisk_with_digits(text: str) -> str:
        """
        Заменяет символ \* на * в строках, где есть цифры.

        Args:
            text: Исходный текст.

        Returns:
            Текст с выполненными заменами.
        """
        lines = text.split('\n')
        modified_lines = []
        for line in lines:
            # if any(char.isdigit() for char in line):
            #     modified_line = re.sub(r'\\\*', '*', line)
            #     modified_line = re.sub(r'\\\[', '[', modified_line)
            #     modified_line = re.sub(r'\\\(', '(', modified_line)
            # else:
            #     modified_line = line
            # Заменяем экранированный символ '_' если прилегает к буквам
            # modified_line = re.sub(r"(?<=\w)\\_|\\_(?=\w)|(?<=\w)\\_(?=\w)", "_", modified_line)
            modified_line = re.sub(r'\\\*', '*', line)
            modified_line = re.sub(r'\\\[', '[', modified_line)
            modified_line = re.sub(r'\\\(', '(', modified_line)
            modified_line = re.sub(r'\\\)', ')', modified_line)
            modified_line = re.sub(r'\\\_', '_', modified_line)
            modified_lines.append(modified_line)
        return '\n'.join(modified_lines)

    text = replace_asterisk_with_digits(text)


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

    text = text.replace('<pre><code class="language-plaintext">\n<pre><code>', '<pre><code class="language-plaintext">')

    # убрать 3 и более пустые сроки подряд (только после блоков кода или любых тегов)
    def replace_newlines(match):
        return '\n\n'
    text = re.sub(r"(?<!<pre>)(?<!<code>)\n{3,}(?!</code>)(?!</pre>)", replace_newlines, text, flags=re.DOTALL)
    text = re.sub(r"pre>\n{2,}", "pre>\n", text)

    text = text.replace('\n</code></pre>\n</code>', '\n</code></pre>')

    return text.strip()


def clear_tables(text: str) -> str:
    '''надо найти в маркдаун таблицах блоки кода (однострочного `кода`) и заменить ` на пробелы
    признаки таблицы - 2 и более идущих подряд строки которые начинаются и заканчиваются на | и количество | в них совпадает
    '''
    lines = text.splitlines()
    in_table = False
    table_lines = []
    result = []

    for line in lines:
        if line.startswith("|") and line.endswith("|") and line.count("|") > 1:
            if not in_table:
                table_lines = []  # Start a new table
                in_table = True
            table_lines.append(line)

        else:
            if in_table:
                # Process the table lines
                processed_table_lines = []
                for table_line in table_lines:
                    processed_table_lines.append(table_line.replace("`", " "))
                result.extend(processed_table_lines)
                table_lines = []
                in_table = False

            result.append(line)

    if in_table:  # If the text ends inside a table block
      processed_table_lines = []
      for table_line in table_lines:
          processed_table_lines.append(table_line.replace("`", " "))
      result.extend(processed_table_lines)

    return "\n".join(result)


def replace_latex(text: str) -> str:
    def is_valid_latex(text: str) -> bool:
        """
        Проверяет, является ли текст валидным LaTeX выражением
        """
        # Базовая проверка на наличие LaTeX команд или математических символов
        latex_indicators = [
            '\\', '_', '^', '{', '}', '=',  # базовые LaTeX команды
            '\\frac', '\\sqrt', '\\sum', '\\int',  # математические операторы
            '\\alpha', '\\beta', '\\gamma',  # греческие буквы
            '\\mathbf', '\\mathrm', '\\text'  # форм
        ]
        # Проверяем наличие хотя бы одного индикатора LaTeX
        return any(indicator in text for indicator in latex_indicators)


    # Обработка LaTeX выражений
    # 1. Сначала ищем выражения в $$ ... $$
    matches = re.findall(r'\$\$(.*?)\$\$', text, flags=re.DOTALL)
    for match in matches:
        if is_valid_latex(match):  # добавим проверку на валидность LaTeX
            try:
                new_match = LatexNodes2Text().latex_to_text(match.replace('\\\\', '\\'))
                new_match = html.escape(new_match)
                text = text.replace(f'$${match}$$', new_match)
            except:
                # Если возникла ошибка при конвертации, оставляем как есть
                continue

    # 2. Затем ищем выражения в $ ... $
    # matches = re.findall(r'(?<!\$)\$(?!\$)(.*?)(?<!\$)\$(?!\$)', text, flags=re.DOTALL)
    matches = re.findall(r'(?<!\$)\$(?!$)(.*?)(?<!\$)\$(?!$)', text, flags=re.DOTALL)
    for match in matches:
        if is_valid_latex(match):
            try:
                new_match = LatexNodes2Text().latex_to_text(match.replace('\\\\', '\\'))
                new_match = html.escape(new_match)
                text = text.replace(f'${match}$', new_match)
            except:
                continue

    # 3. Обработка \[ ... \] и \( ... \)
    matches = re.findall(r'\\\[(.*?)\\\]|\\\((.*?)\\\)', text, flags=re.DOTALL)
    for match_tuple in matches:
        match = match_tuple[0] if match_tuple[0] else match_tuple[1]
        if is_valid_latex(match):
            try:
                new_match = LatexNodes2Text().latex_to_text(match.replace('\\\\', '\\'))
                new_match = html.escape(new_match)
                if match_tuple[0]:
                    text = text.replace(f'\\[{match}\\]', new_match)
                else:
                    text = text.replace(f'\\({match}\\)', new_match)
            except:
                continue

    def latex_to_text(latex_formula):
        # Здесь должна быть реализация преобразования LaTeX в текст
        # В данном примере просто возвращаем формулу без изменений
        r = LatexNodes2Text().latex_to_text(latex_formula).strip()
        rr = html.escape(r)
        return rr

    def replace_function_lt1(match):
        latex_code = match.group(2) if match.group(2) is not None else match.group(3) if match.group(3) is not None else match.group(4)
        return latex_to_text(latex_code)

    pattern = r"\\begin\{(.*?)\}(.*?)\\end\{\1\}|\\\[(.*?)\\\]|\\begin(.*?)\\end"
    text = re.sub(pattern, replace_function_lt1, text, flags=re.DOTALL)

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
    original_text = text
    try:
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
            text = text.replace('<code>',  '      ')
            text = text.replace('</code>', '       ')
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

            def make_strings_unique(strings):
                """
                Проверяет список строк на наличие дубликатов и делает их уникальными.

                Args:
                    strings: Список строк.

                Returns:
                    Список строк без дубликатов.
                """
                seen = set()
                result = []
                for s in strings:
                    original_s = s
                    count = 1
                    while s in seen:
                        s = original_s + f"_{count}"
                        count += 1
                    seen.add(s)
                    result.append(s)
                return result

            x.field_names = make_strings_unique(header)

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

            # return f'\n\n<pre><code>{x.get_string()}\n</code></pre>'
            return f'\n\n<code>{x.get_string()}\n</code>'

        # Находим все таблицы в тексте
        table_pattern = re.compile(r'(\n|^)\s*\|.*\|.*\n\s*\|[-:\s|]+\|\s*\n(\s*\|.*\|.*\n)*', re.MULTILINE)

        # Заменяем каждую найденную таблицу
        text = table_pattern.sub(lambda m: process_table(m.group(0)), text)


        # экранируем запрещенные символы кроме хтмл тегов
        TAG_MAP = {
            "<b>": "40bd001563085fc35165329ea1ff5c5ecbdbbeef",
            "</b>": "c591326762260728871710537179fabf75973234",
            "<strong>": "ef0b585e265b5287aa6d26a6860e0cd846623679",
            "</strong>": "e882cf5c82a930662f17c188c70ade885c55c607",
            "<i>": "497603a6c32112169ae39a79072c07e863ae3f7a",
            "</i>": "0784921025d4c05de5069cc93610c754a4088015",
            "<em>": "d1a25e1cb6b3d667b567323119f126f845c971df",
            "</em>": "851e149d4a4313c6016e73f719c269076790ab23",
            "<code>": "c1166919418e7c62a16b86662710541583068278",
            "</code>": "b7e364fd74d46f698c0f164988c382957c220c7c",
            "<s>": "03c7c0ace395d80182db07ae2c30f0341a739b1b",
            "</s>": "86029812940d86d63c5899ee5227cf94639408a7",
            "<strike>": "f0e25c74b67881c84327dc916c8c919f062c9003",
            "</strike>": "935f70051f605261d9f93948a5c3382f3a843596",
            "<del>": "8527a891e224136950ff32ca212b45bc93f69972",
            "</del>": "a992a007a4e77704231c285601a97cca4a70b768",
            "<pre>": "932162e70462a0f5d1a7599592ed51c41c4f8eb7",
            "</pre>": "e9e6f7c1fe77261334b414ae017288814903b225",
            "<u>": "764689e6705f61c6e7494bfa62688414325d8155",
            "</u>": "8a048b284925205d3187f8b04625a702150a936f",
        }

        REVERSE_TAG_MAP = {
            "40bd001563085fc35165329ea1ff5c5ecbdbbeef": "<b>",
            "c591326762260728871710537179fabf75973234": "</b>",
            "ef0b585e265b5287aa6d26a6860e0cd846623679": "<strong>",
            "e882cf5c82a930662f17c188c70ade885c55c607": "</strong>",
            "497603a6c32112169ae39a79072c07e863ae3f7a": "<i>",
            "0784921025d4c05de5069cc93610c754a4088015": "</i>",
            "d1a25e1cb6b3d667b567323119f126f845c971df": "<em>",
            "851e149d4a4313c6016e73f719c269076790ab23": "</em>",
            "c1166919418e7c62a16b86662710541583068278": "<code>",
            "b7e364fd74d46f698c0f164988c382957c220c7c": "</code>",
            "03c7c0ace395d80182db07ae2c30f0341a739b1b": "<s>",
            "86029812940d86d63c5899ee5227cf94639408a7": "</s>",
            "f0e25c74b67881c84327dc916c8c919f062c9003": "<strike>",
            "935f70051f605261d9f93948a5c3382f3a843596": "</strike>",
            "8527a891e224136950ff32ca212b45bc93f69972": "<del>",
            "a992a007a4e77704231c285601a97cca4a70b768": "</del>",
            "932162e70462a0f5d1a7599592ed51c41c4f8eb7": "<pre>",
            "e9e6f7c1fe77261334b414ae017288814903b225": "</pre>",
            "764689e6705f61c6e7494bfa62688414325d8155": "<u>",
            "8a048b284925205d3187f8b04625a702150a936f": "</u>",
        }

        def replace_tags_with_hashes(text):
            for tag, tag_hash in TAG_MAP.items():
                text = text.replace(tag, tag_hash)
            return text

        def replace_hashes_with_tags(text):
            for tag_hash, tag in REVERSE_TAG_MAP.items():
                text = text.replace(tag_hash, tag)
            return text

        text = replace_tags_with_hashes(text)
        text = re.sub(r'(?<=\|)(.*?)(?=\|)', lambda match: match.group(1).replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&#x27;'), text)
        text = replace_hashes_with_tags(text)

        return text
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        # my_log.log2(f'utils:replace_tables {unknown}\n\n{traceback_error}\n\n{original_text}')
        return original_text


def split_html(text: str, max_length: int = 1500) -> list:
    """
    Разбивает HTML-подобный текст на части, не превышающие max_length символов.

    Учитывает вложенность тегов и корректно переносит их между частями.
    """

    tags = {
        "b": "</b>",
        "i": "</i>",
        "code": "</code>",
        "pre": "</pre>",
        "blockquote": "</blockquote>",
        "blockquote expandable": "</blockquote>",
    }
    opening_tags = {f"<{tag}>" for tag in tags}
    closing_tags = {tag for tag in tags.values()}

    result = []
    current_chunk = ""
    open_tags_stack = []

    lines = text.splitlines(keepends=True)
    for line in lines:
        line_stripped = line.strip()

        # Обработка открывающих тегов
        for tag in opening_tags:
            if line_stripped.startswith(tag):
                tag_name = tag[1:-1]

                # Проверяем, закрыт ли тег в этой же строке
                if tags[tag_name] not in line:
                    open_tags_stack.append(tag_name)

                # Обработка случая <pre><code class="">
                if tag_name == "pre" and '<code class="' in line:
                    open_tags_stack.append("code")

                break

        # Обработка закрывающих тегов
        for closing_tag in closing_tags:
            if closing_tag in line:
                tag_name = closing_tag[2:-1]

                remove_index = -1
                for i in reversed(range(len(open_tags_stack))):
                    if open_tags_stack[i] == tag_name:
                        remove_index = i
                        break
                if remove_index != -1:
                    open_tags_stack.pop(remove_index)

        # Добавление строки к текущему чанку
        if len(current_chunk) + len(line) > max_length:
            # Чанк переполнен, нужно его завершить и начать новый

            # 1. Закрываем теги в текущем чанке
            for tag_name in reversed(open_tags_stack):
                current_chunk += tags[tag_name]

            # 2. Добавляем текущий чанк в результат
            if len(current_chunk) > max_length:
                for x in split_text(current_chunk, max_length):
                    result.append(x)
            else:
                result.append(current_chunk)

            # 3. Начинаем новый чанк
            current_chunk = ""

            # 4. Открываем теги в новом чанке
            for tag_name in open_tags_stack:
                current_chunk += f"<{tag_name}>"

        current_chunk += line

    # Добавление последнего чанка
    if current_chunk:
        if len(current_chunk) > max_length:
            for x in split_text(current_chunk, max_length):
                result.append(x)
        result.append(current_chunk)

    result2 = post_process_split_html(result)

    return result2


def post_process_split_html(chunks: list) -> list:
    """
    Выполняет постобработку списка чанков, полученного из split_html.
    Исправляет поломанные теги, и убирает пусты чанки
    """

    def fix_html_tags(text: str) -> str:
        """
        Fixes HTML tag errors in the text using BeautifulSoup.

        Args:
            text: The input text containing HTML tags.

        Returns:
            The text with fixed HTML tags.
        """
        soup = BeautifulSoup(text, 'html.parser')
        return str(soup)

    processed_chunks = []
    for chunk in chunks:
        processed_chunks.append(fix_html_tags(chunk))

    # удалить пустые чанки
    processed_chunks = [chunk for chunk in processed_chunks if chunk.strip() and chunk.strip() != '</code>']

    return processed_chunks


def html_to_markdown(html: str) -> str:
    """
    Converts HTML to Markdown.

    Args:
        html (str): HTML code.

    Returns:
        str: Markdown code.
    """
    try:
        markdown_text = markdownify.markdownify(html)
        return markdown_text
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'utils:html_to_markdown {error}\n\n{traceback_error}\n\n{html}')
        return html

#######################################################################################


def get_tmp_fname() -> str:
    """
    Generate a temporary file name.

    Returns:
        str: The name of the temporary file.
    """
    with tempfile.NamedTemporaryFile(delete=True) as temp_file:
        return temp_file.name


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


## ytb #####################################################################################

def convert_to_mp3(input_file: str) -> str | None:
    """
    Converts an audio file to MP3 format using ffmpeg with the highest quality settings.

    Args:
        input_file: Path to the input audio file.

    Returns:
        Path to the converted MP3 file, or None if an error occurred.
    """
    with LOCK_TRANSCODE:
        try:
            output_file = get_tmp_fname() + '.mp3'

            # LAME Bitrate Overview
            # lame option | Average kbit/s | Bitrate range kbit/s      | ffmpeg option
            # ----------- | --------------- | ----------------------- | -------------
            # -b 320      | 320             | 320 CBR (non VBR) example | -b:a 320k (NB this is 32KB/s, or its max)
            # -V 0        | 245             | 220-260                 | -q:a 0 (NB this is VBR from 220 to 260 KB/s)
            # -V 1        | 225             | 190-250                 | -q:a 1
            # -V 2        | 190             | 170-210                 | -q:a 2
            # -V 3        | 175             | 150-195                 | -q:a 3
            # -V 4        | 165             | 140-185                 | -q:a 4
            # -V 5        | 130             | 120-150                 | -q:a 5
            # -V 6        | 115             | 100-130                 | -q:a 6
            # -V 7        | 100             | 80-120                  | -q:a 7
            # -V 8        | 85              | 70-105                  | -q:a 8
            # -V 9        | 65              | 45-85                   | -q:a 9

            subprocess.run([
                'ffmpeg',
                '-i',
                input_file,
                '-vn',  # Disable video processing
                '-acodec',
                'libmp3lame',  # Use libmp3lame for MP3 encoding
                '-q:a',
                '3',  # Use -q:a for VBR (Variable Bit Rate)
                # 0 is the highest quality, 9 is the lowest
                '-loglevel',
                'error',
                output_file
            ], check=True)

            return output_file

        except subprocess.CalledProcessError as error:
            my_log.log2(f'utils:convert_to_mp3: error: {error}\n\n{traceback.format_exc()}')
            return None


@cachetools.func.ttl_cache(maxsize=10, ttl=10 * 60)
def get_title_and_poster(url: str) -> Tuple[str, str, str, int]:
    """
    Gets the title, thumbnail URL, description, and size of a YouTube video using yt-dlp.

    Args:
        url: The URL of the YouTube video.

    Returns:
        A tuple containing the title, thumbnail URL, description, and size (duration in seconds) of the video.
        If an error occurs, returns a tuple of four empty strings or 0 for size.
    """
    try:
        # Use yt-dlp to extract video information
        if hasattr(cfg, 'YTB_PROXY2') and cfg.YTB_PROXY2:
            proxy = random.choice(cfg.YTB_PROXY2)
            process = subprocess.run([
                'yt-dlp',
                '--dump-json',
                '--proxy', proxy,
                url
            ], capture_output=True, text=True, check=True)
        else:
            process = subprocess.run([
                'yt-dlp',
                '--dump-json',
                url
            ], capture_output=True, text=True, check=True)

        # Parse the JSON output
        video_info = json.loads(process.stdout)

        # Extract the required information
        title = video_info.get('title', '')
        thumbnail_url = video_info.get('thumbnail', '')
        description = video_info.get('description', '')
        size = video_info.get('duration', 0)

        return title, thumbnail_url, description, size

    except (subprocess.CalledProcessError, json.JSONDecodeError) as error:
        my_log.log2(f'my_ytb:get_title_and_poster {url} {error}')
        return '', '', '', 0


def download_audio(url: str, limit_duration: int = 4 * 60 * 60) -> str | None:
    """
    Downloads audio file using yt-dlp to a temporary folder
    with audio quality 128k or lower. If small file them download best quality.

    Args:
        url: Link to the audio file.
        limit_duration: Maximum duration of the audio file in seconds. Default is 4 hours.

    Returns:
        Path to the downloaded file in the temporary folder, or None if download failed.
    """
    output_template = get_tmp_fname()

    try:
        duration = get_title_and_poster(url)[3]

        if duration > limit_duration:
            return None

        if duration < 10*60:
            quality = 'bestaudio'
        else:
            quality = 'bestaudio[abr<=128]/bestaudio'
        if hasattr(cfg, 'YTB_PROXY2') and cfg.YTB_PROXY2:
            proxy = random.choice(cfg.YTB_PROXY2)
            subprocess.run([
                'yt-dlp',
                '-f', quality,
                '--proxy', proxy,
                '-o', output_template,
                url
            ], check=True)
        else:
            subprocess.run([
                'yt-dlp',
                '-f', quality,
                '-o', output_template,
                url
            ], check=True)
    except subprocess.CalledProcessError:
        return None

    r = output_template
    if quality == 'bestaudio':
        r2 = convert_to_mp3(r)
        if r2:
            remove_file(r)
            return r2
        else:
            return None
    return r


@cachetools.func.ttl_cache(maxsize=10, ttl=10 * 60)
def valid_youtube_url(url: str) -> str:
    """
    Checks if the URL is a valid YouTube URL using yt-dlp, with proxy support.

    Supports various YouTube URL formats:
    - youtu.be/
    - youtube.com/watch?v=
    - m.youtube.com/watch?v=
    - youtube-nocookie.com/embed/

    Args:
        url: The URL string to check.

    Returns:
        The YouTube video ID if the URL is valid, otherwise an empty string.
    """
    try:
        url = url.strip()
        if not url.lower().startswith('http'):
            return ''

        # Check if a proxy is configured
        if hasattr(cfg, 'YTB_PROXY2') and cfg.YTB_PROXY2:
            # Use a random proxy from the list
            proxy = random.choice(cfg.YTB_PROXY2)
            process = subprocess.run([
                'yt-dlp',
                '--print', '%(id)s',
                '--skip-download',  # Skip downloading the video
                '--proxy', proxy,
                url
            ], capture_output=True, text=True, check=True)
        else:
            # No proxy configured, use yt-dlp directly
            process = subprocess.run([
                'yt-dlp',
                '--print', '%(id)s',
                '--skip-download',  # Skip downloading the video
                url
            ], capture_output=True, text=True, check=True)

        # Extract the video ID from the output
        video_id = process.stdout.strip()

        # Check if the extracted ID is not empty
        if video_id:
            return video_id
        else:
            my_log.log2(f'my_ytb:valid_youtube_url1: Invalid YouTube URL: {url}')
            return ''

    except subprocess.CalledProcessError as error:
        error_traceback = traceback.format_exc()
        my_log.log2(f'my_ytb:valid_youtube_url2: {url} {error}\n\n{error_traceback}')
        return ''

## ytb #####################################################################################


def download_audio_file_as_bytes(url: str,  limit_size: int = 200) -> bytes:
    """
    Downloads a file from the given URL and returns it as bytes.
    Does not download more than limit_size (200 MB) to avoid downloading excessively large files.
    Includes timeouts for requests and data reading to handle large files efficiently.

    Args:
        url (str): The URL of the file.
        limit_size (int, optional): The maximum size of the file to download. Defaults to 200 MB.

    Returns:
        bytes: The file as bytes.
    """
    if valid_youtube_url(url):
        p = download_audio(url)
        if p:
            with open(p, 'rb') as f:
                data = f.read()
            remove_file(p)
            return data
        else:
            return None
            

    max_size = limit_size * 1024 * 1024
    chunk_size = 100 * 1024
    timeout = 30  # Timeout for requests in seconds
    read_timeout = 300  # Timeout for reading data in seconds

    try:
        response = requests.get(url, stream=True, timeout=timeout)
        response.raise_for_status()

        # Get the content length from the headers, if available
        content_length = response.headers.get('Content-Length')
        if content_length is not None:
            content_length = int(content_length)
            if content_length > max_size:
                raise ValueError(f"File is too large: {content_length} bytes. Maximum size: {max_size} bytes.")

        downloaded_size = 0
        audio_data = b''
        start_time = time.time()

        # Download the file in chunks to avoid loading large files into memory
        for chunk in response.iter_content(chunk_size=chunk_size):
            if time.time() - start_time > read_timeout:
                raise TimeoutError("Reading data timed out.")

            if downloaded_size + len(chunk) > max_size:
                raise ValueError(f"Exceeded maximum file size: {max_size} bytes.")

            audio_data += chunk
            downloaded_size += len(chunk)

            # Log the progress
            my_log.log2(f'utils:download_audio_file_as_bytes: Downloaded {downloaded_size} bytes out of {content_length if content_length else "unknown"} bytes.')

        return audio_data

    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'utils:download_audio_file_as_bytes: Error in download_audio_file_as_bytes: {url}\n{error}\n\n{traceback_error}')

    return b''


def get_filename_from_url(url: str) -> str:
    return os.path.basename(url)


def download_image_as_bytes(url_or_urls: str) -> bytes:
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
            return b''
        return response.content

    elif isinstance(url_or_urls, list):
        with concurrent.futures.ThreadPoolExecutor() as executor:
            results = list(executor.map(lambda url: requests.get(url, timeout=30).content if requests.get(url, timeout=30).status_code == 200 else None, url_or_urls))
        return results

    else:
        return b''


def download_image_for_thumb(url: str) -> bytes:
    """
    Downloads an image from the given URL, converts it to JPG format if necessary,
    resizes it to a maximum size of 200KB, and ensures its dimensions do not exceed 320x320 pixels.

    Args:
        url: The URL of the image.

    Returns:
        The image data as bytes in JPG format, or empty bytes if an error occurred.
    """
    try:
        # Download the image using requests
        response = requests.get(url, stream=True)
        response.raise_for_status()  # Raise an exception for bad status codes

        # Read the image data into a BytesIO object
        image_data = io.BytesIO(response.content)

        # Open the image using PIL
        image = PIL.Image.open(image_data)

        # Convert the image to RGB mode if it's not
        if image.mode != 'RGB':
            image = image.convert('RGB')

        # Resize the image if necessary, maintaining aspect ratio
        if image.width > 320 or image.height > 320:
            width, height = image.size
            if width > height:
                new_width = 320
                new_height = int(height * (320 / width))
            else:
                new_height = 320
                new_width = int(width * (320 / height))
            image = image.resize((new_width, new_height), PIL.Image.LANCZOS)

        output_data = io.BytesIO()
        quality = 75
        image.save(output_data, format='JPEG', quality=quality)

        return output_data.getvalue()

    except Exception as error:
        my_log.log2(f'download_image_as_bytes_as_jpg: error: {error}\n\n{traceback.format_exc()}')
        return b''


def fast_hash(data: Any) -> str:
    """
    Calculates the SHA256 hash of any Python data.

    This function efficiently handles various data types, including bytes, strings, lists, dictionaries, etc.
    For byte data, it directly calculates the hash. For other data types, it first serializes the data using pickle
    and then calculates the hash.

    Args:
        data: The data to hash. Can be of any type.

    Returns:
        The hexadecimal representation of the SHA256 hash.
    """
    if isinstance(data, bytes):
        hashed = hashlib.sha256(data).hexdigest()
    else:
        pickled_data = pickle.dumps(data)
        hashed = hashlib.sha256(pickled_data).hexdigest()
    return hashed


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


def remove_dir(fname: str):
    '''Удаляет папку рекурсивно'''
    try:
        if os.path.isdir(fname):
            shutil.rmtree(fname)
        elif os.path.isfile(fname):
            os.unlink(fname)
        else:
            # my_log.log2(f'utils:remove_dir: {fname} not found or not a directory or file')
            return False
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


def resize_and_convert_to_jpg(image_data: Union[bytes, str], max_size: int = 2000, jpg_quality: int = 60) -> bytes:
    """
    Resizes an image to a maximum size in either dimension,
    converts it to JPG format (if it's not already), and compresses it.
    If the image is already JPG and within the size limits, it returns the original data.

    Args:
        image_data: The image data as bytes or a file path to the image.
        max_size: The maximum size (in pixels) for the width or height of the image. Defaults to 2000.
        jpg_quality: The quality of the JPG compression (0-100). Defaults to 60.

    Returns:
        The processed JPG image data as bytes, or the original data if no changes were needed.
    """
    try:
        # Открываем изображение, если передали путь к файлу, то читаем файл
        if isinstance(image_data, str):
            with open(image_data, 'rb') as f:
                image_data = f.read()

        print(len(image_data))

        # Открываем изображение из байтов
        img = PIL.Image.open(io.BytesIO(image_data))

        # Получаем ширину и высоту
        width, height = img.size

        # Если размеры меньше max_size и формат JPG, возвращаем исходные данные
        if width <= max_size and height <= max_size and img.format == 'JPEG':
            return image_data

        # Определяем, нужно ли изменять размер
        if width > max_size or height > max_size:
            # Вычисляем коэффициент масштабирования
            if width > height:
                scale = max_size / width
            else:
                scale = max_size / height

            # Рассчитываем новые размеры
            new_width = int(width * scale)
            new_height = int(height * scale)

            # Изменяем размер изображения
            img = img.resize((new_width, new_height))

        # Конвертируем в JPG и сжимаем только если это необходимо
        with io.BytesIO() as output:
            img = img.convert('RGB')  # Конвертируем в RGB если это необходимо
            img.save(output, format='JPEG', quality=jpg_quality, optimize=True)
            jpg_data = output.getvalue()

        print(len(jpg_data))

        return jpg_data

    except Exception as e:
        my_log.log2(f'utils:resize_and_convert_to_jpg: {e}')
        return b''  # Возвращаем пустые байты в случае ошибки


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

    quality = 75

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

        quality -= 10


def resize_image_dimention(image_bytes: bytes) -> bytes:
    """
    Resizes an image to fit within Telegram's dimension limits (width + height <= 10000),
    while preserving the aspect ratio and format.

    Args:
        image_bytes: The image data as bytes.

    Returns:
        The resized image data as bytes, or the original image data if no resizing was needed.
    """
    try:
        img = PIL.Image.open(io.BytesIO(image_bytes)) # Open the image from bytes
        original_format = img.format  # Store original format

        if img.width + img.height > 10000:
            # Calculate the scaling factor to maintain aspect ratio
            # while keeping within Telegram's size limit.
            scale_factor = 10000 / (img.width + img.height)
            new_width = int(img.width * scale_factor)
            new_height = int(img.height * scale_factor)

            # Resize the image using the calculated dimensions
            img = img.resize((new_width, new_height), PIL.Image.LANCZOS)
        else:
            return image_bytes

        # Save the image to a BytesIO object, preserving the original format
        output_bytes = io.BytesIO()
        img.save(output_bytes, format=original_format, optimize=True)
        return output_bytes.getvalue()

    except Exception as e:
        my_log.log2(f"utils:resize_image_dimention: {e}")
        return image_bytes


def truncate_text(text: str, max_lines: int = 10, max_chars: int = 300) -> str:
    try:
        text = html.escape(text)
        if len(text) < max_chars and text.count('\n') < max_lines:
            return text
        text = '<blockquote expandable>' + text[:3500] + '</blockquote>'
        return text
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'utils:truncate_text {error}\n{text}\n{max_lines} {max_chars}\n\n{traceback_error}')
        return text


def extract_user_id(user_id_string: str) -> int:
    """
    Extracts the user ID (the first number) from a string like 'user_id = '[2534346] [0]'' using regular expressions.

    Args:
        user_id_string: The input string containing the user ID.

    Returns:
        The extracted user ID as an integer.
        Returns 0 if the input string is not in the expected format or does not contain a valid number.
    """
    match = re.search(r'\[(-?\d+)\]', user_id_string)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return 0
    return 0


def format_timestamp(timestamp: float) -> str:
    """
    Преобразует timestamp в человекочитаемый формат,
    где месяц написан словами.

    Args:
        timestamp: Timestamp (число секунд с начала эпохи).

    Returns:
        Строка с датой и временем в формате 'День Месяц Год Час:Минута:Секунда'.
    """
    datetime_object = datetime.datetime.fromtimestamp(timestamp)
    month_name = datetime_object.strftime('%B')
    day = datetime_object.strftime('%d')
    year = datetime_object.strftime('%Y')
    time_str = datetime_object.strftime('%H:%M:%S')
    
    return f"{day} {month_name} {year} {time_str}"


def extract_large_ids(text: str, min_digits: int = 5) -> List[str]:
    """
    Extracts IDs (large numbers with a minimum number of digits) from a text string,
    including negative numbers.

    Args:
        text: The input text containing IDs.
        min_digits: Minimum number of digits for a number to be considered as an ID

    Returns:
        A list of extracted IDs as strings, including the square brackets and [0] part.
    """
    pattern = r'(\D|^)(-?\d{' + str(min_digits) + r',})(\D|$)'
    matches = re.findall(pattern, text)
    return [f'[{match[1]}] [0]' for match in matches]


def extract_retry_seconds(text: str) -> int:
    """
    Extracts the number of seconds after the "retry after" phrase from a text.

    Args:
        text: The input text containing the "retry after" phrase.

    Returns:
        The number of seconds as an integer, or None if not found.
    """
    pattern = r"retry after (\d+)"
    match = re.search(pattern, text)
    if match:
        return int(match.group(1))
    return 0


def shorten_all_repeats(text: str, min_repetitions: int = 200, max_keep: int = 10) -> str:
    """
    Detects and shortens all sequences of repeating characters throughout the text.

    Args:
        text: The input string.
        min_repetitions: The minimum number of repetitions to consider for shortening.
        max_keep: The maximum number of repetitions to keep.

    Returns:
        The string with all repeated character sequences shortened.
    """
    def replace_repeat(match):
        repeated_unit: str = match.group(1)
        return repeated_unit * max_keep

    pattern: str = r"(.+?)\1{" + str(min_repetitions - 1) + ",}"
    return re.sub(pattern, replace_repeat, text, flags=re.DOTALL)


def get_ytb_proxy(url: str = None) -> str:
    '''return insert line with proxy if any else Empty string'''

    # # no proxy for vimeo
    # if url and 'vimeo' in url:
    #     return ''

    if hasattr(cfg, 'YTB_PROXY') and cfg.YTB_PROXY:
        proxy = random.choice(cfg.YTB_PROXY)
        result = f' --proxy "{proxy}" '
    else:
        result = ''

    return result


def audio_duration(audio_file: Union[str, bytes]) -> int:
    """
    Get the duration of an audio file.

    Args:
        audio_file: The path to the audio file (str) or the audio file content as bytes.

    Returns:
        int: The duration of the audio file in seconds.
    """
    tmpfname = ''
    if isinstance(audio_file, bytes):
        # Create a temporary file to pass to ffprobe
        tmpfname = get_tmp_fname()
        with open(tmpfname, 'wb') as f:
            f.write(audio_file)
        audio_file = tmpfname

    duration_seconds = 0
    try:
        # Execute ffprobe to get the duration
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', audio_file],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=True  # Raise CalledProcessError for non-zero return codes
        )
        if result.stdout:
            try:
                # Convert the output to float and then to integer
                duration_seconds = int(float(result.stdout.decode('utf-8').strip()))
            except ValueError:
                my_log.log2(f'utils:audio_duration Could not convert ffprobe output to float: {result.stdout}')
    except subprocess.CalledProcessError as error:
        my_log.log2(f'utils:audio_duration ffprobe failed for {audio_file}\n{error}')
    except FileNotFoundError as error:
        my_log.log2(f'utils:audio_duration ffprobe not found\n{error}')
    except Exception as error:
        my_log.log2(f'utils:audio_duration {audio_file}\n{error}')
    finally:
        # Clean up the temporary file if it was created
        if tmpfname:
            remove_file(tmpfname)

    return duration_seconds


def srt_to_text(cap_srt: str) -> str:
    """Converts an SRT subtitle string to plain text.

    Args:
        cap_srt: A string containing subtitles in SRT format.

    Returns:
        A string with the extracted text from the subtitles.
        Returns an empty string ('') if an error occurs during processing.
    """
    try:
        subs = pysrt.from_string(cap_srt)
        text = subs.text
        return text
    except pysrt.Error:
        return ''


if __name__ == '__main__':
    pass

    # with open('C:/Users/user/Downloads/1.srt', 'r', encoding='utf8') as f:
    #     srt_text = f.read()
    # text = srt_to_text(srt_text)
    # print(text)

    # print(get_filename_from_url('https://youtu.be/1234567890.ogg'))


    # with open('C:/Users/user/Downloads/test.md', 'r', encoding='utf8') as f:
    #     text = f.read()
    #     html = bot_markdown_to_html(text)
    #     print(html)

    with open(r'c:\Users\user\Downloads\большая фотография (пережато).jpg', 'wb') as f:
        f.write(resize_and_convert_to_jpg(r'c:\Users\user\Downloads\samples for ai\большая фотография.jpg'))
