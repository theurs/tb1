import telebot

import cfg


bot = telebot.TeleBot(cfg.token)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    t = '10x, если x ≤4 x - 2, если x &gt; 4'
    bot.reply_to(message, t, parse_mode='HTML')


# Запускаем бота
bot.infinity_polling()
