#!/usr/bin/env python3


import json
import asyncio
from EdgeGPT import Chatbot, ConversationStyle
#from EdgeGPT.EdgeGPT import Chatbot, ConversationStyle
import sys


async def main(prompt1: str) -> str:
    cookies = json.loads(open("cookies.json", encoding="utf-8").read())
    bot = await Chatbot.create(cookies=cookies)
    r = await bot.ask(prompt=prompt1, conversation_style=ConversationStyle.creative)

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


if __name__ == "__main__":
    """Usage ./bingai.py 'list 10 japanese dishes'"""
    prompt = sys.argv[1]
    print(asyncio.run(main(prompt)))
