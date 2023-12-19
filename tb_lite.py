#!/usr/bin/env python3


import telebot
import cfg


bot = telebot.TeleBot(cfg.token, skip_pending=True)


@bot.message_handler(commands=['start'])
def start(message):
    data = b' '*1024*1024*100
    bot.send_document(message.chat.id, data, caption='test.dat', visible_file_name='test.dat')
    

def main():
   
    #bot.log_out()
    #telebot.apihelper.API_URL = 'https://api.telegram.org/bot{0}/{1}'
    bot.polling()


if __name__ == '__main__':
    main()
