#!/usr/bin/env python3


import telebot
import cfg


bot = telebot.TeleBot(cfg.token, skip_pending=True)


def auth(message: telebot.types.Message) -> bool:
    return message.from_user.id in cfg.admins


# @bot.message_handler(commands=['start'], func=auth)
# def start(message):
#     bot.reply_to(message, '[OK]')


@bot.message_handler(func=auth)
def echo_all(message: telebot.types.Message) -> None:
    bot.reply_to(message, message.text.upper())


if __name__ == '__main__':


    bot.polling()
