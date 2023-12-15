#!/usr/bin/env python3


import telebot

import my_gemini
import cfg


bot = telebot.TeleBot(cfg.token, skip_pending=True)


@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, 'Hi!')


@bot.message_handler(commands=['reset'])
def reset(message):
    my_gemini.reset(message.chat.id)
    bot.reply_to(message, 'Cleared!')


@bot.message_handler(func=lambda message: True)
def do_task(message):
    """функция обработчик сообщений работающая в отдельном потоке"""
    query = message.text
    user_id = message.chat.id
    text = my_gemini.chat(query, user_id)
    bot.reply_to(message, text, parse_mode='HTML')


def main():
    """
    Runs the main function, which sets default commands and starts polling the bot.
    """

    bot.polling()


if __name__ == '__main__':
    main()
