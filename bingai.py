#!/usr/bin/env python3


import json
import asyncio
from EdgeGPT import Chatbot, ConversationStyle
import sys


async def main(prompt):
    cookies = json.loads(open("cookies.json", encoding="utf-8").read())
    bot = await Chatbot.create(cookies=cookies)
    r = await bot.ask(prompt=prompt, conversation_style=ConversationStyle.creative)
    await bot.close()


    #print('\n\n\n')
    #print(r['item']['messages'])
    #print('\n\n\n')


    r = r['item']['messages'][1]['text']
    return r


if __name__ == "__main__":
    prompt = sys.argv[1]
    print(asyncio.run(main(prompt)))
