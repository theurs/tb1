#!/usr/bin/env python3


import traceback

import telebot
import cfg


bot = telebot.TeleBot(cfg.token, skip_pending=True)


D = {
    1: 'Hi',
}

@bot.message_handler(commands=['cmd'])
def command_code(message: telebot.types.Message):
    cmd = message.text[4:]
    if cmd:
        try:
            cmp = compile(cmd.strip(), 'test', 'exec')
            exec(cmp)
            print(D)
        except Exception:
            error_traceback = traceback.format_exc()
            print(error_traceback)
    else:
        msg = 'Usage: /cmd <string to eval()>'
        bot.reply_to(message, msg)


if __name__ == '__main__':


    bot.polling()
