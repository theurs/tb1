#!/usr/bin/env python3


import telebot

import cfg


bot = telebot.TeleBot(cfg.token, skip_pending=True)


@bot.message_handler(content_types = ['photo'])
def handle_photo(message: telebot.types.Message):
    """получает несколько фотографий и склеивает в 1"""
    pass


@bot.message_handler(func=lambda message: True)
def do_task(message):
    """функция обработчик сообщений работающая в отдельном потоке"""
    text = """
текст

<pre><code class = "language-python">print(&#x27;Hello&#x27;) # Hello
</code></pre>
и тут текст

"""

    bot.reply_to(message, text, parse_mode='HTML')


def main():
    """
    Runs the main function, which sets default commands and starts polling the bot.
    """

    bot.polling()


if __name__ == '__main__':
    main()
