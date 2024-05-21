#!/usr/bin/env python3

import chardet
import datetime
import io
import os
import re
import tempfile
import traceback
import threading
import time

import langcodes
import prettytable
import PyPDF2
import telebot
from collections import defaultdict
from fuzzywuzzy import fuzz
from sqlitedict import SqliteDict
from datetime import timedelta

import cfg
import bing_img
import my_genimg
import my_dic
import my_google
import my_gemini
import my_groq
import my_log
import my_ocr
import my_openrouter
import my_pandoc
import my_stt
import my_sum
import my_trans
import my_tts
import utils


# устанавливаем рабочую папку = папке в которой скрипт лежит
os.chdir(os.path.abspath(os.path.dirname(__file__)))

bot = telebot.TeleBot(cfg.token)
# bot = telebot.TeleBot(cfg.token, skip_pending=True)

_bot_name = bot.get_me().username
BOT_ID = bot.get_me().id


# телеграм группа для отправки сгенерированных картинок
pics_group = cfg.pics_group
pics_group_url = cfg.pics_group_url


# до 500 одновременных потоков для чата с гпт
semaphore_talks = threading.Semaphore(500)

# папка для постоянных словарей, памяти бота
if not os.path.exists('db'):
    os.mkdir('db')

# запоминаем время последнего обращения к боту
LAST_TIME_ACCESS = SqliteDict('db/last_time_access.db', autocommit=True)

# сколько картинок нарисовано юзером {id: counter}
IMAGES_BY_USER_COUNTER = SqliteDict('db/images_by_user_counter.db', autocommit=True)

# запоминаем уникальные хелпы и приветствия, сбрасывать при смене языка
HELLO_MSG = SqliteDict('db/msg_hello.db', autocommit=True)
HELP_MSG = SqliteDict('db/msg_help.db', autocommit=True)

# для хранения загруженных юзерами текстов, по этим текстам можно делать запросы командой /file
# {user_id(str): (filename or link (str), text(str))}
USER_FILES = SqliteDict('db/user_files.db', autocommit=True)

# заблокированные юзера {id:True/False}
BAD_USERS = my_dic.PersistentDict('db/bad_users.pkl')

# в каких чатах какой чатбот отвечает {chat_id_full(str):chatbot(str)}
# 'gemini', 'gemini15'
CHAT_MODE = my_dic.PersistentDict('db/chat_mode.pkl')

# учет сообщений, кто с кем и сколько говорил
# {time(str(timestamp)): (user_id(str), chat_mode(str))}
CHAT_STATS = SqliteDict('db/chat_stats.db', autocommit=True)
CHAT_STATS_LOCK = threading.Lock()
# cache, {userid:gemini message counter}
CHAT_STATS_TEMP = {}

# блокировка чата что бы юзер не мог больше 1 запроса делать за раз,
# только для запросов к гпт*. {chat_id_full(str):threading.Lock()}
CHAT_LOCKS = {}

# в каких чатах выключены автопереводы. 0 - выключено, 1 - включено
BLOCKS = my_dic.PersistentDict('db/blocks.pkl')

# каким голосом озвучивать, мужским или женским
TTS_GENDER = my_dic.PersistentDict('db/tts_gender.pkl')

# хранилище номеров тем в группе для логов {full_user_id as str: theme_id as int}
# full_user_id - полный адрес места которое логируется, либо это юзер ип и 0 либо группа и номер в группе
# theme_id - номер темы в группе для логов
LOGS_GROUPS_DB = SqliteDict('db/logs_groups.db', autocommit=True)

# запоминаем пары хеш-промтп для работы клавиатуры которая рисует по сгенерированным с помощью ИИ подсказкам
# {hash:prompt, ...}
IMAGE_SUGGEST_BUTTONS = SqliteDict('db/image_suggest_buttons.db', autocommit=True)

# включены ли подсказки для рисования в этом чате
# {chat_id: True/False}
SUGGEST_ENABLED = SqliteDict('db/image_suggest_enabled.db', autocommit=True)

# что бы бот работал в публичном чате администратор должен его активировать {id:True/False}
CHAT_ENABLED = SqliteDict('db/chat_enabled.db', autocommit=True)

# в каком чате включен режим без подсказок, боту не будет сообщаться время место и роль,
# он будет работать как в оригинале {id:True/False}
ORIGINAL_MODE = SqliteDict('db/original_mode.db', autocommit=True)

# запоминаем у какого юзера какой язык OCR выбран
OCR_DB = my_dic.PersistentDict('db/ocr_db.pkl')

# для запоминания ответов на команду /sum
SUM_CACHE = SqliteDict('db/sum_cache.db', autocommit=True)

# {chat_id:role} какие роли - дополнительные инструкции в чате
ROLES = my_dic.PersistentDict('db/roles.pkl')

# в каких чатах активирован режим суперчата, когда бот отвечает на все реплики всех участников
# {chat_id:0|1}
SUPER_CHAT = my_dic.PersistentDict('db/super_chat.pkl')

# в каких чатах надо просто транскрибировать голосовые сообщения, не отвечая на них
TRANSCRIBE_ONLY_CHAT = my_dic.PersistentDict('db/transcribe_only_chat.pkl')

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

# кешировать запросы типа кто звонил {number:(result, full text searched)}
CACHE_CHECK_PHONE = {}

# {user_id:lang(2 symbol codes)}
LANGUAGE_DB = my_dic.PersistentDict('db/language_db.pkl')

# Глобальный массив для хранения состояния подписки (user_id: timestamp)
subscription_cache = {}

# хранилище для переводов сообщений сделанных гугл переводчиком
# key: (text, lang)
# value: translated text
AUTO_TRANSLATIONS = SqliteDict('db/auto_translations.db', autocommit=True)

# запоминаем прилетающие сообщения, если они слишком длинные и
# были отправлены клиентом по кускам {id:[messages]}
# ловим сообщение и ждем полсекунды не прилетит ли еще кусок
MESSAGE_QUEUE = {}

# блокировать процесс отправки картинок что бы не было перемешивания разных запросов
SEND_IMG_LOCK = threading.Lock()

# {user_id:lock} не давать рисовать больше чем 1 поток на юзера
IMG_GEN_LOCKS = {}

# настройки температуры для gemini {chat_id:temp}
GEMIMI_TEMP = my_dic.PersistentDict('db/gemini_temperature.pkl')
GEMIMI_TEMP_DEFAULT = 0.2

# Из каких чатов надо выходиьт сразу (забаненые)
LEAVED_CHATS = my_dic.PersistentDict('db/leaved_chats.pkl')

# в каких чатах какое у бота кодовое слово для обращения к боту
BOT_NAMES = my_dic.PersistentDict('db/names.pkl')
# имя бота по умолчанию, в нижнем регистре без пробелов и символов
BOT_NAME_DEFAULT = cfg.default_bot_name

# тут сохраняются сообщения до и после преобразования из маркдауна ботов в хтмл
# {ответ после преобразования:ответ до преобразования, }
# это нужно только что бы записать в логи пару если html версия не пролезла через телеграм фильтр
DEBUG_MD_TO_HTML = {}

# запоминаем кто ответил что бы добавить это в лог в группу
# {user_id: 'chatbot'(gemini, gemini15 etc)}
WHO_ANSWERED = {}


supported_langs_trans = [
        "af","am","ar","az","be","bg","bn","bs","ca","ceb","co","cs","cy","da","de",
        "el","en","eo","es","et","eu","fa","fi","fr","fy","ga","gd","gl","gu","ha",
        "haw","he","hi","hmn","hr","ht","hu","hy","id","ig","is","it","iw","ja","jw",
        "ka","kk","km","kn","ko","ku","ky","la","lb","lo","lt","lv","mg","mi","mk",
        "ml","mn","mr","ms","mt","my","ne","nl","no","ny","or","pa","pl","ps","pt",
        "ro","ru","rw","sd","si","sk","sl","sm","sn","so","sq","sr","st","su","sv",
        "sw","ta","te","tg","th","tl","tr","ua","uk","ur","uz","vi","xh","yi","yo","zh",
        "zh-TW","zu"]
supported_langs_tts = [
        'af', 'am', 'ar', 'as', 'az', 'be', 'bg', 'bn', 'bs', 'ca', 'cs', 'cy', 'da',
        'de', 'el', 'en', 'eo', 'es', 'et', 'eu', 'fa', 'fi', 'fil', 'fr', 'ga', 'gl',
        'gu', 'he', 'hi', 'hr', 'ht', 'hu', 'hy', 'id', 'is', 'it', 'ja', 'jv', 'ka',
        'kk', 'km', 'kn', 'ko', 'ku', 'ky', 'la', 'lb', 'lo', 'lt', 'lv', 'mg', 'mi',
        'mk', 'ml', 'mn', 'mr', 'ms', 'mt', 'my', 'nb', 'ne', 'nl', 'nn', 'no', 'ny',
        'or', 'pa', 'pl', 'ps', 'pt', 'ro', 'ru', 'rw', 'sd', 'si', 'sk', 'sl', 'sm',
        'sn', 'so', 'sq', 'sr', 'st', 'su', 'sv', 'sw', 'ta', 'te', 'tg', 'th', 'tk',
        'tl', 'tr', 'tt', 'ua', 'ug', 'uk', 'ur', 'uz', 'vi', 'xh', 'yi', 'yo', 'zh', 'zu']


class MessageCounter:
    def __init__(self):
        # self.messages = SqliteDict('db/message_counter.db', autocommit=True) # не работает почему то
        # self.messages = {}
        self.messages = my_dic.PersistentDict('db/message_counter.pkl')
        self.lock = threading.Lock()

    def increment(self, userid, n=1):
        now = datetime.datetime.now()
        with self.lock:
            for _ in range(n):
                if userid not in self.messages:
                    self.messages[userid] = []
                self.messages[userid].append(now)
            self._cleanup(userid)

    def status(self, userid):
        with self.lock:
            self._cleanup(userid)
            # my_log.log2(f'message_counter: {userid} {len(self.messages[userid])}')
            return len(self.messages[userid])

    def _cleanup(self, userid):
        now = datetime.datetime.now()
        one_day_ago = now - timedelta(days=1)
        if userid not in self.messages:
            self.messages[userid] = []
        self.messages[userid] = [timestamp for timestamp in self.messages[userid] if timestamp > one_day_ago]


# запоминаем сколько сообщений от юзера за сутки было
GEMINI15_COUNTER = MessageCounter()


class RequestCounter:
    """Ограничитель числа запросов к боту
    не дает делать больше 10 в минуту, банит на cfg.DDOS_BAN_TIME сек после превышения"""
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
    """A thread that can be stopped. Continuously sends a notification of activity to the chat.
    Telegram automatically extinguishes the notification after 5 seconds, so it must be repeated.

    To use in the code, you need to do something like this:
    with ShowAction(message, 'typing'):
        do something and while doing it the notification does not go out
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
        self.is_topic = True if message.is_topic_message else False
        self.action = action
        self.is_running = True
        self.timerseconds = 1
        self.started_time = time.time()

    def run(self):
        while self.is_running:
            if time.time() - self.started_time > 60*5:
                self.stop()
                my_log.log2(f'tb:show_action:stoped after 5min [{self.chat_id}] [{self.thread_id}] is topic: {self.is_topic} action: {self.action}')
                return
            try:
                if self.is_topic:
                    bot.send_chat_action(self.chat_id, self.action, message_thread_id = self.thread_id)
                else:
                    bot.send_chat_action(self.chat_id, self.action)
            except Exception as error:
                if 'A request to the Telegram API was unsuccessful. Error code: 429. Description: Too Many Requests' not in str(error):
                    if 'Forbidden: bot was blocked by the user' in str(error):
                        self.stop()
                        return
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


def tr(text: str, lang: str, help: str = '') -> str:
    """
    This function translates text to the specified language,
    using either the AI translation engine or the standard translation engine.

    Args:
        text: The text to translate.
        lang: The language to translate to.
        help: The help text for ai translator.

    Returns:
        The translated text.
    """
    # перевод на этот язык не работает?
    if lang == 'fa':
        lang = 'en'
    if lang == 'ua':
        lang = 'uk'

    key = str((text, lang, help))
    if key in AUTO_TRANSLATIONS:
        return AUTO_TRANSLATIONS[key]

    translated = ''

    if help:
        translated = my_gemini.translate(text, to_lang=lang, help=help)
        if not translated:
            time.sleep(1)
            # try again
            translated = my_gemini.translate(text, to_lang=lang, help=help)
            if not translated:
                my_log.log_translate(f'gemini\n\n{text}\n\n{lang}\n\n{help}')

    if not translated:
        translated = my_trans.translate_text2(text, lang)

    if translated:
        AUTO_TRANSLATIONS[key] = translated
    else:
        AUTO_TRANSLATIONS[key] = text
    return AUTO_TRANSLATIONS[key]


def add_to_bots_mem(query: str, resp: str, chat_id_full: str):
    if chat_id_full not in CHAT_MODE:
        CHAT_MODE[chat_id_full] = cfg.chat_mode_default
    if 'gemini' in CHAT_MODE[chat_id_full]:
        my_gemini.update_mem(query, resp, chat_id_full)
    elif 'llama3' in CHAT_MODE[chat_id_full]:
        my_groq.update_mem(query, resp, chat_id_full)
    elif 'openrouter' in CHAT_MODE[chat_id_full]:
        my_openrouter.update_mem(query, resp, chat_id_full)


def img2txt(text, lang: str, chat_id_full: str, query: str = '') -> str:
    """
    Generate the text description of an image.

    Args:
        text (str): The image file URL or downloaded data(bytes).
        lang (str): The language code for the image description.
        chat_id_full (str): The full chat ID.

    Returns:
        str: The text description of the image.
    """
    if isinstance(text, bytes):
        data = text
    else:
        data = utils.download_image_as_bytes(text)
    if not query:
        query = tr('Что изображено на картинке? Напиши подробное описание, и объясни подробно что это может означать. Затем напиши длинный подробный промпт одним предложением для рисования этой картинки с помощью нейросетей, начни промпт со слов /image Create image of...', lang)

    if chat_id_full not in CHAT_MODE:
        CHAT_MODE[chat_id_full] = cfg.chat_mode_default

    text = ''

    try:
        text = my_gemini.img2txt(data, query)
    except Exception as img_from_link_error:
        my_log.log2(f'tb:img2txt: {img_from_link_error}')

    if text:
        add_to_bots_mem(tr('User asked about a picture:', lang) + ' ' + query, text, chat_id_full)

    return text


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


def check_blocked_user(id: str, from_user_id: int, check_trottle = True):
    """Raises an exception if the user is blocked and should not be replied to"""
    for x in cfg.admins:
        if id == f'[{x}] [0]':
            return
    user_id = id.replace('[','').replace(']','').split()[0]
    if check_trottle:
        if not request_counter.check_limit(user_id):
            my_log.log2(f'tb:check_blocked_user: User {id} is blocked for DDoS')
            raise Exception(f'user {user_id} in ddos stop list, ignoring')

    from_user_id = f'[{from_user_id}] [0]'
    if from_user_id in BAD_USERS and BAD_USERS[from_user_id]:
        my_log.log2(f'tb:check_blocked_user: User {from_user_id} is blocked')
        raise Exception(f'user {from_user_id} in stop list, ignoring')

    for i in BAD_USERS:
        u_id = i.replace('[','').replace(']','').split()[0]
        if u_id == user_id:
            if BAD_USERS[id]:
                my_log.log2(f'tb:check_blocked_user: User {id} is blocked')
                raise Exception(f'user {user_id} in stop list, ignoring')


def is_admin_member(message: telebot.types.Message):
    """Checks if the user is an admin member of the chat."""
    try:
        if message.data: # its a callback
            is_private = message.message.chat.type == 'private'
            if is_private:
                return True
    except AttributeError:
        pass

    if not message:
        return False
    if message.from_user.id in cfg.admins:
        return True
    try:
        chat_id = message.chat.id
    except AttributeError: # its a callback
        chat_id = message.message.chat.id
    user_id = message.from_user.id
    member = bot.get_chat_member(chat_id, user_id).status.lower()
    return True if 'creator' in member or 'administrator' in member else False


def is_for_me(message: telebot.types.Message):
    """Checks who the command is addressed to, this bot or another one.

    /cmd@botname args

    Returns (True/False, 'the same command but without the bot name').
    If there is no bot name at all, assumes that the command is addressed to this bot.
    """
    cmd = message.text
    is_private = message.chat.type == 'private'

    # если не в привате, то есть в чате
    if not is_private and message.text:
        if message.text.lower().startswith('/'):
            cmd_ = message.text.lower().split(maxsplit=1)[0].strip()
            # и если команда не обращена к этому боту
            if not cmd_.endswith(f'@{_bot_name}'):
                return (False, cmd)

    # for not text command (audio, video, documents etc)
    if not cmd:
        return (True, cmd)

    # если это не команда значит ко мне
    if not cmd.startswith('/'):
        return (True, cmd)

    command_parts = cmd.split()
    first_arg = command_parts[0]

    if '@' in first_arg:
        message_cmd = first_arg.split('@', maxsplit=1)[0]
        message_bot = first_arg.split('@', maxsplit=1)[1] if len(first_arg.split('@', maxsplit=1)) > 1 else ''
        message_args = cmd.split(maxsplit=1)[1] if len(command_parts) > 1 else ''
        return (message_bot == _bot_name, f'{message_cmd} {message_args}'.strip())
    else:
        return (True, cmd)


def log_message(message: telebot.types.Message):
    try:
        if isinstance(message, telebot.types.Message) and hasattr(cfg, 'DO_NOT_LOG') and message.chat.id in cfg.DO_NOT_LOG:
            return

        if not hasattr(cfg, 'LOGS_GROUP') or not cfg.LOGS_GROUP:
            return

        if isinstance(message, telebot.types.Message):
            chat_full_id = get_topic_id(message)
            chat_name = utils.get_username_for_log(message)
            if chat_full_id in LOGS_GROUPS_DB:
                th = LOGS_GROUPS_DB[chat_full_id]
            else:
                th = bot.create_forum_topic(cfg.LOGS_GROUP, chat_full_id + ' ' + chat_name).message_thread_id
                LOGS_GROUPS_DB[chat_full_id] = th
            chat_id_full = get_topic_id(message)
            if chat_id_full in WHO_ANSWERED:
                try:
                    bot.send_message(cfg.LOGS_GROUP, f'[{WHO_ANSWERED[chat_id_full]}]', message_thread_id=th)
                except Exception as unknown:
                    if 'Bad Request: message thread not found' in str(unknown):
                        LOGS_GROUPS_DB[chat_full_id] = bot.create_forum_topic(cfg.LOGS_GROUP, chat_full_id + ' ' + chat_name).message_thread_id
                        th = LOGS_GROUPS_DB[chat_full_id]
                        bot.send_message(cfg.LOGS_GROUP, f'[{WHO_ANSWERED[chat_id_full]}]', message_thread_id=th)
                try:
                    del WHO_ANSWERED[chat_id_full]
                except KeyError:
                    pass
            try:
                bot.copy_message(cfg.LOGS_GROUP, message.chat.id, message.message_id, message_thread_id=th)
            except Exception as unknown:
                if 'Bad Request: message thread not found' in str(unknown):
                    LOGS_GROUPS_DB[chat_full_id] = bot.create_forum_topic(cfg.LOGS_GROUP, chat_full_id + ' ' + chat_name).message_thread_id
                    th = LOGS_GROUPS_DB[chat_full_id]
                    bot.copy_message(cfg.LOGS_GROUP, message.chat.id, message.message_id, message_thread_id=th)
        elif isinstance(message, list):
            chat_full_id = get_topic_id(message[0])
            chat_name = utils.get_username_for_log(message[0])
            if chat_full_id in LOGS_GROUPS_DB:
                th = LOGS_GROUPS_DB[chat_full_id]
            else:
                th = bot.create_forum_topic(cfg.LOGS_GROUP, chat_full_id + ' ' + chat_name).message_thread_id
                LOGS_GROUPS_DB[chat_full_id] = th
            m_ids = [x.message_id for x in message]
            try:
                bot.copy_messages(cfg.LOGS_GROUP, message[0].chat.id, m_ids, message_thread_id=th)
            except Exception as unknown:
                if 'Bad Request: message thread not found' in str(unknown):
                    LOGS_GROUPS_DB[chat_full_id] = bot.create_forum_topic(cfg.LOGS_GROUP, chat_full_id + ' ' + chat_name).message_thread_id
                    th = LOGS_GROUPS_DB[chat_full_id]
                    bot.copy_messages(cfg.LOGS_GROUP, message[0].chat.id, m_ids, message_thread_id=th)
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log2(f'tb:log_message: {error}\n\n{error_traceback}')


def authorized_owner(message: telebot.types.Message) -> bool:
    """if chanel owner or private"""
    is_private = message.chat.type == 'private'

    if not (is_private or is_admin_member(message)):
        bot_reply_tr(message, "This command is only available to administrators")
        return False
    return authorized(message)


def authorized_admin(message: telebot.types.Message) -> bool:
    """if admin"""
    if message.from_user.id not in cfg.admins:
        bot_reply_tr(message, "This command is only available to administrators")
        return False
    return authorized(message)


def authorized_callback(call: telebot.types.CallbackQuery) -> bool:
    # никаких проверок для админов
    if call.from_user.id in cfg.admins:
        return True

    chat_id_full = f'[{call.from_user.id}] [0]'

    # check for blocking and throttling
    try:
        check_blocked_user(chat_id_full, call.from_user.id, check_trottle=False)
    except:
        return False

    return True


def check_subscription(message: telebot.types.Message) -> bool:
    """проверка обязательной подписки на канал"""

    current_time = time.time()
    u_id = message.from_user.id

    try:
        # имеет смысл только в привате?
        if message.chat.type != 'private':
            return True

        if hasattr(cfg, 'subscribe_channel_id') \
            and hasattr(cfg, 'subscribe_channel_mes') \
            and hasattr(cfg, 'subscribe_channel_time'):

            # Проверяем, есть ли пользователь в кэше и не истекло ли время
            if u_id in subscription_cache and current_time - subscription_cache[u_id] < cfg.subscribe_channel_cache:
                return True  # Пользователь подписан (по кэшу)
            st = bot.get_chat_member(cfg.subscribe_channel_id, u_id).status
            if not st:
                bot_reply_tr(message, cfg.subscribe_channel_mes)
                return False
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log2(f'tb:check_blocks: {error}\n\n{error_traceback}\n\n{u_id}')

    # Пользователь подписан, обновляем кэш
    subscription_cache[u_id] = current_time
    return True


def chat_enabled(message: telebot.types.Message) -> bool:
    """check if chat is enabled"""
    chat_id_full = get_topic_id(message)
    if message.chat.type == 'private':
        return True
    if chat_id_full in CHAT_ENABLED and CHAT_ENABLED[chat_id_full]:
        return True
    return False


def authorized(message: telebot.types.Message) -> bool:
    """
    Check if the user is authorized based on the given message.

    Parameters:
        message (telebot.types.Message): The message object containing the chat ID and user ID.

    Returns:
        bool: True if the user is authorized, False otherwise.
    """

    # do not process commands to another bot /cmd@botname args
    if is_for_me(message)[0]:
        message.text = is_for_me(message)[1]
    else:
        return False

    if message.text:
        my_log.log_echo(message)
    else:
        my_log.log_media(message)

    log_message(message)

    # никаких проверок и тротлинга для админов
    if message.from_user.id in cfg.admins:
        return True

    # if this chat was forcibly left (banned), then when trying to enter it immediately exit
    # I don't know how to do that, so I have to leave only when receiving any event
    if message.chat.id in LEAVED_CHATS and LEAVED_CHATS[message.chat.id]:
        try:
            bot.leave_chat(message.chat.id)
            my_log.log2('tb:leave_chat: auto leave ' + str(message.chat.id))
        except Exception as leave_chat_error:
            my_log.log2(f'tb:auth:live_chat_error: {leave_chat_error}')
        return False

    chat_id_full = get_topic_id(message)

    LAST_TIME_ACCESS[chat_id_full] = time.time()

    # trottle only messages addressed to me
    is_private = message.chat.type == 'private'
    if chat_id_full not in SUPER_CHAT:
        SUPER_CHAT[chat_id_full] = 0
    if SUPER_CHAT[chat_id_full] == 1:
        is_private = True

    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == BOT_ID

    if message.text:
        msg = message.text.lower()

        if msg.startswith('.'):
            msg = msg[1:]

        if chat_id_full in BOT_NAMES:
            bot_name = BOT_NAMES[chat_id_full]
        else:
            bot_name = BOT_NAME_DEFAULT
            BOT_NAMES[chat_id_full] = bot_name

        bot_name_used = False
        if msg.startswith((f'{bot_name} ', f'{bot_name},', f'{bot_name}\n')):
            bot_name_used = True

        bot_name2 = f'@{_bot_name}'
        if msg.startswith((f'{bot_name2} ', f'{bot_name2},', f'{bot_name2}\n')):
            bot_name_used = True

        # разрешить удаление своей истории всем
        if msg == '/purge':
            return True

        if is_reply or is_private or bot_name_used:
            # check for blocking and throttling
            try:
                check_blocked_user(chat_id_full, message.from_user.id)
            except:
                return False
    else:
        try:
            check_blocked_user(chat_id_full, message.from_user.id)
        except:
            return False

    if message.text:
        if not chat_enabled(message) and not message.text.startswith('/enable'):
            return False
    if not check_subscription(message):
        return False

    # этого тут быть не должно но яхз что пошло не так, дополнительная проверка
    if chat_id_full in BAD_USERS and BAD_USERS[chat_id_full]:
        my_log.log2(f'tb:authorized: User {chat_id_full} is blocked')
        return False

    return True


def authorized_log(message: telebot.types.Message) -> bool:
    """
    Only log and banned
    """

    # do not process commands to another bot /cmd@botname args
    if is_for_me(message)[0]:
        message.text = is_for_me(message)[1]
    else:
        return False

    if message.text:
        my_log.log_echo(message)
    else:
        my_log.log_media(message)

    log_message(message)

    # if this chat was forcibly left (banned), then when trying to enter it immediately exit
    # I don't know how to do that, so I have to leave only when receiving any event
    if message.chat.id in LEAVED_CHATS and LEAVED_CHATS[message.chat.id]:
        try:
            bot.leave_chat(message.chat.id)
            my_log.log2('tb:leave_chat: auto leave ' + str(message.chat.id))
        except Exception as leave_chat_error:
            my_log.log2(f'tb:auth:live_chat_error: {leave_chat_error}')
        return False

    return True


def check_blocks(chat_id: str) -> bool:
    """в каких чатах выключены автопереводы"""
    if chat_id not in BLOCKS:
        BLOCKS[chat_id] = 0
    return False if BLOCKS[chat_id] == 1 else True


def disabled_kbd(chat_id_full):
    """проверяет не отключена ли тут клавиатура"""
    if chat_id_full not in DISABLED_KBD:
        DISABLED_KBD[chat_id_full] = True
    return DISABLED_KBD[chat_id_full]


def bot_reply_tr(message: telebot.types.Message,
              msg: str,
              parse_mode: str = None,
              disable_web_page_preview: bool = None,
              reply_markup: telebot.types.InlineKeyboardMarkup = None,
              send_message: bool = False,
              not_log: bool = False,
              allow_voice: bool = False):
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    msg = tr(msg, lang)
    bot_reply(message, msg, parse_mode, disable_web_page_preview, reply_markup, send_message, not_log, allow_voice)


def bot_reply(message: telebot.types.Message,
              msg: str,
              parse_mode: str = None,
              disable_web_page_preview: bool = None,
              reply_markup: telebot.types.InlineKeyboardMarkup = None,
              send_message: bool = False,
              not_log: bool = False,
              allow_voice: bool = False):
    """Send message from bot and log it"""
    try:
        if reply_markup is None:
            reply_markup = get_keyboard('hide', message)

        if not not_log:
            my_log.log_echo(message, msg)

        if send_message:
            send_long_message(message, msg, parse_mode=parse_mode,
                                disable_web_page_preview=disable_web_page_preview,
                                reply_markup=reply_markup, allow_voice=allow_voice)
        else:
            reply_to_long_message(message, msg, parse_mode=parse_mode, disable_web_page_preview=disable_web_page_preview,
                            reply_markup=reply_markup, allow_voice=allow_voice)
    except Exception as unknown:
        my_log.log2(f'tb:bot_reply: {unknown}')


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

    if kbd == 'mem':
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
    elif kbd == 'select_lang':
        markup  = telebot.types.InlineKeyboardMarkup(row_width=2)
        most_used_langs = ['en', 'zh', 'es', 'ar', 'hi', 'pt', 'bn', 'ru', 'ja', 'de', 'fr', 'it', 'tr', 'ko', 'id', 'vi']
        pair = []
        for x in most_used_langs:
            native_name = langcodes.Language.make(language=x).display_name(language=x).capitalize()
            # english_name = langcodes.Language.make(language=x).display_name(language='en').capitalize()
            # lang_name = f'{english_name} ({native_name})'
            lang_name = f'{native_name}'
            cb = f'select_lang-{x}'
            button = telebot.types.InlineKeyboardButton(lang_name, callback_data=cb)
            pair.append(button)
            if len(pair) == 2:
                markup.row(pair[0], pair[1])
                pair = []
        if len(pair) == 2:
            markup.row(pair[0], pair[1])
        if len(pair) == 1:
            markup.row(pair[0])
        button1 = telebot.types.InlineKeyboardButton(tr("Отмена", lang), callback_data='erase_answer')
        markup.row(button1)
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
    elif kbd == 'start':
        b_msg_draw = tr('🎨 Нарисуй', lang, 'это кнопка в телеграм боте для рисования, после того как юзер на нее нажимает у него запрашивается описание картинки, сделай перевод таким же коротким что бы надпись уместилась на кнопке, сохрани оригинальную эмодзи')
        b_msg_search = tr('🌐 Найди', lang, 'это кнопка в телеграм боте для поиска в гугле, после того как юзер на нее нажимает бот спрашивает у него что надо найти, сделай перевод таким же коротким что бы надпись уместилась на кнопке, сохрани оригинальную эмодзи')
        b_msg_summary = tr('📋 Перескажи', lang, 'это кнопка в телеграм боте для пересказа текста, после того как юзер на нее нажимает бот спрашивает у него ссылку на текст или файл с текстом, сделай перевод таким же коротким что бы надпись уместилась на кнопке, сохрани оригинальную эмодзи')
        b_msg_tts = tr('🎧 Озвучь', lang, 'это кнопка в телеграм боте для озвучивания текста, после того как юзер на нее нажимает бот спрашивает у него текст для озвучивания, сделай перевод таким же коротким что бы надпись уместилась на кнопке, сохрани оригинальную эмодзи')
        b_msg_translate = tr('🈶 Перевод', lang, 'это кнопка в телеграм боте для перевода текста, после того как юзер на нее нажимает бот спрашивает у него текст для перевода, сделай перевод таким же коротким что бы надпись уместилась на кнопке, сохрани оригинальную эмодзи')
        b_msg_settings = tr('⚙️ Настройки', lang, 'это кнопка в телеграм боте для перехода в настройки, сделай перевод таким же коротким что бы надпись уместилась на кнопке, сохрани оригинальную эмодзи')

        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
        button1 = telebot.types.KeyboardButton(b_msg_draw)
        button2 = telebot.types.KeyboardButton(b_msg_search)
        button3 = telebot.types.KeyboardButton(b_msg_summary)
        button4 = telebot.types.KeyboardButton(b_msg_tts)
        button5 = telebot.types.KeyboardButton(b_msg_translate)
        button6 = telebot.types.KeyboardButton(b_msg_settings)
        markup.row(button1, button2, button3)
        markup.row(button4, button5, button6)
        return markup

    elif kbd == 'openrouter_chat':
        if disabled_kbd(chat_id_full):
            return None
        markup  = telebot.types.InlineKeyboardMarkup(row_width=5)
        button0 = telebot.types.InlineKeyboardButton("➡", callback_data='continue_gpt')
        button1 = telebot.types.InlineKeyboardButton('♻️', callback_data='openrouter_reset')
        button2 = telebot.types.InlineKeyboardButton("🙈", callback_data='erase_answer')
        button3 = telebot.types.InlineKeyboardButton("📢", callback_data='tts')
        button4 = telebot.types.InlineKeyboardButton(lang, callback_data='translate_chat')
        markup.add(button0, button1, button2, button3, button4)
        return markup

    elif kbd == 'groq_groq-llama370_chat':
        if disabled_kbd(chat_id_full):
            return None
        markup  = telebot.types.InlineKeyboardMarkup(row_width=5)
        button0 = telebot.types.InlineKeyboardButton("➡", callback_data='continue_gpt')
        button1 = telebot.types.InlineKeyboardButton('♻️', callback_data='groq-llama370_reset')
        button2 = telebot.types.InlineKeyboardButton("🙈", callback_data='erase_answer')
        button3 = telebot.types.InlineKeyboardButton("📢", callback_data='tts')
        button4 = telebot.types.InlineKeyboardButton(lang, callback_data='translate_chat')
        markup.add(button0, button1, button2, button3, button4)
        return markup

    elif kbd == 'gemini_chat' or kbd == 'chat':
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

        voices = {'tts_female': tr('MS жен.', lang, 'это сокращенный текст на кнопке, полный текст - "Microsoft женский", тут имеется в виду женский голос для TTS от микрософта, сделай перевод таким же коротким что бы уместится на кнопке'),
                  'tts_male': tr('MS муж.', lang, 'это сокращенный текст на кнопке, полный текст - "Microsoft мужской", тут имеется в виду мужской голос для TTS от микрософта, сделай перевод таким же коротким что бы уместится на кнопке'),
                  'tts_google_female': 'Google',
                  }
        voice_title = voices[voice]

        # кто по умолчанию
        if chat_id_full not in CHAT_MODE:
            CHAT_MODE[chat_id_full] = cfg.chat_mode_default

        markup  = telebot.types.InlineKeyboardMarkup(row_width=1)

        if hasattr(cfg, 'coze_bot') and cfg.coze_bot:
            button1 = telebot.types.InlineKeyboardButton("🤜 ChatGPT4 Turbo + Dalle3 (coze.com) 🤛",  url = cfg.coze_bot)
            markup.row(button1)


        button1 = telebot.types.InlineKeyboardButton(f"{tr(f'📢Голос:', lang)} {voice_title}", callback_data=voice)
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

        if chat_id_full not in SUGGEST_ENABLED:
            SUGGEST_ENABLED[chat_id_full] = False
        if SUGGEST_ENABLED[chat_id_full]:
            button1 = telebot.types.InlineKeyboardButton(tr(f'✅Show image suggestions', lang), callback_data='suggest_image_prompts_disable')
        else:
            button1 = telebot.types.InlineKeyboardButton(tr(f'☑️Show image suggestions', lang), callback_data='suggest_image_prompts_enable')
        markup.row(button1)

        if chat_id_full not in TRANSCRIBE_ONLY_CHAT:
            TRANSCRIBE_ONLY_CHAT[chat_id_full] = False
        if TRANSCRIBE_ONLY_CHAT[chat_id_full]:
            button2 = telebot.types.InlineKeyboardButton(tr(f'✅Voice to text mode', lang), callback_data='transcribe_only_chat_disable')
        else:
            button2 = telebot.types.InlineKeyboardButton(tr(f'☑️Voice to text mode', lang), callback_data='transcribe_only_chat_enable')
        markup.row(button2)

        if cfg.pics_group_url:
            button_pics = telebot.types.InlineKeyboardButton(tr("🖼️Галерея", lang),  url = cfg.pics_group_url)
            markup.add(button_pics)

        is_private = message.chat.type == 'private'
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
            if not is_private:
                markup.add(button)

        button = telebot.types.InlineKeyboardButton(tr('🙈Закрыть меню', lang), callback_data='erase_answer')
        markup.add(button)

        return markup
    else:
        raise f"Неизвестная клавиатура '{kbd}'"


@bot.callback_query_handler(func=authorized_callback)
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

        MSG_CONFIG = f"""<b>{tr('Bot name:', lang)}</b> {BOT_NAMES[chat_id_full] if chat_id_full in BOT_NAMES else BOT_NAME_DEFAULT} /name

<b>{tr('Bot style(role):', lang)}</b> {ROLES[chat_id_full] if (chat_id_full in ROLES and ROLES[chat_id_full]) else tr('No role was set.', lang)} /style

<b>{tr('User language:', lang)}</b> {tr(langcodes.Language.make(language=lang).display_name(language='en'), lang)} /lang

{tr('Disable/enable the context, the bot will not know who it is, where it is, who it is talking to, it will work as on the original website', lang, '_')}

/original_mode

<b>{tr('Available ai models:', lang)}</b>
/llama370 - llama 3 70b (groq)
/gemini10 - Google Gemini 1.5 flash
/gemini15 - Google Gemini 1.5 pro
/openrouter - all other models including new GPT-4o, Claude 3 Opus etc

"""

        if call.data == 'clear_history':
            # обработка нажатия кнопки "Стереть историю"
            my_gemini.reset(chat_id_full)
            bot.delete_message(message.chat.id, message.message_id)
        elif call.data == 'continue_gpt':
            # обработка нажатия кнопки "Продолжай GPT"
            message.dont_check_topic = True
            echo_all(message, tr('Продолжай', lang))
            return
        elif call.data == 'forget_all':
            # обработка нажатия кнопки "Забудь всё"
            reset_(chat_id_full)
        elif call.data == 'cancel_command':
            # обработка нажатия кнопки "Отменить ввод команды"
            COMMAND_MODE[chat_id_full] = ''
            bot.delete_message(message.chat.id, message.message_id)
        elif call.data == 'cancel_command_not_hide':
            # обработка нажатия кнопки "Отменить ввод команды, но не скрывать"
            COMMAND_MODE[chat_id_full] = ''
            # bot.delete_message(message.chat.id, message.message_id)
            bot_reply_tr(message, 'Режим поиска в гугле отключен')
        # режим автоответов в чате, бот отвечает на все реплики всех участников
        # комната для разговоров с ботом Ж)
        elif call.data == 'admin_chat' and is_admin_member(call):
            if chat_id_full in SUPER_CHAT:
                SUPER_CHAT[chat_id_full] = 1 if SUPER_CHAT[chat_id_full] == 0 else 0
            else:
                SUPER_CHAT[chat_id_full] = 1
            bot.edit_message_text(chat_id=chat_id, parse_mode='HTML', message_id=message.message_id,
                                  text = MSG_CONFIG, reply_markup=get_keyboard('config', message, 'admin'))
        elif call.data == 'erase_answer':
            # обработка нажатия кнопки "Стереть ответ"
            bot.delete_message(message.chat.id, message.message_id)
        elif call.data == 'tts':
            llang = my_trans.detect_lang(message.text or message.caption or '') or lang
            message.text = f'/tts {llang} {message.text or message.caption or ""}'
            tts(message)
        elif call.data.startswith('imagecmd_'):
            hash = call.data[9:]
            prompt = IMAGE_SUGGEST_BUTTONS[hash]
            message.text = f'/image {prompt}'
            image(message)
        elif call.data.startswith('select_lang-'):
            l = call.data[12:]
            message.text = f'/lang {l}'
            language(message)
        elif call.data == 'translate':
            # реакция на клавиатуру для OCR кнопка перевести текст
            with ShowAction(message, 'typing'):
                text = message.text if message.text else message.caption
                translated = my_trans.translate_text2(text, lang)
            if translated and translated != text:
                if message.text:
                    bot.edit_message_text(chat_id=message.chat.id, message_id=message.message_id, text=translated, 
                                      reply_markup=get_keyboard('translate', message))
                if message.caption:
                    bot.edit_message_caption(chat_id=message.chat.id, message_id=message.message_id, caption=translated, 
                                      reply_markup=get_keyboard('translate', message), parse_mode='HTML')
        elif call.data == 'translate_chat':
            # реакция на клавиатуру для Чата кнопка перевести текст
            with ShowAction(message, 'typing'):
                translated = my_trans.translate_text2(message.text, lang)
            if translated and translated != message.text:
                bot.edit_message_text(chat_id=message.chat.id, message_id=message.message_id, text=translated, 
                                      reply_markup=get_keyboard('chat', message))
        elif call.data == 'groq-llama370_reset':
            my_groq.reset(chat_id_full)
            bot_reply_tr(message, 'История диалога с Groq llama 3 70b очищена.')
        elif call.data == 'openrouter_reset':
            my_openrouter.reset(chat_id_full)
            bot_reply_tr(message, 'История диалога с openrouter очищена.')
        elif call.data == 'gemini_reset':
            my_gemini.reset(chat_id_full)
            bot_reply_tr(message, 'История диалога с Gemini Pro очищена.')
        elif call.data == 'tts_female' and is_admin_member(call):
            TTS_GENDER[chat_id_full] = 'male'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                  text = MSG_CONFIG, reply_markup=get_keyboard('config', message))
        elif call.data == 'tts_male' and is_admin_member(call):
            TTS_GENDER[chat_id_full] = 'google_female'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                  text = MSG_CONFIG, reply_markup=get_keyboard('config', message))
        elif call.data == 'tts_google_female' and is_admin_member(call):
            # TTS_GENDER[chat_id_full] = 'male_ynd'
            TTS_GENDER[chat_id_full] = 'female'
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                  text = MSG_CONFIG, reply_markup=get_keyboard('config', message))
        elif call.data == 'voice_only_mode_disable' and is_admin_member(call):
            VOICE_ONLY_MODE[chat_id_full] = False
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                  text = MSG_CONFIG, reply_markup=get_keyboard('config', message))
        elif call.data == 'suggest_image_prompts_enable'  and is_admin_member(call):
            SUGGEST_ENABLED[chat_id_full] = True
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                  text = MSG_CONFIG, reply_markup=get_keyboard('config', message))
        elif call.data == 'suggest_image_prompts_disable' and is_admin_member(call):
            SUGGEST_ENABLED[chat_id_full] = False
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                  text = MSG_CONFIG, reply_markup=get_keyboard('config', message))
        elif call.data == 'voice_only_mode_enable'  and is_admin_member(call):
            VOICE_ONLY_MODE[chat_id_full] = True
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                  text = MSG_CONFIG, reply_markup=get_keyboard('config', message))
        elif call.data == 'transcribe_only_chat_disable' and is_admin_member(call):
            TRANSCRIBE_ONLY_CHAT[chat_id_full] = False
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                  text = MSG_CONFIG, reply_markup=get_keyboard('config', message))
        elif call.data == 'transcribe_only_chat_enable'  and is_admin_member(call):
            TRANSCRIBE_ONLY_CHAT[chat_id_full] = True
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                  text = MSG_CONFIG, reply_markup=get_keyboard('config', message))
        elif call.data == 'autotranslate_disable' and is_admin_member(call):
            BLOCKS[chat_id_full] = 0
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                  text = MSG_CONFIG, reply_markup=get_keyboard('config', message))
        elif call.data == 'autotranslate_enable' and is_admin_member(call):
            BLOCKS[chat_id_full] = 1
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                  text = MSG_CONFIG, reply_markup=get_keyboard('config', message))
        elif call.data == 'disable_chat_kbd' and is_admin_member(call):
            DISABLED_KBD[chat_id_full] = False
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                  text = MSG_CONFIG, reply_markup=get_keyboard('config', message))
        elif call.data == 'enable_chat_kbd' and is_admin_member(call):
            DISABLED_KBD[chat_id_full] = True
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                  text = MSG_CONFIG, reply_markup=get_keyboard('config', message))


@bot.message_handler(content_types = ['voice', 'audio'], func=authorized)
def handle_voice(message: telebot.types.Message): 
    """Автоматическое распознавание текст из голосовых сообщений"""
    thread = threading.Thread(target=handle_voice_thread, args=(message,))
    thread.start()
def handle_voice_thread(message: telebot.types.Message):
    """Автоматическое распознавание текст из голосовых сообщений и аудио файлов"""
    is_private = message.chat.type == 'private'
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    if chat_id_full not in VOICE_ONLY_MODE:
        VOICE_ONLY_MODE[chat_id_full] = False

    if chat_id_full not in SUPER_CHAT:
        SUPER_CHAT[chat_id_full] = 0
    if SUPER_CHAT[chat_id_full] == 1:
        is_private = True

    if check_blocks(get_topic_id(message)) and not is_private:
        return

    with semaphore_talks:
        # Создание временного файла 
        with tempfile.NamedTemporaryFile(delete=True) as temp_file:
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

            try:
                text = my_stt.stt(file_path, lang, chat_id_full)
            except Exception as error_stt:
                my_log.log2(f'tb:handle_voice_thread: {error_stt}')
                text = ''

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
                    bot_reply(message, text, reply_markup=get_keyboard('translate', message))
            else:
                if VOICE_ONLY_MODE[chat_id_full]:
                    message.text = '/tts ' + tr('Не удалось распознать текст', lang)
                    tts(message)
                else:
                    bot_reply_tr(message, 'Не удалось распознать текст')

            # и при любом раскладе отправляем текст в обработчик текстовых сообщений, возможно бот отреагирует на него если там есть кодовые слова
            if text:
                if chat_id_full not in TRANSCRIBE_ONLY_CHAT:
                    TRANSCRIBE_ONLY_CHAT[chat_id_full] = False
                if not TRANSCRIBE_ONLY_CHAT[chat_id_full]:
                    message.text = text
                    echo_all(message)


@bot.message_handler(content_types = ['document'], func=authorized)
def handle_document(message: telebot.types.Message):
    thread = threading.Thread(target=handle_document_thread, args=(message,))
    thread.start()
def handle_document_thread(message: telebot.types.Message):
    """Обработчик документов"""
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    COMMAND_MODE[chat_id_full] = ''

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
        # если прислали текстовый файл или pdf
        # то скачиваем и вытаскиваем из них текст и показываем краткое содержание
        if is_private and \
            (message.document.mime_type in ('application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document') or \
                message.document.mime_type.startswith('text/')):
            with ShowAction(message, 'typing'):
                # file_info = bot.get_file(message.document.file_id)
                downloaded_file = bot.download_file(file_info.file_path)
                file_bytes = io.BytesIO(downloaded_file)
                text = ''
                if message.document.mime_type == 'application/pdf':
                    pdf_reader = PyPDF2.PdfReader(file_bytes)
                    for page in pdf_reader.pages:
                        text += page.extract_text()
                elif message.document.mime_type.startswith('text/'):
                    data__ = file_bytes.read()
                    try:
                        text = data__.decode('utf-8')
                    except:
                        try:
                            # Определение кодировки
                            result = chardet.detect(data__)
                            encoding = result['encoding']
                            text = data__.decode(encoding)
                        except:
                            pass
                elif message.document.mime_type == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document':
                    text = my_pandoc.fb2_to_text(downloaded_file)

                if text.strip():
                    caption = message.caption or ''
                    caption = caption.strip()
                    summary = my_sum.summ_text(text, 'text', lang, caption)
                    USER_FILES[chat_id_full] = (message.document.file_name if hasattr(message, 'document') else 'text file', text)
                    summary_html = utils.bot_markdown_to_html(summary)
                    bot_reply(message, summary_html, parse_mode='HTML',
                                          disable_web_page_preview = True,
                                          reply_markup=get_keyboard('translate', message))

                    caption_ = tr("попросил ответить по содержанию файла", lang)
                    if caption:
                        caption_ += ', ' + caption
                    add_to_bots_mem(caption_,
                                        f'{tr("посмотрел файл и ответил:", lang)} {summary}',
                                        chat_id_full)
                else:
                    bot_reply_tr(message, 'Не удалось получить никакого текста из документа.')
                return

        # дальше идет попытка распознать ПДФ или jpg файл, вытащить текст с изображений
        if is_private or caption.lower() == 'ocr':
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
                            bot_reply(message, text, parse_mode='',
                                                  reply_markup=get_keyboard('translate', message),
                                                  disable_web_page_preview = True)

                            text = text[:8000]
                            add_to_bots_mem(f'user {tr("попросил распознать текст с картинки", lang)}',
                                                f'{tr("распознал текст и ответил:", lang)} {text}',
                                                chat_id_full)

                        else:
                            bot_reply_tr(message, 'Не смог распознать текст.',
                                         reply_markup=get_keyboard('translate', message))
                    return
                if document.mime_type != 'application/pdf':
                    bot_reply(message, f'{tr("Это не PDF-файл.", lang)} {document.mime_type}')
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
                                m = bot.send_document(chat_id, document = f, visible_file_name = file_name, caption=file_name, 
                                                  reply_to_message_id = message.message_id, reply_markup=get_keyboard('hide', message))
                            else:
                                m = bot.send_document(chat_id, document = f, visible_file_name = file_name, caption=file_name, 
                                                  reply_markup=get_keyboard('hide', message))
                            log_message(m)
                    else:
                        bot_reply(message, text, reply_markup=get_keyboard('translate', message))
                    my_log.log_echo(message, f'[распознанный из PDF текст] {text}')


@bot.message_handler(content_types = ['photo'], func=authorized)
def handle_photo(message: telebot.types.Message):
    """Обработчик фотографий. Сюда же попадают новости которые создаются как фотография + много текста в подписи, и пересланные сообщения в том числе"""
    thread = threading.Thread(target=handle_photo_thread, args=(message,))
    thread.start()
def handle_photo_thread(message: telebot.types.Message):
    """Обработчик фотографий. Сюда же попадают новости которые создаются как фотография
    + много текста в подписи, и пересланные сообщения в том числе"""
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    is_private = message.chat.type == 'private'
    if chat_id_full not in SUPER_CHAT:
        SUPER_CHAT[chat_id_full] = 0
    if SUPER_CHAT[chat_id_full] == 1:
        is_private = True

    msglower = message.caption.lower() if message.caption else ''

    # if (tr('что', lang) in msglower and len(msglower) < 30) or msglower == '':
    if msglower.startswith('?'):
        state = 'describe'
        message.caption = message.caption[1:]
    # elif 'ocr' in msglower or tr('прочитай', lang) in msglower or tr('читай', lang) in msglower:
    elif 'ocr' in msglower:
        state = 'ocr'
    elif is_private:
        # state = 'translate'
        # автопереводом никто не пользуется а вот описание по запросу популярно
        state = 'describe'
    else:
        state = ''

    # выключены ли автопереводы
    if check_blocks(get_topic_id(message)):
        if not is_private:
            if state == 'translate':
                return

    with semaphore_talks:
        # распознаем что на картинке с помощью гугл барда
        # if state == 'describe' and (is_private or tr('что', lang) in msglower):
        if state == 'describe':
            with ShowAction(message, 'typing'):
                photo = message.photo[-1]
                file_info = bot.get_file(photo.file_id)
                image = bot.download_file(file_info.file_path)

                text = img2txt(image, lang, chat_id_full, message.caption)
                if text:
                    text = utils.bot_markdown_to_html(text)
                    text += '\n\n' + tr("<b>Every time you ask a new question about the picture, you have to send the picture again.</b>", lang)
                    bot_reply(message, text, parse_mode='HTML',
                                          reply_markup=get_keyboard('translate', message))
                else:
                    bot_reply_tr(message, 'Sorry, I could not answer your question.')
            return
        elif state == 'ocr':
            with ShowAction(message, 'typing'):
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
                    bot_reply(message, text, parse_mode='',
                                        reply_markup=get_keyboard('translate', message),
                                        disable_web_page_preview = True)

                    text = text[:8000]
                    add_to_bots_mem(f'user {tr("попросил распознать текст с картинки", lang)}',
                                        f'{tr("распознал текст и ответил:", lang)} {text}',
                                        chat_id_full)

                else:
                    bot_reply_tr(message, '[OCR] no results')
            return
        elif state == 'translate':
            # пересланные сообщения пытаемся перевести даже если в них картинка
            # новости в телеграме часто делают как картинка + длинная подпись к ней
            if message.forward_from_chat and message.caption:
                # у фотографий нет текста но есть заголовок caption. его и будем переводить
                with ShowAction(message, 'typing'):
                    text = my_trans.translate(message.caption)
                if text:
                    bot_reply(message, text)
                else:
                    my_log.log_echo(message, "Не удалось/понадобилось перевести.")
                return


@bot.message_handler(content_types = ['video', 'video_note'], func=authorized)
def handle_video(message: telebot.types.Message):
    thread = threading.Thread(target=handle_video_thread, args=(message,))
    thread.start()
def handle_video_thread(message: telebot.types.Message):
    """Обработчик видеосообщений. Сюда же относятся новости и репосты с видео"""
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
            # у видео нет текста но есть заголовок caption. его и будем переводить
            text = my_trans.translate(message.caption)
            if text:
                bot_reply(message, text)
            else:
                my_log.log_echo(message, "Не удалось/понадобилось перевести.")

    with semaphore_talks:
        with ShowAction(message, 'typing'):
            # Создание временного файла 
            with tempfile.NamedTemporaryFile(delete=True) as temp_file:
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
            try:
                text = my_stt.stt(file_path, lang, chat_id_full)
            except Exception as stt_error:
                my_log.log2(f'tb:handle_video_thread: {stt_error}')
                text = ''

            try:
                os.remove(file_path)
            except Exception as hvt_remove_error:
                my_log.log2(f'tb:handle_video_thread:remove: {hvt_remove_error}')

            # Отправляем распознанный текст
            if text:
                bot_reply(message, text, reply_markup=get_keyboard('translate', message))
            else:
                bot_reply_tr(message, 'Не удалось распознать текст')


@bot.message_handler(commands=['config', 'settings', 'setting', 'options'], func=authorized_owner)
def config(message: telebot.types.Message):
    thread = threading.Thread(target=config_thread, args=(message,))
    thread.start()
def config_thread(message: telebot.types.Message):
    """Меню настроек"""
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    COMMAND_MODE[chat_id_full] = ''
    try:
        MSG_CONFIG = f"""<b>{tr('Bot name:', lang)}</b> {BOT_NAMES[chat_id_full] if chat_id_full in BOT_NAMES else BOT_NAME_DEFAULT} /name

<b>{tr('Bot style(role):', lang)}</b> {ROLES[chat_id_full] if (chat_id_full in ROLES and ROLES[chat_id_full]) else tr('No role was set.', lang)} /style

<b>{tr('User language:', lang)}</b> {tr(langcodes.Language.make(language=lang).display_name(language='en'), lang)} /lang

{tr('Disable/enable the context, the bot will not know who it is, where it is, who it is talking to, it will work as on the original website', lang, '_')}

/original_mode

<b>{tr('Available ai models:', lang)}</b>
/llama370 - llama 3 70b (groq)
/gemini10 - Google Gemini 1.5 flash
/gemini15 - Google Gemini 1.5 pro
/openrouter - all other models including new GPT-4o, Claude 3 Opus etc

"""
        bot_reply(message, MSG_CONFIG, parse_mode='HTML', reply_markup=get_keyboard('config', message))
    except Exception as error:
        my_log.log2(f'tb:config:{error}')
        print(error)


@bot.message_handler(commands=['original_mode'], func=authorized_owner)
def original_mode(message: telebot.types.Message):
    """
    Handles the 'original_mode' command for authorized owners. 
    Toggles the original mode for the chat based on the current state.
    """
    chat_id_full = get_topic_id(message)
    COMMAND_MODE[chat_id_full] = ''

    if chat_id_full not in ORIGINAL_MODE:
        ORIGINAL_MODE[chat_id_full] = False

    if ORIGINAL_MODE[chat_id_full]:
        ORIGINAL_MODE[chat_id_full] = False
        bot_reply_tr(message, 'Original mode disabled. Bot will be informed about place, names, roles etc.')
    else:
        ORIGINAL_MODE[chat_id_full] = True
        bot_reply_tr(message, 'Original mode enabled. Bot will not be informed about place, names, roles etc. It will work same as original chatbot.')


@bot.message_handler(commands=['model',], func=authorized_owner)
def model(message: telebot.types.Message):
    """Юзеры могут менять модель для openrouter.ai"""
    thread = threading.Thread(target=model_thread, args=(message,))
    thread.start()
def model_thread(message: telebot.types.Message):
    """Юзеры могут менять модель для openrouter.ai"""
    chat_id_full = get_topic_id(message)
    COMMAND_MODE[chat_id_full] = ''
    
    try:
        model = message.text.split(maxsplit=1)[1].strip()
        if chat_id_full not in my_openrouter.PARAMS:
            my_openrouter.PARAMS[chat_id_full] = my_openrouter.PARAMS_DEFAULT
        _, temperature, max_tokens, maxhistlines, maxhistchars = my_openrouter.PARAMS[chat_id_full]
        my_openrouter.PARAMS[chat_id_full] = [model, temperature, max_tokens, maxhistlines, maxhistchars]
        bot_reply_tr(message, f'Model changed.')
        return
    except Exception as error:
        error_tr = traceback.format_exc()
        my_log.log2(f'tb:model:{error}\n\n{error_tr}')
    bot_reply_tr(message, f'Usage: /model model_name see models at https://openrouter.ai/docs#models', disable_web_page_preview=True)


@bot.message_handler(commands=['maxhistlines',], func=authorized_owner)
def maxhistlines(message: telebot.types.Message):
    """Юзеры могут менять maxhistlines для openrouter.ai"""
    thread = threading.Thread(target=maxhistlines_thread, args=(message,))
    thread.start()
def maxhistlines_thread(message: telebot.types.Message):
    """Юзеры могут менять maxhistlines для openrouter.ai"""
    chat_id_full = get_topic_id(message)
    COMMAND_MODE[chat_id_full] = ''
    
    try:
        maxhistlines = int(message.text.split(maxsplit=1)[1].strip())
        if maxhistlines < 2 or maxhistlines > 100:
            raise Exception('Invalid parameters')
        if chat_id_full not in my_openrouter.PARAMS:
            my_openrouter.PARAMS[chat_id_full] = my_openrouter.PARAMS_DEFAULT
        model, temperature, max_tokens, _, maxhistchars = my_openrouter.PARAMS[chat_id_full]
        my_openrouter.PARAMS[chat_id_full] = [model, temperature, max_tokens, maxhistlines, maxhistchars]
        bot_reply_tr(message, f'Maxhistlines changed.')
        return
    except Exception as error:
        error_tr = traceback.format_exc()
        my_log.log2(f'tb:model:{error}\n\n{error_tr}')
    bot_reply_tr(message, f'Usage: /maxhistlines maxhistlines 2-100', disable_web_page_preview=True)


@bot.message_handler(commands=['maxhistchars',], func=authorized_owner)
def maxhistchars(message: telebot.types.Message):
    """Юзеры могут менять maxhistchars для openrouter.ai"""
    thread = threading.Thread(target=maxhistchars_thread, args=(message,))
    thread.start()
def maxhistchars_thread(message: telebot.types.Message):
    """Юзеры могут менять maxhistchars для openrouter.ai"""
    chat_id_full = get_topic_id(message)
    COMMAND_MODE[chat_id_full] = ''
    
    try:
        maxhistchars = int(message.text.split(maxsplit=1)[1].strip())
        if maxhistchars < 2000 or maxhistchars > 1000000:
            raise Exception('Invalid parameters')
        if chat_id_full not in my_openrouter.PARAMS:
            my_openrouter.PARAMS[chat_id_full] = my_openrouter.PARAMS_DEFAULT
        model, temperature, max_tokens, maxhistlines, _ = my_openrouter.PARAMS[chat_id_full]
        my_openrouter.PARAMS[chat_id_full] = [model, temperature, max_tokens, maxhistlines, maxhistchars]
        bot_reply_tr(message, f'Maxhistchars changed.')
        return
    except Exception as error:
        error_tr = traceback.format_exc()
        my_log.log2(f'tb:model:{error}\n\n{error_tr}')
    bot_reply_tr(message, f'Usage: /maxhistchars maxhistchars 2000-1000000', disable_web_page_preview=True)


@bot.message_handler(commands=['maxtokens',], func=authorized_owner)
def maxtokens(message: telebot.types.Message):
    """Юзеры могут менять maxtokens для openrouter.ai"""
    thread = threading.Thread(target=maxtokens_thread, args=(message,))
    thread.start()
def maxtokens_thread(message: telebot.types.Message):
    """Юзеры могут менять maxtokens для openrouter.ai"""
    chat_id_full = get_topic_id(message)
    COMMAND_MODE[chat_id_full] = ''
    
    try:
        maxtokens = int(message.text.split(maxsplit=1)[1].strip())
        if maxtokens < 10 or maxtokens > 8000:
            raise Exception('Invalid parameters')
        if chat_id_full not in my_openrouter.PARAMS:
            my_openrouter.PARAMS[chat_id_full] = my_openrouter.PARAMS_DEFAULT
        model, temperature, _, maxhistlines, maxhistchars = my_openrouter.PARAMS[chat_id_full]
        my_openrouter.PARAMS[chat_id_full] = [model, temperature, maxtokens, maxhistlines, maxhistchars]
        bot_reply_tr(message, f'Maxtokens changed.')
        return
    except Exception as error:
        error_tr = traceback.format_exc()
        my_log.log2(f'tb:model:{error}\n\n{error_tr}')
    bot_reply_tr(message, f'Usage: /maxtokens maxtokens 10-8000', disable_web_page_preview=True)


@bot.message_handler(commands=['openrouter',], func=authorized_owner)
def openrouter(message: telebot.types.Message):
    """Юзеры могут добавить свои ключи для openrouter.ai и пользоваться платным сервисом через моего бота"""
    thread = threading.Thread(target=openrouter_thread, args=(message,))
    thread.start()
def openrouter_thread(message: telebot.types.Message):
    """Юзеры могут добавить свои ключи для openrouter.ai и пользоваться платным сервисом через моего бота"""
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    COMMAND_MODE[chat_id_full] = ''

    try:
        key = ''
        args = message.text.split(maxsplit=1)
        if len(args) > 1:
            key = args[1].strip()
        if chat_id_full not in my_openrouter.PARAMS:
            my_openrouter.PARAMS[chat_id_full] = my_openrouter.PARAMS_DEFAULT
        if key:
            if key.startswith('sk-or-v1-') and len(key) == 73:
                my_openrouter.KEYS[chat_id_full] = key
                bot_reply_tr(message, 'Key added successfully!')
                CHAT_MODE[chat_id_full] = 'openrouter'
                return
        else:
            msg = tr('You can use your own key from https://openrouter.ai/keys to access all AI supported.', lang)
            if chat_id_full in my_openrouter.KEYS and my_openrouter.KEYS[chat_id_full]:
                key = my_openrouter.KEYS[chat_id_full]
            if key:
                msg = f'{tr("Your key:", lang)} [{key[:20]}...]'
            model, temperature, max_tokens, maxhistlines, maxhistchars = my_openrouter.PARAMS[chat_id_full]
            msg += '\n\n'+ tr('Current settings: ', lang) + f'\n[model {model}]\n[temp {temperature}]\n[max tokens {max_tokens}]\n[maxhistlines {maxhistlines}]\n[maxhistchars {maxhistchars}]'
            msg += '\n\n' + tr('''Change model - /model <model>
change temperature - /temp <temp>
change max tokens - /maxtokens <max_tokens>
change maxhistlines - /maxhistlines <maxhistlines>
change maxhistchars - /maxhistchars <maxhistchars>

Usage: /openrouter <api key>
''', lang)
            bot_reply(message, msg, parse_mode='HTML', disable_web_page_preview=True)
    except Exception as error:
        error_tr = traceback.format_exc()
        my_log.log2(f'tb:openrouter:{error}\n\n{error_tr}')


@bot.message_handler(commands=['keys', 'key'], func=authorized_owner)
def users_keys_for_gemini(message: telebot.types.Message):
    """Юзеры могут добавить свои бесплатные ключи для джемини в общий котёл"""
    thread = threading.Thread(target=users_keys_for_gemini_thread, args=(message,))
    thread.start()
def users_keys_for_gemini_thread(message: telebot.types.Message):
    """Юзеры могут добавить свои бесплатные ключи для джемини в общий котёл"""
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    COMMAND_MODE[chat_id_full] = ''

    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        keys = [x.strip() for x in args[1].split() if len(x.strip()) == 39]
        keys = [x for x in keys if x not in my_gemini.ALL_KEYS and x.startswith('AIza')]
        if keys:
            added_flag = False
            with my_gemini.USER_KEYS_LOCK:
                # my_gemini.USER_KEYS[chat_id_full] = keys
                new_keys = []
                for key in keys:
                    if key not in my_gemini.ALL_KEYS and key not in cfg.gemini_keys:
                        if my_gemini.test_new_key(key):
                            my_gemini.ALL_KEYS.append(key)
                            new_keys.append(key)
                            added_flag = True
                            my_log.log_keys(f'Added new gemini key: {key}')
                            msg = tr('Added new gemini key:', lang) + f' {key}'
                            bot_reply(message, msg)
                        else:
                            my_log.log_keys(f'Failed to add new gemini key: {key}')
                            msg = tr('Failed to add new gemini key:', lang) + f' {key}'
                            bot_reply(message, msg)
            if added_flag:
                my_gemini.USER_KEYS[chat_id_full] = new_keys
                bot_reply_tr(message, 'Added keys successfully!')
                return

    msg = tr('Usage: /keys GEMINI API KEYS space separated\n\nThis bot needs free api keys. Get it at https://ai.google.dev/ \n\nHowto video:', lang) + ' https://www.youtube.com/watch?v=6aj5a7qGcb4\n\nFree VPN: https://www.vpnjantit.com/'
    bot_reply(message, msg, disable_web_page_preview = True)

    if message.from_user.id in cfg.admins:
        msg = tr('Total users keys:', lang)
        msg = f'{msg} {len(my_gemini.ALL_KEYS)}'
        bot_reply(message, msg)
        keys = []
        for x in my_gemini.USER_KEYS.keys():
            keys += my_gemini.USER_KEYS[x]

        msg = tr('All user`s keys:', lang) + '\n\n<code>'
        for key in keys:
            msg += f'"{key}",\n'
        bot_reply(message, msg+'</code>', parse_mode='HTML')

    # показать юзеру его ключи
    if chat_id_full in my_gemini.USER_KEYS:
        keys = my_gemini.USER_KEYS[chat_id_full]
        msg = tr('Your keys:', lang) + '\n\n'
        for key in keys:
            msg += f'<code>{key}</code>\n'
        bot_reply(message, msg, parse_mode='HTML')


@bot.message_handler(commands=['addkey'], func=authorized_admin)
def addkeys(message: telebot.types.Message):
    '''добавить ключи другому юзеру'''
    thread = threading.Thread(target=addkeys_thread, args=(message,))
    thread.start()
def addkeys_thread(message: telebot.types.Message):
    try:
        args = message.text.split(maxsplit=2)
        uid = f'[{args[1].strip()}] [0]'
        key = args[2].strip()
        bot_reply(message, f'{uid} {key}')
        if key not in my_gemini.ALL_KEYS:
            my_gemini.ALL_KEYS.append(key)
            my_gemini.USER_KEYS[uid] = [key,]
            bot_reply_tr(message, 'Added keys successfully!')
        else:
            bot_reply_tr(message, 'Key already exists!')
    except Exception as error:
        error_tr = traceback.format_exc()
        bot_reply_tr(message, 'Usage: /addkeys <uid> <key>\n\n<code>{error}</code>\n\n<code>{error_tr}</code>', parse_mode='HTML')


# @bot.message_handler(commands=['removemykeys'], func=authorized_owner)
# def remove_my_keys(message: telebot.types.Message):
#     thread = threading.Thread(target=remove_my_keys_thread, args=(message,))
#     thread.start()
# def remove_my_keys_thread(message: telebot.types.Message):
#     chat_id_full = get_topic_id(message)
#     keys = my_gemini.USER_KEYS[chat_id_full]
#     del my_gemini.USER_KEYS[chat_id_full]
#     my_gemini.ALL_KEYS = [x for x in my_gemini.ALL_KEYS if x not in keys]
#     bot_reply_tr(message, 'Removed keys successfully!')


@bot.message_handler(commands=['gemini10'], func=authorized_owner)
def gemini10_mode(message: telebot.types.Message):
    chat_id_full = get_topic_id(message)
    CHAT_MODE[chat_id_full] = 'gemini'
    bot_reply_tr(message, 'Gemini Pro 1.0 model selected.')


@bot.message_handler(commands=['gemini15'], func=authorized_owner)
def gemini15_mode(message: telebot.types.Message):
    chat_id_full = get_topic_id(message)
    CHAT_MODE[chat_id_full] = 'gemini15'
    bot_reply_tr(message, 'Gemini Pro 1.5 model selected.')


@bot.message_handler(commands=['donate'], func=authorized_owner)
def donate(message: telebot.types.Message):
    help = f'[<a href = "https://www.donationalerts.com/r/theurs">DonationAlerts</a> 💸 <a href = "https://www.sberbank.com/ru/person/dl/jc?linkname=EiDrey1GTOGUc3j0u">SBER</a> 💸 <a href = "https://qiwi.com/n/KUN1SUN">QIWI</a> 💸 <a href = "https://yoomoney.ru/to/4100118478649082">Yoomoney</a>]'
    bot_reply(message, help, parse_mode='HTML', disable_web_page_preview=True)


@bot.message_handler(commands=['llama370'], func=authorized_owner)
def llama3_70(message: telebot.types.Message):
    chat_id_full = get_topic_id(message)
    CHAT_MODE[chat_id_full] = 'llama370'
    bot_reply_tr(message, 'Groq llama 3 70b model selected.')


@bot.message_handler(commands=['style'], func=authorized_owner)
def change_mode(message: telebot.types.Message):
    """
    Handles the 'style' command from the bot. Changes the prompt for the GPT model
    based on the user's input. If no argument is provided, it displays the current
    prompt and the available options for changing it.

    Parameters:
        message (telebot.types.Message): The message object received from the user.

    Returns:
        None
    """
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    if chat_id_full not in ROLES:
        ROLES[chat_id_full] = ''

    DEFAULT_ROLES = [tr('отвечай суперкоротко', lang),
                     tr('отвечай максимально развернуто', lang),
                     tr('отвечай всегда на английском языке', lang),
                     tr('всегда переводи всё на английский язык вместо того что бы отвечать', lang),
                     tr('ты грубый бот поддержки, делаешь всё что просят люди', lang),]

    arg = message.text.split(maxsplit=1)[1:]
    if arg:
        if arg[0] == '1':
            new_prompt = DEFAULT_ROLES[0]
        elif arg[0] == '2':
            new_prompt = DEFAULT_ROLES[1]
        elif arg[0] == '3':
            new_prompt = DEFAULT_ROLES[2]
        elif arg[0] == '4':
            new_prompt = DEFAULT_ROLES[3]
        elif arg[0] == '5':
            new_prompt = DEFAULT_ROLES[4]
        elif arg[0] == '0':
            new_prompt = ''
        else:
            if 'RYX has no rules' in arg[0] and message.from_user.id not in cfg.admins:
                BAD_USERS[chat_id_full] = True
                return
            new_prompt = arg[0]
        ROLES[chat_id_full] = new_prompt
        msg =  f'{tr("[Новая роль установлена]", lang)} `{new_prompt}`'
        bot_reply(message, msg, parse_mode='Markdown')
    else:
        msg = f"""{tr('Текущий стиль', lang)}

`/style {ROLES[chat_id_full] or tr('нет никакой роли', lang)}`

{tr('Меняет роль бота, строку с указаниями что и как говорить.', lang)}

`/style <0|1|2|3|4|5|{tr('свой текст', lang)}>`

0 - {tr('сброс, нет никакой роли', lang)} `/style 0`

1 - `/style {DEFAULT_ROLES[0]}`

2 - `/style {DEFAULT_ROLES[1]}`

3 - `/style {DEFAULT_ROLES[2]}`

4 - `/style {DEFAULT_ROLES[3]}`

5 - `/style {DEFAULT_ROLES[4]}`
    """

        bot_reply(message, msg, parse_mode='Markdown')


@bot.message_handler(commands=['gemini_proxy'], func=authorized_admin)
def gemini_proxy(message: telebot.types.Message):
    proxies = my_gemini.PROXY_POOL[:]
    my_gemini.sort_proxies_by_speed(proxies)

    msg = ''

    pt = prettytable.PrettyTable(
        align = "l",
        set_style = prettytable.MSWORD_FRIENDLY,
        hrules = prettytable.HEADER,
        junction_char = '|')
    header = ['N', 'last time', 'address']
    pt.field_names = header

    n = 0
    for x in proxies:
        n += 1
        p1 = f'{int(my_gemini.PROXY_POLL_SPEED[x]):02}'
        p2 = f'{round(my_gemini.PROXY_POLL_SPEED[x], 2):.2f}'.split('.')[1]
        row = [n, f'{p1}.{p2}', x]
        try:
            pt.add_row(row)
        except Exception as unknown:
            my_log.log2(f'tb:gemini_proxy:add_row {unknown}')

    msg += f'<pre><code>{pt.get_string()}</code></pre>'

    bot_reply(message, msg, parse_mode='HTML')


@bot.message_handler(commands=['disable_chat_mode'], func=authorized_admin)
def disable_chat_mode(message: telebot.types.Message):
    """mandatory switch all users from one chatbot to another"""
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    try:
        _from = message.text.split(maxsplit=3)[1].strip()
        _to = message.text.split(maxsplit=3)[2].strip()
        
        n = 0
        for x in CHAT_MODE.keys():
            if CHAT_MODE[x] == _from:
                CHAT_MODE[x] = _to
                n += 1

        msg = f'{tr("Changed: ", lang)} {n}.'
        bot_reply(message, msg)
    except:
        n = '\n\n'
        msg = f"{tr('Example usage: /disable_chat_mode FROM TO{n}Available:', lang)} gemini15, gemini"
        bot_reply(message, msg, parse_mode='HTML')


@bot.message_handler(commands=['undo', 'u', 'U', 'Undo'], func=authorized_log)
def undo(message: telebot.types.Message):
    """Clear chat history last message (bot's memory)"""
    chat_id_full = get_topic_id(message)
    COMMAND_MODE[chat_id_full] = ''
    my_gemini.undo(chat_id_full)
    bot_reply_tr(message, 'Ok.')


def reset_(message: telebot.types.Message):
    """Clear chat history (bot's memory)
    message - is chat id or message object"""
    if isinstance(message, str):
        chat_id_full = message    
    else:
        chat_id_full = get_topic_id(message)

        if 'gemini' in CHAT_MODE[chat_id_full]:
            my_gemini.reset(chat_id_full)
        elif 'groq' in CHAT_MODE[chat_id_full]:
            my_groq.reset(chat_id_full)
        elif 'openrouter' in CHAT_MODE[chat_id_full]:
            my_openrouter.reset(chat_id_full)
        else:
            bot_reply_tr(message, 'History WAS NOT cleared.')
            return
        bot_reply_tr(message, 'History cleared.')


@bot.message_handler(commands=['reset'], func=authorized_log)
def reset(message: telebot.types.Message):
    """Clear chat history (bot's memory)"""
    chat_id_full = get_topic_id(message)
    COMMAND_MODE[chat_id_full] = ''
    reset_(message)


@bot.message_handler(commands=['remove_keyboard'], func=authorized_owner)
def remove_keyboard(message: telebot.types.Message):
    try:
        chat_id_full = get_topic_id(message)
        COMMAND_MODE[chat_id_full] = ''
        lang = get_lang(chat_id_full, message)
        kbd = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        button1 = telebot.types.KeyboardButton(tr('777', lang))
        kbd.row(button1)
        m = bot.reply_to(message, '777', reply_markup=kbd)
        bot.delete_message(m.chat.id, m.message_id)
        bot_reply_tr(message, 'Keyboard removed.')
    except Exception as unknown:
        my_log.log2(f'tb:remove_keyboard: {unknown}')


@bot.message_handler(commands=['reset_gemini2'], func=authorized_admin)
def reset_gemini2(message: telebot.types.Message):
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    try:
        arg1 = message.text.split(maxsplit=3)[1]+' '+message.text.split(maxsplit=3)[2]
        my_gemini.reset(arg1)
        msg = f'{tr("История Gemini Pro в чате очищена", lang)} {arg1}'
        bot_reply(message, msg)
    except:
        bot_reply_tr(message, 'Usage: /reset_gemini2 <chat_id_full!>')


@bot.message_handler(commands=['bingcookieclear', 'kc'], func=authorized_admin)
def clear_bing_cookies(message: telebot.types.Message):
    bing_img.COOKIE.clear()
    bot_reply_tr(message, 'Cookies cleared.')


@bot.message_handler(commands=['bingcookie', 'cookie', 'k'], func=authorized_admin)
def set_bing_cookies(message: telebot.types.Message):
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    try:
        args = message.text.split(maxsplit=1)[1]
        args = args.replace('\n', ' ')
        cookies = args.split()
        n = 0

        for cookie in cookies:
            if len(cookie) < 200:
                continue
            if cookie in bing_img.COOKIE:
                continue
            cookie = cookie.strip()
            bing_img.COOKIE[cookie] = 0
            n += 1

        # reset counters after add more cookies
        for cookie in bing_img.COOKIE:
            bing_img.COOKIE[cookie] = 0

        msg = f'{tr("Cookies added:", lang)} {n}'
        bot_reply(message, msg)

    except Exception as error:

        if 'list index out of range' not in str(error):
            my_log.log2(f'set_bing_cookies: {error}\n\n{message.text}')

        bot_reply_tr(message, 'Usage: /bingcookie <whitespace separated cookies> get in at bing.com, i need _U cookie')

        # сортируем куки по количеству обращений к ним
        cookies = [x for x in bing_img.COOKIE.items()]
        cookies = sorted(cookies, key=lambda x: x[1])

        pt = prettytable.PrettyTable(
            align = "r",
            set_style = prettytable.MSWORD_FRIENDLY,
            hrules = prettytable.HEADER,
            junction_char = '|'
            )
        header = ['#', tr('Key', lang, 'тут имеется в виду ключ для рисования'),
                  tr('Counter', lang, 'тут имеется в виду счётчик количества раз использования ключа для рисования')]
        pt.field_names = header

        n = 1
        for cookie in cookies:
            pt.add_row([n, cookie[0][:5], cookie[1]])
            n += 1

        msg = f'{tr("Current cookies:", lang)} {len(bing_img.COOKIE)} \n\n<pre><code>{pt.get_string()}</code></pre>'
        bot_reply(message, msg, parse_mode='HTML')


@bot.message_handler(commands=['style2'], func=authorized_admin)
def change_mode2(message: telebot.types.Message):
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    try:
        arg1 = message.text.split(maxsplit=3)[1]+' '+message.text.split(maxsplit=3)[2]
        arg2 = message.text.split(maxsplit=3)[3]
    except:
        bot_reply_tr(message, 'Usage: /style2 <chat_id_full!> <new_style>')
        return

    ROLES[arg1] = arg2
    msg = tr('[Новая роль установлена]', lang) + ' `' + arg2 + '` ' + tr('для чата', lang) + ' `' + arg1 + '`'
    bot_reply(message, msg, parse_mode='Markdown')


@bot.message_handler(commands=['mem'], func=authorized_owner)
def send_debug_history(message: telebot.types.Message):
    """
    Отправляет текущую историю сообщений пользователю.
    """
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    COMMAND_MODE[chat_id_full] = ''

    if 'gemini' in CHAT_MODE[chat_id_full]:
        prompt = 'Gemini Pro\n\n'
        prompt += my_gemini.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        bot_reply(message, prompt, parse_mode = '', disable_web_page_preview = True, reply_markup=get_keyboard('mem', message))
    if 'groq' in CHAT_MODE[chat_id_full]:
        prompt = 'Groq llama 3 70b\n\n'
        prompt += my_groq.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        bot_reply(message, prompt, parse_mode = '', disable_web_page_preview = True, reply_markup=get_keyboard('mem', message))
    if 'openrouter' in CHAT_MODE[chat_id_full]:
        prompt = 'Openrouter\n\n'
        prompt += my_openrouter.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        bot_reply(message, prompt, parse_mode = '', disable_web_page_preview = True, reply_markup=get_keyboard('mem', message))


@bot.message_handler(commands=['restart', 'reboot'], func=authorized_admin) 
def restart(message: telebot.types.Message):
    """остановка бота. после остановки его должен будет перезапустить скрипт systemd"""
    bot_reply_tr(message, 'Restarting bot, please wait')
    my_log.log2(f'tb:restart: !!!RESTART!!!')

    bot.stop_polling()

    my_gemini.STOP_DAEMON = True


@bot.message_handler(commands=['leave'], func=authorized_admin) 
def leave(message: telebot.types.Message):
    thread = threading.Thread(target=leave_thread, args=(message,))
    thread.start()
def leave_thread(message: telebot.types.Message):
    """выйти из чата"""
    chat_full_id = get_topic_id(message)
    lang = get_lang(chat_full_id, message)

    if len(message.text) > 7:
        args = message.text[7:]
    else:
        bot_reply_tr(message, '/leave <группа из которой на выйти либо любой текст в котором есть список групп из которых надо выйти>')
        return

    chat_ids = [int(x) for x in re.findall(r"-?\d{9,14}", args)]
    for chat_id in chat_ids:
        if chat_id not in LEAVED_CHATS or LEAVED_CHATS[chat_id] == False:
            LEAVED_CHATS[chat_id] = True
            try:
                bot.leave_chat(chat_id)
                bot_reply(message, tr('Вы вышли из чата', lang) + f' {chat_id}')
            except Exception as error:
                my_log.log2(f'tb:leave: {chat_id} {str(error)}')
                bot_reply(message, tr('Не удалось выйти из чата', lang) + f' {chat_id} {str(error)}')
        else:
            bot_reply(message, tr('Вы уже раньше вышли из чата', lang) + f' {chat_id}')


@bot.message_handler(commands=['revoke'], func=authorized_admin) 
def revoke(message: telebot.types.Message):
    thread = threading.Thread(target=revoke_thread, args=(message,))
    thread.start()
def revoke_thread(message: telebot.types.Message):
    """разбанить чат(ы)"""
    chat_full_id = get_topic_id(message)
    lang = get_lang(chat_full_id, message)

    if len(message.text) > 8:
        args = message.text[8:]
    else:
        bot_reply_tr(message, '/revoke <группа или группы которые надо разбанить>')
        return

    chat_ids = [int(x) for x in re.findall(r"-?\d{10,14}", args)]
    for chat_id in chat_ids:
        if chat_id in LEAVED_CHATS and LEAVED_CHATS[chat_id]:
            LEAVED_CHATS[chat_id] = False
            bot_reply(message, tr('Чат удален из списка забаненных чатов', lang) + f' {chat_id}')
        else:
            bot_reply(message, tr('Этот чат не был в списке забаненных чатов', lang) + f' {chat_id}')


@bot.message_handler(commands=['temperature', 'temp'], func=authorized_owner)
def set_new_temperature(message: telebot.types.Message):
    """Changes the temperature for Gemini
    /temperature <0...2>
    Default is 0 - automatic
    The lower the temperature, the less creative the response, the less nonsense and lies,
    and the desire to give an answer
    """

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    COMMAND_MODE[chat_id_full] = ''

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

{tr('''Меняет температуру для Gemini

Температура это параметр, который контролирует степень случайности генерируемого текста. Чем выше температура, тем более случайным и креативным будет текст. Чем ниже температура, тем более точным и сфокусированным будет текст.

Например, если вы хотите, чтобы бот сгенерировал стихотворение, вы можете установить температуру выше 1,5. Это будет способствовать тому, что бот будет выбирать более неожиданные и уникальные слова. Однако, если вы хотите, чтобы бот сгенерировал текст, который является более точным и сфокусированным, вы можете установить температуру ниже 0,5. Это будет способствовать тому, что бот будет выбирать более вероятные и ожидаемые слова.

По-умолчанию 0.1''', lang)}

`/temperature 0.1`
`/temperature 1`
`/temperature 1.9` {tr('На таких высоких значения он пишет один сплошной бред', lang)}
"""
        bot_reply(message, help, parse_mode='Markdown')
        return

    GEMIMI_TEMP[chat_id_full] = new_temp
    if chat_id_full not in my_openrouter.PARAMS:
        my_openrouter.PARAMS[chat_id_full] = my_openrouter.PARAMS_DEFAULT
    model, _, max_tokens, maxhistlines, maxhistchars = my_openrouter.PARAMS[chat_id_full]
    my_openrouter.PARAMS[chat_id_full] = [model, float(new_temp), max_tokens, maxhistlines, maxhistchars]

    msg = f'{tr("New temperature set:", lang)} {new_temp}'
    bot_reply(message, msg, parse_mode='Markdown')


@bot.message_handler(commands=['lang', 'language'], func=authorized_owner)
def language(message: telebot.types.Message):
    thread = threading.Thread(target=language_thread, args=(message,))
    thread.start()
def language_thread(message: telebot.types.Message):
    """change locale"""

    chat_id_full = get_topic_id(message)

    COMMAND_MODE[chat_id_full] = ''

    if chat_id_full in LANGUAGE_DB:
        lang = LANGUAGE_DB[chat_id_full]
    else:
        lang = message.from_user.language_code or cfg.DEFAULT_LANGUAGE
        LANGUAGE_DB[chat_id_full] = lang

    supported_langs_trans2 = ', '.join([x for x in supported_langs_trans])

    if len(message.text.split()) < 2:
        msg = f'/lang {tr("двухбуквенный код языка. Меняет язык бота. Ваш язык сейчас: ", lang)} <b>{lang}</b> ({tr(langcodes.Language.make(language=lang).display_name(language="en"), lang).lower()})\n\n{tr("Возможные варианты:", lang)}\n{supported_langs_trans2}\n\n/lang en\n/lang de\n/lang uk\n...'
        bot_reply(message, msg, parse_mode='HTML', reply_markup=get_keyboard('select_lang', message))
        return

    new_lang = message.text.split(maxsplit=1)[1].strip().lower()
    if new_lang == 'ua':
        new_lang = 'uk'
    if new_lang in supported_langs_trans:
        LANGUAGE_DB[chat_id_full] = new_lang
        HELLO_MSG[chat_id_full] = ''
        HELP_MSG[chat_id_full] = ''
        msg = f'{tr("Язык бота изменен на:", new_lang)} <b>{new_lang}</b> ({tr(langcodes.Language.make(language=new_lang).display_name(language="en"), new_lang).lower()})'
        bot_reply(message, msg, parse_mode='HTML', reply_markup=get_keyboard('start', message))
    else:
        msg = f'{tr("Такой язык не поддерживается:", lang)} <b>{new_lang}</b>\n\n{tr("Возможные варианты:", lang)}\n{supported_langs_trans2}'
        bot_reply(message, msg, parse_mode='HTML')


# @bot.message_handler(commands=['tts'], func=authorized)
def tts(message: telebot.types.Message, caption = None):
    thread = threading.Thread(target=tts_thread, args=(message,caption))
    thread.start()
def tts_thread(message: telebot.types.Message, caption = None):
    """ /tts [ru|en|uk|...] [+-XX%] <текст>
        /tts <URL>
    """

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    # urls = re.findall(r'^/tts\s*(https?://[^\s]+)?$', message.text.lower())

    # Process the url, just get the text and show it with a keyboard for voice acting
    args = message.text.split()
    if len(args) == 2 and my_sum.is_valid_url(args[1]):
        url = args[1]
        if '/youtu.be/' in url or 'youtube.com/' in url:
            text = my_sum.get_text_from_youtube(url)
        else:
            text = my_google.download_text([url, ], 100000, no_links = True)
        if text:
            bot_reply(message, text, parse_mode='',
                                  reply_markup=get_keyboard('translate', message),
                                      disable_web_page_preview=True)
        return

    pattern = r'/tts\s+((?P<lang>' + '|'.join(supported_langs_tts) + r')\s+)?\s*(?P<rate>([+-]\d{1,2}%\s+))?\s*(?P<text>.+)'
    match = re.match(pattern, message.text, re.DOTALL)
    if match:
        llang = match.group("lang") or lang  # If lang is not specified, then by default the user's language
        rate = match.group("rate") or "+0%"  # If rate is not specified, then by default '+0%'
        text = match.group("text") or ''
    else:
        text = llang = rate = ''
    llang = llang.strip()
    if llang == 'ua':
        llang = 'uk'
    rate = rate.strip()

    if not text or llang not in supported_langs_tts:
        help = f"""{tr('Usage:', lang)} /tts [ru|en|uk|...] [+-XX%] <{tr('text', lang)}>|<URL>

+-XX% - {tr('acceleration with mandatory indication of direction + or -', lang)}

/tts hello all
/tts en hello, let me speak
/tts en +50% Hello at a speed of 1.5x

{tr('Supported languages:', lang)} {', '.join(supported_langs_tts)}

{tr('Write what to say to get a voice message.', lang)}
"""

        COMMAND_MODE[chat_id_full] = 'tts'
        bot_reply(message, help, parse_mode='Markdown', reply_markup=get_keyboard('command_mode', message))
        return

    with semaphore_talks:
        with ShowAction(message, 'record_audio'):
            if chat_id_full in TTS_GENDER:
                gender = TTS_GENDER[chat_id_full]
            else:
                gender = 'female'

            # Microsoft do not support Latin
            if llang == 'la' and (gender=='female' or gender=='male'):
                gender = 'google_female'
                bot_reply_tr(message, "Microsoft TTS cannot pronounce text in Latin language, switching to Google TTS.")

            if chat_id_full in VOICE_ONLY_MODE and VOICE_ONLY_MODE[chat_id_full]:
                text = utils.bot_markdown_to_tts(text)
            audio = my_tts.tts(text, llang, rate, gender=gender)
            if audio:
                if message.chat.type != 'private':
                    m = bot.send_voice(message.chat.id, audio, reply_to_message_id = message.message_id,
                                   reply_markup=get_keyboard('hide', message), caption=caption)
                else:
                    # In private, you don't need to add a keyboard with a delete button,
                    # you can delete it there without it, and accidental deletion is useless
                    m = bot.send_voice(message.chat.id, audio, caption=caption)
                log_message(m)
                my_log.log_echo(message, f'[Sent voice message] [{gender}]')
            else:
                bot_reply_tr(message, 'Could not dub. You may have mixed up the language, for example, the German voice does not read in Russian.')


@bot.message_handler(commands=['google','Google'], func=authorized)
def google(message: telebot.types.Message):
    thread = threading.Thread(target=google_thread, args=(message,))
    thread.start()
def google_thread(message: telebot.types.Message):
    """ищет в гугле перед ответом"""

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

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
        bot_reply(message, help, parse_mode = 'Markdown', disable_web_page_preview = False, reply_markup=get_keyboard('command_mode', message))
        return

    with ShowAction(message, 'typing'):
        with semaphore_talks:
            r, text = my_google.search_v3(q, lang)
            if not r.strip():
                bot_reply_tr(message, 'Search failed.')
                return
            USER_FILES[chat_id_full] = ('google: ' + q, text)
        try:
            rr = utils.bot_markdown_to_html(r)
            bot_reply(message, rr, parse_mode = 'HTML',
                         disable_web_page_preview = True,
                         reply_markup=get_keyboard('chat', message), allow_voice=True)
        except Exception as error2:
            my_log.log2(f'tb.py:google_thread: {error2}')

        add_to_bots_mem(f'user {tr("попросил сделать запрос в Google:", lang)} {q}',
                             f'{tr("поискал в Google и ответил:", lang)} {r}',
                             chat_id_full)


def update_user_image_counter(chat_id_full: str, n: int):
    if chat_id_full not in IMAGES_BY_USER_COUNTER:
        IMAGES_BY_USER_COUNTER[chat_id_full] = 0
    IMAGES_BY_USER_COUNTER[chat_id_full] += n

def get_user_image_counter(chat_id_full: str) -> int:
    if chat_id_full not in IMAGES_BY_USER_COUNTER:
        IMAGES_BY_USER_COUNTER[chat_id_full] = 0
    return IMAGES_BY_USER_COUNTER[chat_id_full]


@bot.message_handler(commands=['image2','img2', 'Image2', 'Img2', 'i2', 'I2', 'imagine2', 'imagine2:', 'Imagine2', 'Imagine2:', 'generate2', 'gen2', 'Generate2', 'Gen2'], func=authorized)
def image2(message: telebot.types.Message):
    is_private = message.chat.type == 'private'
    if not is_private:
        bot_reply_tr(message, 'This command is only available in private chats.')
        return
    message.text += 'NSFW'
    thread = threading.Thread(target=image_thread, args=(message,))
    thread.start()


@bot.message_handler(commands=['image','img', 'Image', 'Img', 'i', 'I', 'imagine', 'imagine:', 'Imagine', 'Imagine:', 'generate', 'gen', 'Generate', 'Gen'], func=authorized)
def image(message: telebot.types.Message):
    thread = threading.Thread(target=image_thread, args=(message,))
    thread.start()
def image_thread(message: telebot.types.Message):
    """Generates a picture from a description"""
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    # не использовать бинг для рисования запрещенки, он за это банит
    NSFW_FLAG = False
    if message.text.endswith('NSFW'):
        NSFW_FLAG = True
        message.text = message.text[:-4]

    if chat_id_full in IMG_GEN_LOCKS:
        lock = IMG_GEN_LOCKS[chat_id_full]
    else:
        lock = threading.Lock()
        IMG_GEN_LOCKS[chat_id_full] = lock

    with lock:

        with semaphore_talks:
            draw_text = tr('draw', lang)
            if lang == 'ru': draw_text = 'нарисуй'
            if lang == 'en': draw_text = 'draw'
            help = f"""/image {tr('Text description of the picture, what to draw.', lang)}

/image {tr('an apple', lang)}
/img {tr('an apple', lang)}
/i {tr('an apple', lang)}
{draw_text} {tr('an apple', lang)}

🚫{tr('NSFW is not allowed here', lang)}🚫

{tr('Write what to draw, what it looks like.', lang)}
"""
            prompt = message.text.split(maxsplit = 1)

            if len(prompt) > 1:
                prompt = prompt[1]
                COMMAND_MODE[chat_id_full] = ''

                # get chat history for content
                conversation_history = ''
                conversation_history = my_gemini.get_mem_as_string(chat_id_full) or ''

                conversation_history = conversation_history[-8000:]
                # как то он совсем плохо стал работать с историей, отключил пока что
                conversation_history = ''

                with ShowAction(message, 'upload_photo'):
                    moderation_flag = False

                    if NSFW_FLAG:
                        images = my_genimg.gen_images(prompt, moderation_flag, chat_id_full, conversation_history, use_bing = False)
                    else:
                        images = my_genimg.gen_images(prompt, moderation_flag, chat_id_full, conversation_history, use_bing = True)
                    # 1 а может и больше запросы к репромптеру
                    with CHAT_STATS_LOCK:
                        CHAT_STATS[time.time()] = (chat_id_full, 'gemini')
                        if chat_id_full in CHAT_STATS_TEMP:
                            CHAT_STATS_TEMP[chat_id_full] += 1
                        else:
                            CHAT_STATS_TEMP[chat_id_full] = 1
                    # medias = [telebot.types.InputMediaPhoto(i) for i in images if r'https://r.bing.com' not in i]
                    medias = []
                    has_good_images = False
                    for x in images:
                        if isinstance(x, bytes):
                            has_good_images = True
                            break
                    for i in images:
                        if isinstance(i, str):
                            if i.startswith('error1_') and has_good_images:
                                continue
                            if 'error1_being_reviewed_prompt' in i:
                                bot_reply_tr(message, 'Ваш запрос содержит потенциально неприемлемый контент.')
                                return
                            elif 'error1_blocked_prompt' in i:
                                bot_reply_tr(message, 'Ваш запрос содержит неприемлемый контент.')
                                return
                            elif 'error1_unsupported_lang' in i:
                                bot_reply_tr(message, 'Не понятный язык.')
                                return
                            elif 'error1_Bad images' in i:
                                bot_reply_tr(message, 'Ваш запрос содержит неприемлемый контент.')
                                return
                            if 'https://r.bing.com' in i:
                                continue

                        d = None
                        caption_ = prompt[:1000]
                        if isinstance(i, str):
                            d = utils.download_image_as_bytes(i)
                            caption_ = 'bing.com\n\n' + caption_
                        elif isinstance(i, bytes):
                            if hash(i) in my_genimg.WHO_AUTOR:
                                caption_ = my_genimg.WHO_AUTOR[hash(i)] + '\n\n' + caption_
                                del my_genimg.WHO_AUTOR[hash(i)]
                            else:
                                caption_ = 'error'
                            d = i
                        if d:
                            try:
                                medias.append(telebot.types.InputMediaPhoto(d, caption = caption_))
                            except Exception as add_media_error:
                                error_traceback = traceback.format_exc()
                                my_log.log2(f'tb:image_thread:add_media_bytes: {add_media_error}\n\n{error_traceback}')

                    if chat_id_full not in SUGGEST_ENABLED:
                        SUGGEST_ENABLED[chat_id_full] = False
                    if medias and SUGGEST_ENABLED[chat_id_full]:
                        # 1 запрос на генерацию предложений
                        with CHAT_STATS_LOCK:
                            CHAT_STATS[time.time()] = (chat_id_full, 'gemini')
                            if chat_id_full in CHAT_STATS_TEMP:
                                CHAT_STATS_TEMP[chat_id_full] += 1
                            else:
                                CHAT_STATS_TEMP[chat_id_full] = 1
                        suggest_query = tr("""Suggest a wide range options for a request to a neural network that
generates images according to the description, show 5 options with no numbers and trailing symbols, add many rich details, 1 on 1 line, output example:

Create image of ...
Create image of ...
Create image of ...
Create image of ...
Create image of ...

5 lines total in answer

the original prompt:""", lang) + '\n\n\n' + prompt
                        suggest = my_gemini.ai(suggest_query, temperature=1.5)
                        suggest = utils.bot_markdown_to_html(suggest).strip()
                    else:
                        suggest = ''

                    if len(medias) > 0:
                        with SEND_IMG_LOCK:

                            # делим картинки на группы до 10шт в группе, телеграм не пропускает больше за 1 раз
                            chunk_size = 10
                            chunks = [medias[i:i + chunk_size] for i in range(0, len(medias), chunk_size)]

                            for x in chunks:
                                msgs_ids = bot.send_media_group(message.chat.id, x, reply_to_message_id=message.message_id)
                                log_message(msgs_ids)
                            update_user_image_counter(chat_id_full, len(medias))

                            log_msg = '[Send images] '
                            for x in images:
                                if isinstance(x, str):
                                    log_msg += x + ' '
                                elif isinstance(x, bytes):
                                    log_msg += f'[binary file {round(len(x)/1024)}kb] '
                            my_log.log_echo(message, log_msg)

                            if pics_group and not NSFW_FLAG:
                                try:
                                    translated_prompt = tr(prompt, 'ru')
                                    bot.send_message(cfg.pics_group, f'{utils.html.unescape(prompt)} | #{utils.nice_hash(chat_id_full)}',
                                                    link_preview_options=telebot.types.LinkPreviewOptions(is_disabled=False))
                                    ratio = fuzz.ratio(translated_prompt, prompt)
                                    if ratio < 70:
                                        bot.send_message(cfg.pics_group, f'{utils.html.unescape(translated_prompt)} | #{utils.nice_hash(chat_id_full)}',
                                                        link_preview_options=telebot.types.LinkPreviewOptions(is_disabled=False))
                                    for x in chunks:
                                        bot.send_media_group(pics_group, x)
                                except Exception as error2:
                                    my_log.log2(f'tb:image_thread:send to pics_group: {error2}')

                            if suggest:
                                suggest = [f'{x}'.replace('• ', '', 1).replace('1. ', '', 1).replace('2. ', '', 1).replace('3. ', '', 1).replace('4. ', '', 1).replace('5. ', '', 1).strip() for x in suggest.split('\n')]
                                suggest = [x for x in suggest if x]
                                suggest__ = suggest[:5]
                                suggest = []
                                for x__ in suggest__:
                                    if x__.startswith('– '):
                                        x__ = x__[2:]
                                    suggest.append(x__.strip())

                                suggest_hashes = [utils.nice_hash(x, 12) for x in suggest]
                                markup  = telebot.types.InlineKeyboardMarkup()
                                for s, h in zip(suggest, suggest_hashes):
                                    IMAGE_SUGGEST_BUTTONS[h] = utils.html.unescape(s)

                                b1 = telebot.types.InlineKeyboardButton(text = '1️⃣', callback_data = f'imagecmd_{suggest_hashes[0]}')
                                b2 = telebot.types.InlineKeyboardButton(text = '2️⃣', callback_data = f'imagecmd_{suggest_hashes[1]}')
                                b3 = telebot.types.InlineKeyboardButton(text = '3️⃣', callback_data = f'imagecmd_{suggest_hashes[2]}')
                                b4 = telebot.types.InlineKeyboardButton(text = '4️⃣', callback_data = f'imagecmd_{suggest_hashes[3]}')
                                b5 = telebot.types.InlineKeyboardButton(text = '5️⃣', callback_data = f'imagecmd_{suggest_hashes[4]}')
                                b6 = telebot.types.InlineKeyboardButton(text = '🙈', callback_data = f'erase_answer')

                                markup.add(b1, b2, b3, b4, b5, b6)

                                suggest_msg = tr('Here are some more possible options for your request:', lang)
                                suggest_msg = f'<b>{suggest_msg}</b>\n\n'
                                n = 1
                                for s in suggest:
                                    if n == 1: nn = '1️⃣'
                                    if n == 2: nn = '2️⃣'
                                    if n == 3: nn = '3️⃣'
                                    if n == 4: nn = '4️⃣'
                                    if n == 5: nn = '5️⃣'
                                    suggest_msg += f'{nn} <code>/image {s}</code>\n\n'
                                    n += 1
                                bot_reply(message, suggest_msg, parse_mode = 'HTML', reply_markup=markup)

                            add_to_bots_mem(f'user {tr("asked to draw", lang)}\n{prompt}',
                                                f'{tr("has generated images successfully", lang)}',
                                                chat_id_full)
                    else:
                        bot_reply_tr(message, 'Could not draw anything. Maybe there is no mood, or maybe you need to give another description.')
                        if hasattr(cfg, 'enable_image_adv') and cfg.enable_image_adv:
                            bot_reply_tr(message,
                                    "Try original site https://www.bing.com/ or Try this free group, it has a lot of mediabots: https://t.me/neuralforum or this https://t.me/aibrahma/467",
                                    disable_web_page_preview = True)
                        my_log.log_echo(message, '[image gen error] ')
                        add_to_bots_mem(f'user {tr("asked to draw", lang)}\n{prompt}',
                                                f'{tr("did not want or could not draw this using DALL-E", lang)}',
                                                chat_id_full)

            else:
                COMMAND_MODE[chat_id_full] = 'image'
                bot_reply(message, help, parse_mode = 'Markdown', reply_markup=get_keyboard('command_mode', message))


@bot.message_handler(commands=['stats', 'stat'], func=authorized_admin)
def stats_admin(message: telebot.types.Message):
    """Показывает статистику использования бота."""
    thread = threading.Thread(target=stats_thread, args=(message,))
    thread.start()
def stats_thread(message: telebot.types.Message):
    """Обновленная функция, показывающая статистику использования бота."""
    now = time.time()
    
    # Инициализация счетчиков
    stats = {
        'gemini15': defaultdict(int),
        'gemini': defaultdict(int),
        'llama370': defaultdict(int),
        'new_users': defaultdict(int),
        'active_24h': set(),
        'active_48h': set(),
        'active_7d': set(),
        'active_30d': set(),
        'all_users': set()
    }

    with CHAT_STATS_LOCK:
        for time_stamp, (user_id, chat_mode) in CHAT_STATS.items():
            time_stamp = float(time_stamp)

            if user_id not in stats['all_users']:
                # Определяем, является ли пользователь новым за определенные периоды
                if now - time_stamp <= 86400:  # 24 hours in seconds
                    stats['new_users']['1d'] += 1
                if now - time_stamp <= 604800:  # 7 days in seconds
                    stats['new_users']['7d'] += 1
                if now - time_stamp <= 2592000:  # 30 days in seconds
                    stats['new_users']['30d'] += 1

            stats['all_users'].add(user_id)

            # Подсчет активных пользователей за разные периоды
            if now - time_stamp <= 86400:
                stats['active_24h'].add(user_id)
            if now - time_stamp <= 172800:
                stats['active_48h'].add(user_id)
            if now - time_stamp <= 604800:
                stats['active_7d'].add(user_id)
            if now - time_stamp <= 2592000:
                stats['active_30d'].add(user_id)

            # Подсчет сообщений в зависимости от режима
            if chat_mode in ['gemini15', 'gemini', 'llama370']:
                if now - time_stamp <= 86400:
                    stats[chat_mode]['24'] += 1
                if now - time_stamp <= 172800:
                    stats[chat_mode]['48'] += 1
                if now - time_stamp <= 604800:
                    stats[chat_mode]['7d'] += 1
                if now - time_stamp <= 2592000:
                    stats[chat_mode]['30d'] += 1

    # Строим сообщение для пользователя
    msg = ""
    for mode in ['gemini15', 'gemini', 'llama370']:
        msg += (f"{mode} за 24ч/48ч/7д/30д: "
                f"{stats[mode]['24']}/{stats[mode]['48']}/"
                f"{stats[mode]['7d']}/{stats[mode]['30d']}\n\n")

    msg += (f"Новые пользователи за 1д/7д/30д: "
            f"{stats['new_users']['1d']}/{stats['new_users']['7d']}/"
            f"{stats['new_users']['30d']}\n\n")

    msg += f"Активны за 24ч/48ч/7д/30д: {len(stats['active_24h'])}/{len(stats['active_48h'])}/"
    msg += f"{len(stats['active_7d'])}/{len(stats['active_30d'])}\n\n"

    msg += f"Всего пользователей: {len(stats['all_users'])}"

    # Отправка сообщения
    bot_reply(message, msg)


@bot.message_handler(commands=['blockadd'], func=authorized_admin)
def block_user_add(message: telebot.types.Message):
    """Добавить юзера в стоп список"""

    chat_full_id = get_topic_id(message)
    lang = get_lang(chat_full_id, message)

    user_id = message.text[10:].strip()
    if user_id:
        BAD_USERS[user_id] = True
        bot_reply(message, f'{tr("Пользователь", lang)} {user_id} {tr("добавлен в стоп-лист", lang)}')
    else:
        bot_reply_tr(message, 'Usage: /blockadd <[user id] [group id]>')


@bot.message_handler(commands=['blockdel'], func=authorized_admin)
def block_user_del(message: telebot.types.Message):
    """Убрать юзера из стоп списка"""

    chat_full_id = get_topic_id(message)
    lang = get_lang(chat_full_id, message)

    user_id = message.text[10:].strip()
    if user_id:
        if user_id in BAD_USERS:
            del BAD_USERS[user_id]
            bot_reply(message, f'{tr("Пользователь", lang)} {user_id} {tr("удален из стоп-листа", lang)}')
        else:
            bot_reply(message, f'{tr("Пользователь", lang)} {user_id} {tr("не найден в стоп-листе", lang)}')
    else:
        bot_reply_tr(message, 'Usage: /blockdel <[user id] [group id]>')


@bot.message_handler(commands=['blocklist'], func=authorized_admin)
def block_user_list(message: telebot.types.Message):
    """Показывает список заблокированных юзеров"""
    users = [x for x in BAD_USERS.keys() if x]
    if users:
        bot_reply(message, '\n'.join(users))


@bot.message_handler(commands=['msg', 'm', 'message', 'mes'], func=authorized_admin)
def message_to_user(message: telebot.types.Message):
    thread = threading.Thread(target=message_to_user_thread, args=(message,))
    thread.start()
def message_to_user_thread(message: telebot.types.Message):
    """отправка сообщения от админа юзеру"""
    args = message.text.split(maxsplit=2)

    try:
        uid = int(args[1])
        text = args[2]
        bot.send_message(uid, text, message_thread_id = 0, disable_notification=True)
        bot_reply_tr(message, 'ok')
        my_log.log_echo(message, f'Admin sent message to user {uid}: {text}')
        return
    except:
        pass
    bot_reply_tr(message, 'Usage: /msg userid_as_int text to send from admin to user')


@bot.message_handler(commands=['alert'], func=authorized_admin)
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
    chat_full_id = get_topic_id(message)
    lang = get_lang(chat_full_id, message)

    if message.chat.id in cfg.admins:
        text = message.text[7:]
        if text:
            text = utils.bot_markdown_to_html(text)
            text = f'<b>{tr("Широковещательное сообщение от Верховного Адмнистратора, не обращайте внимания", lang)}</b>' + '\n\n\n' + text

            ids = []
            all_users = [x[0] for x in my_gemini.CHATS.items()] + [x[0] for x in CHAT_MODE.items()]
            all_users = list(set(CHAT_MODE.items()))
            for x in all_users:
                x = x[0]
                x = x.replace('[','').replace(']','')
                chat = int(x.split()[0])
                # if chat not in cfg.admins:
                #     return
                thread = int(x.split()[1])

                # в чаты не слать
                if chat < 0:
                    continue
                chat_id = f'[{chat}] [{thread}]'
                # заблокированым не посылать
                if chat_id in DDOS_BLOCKED_USERS:
                    continue
                if chat_id in BAD_USERS:
                    continue
                # только тех кто был активен в течение 7 дней
                if chat_id in LAST_TIME_ACCESS and LAST_TIME_ACCESS[chat_id] + (3600*7*24) < time.time():
                    continue

                ids.append(chat_id)
                try:
                    bot.send_message(chat_id = chat, message_thread_id=thread, text = text, parse_mode='HTML',
                                    disable_notification = True, reply_markup=get_keyboard('translate', message))
                    my_log.log2(f'tb:alert: sent to {chat_id}')
                except Exception as error2:
                    my_log.log2(f'tb:alert: {error2}')
                time.sleep(0.3)
            bot_reply(message, 'Sent to: ' + ', '.join(ids) + '\n\nTotal: ' + str(len(ids)))
            return

    bot_reply_tr(message, '/alert <текст сообщения которое бот отправит всем кого знает, форматирование маркдаун> Только администраторы могут использовать эту команду')


@bot.message_handler(commands=['ask2', 'а2'], func=authorized)
def ask_file(message: telebot.types.Message):
    '''ответ по сохраненному файлу, вариант с чистым промптом'''
    message.text += '[123CLEAR321]'
    ask_file(message)


@bot.message_handler(commands=['ask', 'а'], func=authorized)
def ask_file(message: telebot.types.Message):
    '''ответ по сохраненному файлу'''
    thread = threading.Thread(target=ask_file_thread, args=(message,))
    thread.start()
def ask_file_thread(message: telebot.types.Message):
    '''ответ по сохраненному файлу'''
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    try:
        query = message.text.split(maxsplit=1)[1]
    except IndexError:
        bot_reply_tr(message, 'Usage: /ask <query saved text>\n\nWhen you send a text document or link to the bot, it remembers the text, and in the future you can ask questions about the saved text.')
        if chat_id_full in USER_FILES:
            msg = f'{tr("Загружен файл/ссылка:", lang)} {USER_FILES[chat_id_full][0]}\n\n{tr("Размер текста:", lang)} {len(USER_FILES[chat_id_full][1])}'
            bot_reply(message, msg, disable_web_page_preview = True)
            return

    if chat_id_full in USER_FILES:
        with ShowAction(message, 'typing'):
            if message.text.endswith('[123CLEAR321]'):
                message.text = message.text[:-13]
                q = f"{message.text}\n\n{tr('URL/file:', lang)} {USER_FILES[chat_id_full][0]}\n\n{tr('Saved text:', lang)} {USER_FILES[chat_id_full][1]}"
            else:
                q = f'''{tr('Answer the user`s query using saved text and your own mind.', lang)}

{tr('User query:', lang)} {query}

{tr('URL/file:', lang)} {USER_FILES[chat_id_full][0]}

{tr('Saved text:', lang)} {USER_FILES[chat_id_full][1]}
    '''
            result = my_gemini.ai(q, temperature=0.1, tokens_limit=8000, model = 'gemini-1.5-flash-latest')
            if result:
                answer = utils.bot_markdown_to_html(result)
                bot_reply(message, answer, parse_mode='HTML')
                add_to_bots_mem(tr("The user asked to answer the question based on the saved text:", lang) + ' ' + USER_FILES[chat_id_full][0],
                                result, chat_id_full)
            else:
                bot_reply_tr(message, 'No reply from AI')
                return
    else:
        bot_reply_tr(message, 'Usage: /ask <query saved text>')
        bot_reply_tr(message, 'No text was saved')
        return


@bot.message_handler(commands=['sum'], func=authorized)
def summ_text(message: telebot.types.Message):
    # автоматически выходить из забаненых чатов
    thread = threading.Thread(target=summ_text_thread, args=(message,))
    thread.start()
def summ_text_thread(message: telebot.types.Message):

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    text = message.text

    if len(text.split(' ', 1)) == 2:
        url = text.split(' ', 1)[1].strip()
        if my_sum.is_valid_url(url):
            # убираем из ютуб урла временную метку
            if '/youtu.be/' in url or 'youtube.com/' in url:
                url = url.split("&t=")[0]

            url_id = str([url, lang])
            with semaphore_talks:

                #смотрим нет ли в кеше ответа на этот урл
                r = ''
                if url_id in SUM_CACHE:
                    r = SUM_CACHE[url_id]
                if r:
                    USER_FILES[chat_id_full] = (url, r)
                    rr = utils.bot_markdown_to_html(r)
                    bot_reply(message, rr, disable_web_page_preview = True,
                                          parse_mode='HTML',
                                          reply_markup=get_keyboard('translate', message))
                    add_to_bots_mem(tr("попросил кратко пересказать содержание текста по ссылке/из файла", lang) + ' ' + url,
                                         f'{tr("прочитал и ответил:", lang)} {r}',
                                         chat_id_full)
                    return

                with ShowAction(message, 'typing'):
                    res = ''
                    try:
                        res, text = my_sum.summ_url(url, lang = lang)
                        USER_FILES[chat_id_full] = (url, text)
                    except Exception as error2:
                        print(error2)
                        bot_reply_tr(message, 'Не нашел тут текста. Возможно что в видео на ютубе нет субтитров или страница слишком динамическая и не показывает текст без танцев с бубном, или сайт меня не пускает.\n\nЕсли очень хочется то отправь мне текстовый файл .txt (utf8) с текстом этого сайта и подпиши `что там`', parse_mode='Markdown')
                        return
                    if res:
                        rr = utils.bot_markdown_to_html(res)
                        bot_reply(message, rr, parse_mode='HTML',
                                              disable_web_page_preview = True,
                                              reply_markup=get_keyboard('translate', message))
                        SUM_CACHE[url_id] = res
                        add_to_bots_mem(tr("попросил кратко пересказать содержание текста по ссылке/из файла", lang) + ' ' + url,
                                         f'{tr("прочитал и ответил:", lang)} {res}',
                                         chat_id_full)
                        return
                    else:
                        bot_reply_tr(message, 'Не смог прочитать текст с этой страницы.')
                        return
    help = f"""{tr('Пример:', lang)} /sum https://youtu.be/3i123i6Bf-U

{tr('Давайте вашу ссылку и я перескажу содержание', lang)}"""
    COMMAND_MODE[chat_id_full] = 'sum'
    bot_reply(message, help, parse_mode = 'Markdown', reply_markup=get_keyboard('command_mode', message))


@bot.message_handler(commands=['sum2'], func=authorized)
def summ2_text(message: telebot.types.Message):
    # убирает запрос из кеша если он там есть и делает запрос снова

    text = message.text

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    if len(text.split(' ', 1)) == 2:
        url = text.split(' ', 1)[1].strip()
        if my_sum.is_valid_url(url):
            # убираем из ютуб урла временную метку
            if '/youtu.be/' in url or 'youtube.com/' in url:
                url = url.split("&t=")[0]
            url_id = str([url, lang])
            #смотрим нет ли в кеше ответа на этот урл
            if url_id in SUM_CACHE:
                SUM_CACHE.pop(url_id)

    summ_text(message)


@bot.message_handler(commands=['trans', 'tr', 't'], func=authorized)
def trans(message: telebot.types.Message):
    thread = threading.Thread(target=trans_thread, args=(message,))
    thread.start()
def trans_thread(message: telebot.types.Message):

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

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
            bot_reply(message, help, parse_mode = 'Markdown',
                         reply_markup=get_keyboard('command_mode', message))
            return
        llang = llang.strip()
        if llang == 'ua':
            llang = 'uk'

        with ShowAction(message, 'typing'):
            translated = my_trans.translate_text2(text, llang)
            if translated:
                detected_langs = []
                try:
                    for x in my_trans.detect_langs(text):
                        # l = my_trans.lang_name_by_code(x.lang)
                        l = tr(langcodes.Language.make(language=x.lang).display_name(language='en'), lang, 'это перевод названия языка, одно слово, прилагательное')
                        p = round(x.prob*100, 2)
                        detected_langs.append(f'{l} {p}%')
                except Exception as detect_error:
                    my_log.log2(f'tb:trans:detect_langs: {detect_error}')
                if match and match.group(1):
                    bot_reply(message, translated,
                                 reply_markup=get_keyboard('translate', message))
                else:
                    bot_reply(message,
                                 translated + '\n\n' + tr('Распознанные языки:', lang) \
                                 + ' ' + str(', '.join(detected_langs)).strip(', '),
                                 reply_markup=get_keyboard('translate', message))
            else:
                bot_reply_tr(message, 'Ошибка перевода')


@bot.message_handler(commands=['name'], func=authorized_owner)
def send_name(message: telebot.types.Message):
    """Меняем имя если оно подходящее, содержит только русские и английские буквы и не
    слишком длинное"""

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

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
            bot_reply(message, msg)
        else:
            msg = f"{tr('Неправильное имя, цифры после букв, не больше 10 всего. Имена', lang)} {', '.join(BAD_NAMES) if BAD_NAMES else ''} {tr('уже заняты.', lang)}"
            bot_reply(message, msg)
    else:
        help = f"{tr('Напишите новое имя бота и я поменяю его, цифры после букв, не больше 10 всего. Имена', lang)} {', '.join(BAD_NAMES) if BAD_NAMES else ''} {tr('уже заняты.', lang)}"
        COMMAND_MODE[chat_id_full] = 'name'
        bot_reply(message, help, parse_mode='Markdown', reply_markup=get_keyboard('command_mode', message))


@bot.message_handler(commands=['ocr'], func=authorized)
def ocr_setup(message: telebot.types.Message):
    """меняет настройки ocr"""

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    COMMAND_MODE[chat_id_full] = ''

    try:
        arg = message.text.split(maxsplit=1)[1]
    except IndexError:
        msg = f'''/ocr langs

<code>/ocr rus+eng</code>

{tr("""Меняет настройки OCR

Не указан параметр, какой язык (код) или сочетание кодов например""", lang)} rus+eng+ukr

{tr("Сейчас выбран:", lang)} <b>{get_ocr_language(message)}</b>

https://tesseract-ocr.github.io/tessdoc/Data-Files-in-different-versions.html'''

        bot_reply(message, msg, parse_mode='HTML',
                     reply_markup=get_keyboard('hide', message),
                     disable_web_page_preview=True)
        return

    llang = get_ocr_language(message)

    msg = f'{tr("Старые настройки:", lang)} {llang}\n\n{tr("Новые настройки:", lang)} {arg}'
    OCR_DB[chat_id_full] = arg
    
    bot_reply(message, msg, parse_mode='HTML')


@bot.message_handler(commands=['start'], func = authorized_log)
def send_welcome_start(message: telebot.types.Message) -> None:
    # автоматически выходить из забаненых чатов
    thread = threading.Thread(target=send_welcome_start_thread, args=(message,))
    thread.start()
def send_welcome_start_thread(message: telebot.types.Message):
    # Отправляем приветственное сообщение
    chat_id_full = get_topic_id(message)
    COMMAND_MODE[chat_id_full] = ''
    if chat_id_full not in CHAT_MODE:
        CHAT_MODE[chat_id_full] = cfg.chat_mode_default
    help = '''Hello, I`m AI chat bot powered by Google Gemini [1.0/1.5/Vision/Flash], llama3-70 etc!

Ask me anything. Send me you text/image/audio/documents with questions.

You can change language with /lang command.

You can generate images with /image command. Image editing is not supported yet.
'''
    bot_reply_tr(message, help, parse_mode='HTML', disable_web_page_preview=True, reply_markup=get_keyboard('start', message))


@bot.message_handler(commands=['help'], func = authorized_log)
def send_welcome_help(message: telebot.types.Message) -> None:
    thread = threading.Thread(target=send_welcome_help_thread, args=(message,))
    thread.start()
def send_welcome_help_thread(message: telebot.types.Message):
    # Отправляем приветственное сообщение

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    COMMAND_MODE[chat_id_full] = ''

    help = f"""The chatbot responds to the name bot.
For example, you can say bot, tell me a joke.
In private messages, you don't need to mention the bot's name

🔭 If you send a link or text file in a private message, the bot will try to extract and provide a brief summary of the content.
After the file or link is downloaded, you can ask questions using the /ask command.

🛸 To get text from an image, send the image with the caption "ocr". Send message with caption starting "?" for image describe.

🎙️ You can issue commands and make requests using voice messages.

👻 /purge command to remove all your data

Change model:
/gemini10 - Google Gemini 1.5 flash
/gemini15 - Google Gemini 1.5 pro
/llama370 - LLaMa 3 70b (Groq)
/openrouter - all other models including new GPT-4o, Claude 3 Opus etc

Report issues on Telegram:
https://t.me/kun4_sun_bot_support

"""

    with ShowAction(message, 'typing'):
        if chat_id_full in HELP_MSG and HELP_MSG[chat_id_full]:
            ai_generated_help = HELP_MSG[chat_id_full]
            new_run = False
        else:
            ai_generated_help = my_gemini.chat(f'Write a help message for Telegram users in language [{lang}] using this text as a source:\n\n' + help, chat_id_full, update_memory=False)
            new_run = True

        if ai_generated_help:
            if new_run:
                help = utils.bot_markdown_to_html(ai_generated_help)
                HELP_MSG[chat_id_full] = help
            else:
                help = ai_generated_help
        else:
            help = tr(help, lang)

        try:
            bot_reply(message, help, parse_mode='HTML', disable_web_page_preview=True)
        except Exception as error:
            print(f'tb:send_welcome_help: {error}')
            my_log.log2(f'tb:send_welcome_help: {error}')
            bot_reply(message, help, parse_mode='', disable_web_page_preview=True)


@bot.message_handler(commands=['report'], func = authorized_log) 
def report_cmd_handler(message: telebot.types.Message):
    chat_id_full = get_topic_id(message)
    COMMAND_MODE[chat_id_full] = ''
    bot_reply_tr(message, 'Support telegram group https://t.me/kun4_sun_bot_support')


@bot.message_handler(commands=['purge'], func = authorized_owner)
def purge_cmd_handler(message: telebot.types.Message):
    """удаляет логи юзера"""
    try:
        is_private = message.chat.type == 'private'
        if is_private:
            chat_id_full = get_topic_id(message)
        else:
            if message.is_topic_message:
                chat_id_full = get_topic_id(message)
            else:
                chat_id_full = f'[{message.chat.id}] [0]'

        COMMAND_MODE[chat_id_full] = ''

        if my_log.purge(message.chat.id):
            lang = get_lang(chat_id_full, message)

            my_gemini.reset(chat_id_full)
            my_groq.reset(chat_id_full)
            my_openrouter.reset(chat_id_full)

            ROLES[chat_id_full] = ''
            BOT_NAMES[chat_id_full] = BOT_NAME_DEFAULT
            if chat_id_full in USER_FILES:
                del USER_FILES[chat_id_full]

            if chat_id_full in LOGS_GROUPS_DB:
                try:
                    r = bot.delete_forum_topic(cfg.LOGS_GROUP, LOGS_GROUPS_DB[chat_id_full])
                    del LOGS_GROUPS_DB[chat_id_full]
                    if not r:
                        my_log.log2(f'tb:purge_cmd_handler: {LOGS_GROUPS_DB[chat_id_full]} not deleted')
                except Exception as unknown:
                    error_traceback = traceback.format_exc()
                    my_log.log2(f'tb:purge_cmd_handler: {unknown}\n\n{chat_id_full}\n\n{error_traceback}')

            msg = f'{tr("Your logs was purged. Keep in mind there could be a backups and some mixed logs. It is hard to erase you from the internet.", lang)}'
        else:
            msg = f'{tr("Error. Your logs was NOT purged.", lang)}'
        bot_reply(message, msg)
    except Exception as unknown:
        error_traceback = traceback.format_exc()
        my_log.log(f'tb:purge_cmd_handler: {unknown}\n\n{message.chat.id}\n\n{error_traceback}')


@bot.message_handler(commands=['id'], func = authorized_log) 
def id_cmd_handler(message: telebot.types.Message):
    """показывает id юзера и группы в которой сообщение отправлено"""
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    COMMAND_MODE[chat_id_full] = ''

    user_id = message.from_user.id
    reported_language = message.from_user.language_code
    msg = f'''{tr("ID пользователя:", lang)} {user_id}
                 
{tr("ID группы:", lang)} {chat_id_full}

{tr("Язык который телеграм сообщает боту:", lang)} {reported_language}

{tr("Выбранная чат модель:", lang)} {CHAT_MODE[chat_id_full] if chat_id_full in CHAT_MODE else cfg.chat_mode_default}
'''

    if chat_id_full in BAD_USERS:
        msg += f'\n{tr("User was banned.", lang)}\n'
    if str(message.chat.id) in DDOS_BLOCKED_USERS and chat_id_full not in BAD_USERS:
        msg += f'\n{tr("User was temporarily banned.", lang)}\n'
    bot_reply(message, msg)


@bot.message_handler(commands=['enable'], func=authorized_admin)
def enable_chat(message: telebot.types.Message):
    """что бы бот работал в чате надо его активировать там"""
    chat_full_id = get_topic_id(message)
    CHAT_ENABLED[chat_full_id] = True
    bot_reply_tr(message, 'Chat enabled.')


@bot.message_handler(commands=['disable'], func=authorized_admin)
def disable_chat(message: telebot.types.Message):
    """что бы бот не работал в чате надо его деактивировать там"""
    chat_full_id = get_topic_id(message)
    del CHAT_ENABLED[chat_full_id]
    bot_reply_tr(message, 'Chat disabled.')


@bot.message_handler(commands=['init'], func=authorized_admin)
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

    def get_seconds(s):
        match = re.search(r"after\s+(?P<seconds>\d+)", s)
        if match:
            return int(match.group("seconds"))
        else:
            return 0

    bot_reply_tr(message, "Localization will take a long time, do not repeat this command.")

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
                        my_log.log2(f'tb:init:command {lang} {description}')
                        commands.append(telebot.types.BotCommand(command, description))
                except Exception as error:
                    my_log.log2(f'Failed to read default commands for language {lang}: {error}')
        result = False
        try:
            l1 = [x.description for x in bot.get_my_commands(language_code=lang)]
            l2 = [x.description for x in commands]
            if l1 != l2:
                result = bot.set_my_commands(commands, language_code=lang)
            else:
                result = True
        except Exception as error_set_command:
            my_log.log2(f'Failed to set default commands for language {lang}: {error_set_command} ')
            time.sleep(get_seconds(str(error_set_command)))
            try:
                if l1 != l2:
                    result = bot.set_my_commands(commands, language_code=lang)
                else:
                    result = True
            except Exception as error_set_command2:
                my_log.log2(f'Failed to set default commands for language {lang}: {error_set_command2}')
        if result:
            result = '✅'
        else:
            result = '❌'

        msg = f'{result} Default commands set [{lang}]'
        msg_commands += msg + '\n'
    bot_reply(message, msg_commands)

    new_bot_name = cfg.bot_name.strip()
    new_description = cfg.bot_description.strip()
    new_short_description = cfg.bot_short_description.strip()

    msg_bot_names = ''
    for lang in most_used_langs:
        result = False
        try:
            if bot.get_my_name(language_code=lang).name != tr(new_bot_name, lang):
                result = bot.set_my_name(tr(new_bot_name, lang), language_code=lang)
                my_log.log2(f'tb:init:name {lang} {tr(new_bot_name, lang)}')
            else:
                result = True
        except Exception as error_set_name:
            my_log.log2(f"Failed to set bot's name: {tr(new_bot_name, lang)}" + '\n\n' + str(error_set_name))
            time.sleep(get_seconds(str(error_set_name)))
            try:
                if bot.get_my_name(language_code=lang).name != tr(new_bot_name, lang):
                    result = bot.set_my_name(tr(new_bot_name, lang), language_code=lang)
                    my_log.log2(f'tb:init::name {lang} {tr(new_bot_name, lang)}')
                else:
                    result = True
            except Exception as error_set_name2:
                my_log.log2(f"Failed to set bot's name: {tr(new_bot_name, lang)}" + '\n\n' + str(error_set_name2))
        if result:
            msg_bot_names += "✅ Bot's name set for language " + lang + f' [{tr(new_bot_name, lang)}]\n'
        else:
            msg_bot_names += "❌ Bot's name set for language " + lang + f' [{tr(new_bot_name, lang)}]\n'
    bot_reply(message, msg_bot_names)

    msg_descriptions = ''
    for lang in most_used_langs:
        result = False
        try:
            if bot.get_my_description(language_code=lang).description != tr(new_description, lang):
                result = bot.set_my_description(tr(new_description, lang), language_code=lang)
                my_log.log2(f'tb:init:desc {lang} {tr(new_description, lang)}')
            else:
                result = True
        except Exception as error_set_description:
            my_log.log2(f"Failed to set bot's description {lang}: {tr(new_description, lang)}" + '\n\n' + str(error_set_description))
            time.sleep(get_seconds(str(error_set_description)))
            try:
                if bot.get_my_description(language_code=lang).description != tr(new_description, lang):
                    result = bot.set_my_description(tr(new_description, lang), language_code=lang)
                    my_log.log2(f'tb:init::desc {lang} {tr(new_description, lang)}')
                else:
                    result = True
            except Exception as error_set_description2:
                my_log.log2(f"Failed to set bot's description {lang}: {tr(new_description, lang)}" + '\n\n' + str(error_set_description2))
                msg_descriptions += "❌ New bot's description set for language " + lang + '\n'
                continue
        if result:
            msg_descriptions += "✅ New bot's description set for language " + lang + '\n'
        else:
            msg_descriptions += "❌ New bot's description set for language " + lang + '\n'
    bot_reply(message, msg_descriptions)

    msg_descriptions = ''
    for lang in most_used_langs:
        result = False
        try:
            if bot.get_my_short_description(language_code=lang).short_description != tr(new_short_description, lang):
                result = bot.set_my_short_description(tr(new_short_description, lang), language_code=lang)
                my_log.log2(f'tb:init:short_desc {lang} {tr(new_short_description, lang)}')
            else:
                result = True
        except Exception as error_set_short_description:
            my_log.log2(f"Failed to set bot's short description: {tr(new_short_description, lang)}" + '\n\n' + str(error_set_short_description))
            time.sleep(get_seconds(str(error_set_short_description)))
            try:
                if bot.get_my_short_description(language_code=lang).short_description != tr(new_short_description, lang):
                    result = bot.set_my_short_description(tr(new_short_description, lang), language_code=lang)
                    my_log.log2(f'tb:init::short_desc {lang} {tr(new_short_description, lang)}')
                else:
                    result = True
            except Exception as error_set_short_description2:
                my_log.log2(f"Failed to set bot's short description: {tr(new_short_description, lang)}" + '\n\n' + str(error_set_short_description2))
                msg_descriptions += "❌ New bot's short description set for language " + lang + '\n'
                continue
        if result:
            msg_descriptions += "✅ New bot's short description set for language " + lang + '\n'
        else:
            msg_descriptions += "❌ New bot's short description set for language " + lang + '\n'
    bot_reply(message, msg_descriptions)
    bot_reply_tr(message, 'Init finished.')


def send_long_message(message: telebot.types.Message, resp: str, parse_mode:str = None, disable_web_page_preview: bool = None,
                      reply_markup: telebot.types.InlineKeyboardMarkup = None, allow_voice: bool = False):
    """отправляем сообщение, если оно слишком длинное то разбивает на 2 части либо отправляем как текстовый файл"""
    reply_to_long_message(message=message, resp=resp, parse_mode=parse_mode,
                          disable_web_page_preview=disable_web_page_preview,
                          reply_markup=reply_markup, send_message = True,
                          allow_voice=allow_voice)


def reply_to_long_message(message: telebot.types.Message, resp: str, parse_mode: str = None,
                          disable_web_page_preview: bool = None,
                          reply_markup: telebot.types.InlineKeyboardMarkup = None, send_message: bool = False,
                          allow_voice: bool = False):
    # отправляем сообщение, если оно слишком длинное то разбивает на 2 части либо отправляем как текстовый файл

    if not resp:
        return

    chat_id_full = get_topic_id(message)

    preview = telebot.types.LinkPreviewOptions(is_disabled=disable_web_page_preview)

    if len(resp) < 32000:
        if parse_mode == 'HTML':
            chunks = utils.split_html(resp, 3800)
        else:
            chunks = utils.split_text(resp, 3800)
        counter = len(chunks)
        for chunk in chunks:
            # в режиме только голоса ответы идут голосом без текста
            # скорее всего будет всего 1 чанк, не слишком длинный текст
            if chat_id_full in VOICE_ONLY_MODE and VOICE_ONLY_MODE[chat_id_full] and allow_voice:
                message.text = '/tts ' + chunk
                tts(message)
            else:
                try:
                    if send_message:
                        m = bot.send_message(message.chat.id, chunk, message_thread_id=message.message_thread_id, parse_mode=parse_mode,
                                         link_preview_options=preview, reply_markup=reply_markup)
                    else:
                        m = bot.reply_to(message, chunk, parse_mode=parse_mode,
                                link_preview_options=preview, reply_markup=reply_markup)
                    log_message(m)
                except Exception as error:
                    if "Error code: 400. Description: Bad Request: can't parse entities" in str(error):
                        error_traceback = traceback.format_exc()
                        my_log.log_parser_error(f'{str(error)}\n\n{error_traceback}\n\n{DEBUG_MD_TO_HTML[resp]}\n=====================================================\n{resp}')
                    else:
                        my_log.log2(f'tb:reply_to_long_message: {error}')
                        my_log.log2(chunk)
                    if send_message:
                        m = bot.send_message(message.chat.id, chunk, message_thread_id=message.message_thread_id, parse_mode='',
                                            link_preview_options=preview, reply_markup=reply_markup)
                    else:
                        m = bot.reply_to(message, chunk, parse_mode='', link_preview_options=preview, reply_markup=reply_markup)
                    log_message(m)
            counter -= 1
            if counter < 0:
                break
            time.sleep(2)
    else:
        buf = io.BytesIO()
        buf.write(resp.encode())
        buf.seek(0)
        m = bot.send_document(message.chat.id, document=buf, message_thread_id=message.message_thread_id,
                              caption='resp.txt', visible_file_name = 'resp.txt', reply_markup=reply_markup)
        log_message(m)
    if resp in DEBUG_MD_TO_HTML:
        del DEBUG_MD_TO_HTML[resp]


@bot.message_handler(func=authorized)
def echo_all(message: telebot.types.Message, custom_prompt: str = '') -> None:
    thread = threading.Thread(target=do_task, args=(message, custom_prompt))
    thread.start()
def do_task(message, custom_prompt: str = ''):
    """default handler"""

    from_user_id = f'[{message.from_user.id}] [0]'
    if from_user_id in BAD_USERS and BAD_USERS[from_user_id]:
        return

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    # catch too long messages
    if chat_id_full not in MESSAGE_QUEUE:
        MESSAGE_QUEUE[chat_id_full] = message.text
        last_state = MESSAGE_QUEUE[chat_id_full]
        n = 10
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
        u_id_ = str(message.chat.id)
        if u_id_ in request_counter.counts:
            if request_counter.counts[u_id_]:
                request_counter.counts[u_id_].pop(0)
        return

    b_msg_draw = tr('🎨 Нарисуй', lang, 'это кнопка в телеграм боте для рисования, после того как юзер на нее нажимает у него запрашивается описание картинки, сделай перевод таким же коротким что бы надпись уместилась на кнопке, сохрани оригинальную эмодзи')
    b_msg_search = tr('🌐 Найди', lang, 'это кнопка в телеграм боте для поиска в гугле, после того как юзер на нее нажимает бот спрашивает у него что надо найти, сделай перевод таким же коротким что бы надпись уместилась на кнопке, сохрани оригинальную эмодзи')
    b_msg_summary = tr('📋 Перескажи', lang, 'это кнопка в телеграм боте для пересказа текста, после того как юзер на нее нажимает бот спрашивает у него ссылку на текст или файл с текстом, сделай перевод таким же коротким что бы надпись уместилась на кнопке, сохрани оригинальную эмодзи')
    b_msg_tts = tr('🎧 Озвучь', lang, 'это кнопка в телеграм боте для озвучивания текста, после того как юзер на нее нажимает бот спрашивает у него текст для озвучивания, сделай перевод таким же коротким что бы надпись уместилась на кнопке, сохрани оригинальную эмодзи')
    b_msg_translate = tr('🈶 Перевод', lang, 'это кнопка в телеграм боте для перевода текста, после того как юзер на нее нажимает бот спрашивает у него текст для перевода, сделай перевод таким же коротким что бы надпись уместилась на кнопке, сохрани оригинальную эмодзи')
    b_msg_settings = tr('⚙️ Настройки', lang, 'это кнопка в телеграм боте для перехода в настройки, сделай перевод таким же коротким что бы надпись уместилась на кнопке, сохрани оригинальную эмодзи')

    if any([x for x in (b_msg_draw, b_msg_search, b_msg_summary, b_msg_tts, b_msg_translate, b_msg_settings) if x == message.text]):
        if any([x for x in (b_msg_draw,) if x == message.text]):
            message.text = '/image'
            image(message)
        if any([x for x in (b_msg_search,) if x == message.text]):
            message.text = '/google'
            google(message)
        if any([x for x in (b_msg_summary,) if x == message.text]):
            message.text = '/sum'
            summ_text(message)
        if any([x for x in (b_msg_tts,) if x == message.text]):
            message.text = '/tts'
            tts(message)
        if any([x for x in (b_msg_translate,) if x == message.text]):
            message.text = '/trans'
            trans(message)
        if any([x for x in (b_msg_settings,) if x == message.text]):
            # если не админ в чате то нельзя вызывать меню
            if not (message.chat.type == 'private' or is_admin_member(message)):
                bot_reply_tr(message, "This command is only available to administrators")
                return
            message.text = '/config'
            config(message)
        return

    if custom_prompt:
        message.text = custom_prompt

    # кто по умолчанию отвечает
    if chat_id_full not in CHAT_MODE:
        CHAT_MODE[chat_id_full] = cfg.chat_mode_default

    # определяем откуда пришло сообщение  
    is_private = message.chat.type == 'private'
    if chat_id_full not in SUPER_CHAT:
        SUPER_CHAT[chat_id_full] = 0
    # если бот должен отвечать всем в этом чате то пусть ведет себя как в привате
    # но если это ответ на чье-то сообщение то игнорируем
    # if SUPER_CHAT[chat_id_full] == 1 and not is_reply_to_other:
    if SUPER_CHAT[chat_id_full] == 1:
        is_private = True

    # detect /tts command
    if (message.text.lower().startswith('/tts ') and is_private) \
    or (message.text.lower().startswith('/tts\n') and is_private) \
    or message.text.lower().startswith(f'/tts@{_bot_name} ') \
    or message.text.lower().startswith(f'/tts@{_bot_name}\n') \
    or (message.text.lower().strip() == '/tts' and is_private) \
    or message.text.lower().strip() == f'/tts@{_bot_name}':
        tts(message)
        return

    chat_mode_ = CHAT_MODE[chat_id_full]



    # # начиная с 30 мая
    # # не давать тем у кого нет ключей доступ к 1.5 pro
    chat_id_full__ = f'[{message.from_user.id}] [0]'
    # if chat_mode_ == 'gemini15' and is_private:
    #     if chat_id_full__ not in my_gemini.USER_KEYS or not my_gemini.USER_KEYS[chat_id_full__]:
    #         total_messages__ = CHAT_STATS_TEMP[chat_id_full__] if chat_id_full__ in CHAT_STATS_TEMP else 0
    #         if total_messages__ > 100:
    #             chat_mode_ = 'gemini'
    #             # каждые 100 сообщение напоминать о ключах
    #             if total_messages__ % 100 == 0:
    #                 msg = tr('This bot needs free API keys to function. Obtain keys at https://ai.google.dev/ and provide them to the bot using the command /keys xxxxxxx. Video instructions:', lang) + ' https://www.youtube.com/watch?v=6aj5a7qGcb4\n\nFree VPN: https://www.vpnjantit.com/'
    #                 bot_reply(message, msg, disable_web_page_preview = True)
    if is_private:
        if chat_id_full__ not in my_gemini.USER_KEYS or not my_gemini.USER_KEYS[chat_id_full__]:
            total_messages__ = CHAT_STATS_TEMP[chat_id_full__] if chat_id_full__ in CHAT_STATS_TEMP else 0
            # каждые 50 сообщение напоминать о ключах
            if total_messages__ > 1 and total_messages__ % 50 == 0:
                msg = tr('This bot needs free API keys to function. Obtain keys at https://ai.google.dev/ and provide them to the bot using the command /keys xxxxxxx. Video instructions:', lang) + ' https://www.youtube.com/watch?v=6aj5a7qGcb4\n\nFree VPN: https://www.vpnjantit.com/'
                bot_reply(message, msg, disable_web_page_preview = True)
    
    if datetime.datetime.now() > datetime.datetime(2024, 5, 30):
        if chat_id_full__ not in my_gemini.USER_KEYS or not my_gemini.USER_KEYS[chat_id_full__]:
            if GEMINI15_COUNTER.status(chat_id_full__) > 50 and chat_mode_ == 'gemini15':
                chat_mode_ = 'gemini'
        else:
            if GEMINI15_COUNTER.status(chat_id_full__) > 300 and chat_mode_ == 'gemini15':
                chat_mode_ = 'gemini'

    # обработка \image это неправильное /image
    if (message.text.lower().startswith('\\image ') and is_private):
        message.text = message.text.replace('/', '\\', 1)
        image(message)
        return

    # не обрабатывать неизвестные команды, если они не в привате, в привате можно обработать их как простой текст
    chat_bot_cmd_was_used = False

    with semaphore_talks:

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

        # удаляем пробелы в конце каждой строки
        message.text = "\n".join([line.rstrip() for line in message.text.split("\n")])

        msg = message.text.lower()

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

        message.text = message.text.strip()
        msg = message.text.lower()

        # если предварительно была введена какая то команда то этот текст надо отправить в неё
        if chat_id_full in COMMAND_MODE and not chat_bot_cmd_was_used:
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
                elif COMMAND_MODE[chat_id_full] == 'name':
                    message.text = f'/name {message.text}'
                    send_name(message)
                elif COMMAND_MODE[chat_id_full] == 'sum':
                    message.text = f'/sum {message.text}'
                    summ_text(message)
                COMMAND_MODE[chat_id_full] = ''
                return

        if msg == tr('забудь', lang) and (is_private or is_reply) or bot_name_used and msg==tr('забудь', lang):
            reset_(message)
            return

        if hasattr(cfg, 'PHONE_CATCHER') and cfg.PHONE_CATCHER:
            # если это номер телефона
            # удалить из текста все символы кроме цифр
            if len(msg) < 18 and len(msg) > 9  and not re.search(r"[^0-9+\-()\s]", msg):
                number = re.sub(r'[^0-9]', '', msg)
                if number:
                    if number.startswith(('7', '8')):
                        number = number[1:]
                    if len(number) == 10:
                        if number in CACHE_CHECK_PHONE:
                            response = CACHE_CHECK_PHONE[number][0]
                            text__ = CACHE_CHECK_PHONE[number][1]
                            USER_FILES[chat_id_full] = (f'User googled phone number: {message.text}', text__)
                        else:
                            with ShowAction(message, 'typing'):
                                # response, text__ = my_gemini.check_phone_number(number)
                                response, text__ = my_groq.check_phone_number(number)
                        if response:
                            USER_FILES[chat_id_full] = (f'User googled phone number: {message.text}', text__)
                            CACHE_CHECK_PHONE[number] = (response, text__)
                            response = utils.bot_markdown_to_html(response)
                            bot_reply(message, response, parse_mode='HTML', not_log=True)
                            my_log.log_echo(message, '[gemini] ' + response)
                            return

        # если в сообщении только ссылка и она отправлена боту в приват
        # тогда сумморизируем текст из неё
        if my_sum.is_valid_url(message.text) and is_private:
            if utils.is_image_link(message.text):
                with ShowAction(message, 'typing'):
                    text = img2txt(message.text, lang, chat_id_full)
                    if text:
                        text = utils.bot_markdown_to_html(text)
                        bot_reply(message, text, parse_mode='HTML',
                                            reply_markup=get_keyboard('translate', message))
                    else:
                        bot_reply_tr(message, 'Sorry, I could not answer your question.')
                    return
            else:
                message.text = '/sum ' + message.text
                summ_text(message)
                return

        # проверяем просят ли нарисовать что-нибудь
        if msg.startswith((tr('нарисуй', lang) + ' ', tr('нарисуй', lang) + ',', 'нарисуй ', 'нарисуй,', 'нарисуйте ', 'нарисуйте,', 'draw ', 'draw,')):
            prompt = message.text.split(' ', 1)[1]
            message.text = f'/image {prompt}'
            image_thread(message)
            return

        # можно перенаправить запрос к гуглу, но он долго отвечает
        # не локализуем
        if msg.startswith(('гугл ', 'гугл,', 'гугл\n')):
            message.text = f'/google {msg[5:]}'
            google(message)
            return

        # так же надо реагировать если это ответ в чате на наше сообщение или диалог происходит в привате
        elif is_reply or is_private or bot_name_used or chat_bot_cmd_was_used:
            if len(msg) > cfg.max_message_from_user:
                bot_reply(message, f'{tr("Слишком длинное сообщение для чат-бота:", lang)} {len(msg)} {tr("из", lang)} {cfg.max_message_from_user}')
                return

            if chat_id_full not in VOICE_ONLY_MODE:
                VOICE_ONLY_MODE[chat_id_full] = False
            if VOICE_ONLY_MODE[chat_id_full]:
                action = 'record_audio'
                message.text = f'[{tr("голосовое сообщение, возможны ошибки распознавания речи, отвечай просто без форматирования текста - ответ будет зачитан вслух", lang)}]: ' + message.text
            else:
                action = 'typing'

            # подсказка для ботов что бы понимали где и с кем общаются
            formatted_date = utils.get_full_time()
            if message.chat.title:
                lang_of_user = get_lang(f'[{message.from_user.id}] [0]', message) or lang
                if chat_id_full in ROLES and ROLES[chat_id_full]:
                    hidden_text = f'[Info to help you answer. You are a telegram chatbot named "{bot_name}", you are working in chat named "{message.chat.title}", your memory limited to last 40 messages, user have telegram commands (/img - image generator, /tts - text to speech, /trans - translate, /sum - summarize, /google - search, you can answer voice messages, images, documents), user name is "{message.from_user.full_name}", user language code is "{lang_of_user}", your current date is "{formatted_date}", your special role here is "{ROLES[chat_id_full]}", do not address the user by name unless it is required.]'
                else:
                    hidden_text = f'[Info to help you answer. You are a telegram chatbot named "{bot_name}", you are working in chat named "{message.chat.title}", your memory limited to last 40 messages, user have telegram commands (/img - image generator, /tts - text to speech, /trans - translate, /sum - summarize, /google - search, you can answer voice messages, images, documents), user name is "{message.from_user.full_name}", user language code is "{lang_of_user}", your current date is "{formatted_date}", do not address the user by name unless it is required.]'
            else:
                if chat_id_full in ROLES and ROLES[chat_id_full]:
                    hidden_text = f'[Info to help you answer. You are a telegram chatbot named "{bot_name}", you are working in private for user named "{message.from_user.full_name}", your memory limited to last 40 messages, user have telegram commands (/img - image generator, /tts - text to speech, /trans - translate, /sum - summarize, /google - search, you can answer voice messages, images, documents), user language code is "{lang}", your current date is "{formatted_date}", your special role here is "{ROLES[chat_id_full]}", do not address the user by name unless it is required.]'
                else:
                    hidden_text = f'[Info to help you answer. You are a telegram chatbot named "{bot_name}", you are working in private for user named "{message.from_user.full_name}", your memory limited to last 40 messages, user have telegram commands (/img - image generator, /tts - text to speech, /trans - translate, /sum - summarize, /google - search, you can answer voice messages, images, documents), user language code is "{lang}", your current date is "{formatted_date}", do not address the user by name unless it is required.]'
            if chat_id_full not in ORIGINAL_MODE:
                ORIGINAL_MODE[chat_id_full] = False
            if ORIGINAL_MODE[chat_id_full]:
                helped_query = message.text
            else:
                helped_query = f'{hidden_text} {message.text}'


            if chat_id_full not in CHAT_LOCKS:
                CHAT_LOCKS[chat_id_full] = threading.Lock()
            with CHAT_LOCKS[chat_id_full]:

                WHO_ANSWERED[chat_id_full] = chat_mode_
                time_to_answer_start = time.time()

                with CHAT_STATS_LOCK:
                    CHAT_STATS[time_to_answer_start] = (chat_id_full, chat_mode_)
                    if chat_id_full in CHAT_STATS_TEMP:
                        CHAT_STATS_TEMP[chat_id_full] += 1
                    else:
                        CHAT_STATS_TEMP[chat_id_full] = 1


                # если активирован режим общения с Gemini Pro
                if chat_mode_ == 'gemini':
                    if len(msg) > my_gemini.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для Gemini:", lang)} {len(msg)} {tr("из", lang)} {my_gemini.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            if chat_id_full not in GEMIMI_TEMP:
                                GEMIMI_TEMP[chat_id_full] = GEMIMI_TEMP_DEFAULT

                            answer = my_gemini.chat(helped_query, chat_id_full, GEMIMI_TEMP[chat_id_full],
                                                    model = 'gemini-1.0-pro')
                            if chat_id_full not in WHO_ANSWERED:
                                WHO_ANSWERED[chat_id_full] = 'gemini'
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'

                            flag_gpt_help = False
                            if not answer:
                                style_ = ROLES[chat_id_full] if chat_id_full in ROLES and ROLES[chat_id_full] else tr(f'Отвечай на языке юзера - {lang}', lang)
                                mem__ = my_gemini.get_mem_for_llama(chat_id_full)
                                answer = my_groq.ai(message.text, mem_ = mem__, system=style_)
                                flag_gpt_help = True
                                if not answer:
                                    answer = 'Gemini Pro ' + tr('did not answered, try to /reset and start again', lang)
                                    return
                                my_gemini.update_mem(message.text, answer, chat_id_full)

                            if not VOICE_ONLY_MODE[chat_id_full]:
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            if flag_gpt_help:
                                WHO_ANSWERED[chat_id_full] = f'👇llama3-70 {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'
                                my_log.log_echo(message, f'[Gemini + llama3-70] {answer}')
                            else:
                                my_log.log_echo(message, f'[Gemini] {answer}')
                            try:
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('gemini_chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'tb:do_task: {error}')
                                my_log.log2(f'tb:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('gemini_chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'tb:do_task:gemini {error3}\n{error_traceback}')
                        return

                # если активирован режим общения с Gemini Pro 1.5
                if chat_mode_ == 'gemini15':
                    if len(msg) > my_gemini.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для Gemini:", lang)} {len(msg)} {tr("из", lang)} {my_gemini.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            if chat_id_full not in GEMIMI_TEMP:
                                GEMIMI_TEMP[chat_id_full] = GEMIMI_TEMP_DEFAULT

                            answer = my_gemini.chat(helped_query, chat_id_full, GEMIMI_TEMP[chat_id_full],
                                                    model = 'gemini-1.5-pro-latest')
                            if chat_id_full not in WHO_ANSWERED:
                                WHO_ANSWERED[chat_id_full] = 'gemini15'
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'
                            flag_gpt_help = False
                            if not answer:
                                style_ = ROLES[chat_id_full] if chat_id_full in ROLES and ROLES[chat_id_full] else tr(f'Отвечай на языке юзера - {lang}', lang)
                                mem__ = my_gemini.get_mem_for_llama(chat_id_full)
                                answer = my_groq.ai(message.text, mem_ = mem__, system=style_)
                                flag_gpt_help = True
                                if not answer:
                                    answer = 'Gemini Pro ' + tr('did not answered, try to /reset and start again', lang)
                                    return
                                my_gemini.update_mem(message.text, answer, chat_id_full)
                            else:
                                GEMINI15_COUNTER.increment(chat_id_full)

                            if not VOICE_ONLY_MODE[chat_id_full]:
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            if flag_gpt_help:
                                WHO_ANSWERED[chat_id_full] = f'👇llama3-70 {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'
                                my_log.log_echo(message, f'[Gemini15 + llama3-70] {answer}')
                            else:
                                my_log.log_echo(message, f'[Gemini15] {answer}')
                            try:
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('gemini_chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'tb:do_task: {error}')
                                my_log.log2(f'tb:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('gemini_chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'tb:do_task:gemini {error3}\n{error_traceback}')
                        return

                # если активирован режим общения с groq llama 3 70b
                if chat_mode_ == 'llama370':
                    if len(msg) > my_groq.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для Groq llama 3 70b:", lang)} {len(msg)} {tr("из", lang)} {my_groq.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            if chat_id_full not in GEMIMI_TEMP:
                                GEMIMI_TEMP[chat_id_full] = GEMIMI_TEMP_DEFAULT

                            # answer = my_groq.chat(message.text, chat_id_full, GEMIMI_TEMP[chat_id_full],
                            #                         model = '', style = hidden_text)
                            style_ = ROLES[chat_id_full] if chat_id_full in ROLES and ROLES[chat_id_full] else tr(f'Отвечай на языке юзера - {lang}', lang)
                            # answer = my_groq.chat(message.text, chat_id_full, style=style_)
                            answer = my_groq.chat(f'({style_}) {message.text}', chat_id_full)

                            if chat_id_full not in WHO_ANSWERED:
                                WHO_ANSWERED[chat_id_full] = 'qroq-llama370'
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'

                            if not answer:
                                answer = 'Groq llama 3 70b ' + tr('did not answered, try to /reset and start again', lang)

                            if not VOICE_ONLY_MODE[chat_id_full]:
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            my_log.log_echo(message, f'[groq-llama370] {answer}')
                            try:
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('groq_groq-llama370_chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'tb:do_task: {error}')
                                my_log.log2(f'tb:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('groq_groq-llama370_chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'tb:do_task:llama370-groq {error3}\n{error_traceback}')
                        return


                # если активирован режим общения с openrouter
                if chat_mode_ == 'openrouter':
                    # не знаем какие там лимиты
                    # if len(msg) > my_openrouter.MAX_REQUEST:
                    #     bot_reply(message, f'{tr("Слишком длинное сообщение для openrouter:", lang)} {len(msg)} {tr("из", lang)} {my_openrouter.MAX_REQUEST}')
                    #     return

                    with ShowAction(message, action):
                        try:
                            if chat_id_full not in GEMIMI_TEMP:
                                GEMIMI_TEMP[chat_id_full] = GEMIMI_TEMP_DEFAULT

                            status, answer = my_openrouter.chat(message.text, chat_id_full)

                            if chat_id_full not in WHO_ANSWERED:
                                WHO_ANSWERED[chat_id_full] = 'openrouter'
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'

                            if not answer:
                                answer = 'Openrouter ' + tr('did not answered, try to /reset and start again. Check your balance https://openrouter.ai/credits', lang)

                            if not VOICE_ONLY_MODE[chat_id_full]:
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            my_log.log_echo(message, f'[openrouter] {answer}')
                            try:
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('openrouter_chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'tb:do_task: {error}')
                                my_log.log2(f'tb:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('openrouter_chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'tb:do_task:gemini {error3}\n{error_traceback}')
                        return


def main():
    """
    Runs the main function, which sets default commands and starts polling the bot.
    """

    my_gemini.load_users_keys()

    for x in CHAT_STATS.keys():
        uid = CHAT_STATS[x][0]
        cm = CHAT_STATS[x][1]
        if 'gemini' in str(cm) or 'llama' in str(cm):
            if uid in CHAT_STATS_TEMP:
                CHAT_STATS_TEMP[uid] += 1
            else:
                CHAT_STATS_TEMP[uid] = 1


    # set_default_commands()

    bot.polling(timeout=90, long_polling_timeout=90)


if __name__ == '__main__':
    main()
