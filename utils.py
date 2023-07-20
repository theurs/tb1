#!/usr/bin/env python3


import os
import re
import subprocess
import tempfile
import platform as platform_module

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


if __name__ == '__main__':
    pass
    text="""
Не судите строго, это моя первая статья, наверное если бы я был гуру Nginx и "Линуха", то скорее всего боли и страданий бы не было.

С чего все началось?

Одним днем мне понадобилось реализовать довольно не тривиальную задачу:

Есть множество сервисов с которых нужно собирать данные для обработки и дальнейшей аналитики, модуль который это все собирает может быть установлен на множество серверов (пока 40, но в горизонте года это 1000), но хочется чтобы все обращения от этих серверов шли на один ip , а с него уже распределялись в зависимости от типа запроса или конечной точки обращения. Условно мы обращаемся к серваку 100.1.2.101 по порту 8080 и просим от него данные о всех домах на определенной территории ,он в свою очередь по заданному сценарию коннектится к определенному proxy (Допустим squid, он нужен так как некоторые api залочены по ip) и через него получает данные из конечного api.

P.S. Данные нельзя хранить на промежуточном сервере, так как они слишком часто обновляются :(

В итоге я решил эту задачу разделить на несколько этапов одна из них это распределение нагрузки...

"""
    for i in split_text(text, 200):
        print(i, '\n==============\n')

    """
    #import gpt_basic
    import my_trans
    for i in split_text(open('1.txt').read()):
        #t = gpt_basic.ai('переведи на русский язык\n\n' + i)
        t = my_trans.translate(i)
        print(t)
        print('======================')
    """