#!/usr/bin/env python3


import asyncio
import json
import os
import re
import sys
import threading

from EdgeGPT.EdgeGPT import Chatbot, ConversationStyle
from BingImageCreator import ImageGen

import cfg


DIALOGS = {}
CHAT_LOCKS = {}

lock_gen_img = threading.Lock()


def reset_bing_chat(chat_id: str):
    try:
        chat('', chat_id, reset=True)
    except Exception as error2:
        my_log.log2(f'bingai.reset_bing_chat: {error2}')
        print(error2)


async def chat_async(query: str, dialog: str, style = 3, reset = False):
    """возвращает список, объект для поддержания диалога и ответ"""
    if reset:
        try:
            await DIALOGS[dialog].close()
        except KeyError:
            print(f'no such key in DIALOGS: {dialog}')
        try:
            del DIALOGS[dialog]
        except KeyError:
            print(f'no such key in DIALOGS: {dialog}')    
        return

    if style == 1:
        st = ConversationStyle.precise
    elif style == 2:
        st = ConversationStyle.balanced
    elif style == 3:
        st = ConversationStyle.creative

    if dialog not in DIALOGS:
        cookies = json.loads(open("cookies.json", encoding="utf-8").read())
        DIALOGS[dialog] = await Chatbot.create(cookies=cookies)

    try:
        r = await DIALOGS[dialog].ask(prompt=query, conversation_style=st, simplify_response=True)
    except Exception as error:
        #sys.stdout, sys.stderr = orig_stdout, orig_stderr
        print(error)
        try:
            await DIALOGS[dialog].close()
        except KeyError:
            print(f'no such key in DIALOGS: {dialog}')
        try:
            del DIALOGS[dialog]
        except KeyError:
            print(f'no such key in DIALOGS: {dialog}')
        return error
    text = r['text']
    suggestions = r['suggestions']
    messages_left = r['messages_left']
    messages_max = r['max_messages']

    sources_text = r['sources_text']

    urls = re.findall(r'\[(.*?)\]\((.*?)\)', sources_text)
    urls2 = []
    for _, url in urls:
        urls2.append(url.strip())

    def replace_links(match):
        index = int(match.group(1)) - 1
        if index < len(urls2):
            return urls2[index]
        else:
            return match.group(0)

    my_log.log2(text)
    text = re.sub(r'\^(\d{1,2})\^', replace_links, text)

    return {'text': text, 'suggestions': suggestions, 'messages_left': messages_left, 'messages_max': messages_max}


def chat(query: str, dialog: str, style: int = 3, reset: bool = False) -> str:
    """возвращает ответ"""
    if dialog in CHAT_LOCKS:
        lock = CHAT_LOCKS[dialog]
    else:
        lock = threading.Lock()
        CHAT_LOCKS[dialog] = lock
    with lock:
        result = asyncio.run(chat_async(query, dialog, style, reset))
    return result


async def main_stream(prompt1: str, style: int = 3) -> str:
    """
    Выполняет запрос к бингу.
    style: 1 - precise, 2 - balanced, 3 - creative
    """

    if style == 1:
        st = ConversationStyle.precise
    elif style == 2:
        st = ConversationStyle.balanced
    elif style == 3:
        st = ConversationStyle.creative

    cookies = json.loads(open("cookies.json", encoding="utf-8").read())
    
    bot = await Chatbot.create(cookies=cookies)
    #r = await bot.ask_stream(prompt=prompt1, conversation_style=st, simplify_response=True)
    wrote = 0
    async for final, response in bot.ask_stream(prompt=prompt1, conversation_style=st, search_result=False, locale='ru'):
        if not final:
            if response[wrote:].startswith('```json'):
                wrote = len(response)
                continue
        if not final:
            # print(response[wrote:], end='')
            yield response[wrote:]
        wrote = len(response)

    await bot.close()


async def main(prompt1: str, style: int = 3) -> str:
    """
    Выполняет запрос к бингу.
    style: 1 - precise, 2 - balanced, 3 - creative
    """

    if style == 1:
        st = ConversationStyle.precise
    elif style == 2:
        st = ConversationStyle.balanced
    elif style == 3:
        st = ConversationStyle.creative

    cookies = json.loads(open("cookies.json", encoding="utf-8").read())
    
    try:
        bot = await Chatbot.create(cookies=cookies)
        r = await bot.ask(prompt=prompt1, conversation_style=st, simplify_response=True)
    except Exception as error:
        #sys.stdout, sys.stderr = orig_stdout, orig_stderr
        print(error)
        return ''
    await bot.close()

    text = r['text']
    sources_text = r['sources_text']

    urls = re.findall(r'\[(.*?)\]\((.*?)\)', sources_text)
    urls2 = []
    for _, url in urls:
        urls2.append(url.strip())

    def replace_links(match):
        index = int(match.group(1)) - 1
        if index < len(urls2):
            return urls2[index]
        else:
            return match.group(0)

    text = re.sub(r'\^(\d{1,2})\^', replace_links, text)

    return text


def ai(prompt: str, style: int = 3) -> str:
    """сырой запрос к бингу"""
    print('bing', len(prompt))
    return asyncio.run(main(prompt, style))


def ai_stream(prompt: str, timer: float = 1) -> str:
    """сырой запрос к бингу, ответ выдается каждые timer секунд по мере поступления"""
    print('bing', len(prompt))
    x = asyncio.run(main_stream(prompt, 3))
    print(x)


def gen_imgs(prompt: str):
    """генерирует список картинок по описанию с помощью бинга
    возвращает список ссылок на картинки или сообщение об ошибке"""
    with lock_gen_img:
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


if __name__ == "__main__":

    # text = open('text.txt', 'r', encoding='utf-8').read()
    # sources_text = open('sources_text.txt', 'r', encoding='utf-8').read()
    
    # urls = re.findall(r'\[(.*?)\]\((.*?)\)', sources_text)
    # urls2 = []
    # for i, url in urls:
    #     num = i.split('. ', maxsplit=1)[1].strip()
    #     urls2.append(url.strip())
    
    
    # def replace_links(match):
    #     index = int(match.group(1)) - 1
    #     if index < len(urls2):
    #         return urls2[index]
    #     else:
    #         return match.group(0)

    # new_text = re.sub(r'\^(\d{1,2})\^', replace_links, text)
    
    # print(new_text)

    #prompt = 'anime резонанс душ'
    #print(gen_imgs(prompt))

    # print(ai('с чего начать изучение питона'))
    #sys.exit()

    #sys.exit()

    """Usage ./bingai.py 'list 10 japanese dishes"""

    t = sys.argv[1]

    print(ai(t))
