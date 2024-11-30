#!/usr/bin/env python3
# pip install -U duckduckgo_search[lxml]
# pip install pyTelegramBotAPI


import time
from duckduckgo_search import DDGS
import telebot

import my_md

import cfg


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
Библиотека `markdown2` не доступна в текущем контексте. Я могу только рассказать, как её использовать, если бы она была установлена.

**Установка:**

В обычной среде Python вы бы установили `markdown2` с помощью pip:

```bash
pip install markdown2
```

**Использование:**

Основной способ конвертации Markdown в HTML с помощью `markdown2` очень прост:

```python
import markdown2

markdown_text = """
# Заголовок 1

* Пункт списка 1
* Пункт списка 2

**Жирный текст**

[Ссылка](https://www.example.com)
"""

html_text = markdown2.markdown(markdown_text)
print(html_text)
```

**Дополнительные возможности:**

`markdown2` предоставляет ряд дополнительных возможностей, которые можно настроить с помощью аргументов функции `markdown()`:

*   **`extras`:**  Список дополнительных расширений. Например,  `extras=["tables", "fenced-code-blocks", "footnotes"]`. Полный  список  доступных  расширений  можно  найти  в  документации  `markdown2`.
*   **`safe_mode`:**  Включает  безопасный  режим,  который  отключает  обработку  HTML  тегов  внутри  Markdown. Полезно  для  предотвращения  XSS-атак.

**Пример с расширениями:**

```python
import markdown2

markdown_text = """
| Заголовок 1 | Заголовок 2 |
|---|---|
| Ячейка 1 | Ячейка 2 |
"""

html_text = markdown2.markdown(markdown_text, extras=["tables"])
print(html_text)
```

**В текущем контексте:**

Вам придется использовать  доступные  инструменты (`html`, `re`) для обработки Markdown. Рекомендую  сосредоточиться на  постепенном  улучшении  имеющейся  функции,  добавляя  поддержку  необходимых  элементов  по  мере  надобности. Если  позже  появится  доступ  к  `markdown2`  или  другим  библиотекам,  вы  сможете  их  использовать.
'''
    print(len(answer))
    answer = my_md.md2mdv2(answer)
    print(len(answer))
    print(answer)
    bot.reply_to(message, answer, parse_mode='MarkdownV2')


# Обработчик текстовых сообщений
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    query = message.text
    chat_id = str(message.chat.id)
    response = chat(query, chat_id)
    if response:
        answer = my_md.md2mdv2(response)
        bot.reply_to(message, answer, parse_mode='MarkdownV2')


# Запуск бота
bot.polling()
