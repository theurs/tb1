#!/usr/bin/env python3


import traceback

import telebot
import cfg


bot = telebot.TeleBot(cfg.token, skip_pending=True)


D = {
    1: 'Hi',
}

@bot.message_handler(commands=['start'])
def command_code(message: telebot.types.Message):
    bot.reply_to(message, '''hi''', parse_mode='HTML', disable_web_page_preview=True)


if __name__ == '__main__':


    bot.polling()
