#!/usr/bin/env python3


#import io
import json
import asyncio
from EdgeGPT import Chatbot, ConversationStyle
#from EdgeGPT.EdgeGPT import Chatbot, ConversationStyle
import sys
from BingImageCreator import ImageGen


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


if __name__ == "__main__":
    """Usage ./bingai.py 'list 10 japanese dishes'"""
    prompt = sys.argv[1]
    print(ai(prompt))
    
    
    #prompt = 'anime резонанс душ'
    #print(gen_imgs(prompt))
