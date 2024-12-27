#!/usr/bin/env python3


import telebot
import cfg



bot = telebot.TeleBot(cfg.token, skip_pending=True)



@bot.message_handler(commands=['start'])
def command_code(message: telebot.types.Message):
    bot.reply_to(message, 'Hello')


if __name__ == '__main__':
    bot.polling()
