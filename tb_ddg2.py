#!/usr/bin/env python3
# pip install -U duckduckgo_search[lxml]
# pip install pyTelegramBotAPI


import glob
import time
from duckduckgo_search import DDGS
import telebot

import cfg
# import my_md
import utils


# Объекты для доступа к чату {id:DDG object}
CHATS_OBJ = {}


def chat_new_connection():
    '''Connect with proxy and return object'''
    return DDGS(timeout=120)


def chat(query: str, chat_id: str, model: str = 'gpt-4o-mini') -> str:
    '''model = 'claude-3-haiku' | 'gpt-3.5' | 'llama-3-70b' | 'mixtral-8x7b' | 'gpt-4o-mini'
    '''

    if chat_id not in CHATS_OBJ:
        CHATS_OBJ[chat_id] = chat_new_connection()


    try:
        resp = CHATS_OBJ[chat_id].chat(query, model)
        return resp
    except Exception as error:
        print(f'my_ddg:chat: {error}')
        time.sleep(2)
        try:
            CHATS_OBJ[chat_id] = chat_new_connection()
            resp = CHATS_OBJ[chat_id].chat(query, model)
            return resp
        except Exception as error:
            print(f'my_ddg:chat: {error}')
            return ''


# Инициализация бота Telegram
bot = telebot.TeleBot(cfg.token)


# Обработчик команды /start
@bot.message_handler(commands=['start'])
def send_welcome(message):

    # for f in glob.glob('C:/Users/user/Downloads/*.txt'):
    #     with open(f, 'r', encoding='utf-8') as file:
    #         answer = file.read()
    #         answer = utils.bot_markdown_to_html(answer)
    #         answer = utils.split_html(answer, 3800)
    #         for chunk in answer:
    #             try:
    #                 bot.reply_to(message, chunk, parse_mode='HTML')
    #             except Exception as error:
    #                 bot.reply_to(message, str(error))
    #                 bot.reply_to(message, chunk)

    t = '''



'''

    answer = utils.bot_markdown_to_html(t)
    bot.reply_to(message, answer, parse_mode='HTML')


# Обработчик текстовых сообщений
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    query = message.text
    chat_id = str(message.chat.id)
    response = chat(query, chat_id)
    if response:
        answer = utils.bot_markdown_to_html(response)
        # bot.reply_to(message, answer)


# Запуск бота
bot.polling()
