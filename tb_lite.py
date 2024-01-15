#!/usr/bin/env python3


import telebot
import cfg


bot = telebot.TeleBot(cfg.token, skip_pending=True)


@bot.message_handler(commands=['start'])
def command_code(message: telebot.types.Message):
    bot.send_message(message.chat.id, 'https://habr.com/ru/articles/786352/', parse_mode='HTML',
                     link_preview_options=telebot.types.LinkPreviewOptions(is_disabled=False, show_above_text=True))
    bot.send_message(message.chat.id, 'https://habr.com/ru/articles/786352/', parse_mode='HTML',
                     link_preview_options=telebot.types.LinkPreviewOptions(is_disabled=False, show_above_text=False))

if __name__ == '__main__':
    bot.polling()
