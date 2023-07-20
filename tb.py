#!/usr/bin/env python3

import io
import html
import os
import re
import tempfile
import datetime
import threading
import time

import openai
import PyPDF2
import telebot
from langdetect import detect_langs

import bingai
import cfg
import gpt_basic
import my_bard
import my_genimg
import my_dic
import my_log
import my_ocr
import my_google
import my_stt
import my_sum
import my_trans
import my_tts
import utils


# использовать прокси (пиратские сайты обычно лочат ваш ип, так что смотрите за этим)
#cfg.all_proxy = ''
#cfg.all_proxy = 'socks5://172.28.1.5:1080'
if cfg.all_proxy:
    os.environ['all_proxy'] = cfg.all_proxy


# устанавливаем рабочую папку = папке в которой скрипт лежит
os.chdir(os.path.abspath(os.path.dirname(__file__)))


bot = telebot.TeleBot(cfg.token, skip_pending=True)
_bot_name = bot.get_me().username
#telebot.apihelper.proxy = cfg.proxy_settings


# телеграм группа для отправки сгенерированных картинок
try:
    pics_group = cfg.pics_group
    pics_group_url = cfg.pics_group_url
except Exception as error123:
    print(error123)
    pics_group = 0

# до 40 одновременных потоков для чата с гпт и бингом
semaphore_talks = threading.Semaphore(40)

# папка для постоянных словарей, памяти бота
if not os.path.exists('db'):
    os.mkdir('db')


# в каких чатах включен/выключен режим общения с бингом 'off' | 'on'
BING_MODE = my_dic.PersistentDict('db/bing_mode.pkl')

# в каких чатах включен/выключен режим общения с бингом 'off' | 'on'
BARD_MODE = my_dic.PersistentDict('db/bard_mode.pkl')

# история диалогов для GPT chat
DIALOGS_DB = my_dic.PersistentDict('db/dialogs.pkl')
# в каких чатах выключены автопереводы. 0 - выключено, 1 - включено
BLOCKS = my_dic.PersistentDict('db/blocks.pkl')

# каким голосом озвучивать, мужским или женским
TTS_GENDER = my_dic.PersistentDict('db/tts_gender.pkl')

# в каких чатах какой промт
PROMPTS = my_dic.PersistentDict('db/prompts.pkl')

# запоминаем промпты для повторения рисования
IMAGE_PROMPTS = my_dic.PersistentDict('db/image_prompts.pkl')

# запоминаем диалоги в чатах для того что бы потом можно было сделать самморизацию,
# выдать краткое содержание
CHAT_LOGS = my_dic.PersistentDict('db/chat_logs.pkl')

# для запоминания ответов на команду /sum
SUM_CACHE = my_dic.PersistentDict('db/sum_cache.pkl')

# для запоминания всех сгенерированных изображений и запросов
# тут есть ключ 'total' в котором хранится счетчик записей
# записи состоят из counter_id: (prompt, images) где
# counter_id - порядковый номер для возможности перечесления последних записей в обратном порядке
# prompt - строка запроса, что хотел нарисовать юзер
# images - веб адреса картинок которые нарисовал ИИ по запросу
#          пока что в этом списке по 1 картинке, выводить по несколько сразу не получается
#          телеграм не дает прикреплять кнопки к нескольким картинкам
IMAGES_DB = my_dic.PersistentDict('db/images_db.pkl')

# в каких чатах какая команда дана, как обрабатывать последующий текст
# например после команды /image ожидаем описание картинки
# COMMAND_MODE[chat_id] = 'google'|'image'|...
COMMAND_MODE = {}

# в каких чатах какое у бота кодовое слово для обращения к боту
BOT_NAMES = my_dic.PersistentDict('db/names.pkl')
# имя бота по умолчанию, в нижнем регистре без пробелов и символов
BOT_NAME_DEFAULT = 'бот'

supported_langs_trans = [
        "af","am","ar","az","be","bg","bn","bs","ca","ceb","co","cs","cy","da","de",
        "el","en","eo","es","et","eu","fa","fi","fr","fy","ga","gd","gl","gu","ha",
        "haw","he","hi","hmn","hr","ht","hu","hy","id","ig","is","it","iw","ja","jw",
        "ka","kk","km","kn","ko","ku","ky","la","lb","lo","lt","lv","mg","mi","mk",
        "ml","mn","mr","ms","mt","my","ne","nl","no","ny","or","pa","pl","ps","pt",
        "ro","ru","rw","sd","si","sk","sl","sm","sn","so","sq","sr","st","su","sv",
        "sw","ta","te","tg","th","tl","tr","uk","ur","uz","vi","xh","yi","yo","zh",
        "zh-TW","zu"]
supported_langs_tts = [
        'af', 'am', 'ar', 'as', 'az', 'be', 'bg', 'bn', 'bs', 'ca', 'cs', 'cy', 'da',
        'de', 'el', 'en', 'eo', 'es', 'et', 'eu', 'fa', 'fi', 'fil', 'fr', 'ga', 'gl',
        'gu', 'he', 'hi', 'hr', 'ht', 'hu', 'hy', 'id', 'is', 'it', 'ja', 'jv', 'ka',
        'kk', 'km', 'kn', 'ko', 'ku', 'ky', 'la', 'lb', 'lo', 'lt', 'lv', 'mg', 'mi',
        'mk', 'ml', 'mn', 'mr', 'ms', 'mt', 'my', 'nb', 'ne', 'nl', 'nn', 'no', 'ny',
        'or', 'pa', 'pl', 'ps', 'pt', 'ro', 'ru', 'rw', 'sd', 'si', 'sk', 'sl', 'sm',
        'sn', 'so', 'sq', 'sr', 'st', 'su', 'sv', 'sw', 'ta', 'te', 'tg', 'th', 'tk',
        'tl', 'tr', 'tt', 'ug', 'uk', 'ur', 'uz', 'vi', 'xh', 'yi', 'yo', 'zh', 'zu']

MSG_CONFIG = """***Панель управления***

Тут можно:

- стереть память боту

- переключить чат с chatGPT на Microsoft Bing или Google Bard

- изменить голос

- выключить авто переводы иностранных текстов на канале и перевод голосовых сообщений в текст

Настройки стиля /style и история /mem ***относятся только к chatGPT***
У Барда и Бинга свои особенные правила, которые не могут быть изменены
"""

class ShowAction(threading.Thread):
    """Поток который можно остановить. Беспрерывно отправляет в чат уведомление об активности.
    Телеграм автоматически гасит уведомление через 5 секунд, по-этому его надо повторять.

    Использовать в коде надо как то так
    with ShowAction(chat_id, 'typing'):
        делаем что-нибудь и пока делаем уведомление не гаснет
    
    """
    def __init__(self, chat_id, action):
        """_summary_

        Args:
            chat_id (_type_): id чата в котором будет отображаться уведомление
            action (_type_):  "typing", "upload_photo", "record_video", "upload_video", "record_audio", 
                              "upload_audio", "upload_document", "find_location", "record_video_note", "upload_video_note"
        """
        super().__init__()
        self.actions = [  "typing", "upload_photo", "record_video", "upload_video", "record_audio",
                         "upload_audio", "upload_document", "find_location", "record_video_note", "upload_video_note"]
        assert action in self.actions, f'Допустимые actions = {self.actions}'
        self.chat_id = chat_id
        self.action = action
        self.is_running = True
        self.timerseconds = 1
        
    def run(self):
        while self.is_running:
            try:
                bot.send_chat_action(self.chat_id, self.action)
            except Exception as error:
                my_log.log2(str(error))
            n = 50
            while n > 0:
                time.sleep(0.1)
                n = n - self.timerseconds

    def stop(self):
        self.timerseconds = 50
        self.is_running = False
        bot.send_chat_action(self.chat_id, 'cancel')

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


def dialog_add_user_request(chat_id: int, text: str, engine: str = 'gpt') -> str:
    """добавляет в историю переписки с юзером его новый запрос и ответ от чатбота
    делает запрос и возвращает ответ

    Args:
        chat_id (int): номер чата или юзера, нужен для хранения истории переписки
        text (str): новый запрос от юзера
        engine (str, optional): 'gpt' или 'bing'. Defaults to 'gpt'.

    Returns:
        str: возвращает ответ который бот может показать, возможно '' или None
    """
    global DIALOGS_DB, PROMPTS

    # в каждом чате свой собственный промт
    if chat_id in PROMPTS:
        current_prompt = PROMPTS[chat_id]
    else:
        # по умолчанию формальный стиль
        PROMPTS[chat_id] = [{"role": "system", "content": utils.gpt_start_message1}]
        current_prompt =   [{"role": "system", "content": utils.gpt_start_message1}]

    # создаем новую историю диалогов с юзером из старой если есть
    # в истории диалогов не храним системный промпт
    if chat_id in DIALOGS_DB:
        new_messages = DIALOGS_DB[chat_id]
    else:
        new_messages = []


    # теперь ее надо почистить что бы влезла в запрос к GPT
    # просто удаляем все кроме max_hist_lines последних
    if len(new_messages) > cfg.max_hist_lines:
        new_messages = new_messages[cfg.max_hist_lines:]
    # удаляем первую запись в истории до тех пор пока общее количество токенов не станет меньше cfg.max_hist_bytes
    # удаляем по 2 сразу так как первая - промпт для бота
    while (utils.count_tokens(new_messages) > cfg.max_hist_bytes):
        new_messages = new_messages[2:]
    
    # добавляем в историю новый запрос и отправляем
    new_messages = new_messages + [{"role":    "user",
                                    "content": text}]

    if engine == 'gpt':
        # пытаемся получить ответ
        try:
            resp = gpt_basic.ai(prompt = text, messages = current_prompt + new_messages, chat_id=chat_id)
            if resp:
                new_messages = new_messages + [{"role":    "assistant",
                                                    "content": resp}]
            else:
                # не сохраняем диалог, нет ответа
                # если в последнем сообщении нет текста (глюк) то убираем его
                if new_messages[-1]['content'].strip() == '':
                    new_messages = new_messages[:-1]
                DIALOGS_DB[chat_id] = new_messages or []
                return 'GPT не ответил.'
        # бот не ответил или обиделся
        except AttributeError:
            # не сохраняем диалог, нет ответа
            return 'Не хочу говорить об этом. Или не могу.'
        # произошла ошибка переполнения ответа
        except openai.error.InvalidRequestError as error2:
            if """This model's maximum context length is""" in str(error2):
                # чистим историю, повторяем запрос
                p = '\n'.join(f'{i["role"]} - {i["content"]}\n' for i in new_messages) or 'Пусто'
                # сжимаем весь предыдущий разговор до cfg.max_hist_compressed символов
                r = gpt_basic.ai_compress(p, cfg.max_hist_compressed, 'dialog')
                new_messages = [{'role':'system','content':r}] + new_messages[-1:]
                # и на всякий случай еще
                while (utils.count_tokens(new_messages) > cfg.max_hist_compressed):
                    new_messages = new_messages[2:]

                try:
                    resp = gpt_basic.ai(prompt = text, messages = current_prompt + new_messages, chat_id=chat_id)
                except Exception as error3:
                    print(error3)
                    return 'GPT не ответил.'
                
                # добавляем в историю новый запрос и отправляем в GPT, если он не пустой, иначе удаляем запрос юзера из истории
                if resp:
                    new_messages = new_messages + [{"role":    "assistant",
                                                    "content": resp}]
                else:
                    return 'GPT не ответил.'
            else:
                print(error2)
                return 'GPT не ответил.'
    else:
        # для бинга
        hist = '\n'.join([f"{i['role']}: {i['content']}" for i in new_messages])
        hist_compressed = ''
        bing_prompt = hist_compressed + '\n\n' + 'Отвечай по-русски\n\n' + text

        msg_bing_no_answer = 'Бинг не ответил.'
        try:
            #my_log.log2(bing_prompt)
            resp = bingai.ai(bing_prompt, 1)
        except Exception as error2:
            print(error2)
            my_log.log2(error2)
            return msg_bing_no_answer
        if resp:
            new_messages = new_messages + [{"role":    "assistant",
                                            "content": resp}]
        else:
            # не сохраняем диалог, нет ответа
            return msg_bing_no_answer

    # сохраняем диалог, на данном этапе в истории разговора должны быть 2 последних записи несжатыми
    new_messages = new_messages[:-2]
    # если запрос юзера был длинным то в истории надо сохранить его коротко
    if len(text) > cfg.max_hist_mem:
        new_text = gpt_basic.ai_compress(text, cfg.max_hist_mem, 'user')
        # заменяем запрос пользователя на сокращенную версию
        new_messages += [{"role":    "user",
                             "content": new_text}]
    else:
        new_messages += [{"role":    "user",
                            "content": text}]
    # если ответ бота был длинным то в истории надо сохранить его коротко
    if len(resp) > cfg.max_hist_mem:
        new_resp = gpt_basic.ai_compress(resp, cfg.max_hist_mem, 'assistant')
        new_messages += [{"role":    "assistant",
                             "content": new_resp}]
    else:
        new_messages += [{"role":    "assistant",
                             "content": resp}]
    DIALOGS_DB[chat_id] = new_messages or []

    return resp


def get_keyboard(kbd: str, chat_id = None) -> telebot.types.InlineKeyboardMarkup:
    """создает и возвращает клавиатуру по текстовому описанию
    'chat' - клавиатура для чата с 3 кнопками Дальше, Забудь, Скрой
    'mem' - клавиатура для команды mem, с кнопками Забудь и Скрой
    'hide' - клавиатура с одной кнопкой Скрой
    """
    if kbd == 'chat':
        markup  = telebot.types.InlineKeyboardMarkup(row_width=5)
        button1 = telebot.types.InlineKeyboardButton("➡", callback_data='continue_gpt')
        button2 = telebot.types.InlineKeyboardButton("♻️", callback_data='forget_all')
        button3 = telebot.types.InlineKeyboardButton("🙈", callback_data='erase_answer')
        button4 = telebot.types.InlineKeyboardButton("📢", callback_data='tts')
        button5 = telebot.types.InlineKeyboardButton("🇷🇺", callback_data='translate_chat')
        markup.add(button1, button2, button3, button4, button5)
        return markup
    elif kbd == 'mem':
        markup  = telebot.types.InlineKeyboardMarkup()
        button1 = telebot.types.InlineKeyboardButton("Стереть историю", callback_data='clear_history')
        button2 = telebot.types.InlineKeyboardButton("Скрыть", callback_data='erase_answer')
        markup.add(button1, button2)
        return markup
    elif kbd == 'hide':
        markup  = telebot.types.InlineKeyboardMarkup()
        button1 = telebot.types.InlineKeyboardButton("Скрыть", callback_data='erase_answer')
        markup.add(button1)
        return markup
    elif kbd == 'command_mode':
        markup  = telebot.types.InlineKeyboardMarkup()
        button1 = telebot.types.InlineKeyboardButton("Отмена", callback_data='cancel_command')
        markup.add(button1)
        return markup
    elif kbd == 'translate':
        markup  = telebot.types.InlineKeyboardMarkup()
        button1 = telebot.types.InlineKeyboardButton("Скрыть", callback_data='erase_answer')
        button2 = telebot.types.InlineKeyboardButton("📢", callback_data='tts')
        button3 = telebot.types.InlineKeyboardButton("Перевод 🇷🇺", callback_data='translate')
        markup.add(button1, button2, button3)
        return markup
    elif kbd == 'hide_image':
        markup  = telebot.types.InlineKeyboardMarkup()
        button1 = telebot.types.InlineKeyboardButton("Скрыть", callback_data='erase_image')
        button2 = telebot.types.InlineKeyboardButton("Повторить", callback_data='repeat_image')
        markup.add(button1, button2)
        return markup
    elif kbd == 'start':
        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
        button1 = telebot.types.KeyboardButton('🎨Нарисуй')
        button2 = telebot.types.KeyboardButton('🌐Найди')
        button3 = telebot.types.KeyboardButton('📋Перескажи')
        button4 = telebot.types.KeyboardButton('🎧Озвучь')
        button5 = telebot.types.KeyboardButton('🈶Переведи')
        button6 = telebot.types.KeyboardButton('⚙️Настройки')
        markup.row(button1, button2, button3)
        markup.row(button4, button5, button6)
        return markup
    elif kbd == 'bing_chat':
        markup  = telebot.types.InlineKeyboardMarkup(row_width=5)
        button0 = telebot.types.InlineKeyboardButton("➡", callback_data='continue_gpt')
        button1 = telebot.types.InlineKeyboardButton('♻️', callback_data='restart_bing')
        button2 = telebot.types.InlineKeyboardButton("🙈", callback_data='erase_answer')
        button3 = telebot.types.InlineKeyboardButton("📢", callback_data='tts')
        button4 = telebot.types.InlineKeyboardButton("🇷🇺", callback_data='translate_chat')
        markup.add(button0, button1, button2, button3, button4)
        return markup
    elif kbd == 'bard_chat':
        markup  = telebot.types.InlineKeyboardMarkup(row_width=5)
        button0 = telebot.types.InlineKeyboardButton("➡", callback_data='continue_gpt')
        button1 = telebot.types.InlineKeyboardButton('♻️', callback_data='restart_bard')
        button2 = telebot.types.InlineKeyboardButton("🙈", callback_data='erase_answer')
        button3 = telebot.types.InlineKeyboardButton("📢", callback_data='tts')
        button4 = telebot.types.InlineKeyboardButton("🇷🇺", callback_data='translate_chat')
        markup.add(button0, button1, button2, button3, button4)
        return markup
    elif kbd == 'image_gallery':
        markup  = telebot.types.InlineKeyboardMarkup(row_width=4)
        button1 = telebot.types.InlineKeyboardButton("-1", callback_data='image_gallery_prev_prompt')
        button2 = telebot.types.InlineKeyboardButton("+1", callback_data='image_gallery_next_prompt')
        button3 = telebot.types.InlineKeyboardButton("-10", callback_data='image_gallery_prev_prompt10')
        button4 = telebot.types.InlineKeyboardButton("+10", callback_data='image_gallery_next_prompt10')
        button5 = telebot.types.InlineKeyboardButton("-100", callback_data='image_gallery_prev_prompt100')
        button6 = telebot.types.InlineKeyboardButton("+100", callback_data='image_gallery_next_prompt100')
        button7 = telebot.types.InlineKeyboardButton("X",  callback_data='erase_answer')
        if pics_group:
            button8 = telebot.types.InlineKeyboardButton("↗",  url = pics_group_url)
            markup.add(button1, button2, button3, button4, button5, button6, button7, button8)
        else:
            markup.add(button1, button2, button3, button4, button5, button6, button7)
        return markup
    elif kbd == 'config':
        global TTS_GENDER, BING_MODE, BARD_MODE, BLOCKS

        if chat_id and chat_id in TTS_GENDER:
            voice = f'tts_{TTS_GENDER[chat_id]}'
        else:
            voice = 'tts_female'

        voices = {'tts_female': 'Микрософт жен.',
                  'tts_male': 'Микрософт муж.',
                  'tts_google_female': 'Google',
                  'tts_silero_xenia': 'Силеро - xenia',
                  'tts_silero_aidar': 'Силеро - aidar'
                  }
        voice_title = voices[voice]

        # бард по умолчанию
        if chat_id not in BARD_MODE and chat_id not in BING_MODE:
            BARD_MODE[chat_id] = 'on'

        bing_mode = BING_MODE[chat_id] if chat_id in BING_MODE else 'off'
        bard_mode = BARD_MODE[chat_id] if chat_id in BARD_MODE else 'off'

        markup  = telebot.types.InlineKeyboardMarkup(row_width=1)

        if bard_mode == 'off' and bing_mode == 'off':
            button1 = telebot.types.InlineKeyboardButton('✅ChatGPT', callback_data='chatGPT_mode_disable')
        else:
            button1 = telebot.types.InlineKeyboardButton('☑️ChatGPT', callback_data='chatGPT_mode_enable')
        button2 = telebot.types.InlineKeyboardButton('❌Стереть', callback_data='chatGPT_reset')
        markup.row(button1, button2)

        if bard_mode == 'off':
            button1 = telebot.types.InlineKeyboardButton('☑️Bard AI', callback_data='bard_mode_enable')
        else:
            button1 = telebot.types.InlineKeyboardButton('✅Bard AI', callback_data='bard_mode_disable')

        button2 = telebot.types.InlineKeyboardButton('❌Стереть', callback_data='bardAI_reset')
        markup.row(button1, button2)

        if bing_mode == 'off':
            button1 = telebot.types.InlineKeyboardButton('☑️Bing AI', callback_data='bing_mode_enable')
        else:
            button1 = telebot.types.InlineKeyboardButton('✅Bing AI', callback_data='bing_mode_disable')

        button2 = telebot.types.InlineKeyboardButton('❌Стереть', callback_data='bingAI_reset')
        markup.row(button1, button2)

        button = telebot.types.InlineKeyboardButton(f'📢Голос: {voice_title}', callback_data=voice)
        markup.add(button)

        if chat_id not in BLOCKS:
            BLOCKS[chat_id] = 1

        if BLOCKS[chat_id] == 1:
            button = telebot.types.InlineKeyboardButton(f'✅Автопереводы', callback_data='autotranslate_disable')
        else:
            button = telebot.types.InlineKeyboardButton(f'☑️Автопереводы', callback_data='autotranslate_enable')
        markup.add(button)

        if cfg.pics_group_url:
            button_pics = telebot.types.InlineKeyboardButton("🖼️Галерея",  url = cfg.pics_group_url)
            markup.add(button_pics)

        button = telebot.types.InlineKeyboardButton('🔍История ChatGPT', callback_data='chatGPT_memory_debug')
        markup.add(button)

        button = telebot.types.InlineKeyboardButton('🙈Закрыть меню', callback_data='erase_answer')
        markup.add(button)

        return markup
    else:
        raise f"Неизвестная клавиатура '{kbd}'"


@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call: telebot.types.CallbackQuery):
    """Обработчик клавиатуры"""
    thread = threading.Thread(target=callback_inline_thread, args=(call,))
    thread.start()
def callback_inline_thread(call: telebot.types.CallbackQuery):
    """Обработчик клавиатуры"""
    
    with semaphore_talks:
        global IMAGE_PROMPTS
        message = call.message
        is_private = message.chat.type == 'private'
        is_reply = message.reply_to_message is not None and message.reply_to_message.from_user.id == bot.get_me().id
        chat_id = message.chat.id
        global DIALOGS_DB, TTS_GENDER, BING_MODE

        if call.data == 'image_gallery_prev_prompt':
            # переходим к предыдущему промпту в базе галереи
            cur = int(message.text.split()[0])
            cur -= 1
            thread = threading.Thread(target=show_gallery, args=(message, cur, True))
            thread.start()
        elif call.data == 'image_gallery_next_prompt':
            # переходим к следующему промпту в базе галереи
            cur = int(message.text.split()[0])
            cur += 1
            thread = threading.Thread(target=show_gallery, args=(message, cur, True))
            thread.start()
        elif call.data == 'image_gallery_prev_prompt10':
            # переходим к предыдущему (-10) промпту в базе галереи
            cur = int(message.text.split()[0])
            cur -= 10
            thread = threading.Thread(target=show_gallery, args=(message, cur, True))
            thread.start()
        elif call.data == 'image_gallery_next_prompt10':
            # переходим к следующему (+10) промпту в базе галереи
            cur = int(message.text.split()[0])
            cur += 10
            thread = threading.Thread(target=show_gallery, args=(message, cur, True))
            thread.start()
        elif call.data == 'image_gallery_prev_prompt100':
            # переходим к предыдущему (-100) промпту в базе галереи
            cur = int(message.text.split()[0])
            cur -= 100
            thread = threading.Thread(target=show_gallery, args=(message, cur, True))
            thread.start()
        elif call.data == 'image_gallery_next_prompt100':
            # переходим к следующему (+100) промпту в базе галереи
            cur = int(message.text.split()[0])
            cur += 100
            thread = threading.Thread(target=show_gallery, args=(message, cur, True))
            thread.start()
        elif call.data == 'clear_history':
            # обработка нажатия кнопки "Стереть историю"
            #bot.edit_message_reply_markup(message.chat.id, message.message_id)
            DIALOGS_DB[chat_id] = []
            bot.delete_message(message.chat.id, message.message_id)
        elif call.data == 'continue_gpt':
            # обработка нажатия кнопки "Продолжай GPT"
            echo_all(message, 'Продолжай')
            return
        elif call.data == 'forget_all':
            # обработка нажатия кнопки "Забудь всё"
            DIALOGS_DB[chat_id] = []
        elif call.data == 'cancel_command':
            # обработка нажатия кнопки "Отменить ввод команды"
            global COMMAND_MODE
            COMMAND_MODE[chat_id] = ''
            bot.delete_message(message.chat.id, message.message_id)
        elif call.data == 'erase_answer':
            # обработка нажатия кнопки "Стереть ответ"
            bot.delete_message(message.chat.id, message.message_id)
        elif call.data == 'tts':
            lang = my_trans.detect_lang(message.text) or 'ru'
            message.text = f'/tts {lang} {message.text}'
            tts(message)
        elif call.data == 'erase_image':
            # обработка нажатия кнопки "Стереть ответ"
            bot.delete_message(message.chat.id, message.message_id)
            # получаем номер сообщения с картинками из сообщения с ссылками на картинки который идет следом
            for i in message.text.split('\n')[0].split():
                bot.delete_message(message.chat.id, int(i))
        elif call.data == 'repeat_image':
            # получаем номер сообщения с картинками (первый из группы)
            for i in message.text.split('\n')[0].split():
                id = int(i)
                break
            p = IMAGE_PROMPTS[id]
            message.text = f'/image {p}'
            # рисуем еще картинки с тем же запросом
            image(message)
        elif call.data == 'translate':
            # реакция на клавиатуру для OCR кнопка перевести текст
            with ShowAction(chat_id, 'typing'):
                translated = my_trans.translate_text2(message.text)
            if translated and translated != message.text:
                bot.edit_message_text(chat_id=message.chat.id, message_id=message.message_id, text=translated, reply_markup=get_keyboard('translate'))
        elif call.data == 'translate_chat':
            # реакция на клавиатуру для Чата кнопка перевести текст
            translated = my_trans.translate_text2(message.text)
            if translated and translated != message.text:
                bot.edit_message_text(chat_id=message.chat.id, message_id=message.message_id, text=translated, reply_markup=get_keyboard('chat'))
        elif call.data == 'restart_bard':
            my_bard.reset_bard_chat(chat_id)
            msg = 'История диалога с бардом отчищена.'
            bot.send_message(chat_id, msg, reply_markup=get_keyboard('hide'))
            my_log.log_echo(message, msg)
        elif call.data == 'restart_bing':
            bingai.reset_bing_chat(chat_id)
            msg = 'История диалога с бингом отчищена.'
            bot.send_message(chat_id, msg, reply_markup=get_keyboard('hide'))
            my_log.log_echo(message, msg)
        elif call.data == 'tts_female':
            TTS_GENDER[chat_id] = 'male'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, text = MSG_CONFIG, reply_markup=get_keyboard('config', chat_id))
        elif call.data == 'tts_male':
            TTS_GENDER[chat_id] = 'google_female'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, text = MSG_CONFIG, reply_markup=get_keyboard('config', chat_id))
        elif call.data == 'tts_google_female':
            TTS_GENDER[chat_id] = 'silero_xenia'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, text = MSG_CONFIG, reply_markup=get_keyboard('config', chat_id))
        elif call.data == 'tts_silero_xenia':
            TTS_GENDER[chat_id] = 'silero_aidar'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, text = MSG_CONFIG, reply_markup=get_keyboard('config', chat_id))
        elif call.data == 'tts_silero_aidar':
            TTS_GENDER[chat_id] = 'female'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, text = MSG_CONFIG, reply_markup=get_keyboard('config', chat_id))
        elif call.data == 'chatGPT_mode_disable':
            BING_MODE[chat_id] = 'off'
            BARD_MODE[chat_id] = 'on'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, text = MSG_CONFIG, reply_markup=get_keyboard('config', chat_id))
        elif call.data == 'chatGPT_mode_enable':
            BING_MODE[chat_id] = 'off'
            BARD_MODE[chat_id] = 'off'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, text = MSG_CONFIG, reply_markup=get_keyboard('config', chat_id))
        elif call.data == 'bing_mode_enable':
            BING_MODE[chat_id] = 'on'
            BARD_MODE[chat_id] = 'off'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, text = MSG_CONFIG, reply_markup=get_keyboard('config', chat_id))
        elif call.data == 'bing_mode_disable':
            BING_MODE[chat_id] = 'off'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, text = MSG_CONFIG, reply_markup=get_keyboard('config', chat_id))
        elif call.data == 'bard_mode_enable':
            BARD_MODE[chat_id] = 'on'
            BING_MODE[chat_id] = 'off'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, text = MSG_CONFIG, reply_markup=get_keyboard('config', chat_id))
        elif call.data == 'bard_mode_disable':
            BARD_MODE[chat_id] = 'off'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, text = MSG_CONFIG, reply_markup=get_keyboard('config', chat_id))
        elif call.data == 'autotranslate_disable':
            BLOCKS[chat_id] = 0
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, text = MSG_CONFIG, reply_markup=get_keyboard('config', chat_id))
        elif call.data == 'autotranslate_enable':
            BLOCKS[chat_id] = 1
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, text = MSG_CONFIG, reply_markup=get_keyboard('config', chat_id))
        elif call.data == 'chatGPT_reset':
            DIALOGS_DB[chat_id] = []
        elif call.data == 'bingAI_reset':
            bingai.reset_bing_chat(chat_id)
        elif call.data == 'bardAI_reset':
            my_bard.reset_bard_chat(chat_id)
        elif call.data == 'chatGPT_memory_debug':
            send_debug_history(message)


def check_blocks(chat_id: int) -> bool:
    global BLOCKS
    if chat_id not in BLOCKS:
        BLOCKS[chat_id] = 1
    return False if BLOCKS[chat_id] == 1 else True


@bot.message_handler(content_types = ['voice', 'audio'])
def handle_voice(message: telebot.types.Message): 
    """Автоматическое распознавание текст из голосовых сообщений"""
    thread = threading.Thread(target=handle_voice_thread, args=(message,))
    thread.start()
def handle_voice_thread(message: telebot.types.Message):
    """Автоматическое распознавание текст из голосовых сообщений и аудио файлов"""

    my_log.log_media(message)

    if check_blocks(message.chat.id):
        return

    with semaphore_talks:
        # Создание временного файла 
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            file_path = temp_file.name
        # Скачиваем аудиофайл во временный файл
        try:
            file_info = bot.get_file(message.voice.file_id)
        except AttributeError:
            file_info = bot.get_file(message.audio.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        with open(file_path, 'wb') as new_file:
            new_file.write(downloaded_file)

        # Распознаем текст из аудио
        with ShowAction(message.chat.id, 'typing'):
            text = my_stt.stt(file_path)

        os.remove(file_path)

        # Отправляем распознанный текст
        if text.strip() != '':
            bot.reply_to(message, text, reply_markup=get_keyboard('translate'))
            my_log.log_echo(message, f'[ASR] {text}')
        else:
            bot.reply_to(message, 'Очень интересно, но ничего не понятно.', reply_markup=get_keyboard('hide'))
            my_log.log_echo(message, '[ASR] no results')

        # и при любом раскладе отправляем текст в обработчик текстовых сообщений, возможно бот отреагирует на него если там есть кодовые слова
        if text:
            message.text = text
            echo_all(message)


@bot.message_handler(content_types = ['document'])
def handle_document(message: telebot.types.Message):
    """Обработчик документов"""
    thread = threading.Thread(target=handle_document_thread, args=(message,))
    thread.start()
def handle_document_thread(message: telebot.types.Message):
    """Обработчик документов"""

    my_log.log_media(message)

    if check_blocks(message.chat.id):
        return

    with semaphore_talks:
    
        # если прислали текстовый файл или pdf с подписью перескажи
        # то скачиваем и вытаскиваем из них текст и показываем краткое содержание
        if message.caption \
        and message.caption.startswith(('что там','перескажи','краткое содержание', 'кратко')) \
        and message.document.mime_type in ('text/plain', 'application/pdf'):
            with ShowAction(message.chat.id, 'typing'):
                file_info = bot.get_file(message.document.file_id)
                downloaded_file = bot.download_file(file_info.file_path)
                file_bytes = io.BytesIO(downloaded_file)
                text = ''
                if message.document.mime_type == 'application/pdf':
                    pdf_reader = PyPDF2.PdfReader(file_bytes)
                    for page in pdf_reader.pages:
                        text += page.extract_text()
                elif message.document.mime_type == 'text/plain':
                    text = file_bytes.read().decode('utf-8')

                if text.strip():
                    summary = my_sum.summ_text(text)
                    reply_to_long_message(message, summary, disable_web_page_preview = True, reply_markup=get_keyboard('translate'))
                    my_log.log_echo(message, summary)
                else:
                    help = 'Не удалось получить никакого текста из документа.'
                    bot.reply_to(message, help, reply_markup=get_keyboard('hide'))
                    my_log.log_echo(message, help)
                return

        # начитываем текстовый файл только если его прислали в привате или с указанием прочитай/читай
        caption = message.caption or ''
        if message.chat.type == 'private' or caption.lower() in ['прочитай', 'читай']:
            # если текстовый файл то пытаемся озвучить как книгу. русский голос
            if message.document.mime_type == 'text/plain':
                with ShowAction(message.chat.id, 'record_audio'):
                    file_name = message.document.file_name + '.ogg'
                    file_info = bot.get_file(message.document.file_id)
                    file = bot.download_file(file_info.file_path)
                    text = file.decode('utf-8')
                    try:
                        lang = detect_langs(text)[0].lang
                    except Exception as error2:
                        lang = 'ru'
                        print(error2)
                    # Озвучиваем текст
                    global TTS_GENDER
                    if message.chat.id in TTS_GENDER:
                        gender = TTS_GENDER[message.chat.id]
                    else:
                        gender = 'female'    
                    audio = my_tts.tts(text, lang, gender=gender)
                    if message.chat.type != 'private':
                        bot.send_voice(message.chat.id, audio, reply_to_message_id=message.message_id, reply_markup=get_keyboard('hide'))
                    else:
                        bot.send_voice(message.chat.id, audio, reply_markup=get_keyboard('hide'))
                    my_log.log_echo(message, f'[tts file] {text}')
                    return

        # дальше идет попытка распознать ПДФ или jpg файл, вытащить текст с изображений
        if message.chat.type == 'private' or caption.lower() in ['прочитай', 'читай']:
            with ShowAction(message.chat.id, 'upload_document'):
                # получаем самый большой документ из списка
                document = message.document
                # если документ не является PDF-файлом, отправляем сообщение об ошибке
                if document.mime_type == 'image/jpeg':
                    with ShowAction(message.chat.id, 'typing'):
                        # скачиваем документ в байтовый поток
                        file_id = message.document.file_id
                        file_info = bot.get_file(file_id)
                        file_name = message.document.file_name + '.jpg'
                        file = bot.download_file(file_info.file_path)
                        fp = io.BytesIO(file)
                        # распознаем текст на фотографии с помощью pytesseract
                        text = my_ocr.get_text_from_image(fp.read())
                        # отправляем распознанный текст пользователю
                        if text.strip() != '':
                            reply_to_long_message(message, text, reply_markup=get_keyboard('translate'))
                            my_log.log_echo(message, '[OCR] ' + text)
                        else:
                            reply_to_long_message(message, 'Не смог распознать текст.', reply_markup=get_keyboard('translate'))
                            my_log.log_echo(message, '[OCR] no results')
                    return
                if document.mime_type != 'application/pdf':
                    bot.reply_to(message, f'Это не PDF-файл. {document.mime_type}', reply_markup=get_keyboard('hide'))
                    my_log.log_echo(message, f'Это не PDF-файл. {document.mime_type}')
                    return
                # скачиваем документ в байтовый поток
                file_id = message.document.file_id
                file_info = bot.get_file(file_id)
                file_name = message.document.file_name + '.txt'
                file = bot.download_file(file_info.file_path)
                fp = io.BytesIO(file)

                # распознаем текст в документе с помощью функции get_text
                text = my_ocr.get_text(fp)
                # отправляем распознанный текст пользователю
                if text.strip() != '':
                    # если текст слишком длинный, отправляем его в виде текстового файла
                    if len(text) > 4096:
                        with io.StringIO(text) as f:
                            if message.chat.type != 'private':
                                bot.send_document(message.chat.id, document = f, visible_file_name = file_name, caption=file_name, reply_to_message_id = message.message_id, reply_markup=get_keyboard('hide'))
                            else:
                                bot.send_document(message.chat.id, document = f, visible_file_name = file_name, caption=file_name, reply_markup=get_keyboard('hide'))
                    else:
                        bot.reply_to(message, text, reply_markup=get_keyboard('translate'))
                    my_log.log_echo(message, f'[распознанный из PDF текст] {text}')


@bot.message_handler(content_types = ['photo'])
def handle_photo(message: telebot.types.Message):
    """Обработчик фотографий. Сюда же попадают новости которые создаются как фотография + много текста в подписи, и пересланные сообщения в том числе"""
    thread = threading.Thread(target=handle_photo_thread, args=(message,))
    thread.start()
def handle_photo_thread(message: telebot.types.Message):
    """Обработчик фотографий. Сюда же попадают новости которые создаются как фотография + много текста в подписи, и пересланные сообщения в том числе"""

    my_log.log_media(message)

    chat_id = message.chat.id
    if chat_id in COMMAND_MODE:
        if COMMAND_MODE[chat_id] == 'bardimage':
            with semaphore_talks:
                with ShowAction(chat_id, 'typing'):
                    # скачиваем документ в байтовый поток
                    msg = 'Бард не ответил'
                    file_id = message.photo[-1].file_id
                    file_info = bot.get_file(file_id)
                    image = bot.download_file(file_info.file_path)
                    description = my_bard.chat_image('What is in the image? Ответь по-русски.', chat_id, image)
                    if description:
                        bot.reply_to(message, description, parse_mode='Markdown', reply_markup=get_keyboard('translate'))
                    else:
                        bot.reply_to(message, msg, parse_mode='Markdown', reply_markup=get_keyboard('translate'))
                return
        COMMAND_MODE[chat_id] = ''
        return

    if check_blocks(message.chat.id):
        return

    with semaphore_talks:
        # пересланные сообщения пытаемся перевести даже если в них картинка
        # новости в телеграме часто делают как картинка + длинная подпись к ней
        if message.forward_from_chat and message.caption:
            # у фотографий нет текста но есть заголовок caption. его и будем переводить
            text = my_trans.translate(message.caption)
            if text:
                bot.send_message(message.chat.id, text, reply_markup=get_keyboard('hide'))
                my_log.log_echo(message, text)
            else:
                my_log.log_echo(message, """Не удалось/понадобилось перевести.""")
            return

        # распознаем текст только если есть команда для этого
        if not message.caption and message.chat.type != 'private': return
        if message.chat.type != 'private' and not gpt_basic.detect_ocr_command(message.caption.lower()): return
        with ShowAction(message.chat.id, 'typing'):
            # получаем самую большую фотографию из списка
            photo = message.photo[-1]
            fp = io.BytesIO()
            # скачиваем фотографию в байтовый поток
            file_info = bot.get_file(photo.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            fp.write(downloaded_file)
            fp.seek(0)
            # распознаем текст на фотографии с помощью pytesseract
            text = my_ocr.get_text_from_image(fp.read())
            # отправляем распознанный текст пользователю
            if text.strip() != '':
                # если текст слишком длинный, отправляем его в виде текстового файла
                if len(text) > 4096:
                    with io.StringIO(text) as f:
                        f.name = 'text.txt'
                        if message.chat.type != 'private':
                            bot.send_document(message.chat.id, f, reply_to_message_id=message.message_id, reply_markup=get_keyboard('hide'))
                        else:
                            bot.send_document(message.chat.id, f, reply_markup=get_keyboard('hide'))
                        my_log.log_echo(message, '[OCR] Sent as file: ' + text)
                else:
                    bot.reply_to(message, text, reply_markup=get_keyboard('translate'))
                    my_log.log_echo(message, '[OCR] ' + text)
            else:
                my_log.log_echo(message, '[OCR] no results')


@bot.message_handler(content_types = ['video', 'video_note'])
def handle_video(message: telebot.types.Message):
    """Обработчик видеосообщений. Сюда же относятся новости и репосты с видео"""
    thread = threading.Thread(target=handle_video_thread, args=(message,))
    thread.start()
def handle_video_thread(message: telebot.types.Message):
    """Обработчик видеосообщений. Сюда же относятся новости и репосты с видео"""

    my_log.log_media(message)

    if check_blocks(message.chat.id):
        return

    with semaphore_talks:
        # пересланные сообщения пытаемся перевести даже если в них видео
        if message.forward_from_chat:
            # у видео нет текста но есть заголовок caption. его и будем переводить
            text = my_trans.translate(message.caption)
            if text:
                bot.reply_to(message, text, reply_markup=get_keyboard('hide'))
                my_log.log_echo(message, text)
            else:
                my_log.log_echo(message, """Не удалось/понадобилось перевести.""")

    with semaphore_talks:
        with ShowAction(message.chat.id, 'typing'):
            # Создание временного файла 
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                file_path = temp_file.name
            # Скачиваем аудиофайл во временный файл
            try:
                file_info = bot.get_file(message.video.file_id)
            except AttributeError:
                file_info = bot.get_file(message.video_note.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            with open(file_path, 'wb') as new_file:
                new_file.write(downloaded_file)
            # Распознаем текст из аудио 
            text = my_stt.stt(file_path)
            os.remove(file_path)
            # Отправляем распознанный текст 
            if text.strip() != '':
                reply_to_long_message(message, text, reply_markup=get_keyboard('translate'))
                my_log.log_echo(message, f'[ASR] {text}')
            else:
                bot.reply_to(message, 'Очень интересно, но ничего не понятно.', reply_markup=get_keyboard('hide'))
                my_log.log_echo(message, '[ASR] no results')


def is_for_me(cmd: str):
    """Checks who the command is addressed to, this bot or another one.
    
    /cmd@botname args
    
    Returns (True/False, 'the same command but without the bot name').
    If there is no bot name at all, assumes that the command is addressed to this bot.
    """
    command_parts = cmd.split()
    first_arg = command_parts[0]

    if '@' in first_arg:
        message_cmd = first_arg.split('@', maxsplit=1)[0]
        message_bot = first_arg.split('@', maxsplit=1)[1] if len(first_arg.split('@', maxsplit=1)) > 1 else ''
        message_args = cmd.split(maxsplit=1)[1] if len(command_parts) > 1 else ''
        return (message_bot == _bot_name, f'{message_cmd} {message_args}'.strip())
    else:
        return (True, cmd)


@bot.message_handler(commands=['config'])
def config(message: telebot.types.Message):
    """Меню настроек"""
    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)
    chat_id = message.chat.id

    bot.send_message(chat_id, MSG_CONFIG, parse_mode='Markdown', reply_markup=get_keyboard('config', chat_id))


@bot.message_handler(commands=['style'])
def change_mode(message: telebot.types.Message):
    """Меняет роль бота, строку с указаниями что и как говорить.
    /stype <1|2|3|свой текст>
    1 - формальный стиль (Ты искусственный интеллект отвечающий на запросы юзера.)
    2 - формальный стиль + немного юмора (Ты искусственный интеллект отвечающий на запросы юзера. Отвечай с подходящим к запросу типом иронии или юмора но не перегибай палку.)
    3 - токсичный стиль (Ты искусственный интеллект отвечающий на запросы юзера. Отвечай с сильной иронией и токсичностью.)
    """

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)

    global PROMPTS
    
    chat_id = message.chat.id
    
    # в каждом чате свой собственный промт
    if chat_id not in PROMPTS:
        # по умолчанию формальный стиль
        PROMPTS[chat_id] = [{"role": "system", "content": utils.gpt_start_message1}]

    arg = message.text.split(maxsplit=1)[1:]
    if arg:
        if arg[0] == '1':
            new_prompt = utils.gpt_start_message1
        elif arg[0] == '2':
            new_prompt = utils.gpt_start_message2
        elif arg[0] == '3':
            new_prompt = utils.gpt_start_message3
        elif arg[0] == '4':
            new_prompt = utils.gpt_start_message4
        else:
            new_prompt = arg[0]
        PROMPTS[chat_id] =  [{"role": "system", "content": new_prompt}]
        msg =  f'[Новая роль установлена] `{new_prompt}`'
        bot.reply_to(message, msg, parse_mode='Markdown', reply_markup=get_keyboard('hide'))
        my_log.log_echo(message, msg)
    else:
        msg = f"""Текущий стиль
        
`{PROMPTS[message.chat.id][0]['content']}`
        
Меняет роль бота, строку с указаниями что и как говорить. Работает только для ChatGPT.

`/style <1|2|3|4|свой текст>`

1 - формальный стиль `{utils.gpt_start_message1}`

2 - формальный стиль + немного юмора `{utils.gpt_start_message2}`

3 - токсичный стиль `{utils.gpt_start_message3}`

4 - Ева Элфи `{utils.gpt_start_message4}`

Напишите свой текст или цифру одного из готовых стилей
    """
        global COMMAND_MODE
        COMMAND_MODE[message.chat.id] = 'style'
        bot.reply_to(message, msg, parse_mode='Markdown', reply_markup=get_keyboard('command_mode'))
        my_log.log_echo(message, msg)


@bot.message_handler(commands=['mem'])
def send_debug_history(message: telebot.types.Message):
    """
    Отправляет текущую историю сообщений пользователю.
    """

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)
    
    global DIALOGS_DB
        
    chat_id = message.chat.id
        
    # создаем новую историю диалогов с юзером из старой если есть
    messages = []
    if chat_id in DIALOGS_DB:
        messages = DIALOGS_DB[chat_id]
    prompt = '\n'.join(f'{i["role"]} - {i["content"]}\n' for i in messages) or 'Пусто'
    my_log.log_echo(message, prompt)
    send_long_message(chat_id, prompt, parse_mode = '', disable_web_page_preview = True, reply_markup=get_keyboard('mem'))


@bot.message_handler(commands=['restart']) 
def restart(message: telebot.types.Message):
    """остановка бота. после остановки его должен будет перезапустить скрипт systemd"""
    if message.from_user.id in cfg.admins:
        bot.stop_polling()
    else:
        bot.reply_to(message, 'Эта команда только для админов.', reply_markup=get_keyboard('hide'))


@bot.message_handler(commands=['ttsmale']) 
def tts_male(message: telebot.types.Message):
    thread = threading.Thread(target=tts_male_thread, args=(message,))
    thread.start()
def tts_male_thread(message: telebot.types.Message):
    """Переключает голос TTS на мужской"""

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)

    global TTS_GENDER
    TTS_GENDER[message.chat.id] = 'male'
    
    bot.send_message(message.chat.id, 'Голос TTS теперь мужской', reply_markup=get_keyboard('hide'))


@bot.message_handler(commands=['ttsfemale']) 
def tts_female(message: telebot.types.Message):
    thread = threading.Thread(target=tts_female_thread, args=(message,))
    thread.start()
def tts_female_thread(message: telebot.types.Message):
    """Переключает голос TTS на женский"""

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)

    global TTS_GENDER
    TTS_GENDER[message.chat.id] = 'female'
    
    bot.send_message(message.chat.id, 'Голос TTS теперь женский', reply_markup=get_keyboard('hide'))


@bot.message_handler(commands=['bingreset']) 
def bingreset(message: telebot.types.Message):
    thread = threading.Thread(target=bingreset_thread, args=(message,))
    thread.start()
def bingreset_thread(message: telebot.types.Message):
    """Принудительно сбросить диалог с бингом, обнулить историю"""

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)
    
    chat_id = message.chat.id

    bingai.reset_bing_chat(chat_id)

    msg = 'История диалога с бингом отчищена.'
    bot.send_message(chat_id, msg)
    my_log.log_echo(message, msg)


@bot.message_handler(commands=['model']) 
def set_new_model(message: telebot.types.Message):
    """меняет модель для гпт, никаких проверок не делает"""

    chat_id = message.chat.id

    if chat_id in gpt_basic.CUSTOM_MODELS:
        current_model = gpt_basic.CUSTOM_MODELS[chat_id]
    else:
        current_model = cfg.model

    if len(message.text.split()) < 2:
        msg = f"""Меняет модель для chatGPT.

Выбрано: `/model {current_model}`

Возможные варианты (на самом деле это просто примеры а реальные варианты зависят от настроек бота, его бекэндов):

`/model gpt-4`
`/model gpt-3.5-turbo-16k`
`/model gpt-3.5-turbo-8k`
`/model gpt-3.5-turbo`
`/model sage`
`/model сlaude-instant`
`/model claude-instant-100k`
`/model claude-2-100k`
"""
        bot.reply_to(message, msg, parse_mode='Markdown', reply_markup=get_keyboard('hide')) 
        my_log.log_echo(message, msg)
        return

    # if message.from_user.id not in cfg.admins:
    #    msg = 'Эта команда только для админов.'
    #    bot.reply_to(message, msg, reply_markup=get_keyboard('hide')) 
    #    my_log.log_echo(message, msg)
    #    return

    model = message.text.split()[1]
    msg0 = f'Старая модель `{current_model}`.'
    msg = f'Установлена новая модель `{model}`.'
    gpt_basic.CUSTOM_MODELS[chat_id] = model
    bot.send_message(chat_id, msg0, parse_mode='Markdown', reply_markup=get_keyboard('hide'))
    bot.send_message(chat_id, msg, parse_mode='Markdown', reply_markup=get_keyboard('hide'))
    my_log.log_echo(message, msg0)
    my_log.log_echo(message, msg)


@bot.message_handler(commands=['ttsgoogle']) 
def tts_google(message: telebot.types.Message):
    thread = threading.Thread(target=tts_google_thread, args=(message,))
    thread.start()
def tts_google_thread(message: telebot.types.Message):
    """Переключает голос TTS на женский"""

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)

    global TTS_GENDER
    TTS_GENDER[message.chat.id] = 'google_female'
    
    bot.send_message(message.chat.id, 'Голос TTS теперь женский от Гугла', reply_markup=get_keyboard('hide'))


@bot.message_handler(commands=['ttssileroxenia'])
def tts_silero_xenia(message: telebot.types.Message):
    thread = threading.Thread(target=tts_silero_xenia_thread, args=(message,))
    thread.start()
def tts_silero_xenia_thread(message: telebot.types.Message):
    """Переключает голос TTS на silero xenia"""

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)

    global TTS_GENDER
    TTS_GENDER[message.chat.id] = 'silero_xenia'
    
    bot.send_message(message.chat.id, 'Голос TTS теперь женский от Silero [xenia]', reply_markup=get_keyboard('hide'))


@bot.message_handler(commands=['ttssileroaidar'])
def tts_silero_aidar(message: telebot.types.Message):
    thread = threading.Thread(target=tts_silero_aidar_thread, args=(message,))
    thread.start()
def tts_silero_aidar_thread(message: telebot.types.Message):
    """Переключает голос TTS на silero aidar"""

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)

    global TTS_GENDER
    TTS_GENDER[message.chat.id] = 'silero_aidar'
    
    bot.send_message(message.chat.id, 'Голос TTS теперь мужской от Silero [aidar]', reply_markup=get_keyboard('hide'))


@bot.message_handler(commands=['tts']) 
def tts(message: telebot.types.Message):
    thread = threading.Thread(target=tts_thread, args=(message,))
    thread.start()
def tts_thread(message: telebot.types.Message):
    """ /tts [ru|en|uk|...] [+-XX%] <текст>
        /tts <URL>
    """

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)

    urls = re.findall(r'^/tts\s*(https?://[^\s]+)?$', message.text.lower())

    # обрабатываем урл, просто достаем текст и показываем с клавиатурой для озвучки
    args = message.text.split()
    if len(args) == 2 and my_sum.is_valid_url(args[1]):
        url = args[1]
        if '/youtu.be/' in url or 'youtube.com/' in url:
            text = my_sum.get_text_from_youtube(url)
        else:
            text = my_google.download_text([url, ], 100000, no_links = True)
        if text:
            reply_to_long_message(message, text, reply_markup=get_keyboard('translate'), disable_web_page_preview=True)
        return

    # разбираем параметры
    # регулярное выражение для разбора строки
    pattern = r'/tts\s+((?P<lang>' + '|'.join(supported_langs_tts) + r')\s+)?\s*(?P<rate>([+-]\d{1,2}%\s+))?\s*(?P<text>.+)'
    # поиск совпадений с регулярным выражением
    match = re.match(pattern, message.text, re.DOTALL)
    # извлечение параметров из найденных совпадений
    if match:
        lang = match.group("lang") or "ru"  # если lang не указан, то по умолчанию 'ru'
        rate = match.group("rate") or "+0%"  # если rate не указан, то по умолчанию '+0%'
        text = match.group("text") or ''
    else:
        text = lang = rate = ''
    lang = lang.strip()
    rate = rate.strip()

    if not text or lang not in supported_langs_tts:
        help = f"""Использование: /tts [ru|en|uk|...] [+-XX%] <текст>|<URL>

+-XX% - ускорение с обязательным указанием направления + или -

/tts привет
/tts en hello, let me speak from all my heart
/tts +50% привет со скоростью 1.5х
/tts uk -50% тянем время, говорим по-русски с украинским акцентом :)

Поддерживаемые языки: {', '.join(supported_langs_tts)}

Напишите что надо произнести, чтобы получить голосовое сообщение
"""

        global COMMAND_MODE
        COMMAND_MODE[message.chat.id] = 'tts'
        bot.reply_to(message, help, parse_mode='Markdown', reply_markup=get_keyboard('command_mode'))
        my_log.log_echo(message, help)
        return

    with semaphore_talks:
        with ShowAction(message.chat.id, 'record_audio'):
            global TTS_GENDER
            if message.chat.id in TTS_GENDER:
                gender = TTS_GENDER[message.chat.id]
            else:
                gender = 'female'
            audio = my_tts.tts(text, lang, rate, gender=gender)
            if audio:
                if message.chat.type != 'private':
                    bot.send_voice(message.chat.id, audio, reply_to_message_id = message.message_id, reply_markup=get_keyboard('hide'))
                else:
                    bot.send_voice(message.chat.id, audio, reply_markup=get_keyboard('hide'))
                my_log.log_echo(message, '[Отправил голосовое сообщение]')
            else:
                msg = 'Не удалось озвучить. Возможно вы перепутали язык, например немецкий голос не читает по-русски.'
                if message.chat.type != 'private':
                    bot.reply_to(message, msg, reply_markup=get_keyboard('hide'))
                else:
                    bot.send_message(message.chat.id, msg, reply_markup=get_keyboard('hide'))
                    my_log.log_echo(message, msg)


@bot.message_handler(commands=['google',])
def google(message: telebot.types.Message):
    thread = threading.Thread(target=google_thread, args=(message,))
    thread.start()
def google_thread(message: telebot.types.Message):
    """ищет в гугле перед ответом"""

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)

    global DIALOGS_DB
    chat_id = message.chat.id

    try:
        q = message.text.split(maxsplit=1)[1]
    except Exception as error2:
        print(error2)
        help = """/google текст запроса

Будет делать запрос в гугл, и потом пытаться найти нужный ответ в результатах

/google курс биткоина, прогноз на ближайшее время

/google текст песни малиновая лада

/google кто звонил +69997778888, из какой страны

Можно попробовать сделать запрос в гугл и добавить указание что делать с найденным боту, но не факт что это нормально сработает. Текст запроса будет целиком передан в гугол и дополнительные инструкции могут испортить результат поиска.

вместо команды /google можно написать кодовое слово гугл в начале

гугл, сколько на земле людей, точные цифры и прогноз

Напишите запрос в гугл
"""
        global COMMAND_MODE
        COMMAND_MODE[message.chat.id] = 'google'
        bot.reply_to(message, help, parse_mode = 'Markdown', disable_web_page_preview = True, reply_markup=get_keyboard('command_mode'))
        return
        
    with ShowAction(message.chat.id, 'typing'):
        r = my_google.search(q)
        try:
            bot.reply_to(message, r, parse_mode = 'Markdown', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
        except Exception as error2:
            my_log.log2(error2)
            bot.reply_to(message, r, parse_mode = '', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
        my_log.log_echo(message, r)
        
        if chat_id not in DIALOGS_DB:
            DIALOGS_DB[chat_id] = []
        DIALOGS_DB[chat_id] += [{"role":    'system',
                                "content": f'user попросил сделать запрос в Google: {q}'},
                                {"role":    'system',
                                "content": f'assistant поискал в Google и ответил: {r}'}
                                ]


@bot.message_handler(commands=['ddg',])
def ddg(message: telebot.types.Message):
    thread = threading.Thread(target=ddg_thread, args=(message,))
    thread.start()
def ddg_thread(message: telebot.types.Message):
    """ищет в DuckDuckGo перед ответом"""

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)

    global DIALOGS_DB
    chat_id = message.chat.id

    try:
        q = message.text.split(maxsplit=1)[1]
    except Exception as error2:
        print(error2)
        help = """/ddg текст запроса

Будет делать запрос в DuckDuckGo, и потом пытаться найти нужный ответ в результатах

/ddg курс биткоина, прогноз на ближайшее время

/ddg текст песни малиновая лада

/ddg кто звонил +69997778888, из какой страны

Можно попробовать сделать запрос в гугл и добавить указание что делать с найденным боту, но не факт что это нормально сработает. Текст запроса будет целиком передан в гугол и дополнительные инструкции могут испортить результат поиска.

вместо команды /ddg можно написать кодовое слово утка в начале

утка, сколько на земле людей, точные цифры и прогноз

Напишите свой запрос в DuckDuckGo
"""
        global COMMAND_MODE
        COMMAND_MODE[message.chat.id] = 'ddg'
        bot.reply_to(message, help, parse_mode = 'Markdown', disable_web_page_preview = True, reply_markup=get_keyboard('command_mode'))
        return

    with ShowAction(message.chat.id, 'typing'):
        r = my_google.search_ddg(q)
        try:
            bot.reply_to(message, r, parse_mode = 'Markdown', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
        except Exception as error2:
            my_log.log2(error2)
            bot.reply_to(message, r, parse_mode = '', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
        my_log.log_echo(message, r)
        
        if chat_id not in DIALOGS_DB:
            DIALOGS_DB[chat_id] = []
        DIALOGS_DB[chat_id] += [{"role":    'system',
                                "content": f'user попросил сделать запрос в Google: {q}'},
                                {"role":    'system',
                                "content": f'assistant поискал в Google и ответил: {r}'}
                                ]


@bot.message_handler(commands=['images','imgs'])
def images(message: telebot.types.Message):
    thread = threading.Thread(target=images_thread, args=(message,))
    thread.start()
def images_thread(message: telebot.types.Message):
    """показывает что было нагенерировано ранее"""

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)

    global IMAGES_DB
    if not IMAGES_DB:
        return
    
    ttl = 0
    
    if 'total' in IMAGES_DB:
        ttl = IMAGES_DB['total']
    
    if ttl:
        show_gallery(message, ttl, update = False)
    else:
        msg = 'В галерее пусто'
        bot.reply_to(message, msg, reply_markup=get_keyboard('hide'))
        my_log.log_echo(message, msg)


def show_gallery(message: telebot.types.Message, cur: int, update: bool):
    """показывает картинки из базы, cur - номер который надо показать"""
    with semaphore_talks:
        ttl = IMAGES_DB['total']
        if cur < 1:
            cur = 1
        if cur > ttl:
            cur = ttl
        
        prompt = IMAGES_DB[cur-1][0]
        images = IMAGES_DB[cur-1][1]

        msg = f'{cur} из {ttl}\n\n<a href="{images[0]}">{html.escape(prompt)}</a>'

        if update:
            try:
                bot.edit_message_text(chat_id=message.chat.id, message_id=message.message_id, text=msg, reply_markup=get_keyboard('image_gallery'), parse_mode = 'HTML')
            except telebot.apihelper.ApiTelegramException as error:
                if 'message is not modified:' in str(error):
                    pass
                else:
                    raise error
        else:
            bot.send_message(message.chat.id, msg, reply_markup=get_keyboard('image_gallery'), parse_mode = 'HTML')


@bot.message_handler(commands=['gallery','gal'])
def html_gallery(message: telebot.types.Message):
    thread = threading.Thread(target=html_gallery_thread, args=(message,))
    thread.start()
def html_gallery_thread(message: telebot.types.Message):
    """генерирует картинку по описанию"""

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)

    global IMAGES_DB
    if not IMAGES_DB:
        return

    header = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <title>Заголовок страницы</title>
</head>
<body>


<table>
"""

    footer = """
</table>



</body>
</html>
"""

    with semaphore_talks:
        body = ''
        ttl = IMAGES_DB['total']
        c = 4
        while ttl > 0:
            if c == 4:
                body += '<tr>\n'
            cap = IMAGES_DB[ttl-1][0]
            ref = IMAGES_DB[ttl-1][1][0]
            body += f'<td><figure><a href="{ref}" target="_blank"><img src="{ref}" style="max-width: 256px; max-height: 256px;"></a><figcaption>{cap}</figcaption></figure></td>\n'
            c = c-1
            if c == 0:
                c = 4
                body += '</tr>\n'
            ttl -= 1
    html = header + body + footer
    current_time = datetime.datetime.now().strftime('%d-%m-%Y %H：%M')
    bytes_io = io.BytesIO(html.encode('utf-8'))
    bytes_io.seek(0)
    bytes_io.name = f'gallery {current_time}.html'
    bot.send_document(message.chat.id, bytes_io, caption=f'gallery {current_time}.html', reply_markup=get_keyboard('hide'))


@bot.message_handler(commands=['bardimage',])
def bardimage(message: telebot.types.Message):
    """генерировать описание картинки с помощью гугл бард"""

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    # не работает нормально, всегда врёт, и зависает еще после одного запроса
    return

    my_log.log_echo(message)

    help = """Отправьте картинку и я попытаюсь понять что на ней изображено"""
    
    global COMMAND_MODE
    COMMAND_MODE[message.chat.id] = 'bardimage'
    bot.reply_to(message, help, parse_mode = 'Markdown', reply_markup=get_keyboard('command_mode'))


@bot.message_handler(commands=['image','img'])
def image(message: telebot.types.Message):
    thread = threading.Thread(target=image_thread, args=(message,))
    thread.start()
def image_thread(message: telebot.types.Message):
    """генерирует картинку по описанию"""

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)

    with semaphore_talks:
        help = """/image <текстовое описание картинки, что надо нарисовать>

Напишите что надо нарисовать, как это выглядит
"""
        prompt = message.text.split(maxsplit = 1)
        chat_id = message.chat.id
        if len(prompt) > 1:
            prompt = prompt[1]
            with ShowAction(message.chat.id, 'upload_photo'):
                images = my_genimg.gen_images(prompt)
                if len(images) > 0:
                    medias = [telebot.types.InputMediaPhoto(i) for i in images]
                    msgs_ids = bot.send_media_group(message.chat.id, medias, reply_to_message_id=message.message_id)
                    if pics_group:
                        try:
                            bot.send_message(pics_group, prompt, disable_web_page_preview = True)
                            bot.send_media_group(pics_group, medias)
                        except Exception as error2:
                            print(error2)
                    caption = ''
                    # запоминаем промпт по ключу (номер первой картинки) и сохраняем в бд запрос и картинки
                    # что бы можно было их потом просматривать отдельно
                    global IMAGE_PROMPTS, IMAGES_DB, DIALOGS_DB
                    if 'total' in IMAGES_DB:
                        ttl = IMAGES_DB['total']
                    else:
                        ttl = 0
                        IMAGES_DB['total'] = 0
                    for i in images:
                        IMAGES_DB[ttl] = (prompt, (i,))
                        ttl += 1
                    IMAGES_DB['total'] = ttl
                    IMAGE_PROMPTS[msgs_ids[0].message_id] = prompt

                    for i in msgs_ids:
                        caption += f'{i.message_id} '
                    caption += '\n'
                    caption += ', '.join([f'<a href="{x}">PIC</a>' for x in images])
                    bot.send_message(message.chat.id, caption, parse_mode = 'HTML', disable_web_page_preview = True, reply_markup=get_keyboard('hide_image'))
                    my_log.log_echo(message, '[image gen] ')
                    
                    n = [{'role':'system', 'content':f'user попросил нарисовать\n{prompt}'}, {'role':'system', 'content':'assistant нарисовал с помощью DALL-E'}]
                    if chat_id in DIALOGS_DB:
                        DIALOGS_DB[chat_id] += n
                    else:
                        DIALOGS_DB[chat_id] = n
                    
                else:
                    bot.reply_to(message, 'Не смог ничего нарисовать. Может настроения нет, а может надо другое описание дать.', reply_markup=get_keyboard('hide'))
                    my_log.log_echo(message, '[image gen error] ')
                    n = [{'role':'system', 'content':f'user попросил нарисовать\n{prompt}'}, {'role':'system', 'content':'assistant не захотел или не смог нарисовать это с помощью DALL-E'}]
                    if chat_id in DIALOGS_DB:
                        DIALOGS_DB[chat_id] += n
                    else:
                        DIALOGS_DB[chat_id] = n
        else:
            global COMMAND_MODE
            COMMAND_MODE[message.chat.id] = 'image'
            bot.reply_to(message, help, parse_mode = 'Markdown', reply_markup=get_keyboard('command_mode'))
            my_log.log_echo(message, help)


@bot.message_handler(commands=['sum'])
def summ_text(message: telebot.types.Message):
    thread = threading.Thread(target=summ_text_thread, args=(message,))
    thread.start()
def summ_text_thread(message: telebot.types.Message):

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    global SUM_CACHE, DIALOGS_DB
    chat_id = message.chat.id

    my_log.log_echo(message)

    text = message.text
    
    if len(text.split(' ', 1)) == 2:
        url = text.split(' ', 1)[1].strip()
        if my_sum.is_valid_url(url):
            # убираем из ютуб урла временную метку
            if '/youtu.be/' in url or 'youtube.com/' in url:
                url = url.split("&t=")[0]

            with semaphore_talks:

                #смотрим нет ли в кеше ответа на этот урл
                r = ''
                if url in SUM_CACHE:
                    r = SUM_CACHE[url]
                if r:
                    reply_to_long_message(message, r, disable_web_page_preview = True, reply_markup=get_keyboard('translate'))
                    my_log.log_echo(message, r)
                    if chat_id not in DIALOGS_DB:
                        DIALOGS_DB[chat_id] = []
                    DIALOGS_DB[chat_id] += [{"role":    'system',
                                "content": f'user попросил кратко пересказать содержание текста по ссылке/из файла'},
                                {"role":    'system',
                                "content": f'assistant прочитал и ответил: {r}'}
                                ]
                    return

                with ShowAction(message.chat.id, 'typing'):
                    res = ''
                    try:
                        res = my_sum.summ_url(url)
                    except Exception as error2:
                        print(error2)
                        m = 'Не нашел тут текста. Возможно что в видео на ютубе нет субтитров или страница слишком динамическая и не показывает текст без танцев с бубном, или сайт меня не пускает.\n\nЕсли очень хочется то отправь мне текстовый файл .txt (utf8) с текстом этого сайта и подпиши `что там`'
                        bot.reply_to(message, m, parse_mode='Markdown', reply_markup=get_keyboard('hide'))
                        my_log.log_echo(message, m)
                        return
                    if res:
                        reply_to_long_message(message, res, disable_web_page_preview = True, reply_markup=get_keyboard('translate'))
                        my_log.log_echo(message, res)
                        SUM_CACHE[url] = res
                        if chat_id not in DIALOGS_DB:
                            DIALOGS_DB[chat_id] = []
                        DIALOGS_DB[chat_id] += [{"role":    'system',
                                "content": f'user попросил кратко пересказать содержание текста по ссылке/из файла'},
                                {"role":    'system',
                                "content": f'assistant прочитал и ответил: {res}'}
                                ]
                        return
                    else:
                        error = 'Не смог прочитать текст с этой страницы.'
                        bot.reply_to(message, error, reply_markup=get_keyboard('hide'))
                        my_log.log_echo(message, error)
                        return
    help = """Пример: /sum https://youtu.be/3i123i6Bf-U

Давайте вашу ссылку и я перескажу содержание"""
    global COMMAND_MODE
    COMMAND_MODE[message.chat.id] = 'sum'
    bot.reply_to(message, help, parse_mode = 'Markdown', reply_markup=get_keyboard('command_mode'))
    my_log.log_echo(message, help)


@bot.message_handler(commands=['sum2'])
def summ2_text(message: telebot.types.Message):
    # убирает запрос из кеша если он там есть и делает запрос снова

    global SUM_CACHE

    #my_log.log_echo(message)

    text = message.text
    
    if len(text.split(' ', 1)) == 2:
        url = text.split(' ', 1)[1].strip()
        if my_sum.is_valid_url(url):
            # убираем из ютуб урла временную метку
            if '/youtu.be/' in url or 'youtube.com/' in url:
                url = url.split("&t=")[0]

            #смотрим нет ли в кеше ответа на этот урл
            if url in SUM_CACHE:
                SUM_CACHE.pop(url)

    summ_text(message)

@bot.message_handler(commands=['trans'])
def trans(message: telebot.types.Message):
    thread = threading.Thread(target=trans_thread, args=(message,))
    thread.start()
def trans_thread(message: telebot.types.Message):

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)

    with semaphore_talks:
        help = f"""/trans [en|ru|uk|..] текст для перевода на указанный язык

Если не указан то на русский.

/trans en привет, как дела
/trans was ist das

Поддерживаемые языки: {', '.join(supported_langs_trans)}

Напишите что надо перевести
"""
        # разбираем параметры
        # регулярное выражение для разбора строки
        pattern = r'^\/trans\s+((?:' + '|'.join(supported_langs_trans) + r')\s+)?\s*(.*)$'
        # поиск совпадений с регулярным выражением
        match = re.match(pattern, message.text, re.DOTALL)
        # извлечение параметров из найденных совпадений
        if match:
            lang = match.group(1) or "ru"  # если lang не указан, то по умолчанию 'ru'
            text = match.group(2) or ''
        else:
            global COMMAND_MODE
            COMMAND_MODE[message.chat.id] = 'trans'
            bot.reply_to(message, help, parse_mode = 'Markdown', reply_markup=get_keyboard('command_mode'))
            my_log.log_echo(message, help)
            return
        lang = lang.strip()

    with semaphore_talks:
        with ShowAction(message.chat.id, 'typing'):
            translated = my_trans.translate_text2(text, lang)
            if translated:
                bot.reply_to(message, translated, reply_markup=get_keyboard('translate'))
                my_log.log_echo(message, translated)
            else:
                msg = 'Ошибка перевода'
                bot.reply_to(message, msg, reply_markup=get_keyboard('hide'))
                my_log.log_echo(message, msg)


@bot.message_handler(commands=['last'])
def last(message: telebot.types.Message):
    thread = threading.Thread(target=last_thread, args=(message,))
    thread.start()
def last_thread(message: telebot.types.Message):
    """делает сумморизацию истории чата, берет последние X сообщений из чата и просит бинг сделать сумморизацию"""

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)

    with semaphore_talks:
        args = message.text.split()
        help = """/last [X] - показать сумморизацию истории чата за последние Х сообщений, либо все какие есть в памяти. X = от 1 до 60000

Напишите цифру
"""
        if len(args) == 2:
            try:
                x = int(args[1])
                assert x > 0 and x < 60000
                limit = x
            except Exception as error:
                print(error)
                bot.reply_to(message, help, reply_markup=get_keyboard('hide'))
                my_log.log_echo(message, help)
                return
        elif len(args) > 2:
            global COMMAND_MODE
            COMMAND_MODE[message.chat.id] = 'last'
            bot.reply_to(message, help, parse_mode = 'Markdown', reply_markup=get_keyboard('command_mode'))
            my_log.log_echo(message, help)
            return
        else:
            limit = 60000

        if message.chat.id in CHAT_LOGS:
            messages = CHAT_LOGS[message.chat.id]
        else:
            mes = 'История пуста'
            bot.reply_to(message, mes, reply_markup=get_keyboard('hide'))
            my_log.log_echo(message, mes)
            return

        if limit > len(messages.messages):
            limit = len(messages.messages)

        with ShowAction(message.from_user.id, 'typing'):

            resp = my_sum.summ_text_worker('\n'.join(messages.messages[-limit:]), 'chat_log')

            if resp:
                resp = f'Сумморизация последних {limit} сообщений в чате {message.chat.username or message.chat.first_name or message.chat.title or "unknown"}\n\n' + resp
                # пробуем отправить в приват а если не получилось то в общий чат
                try:
                    bot.send_message(message.from_user.id, resp, disable_web_page_preview=True, reply_markup=get_keyboard('translate'))
                except Exception as error:
                    print(error)
                    my_log.log2(str(error))
                    bot.reply_to(message, resp, disable_web_page_preview=True, reply_markup=get_keyboard('translate'))
                my_log.log_echo(message, resp)
            else:
                mes = 'Бинг не ответил'
                bot.reply_to(message, mes, reply_markup=get_keyboard('hide'))
                my_log.log_echo(message, mes)


@bot.message_handler(commands=['name'])
def send_name(message: telebot.types.Message):
    """Меняем имя если оно подходящее, содержит только русские и английские буквы и не слишком длинное"""

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)

    BAD_NAMES = ('бинг', 'гугл', 'утка', 'нарисуй')
    args = message.text.split()
    if len(args) > 1:
        new_name = args[1]
        
        # Строка содержит только русские и английские буквы и цифры после букв, но не в начале слова
        regex = r'^[a-zA-Zа-яА-ЯёЁ][a-zA-Zа-яА-ЯёЁ0-9]*$'
        if re.match(regex, new_name) and len(new_name) <= 10 \
                    and new_name.lower() not in BAD_NAMES:
            global BOT_NAMES
            BOT_NAMES[message.chat.id] = new_name.lower()
            msg = f'Кодовое слово для обращения к боту изменено на ({args[1]}) для этого чата.'
            bot.send_message(message.chat.id, msg, reply_markup=get_keyboard('hide'))
            my_log.log_echo(message, msg)
        else:
            msg = f"Неправильное имя, можно только русские и английские буквы и цифры после букв, \
не больше 10 всего. Имена {', '.join(BAD_NAMES) if BAD_NAMES else ''} уже заняты."
            bot.reply_to(message, msg, reply_markup=get_keyboard('hide'))
            my_log.log_echo(message, msg)
    else:
        help = f"Напишите новое имя бота и я поменяю его, только русские и английские буквы и цифры после букв, \
не больше 10 всего. Имена {', '.join(BAD_NAMES) if BAD_NAMES else ''} уже заняты."
        global COMMAND_MODE
        COMMAND_MODE[message.chat.id] = 'name'
        bot.reply_to(message, help, parse_mode='Markdown', reply_markup=get_keyboard('command_mode'))


@bot.message_handler(commands=['start'])
def send_welcome_start(message: telebot.types.Message):
    # Отправляем приветственное сообщение

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)

    help = """Я - ваш персональный чат-бот, готовый помочь вам в любое время суток. Моя задача - помочь вам получить необходимую информацию и решить возникающие проблемы. 

Я умею обрабатывать и анализировать большие объемы данных, быстро находить нужную информацию и предоставлять ее в удобном для вас формате. 

Если у вас есть какие-то вопросы или проблемы, не стесняйтесь обращаться к чат-боту! Я готов помочь вам в любое время и в любой ситуации. 

Спасибо, что выбрали меня в качестве своего помощника! Я буду стараться быть максимально полезным для вас.

Добавьте меня в свою группу и я буду озвучивать голосовые сообщения, переводить иностранные сообщения итп."""
    bot.send_message(message.chat.id, help, parse_mode='Markdown', disable_web_page_preview=True, reply_markup=get_keyboard('start'))
    my_log.log_echo(message, help)


@bot.message_handler(commands=['help'])
def send_welcome_help(message: telebot.types.Message):
    # Отправляем приветственное сообщение

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)

    help = """Чат бот отзывается на кодовое слово ***бот***(можно сменить командой /name) ***бот расскажи про биткоин***

В привате можно не писать имя для обращения к боту

Если бот перестал отвечать то возможно надо почистить ему память командой ***бот забудь*** или ***забудь***

Кодовое слово ***гугл***(нельзя изменить) позволит получить более актуальную информацию, бот будет гуглить перед ответом ***гугл курс биткоин***

Кодовое слово ***утка***(нельзя изменить) позволит получить более актуальную информацию, бот будет искать в DuckDuckGo перед ответом ***утка курс биткоин***

Кодовое слово ***бинг***(нельзя изменить) позволит получить более актуальную информацию, бот будет дооолго гуглить перед ответом ***бинг курс биткоин***

Кодовое слово ***нарисуй*** и дальше описание даст картинки сгенерированные по описанию. В чате надо добавлять к этому обращение ***бот нарисуй на заборе неприличное слово***

В чате бот будет автоматически переводить иностранные тексты на русский и распознавать голосовые сообщения, отключить это можно кодовым словом ***бот замолчи***, включить обратно ***бот вернись***

Если отправить текстовый файл в приват или с подписью ***прочитай*** то попытается озвучить его как книгу, ожидает .txt utf8 язык пытается определить автоматически (русский если не получилось)

Если отправить картинку или .pdf с подписью ***прочитай*** то вытащит текст из них.

Если отправить ссылку в приват то попытается прочитать текст из неё и выдать краткое содержание.

Если отправить текстовый файл или пдф с подписью ***что там*** или ***перескажи*** то выдаст краткое содержание.

Команды и запросы можно делать голосовыми сообщениями, если отправить голосовое сообщение которое начинается на кодовое слово то бот отработает его как текстовую команду.

""" + '\n'.join(open('commands.txt').readlines()) + '\n\n⚙️ https://github.com/theurs/tb1\n\n💬 https://t.me/theurs'

    bot.send_message(message.chat.id, help, parse_mode='Markdown', disable_web_page_preview=True, reply_markup=get_keyboard('hide'))
    my_log.log_echo(message, help)


@bot.message_handler(commands=['bardmode'])
def bard_mode(message: telebot.types.Message):

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)

    global BARD_MODE

    chat_id = message.chat.id

    mode = 'off'
    if chat_id in BARD_MODE:
        mode = BARD_MODE[chat_id]

    if mode == 'off': mode = 'on'
    else: mode = 'off'

    BARD_MODE[chat_id] = mode

    msg = f'Режим диалога с BARD AI {mode}'

    bot.reply_to(message, msg, parse_mode='Markdown', disable_web_page_preview=True, reply_markup=get_keyboard('hide'))

    my_log.log_echo(message, msg)


@bot.message_handler(commands=['bingmode'])
def bing_mode(message: telebot.types.Message):

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)

    global BING_MODE

    chat_id = message.chat.id

    mode = 'off'
    if chat_id in BING_MODE:
        mode = BING_MODE[chat_id]

    if mode == 'off': mode = 'on'
    else: mode = 'off'

    BING_MODE[chat_id] = mode

    msg = f'Режим диалога с BING AI {mode}'

    bot.reply_to(message, msg, parse_mode='Markdown', disable_web_page_preview=True, reply_markup=get_keyboard('hide'))

    my_log.log_echo(message, msg)


def send_long_message(chat_id: int, resp: str, parse_mode:str = None, disable_web_page_preview: bool = None,
                      reply_markup: telebot.types.InlineKeyboardMarkup = None):
    """отправляем сообщение, если оно слишком длинное то разбивает на 2 части либо отправляем как текстовый файл"""
    if len(resp) < 20000:
        chunks = utils.split_text(resp, 3500)
        counter = len(chunks)
        for chunk in chunks:
            try:
                bot.send_message(chat_id, chunk, parse_mode=parse_mode, disable_web_page_preview=disable_web_page_preview, reply_markup=reply_markup)
            except Exception as e:
                print(e)
                bot.send_message(chat_id, chunk, parse_mode='', disable_web_page_preview=disable_web_page_preview, reply_markup=reply_markup)
            counter -= 1
            if counter < 0:
                break
            time.sleep(2)
    else:
        buf = io.BytesIO()
        buf.write(resp.encode())
        buf.seek(0)
        bot.send_document(chat_id, document=buf, caption='resp.txt', visible_file_name = 'resp.txt')


def reply_to_long_message(message: telebot.types.Message, resp: str, parse_mode: str = None,
                          disable_web_page_preview: bool = None, reply_markup: telebot.types.InlineKeyboardMarkup = None):
    """отправляем сообщение, если оно слишком длинное то разбивает на 2 части либо отправляем как текстовый файл"""
    if len(resp) < 20000:
        chunks = utils.split_text(resp, 3500)
        counter = len(chunks)
        for chunk in chunks:
            try:
                bot.reply_to(message, chunk, parse_mode=parse_mode, disable_web_page_preview=disable_web_page_preview, reply_markup=reply_markup)
            except Exception as e:
                print(e)
                bot.reply_to(message, chunk, parse_mode='', disable_web_page_preview=disable_web_page_preview, reply_markup=reply_markup)
            counter -= 1
            if counter < 0:
                break
            time.sleep(2)
    else:
        buf = io.BytesIO()
        buf.write(resp.encode())
        buf.seek(0)
        bot.send_document(message.chat.id, document=buf, caption='resp.txt', visible_file_name = 'resp.txt')


@bot.message_handler(func=lambda message: True)
def echo_all(message: telebot.types.Message, custom_prompt: str = '') -> None:
    """Обработчик текстовых сообщений"""
    thread = threading.Thread(target=do_task, args=(message, custom_prompt))
    thread.start()
def do_task(message, custom_prompt: str = ''):
    """функция обработчик сообщений работающая в отдельном потоке"""

    if message.text in ['🎨Нарисуй', '🌐Найди', '📋Перескажи', '🎧Озвучь', '🈶Переведи', '⚙️Настройки']:
        if message.text == '🎨Нарисуй':
            message.text = '/image'
            image( message)
        if message.text == '🌐Найди':
            message.text = '/google'
            google(message)
        if message.text == '📋Перескажи':
            message.text = '/sum'
            summ_text(message)
        if message.text == '🎧Озвучь':
            message.text = '/tts'
            tts(message)
        if message.text == '🈶Переведи':
            message.text = '/trans'
            trans(message)
        if message.text == '⚙️Настройки':
            message.text = '/config'
            config(message)
        return

    if custom_prompt:
        message.text = custom_prompt

    # не обрабатывать неизвестные команды
    if message.text.startswith('/'): return

    with semaphore_talks:

        my_log.log_echo(message)

        # определяем откуда пришло сообщение  
        is_private = message.chat.type == 'private'
        # является ли это ответом на наше сообщение
        is_reply = message.reply_to_message is not None and message.reply_to_message.from_user.id == bot.get_me().id
        # id куда писать ответ
        chat_id = message.chat.id

        # удаляем пробелы в конце каждой строки
        message.text = "\n".join([line.rstrip() for line in message.text.split("\n")])

        msg = message.text.lower()

        global BLOCKS, BOT_NAMES, CHAT_LOGS, DIALOGS_DB, BING_MODE, BARD_MODE, COMMAND_MODE

        # если предварительно была введена какая то команда то этот текст надо отправить в неё
        if chat_id in COMMAND_MODE:
            if COMMAND_MODE[chat_id]:
                if COMMAND_MODE[chat_id] == 'image':
                    message.text = f'/image {message.text}'
                    image(message)
                elif COMMAND_MODE[chat_id] == 'tts':
                    message.text = f'/tts {message.text}'
                    tts(message)
                elif COMMAND_MODE[chat_id] == 'trans':
                    message.text = f'/trans {message.text}'
                    trans(message)
                elif COMMAND_MODE[chat_id] == 'google':
                    message.text = f'/google {message.text}'
                    google(message)
                elif COMMAND_MODE[chat_id] == 'ddg':
                    message.text = f'/ddg {message.text}'
                    ddg(message)
                elif COMMAND_MODE[chat_id] == 'name':
                    message.text = f'/name {message.text}'
                    send_name(message)
                elif COMMAND_MODE[chat_id] == 'style':
                    message.text = f'/style {message.text}'
                    change_mode(message)
                elif COMMAND_MODE[chat_id] == 'last':
                    message.text = f'/last {message.text}'
                    last(message)
                elif COMMAND_MODE[chat_id] == 'sum':
                    message.text = f'/sum {message.text}'
                    summ_text(message)
                COMMAND_MODE[chat_id] = ''
                return

        # если мы в чате то добавляем новое сообщение в историю чата для суммаризации с помощью бинга
        if not is_private:
            #time_now = datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')
            time_now = datetime.datetime.now().strftime('%H:%M')
            user_name = message.from_user.first_name or message.from_user.username or 'unknown'
            if chat_id in CHAT_LOGS:
                m = CHAT_LOGS[chat_id]
            else:
                m = utils.MessageList()
            m.append(f'[{time_now}] [{user_name}] {message.text}')
            CHAT_LOGS[chat_id] = m
    
        # определяем какое имя у бота в этом чате, на какое слово он отзывается
        if chat_id in BOT_NAMES:
            bot_name = BOT_NAMES[chat_id]
        else:
            bot_name = BOT_NAME_DEFAULT
            BOT_NAMES[chat_id] = bot_name 
        # если сообщение начинается на 'заткнись или замолчи' то ставим блокировку на канал и выходим
        if ((msg.startswith(('замолчи', 'заткнись')) and (is_private or is_reply))) or msg.startswith((f'{bot_name} замолчи', f'{bot_name}, замолчи')) or msg.startswith((f'{bot_name}, заткнись', f'{bot_name} заткнись')):
            BLOCKS[chat_id] = 1
            bot.send_message(chat_id, 'Автоперевод выключен', parse_mode='Markdown', reply_markup=get_keyboard('hide'))
            my_log.log_echo(message, 'Включена блокировка автопереводов в чате')
            return
        # если сообщение начинается на 'вернись' то снимаем блокировку на канал и выходим
        if (msg.startswith('вернись') and (is_private or is_reply)) or msg.startswith((f'{bot_name} вернись', f'{bot_name}, вернись')):
            BLOCKS[chat_id] = 0
            bot.send_message(chat_id, 'Автоперевод включен', parse_mode='Markdown', reply_markup=get_keyboard('hide'))
            my_log.log_echo(message, 'Выключена блокировка автопереводов в чате')
            return
        # если сообщение начинается на 'забудь' то стираем историю общения GPT
        if (msg.startswith('забудь') and (is_private or is_reply)) or msg.startswith((f'{bot_name} забудь', f'{bot_name}, забудь')):
            if chat_id in BARD_MODE and BARD_MODE[chat_id] == 'on':
                my_bard.reset_bard_chat(chat_id)
                my_log.log_echo(message, 'История барда принудительно отчищена')
            elif chat_id in BING_MODE and BING_MODE[chat_id] == 'on':
                my_bing.reset_bing_chat(chat_id)
                my_log.log_echo(message, 'История бинга принудительно отчищена')
            else:
                DIALOGS_DB[chat_id] = []
                my_log.log_echo(message, 'История GPT принудительно отчищена')
            bot.send_message(chat_id, 'Ок', parse_mode='Markdown', reply_markup=get_keyboard('hide'))
            return

        # если в сообщении только ссылка и она отправлена боту в приват
        # тогда сумморизируем текст из неё
        if my_sum.is_valid_url(message.text) and is_private:
            message.text = '/sum ' + message.text
            summ_text(message)
            return

        # определяем нужно ли реагировать. надо реагировать если сообщение начинается на 'бот ' или 'бот,' в любом регистре
        # проверяем просят ли нарисовать что-нибудь
        if is_private:
            if msg.startswith(('нарисуй ', 'нарисуй,')):
                prompt = msg[8:]
                if prompt:
                    message.text = f'/image {prompt}'
                    image_thread(message)
                    n = [{'role':'system', 'content':f'user попросил нарисовать\n{prompt}'}, {'role':'system', 'content':'assistant нарисовал с помощью DALL-E'}]
                    if chat_id in DIALOGS_DB:
                        DIALOGS_DB[chat_id] += n
                    else:
                        DIALOGS_DB[chat_id] = n
                    return
        regex = fr'^(бинг|{bot_name})\,?\s+нарисуй\s+(.+)$'
        match = re.match(regex, msg, re.DOTALL)
        if match:
            prompt = match.group(2)
            message.text = f'/image {prompt}'
            image_thread(message)
            return

        # можно перенаправить запрос к бингу, но он долго отвечает
        if msg.startswith(('бинг ', 'бинг,', 'бинг\n')):
            # message.text = message.text[len(f'бинг '):] # убираем из запроса кодовое слово
            if len(msg) > cfg.max_message_from_user:
                bot.reply_to(message, f'Слишком длинное сообщение чат-для бота: {len(msg)} из {cfg.max_message_from_user}')
                my_log.log_echo(message, f'Слишком длинное сообщение чат-для бота: {len(msg)} из {cfg.max_message_from_user}')
                return
            with ShowAction(chat_id, 'typing'):
                # добавляем новый запрос пользователя в историю диалога пользователя
                resp = dialog_add_user_request(chat_id, message.text[5:], 'bing')
                if resp:
                    try:
                        bot.reply_to(message, resp, parse_mode='Markdown', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                    except Exception as error:
                        print(error)
                        my_log.log2(resp)
                        bot.reply_to(message, resp, disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                    my_log.log_echo(message, resp)

        # можно перенаправить запрос к гуглу, но он долго отвечает
        elif msg.startswith(('гугл ', 'гугл,', 'гугл\n')):
            message.text = f'/google {msg[5:]}'
            google(message)
            return

        # можно перенаправить запрос к DuckDuckGo, но он долго отвечает
        elif msg.startswith(('утка ', 'утка,', 'утка\n')):
            message.text = f'/ddg {msg[5:]}'
            ddg(message)
            return

        # так же надо реагировать если это ответ в чате на наше сообщение или диалог происходит в привате
        elif msg.startswith((f'{bot_name} ', f'{bot_name},', f'{bot_name}\n')) or is_reply or is_private:
            if len(msg) > cfg.max_message_from_user:
                bot.reply_to(message, f'Слишком длинное сообщение чат-для бота: {len(msg)} из {cfg.max_message_from_user}')
                my_log.log_echo(message, f'Слишком длинное сообщение чат-для бота: {len(msg)} из {cfg.max_message_from_user}')
                return
            if msg.startswith((f'{bot_name} ', f'{bot_name},', f'{bot_name}\n')):
                message.text = message.text[len(f'{bot_name} '):] # убираем из запроса кодовое слово

            # если активирован режим общения с бинг чатом
            if chat_id in BING_MODE and BING_MODE[chat_id] == 'on':
                with ShowAction(chat_id, 'typing'):
                    try:
                        answer = bingai.chat(message.text, chat_id)
                        if answer:
                            messages_left = str(answer['messages_left'])
                            text = f"{answer['text']}\n\n{messages_left}/30"
                            try:
                                reply_to_long_message(message, text, parse_mode='Markdown', disable_web_page_preview = True, reply_markup=get_keyboard('bing_chat'))
                            except Exception as error:
                                print(error)
                                reply_to_long_message(message, text, parse_mode='', disable_web_page_preview = True, reply_markup=get_keyboard('bing_chat'))
                            if int(messages_left) == 1:
                                bingai.reset_bing_chat(chat_id)
                            my_log.log_echo(message, answer['text'])
                    except Exception as error:
                        print(error)
                    return

            # по умолчанию всех в барда
            if chat_id not in BARD_MODE:
                BARD_MODE[chat_id] = 'on'

            # если активирован режим общения с бинг чатом
            if chat_id in BARD_MODE and BARD_MODE[chat_id] == 'on':
                if len(msg) > my_bard.MAX_REQUEST:
                    bot.reply_to(message, f'Слишком длинное сообщение для барда: {len(msg)} из {my_bard.MAX_REQUEST}')
                    my_log.log_echo(message, f'Слишком длинное сообщение для барда: {len(msg)} из {my_bard.MAX_REQUEST}')
                    return
                with ShowAction(chat_id, 'typing'):
                    try:
                        answer = my_bard.chat(message.text, chat_id)
                        if answer:
                            try:
                                reply_to_long_message(message, answer, parse_mode='Markdown', disable_web_page_preview = True, reply_markup=get_keyboard('bard_chat'))
                            except Exception as error:
                                print(error)
                                reply_to_long_message(message, answer, parse_mode='', disable_web_page_preview = True, reply_markup=get_keyboard('bard_chat'))
                            my_log.log_echo(message, answer)
                    except Exception as error:
                        print(error)
                        my_log.log2(str(error))
                    return

            # добавляем новый запрос пользователя в историю диалога пользователя
            with ShowAction(chat_id, 'typing'):
                resp = dialog_add_user_request(chat_id, message.text, 'gpt')
                if resp:
                    if is_private:
                        try:
                            send_long_message(chat_id, resp, parse_mode='Markdown', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                        except Exception as error2:    
                            print(error2)
                            my_log.log2(resp)
                            send_long_message(chat_id, resp, parse_mode='', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                    else:
                        try:
                            reply_to_long_message(message, resp, parse_mode='Markdown', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                        except Exception as error2:    
                            print(error2)
                            my_log.log2(resp)
                            reply_to_long_message(message, resp, parse_mode='', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                    my_log.log_echo(message, resp)
        else: # смотрим надо ли переводить текст
            if check_blocks(message.chat.id):
                return
            text = my_trans.translate(message.text)
            if text:
                bot.reply_to(message, text, parse_mode='Markdown', reply_markup=get_keyboard('translate'))
                my_log.log_echo(message, text)


def set_default_commands():
    """
    Reads a file containing a list of commands and their descriptions,
    and sets the default commands for the bot.
    """
    commands = []
    with open('commands.txt', encoding='utf-8') as file:
        for line in file:
            try:
                command, description = line[1:].strip().split(' - ', 1)
                if command and description:
                    commands.append(telebot.types.BotCommand(command, description))
            except Exception as error:
                print(error)
    bot.set_my_commands(commands)


def main():
    """
    Runs the main function, which sets default commands and starts polling the bot.
    """
    set_default_commands()
    bot.polling()


if __name__ == '__main__':
    main()
