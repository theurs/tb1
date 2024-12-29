#!/usr/bin/env python3
# pip install -U duckduckgo_search[lxml]
# pip install pyTelegramBotAPI
# pip install json_repair Pillow pylatexenc pillow-heif prettytable regex


import time
import functools
import threading
from duckduckgo_search import DDGS
import telebot

import cfg
import utils


# Объекты для доступа к чату {id:DDG object}
CHATS_OBJ = {}
# хранилище диалогов {id:list(mem)}
CHATS = {}
# блокировка чатов что бы не испортить историю
# {id:lock}
LOCKS = {}


# {chat_id:lock}
SHOW_ACTION_LOCKS = {}

class ShowAction(threading.Thread):
    """A thread that can be stopped. Continuously sends a notification of activity to the chat.
    Telegram automatically extinguishes the notification after 5 seconds, so it must be repeated.

    To use in the code, you need to do something like this:
    with ShowAction(message, 'typing'):
        do something and while doing it the notification does not go out
    """
    def __init__(self, message, action):
        """_summary_

        Args:
            chat_id (_type_): id чата в котором будет отображаться уведомление
            action (_type_):  "typing", "upload_photo", "record_video", "upload_video", "record_audio", 
                              "upload_audio", "upload_document", "find_location", "record_video_note", "upload_video_note"
        """
        super().__init__()
        self.actions = [  "typing", "upload_photo", "record_video", "upload_video", "record_audio",
                         "upload_audio", "upload_document", "find_location", "record_video_note", "upload_video_note"]
        assert action in self.actions, f'Допустимые actions = {self.actions}'
        self.chat_id = message.chat.id
        self.full_chat_id = get_topic_id(message)
        self.thread_id = message.message_thread_id
        self.is_topic = True if message.is_topic_message else False
        self.action = action
        self.is_running = True
        self.timerseconds = 1
        self.started_time = time.time()

    def run(self):
        if self.full_chat_id not in SHOW_ACTION_LOCKS:
            SHOW_ACTION_LOCKS[self.full_chat_id] = threading.Lock()
        with SHOW_ACTION_LOCKS[self.full_chat_id]:
            while self.is_running:
                if time.time() - self.started_time > 60*5:
                    self.stop()
                    print(f'tb:show_action:stoped after 5min [{self.chat_id}] [{self.thread_id}] is topic: {self.is_topic} action: {self.action}')
                    return
                try:
                    if self.is_topic:
                        bot.send_chat_action(self.chat_id, self.action, message_thread_id = self.thread_id)
                    else:
                        bot.send_chat_action(self.chat_id, self.action)
                except Exception as error:
                    if 'A request to the Telegram API was unsuccessful. Error code: 429. Description: Too Many Requests' not in str(error):
                        if 'Forbidden: bot was blocked by the user' in str(error):
                            self.stop()
                            return
                        print(f'tb:show_action:run: {error}')
                n = 50
                while n > 0:
                    time.sleep(0.1)
                    n = n - self.timerseconds

    def stop(self):
        self.timerseconds = 50
        self.is_running = False
        try:
            bot.send_chat_action(self.chat_id, 'cancel', message_thread_id = self.thread_id)
        except Exception as error:
            print(f'tb:show_action: {error}')

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


def get_topic_id(message: telebot.types.Message) -> str:
    """
    Get the topic ID from a Telegram message.

    Parameters:
        message (telebot.types.Message): The Telegram message object.

    Returns:
        str: '[chat.id] [topic.id]'
    """

    chat_id = message.chat.id
    topic_id = 0

    if message.reply_to_message and message.reply_to_message.is_topic_message:
        topic_id = message.reply_to_message.message_thread_id
    elif message.is_topic_message:
        topic_id = message.message_thread_id

    return f'[{chat_id}] [{topic_id}]'


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
                if model == 'gpt-4o-mini':
                    return chat(query, chat_id, 'claude-3-haiku')
                elif model == 'claude-3-haiku':
                    return chat(query, chat_id, 'llama-3-70b')
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
    with ShowAction(message, 'typing'):
        response = chat(query, chat_id)
        html = utils.bot_markdown_to_html(response)
        chunks = utils.split_html(html, 3800)
        for chunk in chunks:
            bot.reply_to(message, chunk, parse_mode='HTML', disable_web_page_preview=True)


# Запуск бота
bot.infinity_polling(timeout=90, long_polling_timeout=90)