#!/usr/bin/env python3

import io
import json
import os
import random
import re
import tempfile
import datetime
import string
import threading
import time

import PyPDF2
import telebot
from natsort import natsorted
from telebot import apihelper

import cfg
import gpt_basic
import my_bard
import my_claude
import my_genimg
import my_dic
import my_google
import my_gemini
import my_log
import my_ocr
import my_pandoc
import my_perplexity
import my_stt
import my_sum
import my_tiktok
import my_trans
import my_tts
import my_ytb
import utils


# устанавливаем рабочую папку = папке в которой скрипт лежит
os.chdir(os.path.abspath(os.path.dirname(__file__)))

bot = telebot.TeleBot(cfg.token, skip_pending=True)
# if cfg.local_server_url:
#     try:
#         bot.log_out()
#     except Exception as bot_logout_error:
#         my_log.log2(str(bot_logout_error))
#     apihelper.API_URL = cfg.local_server_url
#     bot = telebot.TeleBot(cfg.token, skip_pending=True)

_bot_name = bot.get_me().username
BOT_ID = bot.get_me().id


# телеграм группа для отправки сгенерированных картинок
pics_group = cfg.pics_group
pics_group_url = cfg.pics_group_url

# до 40 одновременных потоков для чата с гпт
semaphore_talks = threading.Semaphore(40)

# папка для постоянных словарей, памяти бота
if not os.path.exists('db'):
    os.mkdir('db')


# хранилище пар ytb_id:ytb_title
# YTB_DB = {}
YTB_DB = my_dic.PersistentDict('db/ytb.pkl')
# хранилище пар ytb_id:message_id
YTB_CACHE = my_dic.PersistentDict('db/ytb_cache.pkl')
YTB_CACHE_FROM = my_dic.PersistentDict('db/ytb_cache_from.pkl')

# заблокированные юзера {id:True/False}
BAD_USERS = my_dic.PersistentDict('db/bad_users.pkl')

# в каких чатах какой чатбот отвечает {chat_id_full(str):chatbot(str)}
# 'bard', 'claude', 'chatgpt'
CHAT_MODE = my_dic.PersistentDict('db/chat_mode.pkl')

# в каких чатах выключены автопереводы. 0 - выключено, 1 - включено
BLOCKS = my_dic.PersistentDict('db/blocks.pkl')

# каким голосом озвучивать, мужским или женским
TTS_GENDER = my_dic.PersistentDict('db/tts_gender.pkl')

# запоминаем промпты для повторения рисования
IMAGE_PROMPTS = my_dic.PersistentDict('db/image_prompts.pkl')

# запоминаем у какого юзера какой язык OCR выбран
OCR_DB = my_dic.PersistentDict('db/ocr_db.pkl')

# для запоминания ответов на команду /sum
SUM_CACHE = my_dic.PersistentDict('db/sum_cache.pkl')

# в каких чатах активирован режим суперчата, когда бот отвечает на все реплики всех участников
# {chat_id:0|1}
SUPER_CHAT = my_dic.PersistentDict('db/super_chat.pkl')

# в каких чатах какая команда дана, как обрабатывать последующий текст
# например после команды /image ожидаем описание картинки
# COMMAND_MODE[chat_id] = 'google'|'image'|...
COMMAND_MODE = {}

# в каких чатах включен режим только голосовые сообщения {'chat_id_full':True/False}
VOICE_ONLY_MODE = my_dic.PersistentDict('db/voice_only_mode.pkl')

# в каких чатах отключена клавиатура {'chat_id_full':True/False}
DISABLED_KBD = my_dic.PersistentDict('db/disabled_kbd.pkl')

# автоматически заблокированные за слишком частые обращения к боту 
# {user_id:Time to release in seconds - дата когда можно выпускать из бана} 
DDOS_BLOCKED_USERS = my_dic.PersistentDict('db/ddos_blocked_users.pkl')

# кешировать запросы типа кто звонил {number:result}
CACHE_CHECK_PHONE = {}

# {user_id:lang(2 symbol codes)}
LANGUAGE_DB = my_dic.PersistentDict('db/language_db.pkl')

# хранилище для переводов сообщений сделанных гугл переводчиком
# key: (text, lang)
# value: translated text
AUTO_TRANSLATIONS = my_dic.PersistentDict('db/auto_translations.pkl')

# замок для выполнения дампа переводов
DUMP_TRANSLATION_LOCK = threading.Lock()

# запоминаем прилетающие сообщения, если они слишком длинные и
# были отправлены клеинтом по кускам {id:[messages]}
# ловим сообщение и ждем полсекунды не прилетит ли еще кусок
MESSAGE_QUEUE = {}

# в каких чатах какое у бота кодовое слово для обращения к боту
BOT_NAMES = my_dic.PersistentDict('db/names.pkl')
# имя бота по умолчанию, в нижнем регистре без пробелов и символов
BOT_NAME_DEFAULT = cfg.default_bot_name


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

MSG_CONFIG = f"""***Панель управления***

Тут можно:

- стереть память боту

- переключить чат с chatGPT на Google Bard, Claude AI

- изменить голос

- выключить авто переводы иностранных текстов на канале и перевод голосовых сообщений в текст

Настройки стиля /style и история /mem ***относятся только к chatGPT***
У Google Bard и Claude AI есть свои особенные правила, которые не могут быть изменены."""

class RequestCounter:
    """Ограничитель числа запросов к боту
    не дает делать больше 10 в минуту, банит на сутки после превышения"""
    def __init__(self):
        self.counts = {}

    def check_limit(self, user_id):
        """Возвращает True если лимит не превышен, False если превышен или юзер уже забанен"""
        current_time = time.time()

        if user_id in DDOS_BLOCKED_USERS:
            if DDOS_BLOCKED_USERS[user_id] > current_time:
                return False
            else:
                del DDOS_BLOCKED_USERS[user_id]

        if user_id not in self.counts:
            self.counts[user_id] = [current_time]
            return True
        else:
            timestamps = self.counts[user_id]
            # Удаляем старые временные метки, которые находятся за пределами 1 минуты
            timestamps = [timestamp for timestamp in timestamps if timestamp >= current_time - 60]
            if len(timestamps) < cfg.DDOS_MAX_PER_MINUTE:
                timestamps.append(current_time)
                self.counts[user_id] = timestamps
                return True
            else:
                DDOS_BLOCKED_USERS[user_id] = current_time + cfg.DDOS_BAN_TIME
                my_log.log2(f'tb:request_counter:check_limit: user blocked {user_id}')
                return False


request_counter = RequestCounter()


class ShowAction(threading.Thread):
    """Поток который можно остановить. Беспрерывно отправляет в чат уведомление об активности.
    Телеграм автоматически гасит уведомление через 5 секунд, по-этому его надо повторять.

    Использовать в коде надо как то так
    with ShowAction(message, 'typing'):
        делаем что-нибудь и пока делаем уведомление не гаснет
    """
    def __init__(self, message, action):
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
        self.chat_id = message.chat.id
        self.thread_id = message.message_thread_id
        self.is_topic = message.is_topic_message
        self.action = action
        self.is_running = True
        self.timerseconds = 1

    def run(self):
        while self.is_running:
            try:
                if self.is_topic:
                    bot.send_chat_action(self.chat_id, self.action, message_thread_id = self.thread_id)
                else:
                    bot.send_chat_action(self.chat_id, self.action)
            except Exception as error:
                my_log.log2(f'tb:show_action:run: {error}')
            n = 50
            while n > 0:
                time.sleep(0.1)
                n = n - self.timerseconds

    def stop(self):
        self.timerseconds = 50
        self.is_running = False
        try:
            bot.send_chat_action(self.chat_id, 'cancel', message_thread_id = self.thread_id)
        except Exception as error:
            my_log.log2(f'tb:show_action: {error}')

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


def tr(text: str, lang: str) -> str:
    """
    Translates the given text into the specified language.

    Args:
        text (str): The text to be translated.
        lang (str): The target language for translation.

    Returns:
        str: The translated text. If the target language is 'ru' (Russian), the original text is returned.

    Note:
        The translation is performed using the `my_trans.translate_text2` function.

    """
    # на русский не переводим
    # lang = lang.lower()
    # if lang == 'ru':
    #     return text

    key = str((text, lang))
    if key in AUTO_TRANSLATIONS:
        return AUTO_TRANSLATIONS[key]
    translated = my_trans.translate_text2(text, lang)
    if translated:
        AUTO_TRANSLATIONS[key] = translated
    else:
        AUTO_TRANSLATIONS[key] = text
    return AUTO_TRANSLATIONS[key]


@bot.message_handler(commands=['fixlang'])
def fix_translation_with_gpt(message: telebot.types.Message):
    thread = threading.Thread(target=fix_translation_with_gpt_thread, args=(message,))
    thread.start()
def fix_translation_with_gpt_thread(message: telebot.types.Message):
    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    chat_full_id = get_topic_id(message)
    user_lang = get_lang(chat_full_id, message)

    if message.from_user.id not in cfg.admins:
        bot.reply_to(message, tr("Эта команда доступна только администраторам",
                                 user_lang))
        return

    target_lang = message.text.split()[1]

    bot.reply_to(message, tr(f'Started translation process, please wait for a while', user_lang))
    counter = 0
    for key in AUTO_TRANSLATIONS.keys():
        text, lang = eval(key)[0], eval(key)[1]
        if lang == target_lang:
            if 'The chatbot responds to the name' in text or "Hello! I'm your personal multi-functional assistant" in text:
                translated_text = gpt_basic.translate_instruct(text, target_lang)
                # translated_text = my_trans.translate_text2(text, target_lang)
                AUTO_TRANSLATIONS[key] = translated_text
                counter += 1
                my_log.log2(f'{key} -> {translated_text}')
                time.sleep(5)

    bot.reply_to(message, tr(f'Переведено {counter} строк', user_lang))


def get_lang(id: str, message: telebot.types.Message = None) -> str:
    """
    Returns the language corresponding to the given ID.
    
    Args:
        id (str): The ID of the language.
        message (telebot.types.Message, optional): The message object. Defaults to None.
    
    Returns:
        str: The language corresponding to the given ID. If the ID is not found in the LANGUAGE_DB, 
             the language corresponding to the user in the message object will be stored in the LANGUAGE_DB
             and returned. If the message object is not provided or the user does not have a language code,
             the default language (cfg.DEFAULT_LANGUAGE) will be returned.
    """
    if id in LANGUAGE_DB:
        return LANGUAGE_DB[id]
    else:
        if message:
            LANGUAGE_DB[id] = message.from_user.language_code or cfg.DEFAULT_LANGUAGE
            return LANGUAGE_DB[id]
        return cfg.DEFAULT_LANGUAGE


def get_ocr_language(message) -> str:
    """Возвращает настройки языка OCR для этого чата"""
    chat_id_full = get_topic_id(message)

    if chat_id_full in OCR_DB:
        lang = OCR_DB[chat_id_full]
    else:
        try:
            OCR_DB[chat_id_full] = cfg.ocr_language
        except:
            OCR_DB[chat_id_full] = 'rus+eng'
        lang = OCR_DB[chat_id_full]
    return lang


def get_topic_id(message: telebot.types.Message) -> str:
    """
    Get the topic ID from a Telegram message.

    Parameters:
        message (telebot.types.Message): The Telegram message object.

    Returns:
        str: '[chat.id] [topic.id]'
    """

    chat_id = message.chat.id
    topic_id = 0

    if message.reply_to_message and message.reply_to_message.is_topic_message:
        topic_id = message.reply_to_message.message_thread_id
    elif message.is_topic_message:
        topic_id = message.message_thread_id

    return f'[{chat_id}] [{topic_id}]'


def is_admin_member(message: telebot.types.Message):
    """Checks if the user is an admin member of the chat."""
    if not message:
        return False
    chat_id = message.chat.id
    user_id = message.from_user.id
    member = bot.get_chat_member(chat_id, user_id).status.lower()
    return True if 'creator' in member or 'administrator' in member else False


def disabled_kbd(chat_id_full):
    """проверяет не отключена ли тут клавиатура"""
    if chat_id_full not in DISABLED_KBD:
        DISABLED_KBD[chat_id_full] = True
    return DISABLED_KBD[chat_id_full]


def get_keyboard(kbd: str, message: telebot.types.Message, flag: str = '', payload = None) -> telebot.types.InlineKeyboardMarkup:
    """создает и возвращает клавиатуру по текстовому описанию
    'chat' - клавиатура для чата
    'mem' - клавиатура для команды mem, с кнопками Забудь и Скрой
    'hide' - клавиатура с одной кнопкой Скрой
    ...
    payload - данные для клавиатуры
    """
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    if kbd == 'chat':
        if disabled_kbd(chat_id_full):
            return None
        markup  = telebot.types.InlineKeyboardMarkup(row_width=5)
        button1 = telebot.types.InlineKeyboardButton("➡", callback_data='continue_gpt')
        button2 = telebot.types.InlineKeyboardButton("♻️", callback_data='forget_all')
        button3 = telebot.types.InlineKeyboardButton("🙈", callback_data='erase_answer')
        button4 = telebot.types.InlineKeyboardButton("📢", callback_data='tts')
        button5 = telebot.types.InlineKeyboardButton(lang, callback_data='translate_chat')
        markup.add(button1, button2, button3, button4, button5)
        return markup
    elif kbd == 'mem':
        if disabled_kbd(chat_id_full):
            return None
        markup  = telebot.types.InlineKeyboardMarkup()
        button1 = telebot.types.InlineKeyboardButton(tr("Стереть историю", lang), callback_data='clear_history')
        button2 = telebot.types.InlineKeyboardButton(tr("Скрыть", lang), callback_data='erase_answer')
        markup.add(button1, button2)
        return markup
    elif kbd == 'hide':
        if disabled_kbd(chat_id_full):
            return None
        markup  = telebot.types.InlineKeyboardMarkup()
        button1 = telebot.types.InlineKeyboardButton(tr("Скрыть", lang), callback_data='erase_answer')
        markup.add(button1)
        return markup
    elif kbd == 'command_mode':
        markup  = telebot.types.InlineKeyboardMarkup()
        button1 = telebot.types.InlineKeyboardButton(tr("Отмена", lang), callback_data='cancel_command')
        markup.add(button1)
        return markup
    elif kbd == 'ytb':
        markup  = telebot.types.InlineKeyboardMarkup(row_width=1)
        for b in payload:
            button = telebot.types.InlineKeyboardButton(f'{b[0]} [{b[1]}]', callback_data=f'youtube {b[2]}')
            YTB_DB[b[2]] = b[0]
            markup.add(button)
        button2 = telebot.types.InlineKeyboardButton(tr("Скрыть", lang), callback_data='erase_answer')
        markup.add(button2)
        return markup
    elif kbd == 'perplexity':
        markup  = telebot.types.InlineKeyboardMarkup(row_width=4)
        button1 = telebot.types.InlineKeyboardButton("🙈", callback_data='erase_answer')
        button2 = telebot.types.InlineKeyboardButton("📢", callback_data='tts')
        button3 = telebot.types.InlineKeyboardButton(lang, callback_data='translate_perplexity')
        button4 = telebot.types.InlineKeyboardButton(tr("⛔️Выход", lang), callback_data='cancel_command_not_hide')
        markup.row(button1, button2, button3, button4)
        return markup       
    elif kbd == 'translate_and_repair':
        if disabled_kbd(chat_id_full):
            return None
        markup  = telebot.types.InlineKeyboardMarkup(row_width=4)
        button1 = telebot.types.InlineKeyboardButton("🙈", callback_data='erase_answer')
        button2 = telebot.types.InlineKeyboardButton("📢", callback_data='tts')
        button3 = telebot.types.InlineKeyboardButton(lang, callback_data='translate')
        button4 = telebot.types.InlineKeyboardButton(tr("✨Исправить✨", lang), callback_data='voice_repair')
        markup.row(button1, button2, button3)
        markup.row(button4)
        return markup
    elif kbd == 'translate':
        if disabled_kbd(chat_id_full):
            return None
        markup  = telebot.types.InlineKeyboardMarkup()
        button1 = telebot.types.InlineKeyboardButton(tr("Скрыть", lang), callback_data='erase_answer')
        button2 = telebot.types.InlineKeyboardButton("📢", callback_data='tts')
        button3 = telebot.types.InlineKeyboardButton(tr("Перевод", lang), callback_data='translate')
        markup.add(button1, button2, button3)
        return markup
    elif kbd == 'download_tiktok':
        markup  = telebot.types.InlineKeyboardMarkup()
        button1 = telebot.types.InlineKeyboardButton(tr("Скачать видео", lang),
                                                     callback_data='download_tiktok')
        button2 = telebot.types.InlineKeyboardButton(tr("Отмена", lang),
                                                     callback_data='erase_answer')
        markup.add(button1, button2)
        return markup
    elif kbd == 'hide_image':
        markup  = telebot.types.InlineKeyboardMarkup()
        button1 = telebot.types.InlineKeyboardButton(tr("Скрыть", lang), callback_data='erase_image')
        button2 = telebot.types.InlineKeyboardButton(tr("Повторить", lang), callback_data='repeat_image')
        markup.add(button1, button2)
        return markup
    elif kbd == 'start':
        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
        button1 = telebot.types.KeyboardButton(tr('🎨 Нарисуй', lang))
        button2 = telebot.types.KeyboardButton(tr('🌐 Найди', lang))
        button3 = telebot.types.KeyboardButton(tr('📋 Перескажи', lang))
        button4 = telebot.types.KeyboardButton(tr('🎧 Озвучь', lang))
        button5 = telebot.types.KeyboardButton(tr('🈶 Перевод', lang))
        button6 = telebot.types.KeyboardButton(tr('⚙️ Настройки', lang))
        markup.row(button1, button2, button3)
        markup.row(button4, button5, button6)
        return markup
    elif kbd == 'claude_chat':
        if disabled_kbd(chat_id_full):
            return None
        markup  = telebot.types.InlineKeyboardMarkup(row_width=5)
        button0 = telebot.types.InlineKeyboardButton("➡", callback_data='continue_gpt')
        button1 = telebot.types.InlineKeyboardButton('♻️', callback_data='claudeAI_reset')
        button2 = telebot.types.InlineKeyboardButton("🙈", callback_data='erase_answer')
        button3 = telebot.types.InlineKeyboardButton("📢", callback_data='tts')
        button4 = telebot.types.InlineKeyboardButton(lang, callback_data='translate_chat')
        markup.add(button0, button1, button2, button3, button4)
        return markup
    elif kbd == 'bard_chat':
        if disabled_kbd(chat_id_full):
            return None
        markup  = telebot.types.InlineKeyboardMarkup(row_width=5)
        button0 = telebot.types.InlineKeyboardButton("➡", callback_data='continue_gpt')
        button1 = telebot.types.InlineKeyboardButton('♻️', callback_data='bardAI_reset')
        button2 = telebot.types.InlineKeyboardButton("🙈", callback_data='erase_answer')
        button3 = telebot.types.InlineKeyboardButton("📢", callback_data='tts')
        button4 = telebot.types.InlineKeyboardButton(lang, callback_data='translate_chat')
        markup.add(button0, button1, button2, button3, button4)
        return markup
    elif kbd == 'gemini_chat':
        if disabled_kbd(chat_id_full):
            return None
        markup  = telebot.types.InlineKeyboardMarkup(row_width=5)
        button0 = telebot.types.InlineKeyboardButton("➡", callback_data='continue_gpt')
        button1 = telebot.types.InlineKeyboardButton('♻️', callback_data='gemini_reset')
        button2 = telebot.types.InlineKeyboardButton("🙈", callback_data='erase_answer')
        button3 = telebot.types.InlineKeyboardButton("📢", callback_data='tts')
        button4 = telebot.types.InlineKeyboardButton(lang, callback_data='translate_chat')
        markup.add(button0, button1, button2, button3, button4)
        return markup
    elif kbd == 'config':
        if chat_id_full in TTS_GENDER:
            voice = f'tts_{TTS_GENDER[chat_id_full]}'
        else:
            voice = 'tts_female'

        voices = {'tts_female': tr('MS жен.', lang),
                  'tts_male': tr('MS муж.', lang),
                  'tts_google_female': 'Google',
                  'tts_female_ynd': tr('Ynd жен.', lang),
                  'tts_male_ynd': tr('Ynd муж.', lang),
                  'tts_openai_alloy': 'Alloy',
                  'tts_openai_echo': 'Echo',
                  'tts_openai_fable': 'Fable',
                  'tts_openai_onyx': 'Onyx',
                  'tts_openai_nova': 'Nova',
                  'tts_openai_shimmer': 'Shimmer',
                  }
        voice_title = voices[voice]

        # кто по умолчанию
        if chat_id_full not in CHAT_MODE:
            CHAT_MODE[chat_id_full] = cfg.chat_mode_default

        markup  = telebot.types.InlineKeyboardMarkup(row_width=1)

        if CHAT_MODE[chat_id_full] == 'chatgpt':
            button1 = telebot.types.InlineKeyboardButton('✅ChatGPT', callback_data='chatGPT_mode_disable')
        else:
            button1 = telebot.types.InlineKeyboardButton('☑️ChatGPT', callback_data='chatGPT_mode_enable')
        button2 = telebot.types.InlineKeyboardButton(tr('❌Стереть', lang), callback_data='chatGPT_reset')
        markup.row(button1, button2)

        if CHAT_MODE[chat_id_full] == 'bard':
            button1 = telebot.types.InlineKeyboardButton('✅Bard AI', callback_data='bard_mode_disable')
        else:
            button1 = telebot.types.InlineKeyboardButton('☑️Bard AI', callback_data='bard_mode_enable')

        button2 = telebot.types.InlineKeyboardButton(tr('❌Стереть', lang), callback_data='bardAI_reset')
        markup.row(button1, button2)

        if CHAT_MODE[chat_id_full] == 'claude':
            button1 = telebot.types.InlineKeyboardButton('✅Claude AI', callback_data='claude_mode_disable')
        else:
            button1 = telebot.types.InlineKeyboardButton('☑️Claude AI', callback_data='claude_mode_enable')

        button2 = telebot.types.InlineKeyboardButton(tr('❌Стереть', lang), callback_data='claudeAI_reset')
        markup.row(button1, button2)

        if CHAT_MODE[chat_id_full] == 'gemini':
            button1 = telebot.types.InlineKeyboardButton('✅Gemini Pro', callback_data='gemini_mode_disable')
        else:
            button1 = telebot.types.InlineKeyboardButton('☑️Gemini Pro', callback_data='gemini_mode_enable')

        button2 = telebot.types.InlineKeyboardButton(tr('❌Стереть', lang), callback_data='gemini_reset')
        markup.row(button1, button2)

        button1 = telebot.types.InlineKeyboardButton(tr(f'📢Голос: {voice_title}', lang), callback_data=voice)
        if chat_id_full not in VOICE_ONLY_MODE:
            VOICE_ONLY_MODE[chat_id_full] = False
        if VOICE_ONLY_MODE[chat_id_full]:
            button2 = telebot.types.InlineKeyboardButton(tr('✅Только голос', lang), callback_data='voice_only_mode_disable')
        else:
            button2 = telebot.types.InlineKeyboardButton(tr('☑️Только голос', lang), callback_data='voice_only_mode_enable')
        markup.row(button1, button2)

        if chat_id_full not in BLOCKS:
            BLOCKS[chat_id_full] = 0

        if BLOCKS[chat_id_full] == 1:
            button1 = telebot.types.InlineKeyboardButton(tr(f'✅Авто переводы', lang), callback_data='autotranslate_disable')
        else:
            button1 = telebot.types.InlineKeyboardButton(tr(f'☑️Авто переводы', lang), callback_data='autotranslate_enable')
        if chat_id_full not in DISABLED_KBD:
            DISABLED_KBD[chat_id_full] = False
        if DISABLED_KBD[chat_id_full]:
            button2 = telebot.types.InlineKeyboardButton(tr(f'☑️Чат-кнопки', lang), callback_data='disable_chat_kbd')
        else:
            button2 = telebot.types.InlineKeyboardButton(tr(f'✅Чат-кнопки', lang), callback_data='enable_chat_kbd')
        markup.row(button1, button2)

        if cfg.pics_group_url:
            button_pics = telebot.types.InlineKeyboardButton(tr("🖼️Галерея", lang),  url = cfg.pics_group_url)
            markup.add(button_pics)

        button = telebot.types.InlineKeyboardButton(tr('🔍История ChatGPT', lang), callback_data='chatGPT_memory_debug')
        markup.add(button)

        is_admin_of_group = False
        if message.reply_to_message:
            is_admin_of_group = is_admin_member(message.reply_to_message)
            from_user = message.reply_to_message.from_user.id
        else:
            from_user = message.from_user.id
            is_admin_of_group = is_admin_member(message)

        if flag == 'admin' or is_admin_of_group or from_user in cfg.admins:
            if chat_id_full not in SUPER_CHAT:
                SUPER_CHAT[chat_id_full] = 0
            if SUPER_CHAT[chat_id_full] == 1:
                button = telebot.types.InlineKeyboardButton(tr('✅Автоответы в чате', lang), callback_data='admin_chat')
            else:
                button = telebot.types.InlineKeyboardButton(tr('☑️Автоответы в чате', lang), callback_data='admin_chat')
            markup.add(button)

        button = telebot.types.InlineKeyboardButton(tr('🙈Закрыть меню', lang), callback_data='erase_answer')
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
        message = call.message
        chat_id = message.chat.id
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)
        # check_blocked_user(chat_id_full)

        if call.data == 'clear_history':
            # обработка нажатия кнопки "Стереть историю"
            if CHAT_MODE[chat_id_full] == 'chatgpt':
                gpt_basic.chat_reset(chat_id_full)
            elif CHAT_MODE[chat_id_full] == 'gemini':
                my_gemini.reset(chat_id_full)
            bot.delete_message(message.chat.id, message.message_id)
        elif call.data == 'continue_gpt':
            # обработка нажатия кнопки "Продолжай GPT"
            message.dont_check_topic = True
            echo_all(message, tr('Продолжай', lang))
            return
        elif call.data == 'forget_all':
            # обработка нажатия кнопки "Забудь всё"
            gpt_basic.chat_reset(chat_id_full)
        elif call.data == 'cancel_command':
            # обработка нажатия кнопки "Отменить ввод команды"
            COMMAND_MODE[chat_id_full] = ''
            bot.delete_message(message.chat.id, message.message_id)
        elif call.data == 'cancel_command_not_hide':
            # обработка нажатия кнопки "Отменить ввод команды, но не скрывать"
            COMMAND_MODE[chat_id_full] = ''
            # bot.delete_message(message.chat.id, message.message_id)
            bot.reply_to(message, tr('Режим поиска в гугле отключен', lang))
        # режим автоответов в чате, бот отвечает на все реплики всех участников
        # комната для разговоров с ботом Ж)
        elif call.data == 'admin_chat':
            #bot.reply_to(message, 'Автоответы в чате активированы, бот будет отвечать на все реплики всех участников')
            if chat_id_full in SUPER_CHAT:
                SUPER_CHAT[chat_id_full] = 1 if SUPER_CHAT[chat_id_full] == 0 else 0
            else:
                SUPER_CHAT[chat_id_full] = 1
            bot.edit_message_text(chat_id=chat_id, parse_mode='Markdown', message_id=message.message_id,
                                  text = tr(MSG_CONFIG, lang), reply_markup=get_keyboard('config', message, 'admin'))
        elif call.data == 'erase_answer':
            # обработка нажатия кнопки "Стереть ответ"
            bot.delete_message(message.chat.id, message.message_id)
        elif call.data == 'tts':
            llang = my_trans.detect_lang(message.text) or lang
            message.text = f'/tts {llang} {message.text}'
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
                p_id = int(i)
                break
            p = IMAGE_PROMPTS[p_id]
            message.text = f'/image {p}'
            # рисуем еще картинки с тем же запросом
            image(message)
        elif call.data == 'voice_repair':
            # реакция на клавиатуру для исправить текст после распознавания
            with ShowAction(message, 'typing'):
                translated = my_bard.bard_clear_text_chunk_voice(message.text)
            if translated and translated != message.text:
                bot.edit_message_text(chat_id=message.chat.id, message_id=message.message_id, text=translated,
                                      reply_markup=get_keyboard('translate', message))
                # bot.reply_to(message, translated, reply_markup=get_keyboard('translate', message))
        elif call.data == 'download_tiktok':
            # реакция на клавиатуру для tiktok
            with ShowAction(message, 'upload_video'):
                tmp = my_tiktok.download_video(message.text)
                try:
                    bot.send_video(chat_id=message.chat.id, video=open(tmp, 'rb'),
                                   reply_markup=get_keyboard('hide', message))
                except Exception as bot_send_tiktok_video_error:
                    my_log.log2(f'tb:callback_inline_thread:download_tiktok:{bot_send_tiktok_video_error}')
                try:
                    os.unlink(tmp)
                except Exception as unlink_error:
                    my_log.log2(f'tb:callback_inline_thread:download_tiktok:{unlink_error}\n\nunlink {tmp}')
        elif call.data.startswith('youtube '):
            song_id = call.data[8:]
            caption = YTB_DB[song_id]
            thumb = f'https://img.youtube.com/vi/{song_id}/maxresdefault.jpg'
            with ShowAction(message, 'upload_audio'):
                my_log.log_echo(message, f'Start sending youtube {song_id} {caption}')
                if song_id in YTB_CACHE:
                    try:
                        bot.copy_message(chat_id=message.chat.id,
                                         from_chat_id=YTB_CACHE_FROM[song_id],
                                         message_id = YTB_CACHE[song_id],
                                         reply_to_message_id = message.message_id,
                                         reply_markup = get_keyboard('hide', message),
                                         disable_notification=True)
                        my_log.log_echo(message, f'Finish sending youtube {song_id} {caption}')
                        return
                    except Exception as copy_message_error:
                        my_log.log2(f'tb:callback_inline_thread:ytb:copy_message:{copy_message_error}')
                data = my_ytb.download_youtube(song_id)
                try:
                    m = bot.send_audio(chat_id=message.chat.id, audio=data,
                                        reply_to_message_id = message.message_id,
                                        reply_markup = get_keyboard('hide', message),
                                        caption = caption,
                                        title = caption,
                                        thumbnail=thumb,
                                        disable_notification=True)
                    YTB_CACHE[song_id] = m.message_id
                    YTB_CACHE_FROM[song_id] = m.chat.id
                    my_log.log_echo(message, f'Finish sending youtube {song_id} {caption}')
                except Exception as send_ytb_error:
                    my_log.log2(str(send_ytb_error))
                    err_msg = tr('Не удалось отправить музыку.', lang) + '\n' + str(send_ytb_error)
                    my_log.log_echo(message, err_msg)
                    bot.reply_to(message, err_msg, reply_markup=get_keyboard('hide', message))
        elif call.data == 'translate':
            # реакция на клавиатуру для OCR кнопка перевести текст
            with ShowAction(message, 'typing'):
                translated = my_trans.translate_text2(message.text, lang)
            if translated and translated != message.text:
                bot.edit_message_text(chat_id=message.chat.id, message_id=message.message_id, text=translated, 
                                      reply_markup=get_keyboard('translate', message))
        elif call.data == 'translate_perplexity':
            # реакция на клавиатуру для OCR кнопка перевести текст
            with ShowAction(message, 'typing'):
                translated = my_trans.translate_text2(message.text, lang)
            if translated and translated != message.text:
                bot.edit_message_text(chat_id=message.chat.id, message_id=message.message_id, text=translated, 
                                      reply_markup=get_keyboard('perplexity', message))
        elif call.data == 'translate_chat':
            # реакция на клавиатуру для Чата кнопка перевести текст
            with ShowAction(message, 'typing'):
                translated = my_trans.translate_text2(message.text, lang)
            if translated and translated != message.text:
                bot.edit_message_text(chat_id=message.chat.id, message_id=message.message_id, text=translated, 
                                      reply_markup=get_keyboard('chat', message))
        elif call.data == 'bardAI_reset':
            my_bard.reset_bard_chat(chat_id_full)
            msg = tr('История диалога с Google Bard отчищена.', lang)
            bot.reply_to(message, msg, reply_markup=get_keyboard('hide', message))
            my_log.log_echo(message, msg)
        elif call.data == 'gemini_reset':
            my_gemini.reset(chat_id_full)
            msg = tr('История диалога с Gemini Pro отчищена.', lang)
            bot.reply_to(message, msg, reply_markup=get_keyboard('hide', message))
            my_log.log_echo(message, msg)
        elif call.data == 'claudeAI_reset':
            my_claude.reset_claude_chat(chat_id_full)
            msg = tr('История диалога с Claude AI отчищена.', lang)
            bot.reply_to(message, msg, reply_markup=get_keyboard('hide', message))
            my_log.log_echo(message, msg)
        elif call.data == 'chatGPT_reset':
            gpt_basic.chat_reset(chat_id_full)
            msg = tr('История диалога с chatGPT отчищена.', lang)
            bot.reply_to(message, msg, reply_markup=get_keyboard('hide', message))
            my_log.log_echo(message, msg)
        elif call.data == 'tts_female':
            TTS_GENDER[chat_id_full] = 'male'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, 
                                  text = tr(MSG_CONFIG, lang), reply_markup=get_keyboard('config', message))
        elif call.data == 'tts_male':
            TTS_GENDER[chat_id_full] = 'google_female'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, 
                                  text = tr(MSG_CONFIG, lang), reply_markup=get_keyboard('config', message))
        elif call.data == 'tts_google_female':
            TTS_GENDER[chat_id_full] = 'male_ynd'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, 
                                  text = tr(MSG_CONFIG, lang), reply_markup=get_keyboard('config', message))

        elif call.data == 'tts_male_ynd':
            TTS_GENDER[chat_id_full] = 'female_ynd'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, 
                                  text = tr(MSG_CONFIG, lang), reply_markup=get_keyboard('config', message))
        elif call.data == 'tts_female_ynd':
            TTS_GENDER[chat_id_full] = 'openai_alloy'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, 
                                  text = tr(MSG_CONFIG, lang), reply_markup=get_keyboard('config', message))

        elif call.data == 'tts_openai_alloy':
            TTS_GENDER[chat_id_full] = 'openai_echo'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, 
                                  text = tr(MSG_CONFIG, lang), reply_markup=get_keyboard('config', message))
        elif call.data == 'tts_openai_echo':
            TTS_GENDER[chat_id_full] = 'openai_fable'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, 
                                  text = tr(MSG_CONFIG, lang), reply_markup=get_keyboard('config', message))
        elif call.data == 'tts_openai_fable':
            TTS_GENDER[chat_id_full] = 'openai_onyx'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, 
                                  text = tr(MSG_CONFIG, lang), reply_markup=get_keyboard('config', message))
        elif call.data == 'tts_openai_onyx':
            TTS_GENDER[chat_id_full] = 'openai_nova'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, 
                                  text = tr(MSG_CONFIG, lang), reply_markup=get_keyboard('config', message))
        elif call.data == 'tts_openai_nova':
            TTS_GENDER[chat_id_full] = 'openai_shimmer'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, 
                                  text = tr(MSG_CONFIG, lang), reply_markup=get_keyboard('config', message))
        elif call.data == 'tts_openai_shimmer':
            TTS_GENDER[chat_id_full] = 'female'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, 
                                  text = tr(MSG_CONFIG, lang), reply_markup=get_keyboard('config', message))

        elif call.data == 'voice_only_mode_disable':
            VOICE_ONLY_MODE[chat_id_full] = False
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, 
                                  text = tr(MSG_CONFIG, lang), reply_markup=get_keyboard('config', message))
        elif call.data == 'voice_only_mode_enable':
            VOICE_ONLY_MODE[chat_id_full] = True
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, 
                                  text = tr(MSG_CONFIG, lang), reply_markup=get_keyboard('config', message))
        elif call.data == 'chatGPT_mode_disable':
            del CHAT_MODE[chat_id_full]
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, 
                                  text = tr(MSG_CONFIG, lang), reply_markup=get_keyboard('config', message))
        elif call.data == 'chatGPT_mode_enable':
            CHAT_MODE[chat_id_full] = 'chatgpt'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, 
                                  text = tr(MSG_CONFIG, lang), reply_markup=get_keyboard('config', message))
        elif call.data == 'bard_mode_enable':
            CHAT_MODE[chat_id_full] = 'bard'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, 
                                  text = tr(MSG_CONFIG, lang), reply_markup=get_keyboard('config', message))
        elif call.data == 'bard_mode_disable':
            del CHAT_MODE[chat_id_full]
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, 
                                  text = tr(MSG_CONFIG, lang), reply_markup=get_keyboard('config', message))
        elif call.data == 'claude_mode_enable':
            CHAT_MODE[chat_id_full] = 'claude'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, 
                                  text = tr(MSG_CONFIG, lang), reply_markup=get_keyboard('config', message))
        elif call.data == 'claude_mode_disable':
            del CHAT_MODE[chat_id_full]
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, 
                                  text = tr(MSG_CONFIG, lang), reply_markup=get_keyboard('config', message))
        elif call.data == 'gemini_mode_enable':
            CHAT_MODE[chat_id_full] = 'gemini'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, 
                                  text = tr(MSG_CONFIG, lang), reply_markup=get_keyboard('config', message))
        elif call.data == 'claude_mode_disable':
            del CHAT_MODE[chat_id_full]
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, 
                                  text = tr(MSG_CONFIG, lang), reply_markup=get_keyboard('config', message))
        elif call.data == 'autotranslate_disable':
            BLOCKS[chat_id_full] = 0
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, 
                                  text = tr(MSG_CONFIG, lang), reply_markup=get_keyboard('config', message))
        elif call.data == 'autotranslate_enable':
            BLOCKS[chat_id_full] = 1
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, 
                                  text = tr(MSG_CONFIG, lang), reply_markup=get_keyboard('config', message))
        elif call.data == 'chatGPT_memory_debug':
            send_debug_history(message)
        elif call.data == 'disable_chat_kbd':
            DISABLED_KBD[chat_id_full] = False
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, 
                                  text = tr(MSG_CONFIG, lang), reply_markup=get_keyboard('config', message))
        elif call.data == 'enable_chat_kbd':
            DISABLED_KBD[chat_id_full] = True
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='Markdown', message_id=message.message_id, 
                                  text = tr(MSG_CONFIG, lang), reply_markup=get_keyboard('config', message))


def check_blocks(chat_id: str) -> bool:
    """в каких чатах выключены автопереводы"""
    if chat_id not in BLOCKS:
        BLOCKS[chat_id] = 0
    return False if BLOCKS[chat_id] == 1 else True


@bot.message_handler(content_types = ['voice', 'audio'])
def handle_voice(message: telebot.types.Message): 
    """Автоматическое распознавание текст из голосовых сообщений"""
    thread = threading.Thread(target=handle_voice_thread, args=(message,))
    thread.start()
def handle_voice_thread(message: telebot.types.Message):
    """Автоматическое распознавание текст из голосовых сообщений и аудио файлов"""

    my_log.log_media(message)

    is_private = message.chat.type == 'private'
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    check_blocked_user(chat_id_full)
    if chat_id_full not in SUPER_CHAT:
        SUPER_CHAT[chat_id_full] = 0
    if SUPER_CHAT[chat_id_full] == 1:
        is_private = True

    if check_blocks(get_topic_id(message)) and not is_private:
        return

    with semaphore_talks:
        # Создание временного файла 
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            file_path = temp_file.name + '.ogg'
        # Скачиваем аудиофайл во временный файл
        try:
            file_info = bot.get_file(message.voice.file_id)
        except AttributeError:
            try:
                file_info = bot.get_file(message.audio.file_id)
            except AttributeError:
                file_info = bot.get_file(message.document.file_id)
            
        downloaded_file = bot.download_file(file_info.file_path)
        with open(file_path, 'wb') as new_file:
            new_file.write(downloaded_file)

        # Распознаем текст из аудио
        if chat_id_full in VOICE_ONLY_MODE and VOICE_ONLY_MODE[chat_id_full]:
            action = 'record_audio'
        else:
            action = 'typing'
        with ShowAction(message, action):
            text = my_stt.stt(file_path, lang)

            try:
                os.remove(file_path)
            except Exception as remove_file_error:
                my_log.log2(f'tb:handle_voice_thread:remove_file_error: {remove_file_error}\n\nfile_path')

            text = text.strip()
            # Отправляем распознанный текст
            if text:
                if VOICE_ONLY_MODE[chat_id_full]:
                    # в этом режиме не показываем распознанный текст а просто отвечаем на него голосом
                    pass
                else:
                    reply_to_long_message(message, text, reply_markup=get_keyboard('translate', message))
                    my_log.log_echo(message, f'[ASR] {text}')
            else:
                if VOICE_ONLY_MODE[chat_id_full]:
                    message.text = '/tts ' + tr('Не удалось распознать текст', lang)
                    tts(message)
                else:
                    bot.reply_to(message, tr('Не удалось распознать текст', lang), reply_markup=get_keyboard('hide', message))
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

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    is_private = message.chat.type == 'private'
    if chat_id_full not in SUPER_CHAT:
        SUPER_CHAT[chat_id_full] = 0
    if SUPER_CHAT[chat_id_full] == 1:
        is_private = True

    chat_id = message.chat.id

    if check_blocks(chat_id_full) and not is_private:
        return

    file_info = bot.get_file(message.document.file_id)
    if file_info.file_path.lower().endswith('.wav'):
        handle_voice(message)
        return

    with semaphore_talks:
        # если прислали файл с исправленными переводами
        if 'AUTO_TRANSLATIONS' in message.document.file_name and '.json' in message.document.file_name:
            if message.from_user.id in cfg.admins:
                try:
                    # file_info = bot.get_file(message.document.file_id)
                    file = bot.download_file(file_info.file_path)
                    with open('AUTO_TRANSLATIONS.json', 'wb') as new_file:
                        new_file.write(file)
                    global AUTO_TRANSLATIONS
                    with open('AUTO_TRANSLATIONS.json', 'r', encoding='utf-8') as f:
                        a = json.load(f)
                        for key, value in a.items():
                            AUTO_TRANSLATIONS[key] = value
                    try:
                        os.remove('AUTO_TRANSLATIONS.json')
                    except Exception as error:
                        print(f'tb:handle_document_thread: {error}')
                        my_log.log2(f'tb:handle_document_thread: {error}')

                    bot.reply_to(message, tr('Переводы загружены', lang))
                except Exception as error:
                    print(f'tb:handle_document_thread: {error}')
                    my_log.log2(f'tb:handle_document_thread: {error}')
                    msg = tr('Не удалось принять файл автопереводов ' + str(error), lang)
                    bot.reply_to(message, msg)
                    my_log.log2(msg)
                    return
                return
        # если в режиме клауда чата то закидываем файл прямо в него
        if chat_id_full in CHAT_MODE and CHAT_MODE[chat_id_full] == 'claude':
            check_blocked_user(chat_id_full)
            with ShowAction(message, 'typing'):
                file_name = message.document.file_name
                # file_info = bot.get_file(message.document.file_id)
                file = bot.download_file(file_info.file_path)
                # сгенерировать случайное имя папки во временной папке для этого файла
                folder_name = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(10))
                # создать эту папку во временной папке. как получить путь до временной папки в системе?
                folder_path = os.path.join(tempfile.gettempdir(), folder_name)
                os.mkdir(folder_path)
                # сохранить файл в этой папке
                if file_name.endswith(('.pdf', '.txt')):
                    full_path = os.path.join(folder_path, file_name)
                    with open(full_path, 'wb') as new_file:
                        new_file.write(file)
                else:
                    file_name += '.txt'
                    text = my_pandoc.fb2_to_text(file)
                    full_path = os.path.join(folder_path, file_name)
                    with open(full_path, 'w', encoding='utf-8') as new_file:
                        new_file.write(text)
                caption = message.caption or '?'
                message.text = f'[File uploaded for Claude] [{file_name}] ' + caption
                my_log.log_echo(message)
                try:
                    response = my_claude.chat(caption, chat_id_full, False, full_path)
                    response = utils.bot_markdown_to_html(response)
                except Exception as error:
                    print(f'tb:handle_document_thread:claude: {error}')
                    my_log.log2(f'tb:handle_document_thread:claude: {error}')
                    msg = tr('Не удалось отправить файл', lang)
                    bot.reply_to(message, msg)
                    my_log.log2(msg)
                    os.remove(full_path)
                    os.rmdir(folder_path)
                    return
                # удалить сначала файл а потом и эту папку
                os.remove(full_path)
                os.rmdir(folder_path)
                my_log.log_echo(message, response)
                reply_to_long_message(message, response, parse_mode='HTML', reply_markup=get_keyboard('claude_chat', message))
            return

        # если прислали текстовый файл или pdf с подписью перескажи
        # то скачиваем и вытаскиваем из них текст и показываем краткое содержание
        if message.caption \
        and message.caption.startswith((tr('что там', lang),tr('перескажи', lang),tr('краткое содержание', lang), tr('кратко', lang))) \
        and message.document.mime_type in ('text/plain', 'application/pdf'):
            check_blocked_user(chat_id_full)
            with ShowAction(message, 'typing'):
                # file_info = bot.get_file(message.document.file_id)
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
                    reply_to_long_message(message, summary, parse_mode='',
                                          disable_web_page_preview = True,
                                          reply_markup=get_keyboard('translate', message))
                    my_log.log_echo(message, summary)
                else:
                    help = tr('Не удалось получить никакого текста из документа.', lang)
                    bot.reply_to(message, help, reply_markup=get_keyboard('hide', message))
                    my_log.log_echo(message, help)
                return

        # дальше идет попытка распознать ПДФ или jpg файл, вытащить текст с изображений
        if is_private or caption.lower() in [tr('прочитай', lang), tr('прочитать', lang)]:
            check_blocked_user(chat_id_full)
            with ShowAction(message, 'upload_document'):
                # получаем самый большой документ из списка
                document = message.document
                # если документ не является PDF-файлом или изображением jpg png, отправляем сообщение об ошибке
                if document.mime_type in ('image/jpeg', 'image/png'):
                    with ShowAction(message, 'typing'):
                        # скачиваем документ в байтовый поток
                        file_id = message.document.file_id
                        file_info = bot.get_file(file_id)
                        file_name = message.document.file_name + '.jpg'
                        file = bot.download_file(file_info.file_path)
                        fp = io.BytesIO(file)
                        # распознаем текст на фотографии с помощью pytesseract
                        text = my_ocr.get_text_from_image(fp.read(), get_ocr_language(message))
                        # отправляем распознанный текст пользователю
                        if text.strip() != '':
                            reply_to_long_message(message, text, parse_mode='',
                                                  reply_markup=get_keyboard('translate', message),
                                                  disable_web_page_preview = True)
                            my_log.log_echo(message, '[OCR] ' + text)
                        else:
                            reply_to_long_message(message, tr('Не смог распознать текст.', lang),
                                                  reply_markup=get_keyboard('translate', message))
                            my_log.log_echo(message, '[OCR] no results')
                    return
                if document.mime_type != 'application/pdf':
                    bot.reply_to(message, f'{tr("Это не PDF-файл.", lang)} {document.mime_type}',
                                 reply_markup=get_keyboard('hide', message))
                    my_log.log_echo(message, f'Это не PDF-файл. {document.mime_type}')
                    return
                # скачиваем документ в байтовый поток
                file_id = message.document.file_id
                file_info = bot.get_file(file_id)
                file_name = message.document.file_name + '.txt'
                file = bot.download_file(file_info.file_path)
                fp = io.BytesIO(file)

                # распознаем текст в документе с помощью функции get_text
                text = my_ocr.get_text(fp, get_ocr_language(message))
                # отправляем распознанный текст пользователю
                if text.strip() != '':
                    # если текст слишком длинный, отправляем его в виде текстового файла
                    if len(text) > 4096:
                        with io.StringIO(text) as f:
                            if not is_private:
                                bot.send_document(chat_id, document = f, visible_file_name = file_name, caption=file_name, 
                                                  reply_to_message_id = message.message_id, reply_markup=get_keyboard('hide', message))
                            else:
                                bot.send_document(chat_id, document = f, visible_file_name = file_name, caption=file_name, 
                                                  reply_markup=get_keyboard('hide', message))
                    else:
                        bot.reply_to(message, text, reply_markup=get_keyboard('translate', message))
                    my_log.log_echo(message, f'[распознанный из PDF текст] {text}')


@bot.message_handler(content_types = ['photo'])
def handle_photo(message: telebot.types.Message):
    """Обработчик фотографий. Сюда же попадают новости которые создаются как фотография + много текста в подписи, и пересланные сообщения в том числе"""
    thread = threading.Thread(target=handle_photo_thread, args=(message,))
    thread.start()
def handle_photo_thread(message: telebot.types.Message):
    """Обработчик фотографий. Сюда же попадают новости которые создаются как фотография
    + много текста в подписи, и пересланные сообщения в том числе"""

    my_log.log_media(message)

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    is_private = message.chat.type == 'private'
    if chat_id_full not in SUPER_CHAT:
        SUPER_CHAT[chat_id_full] = 0
    if SUPER_CHAT[chat_id_full] == 1:
        is_private = True

    msglower = message.caption.lower() if message.caption else ''

    if (tr('что', lang) in msglower and len(msglower) < 30) or msglower == '':
        state = 'describe'
    elif 'ocr' in msglower or tr('прочитай', lang) in msglower or tr('читай', lang) in msglower:
        state = 'ocr'
    else:
        state = 'translate'

    # выключены ли автопереводы
    if check_blocks(get_topic_id(message)):
        if not is_private:
            if state == 'translate':
                return

    with semaphore_talks:
        # распознаем что на картинке с помощью гугл барда
        if state == 'describe' and (is_private or tr('что', lang) in msglower):
            with ShowAction(message, 'typing'):
                photo = message.photo[-1]
                file_info = bot.get_file(photo.file_id)
                image = bot.download_file(file_info.file_path)
                # caption = tr('Опиши что нарисовано на картинке, дай краткое но ёмкое описание изображения, так что бы человек понял что здесь изображено. В ответе не используй тавтологию на изображении изображено, не пиши ничего про эту инструкцию.', lang)
                caption = tr('Что на картинке, подробное описание и объяснение?', lang)
                result = my_gemini.img2txt(image, caption)
                if not result:
                    result = my_bard.chat_image(caption, chat_id_full, image)
                result = utils.bot_markdown_to_html(result)
                reply_to_long_message(message, result, parse_mode='HTML',
                                        reply_markup=get_keyboard('translate', message))
                my_log.log_echo(message, result)
            return
        elif state == 'ocr':
            with ShowAction(message, 'typing'):
                check_blocked_user(chat_id_full)
                # получаем самую большую фотографию из списка
                photo = message.photo[-1]
                fp = io.BytesIO()
                # скачиваем фотографию в байтовый поток
                file_info = bot.get_file(photo.file_id)
                downloaded_file = bot.download_file(file_info.file_path)
                fp.write(downloaded_file)
                fp.seek(0)
                # распознаем текст на фотографии с помощью pytesseract
                text = my_ocr.get_text_from_image(fp.read(), get_ocr_language(message))
                # отправляем распознанный текст пользователю
                if text.strip() != '':
                    reply_to_long_message(message, text, parse_mode='',
                                        reply_markup=get_keyboard('translate', message),
                                        disable_web_page_preview = True)
                    my_log.log_echo(message, '[OCR] ' + text)
                else:
                    my_log.log_echo(message, '[OCR] no results')
                    bot.reply_to(message, tr('[OCR] no results', lang), reply_markup=get_keyboard('hide', message))
            return
        elif state == 'translate':
            # пересланные сообщения пытаемся перевести даже если в них картинка
            # новости в телеграме часто делают как картинка + длинная подпись к ней
            if message.forward_from_chat and message.caption:
                # у фотографий нет текста но есть заголовок caption. его и будем переводить
                check_blocked_user(chat_id_full)
                with ShowAction(message, 'typing'):
                    text = my_trans.translate(message.caption)
                if text:
                    bot.reply_to(message, text, reply_markup=get_keyboard('hide', message))
                    my_log.log_echo(message, text)
                else:
                    my_log.log_echo(message, "Не удалось/понадобилось перевести.")
                return


@bot.message_handler(content_types = ['video', 'video_note'])
def handle_video(message: telebot.types.Message):
    """Обработчик видеосообщений. Сюда же относятся новости и репосты с видео"""
    thread = threading.Thread(target=handle_video_thread, args=(message,))
    thread.start()
def handle_video_thread(message: telebot.types.Message):
    """Обработчик видеосообщений. Сюда же относятся новости и репосты с видео"""

    my_log.log_media(message)

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    is_private = message.chat.type == 'private'
    if chat_id_full not in SUPER_CHAT:
        SUPER_CHAT[chat_id_full] = 0
    if SUPER_CHAT[chat_id_full] == 1:
        is_private = True

    if check_blocks(get_topic_id(message)) and not is_private:
        return

    with semaphore_talks:
        # пересланные сообщения пытаемся перевести даже если в них видео
        if message.forward_from_chat:
            check_blocked_user(chat_id_full)
            # у видео нет текста но есть заголовок caption. его и будем переводить
            text = my_trans.translate(message.caption)
            if text:
                bot.reply_to(message, text, reply_markup=get_keyboard('hide', message))
                my_log.log_echo(message, text)
            else:
                my_log.log_echo(message, "Не удалось/понадобилось перевести.")

    with semaphore_talks:
        with ShowAction(message, 'typing'):
            check_blocked_user(chat_id_full)
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
            text = my_stt.stt(file_path, lang)
            os.remove(file_path)
            # Отправляем распознанный текст
            if text:
                reply_to_long_message(message, text, reply_markup=get_keyboard('translate', message))
                my_log.log_echo(message, f'[ASR] {text}')
            else:
                bot.reply_to(message, tr('Не удалось распознать текст', lang),
                             reply_markup=get_keyboard('hide', message))
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
    try:
        if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
        else: return
    except Exception as error:
        my_log.log2(f'config:{error}')

    my_log.log_echo(message)

    chat_full_id = get_topic_id(message)
    lang = get_lang(chat_full_id, message)

    try:
        bot.reply_to(message, tr(MSG_CONFIG, lang), parse_mode='Markdown', reply_markup=get_keyboard('config', message))
    except Exception as error:
        my_log.log2(f'tb:config:{error}')
        print(error)


@bot.message_handler(commands=['style'])
def change_mode(message: telebot.types.Message):
    """Меняет роль бота, строку с указаниями что и как говорить.
    /stype <1|2|3|свой текст>
    1 - минималистичный стиль (Answer in a super short and objective way.)
    2 - формальный стиль + немного юмора (Ты искусственный интеллект отвечающий на запросы юзера. Отвечай с подходящим к запросу типом иронии или юмора но не перегибай палку.)
    3 - токсичный стиль (Ты искусственный интеллект отвечающий на запросы юзера. Отвечай с сильной иронией и токсичностью.)
    """

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    check_blocked_user(chat_id_full)

    # в каждом чате свой собственный промт
    if chat_id_full not in gpt_basic.PROMPTS:
        # по умолчанию формальный стиль
        gpt_basic.PROMPTS[chat_id_full] = [{"role": "system", "content": tr(utils.gpt_start_message1, lang)}]

    arg = message.text.split(maxsplit=1)[1:]
    if arg:
        if arg[0] == '1':
            new_prompt = tr(utils.gpt_start_message1, lang)
        elif arg[0] == '2':
            new_prompt = tr(utils.gpt_start_message2, lang)
        elif arg[0] == '3':
            new_prompt = tr(utils.gpt_start_message3, lang)
        elif arg[0] == '4':
            new_prompt = tr(utils.gpt_start_message4, lang)
        else:
            new_prompt = arg[0]
        gpt_basic.PROMPTS[chat_id_full] =  [{"role": "system", "content": new_prompt}]
        msg =  f'{tr("[Новая роль установлена]", lang)} `{new_prompt}`\n\n***{tr("Роли работают только с chatGPT, используйте команду /config что бы выбрать chatGPT", lang)}***'
        bot.reply_to(message, msg, parse_mode='Markdown', reply_markup=get_keyboard('hide', message))
        my_log.log_echo(message, msg)
    else:
        msg = f"""{tr('Текущий стиль', lang)}

`{gpt_basic.PROMPTS[chat_id_full][0]['content']}`

{tr('Меняет роль бота, строку с указаниями что и как говорить. Работает только для ChatGPT.', lang)}

***{tr('Роли работают только с chatGPT, используйте команду `/config` что бы выбрать chatGPT', lang)}***

`/style <1|2|3|4|{tr('свой текст', lang)}>`

{tr('1 - формальный стиль', lang)} `{tr(utils.gpt_start_message1, lang)}`

{tr('2 - формальный стиль + немного юмора', lang)} `{tr(utils.gpt_start_message2, lang)}`

{tr('3 - токсичный стиль', lang)} `{tr(utils.gpt_start_message3, lang)}`

{tr('4 - Ева Элфи', lang)} `{tr(utils.gpt_start_message4, lang)}`

{tr('Напишите свой текст или цифру одного из готовых стилей', lang)}
    """
        COMMAND_MODE[chat_id_full] = 'style'
        bot.reply_to(message, msg, parse_mode='Markdown', reply_markup=get_keyboard('command_mode', message))
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
    
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    check_blocked_user(chat_id_full)

    if CHAT_MODE[chat_id_full] == 'bard':
        gpt_basic.CHATS[chat_id_full] = gpt_basic.CHATS[chat_id_full][-cfg.max_hist_lines:]

        # создаем новую историю диалогов с юзером из старой если есть
        messages = []
        if chat_id_full in gpt_basic.CHATS:
            messages = gpt_basic.CHATS[chat_id_full]
        prompt = '\n'.join(f'{i["role"]} - {i["content"]}\n' for i in messages) or tr('Пусто', lang)
    elif CHAT_MODE[chat_id_full] == 'gemini':
        prompt = my_gemini.get_mem_as_string(chat_id_full) or tr('Пусто', lang)
    else:
        return
    my_log.log_echo(message, prompt)
    reply_to_long_message(message, prompt, parse_mode = '', disable_web_page_preview = True, reply_markup=get_keyboard('mem', message))


@bot.message_handler(commands=['restart']) 
def restart(message: telebot.types.Message):
    """остановка бота. после остановки его должен будет перезапустить скрипт systemd"""
    chat_full_id = get_topic_id(message)
    lang = get_lang(chat_full_id, message)
    if message.from_user.id in cfg.admins:
        bot.stop_polling()
    else:
        bot.reply_to(message, tr('Эта команда только для админов.', lang), reply_markup=get_keyboard('hide', message))


@bot.message_handler(commands=['leave']) 
def leave(message: telebot.types.Message):
    """выйти из чата"""
    chat_full_id = get_topic_id(message)
    lang = get_lang(chat_full_id, message)
    if message.from_user.id in cfg.admins:
        chat_id = message.text.split()[1]
        if bot.leave_chat(chat_id):
            bot.reply_to(message, tr('Вы вышли из чата', lang) + f' {chat_id}')
    else:
        bot.reply_to(message, tr('Эта команда только для админов.', lang), reply_markup=get_keyboard('hide', message))


@bot.message_handler(commands=['temperature', 'temp'])
def set_new_temperature(message: telebot.types.Message):
    """меняет температуру для chatGPT
    /temperature <0...2>
    по умолчанию 0 - автоматическая
    чем меньше температура тем менее творчейский ответ, меньше бреда и вранья,
    и желания давать ответ
    """

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    check_blocked_user(chat_id_full)

    if len(message.text.split()) == 2:
        try:
            new_temp = float(message.text.split()[1])
        except ValueError:
            new_temp = -1
    else:
        new_temp = -1

    if new_temp < 0 or new_temp > 2:
        new_temp = -1

    if len(message.text.split()) < 2 or new_temp == -1:
        help = f"""/temperature <0-2>

{tr('''Меняет температуру для chatGPT

Температура у ChatGPT - это параметр, который контролирует степень случайности генерируемого текста. Чем выше температура, тем более случайным и креативным будет текст. Чем ниже температура, тем более точным и сфокусированным будет текст.

Например, если вы хотите, чтобы ChatGPT сгенерировал стихотворение, вы можете установить температуру выше 1,5. Это будет способствовать тому, что ChatGPT будет выбирать более неожиданные и уникальные слова. Однако, если вы хотите, чтобы ChatGPT сгенерировал текст, который является более точным и сфокусированным, вы можете установить температуру ниже 0,5. Это будет способствовать тому, что ChatGPT будет выбирать более вероятные и ожидаемые слова.

По-умолчанию 0 - автоматическая''', lang)}

`/temperature 0.1`
`/temperature 1`
`/temperature 1.9` {tr('На таких высоких значения он пишет один сплошной бред', lang)}
"""
        bot.reply_to(message, help, parse_mode='Markdown', reply_markup=get_keyboard('hide', message))
        return

    gpt_basic.TEMPERATURE[chat_id_full] = new_temp
    bot.reply_to(message, f'{tr("Новая температура для chatGPT установлена:", lang)} {new_temp}',
                 parse_mode='Markdown', reply_markup=get_keyboard('hide', message))


@bot.message_handler(commands=['lang', 'language'])
def language(message: telebot.types.Message):
    """change locale"""

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)

    chat_id_full = get_topic_id(message)
    check_blocked_user(chat_id_full)

    if chat_id_full in LANGUAGE_DB:
        lang = LANGUAGE_DB[chat_id_full]
    else:
        lang = message.from_user.language_code or cfg.DEFAULT_LANGUAGE
        LANGUAGE_DB[chat_id_full] = lang

    supported_langs_trans2 = ', '.join([x for x in supported_langs_trans])
    if len(message.text.split()) < 2:
        msg = f'/lang {tr("двухбуквенный код языка. Меняет язык бота. Ваш язык сейчас: ", lang)} <b>{lang}</b>\n\n{tr("Возможные варианты:", lang)}\n{supported_langs_trans2}\n\n/lang en\n/lang de\n/lang uk\n...'
        bot.reply_to(message, msg, parse_mode='HTML', reply_markup=get_keyboard('hide', message))
        my_log.log_echo(message, msg)
        return

    new_lang = message.text.split(maxsplit=1)[1].strip().lower()
    if new_lang in supported_langs_trans:
        LANGUAGE_DB[chat_id_full] = new_lang
        msg = f'{tr("Язык бота изменен на:", new_lang)} <b>{new_lang}</b>'
        bot.reply_to(message, msg, parse_mode='HTML', reply_markup=get_keyboard('start', message))
        my_log.log_echo(message, msg)
        return
    else:
        msg = f'{tr("Такой язык не поддерживается:", lang)} <b>{new_lang}</b>\n\n{tr("Возможные варианты:", lang)}\n{supported_langs_trans2}'
        bot.reply_to(message, msg, parse_mode='HTML', reply_markup=get_keyboard('hide', message))
        my_log.log_echo(message, msg)
        return


@bot.message_handler(commands=['music', 'mus', 'm'])
def music(message: telebot.types.Message):
    """ищет и скачивает музыку с ютуба"""
    thread = threading.Thread(target=music_thread, args=(message,))
    thread.start()
def music_thread(message: telebot.types.Message):
    """ищет и скачивает музыку с ютуба"""
    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    check_blocked_user(chat_id_full)

    try:
        query = message.text.split(maxsplit=1)[1]
    except:
        query = ''

    my_log.log_echo(message)

    if query:
        with ShowAction(message, 'typing'):
            results = my_ytb.search_youtube(query)
            my_log.log_echo(message, '\n' + '\n'.join([str(x) for x in results]))
            msg = tr('Вот что удалось найти', lang)
            bot.reply_to(message, msg, parse_mode='HTML', reply_markup=get_keyboard('ytb', message, payload = results))
    else:
        with ShowAction(message, 'typing'):
            msg = tr('Usage:', lang) + ' /music <' + tr('song name', lang) + '> - ' + tr('will search for music on youtube', lang) + '\n\n'
            msg += tr('Examples:', lang) + '\n`/music linkin park numb`\n'
            for x in cfg.MUSIC_WORDS:
                msg += '\n`' + x + ' linkin park numb`'
            bot.reply_to(message, msg, parse_mode='markdown', reply_markup=get_keyboard('hide', message))

            results = my_ytb.get_random_songs(10)
            if results:
                my_log.log_echo(message, '\n' + '\n'.join([str(x) for x in results]))
                msg = tr('Случайные песни', lang)
                bot.reply_to(message, msg, parse_mode='HTML', reply_markup=get_keyboard('ytb', message, payload = results))


@bot.message_handler(commands=['model'])
def set_new_model(message: telebot.types.Message):
    """меняет модель для гпт, никаких проверок не делает"""
    thread = threading.Thread(target=set_new_model_thread, args=(message,))
    thread.start()
def set_new_model_thread(message: telebot.types.Message):
    """меняет модель для гпт, никаких проверок не делает"""

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    check_blocked_user(chat_id_full)

    if chat_id_full in gpt_basic.CUSTOM_MODELS:
        current_model = gpt_basic.CUSTOM_MODELS[chat_id_full]
    else:
        current_model = cfg.model

    if len(message.text.split()) < 2:
        available_models = ''
        for m in gpt_basic.get_list_of_models():
            available_models += f'<code>/model {m}</code>\n'
        msg = f"""{tr('Меняет модель для chatGPT.', lang)}

{tr('Выбрано:', lang)} <code>/model {current_model}</code>

{tr('Возможные варианты (на самом деле это просто примеры а реальные варианты зависят от настроек бота, его бекэндов):', lang)}

<code>/model gpt-4</code>
<code>/model gpt-3.5-turbo-16k</code>

{available_models}
"""
        msgs = []
        tmpstr = ''
        for x in msg.split('\n'):
            tmpstr += x + '\n'
            if len(tmpstr) > 3800:
                msgs.append(tmpstr)
                tmpstr = ''
        if len(tmpstr) > 0:
            msgs.append(tmpstr)
        for x in msgs:
            reply_to_long_message(message, x, parse_mode='HTML', reply_markup=get_keyboard('hide', message)) 
            my_log.log_echo(message, x)
        return

    if not (message.from_user.id in cfg.admins or is_admin_member(message)):
       msg = tr('Эта команда только для админов.', lang)
       bot.reply_to(message, msg, reply_markup=get_keyboard('hide', message))
       my_log.log_echo(message, msg)
       return

    model = message.text.split()[1]
    msg0 = f'{tr("Старая модель", lang)} `{current_model}`.'
    msg = f'{tr("Установлена новая модель", lang)} `{model}`.'
    gpt_basic.CUSTOM_MODELS[chat_id_full] = model
    bot.reply_to(message, msg0, parse_mode='Markdown', reply_markup=get_keyboard('hide', message))
    bot.reply_to(message, msg, parse_mode='Markdown', reply_markup=get_keyboard('hide', message))
    my_log.log_echo(message, msg0)
    my_log.log_echo(message, msg)


@bot.message_handler(commands=['tts'])
def tts(message: telebot.types.Message, caption = None):
    thread = threading.Thread(target=tts_thread, args=(message,caption))
    thread.start()
def tts_thread(message: telebot.types.Message, caption = None):
    """ /tts [ru|en|uk|...] [+-XX%] <текст>
        /tts <URL>
    """

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    check_blocked_user(chat_id_full)

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
            reply_to_long_message(message, text, parse_mode='',
                                  reply_markup=get_keyboard('translate', message),
                                      disable_web_page_preview=True)
        return

    # разбираем параметры
    # регулярное выражение для разбора строки
    pattern = r'/tts\s+((?P<lang>' + '|'.join(supported_langs_tts) + r')\s+)?\s*(?P<rate>([+-]\d{1,2}%\s+))?\s*(?P<text>.+)'
    # поиск совпадений с регулярным выражением
    match = re.match(pattern, message.text, re.DOTALL)
    # извлечение параметров из найденных совпадений
    if match:
        llang = match.group("lang") or lang  # если lang не указан, то по умолчанию язык юзера
        rate = match.group("rate") or "+0%"  # если rate не указан, то по умолчанию '+0%'
        text = match.group("text") or ''
    else:
        text = llang = rate = ''
    llang = llang.strip()
    rate = rate.strip()

    if not text or llang not in supported_langs_tts:
        help = f"""{tr('Использование:', lang)} /tts [ru|en|uk|...] [+-XX%] <{tr('текст', lang)}>|<URL>

+-XX% - {tr('ускорение с обязательным указанием направления + или -', lang)}

/tts привет
/tts en hello, let me speak from all my heart
/tts +50% привет со скоростью 1.5х
/tts uk -50% тянем время, говорим по-русски с украинским акцентом :)

{tr('Поддерживаемые языки:', lang)} {', '.join(supported_langs_tts)}

{tr('Напишите что надо произнести, чтобы получить голосовое сообщение', lang)}
"""

        COMMAND_MODE[chat_id_full] = 'tts'
        bot.reply_to(message, help, parse_mode='Markdown', reply_markup=get_keyboard('command_mode', message))
        my_log.log_echo(message, help)
        return

    with semaphore_talks:
        with ShowAction(message, 'record_audio'):
            if chat_id_full in TTS_GENDER:
                gender = TTS_GENDER[chat_id_full]
            else:
                gender = 'female'

            # openai доступен не всем, если недоступен то вместо него используется гугл
            if not allowed_chatGPT_user(message.chat.id):
                gender = 'google_female'
            if 'openai' in gender and len(text) > cfg.MAX_OPENAI_TTS:
                gender = 'google_female'
            
            # яндекс знает только несколько языков и не может больше 2000 символов
            if 'ynd' in gender:
                if len(text) > 1990 or llang not in ['ru', 'en', 'uk', 'he', 'de', 'kk', 'uz']:
                    gender = 'female'

            # микрософт не умеет в латинский язык
            if llang == 'la':
                gender = 'google_female'

            if chat_id_full in VOICE_ONLY_MODE and VOICE_ONLY_MODE[chat_id_full]:
                text = utils.bot_markdown_to_tts(text)
            audio = my_tts.tts(text, llang, rate, gender=gender)
            if audio:
                if message.chat.type != 'private':
                    bot.send_voice(message.chat.id, audio, reply_to_message_id = message.message_id,
                                   reply_markup=get_keyboard('hide', message), caption=caption)
                else:
                    # в привате не надо добавлять клавиатуру с кнопкой для удаления, 
                    # там можно удалить без нее, а случайное удаление ни к чему
                    bot.send_voice(message.chat.id, audio, caption=caption)
                my_log.log_echo(message, '[Отправил голосовое сообщение]')
            else:
                msg = tr('Не удалось озвучить. Возможно вы перепутали язык, например немецкий голос не читает по-русски.', lang)
                if message.chat.type != 'private':
                    bot.reply_to(message, msg, reply_markup=get_keyboard('hide', message))
                else:
                    bot.reply_to(message, msg, reply_markup=get_keyboard('hide', message))
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

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    check_blocked_user(chat_id_full)

    if not allowed_chatGPT_user(message.chat.id):
        my_log.log_echo(message, 'chatGPT запрещен [google]')
        bot.reply_to(message, tr('You are not in allow chatGPT users list', lang))
        return

    try:
        q = message.text.split(maxsplit=1)[1]
    except Exception as error2:
        print(error2)
        help = f"""/google {tr('текст запроса', lang)}

/google {tr('сколько на земле людей, точные цифры и прогноз', lang)}

{tr('гугл, сколько на земле людей, точные цифры и прогноз', lang)}

{tr('Напишите запрос в гугл', lang)}
"""
        COMMAND_MODE[chat_id_full] = 'google'
        bot.reply_to(message, help, parse_mode = 'Markdown', disable_web_page_preview = True, reply_markup=get_keyboard('command_mode', message))
        return

    with ShowAction(message, 'typing'):
        with semaphore_talks:
            r = my_google.search(q, lang)
        try:
            bot.reply_to(message, r, parse_mode = 'Markdown',
                         disable_web_page_preview = True,
                         reply_markup=get_keyboard('chat', message))
        except Exception as error2:
            my_log.log2(error2)
            bot.reply_to(message, r, parse_mode = '', disable_web_page_preview = True,
                         reply_markup=get_keyboard('chat', message))
        my_log.log_echo(message, r)

        if chat_id_full not in gpt_basic.CHATS:
            gpt_basic.CHATS[chat_id_full] = []
        gpt_basic.CHATS[chat_id_full] += [{"role":    'system',
                "content": f'user {tr("попросил сделать запрос в Google:", lang)} {q}'},
                {"role":    'system',
                "content": f'assistant {tr("поискал в Google и ответил:", lang)} {r}'}
            ]
        gpt_basic.CHATS[chat_id_full] = gpt_basic.CHATS[chat_id_full][-cfg.max_hist_lines:]


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

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    check_blocked_user(chat_id_full)

    if not allowed_chatGPT_user(message.chat.id):
        my_log.log_echo(message, 'chatGPT запрещен [ddg]')
        bot.reply_to(message, tr('You are not in allow chatGPT users list', lang))
        return

    try:
        q = message.text.split(maxsplit=1)[1]
    except Exception as error2:
        print(error2)
        help = f"""/ddg {tr('''текст запроса

Будет делать запрос в DuckDuckGo, и потом пытаться найти нужный ответ в результатах

вместо команды''', lang)} /ddg {tr('''можно написать кодовое слово утка в начале

утка, сколько на земле людей, точные цифры и прогноз

Напишите свой запрос в DuckDuckGo''', lang)}
"""

        COMMAND_MODE[chat_id_full] = 'ddg'
        bot.reply_to(message, help, parse_mode = 'Markdown',
                     disable_web_page_preview = True,
                     reply_markup=get_keyboard('command_mode', message))
        return

    with ShowAction(message, 'typing'):
        with semaphore_talks:
            r = my_google.search_ddg(q, lang=lang)
        try:
            bot.reply_to(message, r, parse_mode = 'Markdown',
                         disable_web_page_preview = True,
                         reply_markup=get_keyboard('chat', message))
        except Exception as error2:
            my_log.log2(error2)
            bot.reply_to(message, r, parse_mode = '', disable_web_page_preview = True,
                         reply_markup=get_keyboard('chat', message))
        my_log.log_echo(message, r)
        
        if chat_id_full not in gpt_basic.CHATS:
            gpt_basic.CHATS[chat_id_full] = []
        gpt_basic.CHATS[chat_id_full] += [{"role":    'system',
                "content": f'user {tr("попросил сделать запрос в Google:", lang)} {q}'},
                {"role":    'system',
                "content": f'assistant {tr("поискал в Google и ответил:", lang)} {r}'}
            ]
        gpt_basic.CHATS[chat_id_full] = gpt_basic.CHATS[chat_id_full][-cfg.max_hist_lines:]


@bot.message_handler(commands=['image','img','i'])
def image(message: telebot.types.Message):
    thread = threading.Thread(target=image_thread, args=(message,))
    thread.start()
def image_thread(message: telebot.types.Message):
    """генерирует картинку по описанию"""

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    check_blocked_user(chat_id_full)

    with semaphore_talks:
        help = f"""/image {tr('текстовое описание картинки, что надо нарисовать', lang)}

{tr('Напишите что надо нарисовать, как это выглядит', lang)}
"""
        prompt = message.text.split(maxsplit = 1)
        if len(prompt) > 1:
            prompt = prompt[1]
            with ShowAction(message, 'upload_photo'):
                moderation_flag = gpt_basic.moderation(prompt)
                images = my_genimg.gen_images(prompt, moderation_flag)
                medias = [telebot.types.InputMediaPhoto(i) for i in images if r'https://r.bing.com' not in i]
                if len(medias) > 0:
                    msgs_ids = bot.send_media_group(message.chat.id, medias, reply_to_message_id=message.message_id)
                    if pics_group:
                        try:
                            bot.send_message(cfg.pics_group, f'{prompt}', disable_web_page_preview = True)
                            bot.send_media_group(pics_group, medias)
                        except Exception as error2:
                            print(error2)
                    caption = ''
                    # запоминаем промпт по ключу (номер первой картинки) и сохраняем в бд запрос и картинки
                    # что бы можно было их потом просматривать отдельно
                    IMAGE_PROMPTS[msgs_ids[0].message_id] = prompt

                    for i in msgs_ids:
                        caption += f'{i.message_id} '
                    caption += '\n'
                    caption += ', '.join([f'<a href="{x}">PIC</a>' for x in images])
                    bot.reply_to(message, caption, parse_mode = 'HTML', disable_web_page_preview = True, 
                                 reply_markup=get_keyboard('hide_image', message))
                    # if cfg.enable_image_adv:
                    #     bot.reply_to(message, tr('Try this group, it has a lot of mediabots: ', lang) + 'https://t.me/neuralforum',
                    #              disable_web_page_preview = True,
                    #              reply_markup=get_keyboard('hide', message))

                    my_log.log_echo(message, '[image gen] ')

                    n = [{'role':'system', 'content':f'user {tr("попросил нарисовать", lang)}\n{prompt}'}, 
                         {'role':'system', 'content':f'assistant {tr("нарисовал с помощью DALL-E", lang)}'}]
                    if chat_id_full in gpt_basic.CHATS:
                        gpt_basic.CHATS[chat_id_full] += n
                    else:
                        gpt_basic.CHATS[chat_id_full] = n
                else:
                    bot.reply_to(message, tr('Не смог ничего нарисовать. Может настроения нет, а может надо другое описание дать.', lang), 
                                 reply_markup=get_keyboard('hide', message))
                    if cfg.enable_image_adv:
                        bot.reply_to(message, tr('Try this group, it has a lot of mediabots: ', lang) + 'https://t.me/neuralforum',
                                 disable_web_page_preview = True,
                                 reply_markup=get_keyboard('hide', message))
                    my_log.log_echo(message, '[image gen error] ')
                    n = [{'role':'system', 'content':f'user {tr("попросил нарисовать", lang)}\n{prompt}'}, 
                         {'role':'system', 'content':f'assistant {tr("не захотел или не смог нарисовать это с помощью DALL-E", lang)}'}]
                    if chat_id_full in gpt_basic.CHATS:
                        gpt_basic.CHATS[chat_id_full] += n
                    else:
                        gpt_basic.CHATS[chat_id_full] = n
                        gpt_basic.CHATS[chat_id_full] = gpt_basic.CHATS[chat_id_full][-cfg.max_hist_lines:]
        else:
            COMMAND_MODE[chat_id_full] = 'image'
            bot.reply_to(message, help, parse_mode = 'Markdown', reply_markup=get_keyboard('command_mode', message))
            my_log.log_echo(message, help)


@bot.message_handler(commands=['stats'])
def stats(message: telebot.types.Message):
    """Показывает статистику использования бота."""
    thread = threading.Thread(target=stats_thread, args=(message,))
    thread.start()
def stats_thread(message: telebot.types.Message):
    """Показывает статистику использования бота."""
    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    chat_full_id = get_topic_id(message)
    lang = get_lang(chat_full_id, message)

    my_log.log_echo(message)
    if message.chat.id in cfg.admins:
        users = [x for x in CHAT_MODE.keys()]
        users_sorted = natsorted(users)
        users_text = '\n'.join(users_sorted) + '\n\nTotal: ' + str(len(users_sorted))
        reply_to_long_message(message, tr("Статистика бота:", lang) + '\n\n' + users_text,
                              reply_markup=get_keyboard('hide', message))
        my_log.log_echo(message, users_text)
        return
    msg = f'/stats ' + tr("показывает статистику бота.\n\nТолько администраторы могут использовать эту команду.", lang)
    bot.reply_to(message, msg, reply_markup=get_keyboard('hide', message))
    my_log.log_echo(message, msg)


def check_blocked_user(id: str):
    """Вызывает ошибку если юзер заблокирован и ему не надо отвечать"""
    user_id = id.replace('[','').replace(']','').split()[0]
    if not request_counter.check_limit(user_id):
        my_log.log2(f'tb:check_blocked_user: Пользователь {id} заблокирован за DDOS')
        raise Exception(f'user {user_id} in ddos stop list, ignoring')
    for i in BAD_USERS:
        u_id = i.replace('[','').replace(']','').split()[0]
        if u_id == user_id:
            if BAD_USERS[id]:
                my_log.log2(f'tb:check_blocked_user: Пользователь {id} заблокирован')
                raise Exception(f'user {user_id} in stop list, ignoring')


@bot.message_handler(commands=['blockadd'])
def block_user_add(message: telebot.types.Message):
    """Добавить юзера в стоп список"""
    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    chat_full_id = get_topic_id(message)
    lang = get_lang(chat_full_id, message)
    my_log.log_echo(message)
    if message.chat.id in cfg.admins:
        user_id = message.text[10:].strip()
        if user_id:
            BAD_USERS[user_id] = True
            bot.reply_to(message, f'{tr("Пользователь", lang)} {user_id} {tr("добавлен в стоп-лист", lang)}',
                         reply_markup=get_keyboard('hide', message))
            my_log.log_echo(message, f'Пользователь {user_id} добавлен в стоп-лист')
    else:
        bot.reply_to(message, tr('Только администраторы могут использовать эту команду.', lang), 
                     reply_markup=get_keyboard('hide', message))
        my_log.log_echo(message, 'Только администраторы могут использовать эту команду.')


@bot.message_handler(commands=['blockdel'])
def block_user_del(message: telebot.types.Message):
    """Убрать юзера из стоп списка"""
    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    chat_full_id = get_topic_id(message)
    lang = get_lang(chat_full_id, message)
    my_log.log_echo(message)
    if message.chat.id in cfg.admins:
        user_id = message.text[10:].strip()
        if user_id:
            if user_id in BAD_USERS:
                del BAD_USERS[user_id]
                bot.reply_to(message, f'{tr("Пользователь", lang)} {user_id} {tr("удален из стоп-листа", lang)}',
                             reply_markup=get_keyboard('hide', message))
                my_log.log_echo(message, f'Пользователь {user_id} удален из стоп-листа')
            else:
                bot.reply_to(message, f'{tr("Пользователь", lang)} {user_id} {tr("не найден в стоп-листе", lang)}', 
                             reply_markup=get_keyboard('hide', message))
                my_log.log_echo(message, f'Пользователь {user_id} не найден в стоп-листе')
    else:
        bot.reply_to(message, tr('Только администраторы могут использовать эту команду.', lang), reply_markup=get_keyboard('hide', message))
        my_log.log_echo(message, 'Только администраторы могут использовать эту команду.')


@bot.message_handler(commands=['blocklist'])
def block_user_list(message: telebot.types.Message):
    """Показывает список заблокированных юзеров"""
    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    chat_full_id = get_topic_id(message)
    lang = get_lang(chat_full_id, message)
    my_log.log_echo(message)
    if message.chat.id in cfg.admins:
        users = [x for x in BAD_USERS.keys() if x]
        if users:
            reply_to_long_message(message, '\n'.join(users), reply_markup=get_keyboard('hide', message))
            my_log.log_echo(message, '\n'.join(users))
    else:
        bot.reply_to(message, tr('Только администраторы могут использовать эту команду.', lang), reply_markup=get_keyboard('hide', message))
        my_log.log_echo(message, 'Только администраторы могут использовать эту команду.')


@bot.message_handler(commands=['ask', 'perplexity'])
def ask(message: telebot.types.Message):
    thread = threading.Thread(target=ask_thread, args=(message,))
    thread.start()
def ask_thread(message: telebot.types.Message):
    """ищет в perplexity.ai ответ"""
    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)
    return

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    check_blocked_user(chat_id_full)

    try:
        query = message.text.split(maxsplit=1)[1]
    except Exception as error2:
        print(error2)
        help = """/ask <текст запроса> будет искать с помощью сервиса perplexity.io"""
        bot.reply_to(message, help, parse_mode = 'Markdown',
                     disable_web_page_preview = True,
                     reply_markup=get_keyboard('hide', message))
        return

    with ShowAction(message, 'typing'):
        with semaphore_talks:
            try:
                response = my_perplexity.ask(query)
            except Exception as error2:
                my_log.log2(f'tb:ask: {error2}')
                f'tb:ask: {error2}'
                response = ''
        if not response:
            bot.reply_to(message, 'Интернет вам не ответил, перезвоните позже',
                         parse_mode = '', disable_web_page_preview = True,
                         reply_markup=get_keyboard('hide', message))
            return
        try:
            reply_to_long_message(message, response, parse_mode = 'HTML',
                                  disable_web_page_preview = True,
                                  reply_markup=get_keyboard('chat', message))
        except Exception as error2:
            my_log.log2(error2)
            reply_to_long_message(message, response, parse_mode = '',
                                  disable_web_page_preview = True,
                                  reply_markup=get_keyboard('chat', message))
        my_log.log_echo(message, response)

        if chat_id_full not in gpt_basic.CHATS:
            gpt_basic.CHATS[chat_id_full] = []
        gpt_basic.CHATS[chat_id_full] += [{"role":    'system',
                "content": f'user {tr("попросил сделать запрос в perplexity.io:", lang)} {query}'},
                {"role":    'system',
                "content": f'assistant {tr("perplexity.io ответил:", lang)} {response}'}
            ]
        gpt_basic.CHATS[chat_id_full] = gpt_basic.CHATS[chat_id_full][-cfg.max_hist_lines:]


@bot.message_handler(commands=['alert'])
def alert(message: telebot.types.Message):
    """Сообщение всем кого бот знает. CHAT_MODE обновляется при каждом создании клавиатуры, 
       а она появляется в первом же сообщении.
    """
    thread = threading.Thread(target=alert_thread, args=(message,))
    thread.start()
def alert_thread(message: telebot.types.Message):
    """Сообщение всем кого бот знает. CHAT_MODE обновляется при каждом создании клавиатуры, 
       а она появляется в первом же сообщении.
    """
    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    chat_full_id = get_topic_id(message)
    lang = get_lang(chat_full_id, message)
    my_log.log_echo(message)
    if message.chat.id in cfg.admins:
        text = message.text[7:]
        if text:
            text = utils.bot_markdown_to_html(text)
            text = f'<b>{tr("Широковещательное сообщение от Верховного Адмнистратора, не обращайте внимания", lang)}</b>' + '\n\n\n' + text

            for x, _ in CHAT_MODE.items():
                x = x.replace('[','').replace(']','')
                chat = int(x.split()[0])
                # if chat not in cfg.admins:
                #     return
                thread = int(x.split()[1])
                try:
                    bot.send_message(chat_id = chat, message_thread_id=thread, text = text, parse_mode='HTML',
                                    disable_notification = True, disable_web_page_preview = True,
                                    reply_markup=get_keyboard('translate', message))
                except Exception as error2:
                    print(f'tb:alert: {error2}')
                    my_log.log2(f'tb:alert: {error2}')
                time.sleep(0.3)
            return

    msg = f'/alert <{tr("текст сообщения которое бот отправит всем кого знает, форматирование маркдаун", lang)}>. {tr("Только администраторы могут использовать эту команду.", lang)}'
    bot.reply_to(message, msg, reply_markup=get_keyboard('hide', message))
    my_log.log_echo(message, msg)


@bot.message_handler(commands=['qr'])
def qrcode_text(message: telebot.types.Message):
    """переводит текст в qrcode"""
    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    chat_full_id = get_topic_id(message)
    lang = get_lang(chat_full_id, message)
    my_log.log_echo(message)
    text = message.text[3:]
    if text:
        image = utils.text_to_qrcode(text)
        if image:
            bio = io.BytesIO()
            bio.name = 'qr.png'
            image.save(bio, 'PNG')
            bio.seek(0)
            bot.send_photo(chat_id = message.chat.id, message_thread_id = message.message_thread_id, photo=bio,
                           reply_markup=get_keyboard('hide', message))
            my_log.log_echo(message, '[QR code]')
            return

    msg = f'/qr {tr("текст который надо перевести в qrcode", lang)}'
    bot.reply_to(message, msg, reply_markup=get_keyboard('hide', message))
    my_log.log_echo(message, msg)


@bot.message_handler(commands=['sum'])
def summ_text(message: telebot.types.Message):
    thread = threading.Thread(target=summ_text_thread, args=(message,))
    thread.start()
def summ_text_thread(message: telebot.types.Message):

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    check_blocked_user(chat_id_full)

    my_log.log_echo(message)

    if not allowed_chatGPT_user(message.chat.id):
        my_log.log_echo(message, 'chatGPT запрещен [sum]')
        bot.reply_to(message, tr('You are not in allow chatGPT users list', lang))
        return

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
                    rr = utils.bot_markdown_to_html(r)
                    reply_to_long_message(message, rr, disable_web_page_preview = True,
                                          parse_mode='HTML',
                                          reply_markup=get_keyboard('translate', message))
                    my_log.log_echo(message, r)
                    if chat_id_full not in gpt_basic.CHATS:
                        gpt_basic.CHATS[chat_id_full] = []
                    gpt_basic.CHATS[chat_id_full] += [{"role":    'system',
                                "content": f'user {tr("попросил кратко пересказать содержание текста по ссылке/из файла", lang)}'},
                                {"role":    'system',
                                "content": f'assistant {tr("прочитал и ответил:", lang)} {r}'}
                                ]
                    gpt_basic.CHATS[chat_id_full] = gpt_basic.CHATS[chat_id_full][-cfg.max_hist_lines:]
                    return

                with ShowAction(message, 'typing'):
                    res = ''
                    try:
                        res = my_sum.summ_url(url, lang = lang)
                    except Exception as error2:
                        print(error2)
                        m = tr('Не нашел тут текста. Возможно что в видео на ютубе нет субтитров или страница слишком динамическая и не показывает текст без танцев с бубном, или сайт меня не пускает.\n\nЕсли очень хочется то отправь мне текстовый файл .txt (utf8) с текстом этого сайта и подпиши `что там`', lang)
                        bot.reply_to(message, m, parse_mode='Markdown', reply_markup=get_keyboard('hide', message))
                        my_log.log_echo(message, m)
                        return
                    if res:
                        rr = utils.bot_markdown_to_html(res)
                        reply_to_long_message(message, rr, parse_mode='HTML',
                                              disable_web_page_preview = True,
                                              reply_markup=get_keyboard('translate', message))
                        my_log.log_echo(message, res)
                        SUM_CACHE[url] = res
                        if chat_id_full not in gpt_basic.CHATS:
                            gpt_basic.CHATS[chat_id_full] = []
                        gpt_basic.CHATS[chat_id_full] += [{"role":    'system',
                                "content": f'user {tr("попросил кратко пересказать содержание текста по ссылке/из файла", lang)}'},
                                {"role":    'system',
                                "content": f'assistant {tr("прочитал и ответил:", lang)} {r}'}
                                ]
                        gpt_basic.CHATS[chat_id_full] = gpt_basic.CHATS[chat_id_full][-cfg.max_hist_lines:]
                        return
                    else:
                        error = tr('Не смог прочитать текст с этой страницы.', lang)
                        bot.reply_to(message, error, reply_markup=get_keyboard('hide', message))
                        my_log.log_echo(message, error)
                        return
    help = f"""{tr('Пример:', lang)} /sum https://youtu.be/3i123i6Bf-U

{tr('Давайте вашу ссылку и я перескажу содержание', lang)}"""
    COMMAND_MODE[chat_id_full] = 'sum'
    bot.reply_to(message, help, parse_mode = 'Markdown', reply_markup=get_keyboard('command_mode', message))
    my_log.log_echo(message, help)


@bot.message_handler(commands=['sum2'])
def summ2_text(message: telebot.types.Message):
    # убирает запрос из кеша если он там есть и делает запрос снова

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


@bot.message_handler(commands=['trans', 'tr', 't'])
def trans(message: telebot.types.Message):
    thread = threading.Thread(target=trans_thread, args=(message,))
    thread.start()
def trans_thread(message: telebot.types.Message):

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    check_blocked_user(chat_id_full)

    my_log.log_echo(message)

    with semaphore_talks:
        help = f"""/trans [en|ru|uk|..] {tr('''текст для перевода на указанный язык

Если не указан то на ваш язык.''', lang)}

/trans uk hello world
/trans was ist das

{tr('Поддерживаемые языки:', lang)} {', '.join(supported_langs_trans)}

{tr('Напишите что надо перевести', lang)}
"""
        if message.text.startswith('/t '):
            message.text = message.text.replace('/t', '/trans', 1)
        if message.text.startswith('/tr '):
            message.text = message.text.replace('/tr', '/trans', 1)
        # разбираем параметры
        # регулярное выражение для разбора строки
        pattern = r'^\/trans\s+((?:' + '|'.join(supported_langs_trans) + r')\s+)?\s*(.*)$'
        # поиск совпадений с регулярным выражением
        match = re.match(pattern, message.text, re.DOTALL)
        # извлечение параметров из найденных совпадений
        if match:
            llang = match.group(1) or lang  # если lang не указан, то по умолчанию язык юзера
            text = match.group(2) or ''
        else:
            COMMAND_MODE[chat_id_full] = 'trans'
            bot.reply_to(message, help, parse_mode = 'Markdown',
                         reply_markup=get_keyboard('command_mode', message))
            my_log.log_echo(message, help)
            return
        llang = llang.strip()

    with semaphore_talks:
        with ShowAction(message, 'typing'):
            translated = my_trans.translate_text2(text, llang)
            if translated:
                detected_langs = []
                try:
                    for x in my_trans.detect_langs(text):
                        l = my_trans.lang_name_by_code(x.lang)
                        p = round(x.prob*100, 2)
                        detected_langs.append(f'{tr(l, lang)} {p}%')
                except Exception as detect_error:
                    my_log.log2(f'tb:trans:detect_langs: {detect_error}')
                if match and match.group(1):
                    bot.reply_to(message, translated,
                                 reply_markup=get_keyboard('translate', message))
                else:
                    bot.reply_to(message,
                                 translated + '\n\n' + tr('Распознанные языки:', lang) \
                                 + ' ' + str(', '.join(detected_langs)).strip(', '),
                                 reply_markup=get_keyboard('translate', message))
                my_log.log_echo(message, translated)
            else:
                msg = 'Ошибка перевода'
                bot.reply_to(message, msg, reply_markup=get_keyboard('hide', message))
                my_log.log_echo(message, msg)


@bot.message_handler(commands=['name'])
def send_name(message: telebot.types.Message):
    """Меняем имя если оно подходящее, содержит только русские и английские буквы и не
    слишком длинное"""

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    check_blocked_user(chat_id_full)

    BAD_NAMES = (tr('гугл', lang).lower(), tr('утка', lang).lower(),
                 tr('нарисуй', lang).lower())
    args = message.text.split()
    if len(args) > 1:
        new_name = args[1]
        
        # Строка содержит только русские и английские буквы и цифры после букв, но не в начале слова
        # regex = r'^[a-zA-Zа-яА-ЯёЁ][a-zA-Zа-яА-ЯёЁ0-9]*$'
        # if re.match(regex, new_name) and len(new_name) <= 10 \
                    # and new_name.lower() not in BAD_NAMES:
        if len(new_name) <= 10 and new_name.lower() not in BAD_NAMES:
            BOT_NAMES[chat_id_full] = new_name.lower()
            msg = f'{tr("Кодовое слово для обращения к боту изменено на", lang)} ({args[1]}) {tr("для этого чата.", lang)}'
            bot.reply_to(message, msg, reply_markup=get_keyboard('hide', message))
            my_log.log_echo(message, msg)
        else:
            msg = f"{tr('Неправильное имя, цифры после букв, не больше 10 всего. Имена', lang)} {', '.join(BAD_NAMES) if BAD_NAMES else ''} {tr('уже заняты.', lang)}"
            bot.reply_to(message, msg, reply_markup=get_keyboard('hide', message))
            my_log.log_echo(message, msg)
    else:
        help = f"{tr('Напишите новое имя бота и я поменяю его, цифры после букв, не больше 10 всего. Имена', lang)} {', '.join(BAD_NAMES) if BAD_NAMES else ''} {tr('уже заняты.', lang)}"
        COMMAND_MODE[chat_id_full] = 'name'
        bot.reply_to(message, help, parse_mode='Markdown', reply_markup=get_keyboard('command_mode', message))


@bot.message_handler(commands=['ocr'])
def ocr_setup(message: telebot.types.Message):
    """меняет настройки ocr"""

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    check_blocked_user(chat_id_full)

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)

    try:
        arg = message.text.split(maxsplit=1)[1]
    except IndexError as error:
        print(f'tb:ocr_setup: {error}')
        my_log.log2(f'tb:ocr_setup: {error}')

        msg = f'''/ocr langs

<code>/ocr rus+eng</code>

{tr("""Меняет настройки OCR

Не указан параметр, какой язык (код) или сочетание кодов например""", lang)} rus+eng+ukr

{tr("Сейчас выбран:", lang)} <b>{get_ocr_language(message)}</b>

https://tesseract-ocr.github.io/tessdoc/Data-Files-in-different-versions.html'''

        bot.reply_to(message, msg, parse_mode='HTML',
                     reply_markup=get_keyboard('hide', message),
                     disable_web_page_preview=True)
        return

    llang = get_ocr_language(message)

    msg = f'{tr("Старые настройки:", lang)} {llang}\n\n{tr("Новые настройки:", lang)} {arg}'
    OCR_DB[chat_id_full] = arg
    
    bot.reply_to(message, msg, parse_mode='HTML', reply_markup=get_keyboard('hide', message))


@bot.message_handler(commands=['start'])
def send_welcome_start(message: telebot.types.Message):
    # Отправляем приветственное сообщение

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    help = """Hello! I'm your personal multi-functional assistant 🤖

I provide free access to various chatbots like ChatGPT, Google Bard, Claude AI, and more. Additionally, I can create drawings from text descriptions, recognize text in images, voice messages, and documents. I can work in group chats, have a voice mode, and even search for answers on Google. I can also provide concise summaries of web pages and YouTube videos.

If you need assistance with anything, feel free to reach out to me anytime. Just ask your question, and I'll do my best to help you! 🌟"""
    help = tr(help, lang)
    bot.reply_to(message, help, parse_mode='Markdown', disable_web_page_preview=True, reply_markup=get_keyboard('start', message))
    my_log.log_echo(message, help)


@bot.message_handler(commands=['help'])
def send_welcome_help(message: telebot.types.Message):
    # Отправляем приветственное сообщение

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)

    chat_full = get_topic_id(message)
    lang = get_lang(chat_full, message)

    help = f"""The chatbot responds to the name <b>bot</b>.
For example, you can say <b>bot, tell me a joke</b>.
In private messages, you don't need to mention the bot's name

🔭 If you send a link in a private message, the bot will try to extract and provide a brief summary of the content.

🛸 To get text from an image, send the image with the caption "ocr" (or "read"). 

🎙️ You can issue commands and make requests using voice messages.

When communicating with Claude AI, uploaded files and links are sent directly to Claude, and he can respond based on their content.

ChatGPT has a special mode of operation where a model trained for concise answers responds instead of the chat. To use it, simply start your query with a period.

.Write all days of the week separated by commas

The usual model will add extraneous words to its responses, such as "Okay, I'll try," while this model is trained to be concise and informative.


You can send texts longer than 4096 characters. The Telegram client automatically breaks them down into parts, and the bot reassembles them. The restrictions for chatbots are as follows:

ChatGPT: {cfg.CHATGPT_MAX_REQUEST}
Google Bard: {my_bard.MAX_REQUEST}
Claude AI: {my_claude.MAX_QUERY}
GeminiPro: {my_gemini.MAX_REQUEST}


Website:
https://github.com/theurs/tb1

Report issues on Telegram:
https://t.me/theurs

Donate:"""

    help = tr(help, lang) + f'\n<a href = "https://www.sberbank.com/ru/person/dl/jc?linkname=EiDrey1GTOGUc3j0u">SBER</a> <a href = "https://qiwi.com/n/KUN1SUN">QIWI</a> <a href = "https://yoomoney.ru/to/4100118478649082">Yoomoney</a>'

    try:
        reply_to_long_message(message, help, parse_mode='HTML', disable_web_page_preview=True, reply_markup=get_keyboard('hide', message))
    except Exception as error:
        print(f'tb:send_welcome_help: {error}')
        my_log.log2(f'tb:send_welcome_help: {error}')
        reply_to_long_message(message, help, parse_mode='', disable_web_page_preview=True, reply_markup=get_keyboard('hide', message))
    my_log.log_echo(message, help)


@bot.message_handler(commands=['id']) 
def id_cmd_handler(message: telebot.types.Message):
    """показывает id юзера и группы в которой сообщение отправлено"""

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    chat_full_id = get_topic_id(message)
    lang = get_lang(chat_full_id, message)

    user_id = message.from_user.id
    chat_id_full = get_topic_id(message)
    reported_language = message.from_user.language_code
    bot.reply_to(message, f'''{tr("ID пользователя:", lang)} {user_id}
                 
{tr("ID группы:", lang)} {chat_id_full}

{tr("Язык который телеграм сообщает боту:", lang)} {reported_language}
''', reply_markup=get_keyboard('hide', message))


@bot.message_handler(commands=['dump_translation'])
def dump_translation(message: telebot.types.Message):
    thread = threading.Thread(target=dump_translation_thread, args=(message,))
    thread.start()
def dump_translation_thread(message: telebot.types.Message):
    """
    Dump automatically translated messages as json file
    """
    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    chat_full_id = get_topic_id(message)
    lang = get_lang(chat_full_id, message)

    my_log.log_echo(message)

    with ShowAction(message, 'upload_document'):
        # dump AUTO_TRANSLATIONS as json file
        with DUMP_TRANSLATION_LOCK:
            # сохранить AUTO_TRANSLATIONS в файл AUTO_TRANSLATIONS.json
            with open('AUTO_TRANSLATIONS.json', 'w', encoding='utf-8') as f:
                json.dump(AUTO_TRANSLATIONS, f, indent=4, sort_keys=True, ensure_ascii=False)
            # отправить файл пользователю
            bot.send_document(message.chat.id, open('AUTO_TRANSLATIONS.json', 'rb'))
            try:
                os.remove('AUTO_TRANSLATIONS.json')
            except Exception as error:
                my_log.log2(f'ERROR: {error}')


@bot.message_handler(commands=['init'])
def set_default_commands(message: telebot.types.Message):
    thread = threading.Thread(target=set_default_commands_thread, args=(message,))
    thread.start()
def set_default_commands_thread(message: telebot.types.Message):
    """
    Reads a file containing a list of commands and their descriptions,
    and sets the default commands for the bot.
    """
    """
    Reads a file containing a list of commands and their descriptions,
    and sets the default commands for the bot.
    """
    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    chat_full_id = get_topic_id(message)
    user_lang = get_lang(chat_full_id, message)

    if message.from_user.id not in cfg.admins:
        bot.reply_to(message, tr("Эта команда доступна только администраторам",
                                 user_lang))
        return

    def get_seconds(s):
        match = re.search(r"after\s+(?P<seconds>\d+)", s)
        if match:
            return int(match.group("seconds"))
        else:
            return 0

    bot.reply_to(message,
                 tr("Локализация займет много времени, не повторяйте эту команду",
                    user_lang))
    
    # most_used_langs = ['ar', 'bn', 'da', 'de', 'el', 'en', 'es', 'fa', 'fi', 'fr','hi',
    #                    'hu', 'id', 'in', 'it', 'ja', 'ko', 'nl', 'no', 'pl', 'pt', 'ro',
    #                    'ru', 'sv', 'sw', 'th', 'tr', 'uk', 'ur', 'vi', 'zh']
    most_used_langs = [x for x in supported_langs_trans if len(x) == 2]

    msg_commands = ''
    for lang in most_used_langs:
        commands = []
        with open('commands.txt', encoding='utf-8') as file:
            for line in file:
                try:
                    command, description = line[1:].strip().split(' - ', 1)
                    if command and description:
                        description = tr(description, lang)
                        commands.append(telebot.types.BotCommand(command, description))
                except Exception as error:
                    my_log.log2(f'Не удалось прочитать команды по умолчанию для языка {lang}: {error}')
        result = False
        try:
            l1 = [x.description for x in bot.get_my_commands(language_code=lang)]
            l2 = [x.description for x in commands]
            if l1 != l2:
                result = bot.set_my_commands(commands, language_code=lang)
            else:
                result = True
        except Exception as error_set_command:
            my_log.log2(f'Не удалось установить команды по умолчанию для языка {lang}: {error_set_command} ')
            time.sleep(get_seconds(str(error_set_command)))
            try:
                if l1 != l2:
                    result = bot.set_my_commands(commands, language_code=lang)
                else:
                    result = True
            except Exception as error_set_command2:
                my_log.log2(f'Не удалось установить команды по умолчанию для языка {lang}: {error_set_command2}')
        if result:
            result = '✅'
        else:
            result = '❌'

        msg = f'{result} Установлены команды по умолчанию [{lang}]'
        msg_commands += msg + '\n'
    reply_to_long_message(message, msg_commands)

    new_bot_name = cfg.bot_name.strip()
    new_description = cfg.bot_description.strip()
    new_short_description = cfg.bot_short_description.strip()

    msg_bot_names = ''
    for lang in most_used_langs:
        result = False
        try:
            if bot.get_my_name(language_code=lang).name != tr(new_bot_name, lang):
                result = bot.set_my_name(tr(new_bot_name, lang), language_code=lang)
            else:
                result = True
        except Exception as error_set_name:
            my_log.log2(f'Не удалось установить имя бота: {tr(new_bot_name, lang)}'+'\n\n'+str(error_set_name))
            time.sleep(get_seconds(str(error_set_name)))
            try:
                if bot.get_my_name(language_code=lang).name != tr(new_bot_name, lang):
                    result = bot.set_my_name(tr(new_bot_name, lang), language_code=lang)
                else:
                    result = True
            except Exception as error_set_name2:
                my_log.log2(f'Не удалось установить имя бота: {tr(new_bot_name, lang)}'+'\n\n'+str(error_set_name2))
        if result:
            msg_bot_names += '✅ Установлено имя бота для языка ' + lang + f' [{tr(new_bot_name, lang)}]\n'
        else:
            msg_bot_names += '❌ Установлено имя бота для языка ' + lang + f' [{tr(new_bot_name, lang)}]\n'
    reply_to_long_message(message, msg_bot_names)

    msg_descriptions = ''
    for lang in most_used_langs:
        result = False
        try:
            if bot.get_my_description(language_code=lang).description != tr(new_description, lang):
                result = bot.set_my_description(tr(new_description, lang), language_code=lang)
            else:
                result = True
        except Exception as error_set_description:
            my_log.log2(f'Не удалось установить описание бота {lang}: {tr(new_description, lang)}'+'\n\n'+str(error_set_description))
            time.sleep(get_seconds(str(error_set_description)))
            try:
                if bot.get_my_description(language_code=lang).description != tr(new_description, lang):
                    result = bot.set_my_description(tr(new_description, lang), language_code=lang)
                else:
                    result = True
            except Exception as error_set_description2:
                my_log.log2(f'Не удалось установить описание бота {lang}: {tr(new_description, lang)}'+'\n\n'+str(error_set_description2))
                msg_descriptions += '❌ Установлено новое описание бота для языка ' + lang + '\n'
                continue
        if result:
            msg_descriptions += '✅ Установлено новое описание бота для языка ' + lang + '\n'
        else:
            msg_descriptions += '❌ Установлено новое описание бота для языка ' + lang + '\n'
    reply_to_long_message(message, msg_descriptions)

    msg_descriptions = ''
    for lang in most_used_langs:
        result = False
        try:
            if bot.get_my_short_description(language_code=lang).short_description != tr(new_short_description, lang):
                result = bot.set_my_short_description(tr(new_short_description, lang), language_code=lang)
            else:
                result = True
        except Exception as error_set_short_description:
            my_log.log2(f'Не удалось установить короткое описание бота: {tr(new_short_description, lang)}'+'\n\n'+str(error_set_short_description))
            time.sleep(get_seconds(str(error_set_short_description)))
            try:
                if bot.get_my_short_description(language_code=lang).short_description != tr(new_short_description, lang):
                    result = bot.set_my_short_description(tr(new_short_description, lang), language_code=lang)
                else:
                    result = True
            except Exception as error_set_short_description2:
                my_log.log2(f'Не удалось установить короткое описание бота: {tr(new_short_description, lang)}'+'\n\n'+str(error_set_short_description2))
                msg_descriptions += '❌ Установлено новое короткое описание бота для языка ' + lang + '\n'
                continue
        if result:
            msg_descriptions += '✅ Установлено новое короткое описание бота для языка ' + lang + '\n'
        else:
            msg_descriptions += '❌ Установлено новое короткое описание бота для языка ' + lang + '\n'
    reply_to_long_message(message, msg_descriptions)


def send_long_message(message: telebot.types.Message, resp: str, parse_mode:str = None, disable_web_page_preview: bool = None,
                      reply_markup: telebot.types.InlineKeyboardMarkup = None):
    """отправляем сообщение, если оно слишком длинное то разбивает на 2 части либо отправляем как текстовый файл"""
    reply_to_long_message(message=message, resp=resp, parse_mode=parse_mode,
                          disable_web_page_preview=disable_web_page_preview,
                          reply_markup=reply_markup, send_message = True)


def reply_to_long_message(message: telebot.types.Message, resp: str, parse_mode: str = None,
                          disable_web_page_preview: bool = None,
                          reply_markup: telebot.types.InlineKeyboardMarkup = None, send_message: bool = False):
    # отправляем сообщение, если оно слишком длинное то разбивает на 2 части либо отправляем как текстовый файл

    if not resp:
        return

    chat_id_full = get_topic_id(message)

    if len(resp) < 20000:
        if parse_mode == 'HTML':
            chunks = utils.split_html(resp, 4000)
        else:
            chunks = utils.split_text(resp, 4000)
        counter = len(chunks)
        for chunk in chunks:
            # в режиме только голоса ответы идут голосом без текста
            # скорее всего будет всего 1 чанк, не слишком длинный текст
            if chat_id_full in VOICE_ONLY_MODE and VOICE_ONLY_MODE[chat_id_full]:
                message.text = '/tts ' + chunk
                tts(message)
            else:
                try:
                    if send_message:
                        bot.send_message(message.chat.id, chunk, message_thread_id=message.message_thread_id, parse_mode=parse_mode,
                                         disable_web_page_preview=disable_web_page_preview, reply_markup=reply_markup)
                    else:
                        bot.reply_to(message, chunk, parse_mode=parse_mode,
                                disable_web_page_preview=disable_web_page_preview, reply_markup=reply_markup)
                except Exception as error:
                    print(error)
                    my_log.log2(f'tb:reply_to_long_message: {error}')
                    my_log.log2(chunk)
                    if send_message:
                        bot.send_message(message.chat.id, chunk, message_thread_id=message.message_thread_id, parse_mode='',
                                         disable_web_page_preview=disable_web_page_preview, reply_markup=reply_markup)
                    else:
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


def allowed_chatGPT_user(chat_id: int) -> bool:
    """Проверка на то что юзер может использовать бота"""
    if len(cfg.allow_chatGPT_users) == 0:
        return True

    if chat_id in cfg.allow_chatGPT_users:
        return True
    else:
        return False


@bot.message_handler(func=lambda message: True)
def echo_all(message: telebot.types.Message, custom_prompt: str = '') -> None:
    """Обработчик текстовых сообщений"""
    thread = threading.Thread(target=do_task, args=(message, custom_prompt))
    thread.start()
def do_task(message, custom_prompt: str = ''):
    """функция обработчик сообщений работающая в отдельном потоке"""

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    # отлавливаем слишком длинные сообщения
    if chat_id_full not in MESSAGE_QUEUE:
        MESSAGE_QUEUE[chat_id_full] = message.text
        last_state = MESSAGE_QUEUE[chat_id_full]
        n = 5
        while n > 0:
            n -= 1
            time.sleep(0.1)
            new_state = MESSAGE_QUEUE[chat_id_full]
            if last_state != new_state:
                last_state = new_state
                n = 5
        message.text = last_state
        del MESSAGE_QUEUE[chat_id_full]
    else:
        MESSAGE_QUEUE[chat_id_full] += message.text + '\n\n'
        return

    if message.text in [tr('🎨 Нарисуй', lang),     tr('🌐 Найди', lang), 
                        tr('📋 Перескажи', lang),   tr('🎧 Озвучь', lang),
                        tr('🈶 Перевод', lang),     tr('⚙️ Настройки', lang),
                        '🎨 Нарисуй',               '🌐 Найди',
                        '📋 Перескажи',             '🎧 Озвучь',
                        '🈶 Перевод',               '⚙️ Настройки',
                        '🎨Нарисуй',                '🌐Найди',
                        '📋Перескажи',              '🎧Озвучь',
                        '🈶Перевод',                '⚙️Настройки']:
        if message.text in (tr('🎨 Нарисуй', lang), '🎨 Нарисуй', '🎨Нарисуй'):
            message.text = '/image'
            image(message)
        if message.text in (tr('🌐 Найди', lang), '🌐 Найди', '🌐Найди'):
            message.text = '/google'
            google(message)
        # if message.text in (tr('🌐 Найди', lang), '🌐 Найди', '🌐Найди'):
        #     message.text = '/ask'
        #     ask(message)
        if message.text in (tr('📋 Перескажи', lang), '📋 Перескажи', '📋Перескажи'):
            message.text = '/sum'
            summ_text(message)
        if message.text in (tr('🎧 Озвучь', lang), '🎧 Озвучь', '🎧Озвучь'):
            message.text = '/tts'
            tts(message)
        if message.text in (tr('🈶 Перевод', lang), '🈶 Перевод', '🈶Перевод'):
            message.text = '/trans'
            trans(message)
        if message.text in (tr('⚙️ Настройки', lang), '⚙️ Настройки', '⚙️Настройки'):
            message.text = '/config'
            config(message)
        return

    if custom_prompt:
        message.text = custom_prompt

    # не обрабатывать неизвестные команды
    if message.text.startswith('/'): return

    # если использовано кодовое слово вместо команды /music
    for x in cfg.MUSIC_WORDS:
        mv = x + ' '
        if message.text.lower().startswith(mv) and message.text.lower() != mv:
            message.text = '/music ' + message.text[len(mv):]
            music(message)
            return

    with semaphore_talks:

        my_log.log_echo(message)

        # является ли это сообщение топика, темы (особые чаты внутри чатов)
        is_topic = message.is_topic_message or (message.reply_to_message and message.reply_to_message.is_topic_message)
        # является ли это ответом на сообщение бота
        is_reply = message.reply_to_message and message.reply_to_message.from_user.id == BOT_ID

        # не отвечать если это ответ юзера другому юзеру
        try:
            _ = message.dont_check_topic
        except AttributeError:
            message.dont_check_topic = False
        if not message.dont_check_topic:
            if is_topic: # в топиках всё не так как в обычных чатах
                # если ответ не мне либо запрос ко всем(в топике он выглядит как ответ с content_type == 'forum_topic_created')
                if not (is_reply or message.reply_to_message.content_type == 'forum_topic_created'):
                    return
            else:
                # если это ответ в обычном чате но ответ не мне то выход
                if message.reply_to_message and not is_reply:
                    return

        # определяем откуда пришло сообщение  
        is_private = message.chat.type == 'private'
        if chat_id_full not in SUPER_CHAT:
            SUPER_CHAT[chat_id_full] = 0
        # если бот должен отвечать всем в этом чате то пусть ведет себя как в привате
        # но если это ответ на чье-то сообщение то игнорируем
        # if SUPER_CHAT[chat_id_full] == 1 and not is_reply_to_other:
        if SUPER_CHAT[chat_id_full] == 1:
            is_private = True

        # удаляем пробелы в конце каждой строки
        message.text = "\n".join([line.rstrip() for line in message.text.split("\n")])

        msg = message.text.lower()

        # кто по умолчанию отвечает
        if chat_id_full not in CHAT_MODE:
            CHAT_MODE[chat_id_full] = cfg.chat_mode_default

        # если сообщение начинается на точку и режим чатГПТ то делаем запрос к модели
        # gpt-3.5-turbo-instruct
        FIRST_DOT = False
        if msg.startswith('.'):
            msg = msg[1:]
            message.text = message.text[1:]
            FIRST_DOT = True

        # определяем какое имя у бота в этом чате, на какое слово он отзывается
        if chat_id_full in BOT_NAMES:
            bot_name = BOT_NAMES[chat_id_full]
        else:
            bot_name = BOT_NAME_DEFAULT
            BOT_NAMES[chat_id_full] = bot_name

        bot_name_used = False
        # убираем из запроса кодовое слово
        if msg.startswith((f'{bot_name} ', f'{bot_name},', f'{bot_name}\n')):
            bot_name_used = True
            message.text = message.text[len(f'{bot_name} '):].strip()

        bot_name2 = f'@{_bot_name}'
        # убираем из запроса имя бота в телеграме
        if msg.startswith((f'{bot_name2} ', f'{bot_name2},', f'{bot_name2}\n')):
            bot_name_used = True
            message.text = message.text[len(f'{bot_name2} '):].strip()

        msg = message.text.lower()

        # если предварительно была введена какая то команда то этот текст надо отправить в неё
        if chat_id_full in COMMAND_MODE:
            if COMMAND_MODE[chat_id_full]:
                if COMMAND_MODE[chat_id_full] == 'image':
                    message.text = f'/image {message.text}'
                    image(message)
                elif COMMAND_MODE[chat_id_full] == 'tts':
                    message.text = f'/tts {message.text}'
                    tts(message)
                elif COMMAND_MODE[chat_id_full] == 'trans':
                    message.text = f'/trans {message.text}'
                    trans(message)
                elif COMMAND_MODE[chat_id_full] == 'google':
                    message.text = f'/google {message.text}'
                    google(message)
                elif COMMAND_MODE[chat_id_full] == 'ddg':
                    message.text = f'/ddg {message.text}'
                    ddg(message)
                elif COMMAND_MODE[chat_id_full] == 'name':
                    message.text = f'/name {message.text}'
                    send_name(message)
                elif COMMAND_MODE[chat_id_full] == 'style':
                    message.text = f'/style {message.text}'
                    change_mode(message)
                elif COMMAND_MODE[chat_id_full] == 'sum':
                    message.text = f'/sum {message.text}'
                    summ_text(message)
                COMMAND_MODE[chat_id_full] = ''
                return

        # если сообщение начинается на 'заткнись или замолчи' то ставим блокировку на канал и выходим
        if msg.startswith((tr('замолчи', lang), tr('заткнись', lang))) and (is_private or is_reply):
            BLOCKS[chat_id_full] = 1
            bot.reply_to(message, tr('Автоперевод выключен', lang), reply_markup=get_keyboard('hide', message))
            my_log.log_echo(message, 'Включена блокировка автопереводов в чате')
            return
        # если сообщение начинается на 'вернись' то снимаем блокировку на канал и выходим
        if msg.startswith(tr('вернись', lang)) and (is_private or is_reply):
            BLOCKS[chat_id_full] = 0
            bot.reply_to(message, tr('Автоперевод включен', lang), reply_markup=get_keyboard('hide', message))
            my_log.log_echo(message, 'Выключена блокировка автопереводов в чате')
            return
        # если сообщение начинается на 'забудь' то стираем историю общения GPT
        if msg.startswith(tr('забудь', lang)) and (is_private or is_reply):
            if CHAT_MODE[chat_id_full] == 'bard':
                my_bard.reset_bard_chat(chat_id_full)
                my_log.log_echo(message, 'История барда принудительно отчищена')
            if CHAT_MODE[chat_id_full] == 'gemini':
                my_gemini.reset(chat_id_full)
                my_log.log_echo(message, 'История Gemini Pro принудительно отчищена')
            elif CHAT_MODE[chat_id_full] == 'claude':
                my_claude.reset_claude_chat(chat_id_full)
                my_log.log_echo(message, 'История клода принудительно отчищена')
            elif CHAT_MODE[chat_id_full] == 'chatgpt':
                gpt_basic.chat_reset(chat_id_full)
                my_log.log_echo(message, 'История GPT принудительно отчищена')
            bot.reply_to(message, tr('Ок', lang), reply_markup=get_keyboard('hide', message))
            return

        # если это номер телефона
        # удалить из текста все символы кроме цифр
        if len(msg) < 18 and len(msg) > 9  and not re.search(r"[^0-9+\-()\s]", msg):
            number = re.sub(r'[^0-9]', '', msg)
            if number:
                if number.startswith(('7', '8')):
                    number = number[1:]
                if len(number) == 10:
                    if number in CACHE_CHECK_PHONE:
                        response = CACHE_CHECK_PHONE[number]
                    else:
                        check_blocked_user(chat_id_full)
                        with ShowAction(message, 'typing'):
                            if not allowed_chatGPT_user(message.chat.id):
                                my_log.log_echo(message, 'chatGPT запрещен [phonenumber]')
                                bot.reply_to(message, tr('You are not in allow chatGPT users list', lang))
                                return
                            else:
                                response = gpt_basic.check_phone_number(number)
                    if response:
                        CACHE_CHECK_PHONE[number] = response
                        response = utils.bot_markdown_to_html(response)
                        reply_to_long_message(message, response, parse_mode='HTML',
                                            reply_markup=get_keyboard('hide', message))
                        my_log.log_echo(message, response)
                        return

        # если в сообщении только ссылка на видео в тиктоке
        # предложить скачать это видео
        if my_tiktok.is_valid_url(message.text):
            bot.reply_to(message, message.text, disable_web_page_preview = True,
                         reply_markup=get_keyboard('download_tiktok', message))
            return

        # если в сообщении только ссылка и она отправлена боту в приват
        # тогда сумморизируем текст из неё
        if my_sum.is_valid_url(message.text) and is_private:
            # если в режиме клауда чата то закидываем веб страницу как файл прямо в него
            if chat_id_full in CHAT_MODE and CHAT_MODE[chat_id_full] == 'claude':
                with ShowAction(message, 'typing'):
                    file_name = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(10)) + '.txt'
                    text = my_sum.summ_url(message.text, True, lang)
                    # сгенерировать случайное имя папки во временной папке для этого файла
                    folder_name = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(10))
                    # создать эту папку во временной папке. как получить путь до временной папки в системе?
                    folder_path = os.path.join(tempfile.gettempdir(), folder_name)
                    os.mkdir(folder_path)
                    # сохранить файл в этой папке
                    full_path = os.path.join(folder_path, file_name)
                    with open(full_path, 'w', encoding='utf-8') as new_file:
                        new_file.write(text)
                    caption = message.caption or '?'
                    message.text = f'[File uploaded for Claude] [{file_name}] ' + caption
                    my_log.log_echo(message)
                    try:
                        response = my_claude.chat(caption, chat_id_full, False, full_path)
                        response = utils.bot_markdown_to_html(response)
                    except Exception as error:
                        print(f'tb:handle_document_thread:claude: {error}')
                        my_log.log2(f'tb:handle_document_thread:claude: {error}')
                        msg = tr('Что-то пошло не так', lang)
                        bot.reply_to(message, msg)
                        my_log.log2(msg)
                        os.remove(full_path)
                        os.rmdir(folder_path)
                        return
                    # удалить сначала файл а потом и эту папку
                    os.remove(full_path)
                    os.rmdir(folder_path)
                    my_log.log_echo(message, response)
                    reply_to_long_message(message, response, parse_mode='HTML',
                                          reply_markup=get_keyboard('claude_chat', message))
                return
            message.text = '/sum ' + message.text
            summ_text(message)
            return

        # проверяем просят ли нарисовать что-нибудь
        if msg.startswith((tr('нарисуй', lang) + ' ', tr('нарисуй', lang) + ',')):
            check_blocked_user(chat_id_full)
            # prompt = message.text[8:]
            prompt = message.text.split(' ', 1)[1]
            message.text = f'/image {prompt}'
            image_thread(message)
            n = [{'role':'system', 'content':f'user {tr("попросил нарисовать", lang)}\n{prompt}'},
                 {'role':'system', 'content':f'assistant {tr("нарисовал с помощью DALL-E", lang)}'}]
            if chat_id_full in gpt_basic.CHATS:
                gpt_basic.CHATS[chat_id_full] += n
            else:
                gpt_basic.CHATS[chat_id_full] = n
            gpt_basic.CHATS[chat_id_full] = gpt_basic.CHATS[chat_id_full][-cfg.max_hist_lines:]
            return

        # Получить строку с локализованной датой
        formatted_date = datetime.datetime.now().strftime("%d %B %Y %H:%M")
        from_user_name = ((message.from_user.first_name or '') + ' ' + (message.from_user.last_name or '')).strip()
        if not from_user_name:
            from_user_name = message.from_user.username or 'unknown'
        # message.text = f'[{formatted_date}] [{from_user_name}] {message.text}'

        # можно перенаправить запрос к гуглу, но он долго отвечает
        # не локализуем
        if msg.startswith(('гугл ', 'гугл,', 'гугл\n')):
            message.text = f'/google {msg[5:]}'
            google(message)
            return

        # можно перенаправить запрос к DuckDuckGo, но он долго отвечает
        # не локализуем
        elif msg.startswith(('утка ', 'утка,', 'утка\n')):
            message.text = f'/ddg {msg[5:]}'
            ddg(message)
            return
        # так же надо реагировать если это ответ в чате на наше сообщение или диалог происходит в привате
        elif is_reply or is_private or bot_name_used:
            # if len(msg) > cfg.max_message_from_user and (chat_id_full in CHAT_MODE and CHAT_MODE[chat_id_full] != 'claude'):
            if len(msg) > cfg.max_message_from_user:
                bot.reply_to(message, f'{tr("Слишком длинное сообщение для чат-бота:", lang)} {len(msg)} {tr("из", lang)} {cfg.max_message_from_user}')
                my_log.log_echo(message, f'Слишком длинное сообщение для чат-бота: {len(msg)} из {cfg.max_message_from_user}')
                return

            if chat_id_full not in VOICE_ONLY_MODE:
                VOICE_ONLY_MODE[chat_id_full] = False
            if VOICE_ONLY_MODE[chat_id_full]:
                action = 'record_audio'
                message.text = f'[{tr("голосовое сообщение, возможны ошибки распознавания речи, отвечай коротко и просто без форматирования текста - ответ будет зачитан вслух", lang)}]: ' + message.text
            else:
                action = 'typing'


            # если активирован режим общения с Gemini Pro
            if CHAT_MODE[chat_id_full] == 'gemini' and not FIRST_DOT:
                check_blocked_user(chat_id_full)
                if len(msg) > my_gemini.MAX_REQUEST:
                    bot.reply_to(message, f'{tr("Слишком длинное сообщение для Gemini:", lang)} {len(msg)} {tr("из", lang)} {my_gemini.MAX_REQUEST}')
                    my_log.log_echo(message, f'Слишком длинное сообщение для Gemini: {len(msg)} из {my_gemini.MAX_REQUEST}')
                    return
                message.text = f'[{formatted_date}] [{from_user_name}] [answer in a short and objective way]: {message.text}'
                with ShowAction(message, action):
                    try:
                        answer = my_gemini.chat(message.text, chat_id_full)

                        if not VOICE_ONLY_MODE[chat_id_full]:
                            answer = utils.bot_markdown_to_html(answer)
                        if answer:
                            my_log.log_echo(message, answer)
                            try:
                                reply_to_long_message(message, answer, parse_mode='HTML', disable_web_page_preview = True, 
                                                      reply_markup=get_keyboard('gemini_chat', message))
                            except Exception as error:
                                print(f'tb:do_task: {error}')
                                my_log.log2(f'tb:do_task: {error}')
                                reply_to_long_message(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                      reply_markup=get_keyboard('gemini_chat', message))
                    except Exception as error3:
                        print(error3)
                        my_log.log2(str(error3))
                    return



            # если активирован режим общения с бард чатом
            if CHAT_MODE[chat_id_full] == 'bard' and not FIRST_DOT:
                check_blocked_user(chat_id_full)
                if len(msg) > my_bard.MAX_REQUEST:
                    bot.reply_to(message, f'{tr("Слишком длинное сообщение для барда:", lang)} {len(msg)} {tr("из", lang)} {my_bard.MAX_REQUEST}')
                    my_log.log_echo(message, f'Слишком длинное сообщение для барда: {len(msg)} из {my_bard.MAX_REQUEST}')
                    return
                message.text = f'[{formatted_date}] [{from_user_name}] [answer in a super short and objective way]: {message.text}'
                with ShowAction(message, action):
                    try:
                        # имя пользователя если есть или ник
                        user_name = message.from_user.first_name or message.from_user.username or ''
                        chat_name = message.chat.username or message.chat.first_name or message.chat.title or ''
                        if chat_name:
                            user_name = chat_name
                        answer = my_bard.chat(message.text, chat_id_full, user_name = user_name, lang = lang, is_private = is_private)

                        for x in my_bard.REPLIES:
                            if x[0] == answer:
                                images, links = x[1][:10], x[2]
                                # links_titles = utils.get_page_names(links)
                                # text_links = ''
                                # for link, title in links, links_titles:
                                #     text_links += f'<a href="{link}">{title}</a>\n'
                                break

                        # answer = my_bard.convert_markdown(answer)
                        # my_log.log_echo(message, answer, debug = True)
                        if not VOICE_ONLY_MODE[chat_id_full]:
                            answer = utils.bot_markdown_to_html(answer)
                        if answer:
                            my_log.log_echo(message, (answer + '\nPHOTO\n' + '\n'.join(images) + '\nLINKS\n' + '\n'.join(links)).strip())
                            try:
                                reply_to_long_message(message, answer, parse_mode='HTML', disable_web_page_preview = True, 
                                                      reply_markup=get_keyboard('bard_chat', message))
                            except Exception as error:
                                print(f'tb:do_task: {error}')
                                my_log.log2(f'tb:do_task: {error}')
                                reply_to_long_message(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                      reply_markup=get_keyboard('bard_chat', message))
                            if images:
                                images_group = [telebot.types.InputMediaPhoto(i) for i in images]
                                photos_ids = bot.send_media_group(message.chat.id, images_group[:10], reply_to_message_id=message.message_id)
                            # if links:
                            #     reply_to_long_message(message, text_links, parse_mode='HTML', disable_web_page_preview = True,
                            #                           reply_markup=get_keyboard('hide', message))
                    except Exception as error3:
                        print(error3)
                        my_log.log2(str(error3))
                    return

            # если активирован режим общения с клод чатом
            if CHAT_MODE[chat_id_full] == 'claude' and not FIRST_DOT:
                check_blocked_user(chat_id_full)
                if len(msg) > my_claude.MAX_QUERY:
                    bot.reply_to(message, f'{tr("Слишком длинное сообщение для Клода:", lang)} {len(msg)} {tr("из", lang)} {my_claude.MAX_QUERY}')
                    my_log.log_echo(message, f'Слишком длинное сообщение для Клода: {len(msg)} из {my_claude.MAX_QUERY}')
                    return
                message.text = f'[{formatted_date}] [{from_user_name}] [answer in a super short and objective way]: {message.text}'
                with ShowAction(message, action):
                    try:
                        answer = my_claude.chat(message.text, chat_id_full)
                        if not VOICE_ONLY_MODE[chat_id_full]:
                            answer = utils.bot_markdown_to_html(answer)
                        my_log.log_echo(message, answer)
                        if answer:
                            try:
                                reply_to_long_message(message, answer, parse_mode='HTML', disable_web_page_preview = True, 
                                                      reply_markup=get_keyboard('claude_chat', message))
                            except Exception as error:
                                print(f'tb:do_task: {error}')
                                my_log.log2(f'tb:do_task: {error}')
                                reply_to_long_message(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                      reply_markup=get_keyboard('claude_chat', message))
                    except Exception as error3:
                        print(error3)
                        my_log.log2(str(error3))
                    return

            # chatGPT
            # добавляем новый запрос пользователя в историю диалога пользователя
            with ShowAction(message, action):
                check_blocked_user(chat_id_full)
                if not allowed_chatGPT_user(message.chat.id):
                    my_log.log_echo(message, 'chatGPT запрещен')
                    bot.reply_to(message, tr('You are not in allow chatGPT users list, try other chatbot', lang))
                    return
                if len(msg) > cfg.CHATGPT_MAX_REQUEST:
                    bot.reply_to(message, f'{tr("Слишком длинное сообщение для chatGPT:", lang)} {len(msg)} {tr("из", lang)} {cfg.CHATGPT_MAX_REQUEST}')
                    my_log.log_echo(message, f'Слишком длинное сообщение для chatGPT: {len(msg)} из {cfg.CHATGPT_MAX_REQUEST}')
                    return
                # имя пользователя если есть или ник
                user_name = message.from_user.first_name or message.from_user.username or ''
                chat_name = message.chat.username or message.chat.first_name or message.chat.title or ''
                if chat_name:
                    user_name = chat_name
                # если это запрос к модели instruct
                if FIRST_DOT:
                    resp = gpt_basic.ai_instruct(message.text)
                else:
                    if chat_name:
                        resp = gpt_basic.chat(chat_id_full, message.text,
                                            user_name = user_name, lang=lang,
                                            is_private = False, chat_name=chat_name)
                    else:
                        resp = gpt_basic.chat(chat_id_full, message.text,
                                            user_name = user_name, lang=lang,
                                            is_private = is_private, chat_name=chat_name)
                if resp:
                    if not VOICE_ONLY_MODE[chat_id_full]:
                        resp = utils.bot_markdown_to_html(resp)
                    my_log.log_echo(message, resp)
                    try:
                        reply_to_long_message(message, resp, parse_mode='HTML',
                                              disable_web_page_preview = True,
                                              reply_markup=get_keyboard('chat', message))
                    except Exception as error2:
                        print(error2)
                        my_log.log2(resp)
                        reply_to_long_message(message, resp, parse_mode='',
                                              disable_web_page_preview = True,
                                              reply_markup=get_keyboard('chat', message))
        else: # смотрим надо ли переводить текст
            if check_blocks(chat_id_full) and not is_private:
                return
            text = my_trans.translate(message.text)
            if text:
                bot.reply_to(message, text, parse_mode='Markdown',
                             reply_markup=get_keyboard('translate', message))
                my_log.log_echo(message, text)


def main():
    """
    Runs the main function, which sets default commands and starts polling the bot.
    """
    # set_default_commands()

    bot.polling(timeout=90, long_polling_timeout=90)


if __name__ == '__main__':
    main()
