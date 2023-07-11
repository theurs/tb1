#!/usr/bin/env python3


import asyncio
import json
import re
import sys
import threading
from pprint import pprint

#from EdgeGPT import Chatbot, ConversationStyle
from EdgeGPT.EdgeGPT import Chatbot, ConversationStyle
from BingImageCreator import ImageGen


lock_gen_img = threading.Lock()


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
    pattern = r'\[\^\d{1,2}\^]'
    cleaned_text = re.sub(pattern, '', text)
    return cleaned_text.replace(' .', '.')
    links_raw = r['item']['messages'][1]['adaptiveCards'][0]['body'][0]['text']
    

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


def ai(prompt: str, style: int = 3) -> str:
    """сырой запрос к бингу"""
    print('bing', len(prompt))
    return asyncio.run(main(prompt, style))


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
    # prompt = 'anime резонанс душ'
    # print(gen_imgs(prompt))

    print(ai('Официальный сайт iVentoy'))
    sys.exit()

    """Usage ./bingai.py 'list 10 japanese dishes"""

    t = sys.argv[1]

    print(ai(t))
