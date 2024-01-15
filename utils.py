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
        if i.startswith('<code>') and len(i) > 7:
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
        text = text.replace(table, f'<pre><code>{new_table}</code></pre>')

    return text


def split_html(text: str, max_length: int = 1500) -> list:
    """
    Split the given HTML text into chunks of maximum length, while preserving the integrity
    of HTML tags. The function takes two arguments:
    
    Parameters:
        - text (str): The HTML text to be split.
        - max_length (int): The maximum length of each chunk. Default is 1500.
        
    Returns:
        - list: A list of chunks, where each chunk is a part of the original text.
        
    Raises:
        - AssertionError: If the length of the text is less than or equal to 299.
    """
    if len(text) <= max_length:
        return [text,]
    def find_all(a_str, sub):
        start = 0
        while True:
            start = a_str.find(sub, start)
            if start == -1:
                return
            if sub.startswith('\n'):
                yield start+1
            else:
                yield start+len(sub)
            start += len(sub) # use start += 1 to find overlapping matches

    # find all end tags positions with \n after them
    positions = []
    # ищем либо открывающий тег в начале, либо закрывающий в конце
    tags = ['</b>\n','</a>\n','</pre>\n', '</code>\n',
            '\n<b>', '\n<a>', '\n<pre>', '\n<code>']

    for i in tags:
        for j in find_all(text, i):
            positions.append(j)

    chunks = []

    # нет ни одной найденной позиции, тупо режем по границе
    if not positions:
        chunks.append(text[:max_length])
        chunks += split_html(text[max_length:], max_length)
        return chunks

    for i in list(reversed(positions)):
        if i < max_length:
            chunks.append(text[:i])
            chunks += split_html(text[i:], max_length)
            return chunks

    # позиции есть но нет такой по которой можно резать,
    # значит придется резать просто по границе
    chunks.append(text[:max_length])
    chunks += split_html(text[max_length:], max_length)
    return chunks


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


if __name__ == '__main__':
    # print(is_image_link('https://keep.google.com/u/0/?pli=1#NOTE/1KA1ADEB_Cn9dNEiBKakN8BebZkOtBVCNpeOeFTFujVKkDYtyKGuNFzW-a6dYK_Q'))
    
    # print(get_full_time())    
    
    t1 = r"""
      На четырнадцатом году непрерывной агонии старый император наконец умер. 
        Михайло II правил Западным Краем без малого двадцать лет и бóльшую часть своего царствования был прикован к постели. Поначалу, когда император только занемог, никто не сомневался, что вскоре он отправится к праотцам, и его вероятные преемники уже мысленно примеряли на себя корону, отчаянно интригуя друг против друга. Но старик упрямо цеплялся за жизнь и никак не хотел умирать. Нобили Империи, прибывшие в столицу для избрания нового императора, после трёх месяцев напрасного ожидания и бесплодных интриг вынуждены были разъехаться несолоно хлебавши. Затем они ещё четырежды съезжались в Златовар при каждом новом известии о резком ухудшении здоровья императора - и каждый раз старый Михайло оставлял их в дураках. Даже на этот раз, самый последний, умерши окончательно и бесповоротно, он ухитрился подсунуть могущественным князьям большую свинью, поскольку умер, так сказать, без предупреждения - просто вечером уснул, а на утро не проснулся. 
        Специальные курьеры лишь покидали Златовар, неся во все концы огромного государства эту столь долгожданную скорбную весть, а Стэнислав, или проще Стэн, четырнадцатый князь Мышковицкий, воевода Гаалосага, хоть и находился более чем в тысяче миль к юго-западу от столицы, уже знал о кончине императора. Также он знал, что факт смерти Михайла II скрывали до самого полудня, а когда слухи об этом стали просачиваться из дворца в город, по всему императорскому домену началась беспрецедентная по своему размаху охота на голубей. Главной мишенью, разумеется, были почтовые голуби, но рассредоточенные вокруг столицы и близлежащих поселений лучники и арбалетчики для пущей верности отстреливали всех пернатых без разбора, даже ни в чём не повинных ворон. Старший сын Михайла, Чеслав, князь Вышеградский и регент Империи, во что бы то ни стало стремился выиграть время, чтобы успеть привести в действие изрядно заржавевший механизм давно уже подготовленного заговора по захвату верховной власти. Как и все прочие, за исключением горстки избранных, князь Чеслав не подозревал, что существует куда более быстрый способ передачи известий, чем с помощью голубей; а избранные - те, кто знал этот способ, - предпочитали держать его в тайне. 
        Впрочем, голубь, отправленный Стэну, избежал горькой участи многих своих собратьев. Он был выпущен за пределами владений Короны и должен был прилететь не раньше послезавтрашнего вечера. Лишь тогда можно будет во всеуслышание сообщить о кончине императора, а до тех пор нужно делать вид, будто ничего не случилось. Хорошо хоть, что к поездке в далёкий Златовар долго готовиться не придётся. На следующей неделе Стэн собирался в Лютицу, где вскоре должно было открыться ежегодное собрание земельного сейма Гаалосага. Так что он просто объявит о вынужденном изменении маршрута... Или не объявит - всё зависит от того, примет ли он предложение Флавиана. Если да, то император умер весьма своевременно - нет необходимости специально созывать сейм... 
        'Издох таки, сукин сын! - без тени сочувствия и с изрядной долей злорадства думал Стэн, энергично шагая по мощённой гладкими булыжниками набережной. Люди на его пути расступались, почтительно приветствуя своего молодого господина; он же отвечал им рассеянными кивками, целиком погружённый в собственные мысли. - Чтоб ты вечно горел в аду, Михайло!' 
        Стэн имел веские причины не питать к покойному императору тёплых чувств и не скорбеть по поводу его запоздалой кончины. Лет тринадцать назад, когда все ожидали, что Михайло II вот-вот умрёт, у князя Всевлада, отца Стэна, были неплохие шансы стать его преемником. И не просто неплохие, а отличные. Что же касается самого Стэна, то хоть он формально и числился среди претендентов на престол, его шансы были ничтожными. Ещё меньше надежд заполучить законным путём корону имел разве что нынешний регент Империи, князь Чеслав Вышеградский... 
        На молу, как всегда, было многолюдно и шумно. Огромное красное солнце уже начало погружаться в воды Ибрийского моря, но никаких признаков спада активности в порту не наблюдалось, скорее наоборот - с наступлением вечерней прохлады суета лишь усилилась. Жизнь здесь не замирала даже ночью. Мышкович был самым крупным морским портом на западном побережье Гаалосага и четвёртым по величине среди всех портов Западного Края. Моряки любовно называли его Крысовичем - в честь соответствующих грызунов, которыми кишмя кишит любой порт на свете. Стэн не считал этот каламбур удачным или хотя бы остроумным, постольку Мышкович было также его родовое имя, и происходило оно вовсе не от мышей, а от знаменитого воеводы Мышка, который четыреста с лишним лет назад заложил в устье реки Гарры замок Мышковар и построил порт Мышкович, который впоследствии стал главной ценностью его потомков, князей Мышковицких, и основным источником их богатства. 
        Сейчас на рейде в гавани стояло свыше полусотни кораблей разного водоизмещения, и среди них особо выделялись два огромных судна - новые трёхмачтовые красавцы, лишь в начале этого года сошедшие со стапелей на мышковицкой верфи. Корабли назывались 'Князь Всевлад' и 'Святая Илона'; завтра на рассвете они отправятся в плавание к неведомым берегам, на поиски западного морского пути в Хиндураш. Организовать такую экспедицию было заветной мечтой князя Всевлада - но осуществилась она лишь спустя девять лет после его смерти, благодаря стараниям Стэна, который завершил дело, начатое отцом... 
        С гордостью глядя на прекрасные корабли, равных которым не было на всём белом свете, Стэн вспомнил, как он, будучи ещё подростком, коротал долгие зимние вечера, изучая сложные чертежи и изобиловавшие неточностями морские карты; как, сидя у камина, он слушал увлекательные рассказы отца о великих мореплавателях прошлого; как они вместе мечтали о том дне, когда могучие суда поднимут свои белоснежные паруса и, подгоняемые попутным ветром, устремятся на запад, чтобы совершить невозможное - пересечь Великий Океан и бросить якорь у берегов далёкого восточного Хиндураша... 
        И Стэном с новой силой овладел гнев. 
        'Грязный ублюдок! - мысленно обратился он к покойному императору. - Если бы ты помер в срок, мой отец был бы ещё жив. И мама тоже... А что до тебя, Чеслав, то ты у меня ещё попляшешь. А потом я спляшу на твоей могиле...' 
        В смерти своих родителей Стэн не без оснований винил недавно преставившегося Михайла II и его ныне здравствующего сына, которые девять лет назад развязали бессмысленную войну с Норландом и вели её мало сказать, что бездарно. В этой войне погибли отец и мать Стэна, оставив его, шестнадцатилетнего юношу, с тяжким бременем власти на плечах и с подрастающей сестрёнкой на руках. И неизвестно ещё, какая из этих двух нош была тяжелее... 
        На главном причале шла погрузка на шлюпки последней партии продовольствия и питьевой воды, предназначенных для 'Князя Всевлада' и 'Святой Илоны'. Обратным рейсом эти шлюпки должны привезти на берег всех моряков - офицеры обоих кораблей были приглашены на праздничный ужин за княжеским столом, а рядовых матросов ждало щедрое угощение во дворе замка. 
        За погрузкой присматривал высокий рыжебородый мужчина лет сорока пяти, с широким скуластым лицом, огрубевшим от длительного воздействия солнечных лучей и солёного морского воздуха. Он был одет хорошо, со вкусом, но практично и без претензий. В любой момент он мог запросто скинуть камзол и шляпу и подсобить в работе матросам, не боясь испортить свой костюм. Звали его Младко Иштван; он был капитаном 'Святой Илоны' и руководителем экспедиции. Пожалуй, на всём западном побережье не сыскалось бы шкипера, который бы так подходил на эту роль. Иштван обладал огромным опытом в обращении с людьми и кораблями, во всех тонкостях владел искусством навигации и - что немаловажно - был одержим идеей найти западный путь в страну шёлка и пряностей. 
        Завидев своего князя, матросы разом прекратили погрузку; посыпались приветствия в его адрес и пожелания доброго здравия. Стэн кивнул им в ответ и сказал: 
        - Спасибо, друзья. Но прошу вас, продолжайте. Чем скорее вы управитесь, тем раньше начнётся пир. 
        Матросы с удвоенным рвением принялись за работу. А Иштван ухмыльнулся в рыжую бороду: 
        - Ну и задали вы мне задачку, газда Стэнислав. Боюсь, некоторые парни так напьются на дармовщину, что завтра не смогут встать. 
        - Это и будет для них первым испытанием, - невозмутимо заметил Стэн. - Вот почему я велел вам с Волчеком набрать больше людей, чем вы считали необходимым. Завтра можете отсеять лишних из числа невоздержанных и буянов. Для остальных это послужит хорошим уроком. 
        Иштван несколько раз недоуменно моргнул, затем громко захохотал: 
        - Однако хитрец вы, государь! Ловко придумано! 
        Матросы, не переставая работать, вопросительно поглядывали на своего капитана. Они не расслышали, что сказал ему Стэн, и им оставалось лишь гадать, почему Иштван смеётся. 
        - Да, кстати, - произнёс Стэн. - А где подевался Волчек? 
        Иштван мигом нахмурился: 
        - На своём корабле. Обещал вернуться с последней шлюпкой, но сегодня он явно не в духе. Да и вообще... - Капитан прокашлялся. - Хотя к чему теперь эти разговоры. 
        Стэн покачал головой: 
        - Как раз наоборот. Теперь мы можем откровенно поговорить. 
        - О Волчеке? 
        - О нём. 
        - Когда уже нельзя его заменить, - не спросил, а констатировал Иштван. 
        - Вот именно, - кивнул Стэн. - Я вижу, ваши люди уже заканчивают. Вы хотите отправиться с ними? 
        - Как будет угодно вашей светлости, - уклончиво ответил капитан. 
        - В таком случае, я предпочёл бы, чтоб вы остались. 
        - Хорошо. 
        Наконец был погружен последний бочонок с пресной водой, шлюпки отчалили от берега и поплыли к кораблям. Между тем, прослышав о присутствии князя, несколько офицеров с 'Князя Всевлада' и 'Святой Илоны', околачивавшихся в порту, явились к главному причалу. Стэн вежливо посоветовал им не терять времени даром и отправляться в замок. Сообразив, что князь хочет переговорить с Иштваном с глазу на глаз, офицеры и прочие присутствующие поспешно ретировались. Стэн и капитан 'Святой Илоны' остались у причала одни. Двое стражников и оруженосец, сопровождавшие Стэна в прогулке, стояли поодаль и недвусмысленно намекали любопытным зевакам, что его светлость занят, и предлагали не задерживаться, а идти по своим делам. 
        Прислонившись к деревянной свае, Стэн устремил задумчивый взгляд мимо кораблей к горизонту, за которым только что скрылось солнце. 
        - Как бы мне хотелось отправиться вместе с вами, капитан, - произнёс он с нотками грусти в голосе. - Будь мой отец жив, я бы так и поступил. 
        Иштван тяжело вздохнул - покойный князь Всевлад был его другом и покровителем. 
        - Но увы, вашего батюшки, светлая ему память, больше нет с нами, и ваше место, государь, здесь. 
        Стэн согласно кивнул: 
        - Да, это мой долг, и я не собираюсь уклоняться от своих обязанностей правителя. Поэтому с вами отправится Слободан Волчек. 
        Иштван удивлённо приподнял левую бровь, однако промолчал. 
        - Насколько я понимаю, - продолжал Стэн после короткой паузы, - все ваши возражения против Слободана сводятся к тому, что он слишком молод и ещё неопытен. 
        - Ну... В общем, да. А кроме того, ему порой не хватает выдержки. Он чересчур импульсивен и не всегда хорошо ладит с людьми. 
        - Опять же, это по молодости. 
        - Гм. Пожалуй, вы правы, - вынужден был согласиться Иштван. - Я не отрицаю, что Волчек отличный моряк. Лет через пять, возможно, он станет одним из лучших в нашей профессии - или, даже, лучшим из лучших. А пока... Я был бы рад видеть его среди своих офицеров, например, в качестве старшего помощника - но отнюдь не капитана корабля. 
        - Слободан уже три года командует кораблём, - заметил Стэн. - И ни какой-нибудь посудиной, а двухмачтовым бригом. Не станете же вы утверждать, что он плохо справляется? 
        Иштван повернул голову и вслед за Стэном посмотрел на 'Одинокую звезду' - судно, владельцем которого был девятнадцатилетний Слободан Волчек. Три года назад, когда умер его отец, юный Слободан, который почти всю сознательную жизнь провёл в море, не стал нанимать опытного шкипера, а сам занял место отца на капитанском мостике. Он согласился передать командование своим кораблём в чужие руки, лишь когда Стэн предложил ему пост капитана 'Князя Всевлада'. 
        - Нет, газда Стэнислав, - наконец ответил Иштван. - Я не стану утверждать, что Волчек плохо справляется. Как шкипер, он уже сейчас очень хорош, к тому же чертовски везучий. Но для такого длительного плавания, в которое мы отправляемся, только лишь мастерства и везения недостаточно. Нужен также большой жизненный опыт, умение обращаться с людьми. 
        Стэн хмыкнул: 
        - Боюсь, вы недооцениваете Слободана. Разве у вас есть какие-нибудь претензии к тому, как он набрал себе экипаж? 
        Иштван немного помедлил с ответом. 
        - Вообще-то нет, - нехотя признал он. - Надо сказать, что в этом отношении Волчек меня приятно удивил. У него дисциплинированная команда, толковые, знающие своё дело офицеры... 
        - Вы поменялись бы с ним экипажами? - немедленно перешёл в наступление Стэн. 
        - Ну, пожалуй... - Иштван замялся. 
        - Так да или нет? 
        - Да, поменялся бы. Конечно, я бы сделал кое-какие перестановки, но костяк оставил бы в неприкосновенности. 
        - Значит, всё дело в молодости Слободана, - подытожил Стэн. - Между прочим, в наших с ним судьбах много общего. Меня с детства учили править, его - водить корабли. Я стал князем в шестнадцать лет; он в таком же возрасте - капитаном. Неужели в свои девятнадцать я был дрянным правителем? 
        - Что вы, газда Стэнислав! - запротестовал Иштван, поражённый таким, на его взгляд совершенно неуместным сравнением. - У вас случай особый. 
        - И чем же он особый? Тем, что я сын святой Илоны? Или что я колдун? 
"""

    t2 = r"""
There are a few ways to escape data in different contexts.

<b>In SQL:</b>

• Use the backslash character (\) to escape special characters, such as single quotes (&#x27;), double quotes (&quot;), and backslashes (\). For example:

<pre><code class = "language-sql">INSERT INTO table_name (column_name) VALUES (&#x27;This is a &#x27;&#x27;test&#x27;&#x27;.&#x27;);
</code></pre>
• Use the <code>ESCAPE</code> clause to specify a different character to use for escaping. For example:

<pre><code class = "language-sql">INSERT INTO table_name (column_name) VALUES E&#x27;This is a &#x27;&#x27;test&#x27;&#x27;.&#x27; ESCAPE &#x27;\&#x27;&#x27;;
</code></pre>
<b>In JSON:</b>

• Use the backslash character (\) to escape special characters, such as double quotes (&quot;), backslashes (\), and forward slashes (/). For example:

<pre><code class = "language-json">{
  &quot;name&quot;: &quot;John Doe&quot;,
  &quot;address&quot;: &quot;123 Main Street&quot;,
  &quot;city&quot;: &quot;Anytown, USA&quot;,
  &quot;phone&quot;: &quot;555-123-4567&quot;
}
</code></pre>
• Use the <code>\u</code> escape sequence to represent Unicode characters. For example:

<pre><code class = "language-json">{
  &quot;name&quot;: &quot;John Doe&quot;,
  &quot;address&quot;: &quot;123 Main Street&quot;,
  &quot;city&quot;: &quot;Anytown, USA&quot;,
  &quot;phone&quot;: &quot;555-123-4567&quot;,
  &quot;favorite_emoji&quot;: &quot;\u263a&quot;
}
</code></pre>
<b>In HTML:</b>

• Use the <code>&amp;</code> character followed by the name of the HTML entity to escape special characters, such as less than (&lt;), greater than (&gt;), and ampersand (&amp;). For example:

<pre><code class = "language-html">&lt;p&gt;This is a &amp;lt;strong&amp;gt;test&amp;lt;/strong&amp;gt;.&lt;/p&gt;
</code></pre>
• Use the <code>&amp;#</code> character followed by the decimal or hexadecimal code of the Unicode character to escape Unicode characters. For example:

<pre><code class = "language-html">&lt;p&gt;This is a &amp;#x263a;.&lt;/p&gt;
</code></pre>
<b>In JavaScript:</b>

• Use the backslash character (\) to escape special characters, such as single quotes (&#x27;), double quotes (&quot;), and backslashes (\). For example:

<pre><code class = "language-javascript">var name = &#x27;John Doe&#x27;;
var address = &quot;123 Main Street&quot;;
var city = &#x27;Anytown, USA&#x27;;
var phone = &#x27;555-123-4567&#x27;;
</code></pre>
• Use the <code>\u</code> escape sequence to represent Unicode characters. For example:

<pre><code class = "language-javascript">var favorite_emoji = &#x27;\u263a&#x27;;
</code></pre>
<b>In Python:</b>

• Use the backslash character (\) to escape special characters, such as single quotes (&#x27;), double quotes (&quot;), and backslashes (\). For example:

<pre><code class = "language-python">name = &#x27;John Doe&#x27;
address = &quot;123 Main Street&quot;
city = &#x27;Anytown, USA&#x27;
phone = &#x27;555-123-4567&#x27;
</code></pre>
• Use the <code>\u</code> escape sequence to represent Unicode characters. For example:

<pre><code class = "language-python">favorite_emoji = &#x27;\u263a&#x27;
</code></pre>
<b>In C++:</b>

• Use the backslash character (\) to escape special characters, such as single quotes (&#x27;), double quotes (&quot;), and backslashes (\). For example:

<pre><code class = "language-c++">string name = &quot;John Doe&quot;;
string address = &quot;123 Main Street&quot;;
string city = &quot;Anytown, USA&quot;;
string phone = &quot;555-123-4567&quot;;
</code></pre>
• Use the <code>\u</code> escape sequence to represent Unicode characters. For example:

<pre><code class = "language-c++">string favorite_emoji = &quot;\u263a&quot;;
</code></pre>
<b>In Java:</b>

• Use the backslash character (\) to escape special characters, such as single quotes (&#x27;), double quotes (&quot;), and backslashes (\). For example:

<pre><code class = "language-java">String name = &quot;John Doe&quot;;
String address = &quot;123 Main Street&quot;;
String city = &quot;Anytown, USA&quot;;
String phone = &quot;555-123-4567&quot;;
</code></pre>
• Use the <code>\u</code> escape sequence to represent Unicode characters. For example:

<pre><code class = "language-java">String favorite_emoji = &quot;\u263a&quot;;
</code></pre>
<b>In PHP:</b>

• Use the backslash character (\) to escape special characters, such as single quotes (&#x27;), double quotes (&quot;), and backslashes (\). For example:

<pre><code class = "language-php">$name = &#x27;John Doe&#x27;;
$address = &quot;123 Main Street&quot;;
$city = &#x27;Anytown, USA&#x27;;
$phone = &#x27;555-123-4567&#x27;;
</code></pre>
• Use the <code>\u</code> escape sequence to represent Unicode characters. For example:

<pre><code class = "language-php">$favorite_emoji = &#x27;\u263a&#x27;;
</code></pre>
    """


    r = split_html(t2)
    for x in r:
        print(len(x))

    # print(mime_from_buffer(open('1.pdf', 'rb').read()))