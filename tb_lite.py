#!/usr/bin/env python3


from flask import Flask, request

import telebot
import cfg


bot = telebot.TeleBot(cfg.token, skip_pending=True)


@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, '[OK]')


if __name__ == '__main__':

    server = Flask(__name__)

    @server.route("/bot", methods=['POST'])
    def getMessage():
        bot.process_new_updates([telebot.types.Update.de_json(request.stream.read().decode("utf-8"))])
        return "!", 200
    @server.route("/")
    def webhook():
        bot.remove_webhook()
        bot.set_webhook(url="https://oracle2-bot1.dns.army/bot")
        return "?", 200
    server.run(host="0.0.0.0", port=32621)

    bot.polling()
