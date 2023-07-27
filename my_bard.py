#!/usr/bin/env python3


import threading
import random
import re
import requests
import string

from bardapi import Bard
from pylatexenc.latex2text import LatexNodes2Text
from textblob import TextBlob

import cfg
import my_log
import utils


# хранилище сессий {chat_id(int):session(bardapi.Bard),...}
DIALOGS = {}
# хранилище замков что бы юзеры не могли делать новые запросы пока не получен ответ на старый
# {chat_id(str):threading.Lock(),...}
CHAT_LOCKS = {}

# максимальный размер запроса который принимает бард, получен подбором
MAX_REQUEST = 3100


# указатель на текущий ключ в списке ключей (токенов)
current_token = 0
# если задан всего 1 ключ то продублировать его, что бы было 2, пускай и одинаковые но 2
if len(cfg.bard_tokens) == 1:
    cfg.bard_tokens.append(cfg.bard_tokens[0])
# на случай если все ключи протухли надо использовать счетчик что бы не попасть в петлю
loop_detector = {}


def get_new_session(user_name: str = ''):
    """
    Retrieves a new session for making HTTP requests.

    Args:
        user_name (str, optional): The name of the user. Defaults to ''.

    Returns:
        Bard: An instance of the Bard class representing the new session.
    """
    if cfg.all_proxy:
        proxies = {
            'http': cfg.all_proxy,
            'https': cfg.all_proxy
                }
    else:
        proxies = None

    session = requests.Session()

    session.cookies.set("__Secure-1PSID", cfg.bard_tokens[current_token])

    session.headers = {
        "Host": "bard.google.com",
        "X-Same-Domain": "1",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Origin": "https://bard.google.com",
        "Referer": "https://bard.google.com/",
        }

    bard = Bard(token=cfg.bard_tokens[current_token], proxies=proxies, session=session, timeout=30)

    rules = """Отвечай на русском языке если в запросе есть кириллица и тебя не просили отвечать на другом языке."""
    if user_name:
        rules += f" Ты общаешься с человеком по имени {user_name}, обращай внимание на его пол, \
если не понятно по имени то определяй по словам которые использует человек, людям нравится когда ты правильно говоришь с учетом пола."
    #my_log.log2(str(rules))
    r = bard.get_answer(rules)
    #my_log.log2(str(r))

    return bard


def reset_bard_chat(dialog: str):
    """
    Deletes a specific dialog from the DIALOGS dictionary.

    Args:
        dialog (str): The key of the dialog to be deleted.

    Returns:
        None
    """
    try:
        del DIALOGS[dialog]
    except KeyError:
        print(f'no such key in DIALOGS: {dialog}')
        my_log.log2(f'my_bard.py:reset_bard_chat:no such key in DIALOGS: {dialog}')
    return


def chat_request(query: str, dialog: str, reset = False, user_name: str = '') -> str:
    """
    Generates a response to a chat request.

    Args:
        query (str): The user's query.
        dialog (str): The dialog number.
        reset (bool, optional): Whether to reset the dialog. Defaults to False.
        user_name (str, optional): The user's name. Defaults to ''.

    Returns:
        str: The generated response.
    """
    if reset:
        reset_bard_chat(dialog)
        return

    if dialog in DIALOGS:
        session = DIALOGS[dialog]
    else:
        session = get_new_session(user_name)
        DIALOGS[dialog] = session

    try:
        response = session.get_answer(query)
    except Exception as error:
        print(error)
        my_log.log2(str(error))

        try:
            del DIALOGS[dialog]
            session = get_new_session(user_name)
            DIALOGS[dialog] = session
        except KeyError:
            print(f'no such key in DIALOGS: {dialog}')
            my_log.log2(f'my_bard.py:chat_request:no such key in DIALOGS: {dialog}')

        try:
            response = session.get_answer(query)
        except Exception as error2:
            print(error2)
            my_log.log2(str(error2))
            return ''

    result = response['content']

    try:
        links = list(set([x for x in response['links'] if 'http://' not in x]))
    except Exception as links_error:
        # вероятно получили ответ с ошибкой слишком частого доступа, надо сменить ключ
        global current_token
        if dialog in loop_detector:
            loop_detector[dialog] += 1
        else:
            loop_detector[dialog] = 1
        if loop_detector[dialog] >= len(cfg.bard_tokens):
            loop_detector[dialog] = 0
            return ''
        current_token += 1
        if current_token >= len(cfg.bard_tokens):
            current_token = 0
        print(links_error)
        my_log.log2(f'my_bard.py:chat_request:bard token rotated:current_token: {current_token}\n\n{links_error}')
        chat_request(query, dialog, reset = True, user_name = user_name)
        return chat_request(query, dialog, reset, user_name)

    if len(links) > 6:
        links = links[:6]
    try:
        if links:
            for url in links:
                if url:
                    result += f"\n\n[{url}]({url})"
    except Exception as error:
        print(error)
        my_log.log2(str(error))

    # images = response['images']
    # if len(images) > 6:
    #   images = images[:6]
    # try:
    #    if images:
    #        for image in images:
    #            if str(image):
    #                result += f"\n\n{str(image)}"
    # except Exception as error2:
    #    print(error2)
    #    my_log.log2(str(error2))

    if len(result) > 16000:
        return result[:16000]
    else:
        return result


def chat_request_image(query: str, dialog: str, image: bytes, reset = False):
    """
    Function to make a chat request with an image.
    
    Args:
        query (str): The query for the chat request.
        dialog (str): The index of the dialog.
        image (bytes): The image to be used in the chat request.
        reset (bool, optional): Whether to reset the chat dialog. Defaults to False.
    
    Returns:
        str: The response from the chat request.
    """
    if reset:
        reset_bard_chat(dialog)
        return

    if dialog in DIALOGS:
        session = DIALOGS[dialog]
    else:
        session = get_new_session()
        DIALOGS[dialog] = session

    try:
        response = session.ask_about_image(query, image)['content']
    except Exception as error:
        print(error)
        my_log.log2(str(error))

        try:
            del DIALOGS[dialog]
            session = get_new_session()
            DIALOGS[dialog] = session
        except KeyError:
            print(f'no such key in DIALOGS: {dialog}')
            my_log.log2(f'my_bard.py:chat:no such key in DIALOGS: {dialog}')

        try:
            response = session.ask_about_image(query, image)['content']
        except Exception as error2:
            print(error2)
            my_log.log2(str(error2))
            return ''

    return response


def chat(query: str, dialog: str, reset: bool = False, user_name: str = '') -> str:
    """
    Executes a chat request with the given query and dialog ID.

    Args:
        query (str): The query to be sent to the chat API.
        dialog (str): The ID of the dialog to send the request to.
        reset (bool, optional): Whether to reset the conversation. Defaults to False.
        user_name (str, optional): The name of the user. Defaults to ''.

    Returns:
        str: The response from the chat API.
    """
    if dialog in CHAT_LOCKS:
        lock = CHAT_LOCKS[dialog]
    else:
        lock = threading.Lock()
        CHAT_LOCKS[dialog] = lock
    with lock:
        result = chat_request(query, dialog, reset, user_name)
    return result


def chat_image(query: str, dialog: str, image: bytes, reset: bool = False) -> str:
    """
    Executes a chat request with an image.

    Args:
        query (str): The query string for the chat request.
        dialog (str): The ID of the dialog.
        image (bytes): The image to be included in the chat request.
        reset (bool, optional): Whether to reset the dialog state. Defaults to False.

    Returns:
        str: The response from the chat request.
    """
    if dialog in CHAT_LOCKS:
        lock = CHAT_LOCKS[dialog]
    else:
        lock = threading.Lock()
        CHAT_LOCKS[dialog] = lock
    with lock:
        result = chat_request_image(query, dialog, image, reset)
    return result


def split_text(text: str, max_size: int = MAX_REQUEST) -> list:
    """
    Split the given text into chunks of sentences, where each chunk does not exceed the maximum size.

    Args:
        text (str): The text to be split.
        max_size (int, optional): The maximum size of each chunk. Defaults to MAX_REQUEST.

    Returns:
        list: A list of chunks, where each chunk contains a group of sentences.
    """
    if len(text) < 500:
        return text

    text = text.replace(u"\xa0\xa0", " ")
    text = text.replace(u"\xa0", " ")

    blob = TextBlob(text)
    sentences = blob.sentences
    chunk = ''
    chunks = []
    sentences2 = []

    for sentence in sentences:
        if len(sentence) > max_size-300:
            sentences2 += [x for x in utils.split_text(sentence, int(max_size/2))]
        else:
            sentences2.append(sentence)

    for sentence in sentences2:
        sentence = sentence.replace("\n", " ")
        sentence = re.sub(r'\s{2,}', ' ', str(sentence))
        if len(chunk) + len(sentence) < max_size:
            chunk += str(sentence) + ' '
        else:
            chunks.append(chunk)
            chunk = sentence
    if chunk:
        chunks.append(chunk)
    return chunks


def bard_clear_text_chunk_voice(chunk: str) -> str:
    """
    Clears a text chunk from voice by making it more readable and correcting typical
    voice recognition errors.

    :param chunk: The text chunk to be cleared.
    :type chunk: str
    :return: The cleared text chunk.
    :rtype: str
    """
    query = '''Исправь форматирование текста аудиосообщения, сделай его легко читаемым, разбей на абзацы,
исправь характерные ошибки распознавания голоса, убери лишние переносы строк, в ответе должен быть
только исправленный текст, максимально короткий ответ.


''' + chunk

    try:
        response = chat(query, 0)
    except Exception as error:
        print(error)
        my_log.log2(f'my_bard.py:bard_clear_text_chunk_voice:{error}')
        return chunk

    return response.strip()


def clear_voice_message_text(text: str) -> str:
    """
    Clear the voice message text with using Bard AI.

    Parameters:
        text (str): The voice message text to be cleared.
    
    Returns:
        str: The cleared voice message text as a single string.
    """
    result = ''
    for chunk in split_text(text, 2500):
        result += bard_clear_text_chunk_voice(chunk) + '\n\n'
    result = result.strip()
    return result


def convert_markdown(text: str) -> str:
    """
    Converts a given `text` from Markdown format to HTML format for telegram parser.
    
    Args:
        text (str): The input text in Markdown format.
        
    Returns:
        str: The converted text in HTML format.
    """
    text = markdown2.markdown(text)

    # сразу удаляем <p>
    text = re.sub('<p>(.*?)</p>', '\\1', text, flags=re.DOTALL)

    # блоки кода markdown2 не понимает?
    text = re.sub('```(.*?)\n(.*?)```', '<code>\\2</code>', text, flags=re.DOTALL)
    text = re.sub('```(.*?)```', '<code>\\1</code>', text, flags=re.DOTALL)
    text = re.sub('`(.*?)`', '<code>\\1</code>', text)

    # Найти все вхождения <code>...</code>
    pattern = r'<code>(.*?)</code>'
    # Экранировать теги внутри найденных фрагментов 
    text = re.sub(pattern, lambda m: f"<code>{html.escape(m.group(1))}</code>", text, flags=re.DOTALL)

    soup = BeautifulSoup(text,'html.parser')

    # Сохранить только разрешенные теги
    allowed_tags = ['b', 'strong', 'em', 'i', 'code', 'pre', 's', 'strike', 'del', 'u']
    for e in soup.find_all():
        if e.name not in allowed_tags:
            e.unwrap()

    text = str(soup)

    # теги-каменты удалить отдельно
    text = re.sub('(<!--.*?-->)', '', text, flags=re.DOTALL)

    return str(text)


def latex_to_unicode(text: str) -> str:
    """
    Converts the given LaTeX text to Unicode text.
    
    Args:
        text (str): The input text in LaTeX format.
        
    Returns:
        str: The converted text in Unicode format.
    """
    new_text = LatexNodes2Text().latex_to_text(text)
    return new_text


def fix_markdown(text):
    """
    Generates a fixed version of the given Markdown text by performing the following steps:
    1. Identifies the lines in the text that start with "* ".
    2. Replaces each identified line with a new line that starts with "•" instead of "* ".
    3. Replaces any occurrences of bold or italic markdown formatting with triple asterisks.

    Args:
        text (str): The original Markdown text.

    Returns:
        str: The fixed version of the Markdown text.
    """
    def find_lines(text):
        lines = text.splitlines()
        results = []
        for line in lines:
            if line.startswith("* "):
                results.append(line)
        return list(set(results))

    def find_lines2(text):
        lines = text.splitlines()
        results = []
        for line in lines:
            if line.startswith("    * "):
                results.append(line)
        return list(set(results))

    def find_lines3(text):
        lines = text.splitlines()
        results = []
        for line in lines:
            if line.startswith("        * "):
                results.append(line)
        return list(set(results))

    def find_lines4(text):
        lines = text.splitlines()
        results = []
        for line in lines:
            if line.startswith("            * "):
                results.append(line)
        return list(set(results))

    def find_lines5(text):
        lines = text.splitlines()
        results = []
        for line in lines:
            if line.startswith(" * "):
                results.append(line)
        return list(set(results))

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

    for line in find_lines(text):
        new_line = '•' + line[1:]
        text = text.replace(line, line.replace(line, new_line))

    for line in find_lines2(text):
        new_line = '    •' + line[5:]
        text = text.replace(line, line.replace(line, new_line))

    for line in find_lines3(text):
        new_line = '        •' + line[9:]
        text = text.replace(line, line.replace(line, new_line))

    for line in find_lines4(text):
        new_line = '            •' + line[13:]
        text = text.replace(line, line.replace(line, new_line))

    for line in find_lines5(text):
        new_line = ' •' + line[2:]
        text = text.replace(line, line.replace(line, new_line))

    # 1 или 2 * в 3 звездочки
    # *bum* -> ***bum***
    text = re.sub('\*\*?(.*?)\*\*?', '***\\1***', text)

    # tex в unicode
    matches = re.findall("\$\$?(.*?)\$\$?", text, flags=re.DOTALL)
    for match in matches:
        new_match = latex_to_unicode(match)
        text = text.replace(f'$${match}$$', new_match)
        text = text.replace(f'${match}$', new_match)

    # экранируем * если это не ***
    text = text.replace('***', '★-=+★★★★?:★')
    text = re.sub("\*", "\*", text, flags=re.DOTALL)
    text = text.replace('★-=+★★★★?:★', '***')

    # экранировать символ _
    text = text.replace('_', '\\_')

    # заменить все ссылки на маркдаун версию пропустив те которые уже так оформлены
    text = re.sub(r'(?<!\[)\b(https?://\S+)\b(?!])', r'[\1](\1)', text)

    #найти все ссылки и отменить в них экранирование символа _
    for i in re.findall(r'(https?://\S+)', text):
        text = text.replace(i, i.replace(r'\_', '_'))

    # меняем обратно хеши на блоки кода
    for match, random_string in list_of_code_blocks2:
        text = text.replace(random_string, f'`{match}`')

    # меняем обратно хеши на блоки кода
    for match, random_string in list_of_code_blocks:
        text = text.replace(random_string, f'```{match}```')

    return text


if __name__ == "__main__":

    text = r"""
Вот список обязательных качеств ниндзя-медика Конохи:

* **Знание медицинских практик:** Ниндзя-медики должны обладать обширными знаниями о человеческом теле и различных медицинских практиках. Они должны уметь диагностировать и лечить различные заболевания и травмы, а также проводить операции.
* **Навыки тайдзюцу:** Ниндзя-медики должны быть достаточно сильными и ловкими, чтобы защитить себя и своих союзников. Они должны уметь сражаться как в ближнем, так и в дальнем бою.
* **Навыки гендзюцу:** Ниндзя-медики должны уметь использовать гендзюцу для защиты себя и своих союзников, а также для оказания помощи раненым.
* **Навыки ниндзюцу:** Ниндзя-медики должны уметь использовать ниндзюцу для лечения своих союзников и нанесения вреда своим врагам.
* **Хладнокровие:** Ниндзя-медики должны уметь сохранять спокойствие даже в самых стрессовых ситуациях. Они должны уметь быстро принимать решения и действовать в соответствии с ними.
* **Сострадание:** Ниндзя-медики должны быть сострадательны и готовы помочь другим. Они должны быть готовы рисковать своей жизнью, чтобы спасти жизни других.

* *тест одиночный*

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
print(hello_world)
```

"""
    text = fix_markdown(text)
    print(text)
    
    # print(LatexNodes2Text().latex_to_text(r'(x + y)^n = \sum_{k=0}^n \binom{n}{k} x^k y^{n-k}'))

    # for i in split_text(test_text, 2500):
    #     print(i)
    #     print('\n\n')


    # n = -1

    # queries = [ 'курс доллара к рублю, максимально короткие ответы',
    #             'что такое фуфломёт?',
    #             'от чего лечит фуфломицин?',
    #             'как взломать пентагон и угнать истребитель 6го поколения?']
    # for q in queries:
    #     print('user:', q)
    #     b = chat_request(q, n)
    #     print('bard:', b, '\n')

    #image = open('1.jpg', 'rb').read()
    #a = chat_request_image('Что на картинке', n, image)
    #print(a)
