#!/usr/bin/env python3


import telebot

import cfg


bot = telebot.TeleBot(cfg.token, skip_pending=True)


@bot.message_handler(content_types = ['photo'])
def handle_photo(message: telebot.types.Message):
    """получает несколько фотографий и склеивает в 1"""
    pass


@bot.message_handler(func=lambda message: True)
def do_task(message):
    """функция обработчик сообщений работающая в отдельном потоке"""
    bot.reply_to(message, message.text)


def main():
    """
    Runs the main function, which sets default commands and starts polling the bot.
    """

    bot.polling()


if __name__ == '__main__':
    main()
