#!/usr/bin/env python3


import chardet
import gpt_basic
import io
import magic
import os
import re
import requests
import sys
from langdetect import detect
from PyPDF2 import PyPDF2
from trafilatura import trafilatura
from urllib.parse import urlparse
from youtube_transcript_api import YouTubeTranscriptApi

import bingai
import gpt_basic


def get_text_from_youtube(url: str) -> str:
    """Вытаскивает текст из субтитров на ютубе

    Args:
        url (str): ссылка на ютуб видео

    Returns:
        str: первые субтитры из списка какие есть в видео
    """
    top_langs = ('ru', 'en', 'uk', 'es', 'pt', 'fr', 'ar', 'id', 'it', 'de', 'ja', 'ko', 'pl', 'th', 'tr', 'nl', 'hi', 'vi', 'sv', 'ro')

    video_id = re.search(r"(?:v=|\/)([a-zA-Z0-9_-]{11})(?:\?|&|\/|$)", url).group(1)

    t = YouTubeTranscriptApi.get_transcript(video_id, languages=top_langs)

    text = '\n'.join([x['text'] for x in t])

    return text or ''


def summ_text_worker(text: str, subj: str = 'text') -> str:
    """паралелльный воркер для summ_text
       subj == 'text' or 'pdf'  - обычный текст о котором ничего не известно
       subj == 'chat_log'       - журнал чата
       subj == 'youtube_video'  - субтитры к видео на ютубе
    """

    # если запустили из pool.map и передали параметры как список
    if type(text) == tuple:
        text, subj, cont = text[0], text[1], text[2]

    if subj == 'text' or subj == 'pdf':
        prompt = f"""Summarize the following, briefly answer in Russian with easy-to-read formatting:
-------------
{text}
-------------
BEGIN:
"""
    elif subj == 'chat_log':
        prompt = f"""Summarize the following telegram chat log, briefly answer in Russian with easy-to-read formatting:
-------------
{text}
-------------
BEGIN:
"""
    elif subj == 'youtube_video':
        prompt = f"""Summarize the following video subtitles extracted from youtube, briefly answer in Russian with easy-to-read formatting:
-------------
{text}
-------------
BEGIN:
"""

    if type(text) != str or len(text) < 1: return ''

    try:
        assert len(text) < 15000
        result = gpt_basic.ai(prompt, second = True)
    except Exception as error:
        try:
            result = bingai.ai(prompt, 1)
        except Exception as error2:
            print(error2)
            result = ''
        print(error)

    return result


def summ_text(text: str, subj: str = 'text') -> str:
    """сумморизирует текст с помощью бинга или гптчата, возвращает краткое содержание, только первые 30(60)т символов
    subj - смотрите summ_text_worker()
    """

    # уменьшаем текст до 60000 байт (не символов!)
    text2 = text
    if len(text2) > 60000:
        text2 = text2[:60000]
    text_bytes = text2.encode()

    while len(text_bytes) > 60000:
        text2 = text2[:-1]
        text_bytes = text2.encode()

    return summ_text_worker(text2, subj)


def summ_url(url:str) -> str:
    """скачивает веб страницу, просит гптчат или бинг сделать краткое изложение текста, возвращает текст
    если в ссылке ютуб то скачивает субтитры к видео вместо текста"""
    youtube = False
    pdf = False
    if '/youtu.be/' in url or 'youtube.com/' in url:
        text = get_text_from_youtube(url)
        youtube = True
    else:
        # Получаем содержимое страницы
                
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}

        response = requests.get(url, stream=True, headers=headers, timeout=10)
        content = b''
        # Ограничиваем размер
        for chunk in response.iter_content(chunk_size=1024):
            content += chunk
            if len(content) > 1 * 1024 * 1024: # 1 MB
                break

        if 'PDF document' in magic.from_buffer(content):
            pdf = True
            file_bytes = io.BytesIO(content)
            pdf_reader = PyPDF2.PdfReader(file_bytes)
            text = ''
            for page in pdf_reader.pages:
                text += page.extract_text()
        else:
            # Определяем кодировку текста
            encoding = chardet.detect(content)['encoding']
            # Декодируем содержимое страницы
            try:
                content = content.decode(encoding)
            except UnicodeDecodeError as error:
                print(error)
                content = response.content.decode('utf-8')

            newconfig = trafilatura.settings.use_config()
            newconfig.set("DEFAULT", "EXTRACTION_TIMEOUT", "0")
            text = trafilatura.extract(content, config=newconfig)
   
    #return text
    if youtube:
        r = summ_text(text, 'youtube_video')
    elif pdf:
        r = summ_text(text, 'pdf')
    else:
        r = summ_text(text, 'text')
    return r


def is_valid_url(url: str) -> bool:
    """Функция is_valid_url() принимает строку url и возвращает True, если эта строка является веб-ссылкой,
    и False в противном случае."""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False


if __name__ == "__main__":
    """Usage ./summarize.py '|URL|filename"""
    #r = summ_url('https://techxplore.com/news/2023-06-problems.html')
    #print(r)
    #sys.exit(0)
    
    t = sys.argv[1]
    
    if is_valid_url(t):
        print(summ_url(t))
    elif os.path.exists(t):
        print(summ_text(open(t).read()))
    else:
        print("""Usage ./summarize.py '|URL|filename""")
