#!/usr/bin/env python3


import telebot
import cfg


bot = telebot.TeleBot(cfg.token, skip_pending=True)


@bot.message_handler(commands=['start'])
def command_code(message: telebot.types.Message):
    bot.send_message(message.chat.id, 'https://mail.ru', parse_mode='HTML',
                     disable_web_page_preview=True)
                    #  link_preview_options=telebot.types.LinkPreviewOptions(is_disabled=False))


if __name__ == '__main__':
    bot.polling()
