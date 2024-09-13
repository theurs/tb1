#!/usr/bin/env python3
# pip install -U duckduckgo_search[lxml]
# pip install pyTelegramBotAPI


import time
import functools
import threading
from duckduckgo_search import DDGS
import telebot

import cfg


# Объекты для доступа к чату {id:DDG object}
CHATS_OBJ = {}
# хранилище диалогов {id:list(mem)}
CHATS = {}
# блокировка чатов что бы не испортить историю
# {id:lock}
LOCKS = {}


def async_run(func):
    '''Декоратор для запуска функции в отдельном потоке, асинхронно'''
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        thread = threading.Thread(target=func, args=args, kwargs=kwargs)
        thread.start()
    return wrapper


def chat_new_connection():
    '''Connect with proxy and return object'''
    return DDGS(timeout=120)


def chat(query: str, chat_id: str, model: str = 'gpt-4o-mini') -> str:
    '''model = 'claude-3-haiku' | 'gpt-3.5' | 'llama-3-70b' | 'mixtral-8x7b' | 'gpt-4o-mini'
    '''

    if chat_id not in CHATS_OBJ:
        CHATS_OBJ[chat_id] = chat_new_connection()

    if chat_id not in LOCKS:
        LOCKS[chat_id] = threading.Lock()

    with LOCKS[chat_id]:
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
    bot.reply_to(message, "Привет! Я простой чат-бот. Напиши мне что-нибудь.")


# Обработчик текстовых сообщений (асинхронный)
@bot.message_handler(func=lambda message: True)
@async_run
def echo_all(message):
    query = message.text
    chat_id = str(message.chat.id)
    response = chat(query, chat_id)
    bot.reply_to(message, response)


# Запуск бота
bot.polling()
