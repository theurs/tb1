#!/usr/bin/env python3
# pip install -U duckduckgo_search[lxml]
# pip install pyTelegramBotAPI


import glob
import time
from duckduckgo_search import DDGS
import telebot

import cfg
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


    # t1 = '''Конечно, давайте решим задачи по порядку.\n\n<b>1. Создать локального пользователя: UserTest</b>\n\n• <b>Решение:</b>\n    • Откройте &quot;Управление компьютером&quot; (можно найти через поиск в меню &quot;Пуск&quot;).\n    • Перейдите в &quot;Локальные пользователи и группы&quot; -&gt; &quot;Пользователи&quot;.\n    • Нажмите правой кнопкой мыши и выберите &quot;Новый пользователь...&quot;.\n    • В поле &quot;Имя пользователя&quot; введите <code>UserTest</code>.\n    • Задайте пароль (можно снять галочку &quot;Требовать смену пароля при следующем входе в систему&quot;).\n    • Нажмите &quot;Создать&quot;.\n• <b>Ответ:</b> Локальный пользователь <code>UserTest</code> создан.\n\n<b>2. Создать каталог*: FolderTest<b>\n\n• </b>Решение:<b>\n    • Откройте &quot;Проводник&quot;.\n    • Выберите место, где хотите создать каталог (например, диск <code>C:\\</code>).\n    • Нажмите правой кнопкой мыши и выберите &quot;Создать&quot; -&gt; &quot;Папку&quot;.\n    • Введите имя <code>FolderTest</code>.\n• </b>Ответ:<b> Каталог <code>FolderTest</code> создан.\n\n</b>3. В каталоге создать файл: Test.txt<b>\n\n• </b>Решение:<b>\n    • Откройте каталог <code>FolderTest</code>.\n    • Нажмите правой кнопкой мыши и выберите &quot;Создать&quot; -&gt; &quot;Текстовый документ&quot;.\n    • Введите имя <code>Test.txt</code>.\n• </b>Ответ:<b> Файл <code>Test.txt</code> создан в каталоге <code>FolderTest</code>.\n\n</b>4. Запретить доступ созданного пользователя к указанному каталогу, но разрешить доступ к файлу<b>\n\n• </b>Решение:<b>\n    • Нажмите правой кнопкой мыши на каталоге <code>FolderTest</code> и выберите &quot;Свойства&quot;.\n    • Перейдите на вкладку &quot;Безопасность&quot;.\n    • Нажмите &quot;Изменить...&quot;.\n    • Нажмите &quot;Добавить...&quot;.\n    • Введите имя пользователя <code>UserTest</code> и нажмите &quot;Проверить имена&quot;.\n    • Выберите пользователя <code>UserTest</code> и нажмите &quot;ОК&quot;.\n    • В списке разрешений для <code>UserTest</code> поставьте галочку &quot;Запретить&quot; напротив &quot;Полный доступ&quot;.\n    • Нажмите &quot;Применить&quot;.\n    • Теперь нажмите правой кнопкой мыши на файле <code>Test.txt</code> и выберите &quot;Свойства&quot;.\n    • Перейдите на вкладку &quot;Безопасность&quot;.\n    • Нажмите &quot;Изменить...&quot;.\n    • Нажмите &quot;Добавить...&quot;.\n    • Введите имя пользователя <code>UserTest</code> и нажмите &quot;Проверить имена&quot;.\n    • Выберите пользователя <code>UserTest</code> и нажмите &quot;ОК&quot;.\n    • В списке разрешений для <code>UserTest</code> поставьте галочку &quot;Разрешить&quot; напротив &quot;Чтение&quot; (или других необходимых разрешений).\n    • Нажмите &quot;Применить&quot; и &quot;ОК&quot;.\n• </b>Ответ:<b> Доступ пользователя <code>UserTest</code> к каталогу <code>FolderTest</code> запрещен, но доступ к файлу <code>Test.txt</code> разрешен.\n\n</b>5. Настроить регистрацию (аудит) событий «Аудит доступа к объектам» (отказ)<b>\n\n• </b>Решение:<b>\n    • Откройте &quot;Редактор локальной групповой политики&quot; (<code>gpedit.msc</code>).\n    • Перейдите в &quot;Конфигурация компьютера&quot; -&gt; &quot;Конфигурация Windows&quot; -&gt; &quot;Параметры безопасности&quot; -&gt; &quot;Локальные политики&quot; -&gt; &quot;Политика аудита&quot;.\n    • Найдите &quot;Аудит доступа к объектам&quot;.\n    • Дважды щелкните по нему.\n    • Поставьте галочку &quot;Отказ&quot; и нажмите &quot;Применить&quot; и &quot;ОК&quot;.\n• </b>Ответ:<b> Аудит доступа к объектам (отказ) настроен.\n\n</b>6. Найти события неуспешного открытия каталога, отфильтровав неуспешные попытки по EventID 4656 в оснастке «Просмотр событий»<b>\n\n• </b>Решение:<b>\n    • Откройте &quot;Просмотр событий&quot; (можно найти через поиск в меню &quot;Пуск&quot;).\n</b>'''
    # t1 = utils.re.sub(r"<b>((?:(?!</b>).)*?)<b>", r"\1<b>", t1)
    # bot.reply_to(message, t1, parse_mode='HTML')

    for f in glob.glob('C:/Users/user/Downloads/*.txt'):
        with open(f, 'r', encoding='utf-8') as file:
            answer = file.read()
            answer = utils.bot_markdown_to_html(answer)
            with open('C:/Users/user/Downloads/111.dat', 'w', encoding='utf-8') as f:
                f.write(answer)
            answer2 = utils.split_html(answer, 3800)
            for chunk in answer2:
                try:
                    bot.reply_to(message, chunk, parse_mode='HTML')
                except Exception as error:
                    bot.reply_to(message, str(error))
                    bot.reply_to(message, chunk)
            time.sleep(2)

    for f in glob.glob('C:/Users/user/Downloads/*.log'):
        with open(f, 'r', encoding='utf-8') as file:
            answer = file.read() # уже html
            # answer = utils.bot_markdown_to_html(answer)
            with open('C:/Users/user/Downloads/111.dat', 'w', encoding='utf-8') as f:
                f.write(answer)
            answer2 = utils.split_html(answer, 3800)
            for chunk in answer2:
                try:
                    bot.reply_to(message, chunk, parse_mode='HTML')
                except Exception as error:
                    bot.reply_to(message, str(error))
                    bot.reply_to(message, chunk)
            time.sleep(2)


# Обработчик текстовых сообщений
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    query = message.text
    chat_id = str(message.chat.id)
    response = chat(query, chat_id)
    if response:
        answer = utils.bot_markdown_to_html(response)
        bot.reply_to(message, answer, parse_mode='HTML')


# Запуск бота
bot.polling()
