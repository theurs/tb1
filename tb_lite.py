#!/usr/bin/env python3


import telebot

import cfg
import my_p_hub


bot = telebot.TeleBot(cfg.token, skip_pending=True)


@bot.message_handler(func=lambda message: True)
def do_task(message):
    """функция обработчик сообщений работающая в отдельном потоке"""
    images = my_p_hub.get_screenshots(message.text)

    bot.send_media_group(message.chat.id, images)


def main():
    """
    Runs the main function, which sets default commands and starts polling the bot.
    """

    bot.polling()


if __name__ == '__main__':
    main()
