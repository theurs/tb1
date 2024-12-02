#!/usr/bin/env python3
# pip install -U duckduckgo_search[lxml]
# pip install pyTelegramBotAPI


import time
from duckduckgo_search import DDGS
import telebot

import cfg
import my_md
import utils


# Объекты для доступа к чату {id:DDG object}
CHATS_OBJ = {}


def chat_new_connection():
    '''Connect with proxy and return object'''
    return DDGS(timeout=120)


def chat(query: str, chat_id: str, model: str = 'gpt-4o-mini') -> str:
    '''model = 'claude-3-haiku' | 'gpt-3.5' | 'llama-3-70b' | 'mixtral-8x7b' | 'gpt-4o-mini'
    '''

    if chat_id not in CHATS_OBJ:
        CHATS_OBJ[chat_id] = chat_new_connection()


    try:
        resp = CHATS_OBJ[chat_id].chat(query, model)
        return resp
    except Exception as error:
        print(f'my_ddg:chat: {error}')
        time.sleep(2)
        try:
            CHATS_OBJ[chat_id] = chat_new_connection()
            resp = CHATS_OBJ[chat_id].chat(query, model)
            return resp
        except Exception as error:
            print(f'my_ddg:chat: {error}')
            return ''


# Инициализация бота Telegram
bot = telebot.TeleBot(cfg.token)


# Обработчик команды /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Привет! Я простой чат-бот. Напиши мне что-нибудь.")
    answer = '''
**IV. Types of Errors**

In hypothesis testing, there are two potential types of errors that can occur:

* **Type I Error (False Positive):**  This occurs when the null hypothesis is rejected when it is actually true. In other words, the researcher concludes there is an effect or difference when there really isn't one. The probability of making a Type I error is denoted by alpha (α), which is the significance level set for the test.
* **Type II Error (False Negative):** This occurs when the null hypothesis is not rejected when it is actually false. This means the researcher fails to detect a real effect or difference. The probability of making a Type II error is denoted by beta (β). The power of a test, denoted as (1-β), is the probability of correctly rejecting the null hypothesis when it is false—essentially, the probability of finding a real effect if one exists.

The relationship between α and β is important: decreasing α (making the test more stringent) increases β, and vice versa. The desired balance between these error rates depends on the context of the research and the consequences of each type of error.

**V. Choosing the Right Statistical Test**

Selecting the appropriate statistical test is crucial for valid hypothesis testing. The choice depends on several factors:

## Реализовать распознавание голосовых команд пользователя с помощью библиотеки Vosk и ресурса https://speechpad.ru/.

.  ## Для этого необходимо настроить библиотеку Vosk и подключиться к ресурсу https://speechpad.ru/. Затем необходимо создать функцию, которая будет принимать на вход аудиоданные и возвращать распознанный текст.
[hi](https://example.com/123(123))
[hi](https://example.com/123123)

**Шаг 3:**
. ### 135 выберите библиотеку Vosk

привет  я   медвед    ва

1. [a(x<sub>i</sub>) = j]: Это значит, что алгоритм определил, к какому кластеру (j) относится объект (x<sub>i</sub>).

W(j) = Σ<sub>j=1</sub><sup>k</sup> Σ<sub>i=1</sub><sup>n</sup> [d(c<sub>j</sub>, x<sub>i</sub>)]<sup>2</sup>Π[a(x<sub>i</sub>) = j] → min;

Ну __вот и наклонный__ текст.


```python
# Обработчик текстовых сообщений
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    query = message.text
    chat_id = str(message.chat.id)
    response = chat(query, chat_id)
    if response:
        answer = utils.bot_markdown_to_html(response)
        # bot.reply_to(message, answer)
```


'''

    # answer = utils.bot_markdown_to_html(answer)
    # answer = my_md.split_md(answer)
    answer = my_md.md2html(answer)
    
    bot.reply_to(message, answer, parse_mode='HTML')
    # for chunk in utils.split_html(answer, 3800):
        # bot.reply_to(message, chunk, parse_mode='HTML')
    # for chunk in answer:
        # bot.reply_to(message, chunk, parse_mode='MarkdownV2')


# Обработчик текстовых сообщений
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    query = message.text
    chat_id = str(message.chat.id)
    response = chat(query, chat_id)
    if response:
        answer = utils.bot_markdown_to_html(response)
        # bot.reply_to(message, answer)


# Запуск бота
bot.polling()
