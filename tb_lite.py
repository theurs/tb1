#!/usr/bin/env python3


import telebot
import cfg
import utils


bot = telebot.TeleBot(cfg.token, skip_pending=True)


@bot.message_handler(commands=['start'])
def command_code(message: telebot.types.Message):
    t = r"""
`Слайд 1:


"""

    # t = utils.bot_markdown_to_html(t)
    # for x in utils.split_html(t, 4000):
    #     print(x)
    #     bot.reply_to(message, x, parse_mode = 'HTML')

    # bot.reply_to(message, t, parse_mode = 'HTML')
    tt = utils.bot_markdown_to_html(t)
    print(len(tt))
    print(tt)
    for ttt in utils.split_html(tt):
      bot.reply_to(message, ttt, parse_mode = 'HTML')


if __name__ == '__main__':
    bot.polling()
