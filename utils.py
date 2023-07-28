#!/usr/bin/env python3


import html
import os
import random
import re
import string
import subprocess
import tempfile
import platform as platform_module

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


if __name__ == '__main__':
    text = r"""
$$\\frac{16}{9} = \\frac{x}{178}$$
Вот список обязательных качеств ниндзя-медика Конохи:

* **Знание медицинских практик:** Ниндзя-медики должны обладать обширными знаниями о человеческом теле и различных медицинских практиках. Они должны уметь диагностировать и лечить различные заболевания и травмы, а также проводить операции.
* **Навыки тайдзюцу:** Ниндзя-медики должны быть достаточно сильными и ловкими, чтобы защитить себя и своих союзников. Они должны уметь сражаться как в ближнем, так и в дальнем бою.
* **Навыки гендзюцу:** Ниндзя-медики должны уметь использовать гендзюцу для защиты себя и своих союзников, а также для оказания помощи раненым.
* **Навыки ниндзюцу:** Ниндзя-медики должны уметь использовать ниндзюцу для лечения своих союзников и нанесения вреда своим врагам.
* **Хладнокровие:** Ниндзя-медики должны уметь сохранять спокойствие даже в самых стрессовых ситуациях. Они должны уметь быстро принимать решения и действовать в соответствии с ними.
* **Сострадание:** Ниндзя-медики должны быть сострадательны и готовы помочь другим. Они должны быть готовы рисковать своей жизнью, чтобы спасти жизни других.

Ниндзя-медики - одни из самых важных членов деревни Коноха. Они несут ответственность за здоровье и благополучие своих сограждан. Чтобы стать ниндзя-медиком, нужно обладать всеми вышеперечисленными качествами.

Хорошо, вот некоторые формулы, связанные с теорией относительности:

* **Специальная теория относительности:**
    * **Уравнение Эйнштейна:** $E = mc^2$, где E — энергия, m — масса, а c — скорость света в вакууме.
    * **Уравнение Лоренца:** $t' = \frac{t}{\sqrt{1 - \frac{v^2}{c^2}}}$, где t' — время, измеренное в движущейся системе, а t — время, измеренное в неподвижной системе.
* **Общая теория относительности:**
    * **Уравнение Эйнштейна:** $R_{\mu \nu} - \frac{1}{2} R g_{\mu \nu} = \kappa T_{\mu \nu}$, где R — тензор кривизны, g — метрический тензор, T — тензор энергии-импульса, >    * **Уравнение Шварцшильда:** $r = \frac{2GM}{c^2}$, где r — радиус Шварцшильда, G — гравитационная постоянная, M — масса объекта, а c — скорость света в вакууме.

Эти формулы являются лишь некоторыми из многих, которые используются в теории относительности. Они описывают различные аспекты теории, от взаимосвязи между энергией и массой>

Я надеюсь, это было интересно!

Overall, LZ4 is a powerful and versatile compression algorithm that can be used to improve the performance of a wide variety of applications. It is fast, efficient, and versatile, but it is not as good as some other algorithms for some data types.
https://en.wikipedia.org/wiki/LZ4_(compression_algorithm) hi there
https://en.wikipedia.org/wiki/LZ4_(compression_algorithm)
https://en.wikipedia.org/wiki/LZ4_(compression_algorithm) dfgdfg
                                                                                                                                                                              * https://google.com
* https://www.wikipedia.org
* https://www.youtube.com
* https://www.facebook.com
* https://www.twitter.com

[26-07-2023 20:56:55] [BOT]: Кольца Сатурна — одно из самых впечатляющих и загадочных явлений в Солнечной системе. Они состоят из миллиардов ледяных и каменных частиц, котор>

Кольца Сатурна были открыты в 1610 году итальянским астрономом Галилео Галилеем. Он использовал телескоп, чтобы впервые увидеть кольца планеты. Позже, в 1789 году, английски>

Кольца Сатурна постоянно движутся и изменяются. Частицы, из которых они состоят, сталкиваются друг с другом и разрушаются. Это приводит к образованию новых частиц и формиров>

Кольца Сатурна — одна из самых удивительных и загадочных загадок Солнечной системы. Ученые до сих пор не могут полностью объяснить, как они образовались и как эволюционируют>

Вот несколько фотографий колец Сатурна, которые были сделаны космическими аппаратами НАСА:

Фотография колец Сатурна, сделанная космическим аппаратом "Кассини": https://www.nasa.gov/multimedia/imagegallery/image_feature_404.html

Фотография колец Сатурна, сделанная космическим аппаратом "Вояджер-1": https://www.nasa.gov/multimedia/imagegallery/image_feature_402.html

Фотография колец Сатурна, сделанная космическим аппаратом "Хопи": https://www.nasa.gov/multimedia/imagegallery/image_feature_403.html

Эти фотографии показывают красоту и сложность колец Сатурна. Они являются напоминанием о том, что Солнечная система — это удивительное место, полное загадок и чудес.

[test](https://en.wikipedia.org/wiki/LZ4_(compression_algorithm))

- Если разрешение 72 PPI, то ширина в пикселях равна $$\frac{316.4 \times 10^6}{72} \approx 4.4 \times 10^6$$
- Если разрешение 150 PPI, то ширина в пикселях равна $$\frac{316.4 \times 10^6}{150} \approx 2.1 \times 10^6$$
- Если разрешение 300 PPI, то ширина в пикселях равна $$\frac{316.4 \times 10^6}{300} \approx 1.1 \times 10^6$$

$$\text{ширина в пикселях} = \frac{\text{количество пикселей по горизонтали}}{\text{разрешение}}$$

где количество пикселей по горизонтали мы уже нашли ранее и оно равно примерно 316.4 миллиона. Например, если вы хотите знать ширину в пикселях для разрешения 200 PPI, то вы можете подставить эти значения в формулу и получить:

$$\text{ширина в пикселях} = \frac{316.4 \times 10^6}{200} \approx 1.6 \times 10^6$$


Общее количество пикселей в фотографии составляет 178 миллионов. Соотношение сторон 16 к 9 означает, что соотношение ширины к высоте составляет 1

* Ширина (пиксели) = Общее количество пикселей * (Ширина / Высота)

Подставив значения, мы получим:

* Ширина (пиксели) = 178 миллионов * (16 / 9)
* Ширина (пиксели) = 1920 пикселей

Итак, ширина фотографии составляет 1920 пикселей.

\binom{n}{k} = \frac{n!}{k!(n-k)!}

_тест_

```
print('<b>hello_world</b>')
```
Как видите, программа успешно заменила теги <body> <b> </b> на теги <i> </i>.

**В конечном счете, решение о том, покупать ли роутер или нет, зависит от конкретных потребностей пользователя.**
* ** Если вам нужен способ подключить к интернету несколько устройств, защитить свои данные и фильтровать трафик, то роутер - это хороший вариант. Однако, если вы не нуждаетесь в этих функциях, то роутер может быть для вас излишней тратой средств.**
* ** Если вам нужен способ подключить к интернету несколько устройств, защитить свои данные и фильтровать трафик, то роутер - это хороший вариант. Однако, если вы не нуждаетесь в этих функциях, то роутер может быть для вас излишней тратой средств.**
* ** Если вам нужен способ подключить 

* *тест одиночный* 2*2=4 2*3=6

$$\\frac{16}{9} = \\frac{x}{178}$$
"""
    text = bot_markdown_to_html(text)
    print(text)
