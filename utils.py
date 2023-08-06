#!/usr/bin/env python3


import html
import os
import random
import re
import string
import subprocess
import tempfile
import platform as platform_module

from bs4 import BeautifulSoup
from pylatexenc.latex2text import LatexNodes2Text

import my_log

# диалог всегда начинается одинаково

gpt_start_message1 = 'Ты искусственный интеллект отвечающий на запросы юзера.'
gpt_start_message2 = 'Ты искусственный интеллект отвечающий на запросы юзера. Отвечай с подходящим к запросу типом иронии или юмора но не перегибай палку. Добавляй один смайлик с подходящей эмоцией если это уместно.'
#gpt_start_message3 = 'Ты искусственный интеллект отвечающий на запросы юзера. Отвечай с сильной иронией и токсичностью.'
gpt_start_message3 = 'Ты троль из интернета. Отвечай с сильной иронией и токсичностью.'
gpt_start_message4 = 'Ты известная порно актриса Ева Элфи и отвечаешь на вопросы поклонников в телеграм чате, твои ответы всегда очень горячие и провокационные, короткие, с жаргоном из порноиндустрии, намекающие на порно.'

def escape_markdown(text):
    """
    Escapes special characters in a given text using Markdown escape sequences.

    Args:
        text (str): The text to escape.

    Returns:
        str: The escaped text.
    """
    pattern = r"([_*\[\]~|`])"
    my_log.log2(text + '\n\n\n\n')
    return re.sub(pattern, r"\\\1", text)


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


class MessageList:
    """список последних сообщений в чате с заданным максимальным размером в байтах
    это нужно для суммаризации событий в чате с помощью бинга
    """
    def __init__(self, max_size=60000):
        self.max_size = max_size
        self.messages = []
        self.size = 0

    def append(self, message: str):
        assert len(message) < (4*1024)+1
        message_bytes = message.encode('utf-8')
        message_size = len(message_bytes)
        if self.size + message_size > self.max_size:
            while self.size + message_size > self.max_size:
                oldest_message = self.messages.pop(0)
                self.size -= len(oldest_message.encode('utf-8'))
        self.messages.append(message)
        self.size += message_size


def split_text(text: str, chunk_limit: int = 1500):
    """
    Splits a text into chunks of a specified length without breaking words.

    Args:
        text (str): The text to be split.
        chunk_limit (int, optional): The maximum length of each chunk. Defaults to 1500.

    Returns:
        list: A list of chunks of the text.

    Note:
        If no spaces are found in the text, the chunks may be larger than the specified limit.
    """
    chunks = []
    position = 0
    while position < len(text):
        space_index = text.find(" ", position + chunk_limit)
        if space_index == -1:
            space_index = len(text)
        chunks.append(text[position:space_index])
        position = space_index + 1
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


def bot_markdown_to_html(text):
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

    # 1 или 2 * в 3 звездочки
    # *bum* -> ***bum***
    # text = re.sub('\*\*?(.*?)\*\*?', '***\\1***', text)
    text = re.sub('\*\*(.+?)\*\*', '<b>\\1</b>', text)
    # одиночные звезды невозможно нормально заменить Ж( как впрочем и пары
    # text = re.sub('\*(.+?)\*', '<b>\\1</b>', text)

    # tex в unicode
    matches = re.findall("\$\$?(.*?)\$\$?", text, flags=re.DOTALL)
    for match in matches:
        new_match = LatexNodes2Text().latex_to_text(match.replace('\\\\', '\\'))
        text = text.replace(f'$${match}$$', new_match)
        text = text.replace(f'${match}$', new_match)

    # меняем маркдаун ссылки на хтмл
    text = re.sub(r'\[([^]]+)\]\((https?://\S+)\)', r'<a href="\2">\1</a>', text)
    # меняем все ссылки на ссылки в хтмл теге кроме тех кто уже так оформлен
    text = re.sub(r'(?<!<a href=")(https?://\S+)(?!">[^<]*</a>)', r'<a href="\1">\1</a>', text)

    # меняем обратно хеши на блоки кода
    for match, random_string in list_of_code_blocks2:
        # new_match = html.escape(match)
        new_match = match
        text = text.replace(random_string, f'<code>{new_match}</code>')

    # меняем обратно хеши на блоки кода
    for match, random_string in list_of_code_blocks:
        new_match = match
        text = text.replace(random_string, f'<code>{new_match}</code>')

    return text


def split_html(text, max_length):
    chunks = []
    current_chunk = []
    for i in range(len(text)):
        if len(current_chunk) + 1 > max_length:
            chunks.append(''.join(current_chunk))
            current_chunk = []
        current_chunk.append(text[i])
    chunks.append(''.join(current_chunk))

    return chunks

def add_closing_tags(text):
    pattern = re.compile(r'<(b|code|a)[^>]*>')
    result = pattern.sub(r'<\1></\1>', text)
    return result

def split_and_add_closing_tags(text, max_length):
    chunks = split_html(text, max_length)
    for i in range(len(chunks)):
        chunks[i] = add_closing_tags(chunks[i])
    return chunks


if __name__ == '__main__':
    text = r"""
Причины и окончание югославской войны
----------------------------------------
Югославские войны были серией конфликтов, которые происходили в бывшей Югославии с 1991 по 1999 год. Они привели к распаду страны и образованию новых государств: Словении, Хорватии, Боснии и Герцеговины, Сербии, Черногории и Македонии.

Причины югославских войн были многофакторными. Среди них можно выделить следующие:

• <b>Этнические и религиозные противоречия.</b> В Югославии проживало множество различных этнических групп, которые имели свои собственные религиозные традиции. Это привело к многочисленным конфликтам между этими группами.
• <b>Экономические проблемы.</b> Югославия была в состоянии экономического кризиса, который привел к росту безработицы и бедности. Это создало благодатную почву для социальных волнений.
• <b>Политические разногласия.</b> В Югославии не было единой политической системы, которая бы устраивала все этнические группы. Это привело к многочисленным конфликтам между различными политическими партиями.

Югославские войны закончились в 1999 году подписанием Охридских соглашений. Эти соглашения установили мир в Македонии и положили конец югославским войнам.

Югославские войны были одними из самых кровопролитных конфликтов в Европе после Второй мировой войны. В них погибло более 100 000 человек, а еще более 2 миллиона человек были вынуждены покинуть свои дома. Югославские войны оказали огромное влияние на развитие региона, и их последствия до сих пор ощущаются.

[Google Bard]
"""
    # text = split_html(text, 50)
    # for x in text:
    #     print('\n\n')
    #     print(x)

    # soup = BeautifulSoup(text)
    # print(soup)
    # for i in soup.sp
    #     print(i)