#!/usr/bin/env python3


#import io
import os
import json
import asyncio
from EdgeGPT import Chatbot, ConversationStyle
#from EdgeGPT.EdgeGPT import Chatbot, ConversationStyle
import sys
from BingImageCreator import ImageGen
import html2text
import requests
from urllib.parse import urlparse
import chardet
from youtube_transcript_api import YouTubeTranscriptApi
from urllib.parse import urlparse, parse_qs
import gpt_basic


async def main(prompt1: str) -> str:
    cookies = json.loads(open("cookies.json", encoding="utf-8").read())
    
    try:
        bot = await Chatbot.create(cookies=cookies)
        r = await bot.ask(prompt=prompt1, conversation_style=ConversationStyle.creative)
    except Exception as error:
        sys.stdout, sys.stderr = orig_stdout, orig_stderr
        print(error)

    text = r['item']['messages'][1]['text']
    links_raw = r['item']['messages'][1]['adaptiveCards'][0]['body'][0]['text']
    
    await bot.close()
    
    links = []
    for i in links_raw.split('\n'):
        s = i.strip()
        if len(s) > 2:
            if s[0] == '[' and s[1].isnumeric():
                link = s.split(']: ')[1].split(' "')[0]
                links.append(link)
            else:
                break
        else:
            break

    n = 1
    for i in links:
        fr = f'[^{n}^]'
        to = f'[ <{n}> ]({links[n - 1]})'
        text = text.replace(fr, to)
        n += 1
    return text


def ai(prompt: str) -> str:
    """сырой запрос к бингу"""
    return asyncio.run(main(prompt))


def gen_imgs(prompt: str):
    """генерирует список картинок по описанию с помощью бинга
    возвращает список ссылок на картинки или сообщение об ошибке"""
    with open("cookies.json") as f:
        c = json.load(f)
        for ck in c:
            if ck["name"] == "_U":
                auth = ck["value"]
                break

    if auth:
        image_gen = ImageGen(auth, quiet = True)

        try:
            images = image_gen.get_images(prompt)
        except Exception as error:
            if 'Your prompt has been blocked by Bing. Try to change any bad words and try again.' in str(error):
                return 'Бинг отказался это рисовать.'
            print(error)
            return str(error)

        return images

    return 'No auth provided'


def get_text_from_youtube(url: str) -> str:
    """Вытаскивает текст из субтитров на ютубе

    Args:
        url (str): ссылка на ютуб видео

    Returns:
        str: первые субтитры из списка какие есть в видео
    """
    top_langs = ('ru', 'en', 'uk', 'es', 'pt', 'fr', 'ar', 'id', 'it', 'de', 'ja', 'ko', 'pl', 'th', 'tr', 'nl', 'hi', 'vi', 'sv', 'ro')

    query = urlparse(url)
    
    if 'youtu' in query.netloc:
        if query.path == '/watch':
            video_id = parse_qs(query.query)['v'][0]
        else:
            video_id = query.path[1:]
    else:
        video_id = None
        raise ValueError(f'Bad youtube URL, no id found {url}')
    
    #video_id = parse_qs(query.query)['v'][0]

    t = YouTubeTranscriptApi.get_transcript(video_id, languages=top_langs)

    text = '\n'.join([x['text'] for x in t])

    return text or ''


def summ_url(url:str) -> str:
    """скачивает веб страницу в память и пропускает через фильтр html2text, возвращает текст"""
    if '/youtu.be/' in url or 'youtube.com/' in url:
        text = get_text_from_youtube(url)
    else:
        # Получаем содержимое страницы
        response = requests.get(url)
        content = response.content
        #content = response.content.decode('utf-8')
        # Определяем кодировку текста
        encoding = chardet.detect(content)['encoding']
        # Декодируем содержимое страницы
        content = content.decode(encoding)
        # Пропускаем содержимое через фильтр html2text
        h = html2text.HTML2Text()
        h.ignore_links = True
        h.ignore_images = True
        text = h.handle(content)
    
    # уменьшаем текст до 60000 байт (не символов!)
    text2 = text
    if len(text2) > 60000:
        text2 = text2[:60000]
    text_bytes = text2.encode()
    while len(text_bytes) > 60000:
        text2 = text2[:-1]
        text_bytes = text2.encode()

    prompt = 'Передай краткое содержание веб текста веб страницы так что бы мне не пришлось \
читать его полностью, используй для передачи мой родной язык - русский, \
начни свой ответ со слов Вот краткое содержание текста, \
закончи свой ответ словами Конец краткого содержания, ничего после этого не добавляй.'

#    request_size = len((text2+prompt).encode())
#    print(request_size)
#    if request_size < 4000:
#        result = gpt_basic.ai(prompt + '\n\n' + text2)
#    else:
#        result = ai(prompt + '\n\n' + text2)
    
    try:
        result = gpt_basic.ai(prompt + '\n\n' + text2)
    except Exception as error:
        result = ai(prompt + '\n\n' + text2)
        print(error)
    
    return result


def is_valid_url(url: str) -> bool:
    """Функция is_valid_url() принимает строку url и возвращает True, если эта строка является веб-ссылкой,
    и False в противном случае."""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False


if __name__ == "__main__":
    """Usage ./bingai.py 'list 10 japanese dishes'|URL|filename"""
    t = sys.argv[1]
    
    if is_valid_url(t):
        print(summ_url(t))
    elif os.path.exists(t):
        print(ai(open(t).read()))
    else:
        print(ai(t))
    
    
    #prompt = 'anime резонанс душ'
    #print(gen_imgs(prompt))
