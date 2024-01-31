#!/usr/bin/env python3


import telebot
import cfg
import utils


bot = telebot.TeleBot(cfg.token, skip_pending=True)


@bot.message_handler(commands=['start'])
def command_code(message: telebot.types.Message):
    t = r"""
Хорошо, продолжаю.

Вот еще один пример того, как можно использовать Bardapi:

```python
import bardapi

# Create a Bard client
client = bardapi.BardClient()

# Translate some text
response = client.translate_text(text="Hello, world!", target_language="fr")
print(response)
```

Этот код переведет текст "Hello, world!" на французский язык. Вы можете использовать Bardapi для перевода текстов на различные языки.

Вот еще один пример:

```python
import bardapi

# Create a Bard client
client = bardapi.BardClient()

# Answer a question
response = client.answer_question(question="What is the capital of France?")
print(response)
```

Этот код ответит на вопрос "Какой город является столицей Франции?". Вы можете использовать Bardapi, чтобы отвечать на различные вопросы, даже если они открытые, сложные или странные.

Это лишь некоторые из примеров того, что можно делать с Bardapi. Bardapi - это мощный инструмент, который можно использовать для различных целей. Если вы хотите узнать больше о Bardapi, вы можете посетить официальный сайт Bardapi.

Вот еще несколько вещей, которые можно сделать с Bardapi:

* Вы можете использовать Bardapi для создания своих собственных чат-ботов.
* Вы можете использовать Bardapi для создания своих собственных приложений для обработки естественного языка.
* Вы можете использовать Bardapi для автоматизации задач, которые требуют человеческих языковых навыков.

Bardapi - это еще молодой инструмент, но он имеет огромный потенциал. Я уверен, что в будущем мы увидим еще больше интересных и инновационных применений Bardapi.
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
