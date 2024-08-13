#!/usr/bin/env python3

import chardet
import concurrent.futures
import datetime
import io
import hashlib
import os
import pickle
import re
import subprocess
import tempfile
import traceback
import threading
import time

import cairosvg
import langcodes
import prettytable
import PyPDF2
import telebot
from fuzzywuzzy import fuzz
from sqlitedict import SqliteDict

import cfg
import bing_img
import md2tgmd
import my_init
import my_genimg
import my_db
import my_ddg
import my_google
import my_gemini
import my_gpt4omini
import my_groq
import my_log
import my_ocr
import my_openrouter
import my_pandoc
import my_shadowjourney
import my_stt
import my_sum
import my_trans
import my_transcribe
import my_tts
import utils
from utils import async_run


# устанавливаем рабочую папку = папке в которой скрипт лежит
os.chdir(os.path.abspath(os.path.dirname(__file__)))

bot = telebot.TeleBot(cfg.token)
# bot = telebot.TeleBot(cfg.token, skip_pending=True)

_bot_name = bot.get_me().username
BOT_ID = bot.get_me().id


# телеграм группа для отправки сгенерированных картинок
pics_group = cfg.pics_group
pics_group_url = cfg.pics_group_url

# следим за наличием активности, если в бота никаких событий
# не прилетало 30 минут то перезапускаем принудительно, возможно телега зависла
ACTIVITY_MONITOR = {
    'last_activity': time.time(),
    'max_inactivity': datetime.timedelta(minutes=30).seconds,
}
ACTIVITY_DAEMON_RUN = True

# до 500 одновременных потоков для чата с гпт
semaphore_talks = threading.Semaphore(500)

# папка для постоянных словарей, памяти бота
if not os.path.exists('db'):
    os.mkdir('db')

# {user_id:True} была ли команда на остановку генерации image10
IMAGE10_STOP = {}

# сообщения приветствия и помощи
HELLO_MSG = {}
HELP_MSG = {}

# хранилище для запросов на поиск картинок
# {hash: search query}
SEARCH_PICS = {}

# блокировка чата что бы юзер не мог больше 1 запроса делать за раз,
# только для запросов к гпт*. {chat_id_full(str):threading.Lock()}
CHAT_LOCKS = {}

# блокировка на выполнение одновременных команд sum, google, image, document handler, voice handler
# {chat_id:threading.Lock()}
GOOGLE_LOCKS = {}
SUM_LOCKS = {}
IMG_GEN_LOCKS = {}
DOCUMENT_LOCKS = {}
VOICE_LOCKS = {}
IMG_LOCKS = {}

# хранилище номеров тем в группе для логов {full_user_id as str: theme_id as int}
# full_user_id - полный адрес места которое логируется, либо это юзер ип и 0 либо группа и номер в группе
# theme_id - номер темы в группе для логов
LOGS_GROUPS_DB = SqliteDict('db/logs_groups.db', autocommit=True)

# в каких чатах какая команда дана, как обрабатывать последующий текст
# например после команды /image ожидаем описание картинки
# COMMAND_MODE[chat_id] = 'google'|'image'|...
COMMAND_MODE = {}

# автоматически заблокированные за слишком частые обращения к боту 
# {user_id:Time to release in seconds - дата когда можно выпускать из бана} 
DDOS_BLOCKED_USERS = {}

# кешировать запросы типа кто звонил {number:(result, full text searched)}
CACHE_CHECK_PHONE = {}


# Глобальный массив для хранения состояния подписки (user_id: timestamp)
subscription_cache = {}

# запоминаем прилетающие сообщения, если они слишком длинные и
# были отправлены клиентом по кускам {id:[messages]}
# ловим сообщение и ждем секунду не прилетит ли еще кусок
MESSAGE_QUEUE = {}
# так же ловим пачки картинок(медиагруппы), телеграм их отправляет по одной
MESSAGE_QUEUE_IMG = {}

# блокировать процесс отправки картинок что бы не было перемешивания разных запросов
SEND_IMG_LOCK = threading.Lock()

GEMIMI_TEMP_DEFAULT = 1

# имя бота по умолчанию, в нижнем регистре без пробелов и символов
BOT_NAME_DEFAULT = cfg.default_bot_name

# тут сохраняются сообщения до и после преобразования из маркдауна ботов в хтмл
# {ответ после преобразования:ответ до преобразования, }
# это нужно только что бы записать в логи пару если html версия не пролезла через телеграм фильтр
DEBUG_MD_TO_HTML = {}

# запоминаем кто ответил что бы добавить это в лог в группу
# {user_id: 'chatbot'(gemini, gemini15 etc)}
WHO_ANSWERED = {}

# кеш для переводов в оперативной памяти
TRANS_CACHE = my_db.SmartCache()


# key - time.time() float
# value - list
#   type as string='new' or 'copy',
#   text as str,
#   chat_full_id as str,
#   chat_name as str,
#   m_ids as list of int,
#   message_chat_id as int,
#   message_message_id as int
LOG_GROUP_MESSAGES = SqliteDict('db/log_group_messages.db', autocommit=True)
LOG_GROUP_MESSAGES_LOCK = threading.Lock()
LOG_GROUP_DAEMON_ENABLED = True

# {id:True} кто из юзеров не в этом словаре тому обновить клавиатуру
NEW_KEYBOARD = SqliteDict('db/new_keyboard_installed.db', autocommit=True)


supported_langs_trans = my_init.supported_langs_trans
supported_langs_tts = my_init.supported_langs_tts


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

# {chat_id:lock}
SHOW_ACTION_LOCKS = {}

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
        self.full_chat_id = get_topic_id(message)
        self.thread_id = message.message_thread_id
        self.is_topic = True if message.is_topic_message else False
        self.action = action
        self.is_running = True
        self.timerseconds = 1
        self.started_time = time.time()

    def run(self):
        if self.full_chat_id not in SHOW_ACTION_LOCKS:
            SHOW_ACTION_LOCKS[self.full_chat_id] = threading.Lock()
        with SHOW_ACTION_LOCKS[self.full_chat_id]:
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


def tr(text: str, lang: str, help: str = '', save_cache: bool = True) -> str:
    """
    This function translates text to the specified language,
    using either the AI translation engine or the standard translation engine.

    Args:
        text: The text to translate.
        lang: The language to translate to.
        help: The help text for ai translator.
        save_cache: Whether to save the translated text in the DB on disk.

    Returns:
        The translated text.
    """
    if lang == 'fa':
        lang = 'en'
    if lang == 'ua':
        lang = 'uk'

    cache_key = (text, lang, help)
    cache_key_hash = hashlib.md5(str(cache_key).encode()).hexdigest()
    translated = TRANS_CACHE.get(cache_key_hash)
    if translated:
        return translated

    translated = my_db.get_translation(text, lang, help)
    if translated:
        TRANS_CACHE.set(cache_key_hash, translated)
        return translated

    translated = ''

    if help:
        translated = my_groq.translate(text, to_lang=lang, help=help)
        if not translated:
            # time.sleep(1)
            # try again and another ai engine
            translated = my_gemini.translate(text, to_lang=lang, help=help)
            if not translated:
                my_log.log_translate(f'gemini\n\n{text}\n\n{lang}\n\n{help}')

    if not translated:
        translated = my_trans.translate_text2(text, lang)

    if not translated:
        translated = my_trans.translate_deepl(text, to_lang = lang)

    if not translated and not help:
        translated = my_groq.translate(text, to_lang=lang, help=help)

    if not translated and not help:
        translated = my_gemini.translate(text, to_lang=lang, help=help)

    if not translated:
        translated = text

    TRANS_CACHE.set(cache_key_hash, translated)
    if save_cache:
        my_db.update_translation(text, lang, help, translated)

    return translated


def add_to_bots_mem(query: str, resp: str, chat_id_full: str):
    """
    Updates the memory of the selected bot based on the chat mode.

    Args:
        query: The user's query text.
        resp: The bot's response.
        chat_id_full: The full chat ID.
    """
    # Checks if there is a chat mode for the given chat, if not, sets the default value.
    if not my_db.get_user_property(chat_id_full, 'chat_mode'):
        my_db.set_user_property(chat_id_full, 'chat_mode', cfg.chat_mode_default)

    # Updates the memory of the selected bot based on the chat mode.
    if 'gemini' in my_db.get_user_property(chat_id_full, 'chat_mode'):
        my_gemini.update_mem(query, resp, chat_id_full)
    elif 'llama370' in my_db.get_user_property(chat_id_full, 'chat_mode'):
        my_groq.update_mem(query, resp, chat_id_full)
    elif 'openrouter' in my_db.get_user_property(chat_id_full, 'chat_mode'):
        my_openrouter.update_mem(query, resp, chat_id_full)
    elif 'gemma2-9b' in my_db.get_user_property(chat_id_full, 'chat_mode'):
        my_groq.update_mem(query, resp, chat_id_full)
    elif 'gpt4o' == my_db.get_user_property(chat_id_full, 'chat_mode'):
        my_shadowjourney.update_mem(query, resp, chat_id_full)
    elif 'gpt4omini' == my_db.get_user_property(chat_id_full, 'chat_mode'):
        my_gpt4omini.update_mem(query, resp, chat_id_full)
    elif 'haiku' in my_db.get_user_property(chat_id_full, 'chat_mode'):
        my_ddg.update_mem(query, resp, chat_id_full)
    elif 'gpt-4o-mini-ddg' in my_db.get_user_property(chat_id_full, 'chat_mode'):
        my_ddg.update_mem(query, resp, chat_id_full)


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
    else:
        query = query + '\n\n' + tr(f'Answer in "{lang}" language, if not asked other.', lang)

    if not my_db.get_user_property(chat_id_full, 'chat_mode'):
        my_db.set_user_property(chat_id_full, 'chat_mode', cfg.chat_mode_default)

    text = ''

    try:
        # text = my_gemini.img2txt(data, query, temp = 1,  model = 'gemini-1.5-flash')
        text = my_gemini.img2txt(data, query, temp = 1,  model = 'gemini-1.5-pro-exp-0801')
        # text = my_gemini.img2txt(data, query, temp = 1,  model = 'gemini-1.5-pro')
        if not text:
            text = my_gpt4omini.img2txt(data, query, temp = 1)
            my_db.add_msg(chat_id_full, 'gpt_4o_mini')
    except Exception as img_from_link_error:
        my_log.log2(f'tb:img2txt: {img_from_link_error}')

    if text:
        add_to_bots_mem(tr('User asked about a picture:', lang) + ' ' + query, text, chat_id_full)

    return text


def get_lang(user_id: str, message: telebot.types.Message = None) -> str:
    """
    Returns the language corresponding to the given ID.

    Args:
        user_id (str): The ID of the user.
        message (telebot.types.Message, optional): The message object. Defaults to None.

    Returns:
        str: The language corresponding to the given user ID.
    """
    lang = my_db.get_user_property(user_id, 'lang')

    if not lang:
        lang = cfg.DEFAULT_LANGUAGE
        if message:
            lang = message.from_user.language_code or cfg.DEFAULT_LANGUAGE
        my_db.set_user_property(user_id, 'lang', lang)

    if lang == 'pt-br':
        lang = 'pt'
    if lang.startswith('zh-'):
        lang = 'zh'

    return lang


def get_ocr_language(message) -> str:
    """Возвращает настройки языка OCR для этого чата"""
    try:
        chat_id_full = get_topic_id(message)

        lang = my_db.get_user_property(chat_id_full, 'ocr_lang')
        if not lang:
            if hasattr(cfg, 'ocr_language'):
                my_db.set_user_property(chat_id_full, 'ocr_lang', cfg.ocr_language)
            else:
                my_db.set_user_property(chat_id_full, 'ocr_lang', 'rus+eng')
            lang = my_db.get_user_property(chat_id_full, 'ocr_lang')
        return lang
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:get_ocr_language: {error}\n\n{traceback_error}')
        return 'rus+eng'


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


def check_blocked_user(id_: str, from_user_id: int, check_trottle = True):
    """Raises an exception if the user is blocked and should not be replied to"""
    for x in cfg.admins:
        if id_ == f'[{x}] [0]':
            return
    user_id = id_.replace('[','').replace(']','').split()[0]
    if check_trottle:
        if not request_counter.check_limit(user_id):
            my_log.log2(f'tb:check_blocked_user: User {id_} is blocked for DDoS')
            raise Exception(f'user {user_id} in ddos stop list, ignoring')

    from_user_id = f'[{from_user_id}] [0]'
    if my_db.get_user_property(from_user_id, 'blocked'):
        my_log.log2(f'tb:check_blocked_user: User {from_user_id} is blocked')
        raise Exception(f'user {from_user_id} in stop list, ignoring')

    if my_db.get_user_property(id_, 'blocked'):
        my_log.log2(f'tb:check_blocked_user: User {id_} is blocked')
        raise Exception(f'user {user_id} in stop list, ignoring')


def is_admin_member(message: telebot.types.Message) -> bool:
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
    if 'creator' in member or 'administrator' in member or chat_id in cfg.admins:
        return True
    else:
        if int(user_id) != int(chat_id):
            my_log.log2(f'User {user_id} is {member} of {chat_id}')
        return False


def is_for_me(message: telebot.types.Message) -> bool:
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


@async_run
def log_group_daemon():
    """
    This daemon function processes messages stored in the LOG_GROUP_MESSAGES queue.
    It sends new messages or copies existing messages to a designated logging group 
    based on their type and chat information. 

    The function retrieves the oldest message from the queue, extracts its details, 
    and then attempts to send or copy it to the appropriate forum topic within the 
    logging group. It handles potential errors during topic creation and message 
    sending/copying, logging any exceptions encountered. 

    The daemon continues processing messages until the LOG_GROUP_DAEMON_ENABLED flag 
    is set to False.
    """
    if not hasattr(cfg, 'LOGS_GROUP') or not cfg.LOGS_GROUP:
        return

    global LOG_GROUP_DAEMON_ENABLED
    group = 10
    while LOG_GROUP_DAEMON_ENABLED:
        try:
            time.sleep(3 + group) # telegram limit 1 message per second for groups
            group = 0
            with LOG_GROUP_MESSAGES_LOCK:
                try:
                    min_key = min(LOG_GROUP_MESSAGES.keys())
                except ValueError:
                    continue # no messages in queue
                value = LOG_GROUP_MESSAGES[min_key]
                _type = value[0]
                _text = value[1]
                _chat_full_id = value[2]
                _chat_name = value[3]
                _m_ids = value[4]
                _message_chat_id = value[5]
                _message_message_id = value[6]

                if _chat_full_id in LOGS_GROUPS_DB:
                    th = LOGS_GROUPS_DB[_chat_full_id]
                else:
                    try:
                        th = bot.create_forum_topic(cfg.LOGS_GROUP, _chat_full_id + ' ' + _chat_name).message_thread_id
                        LOGS_GROUPS_DB[_chat_full_id] = th
                    except Exception as error:
                        traceback_error = traceback.format_exc()
                        my_log.log2(f'tb:log_group_daemon:create group topic: {error}\n{traceback_error}')
                        del LOG_GROUP_MESSAGES[min_key] # drop message
                        continue

                if _type == 'new':
                    try:
                        bot.send_message(cfg.LOGS_GROUP, _text, message_thread_id=th)
                    except Exception as error2_0:
                        try:
                            if 'Bad Request: message thread not found' in str(error2_0):
                                th = bot.create_forum_topic(cfg.LOGS_GROUP, _chat_full_id + ' ' + _chat_name).message_thread_id
                                LOGS_GROUPS_DB[_chat_full_id] = th
                                bot.send_message(cfg.LOGS_GROUP, _text, message_thread_id=th)
                        except Exception as error2:
                            traceback_error = traceback.format_exc()
                            my_log.log2(f'tb:log_group_daemon:send message: {error2}\n{traceback_error}\n\n{_text}')

                elif _type == 'copy':
                    if _m_ids:
                        try:
                            group = len(_m_ids)*3
                            bot.copy_messages(cfg.LOGS_GROUP, _message_chat_id, _m_ids, message_thread_id=th)
                        except Exception as error3_0:
                            try:
                                if 'Bad Request: message thread not found' in str(error3_0):
                                    th = bot.create_forum_topic(cfg.LOGS_GROUP, _chat_full_id + ' ' + _chat_name).message_thread_id
                                    LOGS_GROUPS_DB[_chat_full_id] = th
                                    bot.copy_messages(cfg.LOGS_GROUP, _message_chat_id, _m_ids, message_thread_id=th)
                            except Exception as error3:
                                traceback_error = traceback.format_exc()
                                my_log.log2(f'tb:log_group_daemon:copy message: {error3}\n{traceback_error}\n\n{_text}')
                    else:
                        try:
                            bot.copy_message(cfg.LOGS_GROUP, _message_chat_id, _message_message_id, message_thread_id=th)
                        except Exception as error4_0:
                            try:
                                if 'Bad Request: message thread not found' in str(error4_0):
                                    th = bot.create_forum_topic(cfg.LOGS_GROUP, _chat_full_id + ' ' + _chat_name).message_thread_id
                                    LOGS_GROUPS_DB[_chat_full_id] = th
                                    bot.copy_message(cfg.LOGS_GROUP, _message_chat_id, _message_message_id, message_thread_id=th)
                            except Exception as error4:
                                traceback_error = traceback.format_exc()
                                my_log.log2(f'tb:log_group_daemon:copy message2: {error4}\n{traceback_error}\n\n{_text}')

                del LOG_GROUP_MESSAGES[min_key]
        except Exception as unknown_error:
            traceback_error = traceback.format_exc()
            my_log.log2(f'tb:log_group_daemon: {unknown_error}\n{traceback_error}')


def log_message_add(_type: str,
                    _text: str,
                    _chat_full_id: str,
                    _chat_name: str,
                    _m_ids: list,
                    _message_chat_id: int,
                    _message_message_id: int):
    """
    Adds a message to the LOG_GROUP_MESSAGES queue for logging.

    Args:
        _type (str): Type of the message ('new' or 'copy').
        _text (str): Text content of the message.
        _chat_full_id (str): Unique identifier for the chat.
        _chat_name (str): Name of the chat.
        _m_ids (list): List of message IDs (used for copied messages).
        _message_chat_id (int): ID of the chat the message belongs to.
        _message_message_id (int): Unique ID of the message.
    """
    with LOG_GROUP_MESSAGES_LOCK:
        current_time = time.time()
        while current_time in LOG_GROUP_MESSAGES:
            current_time += 0.001
        value = (_type, _text, _chat_full_id, _chat_name, _m_ids, _message_chat_id, _message_message_id)
        LOG_GROUP_MESSAGES[current_time] = value


def log_message(message: telebot.types.Message):
    """
    Logs a message or a list of messages to the designated logging group.

    This function checks if logging is enabled and if the message should be logged
    based on configuration. It then extracts relevant information from the message(s)
    and adds them to the LOG_GROUP_MESSAGES queue for processing by the log_group_daemon.

    Args:
        message (telebot.types.Message or list): The message or list of messages to log.
    """
    try:
        if isinstance(message, telebot.types.Message) and hasattr(cfg, 'DO_NOT_LOG') and message.chat.id in cfg.DO_NOT_LOG:
            return
        if isinstance(message, list) and hasattr(cfg, 'DO_NOT_LOG') and message[0].chat.id in cfg.DO_NOT_LOG:
            return

        if not hasattr(cfg, 'LOGS_GROUP') or not cfg.LOGS_GROUP:
            return

        if isinstance(message, telebot.types.Message):
            chat_full_id = get_topic_id(message)
            chat_name = utils.get_username_for_log(message)

            if chat_full_id in WHO_ANSWERED:
                log_message_add('new',
                                f'[{WHO_ANSWERED[chat_full_id]}]',
                                chat_full_id,
                                chat_name,
                                None, # m_ids
                                message.chat.id,
                                message.message_id)
                try:
                    del WHO_ANSWERED[chat_full_id]
                except KeyError:
                    pass

            log_message_add('copy',
                            '',
                            chat_full_id,
                            chat_name,
                            None,
                            message.chat.id,
                            message.message_id)

        elif isinstance(message, list):
            chat_full_id = get_topic_id(message[0])
            chat_name = utils.get_username_for_log(message[0])
            m_ids = [x.message_id for x in message]

            log_message_add('copy',
                            '',
                            chat_full_id,
                            chat_name,
                            m_ids,
                            message[0].chat.id,
                            message[0].message_id)
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log2(f'tb:log_message: {error}\n\n{error_traceback}')


def authorized_owner(message: telebot.types.Message) -> bool:
    """if chanel owner or private"""
    is_private = message.chat.type == 'private'

    # # banned users do nothing
    # chat_id_full = get_topic_id(message)
    # if my_db.get_user_property(chat_id_full, 'blocked'):
    #     return False

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
    # banned users do nothing
    if my_db.get_user_property(chat_id_full, 'blocked'):
        return False

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
    return bool(my_db.get_user_property(chat_id_full, 'chat_enabled'))


def authorized(message: telebot.types.Message) -> bool:
    """
    Check if the user is authorized based on the given message.

    Parameters:
        message (telebot.types.Message): The message object containing the chat ID and user ID.

    Returns:
        bool: True if the user is authorized, False otherwise.
    """

    ACTIVITY_MONITOR['last_activity'] = time.time()

    # full block, no logs
    chat_id_full = get_topic_id(message)
    if my_db.get_user_property(chat_id_full, 'blocked_totally'):
        return False

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

    if message.text:
        msg = message.text.lower() 
    else:
        msg = ''
    # разрешить удаление своей истории всем
    if msg == '/purge':
        return True

    # banned users do nothing
    chat_id_full = get_topic_id(message)
    if my_db.get_user_property(chat_id_full, 'blocked'):
        return False

    # if this chat was forcibly left (banned), then when trying to enter it immediately exit
    # I don't know how to do that, so I have to leave only when receiving any event
    if my_db.get_user_property(str(message.chat.id), 'auto_leave_chat') == True:
        try:
            bot.leave_chat(message.chat.id)
            my_log.log2('tb:leave_chat: auto leave ' + str(message.chat.id))
        except Exception as leave_chat_error:
            my_log.log2(f'tb:auth:live_chat_error: {leave_chat_error}')
        return False

    my_db.set_user_property(chat_id_full, 'last_time_access', time.time())

    # trottle only messages addressed to me
    is_private = message.chat.type == 'private'
    supch = my_db.get_user_property(chat_id_full, 'superchat') or 0
    if supch == 1:
        is_private = True


    # обновить клавиатуру старым юзерам
    if is_private:
        if chat_id_full not in NEW_KEYBOARD:
            bot_reply_tr(message, 'New keyboard installed.',
                         parse_mode='HTML',
                         disable_web_page_preview=True,
                         reply_markup=get_keyboard('start', message))
            NEW_KEYBOARD[chat_id_full] = True


    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == BOT_ID

    if message.text:
        if msg.startswith('.'):
            msg = msg[1:]

        bot_name = my_db.get_user_property(chat_id_full, 'bot_name') or BOT_NAME_DEFAULT

        bot_name_used = False
        if msg.startswith((f'{bot_name} ', f'{bot_name},', f'{bot_name}\n')):
            bot_name_used = True

        bot_name2 = f'@{_bot_name}'
        if msg.startswith((f'{bot_name2} ', f'{bot_name2},', f'{bot_name2}\n')):
            bot_name_used = True

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
            if message.text and message.text.startswith('/'):
                bot_reply(message, f'Not enabled here. Use /enable@{_bot_name} to enable in this chat.')
            return False
    if not check_subscription(message):
        return False

    # этого тут быть не должно но яхз что пошло не так, дополнительная проверка
    if my_db.get_user_property(chat_id_full, 'blocked'):
        my_log.log2(f'tb:authorized: User {chat_id_full} is blocked')
        return False

    return True


def authorized_log(message: telebot.types.Message) -> bool:
    """
    Only log and banned
    """
    ACTIVITY_MONITOR['last_activity'] = time.time()

    # full block, no logs
    chat_id_full = get_topic_id(message)
    if my_db.get_user_property(chat_id_full, 'blocked_totally'):
        return False

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

    # # banned users do nothing
    # chat_id_full = get_topic_id(message)
    # if my_db.get_user_property(chat_id_full, 'blocked'):
    #     return False

    # if this chat was forcibly left (banned), then when trying to enter it immediately exit
    # I don't know how to do that, so I have to leave only when receiving any event
    if my_db.get_user_property(str(message.chat.id), 'auto_leave_chat') == True:
        try:
            bot.leave_chat(message.chat.id)
            my_log.log2('tb:leave_chat: auto leave ' + str(message.chat.id))
        except Exception as leave_chat_error:
            my_log.log2(f'tb:auth:live_chat_error: {leave_chat_error}')
        return False

    return True


def check_blocks(chat_id_full: str) -> bool:
    """в каких чатах выключены автопереводы"""
    if not my_db.get_user_property(chat_id_full, 'auto_translations'):
        my_db.set_user_property(chat_id_full, 'auto_translations', 0)
    return False if my_db.get_user_property(chat_id_full, 'auto_translations') == 1 else True


def bot_reply_tr(message: telebot.types.Message,
              msg: str,
              parse_mode: str = None,
              disable_web_page_preview: bool = None,
              reply_markup: telebot.types.InlineKeyboardMarkup = None,
              send_message: bool = False,
              not_log: bool = False,
              allow_voice: bool = False,
              save_cache: bool = True,
              help: str = ''):
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    msg = tr(msg, lang, help, save_cache)
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
        if my_db.get_user_property(chat_id_full, 'disabled_kbd'):
            return None
        markup  = telebot.types.InlineKeyboardMarkup()
        button1 = telebot.types.InlineKeyboardButton(tr("Стереть историю", lang), callback_data='clear_history')
        button2 = telebot.types.InlineKeyboardButton(tr("Скрыть", lang), callback_data='erase_answer')
        markup.add(button1, button2)
        return markup
    elif kbd == 'download_saved_text':
        markup  = telebot.types.InlineKeyboardMarkup()
        button1 = telebot.types.InlineKeyboardButton(tr("Скачать", lang), callback_data='download_saved_text')
        button2 = telebot.types.InlineKeyboardButton(tr("Удалить", lang), callback_data='delete_saved_text')
        markup.add(button1, button2)
        return markup

    elif kbd == 'hide':
        if my_db.get_user_property(chat_id_full, 'disabled_kbd'):
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
        markup = telebot.types.InlineKeyboardMarkup(row_width=2)
        most_used_langs = ['en', 'zh', 'es', 'ar', 'hi', 'pt', 'bn', 'ru', 'ja', 'de', 'fr', 'it', 'tr', 'ko', 'id', 'vi']

        # Словарь с флагами
        flags = {
            'en': '🇬🇧',
            'zh': '🇨🇳',
            'es': '🇪🇸',
            'ar': '🇸🇦',
            'hi': '🇮🇳',
            'pt': '🇧🇷',
            'bn': '🇧🇩',
            'ru': '🇷🇺',
            'ja': '🇯🇵',
            'de': '🇩🇪',
            'fr': '🇫🇷',
            'it': '🇮🇹',
            'tr': '🇹🇷',
            'ko': '🇰🇷',
            'id': '🇮🇩',
            'vi': '🇻🇳'
        }

        pair = []
        for x in most_used_langs:
            native_name = langcodes.Language.make(language=x).display_name(language=x).capitalize()
            lang_name = f'{flags[x]} {native_name}'  # Добавляем флаг к названию языка
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
        if my_db.get_user_property(chat_id_full, 'disabled_kbd'):
            return None
        markup  = telebot.types.InlineKeyboardMarkup()
        button1 = telebot.types.InlineKeyboardButton(tr("Скрыть", lang), callback_data='erase_answer')
        button2 = telebot.types.InlineKeyboardButton("📢", callback_data='tts')
        button3 = telebot.types.InlineKeyboardButton(tr("Перевод", lang), callback_data='translate')
        markup.add(button1, button2, button3)
        return markup
    elif kbd == 'start':
        b_msg_draw = '/img'
        b_msg_search = '/google'
        b_msg_summary = '/sum'
        b_msg_tts = '/tts'
        b_msg_translate = '/trans'
        b_msg_settings = '/config'

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
        if my_db.get_user_property(chat_id_full, 'disabled_kbd'):
            return None
        markup  = telebot.types.InlineKeyboardMarkup(row_width=5)
        button0 = telebot.types.InlineKeyboardButton("➡", callback_data='continue_gpt')
        button1 = telebot.types.InlineKeyboardButton('♻️', callback_data='openrouter_reset')
        button2 = telebot.types.InlineKeyboardButton("🙈", callback_data='erase_answer')
        button3 = telebot.types.InlineKeyboardButton("📢", callback_data='tts')
        button4 = telebot.types.InlineKeyboardButton(lang, callback_data='translate_chat')
        markup.add(button0, button1, button2, button3, button4)
        return markup

    elif kbd == 'gpt4o_chat':
        if my_db.get_user_property(chat_id_full, 'disabled_kbd'):
            return None
        markup  = telebot.types.InlineKeyboardMarkup(row_width=5)
        button0 = telebot.types.InlineKeyboardButton("➡", callback_data='continue_gpt')
        button1 = telebot.types.InlineKeyboardButton('♻️', callback_data='gpt4o_reset')
        button2 = telebot.types.InlineKeyboardButton("🙈", callback_data='erase_answer')
        button3 = telebot.types.InlineKeyboardButton("📢", callback_data='tts')
        button4 = telebot.types.InlineKeyboardButton(lang, callback_data='translate_chat')
        markup.add(button0, button1, button2, button3, button4)
        return markup

    elif kbd == 'gemma2-9b_chat':
        if my_db.get_user_property(chat_id_full, 'disabled_kbd'):
            return None
        markup  = telebot.types.InlineKeyboardMarkup(row_width=5)
        button0 = telebot.types.InlineKeyboardButton("➡", callback_data='continue_gpt')
        button1 = telebot.types.InlineKeyboardButton('♻️', callback_data='gemma2-9b_reset')
        button2 = telebot.types.InlineKeyboardButton("🙈", callback_data='erase_answer')
        button3 = telebot.types.InlineKeyboardButton("📢", callback_data='tts')
        button4 = telebot.types.InlineKeyboardButton(lang, callback_data='translate_chat')
        markup.add(button0, button1, button2, button3, button4)
        return markup

    elif kbd == 'haiku_chat':
        if my_db.get_user_property(chat_id_full, 'disabled_kbd'):
            return None
        markup  = telebot.types.InlineKeyboardMarkup(row_width=5)
        button0 = telebot.types.InlineKeyboardButton("➡", callback_data='continue_gpt')
        button1 = telebot.types.InlineKeyboardButton('♻️', callback_data='haiku_reset')
        button2 = telebot.types.InlineKeyboardButton("🙈", callback_data='erase_answer')
        button3 = telebot.types.InlineKeyboardButton("📢", callback_data='tts')
        button4 = telebot.types.InlineKeyboardButton(lang, callback_data='translate_chat')
        markup.add(button0, button1, button2, button3, button4)
        return markup


    elif kbd == 'gpt-4o-mini-ddg_chat':
        if my_db.get_user_property(chat_id_full, 'disabled_kbd'):
            return None
        markup  = telebot.types.InlineKeyboardMarkup(row_width=5)
        button0 = telebot.types.InlineKeyboardButton("➡", callback_data='continue_gpt')
        button1 = telebot.types.InlineKeyboardButton('♻️', callback_data='gpt-4o-mini-ddg_reset')
        button2 = telebot.types.InlineKeyboardButton("🙈", callback_data='erase_answer')
        button3 = telebot.types.InlineKeyboardButton("📢", callback_data='tts')
        button4 = telebot.types.InlineKeyboardButton(lang, callback_data='translate_chat')
        markup.add(button0, button1, button2, button3, button4)
        return markup

    elif kbd == 'gpt4omini_chat':
        if my_db.get_user_property(chat_id_full, 'disabled_kbd'):
            return None
        markup  = telebot.types.InlineKeyboardMarkup(row_width=5)
        button0 = telebot.types.InlineKeyboardButton("➡", callback_data='continue_gpt')
        button1 = telebot.types.InlineKeyboardButton('♻️', callback_data='gpt4omini_reset')
        button2 = telebot.types.InlineKeyboardButton("🙈", callback_data='erase_answer')
        button3 = telebot.types.InlineKeyboardButton("📢", callback_data='tts')
        button4 = telebot.types.InlineKeyboardButton(lang, callback_data='translate_chat')
        markup.add(button0, button1, button2, button3, button4)
        return markup

    elif kbd == 'groq_groq-llama370_chat':
        if my_db.get_user_property(chat_id_full, 'disabled_kbd'):
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
        if my_db.get_user_property(chat_id_full, 'disabled_kbd'):
            return None
        markup  = telebot.types.InlineKeyboardMarkup(row_width=5)
        button0 = telebot.types.InlineKeyboardButton("➡", callback_data='continue_gpt')
        button1 = telebot.types.InlineKeyboardButton('♻️', callback_data='gemini_reset')
        button2 = telebot.types.InlineKeyboardButton("🙈", callback_data='erase_answer')
        button3 = telebot.types.InlineKeyboardButton("📢", callback_data='tts')
        button4 = telebot.types.InlineKeyboardButton(lang, callback_data='translate_chat')
        markup.add(button0, button1, button2, button3, button4)
        return markup
    elif kbd.startswith('search_pics_'):
        markup  = telebot.types.InlineKeyboardMarkup(row_width=3)
        button0 = telebot.types.InlineKeyboardButton('📸', callback_data=f'search_pics_{kbd[12:]}')
        button1 = telebot.types.InlineKeyboardButton("🙈", callback_data='erase_answer')
        button2 = telebot.types.InlineKeyboardButton("📢", callback_data='tts')
        markup.add(button0, button1, button2)
        return markup
    elif kbd == 'config':
        if my_db.get_user_property(chat_id_full, 'tts_gender'):
            voice = f'tts_{my_db.get_user_property(chat_id_full, "tts_gender")}'
        else:
            voice = 'tts_female'

        voices = {'tts_female': tr('MS жен.', lang, 'это сокращенный текст на кнопке, полный текст - "Microsoft женский", тут имеется в виду женский голос для TTS от микрософта, сделай перевод таким же коротким что бы уместится на кнопке'),
                  'tts_male': tr('MS муж.', lang, 'это сокращенный текст на кнопке, полный текст - "Microsoft мужской", тут имеется в виду мужской голос для TTS от микрософта, сделай перевод таким же коротким что бы уместится на кнопке'),
                  'tts_google_female': 'Google',
                  }
        voice_title = voices[voice]

        # кто по умолчанию
        if not my_db.get_user_property(chat_id_full, 'chat_mode'):
            my_db.set_user_property(chat_id_full, 'chat_mode', cfg.chat_mode_default)

        markup  = telebot.types.InlineKeyboardMarkup(row_width=1)

        have_gemini_keys = chat_id_full in my_gemini.USER_KEYS or message.from_user.id in cfg.admins
        button1 = telebot.types.InlineKeyboardButton('Gemini 1.5 Flash', callback_data='select_gemini15_flash')
        if have_gemini_keys:
            button2 = telebot.types.InlineKeyboardButton('Gemini 1.5 Pro', callback_data='select_gemini15_pro')
        else:
            button2 = telebot.types.InlineKeyboardButton('🔒Gemini 1.5 Pro', callback_data='select_gemini15_pro')
        # button3 = telebot.types.InlineKeyboardButton('GPT-4o', callback_data='select_gpt4o')
        button3 = telebot.types.InlineKeyboardButton('Gemma 2 9b', callback_data='select_gemma2-9b')
        button4 = telebot.types.InlineKeyboardButton('Llama-3.1 70b', callback_data='select_llama370')
        button5 = telebot.types.InlineKeyboardButton('GPT 4o mini', callback_data='select_gpt-4o-mini-ddg')
        button6 = telebot.types.InlineKeyboardButton('Haiku', callback_data='select_haiku')
        markup.row(button1, button2)
        markup.row(button3, button4)
        markup.row(button5, button6)
        # if hasattr(cfg, 'GPT4OMINI_KEY'):
        #     button7 = telebot.types.InlineKeyboardButton('GPT 4o mini', callback_data='select_gpt4omini')
        #     markup.row(button7)

        button1 = telebot.types.InlineKeyboardButton(f"{tr(f'📢Голос:', lang)} {voice_title}", callback_data=voice)
        if my_db.get_user_property(chat_id_full, 'voice_only_mode'):
            button2 = telebot.types.InlineKeyboardButton(tr('✅Только голос', lang), callback_data='voice_only_mode_disable')
        else:
            button2 = telebot.types.InlineKeyboardButton(tr('☑️Только голос', lang), callback_data='voice_only_mode_enable')
        markup.row(button1, button2)

        if not my_db.get_user_property(chat_id_full, 'auto_translations'):
            my_db.set_user_property(chat_id_full, 'auto_translations', 0)

        if my_db.get_user_property(chat_id_full, 'auto_translations') == 1:
            button1 = telebot.types.InlineKeyboardButton(tr(f'✅Авто переводы', lang), callback_data='autotranslate_disable')
        else:
            button1 = telebot.types.InlineKeyboardButton(tr(f'☑️Авто переводы', lang), callback_data='autotranslate_enable')
        if my_db.get_user_property(chat_id_full, 'disabled_kbd'):
            button2 = telebot.types.InlineKeyboardButton(tr(f'☑️Чат-кнопки', lang), callback_data='disable_chat_kbd')
        else:
            button2 = telebot.types.InlineKeyboardButton(tr(f'✅Чат-кнопки', lang), callback_data='enable_chat_kbd')
        markup.row(button1, button2)

        if my_db.get_user_property(chat_id_full, 'suggest_enabled'):
            button1 = telebot.types.InlineKeyboardButton(tr(f'✅Show image suggestions', lang), callback_data='suggest_image_prompts_disable')
        else:
            button1 = telebot.types.InlineKeyboardButton(tr(f'☑️Show image suggestions', lang), callback_data='suggest_image_prompts_enable')
        markup.row(button1)

        if my_db.get_user_property(chat_id_full, 'transcribe_only'):
            button2 = telebot.types.InlineKeyboardButton(tr(f'✅Voice to text mode', lang), callback_data='transcribe_only_chat_disable')
        else:
            button2 = telebot.types.InlineKeyboardButton(tr(f'☑️Voice to text mode', lang), callback_data='transcribe_only_chat_enable')
        markup.row(button2)

        # if cfg.pics_group_url:
        #     button_pics = telebot.types.InlineKeyboardButton(tr("🖼️Галерея", lang),  url = cfg.pics_group_url)
        #     markup.add(button_pics)

        is_private = message.chat.type == 'private'
        is_admin_of_group = False
        if message.reply_to_message:
            is_admin_of_group = is_admin_member(message.reply_to_message)
            from_user = message.reply_to_message.from_user.id
        else:
            from_user = message.from_user.id
            is_admin_of_group = is_admin_member(message)

        if flag == 'admin' or is_admin_of_group or from_user in cfg.admins:
            supch = my_db.get_user_property(chat_id_full, 'superchat') or 0
            if supch == 1:
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
@async_run
def callback_inline_thread(call: telebot.types.CallbackQuery):
    """Обработчик клавиатуры"""

    with semaphore_talks:
        message = call.message
        chat_id = message.chat.id
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)
        bot_name = my_db.get_user_property(chat_id_full, 'bot_name') or BOT_NAME_DEFAULT
        MSG_CONFIG = f"""<b>{tr('Bot name:', lang)}</b> {bot_name} /name

<b>{tr('Bot style(role):', lang)}</b> {my_db.get_user_property(chat_id_full, 'role') if my_db.get_user_property(chat_id_full, 'role') else tr('No role was set.', lang)} /style

<b>{tr('User language:', lang)}</b> {tr(langcodes.Language.make(language=lang).display_name(language='en'), lang)} /lang

{tr('Disable/enable the context, the bot will not know who it is, where it is, who it is talking to, it will work as on the original website', lang, '_')}

/original_mode

"""

        if call.data == 'clear_history':
            # обработка нажатия кнопки "Стереть историю"
            reset_(chat_id_full)
            bot.delete_message(message.chat.id, message.message_id)
        elif call.data == 'continue_gpt':
            # обработка нажатия кнопки "Продолжай GPT"
            message.dont_check_topic = True
            echo_all(message, tr('Продолжай', lang))
            return
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
            supch = my_db.get_user_property(chat_id_full, 'superchat') or 0
            if supch == 1:
                supch = 0
                my_db.set_user_property(chat_id_full, 'superchat', 0)
            else:
                supch = 1
                my_db.set_user_property(chat_id_full, 'superchat', 1)
            bot.edit_message_text(chat_id=chat_id, parse_mode='HTML', message_id=message.message_id,
                                  text = MSG_CONFIG, reply_markup=get_keyboard('config', message, 'admin'))
        elif call.data == 'erase_answer':
            # обработка нажатия кнопки "Стереть ответ"
            bot.delete_message(message.chat.id, message.message_id)
        elif call.data == 'tts':
            message.text = f'/tts {lang or "de"} {message.text or message.caption or ""}'
            tts(message)
        elif call.data.startswith('imagecmd_'):
            hash = call.data[9:]
            prompt = my_db.get_from_im_suggests(hash)
            message.text = f'/image {prompt}'
            image_gen(message)
        elif call.data.startswith('imagecmd2_'):
            hash = call.data[10:]
            prompt = my_db.get_from_im_suggests(hash)
            message.text = f'/image2 {prompt}'
            image2_gen(message)
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


        elif call.data.startswith('search_pics_'):
            # Поиск картинок в дак дак гоу
            if chat_id_full not in GOOGLE_LOCKS:
                GOOGLE_LOCKS[chat_id_full] = threading.Lock()
            with GOOGLE_LOCKS[chat_id_full]:
                with ShowAction(message, 'upload_photo'):
                    hash = call.data[12:]
                    query = SEARCH_PICS[hash]
                    images = my_ddg.get_images(query)
                    medias = [telebot.types.InputMediaPhoto(x[0], caption = x[1][:900]) for x in images]
                    msgs_ids = bot.send_media_group(message.chat.id, medias, reply_to_message_id=message.message_id, disable_notification=True)
                    # for _ in range(10):
                    #     my_db.add_msg(chat_id_full, 'gemini15_flash')
                    #     time.sleep(0.01)
                    log_message(msgs_ids)


        elif call.data == 'download_saved_text':
            # отдать юзеру его текст
            if my_db.get_user_property(chat_id_full, 'saved_file_name'):
                with ShowAction(message, 'typing'):
                    buf = io.BytesIO()
                    buf.write(my_db.get_user_property(chat_id_full, 'saved_file').encode())
                    buf.seek(0)
                    fname = utils.safe_fname(my_db.get_user_property(chat_id_full, 'saved_file_name')) + '.txt'
                    if fname.endswith('.txt.txt'):
                        fname = fname[:-4]
                    m = bot.send_document(message.chat.id,
                                          document=buf,
                                          message_thread_id=message.message_thread_id,
                                          caption=fname,
                                          visible_file_name = fname)
                    log_message(m)
            else:
                bot_reply_tr(message, 'No text was saved.')


        elif call.data == 'delete_saved_text':
            # удалить сохраненный текст
            if my_db.get_user_property(chat_id_full, 'saved_file_name'):
                my_db.delete_user_property(chat_id_full, 'saved_file_name')
                my_db.delete_user_property(chat_id_full, 'saved_file')
                bot_reply_tr(message, 'Saved text deleted.')
            else:
                bot_reply_tr(message, 'No text was saved.')


        elif call.data == 'translate_chat':
            # реакция на клавиатуру для Чата кнопка перевести текст
            with ShowAction(message, 'typing'):
                translated = my_trans.translate_text2(message.text, lang)
            if translated and translated != message.text:
                bot.edit_message_text(chat_id=message.chat.id, message_id=message.message_id, text=translated, 
                                      reply_markup=get_keyboard('chat', message))
        elif call.data == 'select_gpt4o':
            bot.answer_callback_query(callback_query_id=call.id, show_alert=False, text=tr('Выбрана модель GPT-4o.', lang))
            my_db.set_user_property(chat_id_full, 'chat_mode', 'gpt4o')
        elif call.data == 'select_llama370':
            bot.answer_callback_query(callback_query_id=call.id, show_alert=False, text=tr('Выбрана модель Llama-3.1 70b Groq.', lang))
            my_db.set_user_property(chat_id_full, 'chat_mode', 'llama370')
        elif call.data == 'select_gemma2-9b':
            bot.answer_callback_query(callback_query_id=call.id, show_alert=False, text=tr('Выбрана модель Google Gemma 2 9b.', lang))
            my_db.set_user_property(chat_id_full, 'chat_mode', 'gemma2-9b')
        elif call.data == 'select_haiku':
            bot.answer_callback_query(callback_query_id=call.id, show_alert=False, text=tr('Выбрана модель Claude 3 Haiku from DuckDuckGo.', lang))
            my_db.set_user_property(chat_id_full, 'chat_mode', 'haiku')
        elif call.data == 'select_gpt-4o-mini-ddg':
            bot.answer_callback_query(callback_query_id=call.id, show_alert=False, text=tr('Выбрана модель GPT 4o mini from DuckDuckGo.', lang))
            my_db.set_user_property(chat_id_full, 'chat_mode', 'gpt-4o-mini-ddg')
        elif call.data == 'select_gpt4omini':
            bot.answer_callback_query(callback_query_id=call.id, show_alert=False, text=tr('Выбрана модель GPT 4o mini.', lang))
            my_db.set_user_property(chat_id_full, 'chat_mode', 'gpt4omini')
        elif call.data == 'select_gemini15_flash':
            bot.answer_callback_query(callback_query_id=call.id, show_alert=False, text=tr('Выбрана модель Google Gemini 1.5 Flash.', lang))
            my_db.set_user_property(chat_id_full, 'chat_mode', 'gemini')
        elif call.data == 'select_gemini15_pro':
            have_keys = chat_id_full in my_gemini.USER_KEYS or chat_id_full in my_groq.USER_KEYS or\
                chat_id_full in my_trans.USER_KEYS or chat_id_full in my_genimg.USER_KEYS\
                    or message.from_user.id in cfg.admins
            if have_keys:
                bot.answer_callback_query(callback_query_id=call.id, show_alert=False, text=tr('Выбрана модель Google Gemini 1.5 Pro.', lang))
                my_db.set_user_property(chat_id_full, 'chat_mode', 'gemini15')
            else:
                bot.answer_callback_query(callback_query_id=call.id, show_alert=True, text=tr('Надо вставить свои ключи что бы использовать Google Gemini 1.5 Pro. Команда /keys', lang))
        elif call.data == 'groq-llama370_reset':
            my_groq.reset(chat_id_full)
            bot_reply_tr(message, 'История диалога с Groq llama 3.1 70b очищена.')
            # bot.answer_callback_query(callback_query_id=call.id, show_alert=True, text=tr('История диалога с Groq llama 3.1 70b очищена.', lang))
        elif call.data == 'gemma2-9b_reset':
            my_groq.reset(chat_id_full)
            bot_reply_tr(message, 'История диалога с Gemma 2 9b очищена.')
        elif call.data == 'openrouter_reset':
            my_openrouter.reset(chat_id_full)
            bot_reply_tr(message, 'История диалога с openrouter очищена.')
        elif call.data == 'gpt4o_reset':
            my_shadowjourney.reset(chat_id_full)
            bot_reply_tr(message, 'История диалога с GPT-4o очищена.')
        elif call.data == 'gpt-4o-mini-ddg_reset':
            my_ddg.reset(chat_id_full)
            bot_reply_tr(message, 'История диалога с GPT 4o mini очищена.')
        elif call.data == 'gpt4omini_reset':
            my_gpt4omini.reset(chat_id_full)
            bot_reply_tr(message, 'История диалога с GPT 4o mini очищена.')
        elif call.data == 'haiku_reset':
            my_ddg.reset(chat_id_full)
            bot_reply_tr(message, 'История диалога с haiku очищена.')
        elif call.data == 'gemini_reset':
            my_gemini.reset(chat_id_full)
            bot_reply_tr(message, 'История диалога с Gemini очищена.')
        elif call.data == 'tts_female' and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'tts_gender', 'male')
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                  text = MSG_CONFIG, reply_markup=get_keyboard('config', message))
        elif call.data == 'tts_male' and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'tts_gender', 'google_female')
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                  text = MSG_CONFIG, reply_markup=get_keyboard('config', message))
        elif call.data == 'tts_google_female' and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'tts_gender', 'female')
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                  text = MSG_CONFIG, reply_markup=get_keyboard('config', message))
        elif call.data == 'voice_only_mode_disable' and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'voice_only_mode', False)
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                  text = MSG_CONFIG, reply_markup=get_keyboard('config', message))
        elif call.data == 'suggest_image_prompts_enable'  and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'suggest_enabled', True)
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                  text = MSG_CONFIG, reply_markup=get_keyboard('config', message))
        elif call.data == 'suggest_image_prompts_disable' and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'suggest_enabled', False)
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                  text = MSG_CONFIG, reply_markup=get_keyboard('config', message))
        elif call.data == 'voice_only_mode_enable'  and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'voice_only_mode', True)
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                  text = MSG_CONFIG, reply_markup=get_keyboard('config', message))
        elif call.data == 'transcribe_only_chat_disable' and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'transcribe_only', False)
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                  text = MSG_CONFIG, reply_markup=get_keyboard('config', message))
        elif call.data == 'transcribe_only_chat_enable'  and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'transcribe_only', True)
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                  text = MSG_CONFIG, reply_markup=get_keyboard('config', message))
        elif call.data == 'autotranslate_disable' and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'auto_translations', 0)
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                  text = MSG_CONFIG, reply_markup=get_keyboard('config', message))
        elif call.data == 'autotranslate_enable' and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'auto_translations', 1)
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                  text = MSG_CONFIG, reply_markup=get_keyboard('config', message))
        elif call.data == 'disable_chat_kbd' and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'disabled_kbd', False)
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                  text = MSG_CONFIG, reply_markup=get_keyboard('config', message))
        elif call.data == 'enable_chat_kbd' and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'disabled_kbd', True)
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                  text = MSG_CONFIG, reply_markup=get_keyboard('config', message))


@bot.message_handler(content_types = ['voice', 'video', 'video_note', 'audio'], func=authorized)
@async_run
def handle_voice(message: telebot.types.Message):
    """Автоматическое распознавание текст из голосовых сообщений и аудио файлов"""
    is_private = message.chat.type == 'private'
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    supch = my_db.get_user_property(chat_id_full, 'superchat') or 0
    if supch == 1:
        is_private = True

    if check_blocks(get_topic_id(message)) and not is_private:
        return

    if chat_id_full in VOICE_LOCKS:
        lock = VOICE_LOCKS[chat_id_full]
    else:
        lock = threading.Lock()
        VOICE_LOCKS[chat_id_full] = lock

    with lock:
        with semaphore_talks:
            # Скачиваем аудиофайл во временный файл
            try:
                if message.voice:
                    file_info = bot.get_file(message.voice.file_id)
                elif message.audio:
                    file_info = bot.get_file(message.audio.file_id)
                elif message.video:
                    file_info = bot.get_file(message.video.file_id)
                elif message.video_note:
                    file_info = bot.get_file(message.video_note.file_id)
                elif message.document:
                    file_info = bot.get_file(message.document.file_id)
                else:
                    bot_reply_tr(message, 'Unknown message type')
            except telebot.apihelper.ApiTelegramException as error:
                if 'file is too big' in str(error):
                    bot_reply_tr(message, 'Too big file.')
                    return
                else:
                    raise error

            # Создание временного файла
            with tempfile.NamedTemporaryFile(delete=True) as temp_file:
                file_path = temp_file.name + (utils.get_file_ext(file_info.file_path) or 'unknown')

            downloaded_file = bot.download_file(file_info.file_path)
            with open(file_path, 'wb') as new_file:
                new_file.write(downloaded_file)

            # Распознаем текст из аудио
            if my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                action = 'record_audio'
            else:
                action = 'typing'
            with ShowAction(message, action):

                try:
                    prompt = tr('Распознай аудиозапись и исправь ошибки.', lang)
                    text = my_stt.stt(file_path, lang, chat_id_full, prompt)
                except Exception as error_stt:
                    my_log.log2(f'tb:handle_voice: {error_stt}')
                    text = ''

                utils.remove_file(file_path)

                text = text.strip()
                # Отправляем распознанный текст
                if text:
                    if my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                        # в этом режиме не показываем распознанный текст а просто отвечаем на него голосом
                        pass
                    else:
                        bot_reply(message, utils.bot_markdown_to_html(text),
                                parse_mode='HTML',
                                reply_markup=get_keyboard('translate', message))
                else:
                    if my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                        message.text = f'/tts {lang or "de"} ' + tr('Не удалось распознать текст', lang)
                        tts(message)
                    else:
                        bot_reply_tr(message, 'Не удалось распознать текст')

                # и при любом раскладе отправляем текст в обработчик текстовых сообщений, возможно бот отреагирует на него если там есть кодовые слова
                if text:
                    if not my_db.get_user_property(chat_id_full, 'transcribe_only'):
                        # message.text = f'voice message: {text}'
                        message.text = text
                        echo_all(message)


@bot.message_handler(content_types = ['document'], func=authorized)
@async_run
def handle_document(message: telebot.types.Message):
    """Обработчик документов"""
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    COMMAND_MODE[chat_id_full] = ''

    is_private = message.chat.type == 'private'
    supch = my_db.get_user_property(chat_id_full, 'superchat') or 0
    if supch == 1:
        is_private = True

    chat_id = message.chat.id

    if check_blocks(chat_id_full) and not is_private:
        return

    if chat_id_full in DOCUMENT_LOCKS:
        lock = DOCUMENT_LOCKS[chat_id_full]
    else:
        lock = threading.Lock()
        DOCUMENT_LOCKS[chat_id_full] = lock

    pandoc_support = ('application/vnd.ms-excel',
        'application/vnd.oasis.opendocument.spreadsheet',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/octet-stream',
        'application/epub+zip',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'application/rtf',
        'application/msword',
        'application/x-msexcel',
        'application/x-fictionbook+xml',
    )
    simple_text = ('application/x-bat',
                   'application/xml',
                   'application/javascript',
                   'application/json',
                   'application/x-sh',
                   'application/xhtml+xml',
                   'application/atom+xml',
                   'application/x-subrip',
                   )

    with lock:
        with semaphore_talks:
            # если прислали текстовый файл или pdf
            # то скачиваем и вытаскиваем из них текст и показываем краткое содержание
            if is_private and \
                (message.document.mime_type in ('application/pdf',
                                                'image/svg+xml',
                                                )+pandoc_support+simple_text or \
                                                message.document.mime_type.startswith('text/') or \
                                                message.document.mime_type.startswith('video/') or \
                                                message.document.mime_type.startswith('audio/')):
                if message.document and message.document.mime_type.startswith('audio/') or \
                    message.document and message.document.mime_type.startswith('video/'):
                    handle_voice(message)
                    return
                with ShowAction(message, 'typing'):
                    try:
                        file_info = bot.get_file(message.document.file_id)
                    except telebot.apihelper.ApiTelegramException as error:
                        if 'file is too big' in str(error):
                            bot_reply_tr(message, 'Too big file')
                            return
                        else:
                            raise error
                    downloaded_file = bot.download_file(file_info.file_path)
                    file_bytes = io.BytesIO(downloaded_file)
                    text = ''
                    if message.document.mime_type == 'application/pdf':
                        pdf_reader = PyPDF2.PdfReader(file_bytes)
                        for page in pdf_reader.pages:
                            text += page.extract_text()
                        if not text.strip() or len(text) < 100:
                            text = my_ocr.get_text_from_pdf(file_bytes, get_ocr_language(message))
                    elif message.document.mime_type in pandoc_support:
                        ext = utils.get_file_ext(file_info.file_path)
                        text = my_pandoc.fb2_to_text(file_bytes.read(), ext)
                    elif message.document.mime_type == 'image/svg+xml':
                        try:
                            image = cairosvg.svg2png(file_bytes.read(), output_width=2048)
                            #send converted image back
                            bot.send_photo(message.chat.id,
                                        image,
                                        reply_to_message_id=message.message_id,
                                        message_thread_id=message.message_thread_id,
                                        caption=message.document.file_name + '.png',
                                        reply_markup=get_keyboard('translate', message),
                                        disable_notification=True)
                            text = img2txt(image, lang, chat_id_full, message.caption)
                            # my_db.add_msg(chat_id_full, 'gemini15_flash')
                            if text:
                                text = utils.bot_markdown_to_html(text)
                                text += '\n\n' + tr("<b>Every time you ask a new question about the picture, you have to send the picture again.</b>", lang)
                                bot_reply(message, text, parse_mode='HTML',
                                                    reply_markup=get_keyboard('translate', message))
                            else:
                                bot_reply_tr(message, 'Sorry, I could not answer your question.')
                            return
                        except Exception as error:
                            my_log.log2(f'tb:handle_document:svg: {error}')
                            bot_reply_tr(message, 'Не удалось распознать изображение')
                            return
                    elif message.document.mime_type.startswith('text/') or \
                        message.document.mime_type in simple_text:
                        data__ = file_bytes.read()
                        text = ''
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
                    if text.strip():
                        caption = message.caption or ''
                        caption = caption.strip()
                        summary = my_sum.summ_text(text, 'text', lang, caption)
                        my_db.set_user_property(chat_id_full, 'saved_file_name', message.document.file_name if hasattr(message, 'document') else 'noname.txt')
                        my_db.set_user_property(chat_id_full, 'saved_file', text)
                        summary_html = utils.bot_markdown_to_html(summary)
                        bot_reply(message, summary_html, parse_mode='HTML',
                                            disable_web_page_preview = True,
                                            reply_markup=get_keyboard('translate', message))
                        bot_reply_tr(message, 'Use /ask command to query this file. Example /ask generate a short version of part 1.')

                        caption_ = tr("юзер попросил ответить по содержанию файла", lang)
                        if caption:
                            caption_ += ', ' + caption
                        add_to_bots_mem(caption_,
                                            f'{tr("бот посмотрел файл и ответил:", lang)} {summary}',
                                            chat_id_full)
                    else:
                        bot_reply_tr(message, 'Не удалось получить никакого текста из документа.')
                    return

            # дальше идет попытка распознать ПДФ или jpg файл, вытащить текст с изображений
            if is_private or caption.lower().startswith('ocr'):
                with ShowAction(message, 'upload_document'):
                    # получаем самый большой документ из списка
                    document = message.document
                    # если документ не является PDF-файлом или изображением jpg png, отправляем сообщение об ошибке
                    if document.mime_type.startswith('image/'):
                        handle_photo(message)
                        return
                    if document.mime_type != 'application/pdf':
                        bot_reply(message, f'{tr("Unsupported file type.", lang)} {document.mime_type}')
                        return
                    # скачиваем документ в байтовый поток
                    file_id = message.document.file_id
                    try:
                        file_info = bot.get_file(file_id)
                    except telebot.apihelper.ApiTelegramException as error:
                        if 'file is too big' in str(error):
                            bot_reply_tr(message, 'Too big file.')
                            return
                        else:
                            raise error
                    file_name = message.document.file_name + '.txt'
                    file = bot.download_file(file_info.file_path)
                    # распознаем текст в документе с помощью функции get_text
                    text = my_ocr.get_text_from_pdf(file, get_ocr_language(message))
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


def download_image_from_message(message: telebot.types.Message) -> bytes:
    '''Download image from message'''
    try:
        if message.photo:
            photo = message.photo[-1]
            try:
                file_info = bot.get_file(photo.file_id)
            except telebot.apihelper.ApiTelegramException as error:
                if 'file is too big' in str(error):
                    bot_reply_tr(message, 'Too big file.')
                    return
                else:
                    raise error
            image = bot.download_file(file_info.file_path)
        elif message.document:
            file_id = message.document.file_id
            try:
                file_info = bot.get_file(file_id)
            except telebot.apihelper.ApiTelegramException as error:
                if 'file is too big' in str(error):
                    bot_reply_tr(message, 'Too big file.')
                    return
                else:
                    raise error
            file = bot.download_file(file_info.file_path)
            fp = io.BytesIO(file)
            image = fp.read()
        return image
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:download_image_from_message: {error} {traceback_error}')
        return b''


def download_image_from_messages(MESSAGES: list) -> list:
    '''Download images from message list'''
    images = []

    with concurrent.futures.ThreadPoolExecutor() as executor:
        results = [executor.submit(download_image_from_message, message) for message in MESSAGES]
        for f in concurrent.futures.as_completed(results):
            images.append(f.result())

    return images


@bot.message_handler(content_types = ['photo'], func=authorized)
@async_run
def handle_photo(message: telebot.types.Message):
    """Обработчик фотографий. Сюда же попадают новости которые создаются как фотография
    + много текста в подписи, и пересланные сообщения в том числе"""

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)



    # catch groups of images up to 10
    if chat_id_full not in MESSAGE_QUEUE_IMG:
        MESSAGE_QUEUE_IMG[chat_id_full] = [message,]
        last_state = MESSAGE_QUEUE_IMG[chat_id_full]
        n = 10
        while n > 0:
            n -= 1
            time.sleep(0.1)
            new_state = MESSAGE_QUEUE_IMG[chat_id_full]
            if last_state != new_state:
                last_state = new_state
                n = 10
    else:
        MESSAGE_QUEUE_IMG[chat_id_full].append(message)
        return


    if len(MESSAGE_QUEUE_IMG[chat_id_full]) > 1:
        MESSAGES = MESSAGE_QUEUE_IMG[chat_id_full]
    else:
        MESSAGES = [message,]
    del MESSAGE_QUEUE_IMG[chat_id_full]


    try:
        is_private = message.chat.type == 'private'
        supch = my_db.get_user_property(chat_id_full, 'superchat') or 0
        if supch == 1:
            is_private = True

        msglower = message.caption.lower() if message.caption else ''

        # if (tr('что', lang) in msglower and len(msglower) < 30) or msglower == '':
        if msglower.startswith('?'):
            state = 'describe'
            message.caption = message.caption[1:]

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


        if is_private:
            # Если прислали медиагруппу то делаем из нее коллаж, и обрабатываем как одну картинку
            if len(MESSAGES) > 1:
                with ShowAction(message, 'typing'):
                    images = [download_image_from_message(msg) for msg in MESSAGES]
                    result_image_as_bytes = utils.make_collage(images)
                    m = bot.send_photo(message.chat.id,
                                    result_image_as_bytes,
                                    disable_notification=True,
                                    reply_to_message_id=message.message_id,
                                    reply_markup=get_keyboard('hide', message))
                    log_message(m)
                    my_log.log_echo(message, f'Made collage of {len(images)} images.')
                    text = img2txt(result_image_as_bytes, lang, chat_id_full, message.caption)
                    if text:
                        text = utils.bot_markdown_to_html(text)
                        text += '\n\n' + tr("<b>Every time you ask a new question about the picture, you have to send the picture again.</b>", lang)
                        bot_reply(message, text, parse_mode='HTML',
                                            reply_markup=get_keyboard('translate', message),
                                            disable_web_page_preview=True)
                    else:
                        bot_reply_tr(message, 'Sorry, I could not answer your question.')
                    return


        if chat_id_full in IMG_LOCKS:
            lock = IMG_LOCKS[chat_id_full]
        else:
            lock = threading.Lock()
            IMG_LOCKS[chat_id_full] = lock


        with lock:
            with semaphore_talks:
                # распознаем что на картинке с помощью гугл джемини
                if state == 'describe':
                    with ShowAction(message, 'typing'):
                        image = download_image_from_message(message)
                        if not image:
                            my_log.log2(f'tb:handle_photo: не удалось распознать документ или фото {str(message)}')
                            return

                        text = img2txt(image, lang, chat_id_full, message.caption)
                        # my_db.add_msg(chat_id_full, 'gemini15_flash')
                        if text:
                            text = utils.bot_markdown_to_html(text)
                            text += '\n\n' + tr("<b>Every time you ask a new question about the picture, you have to send the picture again.</b>", lang)
                            bot_reply(message, text, parse_mode='HTML',
                                                reply_markup=get_keyboard('translate', message),
                                                disable_web_page_preview=True)
                        else:
                            bot_reply_tr(message, 'Sorry, I could not answer your question.')
                    return
                elif state == 'ocr':
                    with ShowAction(message, 'typing'):
                        if message.photo:
                            photo = message.photo[-1]
                            try:
                                file_info = bot.get_file(photo.file_id)
                            except telebot.apihelper.ApiTelegramException as error:
                                if 'file is too big' in str(error):
                                    bot_reply_tr(message, 'Too big file.')
                                    return
                                else:
                                    raise error
                            image = bot.download_file(file_info.file_path)
                        elif message.document:
                            # скачиваем документ в байтовый поток
                            file_id = message.document.file_id
                            try:
                                file_info = bot.get_file(file_id)
                            except telebot.apihelper.ApiTelegramException as error:
                                if 'file is too big' in str(error):
                                    bot_reply_tr(message, 'Too big file.')
                                    return
                                else:
                                    raise error
                            file = bot.download_file(file_info.file_path)
                            fp = io.BytesIO(file)
                            image = fp.read()
                        else:
                            my_log.log2(f'tb:handle_photo: не удалось распознать документ или фото {str(message)}')
                            return

                        # распознаем текст на фотографии с помощью pytesseract
                        llang = get_ocr_language(message)
                        if message.caption.strip()[3:]:
                            llang = message.caption.strip()[3:].strip()
                        text = my_ocr.get_text_from_image(image, llang)
                        # отправляем распознанный текст пользователю
                        if text.strip() != '':
                            bot_reply(message, text, parse_mode='',
                                                reply_markup=get_keyboard('translate', message),
                                                disable_web_page_preview = True)

                            text = text[:8000]
                            add_to_bots_mem(f'{tr("юзер попросил распознать текст с картинки", lang)}',
                                                f'{tr("бот распознал текст и ответил:", lang)} {text}',
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
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:handle_photo: {error}\n{traceback_error}')


@bot.message_handler(commands=['config', 'settings', 'setting', 'options'], func=authorized_owner)
@async_run
def config(message: telebot.types.Message):
    """Меню настроек"""
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    COMMAND_MODE[chat_id_full] = ''
    try:
        bot_name = my_db.get_user_property(chat_id_full, 'bot_name') or BOT_NAME_DEFAULT
        MSG_CONFIG = f"""<b>{tr('Bot name:', lang)}</b> {bot_name} /name

<b>{tr('Bot style(role):', lang)}</b> {my_db.get_user_property(chat_id_full, 'role') if my_db.get_user_property(chat_id_full, 'role') else tr('No role was set.', lang)} /style

<b>{tr('User language:', lang)}</b> {tr(langcodes.Language.make(language=lang).display_name(language='en'), lang)} /lang

{tr('Disable/enable the context, the bot will not know who it is, where it is, who it is talking to, it will work as on the original website', lang, '_')}

/original_mode

"""
        bot_reply(message, MSG_CONFIG, parse_mode='HTML', reply_markup=get_keyboard('config', message))
    except Exception as error:
        my_log.log2(f'tb:config:{error}')
        print(error)


@bot.message_handler(commands=['original_mode'], func=authorized_owner)
@async_run
def original_mode(message: telebot.types.Message):
    """
    Handles the 'original_mode' command for authorized owners. 
    Toggles the original mode for the chat based on the current state.
    """
    chat_id_full = get_topic_id(message)
    COMMAND_MODE[chat_id_full] = ''
    omode = my_db.get_user_property(chat_id_full, 'original_mode') or False

    if omode:
        my_db.set_user_property(chat_id_full, 'original_mode', False)
        bot_reply_tr(message, 'Original mode disabled. Bot will be informed about place, names, roles etc.')
    else:
        my_db.set_user_property(chat_id_full, 'original_mode', True)
        bot_reply_tr(message, 'Original mode enabled. Bot will not be informed about place, names, roles etc. It will work same as original chatbot.')


@bot.message_handler(commands=['model',], func=authorized_owner)
@async_run
def model(message: telebot.types.Message):
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
    except IndexError:
        pass
    except Exception as error:
        error_tr = traceback.format_exc()
        my_log.log2(f'tb:model:{error}\n\n{error_tr}')
    bot_reply_tr(message, f'Usage: /model model_name see models at https://openrouter.ai/docs#models', disable_web_page_preview=True)


@bot.message_handler(commands=['maxhistlines',], func=authorized_owner)
@async_run
def maxhistlines(message: telebot.types.Message):
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
    except IndexError:
        pass
    except Exception as error:
        error_tr = traceback.format_exc()
        my_log.log2(f'tb:model:{error}\n\n{error_tr}')
    bot_reply_tr(message, f'Usage: /maxhistlines maxhistlines 2-100', disable_web_page_preview=True)


@bot.message_handler(commands=['maxhistchars',], func=authorized_owner)
@async_run
def maxhistchars(message: telebot.types.Message):
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
    except IndexError:
        pass
    except Exception as error:
        error_tr = traceback.format_exc()
        my_log.log2(f'tb:model:{error}\n\n{error_tr}')
    bot_reply_tr(message, f'Usage: /maxhistchars maxhistchars 2000-1000000', disable_web_page_preview=True)


@bot.message_handler(commands=['maxtokens',], func=authorized_owner)
@async_run
def maxtokens(message: telebot.types.Message):
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
    except IndexError:
        pass
    except Exception as error:
        error_tr = traceback.format_exc()
        my_log.log2(f'tb:model:{error}\n\n{error_tr}')
    bot_reply_tr(message, f'Usage: /maxtokens maxtokens 10-8000', disable_web_page_preview=True)


@bot.message_handler(commands=['openrouter',], func=authorized_owner)
@async_run
def openrouter(message: telebot.types.Message):
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
                my_db.set_user_property(chat_id_full, 'chat_mode', 'openrouter')
                return
        else:
            msg = tr('You can use your own key from https://openrouter.ai/keys to access all AI supported.', lang)
            if chat_id_full in my_openrouter.KEYS and my_openrouter.KEYS[chat_id_full]:
                key = my_openrouter.KEYS[chat_id_full]
            if key:
                my_db.set_user_property(chat_id_full, 'chat_mode', 'openrouter')
                msg = f'{tr("Your key:", lang)} [{key[:12]}...]'
            model, temperature, max_tokens, maxhistlines, maxhistchars = my_openrouter.PARAMS[chat_id_full]
            msg += '\n\n'+ tr('Current settings: ', lang) + f'\n[model {model}]\n[temp {temperature}]\n[max tokens {max_tokens}]\n[maxhistlines {maxhistlines}]\n[maxhistchars {maxhistchars}]'
            msg += '\n\n' + tr('''/model <model> see available models at https://openrouter.ai/docs#models
/temp <temperature> - 0.1 ... 2.0
/maxtokens <max_tokens> - maximum response size, see model details
/maxhistlines <maxhistlines> - how many lines in history
/maxhistchars <maxhistchars> - how many chars in history

Usage: /openrouter <api key>
''', lang)
            bot_reply(message, msg, disable_web_page_preview=True)
    except Exception as error:
        error_tr = traceback.format_exc()
        my_log.log2(f'tb:openrouter:{error}\n\n{error_tr}')


@bot.message_handler(commands=['tgui'], func=authorized_admin)
@async_run
def translation_gui(message: telebot.types.Message):
    """Исправление перевода сообщений от бота"""

    # Usage: /tgui кусок текста который надо найти, это кривой перевод|||новый перевод, если не задан то будет автоперевод

    # тут перевод указан вручную
    # /tgui клавиши Близнецы добавлены|||ключи для Gemini добавлены

    # а тут будет автоперевод с помощью ии
    # /tgui клавиши Близнецы добавлены

    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)
        COMMAND_MODE[chat_id_full] = ''

        translated_counter = 0
        # первый аргумент - кривой перевод который надо найти и исправить
        text = message.text.split(maxsplit=1)
        if len(text) > 1:
            with ShowAction(message, 'find_location'):
                text = text[1].strip()
                if '|||' in text:
                    text, new_translation = text.split('|||', maxsplit=1)
                else:
                    new_translation = ''
                help = 'its a gui message in telegram bot, keep it same format and average size to fit gui'
                for key in my_db.get_translations_like(text):
                    original = key[0]
                    lang = key[1]
                    help = key[2]
                    # translated = key[3]

                    if not new_translation:
                        new_translation = my_gemini.translate(original, to_lang = lang, help = help)
                        # my_db.add_msg(chat_id_full, 'gemini15_flash')
                    if not new_translation:
                        new_translation = my_groq.translate(original, to_lang = lang, help = help)
                        my_db.add_msg(chat_id_full, 'llama3-70b-8192')
                    if new_translation:
                        my_db.update_translation(original, lang, help, new_translation)

                        cache_key = (original, lang, help)
                        cache_key_hash = hashlib.md5(str(cache_key).encode()).hexdigest()
                        TRANS_CACHE.set(cache_key_hash, new_translation)

                        translated_counter += 1
                        bot_reply(message, f'New translation:\n\n{new_translation}', disable_web_page_preview=True)
                    else:
                        bot_reply(message, 'Failed to translate')
        bot_reply(message, 'Finished, language db size: ' + str(my_db.get_translations_count()) + ', translated: ' + str(translated_counter))
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:tgui:{error}\n\n{traceback_error}')


@bot.message_handler(commands=['keys', 'key', 'Keys', 'Key'], func=authorized_owner)
@async_run
def users_keys_for_gemini(message: telebot.types.Message):
    """Юзеры могут добавить свои бесплатные ключи для джемини в общий котёл"""
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    COMMAND_MODE[chat_id_full] = ''
    is_private = message.chat.type == 'private'

    try:
        args = message.text.split(maxsplit=1)
        if len(args) > 1:

            keys = [x.strip() for x in args[1].split() if len(x.strip()) == 39]
            already_exists = any(key in my_gemini.ALL_KEYS for key in keys)
            if already_exists:
                msg = f'{tr("This key has already been added by someone earlier.", lang)} {keys}'
                bot_reply(message, msg)
            keys = [x for x in keys if x not in my_gemini.ALL_KEYS and x.startswith('AIza')]

            # groq keys len=56, starts with "gsk_"
            keys_groq = [x.strip() for x in args[1].split() if len(x.strip()) == 56]
            if keys_groq and keys_groq[0] in my_groq.ALL_KEYS:
                bot_reply_tr(message, 'Groq API key already exists!')
            keys_groq = [x for x in keys_groq if x not in my_groq.ALL_KEYS and x.startswith('gsk_')]

            #deepl keys len=39, endwith ":fx"
            deepl_keys = [x.strip() for x in args[1].split() if len(x.strip()) == 39]
            if deepl_keys and deepl_keys[0] in my_trans.ALL_KEYS:
                bot_reply_tr(message, 'Deepl API key already exists!')
            deepl_keys = [x for x in deepl_keys if x not in my_trans.ALL_KEYS and x.endswith(':fx')]

            # huggingface keys len=37, starts with "hf_"
            huggingface_keys = [x.strip() for x in args[1].split() if len(x.strip()) == 37]
            if huggingface_keys and huggingface_keys[0] in my_genimg.ALL_KEYS:
                bot_reply_tr(message, 'Huggingface API key already exists!')
            huggingface_keys = [x for x in huggingface_keys if x not in my_genimg.ALL_KEYS and x.startswith('hf_')]

            if huggingface_keys:
                if my_genimg.test_hkey(huggingface_keys[0]):
                    my_genimg.USER_KEYS[chat_id_full] = huggingface_keys[0]
                    my_log.log_keys(f'Added new API key for Huggingface: {chat_id_full} {huggingface_keys}')
                    bot_reply_tr(message, 'Added API key for Huggingface successfully!')
                else:
                    msg = tr('API key for Huggingface failed, check if it has permissions.', lang) + ' (Inference)'
                    bot_reply(message, msg)

            if keys_groq:
                my_groq.USER_KEYS[chat_id_full] = keys_groq[0]
                my_log.log_keys(f'Added new API key for Groq: {chat_id_full} {keys_groq}')
                bot_reply_tr(message, 'Added API key for Groq successfully!')

            if deepl_keys:
                my_trans.USER_KEYS[chat_id_full] = deepl_keys[0]
                my_log.log_keys(f'Added new API key for Deepl: {chat_id_full} {deepl_keys}')
                bot_reply_tr(message, 'Added API key for Deepl successfully!')

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
                                my_log.log_keys(f'Added new api key for Gemini: {key}')
                                my_db.set_user_property(chat_id_full, 'chat_mode', 'gemini15')
                                msg = tr('Added new API key for Gemini:', lang) + f' {key}'
                                bot_reply(message, msg)
                            else:
                                my_log.log_keys(f'Failed to add new API key for Gemini: {key}')
                                msg = tr('Failed to add new API key for Gemini:', lang) + f' {key}'
                                bot_reply(message, msg)
                if added_flag:
                    my_gemini.USER_KEYS[chat_id_full] = new_keys
                    bot_reply_tr(message, 'Added keys successfully!')
                    return

        msg = tr('Usage: /keys API KEYS space separated (gemini, groq, deepl, huggingface)\n\nThis bot needs free API keys. Get it at https://ai.google.dev/ \n\nHowto video:', lang) + ' https://www.youtube.com/watch?v=6aj5a7qGcb4\n\nFree VPN: https://www.vpnjantit.com/\n\nhttps://console.groq.com/keys\n\nhttps://huggingface.co/settings/tokens\n\nhttps://www.deepl.com'
        bot_reply(message, msg, disable_web_page_preview = True)

        if message.from_user.id in cfg.admins and is_private:
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
        if is_private:
            if chat_id_full in my_gemini.USER_KEYS:
                qroq_keys = [my_groq.USER_KEYS[chat_id_full],] if chat_id_full in my_groq.USER_KEYS else []
                deepl_keys = [my_trans.USER_KEYS[chat_id_full],] if chat_id_full in my_trans.USER_KEYS else []
                huggingface_keys = [my_genimg.USER_KEYS[chat_id_full],] if chat_id_full in my_genimg.USER_KEYS else []
                keys = my_gemini.USER_KEYS[chat_id_full] + qroq_keys + deepl_keys + huggingface_keys
                msg = tr('Your keys:', lang) + '\n\n'
                for key in keys:
                    msg += f'<tg-spoiler>{key}</tg-spoiler>\n\n'
                bot_reply(message, msg, parse_mode='HTML')
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'Error in /keys: {error}\n\n{message.text}\n\n{traceback_error}')


@bot.message_handler(commands=['addkey', 'addkeys'], func=authorized_admin)
@async_run
def addkeys(message: telebot.types.Message):
    try:
        args = message.text.split(maxsplit=2)
        uid = int(args[1].strip())
        uid = f'[{uid}] [0]'
        key = args[2].strip()
        bot_reply(message, f'{uid} {key}')
        if key not in my_gemini.ALL_KEYS:
            my_gemini.ALL_KEYS.append(key)
            my_gemini.USER_KEYS[uid] = [key,]
            bot_reply_tr(message, 'Added keys successfully!')
        else:
            for uid_ in [x for x in my_gemini.USER_KEYS.keys()]:
                if uid_ in my_gemini.USER_KEYS:
                    if my_gemini.USER_KEYS[uid_] == [key,]:
                        del my_gemini.USER_KEYS[uid_]
            my_gemini.USER_KEYS[uid] = [key,]
            bot_reply_tr(message, 'Added keys successfully!')
    except Exception as error:
        bot_reply_tr(message, 'Usage: /addkeys <user_id as int> <key>')


# @bot.message_handler(commands=['removemykeys'], func=authorized_owner)
# @run_in_thread
# def remove_my_keys(message: telebot.types.Message):
#     chat_id_full = get_topic_id(message)
#     keys = my_gemini.USER_KEYS[chat_id_full]
#     del my_gemini.USER_KEYS[chat_id_full]
#     my_gemini.ALL_KEYS = [x for x in my_gemini.ALL_KEYS if x not in keys]
#     bot_reply_tr(message, 'Removed keys successfully!')


@bot.message_handler(commands=['donate'], func=authorized_owner)
@async_run
def donate(message: telebot.types.Message):
    help = f'[<a href = "https://www.donationalerts.com/r/theurs">DonationAlerts</a> 💸 <a href = "https://www.sberbank.com/ru/person/dl/jc?linkname=EiDrey1GTOGUc3j0u">SBER</a> 💸 <a href = "https://qiwi.com/n/KUN1SUN">QIWI</a> 💸 <a href = "https://yoomoney.ru/to/4100118478649082">Yoomoney</a>]'
    bot_reply(message, help, parse_mode='HTML', disable_web_page_preview=True)


@bot.message_handler(commands=['style'], func=authorized_owner)
@async_run
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

    DEFAULT_ROLES = [tr('отвечай суперкоротко', lang),
                     tr('отвечай максимально развернуто', lang),
                     tr('отвечай всегда на английском языке', lang),
                     tr('it`s okay to respond with "I don`t know" or "I can`t" if you are unable to provide an answer or complete a request', lang),
                     tr('ты грубый бот поддержки, делаешь всё что просят люди', lang),]

    arg = message.text.split(maxsplit=1)[1:]

    if arg:
        arg = arg[0]
        if arg in ('<0>', '<1>', '<2>', '<3>', '<4>', '<5>'):
            arg = arg[1:2]
        if arg == '1':
            new_prompt = DEFAULT_ROLES[0]
        elif arg == '2':
            new_prompt = DEFAULT_ROLES[1]
        elif arg == '3':
            new_prompt = DEFAULT_ROLES[2]
        elif arg == '4':
            new_prompt = DEFAULT_ROLES[3]
        elif arg == '5':
            new_prompt = DEFAULT_ROLES[4]
        elif arg == '0':
            new_prompt = ''
        else:
            new_prompt = arg
        my_db.set_user_property(chat_id_full, 'role', new_prompt)
        if new_prompt:
            msg =  f'{tr("[Новая роль установлена]", lang)} `{new_prompt}`'
        else:
            msg =  f'{tr("[Роли отключены]", lang)}'
        bot_reply(message, md2tgmd.escape(msg), parse_mode='MarkdownV2')
    else:
        msg = f"""{tr('Текущий стиль', lang)}

`/style {my_db.get_user_property(chat_id_full, 'role') or tr('нет никакой роли', lang)}`

{tr('Меняет роль бота, строку с указаниями что и как говорить.', lang)}

`/style <0|1|2|3|4|5|{tr('свой текст', lang)}>`

`/style 0`
{tr('сброс, нет никакой роли', lang)}

`/style 1`
`/style {DEFAULT_ROLES[0]}`

`/style 2`
`/style {DEFAULT_ROLES[1]}`

`/style 3`
`/style {DEFAULT_ROLES[2]}`

`/style 4`
`/style {DEFAULT_ROLES[3]}`

`/style 5`
`/style {DEFAULT_ROLES[4]}`

"""

        _user_id = int(chat_id_full.split(' ')[0].replace('[','').replace(']',''))
        if _user_id in cfg.admins:
            msg += '`/style ты можешь сохранять и запускать скрипты на питоне и баше через функцию run_script, в скриптах можно импортировать любые библиотеки и обращаться к сети и диску`'
        bot_reply(message, md2tgmd.escape(msg), parse_mode='MarkdownV2')


@bot.message_handler(commands=['disable_chat_mode'], func=authorized_admin)
@async_run
def disable_chat_mode(message: telebot.types.Message):
    """mandatory switch all users from one chatbot to another"""
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    try:
        _from = message.text.split(maxsplit=3)[1].strip()
        _to = message.text.split(maxsplit=3)[2].strip()
        
        n = 0
        for x in my_db.get_all_users_ids():
            if my_db.get_user_property(x, 'chat_mode') == _from:
                my_db.set_user_property(x, 'chat_mode', _to)
                n += 1

        msg = f'{tr("Changed: ", lang)} {n}.'
        bot_reply(message, msg)
    except:
        n = '\n\n'
        msg = f"{tr('Example usage: /disable_chat_mode FROM TO{n}Available:', lang)} gemini15, gemini"
        bot_reply(message, msg, parse_mode='HTML')


@bot.message_handler(commands=['undo', 'u', 'U', 'Undo'], func=authorized_log)
@async_run
def undo(message: telebot.types.Message):
    """Clear chat history last message (bot's memory)"""
    chat_id_full = get_topic_id(message)
    COMMAND_MODE[chat_id_full] = ''
    if 'gemini' in my_db.get_user_property(chat_id_full, 'chat_mode'):
        my_gemini.undo(chat_id_full)
    elif 'llama' in my_db.get_user_property(chat_id_full, 'chat_mode'):
        my_groq.undo(chat_id_full)
    elif 'openrouter' in my_db.get_user_property(chat_id_full, 'chat_mode'):
        my_openrouter.undo(chat_id_full)
    elif 'gemma2-9b' in my_db.get_user_property(chat_id_full, 'chat_mode'):
        my_groq.undo(chat_id_full)
    elif 'gpt4omini' == my_db.get_user_property(chat_id_full, 'chat_mode'):
        my_gpt4omini.undo(chat_id_full)
    elif 'gpt4o' == my_db.get_user_property(chat_id_full, 'chat_mode'):
        my_shadowjourney.undo(chat_id_full)
    elif 'haiku' in my_db.get_user_property(chat_id_full, 'chat_mode'):
        bot_reply_tr(message, 'DuckDuckGo haiku do not support /undo command')
    elif 'gpt-4o-mini-ddg' in my_db.get_user_property(chat_id_full, 'chat_mode'):
        bot_reply_tr(message, 'DuckDuckGo GPT 4o mini do not support /undo command')
    else:
        bot_reply_tr(message, 'History WAS NOT undone.')

    bot_reply_tr(message, 'Last message was cancelled.')


def reset_(message: telebot.types.Message):
    """Clear chat history (bot's memory)
    message - is chat id or message object"""
    if isinstance(message, str):
        chat_id_full = message    
    else:
        chat_id_full = get_topic_id(message)

    if not my_db.get_user_property(chat_id_full, 'chat_mode'):
        my_db.set_user_property(chat_id_full, 'chat_mode', cfg.chat_mode_default)

    if 'gemini' in my_db.get_user_property(chat_id_full, 'chat_mode'):
        my_gemini.reset(chat_id_full)
    elif 'llama' in my_db.get_user_property(chat_id_full, 'chat_mode'):
        my_groq.reset(chat_id_full)
    elif 'openrouter' in my_db.get_user_property(chat_id_full, 'chat_mode'):
        my_openrouter.reset(chat_id_full)
    elif 'gemma2-9b' in my_db.get_user_property(chat_id_full, 'chat_mode'):
        my_groq.reset(chat_id_full)
    elif 'gpt4o' == my_db.get_user_property(chat_id_full, 'chat_mode'):
        my_shadowjourney.reset(chat_id_full)
    elif 'haiku' in my_db.get_user_property(chat_id_full, 'chat_mode'):
        my_ddg.reset(chat_id_full)
    elif 'gpt-4o-mini-ddg' in my_db.get_user_property(chat_id_full, 'chat_mode'):
        my_ddg.reset(chat_id_full)
    elif 'gpt4omini' == my_db.get_user_property(chat_id_full, 'chat_mode'):
        my_gpt4omini.reset(chat_id_full)
    else:
        if isinstance(message, telebot.types.Message):
            bot_reply_tr(message, 'History WAS NOT cleared.')
        return
    if isinstance(message, telebot.types.Message):
        bot_reply_tr(message, 'History cleared.')


@bot.message_handler(commands=['reset', 'clear'], func=authorized_log)
@async_run
def reset(message: telebot.types.Message):
    """Clear chat history (bot's memory)"""
    chat_id_full = get_topic_id(message)
    COMMAND_MODE[chat_id_full] = ''
    reset_(message)


@bot.message_handler(commands=['remove_keyboard'], func=authorized_owner)
@async_run
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
@async_run
def reset_gemini2(message: telebot.types.Message):
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    try:
        arg1 = message.text.split(maxsplit=3)[1]+' '+message.text.split(maxsplit=3)[2]
        my_gemini.reset(arg1)
        msg = f'{tr("История Gemini в чате очищена", lang)} {arg1}'
        bot_reply(message, msg)
    except:
        bot_reply_tr(message, 'Usage: /reset_gemini2 <chat_id_full!>')


@bot.message_handler(commands=['bingcookieclear', 'kc'], func=authorized_admin)
@async_run
def clear_bing_cookies(message: telebot.types.Message):
    bing_img.COOKIE.clear()
    bot_reply_tr(message, 'Cookies cleared.')


@bot.message_handler(commands=['bingcookie', 'cookie', 'k'], func=authorized_admin)
@async_run
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
@async_run
def change_mode2(message: telebot.types.Message):
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    try:
        arg1 = message.text.split(maxsplit=3)[1]+' '+message.text.split(maxsplit=3)[2]
        arg2 = message.text.split(maxsplit=3)[3]
    except:
        bot_reply_tr(message, 'Usage: /style2 <chat_id_full!> <new_style>')
        return

    my_db.set_user_property(arg1, 'role', arg2)
    msg = tr('[Новая роль установлена]', lang) + ' `' + arg2 + '` ' + tr('для чата', lang) + ' `' + arg1 + '`'
    bot_reply(message, md2tgmd.escape(msg), parse_mode='MarkdownV2')


@bot.message_handler(commands=['mem'], func=authorized_owner)
@async_run
def send_debug_history(message: telebot.types.Message):
    """
    Отправляет текущую историю сообщений пользователю.
    """
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    COMMAND_MODE[chat_id_full] = ''

    if 'gemini' in my_db.get_user_property(chat_id_full, 'chat_mode'):
        prompt = 'Gemini\n\n'
        prompt += my_gemini.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        bot_reply(message, prompt, parse_mode = '', disable_web_page_preview = True, reply_markup=get_keyboard('mem', message))
    if 'llama' in my_db.get_user_property(chat_id_full, 'chat_mode'):
        prompt = 'Groq llama 3.1 70b\n\n'
        prompt += my_groq.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        bot_reply(message, prompt, parse_mode = '', disable_web_page_preview = True, reply_markup=get_keyboard('mem', message))
    if 'openrouter' in my_db.get_user_property(chat_id_full, 'chat_mode'):
        prompt = 'Openrouter\n\n'
        prompt += my_openrouter.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        bot_reply(message, prompt, parse_mode = '', disable_web_page_preview = True, reply_markup=get_keyboard('mem', message))
    if 'gemma2-9b' in my_db.get_user_property(chat_id_full, 'chat_mode'):
        prompt = 'Google Gemma 2 9b\n\n'
        prompt += my_groq.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        bot_reply(message, prompt, parse_mode = '', disable_web_page_preview = True, reply_markup=get_keyboard('mem', message))
    if 'gpt4o' == my_db.get_user_property(chat_id_full, 'chat_mode'):
        prompt = 'GPT-4o\n\n'
        prompt += my_shadowjourney.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        bot_reply(message, prompt, parse_mode = '', disable_web_page_preview = True, reply_markup=get_keyboard('mem', message))
    if 'haiku' in my_db.get_user_property(chat_id_full, 'chat_mode'):
        prompt = tr('DuckDuckGo haiku do not support memory manipulation, this memory is not really used, its just for debug', lang) + '\n\n'
        prompt += my_ddg.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        bot_reply(message, prompt, parse_mode = '', disable_web_page_preview = True, reply_markup=get_keyboard('mem', message))
    if 'gpt-4o-mini-ddg' in my_db.get_user_property(chat_id_full, 'chat_mode'):
        prompt = tr('DuckDuckGo GPT 4o mini do not support memory manipulation, this memory is not really used, its just for debug', lang) + '\n\n'
        prompt += my_ddg.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        bot_reply(message, prompt, parse_mode = '', disable_web_page_preview = True, reply_markup=get_keyboard('mem', message))
    if 'gpt4omini' == my_db.get_user_property(chat_id_full, 'chat_mode'):
        prompt = 'GPT-4o-mini\n\n'
        prompt += my_gpt4omini.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        bot_reply(message, prompt, parse_mode = '', disable_web_page_preview = True, reply_markup=get_keyboard('mem', message))


@bot.message_handler(commands=['restart', 'reboot'], func=authorized_admin)
def restart(message):
    """остановка бота. после остановки его должен будет перезапустить скрипт systemd"""
    global LOG_GROUP_DAEMON_ENABLED, ACTIVITY_DAEMON_RUN
    if isinstance(message, telebot.types.Message):
        bot_reply_tr(message, 'Restarting bot, please wait')
    my_log.log2(f'tb:restart: !!!RESTART!!!')
    bot.stop_polling()


@bot.message_handler(commands=['leave'], func=authorized_admin)
@async_run
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
        if my_db.get_user_property(str(chat_id), 'auto_leave_chat') == True:
            bot_reply(message, tr('Вы уже раньше вышли из чата', lang) + f' {chat_id}')
            continue
        my_db.set_user_property(str(chat_id), 'auto_leave_chat', True)
        try:
            bot.leave_chat(chat_id)
            bot_reply(message, tr('Вы вышли из чата', lang) + f' {chat_id}')
        except Exception as error:
            my_log.log2(f'tb:leave: {chat_id} {str(error)}')
            bot_reply(message, tr('Не удалось выйти из чата', lang) + f' {chat_id} {str(error)}')


@bot.message_handler(commands=['revoke'], func=authorized_admin) 
@async_run
def revoke(message: telebot.types.Message):
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
        if my_db.get_user_property(str(chat_id), 'auto_leave_chat') != True:
            bot_reply(message, tr('Этот чат не был в списке забаненных чатов', lang) + f' {chat_id}')
            continue
        my_db.delete_user_property(str(chat_id), 'auto_leave_chat')
        bot_reply(message, tr('Чат удален из списка забаненных чатов', lang) + f' {chat_id}')


@bot.message_handler(commands=['temperature', 'temp'], func=authorized_owner)
@async_run
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

По-умолчанию 1''', lang)}

`/temperature 0.5`
`/temperature 1.5`
`/temperature 2`

{tr('Сейчас температура', lang)} = {my_db.get_user_property(chat_id_full, 'temperature')}
"""
        bot_reply(message, md2tgmd.escape(help), parse_mode='MarkdownV2')
        return

    my_db.set_user_property(chat_id_full, 'temperature', new_temp)
    if chat_id_full not in my_openrouter.PARAMS:
        my_openrouter.PARAMS[chat_id_full] = my_openrouter.PARAMS_DEFAULT
    model, _, max_tokens, maxhistlines, maxhistchars = my_openrouter.PARAMS[chat_id_full]
    my_openrouter.PARAMS[chat_id_full] = [model, float(new_temp), max_tokens, maxhistlines, maxhistchars]

    msg = f'{tr("New temperature set:", lang)} {new_temp}'
    bot_reply(message, md2tgmd.escape(msg), parse_mode='MarkdownV2')


@bot.message_handler(commands=['lang', 'language'], func=authorized_owner)
@async_run
def language(message: telebot.types.Message):
    """change locale"""

    chat_id_full = get_topic_id(message)

    COMMAND_MODE[chat_id_full] = ''

    lang = get_lang(chat_id_full, message)

    supported_langs_trans2 = ', '.join([x for x in supported_langs_trans])

    if len(message.text.split()) < 2:
        msg = f'/lang {tr("двухбуквенный код языка. Меняет язык бота. Ваш язык сейчас: ", lang)} <b>{lang}</b> ({tr(langcodes.Language.make(language=lang).display_name(language="en"), lang).lower()})\n\n{tr("Возможные варианты:", lang)}\n{supported_langs_trans2}\n\n/lang en\n/lang de\n/lang uk\n...'
        bot_reply(message, msg, parse_mode='HTML', reply_markup=get_keyboard('select_lang', message))
        return

    new_lang = message.text.split(maxsplit=1)[1].strip().lower()
    if new_lang == 'ua':
        new_lang = 'uk'
    if new_lang in supported_langs_trans:
        my_db.set_user_property(chat_id_full, 'lang', new_lang)
        msg = f'{tr("Язык бота изменен на:", new_lang)} <b>{new_lang}</b> ({tr(langcodes.Language.make(language=new_lang).display_name(language="en"), new_lang).lower()})'
        bot_reply(message, msg, parse_mode='HTML')
    else:
        msg = f'{tr("Такой язык не поддерживается:", lang)} <b>{new_lang}</b>\n\n{tr("Возможные варианты:", lang)}\n{supported_langs_trans2}'
        bot_reply(message, msg, parse_mode='HTML')


# @bot.message_handler(commands=['tts'], func=authorized)
@async_run
def tts(message: telebot.types.Message, caption = None):
    """ /tts [ru|en|uk|...] [+-XX%] <текст>
        /tts <URL>
    """

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    # urls = re.findall(r'^/tts\s*(https?://[^\s]+)?$', message.text.lower())

    # Process the url, just get the text and show it with a keyboard for voice acting
    args = message.text.split()
    if len(args) == 2 and my_sum.is_valid_url(args[1]):
        with ShowAction(message, 'typing'):
            url = args[1]
            if  '/youtu.be/' in url or 'youtube.com/' in url or '//dzen.ru/video/watch/' in url or \
                '//rutube.ru/video/' in url or 'pornhub.com/view_video.php?viewkey=' in url or \
                ('tiktok.com' in url and 'video' in url) or \
                ('vk.com' in url and '/video-' in url) or \
                ('//my.mail.ru/v/' in url and '/video/' in url):
                text = my_sum.get_text_from_youtube(url, lang)
                text = my_gemini.rebuild_subtitles(text, lang)
                if text:
                    text = utils.bot_markdown_to_html(text)
                    bot_reply(message, text, parse_mode='HTML',
                              reply_markup=get_keyboard('translate', message),
                              disable_web_page_preview=True)
            else:
                text = my_sum.download_text([url, ], 100000, no_links = True)
                if text:
                    bot_reply(message, text, parse_mode='',
                              reply_markup=get_keyboard('translate', message),
                              disable_web_page_preview=True)
            return

    pattern = r'/tts\s+((?P<lang>' + '|'.join(supported_langs_tts) + r')\s+)?\s*(?P<rate>([+-]\d{1,2}%\s+))?\s*(?P<text>.+)'
    match = re.match(pattern, message.text, re.DOTALL)
    if match:
        llang = match.group("lang") or ''
        rate = match.group("rate") or '+0%'  # If rate is not specified, then by default '+0%'
        text = match.group("text") or ''
    else:
        text = llang = rate = ''
    if llang:
        llang = llang.strip()
    if llang == 'ua':
        llang = 'uk'
    if llang == 'eo':
        llang = 'de'
    rate = rate.strip()

    if not llang:
        llang = lang or 'de'
        # # check if message have any letters
        # if sum(1 for char in text if char.isalpha()) > 1:
        #     # 'de' - universal multilang voice
        #     llang = 'de'
        # else: # no any letters in string, use default user language if any
        #     llang = lang or 'de'

    if not text or llang not in supported_langs_tts:
        help = f"""{tr('Usage:', lang)} /tts [ru|en|uk|...] [+-XX%] <{tr('text to speech', lang)}>|<URL>

+-XX% - {tr('acceleration with mandatory indication of direction + or -', lang)}

/tts hello all
/tts en hello, let me speak -  {tr('force english', lang)}
/tts en +50% Hello at a speed of 1.5x - {tr('force english and speed', lang)}
/tts en12 Tell me your name. - {tr('12th english voice - "en-KE-Chilemba" or "en-KE-Asilia"', lang)}

{tr('''en, en2, de and fr voices are multilingual, you can use them to change voice for any language
(/tts ru привет) and (/tts fr привет) will say hello in russian with 2 different voices''', lang)}

{tr('Supported languages:', lang)} https://telegra.ph/Golosa-dlya-TTS-06-29

{tr('Write what to say to get a voice message.', lang)}
"""

        COMMAND_MODE[chat_id_full] = 'tts'
        bot_reply(message, md2tgmd.escape(help), parse_mode = 'MarkdownV2',
                  reply_markup=get_keyboard('command_mode', message),
                  disable_web_page_preview = True)
        return

    with semaphore_talks:
        with ShowAction(message, 'record_audio'):
            COMMAND_MODE[chat_id_full] = ''
            if my_db.get_user_property(chat_id_full, 'tts_gender'):
                gender = my_db.get_user_property(chat_id_full, 'tts_gender')
            else:
                gender = 'female'

            # Microsoft do not support Latin
            if llang == 'la' and (gender=='female' or gender=='male'):
                gender = 'google_female'
                bot_reply_tr(message, "Microsoft TTS cannot pronounce text in Latin language, switching to Google TTS.")

            if my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                text = utils.bot_markdown_to_tts(text)
            if gender == 'google_female':
                #remove numbers from llang
                llang = re.sub(r'\d+', '', llang)
            audio = my_tts.tts(text, llang, rate, gender=gender)
            if not audio and llang != 'de':
                my_log.log2(f'tb:tts:error: trying universal voice for {llang} {rate} {gender} {text}')
                audio = my_tts.tts(text, 'de', rate, gender=gender)
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
@async_run
def google(message: telebot.types.Message):
    """ищет в гугле перед ответом"""
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    if chat_id_full not in GOOGLE_LOCKS:
        GOOGLE_LOCKS[chat_id_full] = threading.Lock()

    with GOOGLE_LOCKS[chat_id_full]:
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
            bot_reply(message, md2tgmd.escape(help), parse_mode = 'MarkdownV2', disable_web_page_preview = False, reply_markup=get_keyboard('command_mode', message))
            return

        with ShowAction(message, 'typing'):
            with semaphore_talks:
                COMMAND_MODE[chat_id_full] = ''
                r, text = my_google.search_v3(q, lang)
                if not r.strip():
                    bot_reply_tr(message, 'Search failed.')
                    return
                my_db.set_user_property(chat_id_full, 'saved_file_name', 'google: ' + q + '.txt')
                my_db.set_user_property(chat_id_full, 'saved_file', text)
            try:
                rr = utils.bot_markdown_to_html(r)
                hash = utils.nice_hash(q, 16)
                SEARCH_PICS[hash] = q
                bot_reply(message, rr, parse_mode = 'HTML',
                                disable_web_page_preview = True,
                                reply_markup=get_keyboard(f'search_pics_{hash}', message), allow_voice=True)
            except Exception as error2:
                my_log.log2(f'tb.py:google: {error2}')

            add_to_bots_mem(f'user {tr("юзер попросил сделать запрос в Google:", lang)} {q}',
                                    f'{tr("бот поискал в Google и ответил:", lang)} {r}',
                                    chat_id_full)


def update_user_image_counter(chat_id_full: str, n: int):
    if not my_db.get_user_property(chat_id_full, 'image_generated_counter'):
        my_db.set_user_property(chat_id_full, 'image_generated_counter', 0)
    my_db.set_user_property(chat_id_full, 'image_generated_counter', my_db.get_user_property(chat_id_full, 'image_generated_counter') + n)

def get_user_image_counter(chat_id_full: str) -> int:
    if not my_db.get_user_property(chat_id_full, 'image_generated_counter'):
        my_db.set_user_property(chat_id_full, 'image_generated_counter', 0)
    return my_db.get_user_property(chat_id_full, 'image_generated_counter')


# @bot.message_handler(commands=['bing10', 'Bing10', ], func=authorized)
# @async_run
# def image10_bing_gen(message: telebot.types.Message):
#     if len(message.text.strip().split(maxsplit=1)) > 1 and message.text.strip().split(maxsplit=1)[1].strip():
#         chat_id_full = get_topic_id(message)
#         if my_db.get_user_property(chat_id_full, 'blocked_bing'):
#             bot_reply_tr(message, 'Bing вас забанил.')
#             return

#         bot_reply_tr(message, '10 times bing`s image generation started.')
#         chat_id_full = get_topic_id(message)
#         for _ in range(10):
#             if chat_id_full in IMAGE10_STOP:
#                 del IMAGE10_STOP[chat_id_full]
#                 return
#             image_bing_gen(message)
#             time.sleep(15)


@bot.message_handler(commands=['bing', 'Bing'], func=authorized)
@async_run
def image_bing_gen(message: telebot.types.Message):
    chat_id_full = get_topic_id(message)
    if my_db.get_user_property(chat_id_full, 'blocked_bing'):
        bot_reply_tr(message, 'Bing вас забанил.')
        time.sleep(2)
        return
    message.text += '[{(BING)}]'
    image_gen(message)


# @bot.message_handler(commands=['stop','cancel'], func=authorized)
# @async_run
# def image10_stop(message: telebot.types.Message):
#     chat_id_full = get_topic_id(message)
#     IMAGE10_STOP[chat_id_full] = True
#     bot_reply_tr(message, 'Image generation stopped.')


# @bot.message_handler(commands=['image10','img10', 'IMG10', 'Image10', 'Img10', 'i10', 'I10', 'imagine10', 'imagine10:', 'Imagine10', 'Imagine10:', 'generate10', 'gen10', 'Generate10', 'Gen10', 'art10', 'Art10'], func=authorized)
# @async_run
# def image10_gen(message: telebot.types.Message):
#     if len(message.text.strip().split(maxsplit=1)) > 1 and message.text.strip().split(maxsplit=1)[1].strip():
#         bot_reply_tr(message, '10 times image generation started.')
#         chat_id_full = get_topic_id(message)
#         for _ in range(10):
#             if chat_id_full in IMAGE10_STOP:
#                 del IMAGE10_STOP[chat_id_full]
#                 return
#             image_gen(message)
#             time.sleep(60)


# @bot.message_handler(commands=['image2','IMG2', 'img2', 'Image2', 'Img2', 'i2', 'I2', 'imagine2', 'imagine2:', 'Imagine2', 'Imagine2:', 'generate2', 'gen2', 'Generate2', 'Gen2', 'art2', 'Art2'], func=authorized)
# @async_run
# def image2_gen(message: telebot.types.Message):
#     is_private = message.chat.type == 'private'
#     if not is_private:
#         bot_reply_tr(message, 'This command is only available in private chats.')
#         return
#     message.text += 'NSFW'
#     image_gen(message)


@bot.message_handler(commands=['image','img', 'IMG', 'Image', 'Img', 'i', 'I', 'imagine', 'imagine:', 'Imagine', 'Imagine:', 'generate', 'gen', 'Generate', 'Gen', 'art', 'Art'], func=authorized)
@async_run
def image_gen(message: telebot.types.Message):
    """Generates a picture from a description"""
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    try:
        # не использовать бинг для рисования запрещенки, он за это банит
        NSFW_FLAG = False
        if message.text.endswith('NSFW'):
            NSFW_FLAG = True
            message.text = message.text[:-4]

        # забаненный в бинге юзер
        if my_db.get_user_property(chat_id_full, 'blocked_bing'):
            NSFW_FLAG = True

        if NSFW_FLAG:
            return

        # рисовать только бингом, команда /bing
        BING_FLAG = False
        if message.text.endswith('[{(BING)}]'):
            message.text = message.text[:-10]
            BING_FLAG = True

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

                    # если новый юзер пытается рисовать сиськи то идет нафиг сразу
                    if not my_db.get_user_property(chat_id_full, 'image_generated_counter'):
                        prompt_lower = prompt.lower()
                        with open('image_bad_words.txt.dat', 'r', encoding='utf-8') as f:
                            bad_words = [x.strip().lower() for x in f.read().split() if x.strip() and not x.strip().startswith('#')]
                        for x in bad_words:
                            if x in prompt_lower:
                                my_db.set_user_property(chat_id_full, 'blocked', True)
                                return

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
                            if BING_FLAG:
                                images = my_genimg.gen_images_bing_only(prompt, chat_id_full, conversation_history)
                            else:
                                images = my_genimg.gen_images(prompt, moderation_flag, chat_id_full, conversation_history, use_bing = True)
                        if chat_id_full in IMAGE10_STOP:
                            # del IMAGE10_STOP[chat_id_full]
                            return
                        # 1 а может и больше запросы к репромптеру
                        # my_db.add_msg(chat_id_full, 'gemini15_flash')
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
                            caption_ = prompt[:900]
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
                                    medias.append(telebot.types.InputMediaPhoto(d, caption = caption_[:900]))
                                except Exception as add_media_error:
                                    error_traceback = traceback.format_exc()
                                    my_log.log2(f'tb:image:add_media_bytes: {add_media_error}\n\n{error_traceback}')

                        if medias and my_db.get_user_property(chat_id_full, 'suggest_enabled'):
                            # 1 запрос на генерацию предложений
                            suggest_query = tr("""Suggest a wide range options for a request to a neural network that
generates images according to the description, show 5 options with no numbers and trailing symbols, add many rich details, 1 on 1 line, output example:

Create image of ...
Create image of ...
Create image of ...
Create image of ...
Create image of ...

5 lines total in answer

the original prompt:""", lang, save_cache=False) + '\n\n\n' + prompt
                            if NSFW_FLAG:
                                suggest = my_gemini.ai(suggest_query, temperature=1.5, mem=my_gemini.MEM_UNCENSORED)
                            else:
                                suggest = my_gemini.ai(suggest_query, temperature=1.5)
                            # my_db.add_msg(chat_id_full, 'gemini15_flash')
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
                                        translated_prompt = tr(prompt, 'ru', save_cache=False)
                                        # bot.send_message(cfg.pics_group, f'{utils.html.unescape(prompt)} | #{utils.nice_hash(chat_id_full)}',
                                        #                 link_preview_options=telebot.types.LinkPreviewOptions(is_disabled=False))

                                        hashtag = 'H' + chat_id_full.replace('[', '').replace(']', '')
                                        bot.send_message(cfg.pics_group, f'{utils.html.unescape(prompt)} | #{hashtag}',
                                                        link_preview_options=telebot.types.LinkPreviewOptions(is_disabled=False))

                                        ratio = fuzz.ratio(translated_prompt, prompt)
                                        if ratio < 70:
                                            # bot.send_message(cfg.pics_group, f'{utils.html.unescape(translated_prompt)} | #{utils.nice_hash(chat_id_full)}',
                                            #                 link_preview_options=telebot.types.LinkPreviewOptions(is_disabled=False))
                                            bot.send_message(cfg.pics_group, f'{utils.html.unescape(translated_prompt)} | #{hashtag}',
                                                            link_preview_options=telebot.types.LinkPreviewOptions(is_disabled=False))

                                        for x in chunks:
                                            bot.send_media_group(pics_group, x)
                                    except Exception as error2:
                                        my_log.log2(f'tb:image:send to pics_group: {error2}')

                                if suggest:
                                    try:
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
                                            my_db.set_im_suggests(h, utils.html.unescape(s))

                                        if NSFW_FLAG:
                                            b1 = telebot.types.InlineKeyboardButton(text = '1️⃣', callback_data = f'imagecmd2_{suggest_hashes[0]}')
                                            b2 = telebot.types.InlineKeyboardButton(text = '2️⃣', callback_data = f'imagecmd2_{suggest_hashes[1]}')
                                            b3 = telebot.types.InlineKeyboardButton(text = '3️⃣', callback_data = f'imagecmd2_{suggest_hashes[2]}')
                                            b4 = telebot.types.InlineKeyboardButton(text = '4️⃣', callback_data = f'imagecmd2_{suggest_hashes[3]}')
                                            b5 = telebot.types.InlineKeyboardButton(text = '5️⃣', callback_data = f'imagecmd2_{suggest_hashes[4]}')
                                            b6 = telebot.types.InlineKeyboardButton(text = '🙈', callback_data = f'erase_answer')
                                        else:
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
                                            if NSFW_FLAG:
                                                suggest_msg += f'{nn} <code>/image2 {s}</code>\n\n'
                                            else:
                                                suggest_msg += f'{nn} <code>/image {s}</code>\n\n'
                                            n += 1
                                        bot_reply(message, suggest_msg, parse_mode = 'HTML', reply_markup=markup)
                                    except Exception as error2:
                                        my_log.log2(f'tb:image:send to suggest: {error2}')
                                add_to_bots_mem(f'{tr("user used /img command to generate", lang)} "{prompt}"',
                                                    f'{tr("images was generated successfully", lang)}',
                                                    chat_id_full)
                        else:
                            bot_reply_tr(message, 'Could not draw anything. Maybe there is no mood, or maybe you need to give another description.')
                            # if hasattr(cfg, 'enable_image_adv') and cfg.enable_image_adv:
                            #     bot_reply_tr(message,
                            #             "Try original site https://www.bing.com/ or Try this free group, it has a lot of mediabots: https://t.me/neuralforum",
                            #             disable_web_page_preview = True)
                            my_log.log_echo(message, '[image gen error] ')
                            add_to_bots_mem(f'{tr("user used /img command to generate", lang)} "{prompt}"',
                                                    f'{tr("bot did not want or could not draw this", lang)}',
                                                    chat_id_full)

                else:
                    COMMAND_MODE[chat_id_full] = 'image'
                    bot_reply(message, md2tgmd.escape(help), parse_mode = 'MarkdownV2', reply_markup=get_keyboard('command_mode', message))
    except Exception as error_unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:image:send: {error_unknown}\n{traceback_error}')


@bot.message_handler(commands=['stats', 'stat'], func=authorized_admin)
@async_run
def stats(message: telebot.types.Message):
    """Функция, показывающая статистику использования бота."""
    with ShowAction(message, 'typing'):
        model_usage1 = my_db.get_model_usage(1)
        model_usage7 = my_db.get_model_usage(7)
        model_usage30 = my_db.get_model_usage(30)

        msg = f'Total messages in DB: {my_db.count_msgs_all()}'
        msg += '\n\n1 day\n'
        if model_usage1:
            for model in model_usage1:
                msg += f'{model} - {model_usage1[model]}\n'
        msg += '\n\n7 days\n'
        if model_usage7:
            for model in model_usage7:
                msg += f'{model} - {model_usage7[model]}\n'
        msg += '\n\n30 days\n'
        if model_usage30:
            for model in model_usage30:
                msg += f'{model} - {model_usage30[model]}\n'

        msg += f'\n\nTotal users: {my_db.get_total_msg_users()}'
        msg += f'\n\nActive users in 1 day: {my_db.get_total_msg_users_in_days(1)}'
        msg += f'\nActive users in 7 days: {my_db.get_total_msg_users_in_days(7)}'
        msg += f'\nActive users in 30 days: {my_db.get_total_msg_users_in_days(30)}'

        msg += f'\n\nNew users in 1 day: {my_db.count_new_user_in_days(1)}'
        msg += f'\nNew users in 7 day: {my_db.count_new_user_in_days(7)}'
        msg += f'\nNew users in 30 day: {my_db.count_new_user_in_days(30)}'

        msg += f'\n\nGemini keys: {len(my_gemini.ALL_KEYS)+len(cfg.gemini_keys)}'
        msg += f'\nGroq keys: {len(my_groq.ALL_KEYS)}'
        msg += f'\nHuggingface keys: {len(my_genimg.ALL_KEYS)}'
        msg += f'\nDEEPL keys: {len(my_trans.ALL_KEYS)+len(cfg.DEEPL_KEYS if hasattr(cfg, "DEEPL_KEYS") else [])}'

        bot_reply(message, msg)


@bot.message_handler(commands=['shell', 'cmd'], func=authorized_admin)
@async_run
def shell_command(message: telebot.types.Message):
    """Выполняет шел комманды"""
    try:
        if not hasattr(cfg, 'SYSTEM_CMDS'):
            bot_reply_tr(message, 'Шел команды не настроены.')
            return

        cmd = message.text.strip().split(maxsplit=1)
        if len(cmd) == 2:
            try:
                n = int(cmd[1])
            except ValueError:
                bot_reply_tr(message, 'Usage: /shell <command number>, empty for list available commands')
                return
            cmd_ = cfg.SYSTEM_CMDS[n -1]
            with subprocess.Popen(cmd_, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding=utils.get_codepage()) as proc:
                stdout, stderr = proc.communicate()
            out_ = stdout + '\n\n' + stderr
            out_ = f'```cmd\n{out_}```'
            bot_reply(message, md2tgmd.escape(out_), parse_mode='MarkdownV2')
        else:
            msg = ''
            n = 1
            for x in cfg.SYSTEM_CMDS:
                msg += f'{n} - {x}\n'
                n += 1
            msg_ = f'```Commands:\n{msg}```'
            msg_ = utils.bot_markdown_to_html(msg_)
            bot_reply(message, msg_, parse_mode='HTML')
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:shell_command {error}\n\n{traceback_error}')




@bot.message_handler(commands=['blockadd3'], func=authorized_admin)
@async_run
def block_user_add3(message: telebot.types.Message):
    """Добавить юзера в стоп список blocked_totally - юзеру не будет даже в логи попадать"""

    chat_full_id = get_topic_id(message)
    lang = get_lang(chat_full_id, message)

    user_id = message.text[10:].strip()
    if user_id:
        my_db.set_user_property(user_id, 'blocked_totally', True)
        bot_reply(message, f'{tr("Пользователь", lang)} {user_id} {tr("добавлен в стоп-лист", lang)}')
    else:
        bot_reply_tr(message, 'Usage: /blockadd3 <[user id] [group id]>')


@bot.message_handler(commands=['blockdel3'], func=authorized_admin)
@async_run
def block_user_del3(message: telebot.types.Message):
    """Убрать юзера из стоп списка totally"""

    chat_full_id = get_topic_id(message)
    lang = get_lang(chat_full_id, message)

    user_id = message.text[10:].strip()
    if user_id:
        if my_db.get_user_property(user_id, 'blocked_totally'):
            my_db.delete_user_property(user_id, 'blocked_totally')
            bot_reply(message, f'{tr("Пользователь", lang)} {user_id} {tr("удален из стоп-листа", lang)}')
        else:
            bot_reply(message, f'{tr("Пользователь", lang)} {user_id} {tr("не найден в стоп-листе", lang)}')
    else:
        bot_reply_tr(message, 'Usage: /blockdel3 <[user id] [group id]>')


@bot.message_handler(commands=['blocklist3'], func=authorized_admin)
@async_run
def block_user_list3(message: telebot.types.Message):
    """Показывает список совсем заблокированных юзеров"""
    if my_db.get_user_all_bad_totally_ids():
        bot_reply(message, '\n'.join(my_db.get_user_all_bad_totally_ids()))





@bot.message_handler(commands=['blockadd2'], func=authorized_admin)
@async_run
def block_user_add2(message: telebot.types.Message):
    """Добавить юзера в стоп список image nsfw - юзеру можно будет рисовать только без бинга"""

    chat_full_id = get_topic_id(message)
    lang = get_lang(chat_full_id, message)

    user_id = message.text[10:].strip()
    if user_id:
        my_db.set_user_property(user_id, 'blocked_bing', True)
        bot_reply(message, f'{tr("Пользователь", lang)} {user_id} {tr("добавлен в стоп-лист", lang)}')
    else:
        bot_reply_tr(message, 'Usage: /blockadd2 <[user id] [group id]>')


@bot.message_handler(commands=['blockdel2'], func=authorized_admin)
@async_run
def block_user_del2(message: telebot.types.Message):
    """Убрать юзера из стоп списка image nsfw"""

    chat_full_id = get_topic_id(message)
    lang = get_lang(chat_full_id, message)

    user_id = message.text[10:].strip()
    if user_id:
        if my_db.get_user_property(user_id, 'blocked_bing'):
            my_db.delete_user_property(user_id, 'blocked_bing')
            bot_reply(message, f'{tr("Пользователь", lang)} {user_id} {tr("удален из стоп-листа", lang)}')
        else:
            bot_reply(message, f'{tr("Пользователь", lang)} {user_id} {tr("не найден в стоп-листе", lang)}')
    else:
        bot_reply_tr(message, 'Usage: /blockdel2 <[user id] [group id]>')


@bot.message_handler(commands=['blocklist2'], func=authorized_admin)
@async_run
def block_user_list2(message: telebot.types.Message):
    """Показывает список заблокированных юзеров image nsfw"""
    if my_db.get_user_all_bad_bing_ids():
        bot_reply(message, '\n'.join(my_db.get_user_all_bad_bing_ids()))


@bot.message_handler(commands=['blockadd'], func=authorized_admin)
@async_run
def block_user_add(message: telebot.types.Message):
    """Добавить юзера в стоп список"""

    chat_full_id = get_topic_id(message)
    lang = get_lang(chat_full_id, message)

    user_id = message.text[10:].strip()
    if user_id:
        my_db.set_user_property(user_id, 'blocked', True)
        bot_reply(message, f'{tr("Пользователь", lang)} {user_id} {tr("добавлен в стоп-лист", lang)}')
    else:
        bot_reply_tr(message, 'Usage: /blockadd <[user id] [group id]>')


@bot.message_handler(commands=['blockdel'], func=authorized_admin)
@async_run
def block_user_del(message: telebot.types.Message):
    """Убрать юзера из стоп списка"""

    chat_full_id = get_topic_id(message)
    lang = get_lang(chat_full_id, message)

    user_id = message.text[10:].strip()
    if user_id:
        if my_db.get_user_property(user_id, 'blocked'):
            my_db.delete_user_property(user_id, 'blocked')
            bot_reply(message, f'{tr("Пользователь", lang)} {user_id} {tr("удален из стоп-листа", lang)}')
        else:
            bot_reply(message, f'{tr("Пользователь", lang)} {user_id} {tr("не найден в стоп-листе", lang)}')
    else:
        bot_reply_tr(message, 'Usage: /blockdel <[user id] [group id]>')


@bot.message_handler(commands=['blocklist'], func=authorized_admin)
@async_run
def block_user_list(message: telebot.types.Message):
    """Показывает список заблокированных юзеров"""
    if my_db.get_user_all_bad_ids():
        bot_reply(message, '\n'.join(my_db.get_user_all_bad_ids()))


@bot.message_handler(commands=['msg', 'm', 'message', 'mes'], func=authorized_admin)
@async_run
def message_to_user(message: telebot.types.Message):
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
@async_run
def alert(message: telebot.types.Message):
    """Сообщение всем кого бот знает."""
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    if message.chat.id in cfg.admins:
        text = message.text[7:]
        if text:
            text = utils.bot_markdown_to_html(text)
            text = f'<b>{tr("Широковещательное сообщение от Верховного Адмнистратора, не обращайте внимания", lang)}</b>' + '\n\n\n' + text

            ids = []
            all_users = list(set(my_db.get_all_users_ids()))
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
                if my_db.get_user_property(chat_id, 'blocked'):
                    continue
                # только тех кто был активен в течение 7 дней
                if my_db.get_user_property(chat_id_full, 'last_time_access') and my_db.get_user_property(chat_id_full, 'last_time_access') + (3600*7*24) < time.time():
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
@async_run
def ask_file2(message: telebot.types.Message):
    '''ответ по сохраненному файлу, вариант с чистым промптом'''
    message.text += '[123CLEAR321]'
    ask_file(message)


@bot.message_handler(commands=['ask', 'а'], func=authorized)
@async_run
def ask_file(message: telebot.types.Message):
    '''ответ по сохраненному файлу'''
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    try:
        query = message.text.split(maxsplit=1)[1]
    except IndexError:
        bot_reply_tr(message, 'Usage: /ask <query saved text>\n\nWhen you send a text document or link to the bot, it remembers the text, and in the future you can ask questions about the saved text.')
        if my_db.get_user_property(chat_id_full, 'saved_file_name'):
            msg = f'{tr("Загружен файл/ссылка:", lang)} {my_db.get_user_property(chat_id_full, "saved_file_name")}\n\n{tr("Размер текста:", lang)} {len(my_db.get_user_property(chat_id_full, "saved_file"))}'
            bot_reply(message, msg, disable_web_page_preview = True, reply_markup=get_keyboard('download_saved_text', message))
            return

    if my_db.get_user_property(chat_id_full, 'saved_file_name'):
        with ShowAction(message, 'typing'):
            if message.text.endswith('[123CLEAR321]'):
                message.text = message.text[:-13]
                q = f"{message.text}\n\n{tr('URL/file:', lang)} {my_db.get_user_property(chat_id_full, 'saved_file_name')}\n\n{tr('Saved text:', lang)} {my_db.get_user_property(chat_id_full, 'saved_file')}"
            else:
                q = f'''{tr('Answer the user`s query using saved text and your own mind.', lang)}

{tr('User query:', lang)} {query}

{tr('URL/file:', lang)} {my_db.get_user_property(chat_id_full, 'saved_file_name')}

{tr('Saved text:', lang)} {my_db.get_user_property(chat_id_full, 'saved_file')}
    '''
            result = my_gemini.ai(q[:my_gemini.MAX_SUM_REQUEST], temperature=1, tokens_limit=8000, model = 'gemini-1.5-flash')
            # result = my_gemini.ai(q[:my_gemini.MAX_SUM_REQUEST], temperature=1, tokens_limit=8000, model = 'gemini-1.5-pro')
            if not result:
                result = my_groq.ai(q[:my_groq.MAX_SUM_REQUEST], temperature=1, max_tokens_ = 4000, model_ = 'llama-3.1-70b-versatile')
            if not result:
                result = my_groq.ai(q[:my_groq.MAX_REQUEST_GEMMA2_9B], model_ = 'gemma2-9b-it', temperature=1, max_tokens_ = 4000)

            if result:
                answer = utils.bot_markdown_to_html(result)
                bot_reply(message, answer, parse_mode='HTML')
                add_to_bots_mem(tr("The user asked to answer the question based on the saved text:", lang) + ' ' + my_db.get_user_property(chat_id_full, 'saved_file_name')+'\n'+query,
                                result, chat_id_full)
            else:
                bot_reply_tr(message, 'No reply from AI')
                return
    else:
        bot_reply_tr(message, 'Usage: /ask <query saved text>')
        bot_reply_tr(message, 'No text was saved')
        return


@bot.message_handler(commands=['ping', 'echo'])
def ping(message: telebot.types.Message):
    bot.reply_to(message, 'pong')


@bot.message_handler(commands=['sum'], func=authorized)
@async_run
def summ_text(message: telebot.types.Message):

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    if chat_id_full not in SUM_LOCKS:
        SUM_LOCKS[chat_id_full] = threading.Lock()

    with SUM_LOCKS[chat_id_full]:
        text = message.text

        if len(text.split(' ', 1)) == 2:

            # блокируем одновременные запросы на одно и тоже
            request_hash = utils.nice_hash(text)
            if request_hash not in SUM_LOCKS:
                SUM_LOCKS[request_hash] = threading.Lock()
            with SUM_LOCKS[request_hash]:
                url = text.split(' ', 1)[1].strip()
                if my_sum.is_valid_url(url):
                    # убираем из ютуб урла временную метку
                    if '/youtu.be/' in url or 'youtube.com/' in url:
                        url = url.split("&t=")[0]

                    url_id = str([url, lang])
                    with semaphore_talks:

                        #смотрим нет ли в кеше ответа на этот урл
                        r = my_db.get_from_sum(url_id)

                        if r:
                            with ShowAction(message, 'typing'):
                                my_db.set_user_property(chat_id_full, 'saved_file_name', url + '.txt')
                                text = my_sum.summ_url(url, lang = lang, deep = False, download_only=True)
                                my_db.set_user_property(chat_id_full, 'saved_file', text)
                                rr = utils.bot_markdown_to_html(r)
                                ask = tr('Use /ask command to query this file. Example /ask generate a short version of part 1.', lang)
                                bot_reply(message, rr + '\n' + ask, disable_web_page_preview = True,
                                                    parse_mode='HTML',
                                                    reply_markup=get_keyboard('translate', message))
                                add_to_bots_mem(tr("юзер попросил кратко пересказать содержание текста по ссылке/из файла", lang) + ' ' + url,
                                                    f'{tr("бот прочитал и ответил:", lang)} {r}',
                                                    chat_id_full)
                                return

                        with ShowAction(message, 'typing'):
                            res = ''
                            try:
                                has_subs = my_sum.check_ytb_subs_exists(url)
                                if not has_subs and ('/youtu.be/' in url or 'youtube.com/' in url):
                                    bot_reply_tr(message, 'Видео с ютуба не содержит субтитров, обработка может занять некоторое время.')
                                res, text = my_sum.summ_url(url, lang = lang, deep = False)
                                my_db.set_user_property(chat_id_full, 'saved_file_name', url + '.txt')
                                my_db.set_user_property(chat_id_full, 'saved_file', text)
                            except Exception as error2:
                                print(error2)
                                bot_reply_tr(message, md2tgmd.escape('Не нашел тут текста. Возможно что в видео на ютубе нет субтитров или страница слишком динамическая и не показывает текст без танцев с бубном, или сайт меня не пускает.\n\nЕсли очень хочется то отправь мне текстовый файл .txt (utf8) с текстом этого сайта и подпиши `что там`'), parse_mode='MarkdownV2')
                                return
                            if res:
                                rr = utils.bot_markdown_to_html(res)
                                ask = tr('Use /ask command to query this file. Example /ask generate a short version of part 1.', lang)
                                bot_reply(message, rr + '\n' + ask, parse_mode='HTML',
                                                    disable_web_page_preview = True,
                                                    reply_markup=get_keyboard('translate', message))
                                my_db.set_sum_cache(url_id, res)
                                add_to_bots_mem(tr("юзер попросил кратко пересказать содержание текста по ссылке/из файла", lang) + ' ' + url,
                                                f'{tr("бот прочитал и ответил:", lang)} {res}',
                                                chat_id_full)
                                return
                            else:
                                bot_reply_tr(message, 'Не смог прочитать текст с этой страницы.')
                                return
        help = f"""{tr('Пример:', lang)} /sum https://youtu.be/3i123i6Bf-U

{tr('Давайте вашу ссылку и я перескажу содержание', lang)}"""
        COMMAND_MODE[chat_id_full] = 'sum'
        bot_reply(message, md2tgmd.escape(help), parse_mode = 'MarkdownV2', reply_markup=get_keyboard('command_mode', message))


@bot.message_handler(commands=['sum2'], func=authorized)
@async_run
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
            my_db.delete_from_sum(url_id)

    summ_text(message)


#@bot.message_handler(commands=['trans', 'tr', 't'], func=authorized)
@async_run
def trans(message: telebot.types.Message):

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
            bot_reply(message, md2tgmd.escape(help), parse_mode = 'MarkdownV2',
                         reply_markup=get_keyboard('command_mode', message))
            return
        llang = llang.strip()
        if llang == 'ua':
            llang = 'uk'

        with ShowAction(message, 'typing'):
            translated = tr(text, llang, save_cache=False)
            if translated and translated != text:
                try:
                    detected_lang = my_trans.detect(text) or 'unknown language'
                    detected_lang = tr(langcodes.Language.make(language=detected_lang).display_name(language="en"), lang).lower()
                except:
                    detected_lang = tr('unknown language', lang)

                bot_reply(message,
                          translated + '\n\n' + tr('Распознанный язык:', lang) \
                          + ' ' + detected_lang,
                          reply_markup=get_keyboard('translate', message))
            else:
                # bot_reply_tr(message, 'Ошибка перевода')
                message.text = text
                do_task(message)


@bot.message_handler(commands=['name'], func=authorized_owner)
@async_run
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
            my_db.set_user_property(chat_id_full, 'bot_name', new_name.lower())
            msg = f'{tr("Кодовое слово для обращения к боту изменено на", lang)} ({args[1]}) {tr("для этого чата.", lang)}'
            bot_reply(message, msg)
        else:
            msg = f"{tr('Неправильное имя, цифры после букв, не больше 10 всего. Имена', lang)} {', '.join(BAD_NAMES) if BAD_NAMES else ''} {tr('уже заняты.', lang)}"
            bot_reply(message, msg)
    else:
        help = f"{tr('Напишите новое имя бота и я поменяю его, цифры после букв, не больше 10 всего. Имена', lang)} {', '.join(BAD_NAMES) if BAD_NAMES else ''} {tr('уже заняты.', lang)}"
        COMMAND_MODE[chat_id_full] = 'name'
        bot_reply(message, md2tgmd.escape(help), parse_mode='MarkdownV2', reply_markup=get_keyboard('command_mode', message))


def is_language_code_valid_for_ocr(code: str) -> bool:
  """
  Проверяет, является ли строка с языками корректной.

  Args:
    code: Строка с языками, разделенными плюсами (например, "rus+eng+jpn").

  Returns:
    True, если строка корректна, False в противном случае.
  """
  for lang in code.split('+'):
    if lang not in my_init.languages_ocr:
      return False
  return True


@bot.message_handler(commands=['ocr'], func=authorized)
@async_run
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
    my_db.set_user_property(chat_id_full, 'ocr_lang', arg)

    bot_reply(message, msg, parse_mode='HTML')
    if not is_language_code_valid_for_ocr(arg):
        bot_reply_tr(message, 'Проверьте правильность введенных данных, похоже что в них ошибка.', lang)


@bot.message_handler(commands=['start'], func = authorized_log)
@async_run
def send_welcome_start(message: telebot.types.Message):
    # Отправляем приветственное сообщение
    try:
        user_have_lang = message.from_user.language_code
    except Exception as error:
        my_log.log2(f'tb:start {error}\n\n{str(message)}')
        user_have_lang = None

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    COMMAND_MODE[chat_id_full] = ''
    if not my_db.get_user_property(chat_id_full, 'chat_mode'):
        my_db.set_user_property(chat_id_full, 'chat_mode', cfg.chat_mode_default)

    args = message.text.split(maxsplit = 1)
    if len(args) == 2:
        if args[1].lower() in [x.lower() for x in my_init.supported_langs_trans+['pt-br',]]:
            lang = args[1].lower()

    if lang in HELLO_MSG:
        help = HELLO_MSG[lang]
    else:
        help = my_init.start_msg
        my_log.log2(f'tb:send_welcome_start Unknown language: {lang}')

    bot_reply(message, help, parse_mode='HTML', disable_web_page_preview=True, reply_markup=get_keyboard('start', message))
    if chat_id_full not in NEW_KEYBOARD:
        NEW_KEYBOARD[chat_id_full] = True

    # no language in user info, show language selector
    if not user_have_lang:
        language(message)


@bot.message_handler(commands=['help'], func = authorized_log)
@async_run
def send_welcome_help(message: telebot.types.Message):
    # Отправляем приветственное сообщение

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    COMMAND_MODE[chat_id_full] = ''
    
    args = message.text.split(maxsplit = 1)
    if len(args) == 2:
        if args[1] in my_init.supported_langs_trans+['pt-br',]:
            lang = args[1]

    help = HELP_MSG[lang] if lang in HELP_MSG else my_init.help_msg
    if lang not in HELP_MSG:
        my_log.log2(f'tb:send_welcome_help Unknown language: {lang}')

    help = utils.bot_markdown_to_html(help)
    bot_reply(message, help, parse_mode='HTML', disable_web_page_preview=True)


@bot.message_handler(commands=['free', 'help_1'], func = authorized_log)
@async_run
def send_welcome_help_1(message: telebot.types.Message):
    # почему бесплатно и как это работает

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)
    COMMAND_MODE[chat_id_full] = ''

    args = message.text.split(maxsplit = 1)
    if len(args) == 2:
        if args[1] in my_init.supported_langs_trans+['pt-br',]:
            lang = args[1]

    help = """
**Google** gives everyone free API keys to its **Gemini** AI, you can insert them into this bot and use them.

**Groq** gives free API keys to its **llama3** and **mistral** AI, and they can be inserted into this bot.

**Openrouter** provides access to all other paid AIs, you can insert your personal key and use it in this bot.

**DEEPL** will give free API keys to its translator, they can be inserted into this bot.

The keys have usage limits, but if you use them together and there are enough keys, the limits cease to be a problem.

**If you have paid accounts on these services and use them for something else, do not give your keys to this bot, it is meant to work only with free keys.**

Voice recognition, drawing, etc. also all work on free services in one way or another.
"""
    help = tr(help, lang)
    help = utils.bot_markdown_to_html(help)
    bot_reply(message, help, disable_web_page_preview=True, parse_mode='HTML')


@bot.message_handler(commands=['report'], func = authorized_log)
@async_run
def report_cmd_handler(message: telebot.types.Message):
    chat_id_full = get_topic_id(message)
    COMMAND_MODE[chat_id_full] = ''
    bot_reply_tr(message, 'Support telegram group https://t.me/kun4_sun_bot_support')


@bot.message_handler(commands=['purge'], func = authorized_owner)
@async_run
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
            my_shadowjourney.reset(chat_id_full)
            my_gpt4omini.reset(chat_id_full)
            my_ddg.reset(chat_id_full)

            my_db.delete_user_property(chat_id_full, 'role')
            my_db.delete_user_property(chat_id_full, 'persistant_memory')

            my_db.set_user_property(chat_id_full, 'bot_name', BOT_NAME_DEFAULT)
            if my_db.get_user_property(chat_id_full, 'saved_file_name'):
                my_db.delete_user_property(chat_id_full, 'saved_file_name')
                my_db.delete_user_property(chat_id_full, 'saved_file')

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
        my_log.log2(f'tb:purge_cmd_handler: {unknown}\n\n{message.chat.id}\n\n{error_traceback}')


@bot.message_handler(commands=['id'], func = authorized_log)
@async_run
def id_cmd_handler(message: telebot.types.Message):
    """показывает id юзера и группы в которой сообщение отправлено"""
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    COMMAND_MODE[chat_id_full] = ''

    user_id = message.from_user.id
    reported_language = message.from_user.language_code
    open_router_model, temperature, max_tokens, maxhistlines, maxhistchars = my_openrouter.PARAMS[chat_id_full] if chat_id_full in my_openrouter.PARAMS else my_openrouter.PARAMS_DEFAULT

    user_model = my_db.get_user_property(chat_id_full, 'chat_mode') if my_db.get_user_property(chat_id_full, 'chat_mode') else cfg.chat_mode_default
    models = {
        'gemini': 'Gemini 1.5 Flash',
        'gemini15': 'Gemini 1.5 Pro',
        'llama370': 'Llama 3.1 70b',
        'openrouter': 'openrouter.ai',
        'gpt4o': 'GPT 4o',
        'gpt4omini': 'GPT 4o mini',
        'gemma2-9b': 'Gemma 2 9b',
        'haiku': 'Claude 3 Haiku',
        'gpt35': 'GPT 3.5',
        'gpt-4o-mini-ddg': 'GPT 4o mini',
    }
    if user_model in models.keys():
        user_model = f'<b>{models[user_model]}</b>'
 
    msg = f'''{tr("ID пользователя:", lang)} {user_id}

{tr("ID группы:", lang)} {chat_id_full}

{tr("Язык который телеграм сообщает боту:", lang)} {reported_language}

{tr("Выбранная чат модель:", lang)} {user_model}'''
    if my_db.get_user_property(chat_id_full, 'chat_mode') == 'openrouter':
        msg += f' <b>{open_router_model}</b>'

    gemini_keys = my_gemini.USER_KEYS[chat_id_full] if chat_id_full in my_gemini.USER_KEYS else []
    groq_keys = [my_groq.USER_KEYS[chat_id_full],] if chat_id_full in my_groq.USER_KEYS else []
    openrouter_keys = [my_openrouter.KEYS[chat_id_full],] if chat_id_full in my_openrouter.KEYS else []
    deepl_keys = [my_trans.USER_KEYS[chat_id_full],] if chat_id_full in my_trans.USER_KEYS else []
    huggingface_keys = [my_genimg.USER_KEYS[chat_id_full],] if chat_id_full in my_genimg.USER_KEYS else []
    # keys_count = len(gemini_keys) + len(groq_keys) + len(openrouter_keys) + len(deepl_keys)
    keys_count = len(gemini_keys) + len(groq_keys) + len(deepl_keys)
    keys_count_ = '🔑'*keys_count

    if openrouter_keys:
        msg += '\n\n🔑️ OpenRouter\n'
    else:
        msg += '\n\n🔒 OpenRouter\n'
    if gemini_keys:
        msg += '🔑️ Gemini\n'
    else:
        msg += '🔒 Gemini\n'
    if groq_keys:
        msg += '🔑️ Groq\n'
    else:
        msg += '🔒 Groq\n'
    if deepl_keys:
        msg += '🔑️ Deepl\n'
    else:
        msg += '🔒 Deepl\n'
    if huggingface_keys:
        msg += '🔑️ Huggingface\n'
    else:
        msg += '🔒 Huggingface\n'

    if my_db.get_user_property(chat_id_full, 'blocked'):
        msg += f'\n{tr("User was banned.", lang)}\n'

    if my_db.get_user_property(chat_id_full, 'blocked_bing'):
        msg += f'\n{tr("User was banned in bing.com.", lang)}\n'

    if str(message.chat.id) in DDOS_BLOCKED_USERS and not my_db.get_user_property(chat_id_full, 'blocked'):
        msg += f'\n{tr("User was temporarily banned.", lang)}\n'

    if my_db.get_user_property(chat_id_full, 'persistant_memory'):
        msg += f'\n{tr("Что бот помнит о пользователе:", lang)}\n{my_db.get_user_property(chat_id_full, "persistant_memory")}'

    bot_reply(message, msg, parse_mode = 'HTML')


@bot.message_handler(commands=['enable'], func=authorized_owner)
@async_run
def enable_chat(message: telebot.types.Message):
    """что бы бот работал в чате надо его активировать там"""
    is_private = message.chat.type == 'private'
    if is_private:
        bot_reply_tr(message, "Use this command to activate bot in public chat.")
        return
    user_full_id = f'[{message.from_user.id}] [0]'
    admin_have_keys = user_full_id in my_gemini.USER_KEYS and user_full_id in my_groq.USER_KEYS \
                      and user_full_id in my_genimg.USER_KEYS or message.from_user.id in cfg.admins

    if admin_have_keys:
        chat_full_id = get_topic_id(message)
        my_db.set_user_property(chat_full_id, 'chat_enabled', True)
        user_lang = get_lang(user_full_id)
        my_db.set_user_property(chat_full_id, 'lang', user_lang)
        bot_reply_tr(message, 'Chat enabled.')
    else:
        bot_reply_tr(message, 'Что бы включить бота в публичном чате надо сначала вставить свои ключи. В приватном чате команды /id /keys /openrouter')


@bot.message_handler(commands=['disable'], func=authorized_owner)
@async_run
def disable_chat(message: telebot.types.Message):
    """что бы бот не работал в чате надо его деактивировать там"""
    is_private = message.chat.type == 'private'
    if is_private:
        bot_reply_tr(message, "Use this command to deactivate bot in public chat.")
        return
    chat_id_full = get_topic_id(message)
    my_db.delete_user_property(chat_id_full, 'chat_enabled')
    bot_reply_tr(message, 'Chat disabled.')


@bot.message_handler(commands=['init'], func=authorized_admin)
@async_run
def set_default_commands(message: telebot.types.Message):
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

    if not resp.strip():
        return

    chat_id_full = get_topic_id(message)

    preview = telebot.types.LinkPreviewOptions(is_disabled=disable_web_page_preview)

    if len(resp) < 45000:
        if parse_mode == 'HTML':
            chunks = utils.split_html(resp, 3800)
        else:
            chunks = utils.split_text(resp, 3800)
        counter = len(chunks)
        for chunk in chunks:
            if not chunk.strip():
                continue
            # в режиме только голоса ответы идут голосом без текста
            # скорее всего будет всего 1 чанк, не слишком длинный текст
            if my_db.get_user_property(chat_id_full, 'voice_only_mode') and allow_voice:
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
    if my_db.get_user_property(from_user_id, 'blocked'):
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
                n = 10
        message.text = last_state
        del MESSAGE_QUEUE[chat_id_full]
    else:
        MESSAGE_QUEUE[chat_id_full] += message.text + '\n\n'
        u_id_ = str(message.chat.id)
        if u_id_ in request_counter.counts:
            if request_counter.counts[u_id_]:
                request_counter.counts[u_id_].pop(0)
        return


    if custom_prompt:
        message.text = custom_prompt

    # кто по умолчанию отвечает
    if not my_db.get_user_property(chat_id_full, 'chat_mode'):
        my_db.set_user_property(chat_id_full, 'chat_mode', cfg.chat_mode_default)

    # определяем откуда пришло сообщение  
    is_private = message.chat.type == 'private'
    supch = my_db.get_user_property(chat_id_full, 'superchat') or 0
    # если бот должен отвечать всем в этом чате то пусть ведет себя как в привате
    # но если это ответ на чье-то сообщение то игнорируем
    if supch == 1:
        is_private = True

    # удаляем пробелы в конце каждой строки,
    # это когда текст скопирован из кривого терминала с кучей лишних пробелов
    message.text = "\n".join([line.rstrip() for line in message.text.split("\n")])

    msg = message.text.lower().strip()

    # detect /tts /t /tr /trans command
    if is_private:
        if msg in ('/tts', f'/tts@{_bot_name}') or msg.startswith(('/tts ', '/tts\n', f'/tts@{_bot_name} ', f'/tts@{_bot_name}\n')):
            tts(message)
            return

        if msg in ('/t', '/tr', '/trans', f'/trans@{_bot_name}') or msg.startswith(('/t ', '/t\n', '/tr ', '/tr\n', '/trans ', '/trans\n', f'/trans@{_bot_name} ', f'/trans@{_bot_name}\n')):
            trans(message)
            return


    chat_mode_ = my_db.get_user_property(chat_id_full, 'chat_mode')

    have_keys = chat_id_full in my_gemini.USER_KEYS or chat_id_full in my_groq.USER_KEYS or \
        chat_id_full in my_trans.USER_KEYS or chat_id_full in my_genimg.USER_KEYS or\
            message.from_user.id in cfg.admins

    # если у юзера нет апи ключа для джемини то переключаем на дешевый флеш
    # if my_db.get_user_property(chat_id_full, 'chat_mode') == 'gemini15' and not have_keys and is_private:
    #     chat_mode_ = 'gemini'

    if is_private:
        if not have_keys:
            total_messages__ = my_db.count_msgs(chat_id_full, 'all', 1000000000)
            # каждые 50 сообщение напоминать о ключах
            if total_messages__ > 1 and total_messages__ % 50 == 0:
                if message.chat.type == 'private':
                    msg = tr('This bot uses API keys to unlock more powerful AI features. You can obtain a free key at https://ai.google.dev/ and provide it to the bot using the command /keys xxxxxxx. Video instructions:', lang) + ' https://www.youtube.com/watch?v=6aj5a7qGcb4\n\nFree VPN: https://www.vpnjantit.com/'
                    bot_reply(message, msg, disable_web_page_preview = True)
                    # если больше 1000 сообщений уже и нет ключей то нафиг
                    # if total_messages__ > 1000:
                    #     return
        # но даже если ключ есть всё равно больше 300 сообщений в день нельзя,
        # на бесплатных ключах лимит - 50, 300 может получится за счет взаимопомощи
        if chat_mode_ == 'gemini15' and my_db.count_msgs(chat_id_full, 'gemini15_pro', 60*60*24) > 300:
            chat_mode_ = 'gemini'
    else:
        if chat_mode_ == 'gemini15' and my_db.count_msgs(chat_id_full, 'gemini15_pro', 60*60*24) > 300:
            chat_mode_ = 'gemini'

    chat_modes = {
        '/gemma2':    'gemma2-9b',
        '/gemma':     'gemma2-9b',
        '/haiku':     'haiku',
        '/flash':     'gemini',
        '/pro':       'gemini15',
        '/llama':     'llama370',
        # '/gpt35':     'gpt35',
        '/gpt4omini': 'gpt-4o-mini-ddg',
        '/gpt':       'gpt-4o-mini-ddg',
    }
    for command, mode in chat_modes.items():
        if msg.startswith(command):
            try:
                l = len(command) + 1
                message.text = message.text[l:]
                msg = msg[l:]
                chat_mode_ = mode
            except IndexError:
                pass
            if not msg.strip():
                return
            break


    # обработка \image это неправильное /image
    if (msg.startswith('\\image ') and is_private):
        message.text = message.text.replace('/', '\\', 1)
        image_gen(message)
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

        # определяем какое имя у бота в этом чате, на какое слово он отзывается
        bot_name = my_db.get_user_property(chat_id_full, 'bot_name') or BOT_NAME_DEFAULT

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
                    image_gen(message)
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
                            my_db.set_user_property(chat_id_full, 'saved_file_name', f'User googled phone number: {message.text}.txt')
                            my_db.set_user_property(chat_id_full, 'saved_file', text__)
                        else:
                            with ShowAction(message, 'typing'):
                                # response, text__ = my_gemini.check_phone_number(number)
                                response, text__ = my_groq.check_phone_number(number)
                                my_db.add_msg(chat_id_full, 'llama3-70b-8192')
                        if response:
                            my_db.set_user_property(chat_id_full, 'saved_file_name', f'User googled phone number: {message.text}.txt')
                            my_db.set_user_property(chat_id_full, 'saved_file', text__)
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
                    # my_db.add_msg(chat_id_full, 'gemini15_flash')
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
            image_gen(message)
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

            if my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                action = 'record_audio'
                message.text = f'[{tr("голосовое сообщение, возможны ошибки распознавания речи, отвечай просто без форматирования текста - ответ будет зачитан вслух", lang)}]: ' + message.text
            else:
                action = 'typing'

            # подсказка для ботов что бы понимали где и с кем общаются
            formatted_date = utils.get_full_time()
            if message.chat.title:
                lang_of_user = get_lang(f'[{message.from_user.id}] [0]', message) or lang
                if my_db.get_user_property(chat_id_full, 'role'):
                    hidden_text = f'[Info to help you answer. You are a telegram chatbot named "{bot_name}", you are working in chat named "{message.chat.title}", your memory limited to last 20 messages, user have telegram commands (/img - image generator, /tts - text to speech, /trans - translate, /sum - summarize, /google - search, you can answer voice messages, images, documents, urls(any text and youtube subs)), you cannot do anything in the background, user name is "{message.from_user.full_name}", user language code is "{lang_of_user}" but it`s not important, your current date is "{formatted_date}", your special role here is "{my_db.get_user_property(chat_id_full, "role")}", do not address the user by name and no emoji unless it is required.]'
                else:
                    hidden_text = f'[Info to help you answer. You are a telegram chatbot named "{bot_name}", you are working in chat named "{message.chat.title}", your memory limited to last 20 messages, user have telegram commands (/img - image generator, /tts - text to speech, /trans - translate, /sum - summarize, /google - search, you can answer voice messages, images, documents, urls(any text and youtube subs)), you cannot do anything in the background, user name is "{message.from_user.full_name}", user language code is "{lang_of_user}" but it`s not important, your current date is "{formatted_date}", do not address the user by name and no emoji unless it is required.]'
            else:
                if my_db.get_user_property(chat_id_full, 'role'):
                    hidden_text = f'[Info to help you answer. You are a telegram chatbot named "{bot_name}", you are working in private for user named "{message.from_user.full_name}", your memory limited to last 20 messages, user have telegram commands (/img - image generator, /tts - text to speech, /trans - translate, /sum - summarize, /google - search, you can answer voice messages, images, documents, urls(any text and youtube subs)), you cannot do anything in the background, user language code is "{lang}" but it`s not important, your current date is "{formatted_date}", your special role here is "{my_db.get_user_property(chat_id_full, "role")}", do not address the user by name and no emoji unless it is required.]'
                else:
                    hidden_text = f'[Info to help you answer. You are a telegram chatbot named "{bot_name}", you are working in private for user named "{message.from_user.full_name}", your memory limited to last 20 messages, user have telegram commands (/img - image generator, /tts - text to speech, /trans - translate, /sum - summarize, /google - search, you can answer voice messages, images, documents, urls(any text and youtube subs)), you cannot do anything in the background, user language code is "{lang}" but it`s not important, your current date is "{formatted_date}", do not address the user by name and no emoji unless it is required.]'
            hidden_text_for_llama370 = tr(f'Answer in "{lang}" language, do not address the user by name and no emoji unless it is required.', lang)
            omode = my_db.get_user_property(chat_id_full, 'original_mode') or False
            if omode:
                helped_query = message.text
                hidden_text_for_llama370 = ''
                hidden_text = ''
            else:
                helped_query = f'{hidden_text} {message.text}'

            if chat_id_full not in CHAT_LOCKS:
                CHAT_LOCKS[chat_id_full] = threading.Lock()
            with CHAT_LOCKS[chat_id_full]:

                WHO_ANSWERED[chat_id_full] = chat_mode_
                if chat_mode_ == 'gemini':
                    WHO_ANSWERED[chat_id_full] = 'gemini15flash'
                elif chat_mode_ == 'gemini15':
                    WHO_ANSWERED[chat_id_full] = 'gemini15pro'
                time_to_answer_start = time.time()

                # если активирован режим общения с Gemini Flash
                if chat_mode_ == 'gemini':
                    if len(msg) > my_gemini.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для Gemini, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_gemini.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            if not my_db.get_user_property(chat_id_full, 'temperature'):
                                my_db.set_user_property(chat_id_full, 'temperature', GEMIMI_TEMP_DEFAULT)

                            # answer = my_gemini.chat(helped_query,
                            #                         chat_id_full,
                            #                         my_db.get_user_property(chat_id_full, 'temperature'),
                            #                         model = 'gemini-1.5-flash')

                            answer = my_gemini.chat(message.text,
                                                    chat_id_full,
                                                    my_db.get_user_property(chat_id_full, 'temperature'),
                                                    model = 'gemini-1.5-flash',
                                                    system = hidden_text,
                                                    use_skills=True
                                                    )

                            # если ответ длинный и в нем очень много повторений то вероятно это зависший ответ
                            # передаем эстафету следующему претенденту (ламе)
                            if len(answer) > 2000 and my_transcribe.detect_repetitiveness_with_tail(answer):
                                answer = ''
                            if fuzz.ratio(answer, tr("images was generated successfully", lang)) > 80:
                                my_gemini.undo(chat_id_full)
                                message.text = f'/image {message.text}'
                                image_gen(message)
                                return
                            if chat_id_full not in WHO_ANSWERED:
                                WHO_ANSWERED[chat_id_full] = 'gemini15flash'
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'

                            flag_gpt_help = False
                            if not answer:
                                style_ = my_db.get_user_property(chat_id_full, 'role') or hidden_text_for_llama370
                                mem__ = my_gemini.get_mem_for_llama(chat_id_full)
                                if style_:
                                    answer = my_groq.ai(f'({style_}) {message.text}', mem_ = mem__, model_ = 'llama-3.1-70b-versatile',)
                                else:
                                    answer = my_groq.ai(message.text, mem_ = mem__, model_ = 'llama-3.1-70b-versatile',)
                                if fuzz.ratio(answer, tr("images was generated successfully", lang)) > 80:
                                    my_groq.undo(chat_id_full)
                                    message.text = f'/image {message.text}'
                                    image_gen(message)
                                    return
                                my_db.add_msg(chat_id_full, 'llama3-70b-8192')
                                flag_gpt_help = True
                                if not answer:
                                    answer = 'Gemini ' + tr('did not answered, try to /reset and start again', lang)
                                    return
                                my_gemini.update_mem(message.text, answer, chat_id_full)

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            if flag_gpt_help:
                                WHO_ANSWERED[chat_id_full] = f'👇Gemini15flash + llama3-70 {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'
                                my_log.log_echo(message, f'[Gemini15flash + llama3-70] {answer}')
                            else:
                                my_log.log_echo(message, f'[Gemini15flash] {answer}')
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
                            my_log.log2(f'tb:do_task:gemini10 {error3}\n{error_traceback}')
                        return

                # если активирован режим общения с Gemini 1.5 pro
                if chat_mode_ == 'gemini15':
                    if len(msg) > my_gemini.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для Gemini, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_gemini.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            if not my_db.get_user_property(chat_id_full, 'temperature'):
                                my_db.set_user_property(chat_id_full, 'temperature', GEMIMI_TEMP_DEFAULT)

                            # answer = my_gemini.chat(helped_query,
                            #                         chat_id_full,
                            #                         my_db.get_user_property(chat_id_full, 'temperature'),
                            #                         model = 'gemini-1.5-pro')

                            exp_ = True
                            WHO_ANSWERED[chat_id_full] = 'gemini15pro-exp'
                            answer = my_gemini.chat(message.text,
                                                    chat_id_full,
                                                    my_db.get_user_property(chat_id_full, 'temperature'),
                                                    # model = 'gemini-1.5-pro',
                                                    model = 'gemini-1.5-pro-exp-0801',
                                                    system = hidden_text,
                                                    use_skills=True,
                                                    )
                            if not answer:
                                exp_ = False
                                WHO_ANSWERED[chat_id_full] = 'gemini15pro'
                                answer = my_gemini.chat(message.text,
                                                        chat_id_full,
                                                        my_db.get_user_property(chat_id_full, 'temperature'),
                                                        model = 'gemini-1.5-pro',
                                                        system = hidden_text,
                                                        use_skills=True,
                                                        )

                            # если ответ длинный и в нем очень много повторений то вероятно это зависший ответ
                            # передаем эстафету следующему претенденту (ламе)
                            if len(answer) > 2000 and my_transcribe.detect_repetitiveness_with_tail(answer):
                                answer = ''
                            if fuzz.ratio(answer, tr("images was generated successfully", lang)) > 80:
                                my_gemini.undo(chat_id_full)
                                message.text = f'/image {message.text}'
                                image_gen(message)
                                return
                            if chat_id_full not in WHO_ANSWERED:
                                if exp_:
                                    WHO_ANSWERED[chat_id_full] = 'gemini15pro-exp'
                                else:
                                    WHO_ANSWERED[chat_id_full] = 'gemini15pro'
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'
                            flag_gpt_help = False
                            if not answer:
                                style_ = my_db.get_user_property(chat_id_full, 'role') or hidden_text_for_llama370
                                mem__ = my_gemini.get_mem_for_llama(chat_id_full)
                                if style_:
                                    answer = my_groq.ai(f'({style_}) {message.text}', mem_ = mem__, model_ = 'llama-3.1-70b-versatile',)
                                else:
                                    answer = my_groq.ai(message.text, mem_ = mem__, model_ = 'llama-3.1-70b-versatile',)
                                if fuzz.ratio(answer, tr("images was generated successfully", lang)) > 80:
                                    my_groq.undo(chat_id_full)
                                    message.text = f'/image {message.text}'
                                    image_gen(message)
                                    return
                                my_db.add_msg(chat_id_full, 'llama3-70b-8192')
                                flag_gpt_help = True
                                if not answer:
                                    answer = 'Gemini ' + tr('did not answered, try to /reset and start again', lang)
                                    return
                                my_gemini.update_mem(message.text, answer, chat_id_full)

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            if flag_gpt_help:
                                WHO_ANSWERED[chat_id_full] = f'👇Gemini15pro + llama3-70 {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'
                                my_log.log_echo(message, f'[Gemini15pro + llama3-70] {answer}')
                            else:
                                if exp_:
                                    my_log.log_echo(message, f'[Gemini15pro-exp] {answer}')
                                else:
                                    my_log.log_echo(message, f'[Gemini15pro] {answer}')
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
                            my_log.log2(f'tb:do_task:gemini15 {error3}\n{error_traceback}')
                        return

                # если активирован режим общения с groq llama 3.1 70b
                if chat_mode_ == 'llama370':
                    if len(msg) > my_groq.MAX_REQUEST_LLAMA31:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для Groq llama 3.1 70b, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_groq.MAX_REQUEST_LLAMA31}')
                        return

                    with ShowAction(message, action):
                        try:
                            if not my_db.get_user_property(chat_id_full, 'temperature'):
                                my_db.set_user_property(chat_id_full, 'temperature', GEMIMI_TEMP_DEFAULT)

                            style_ = my_db.get_user_property(chat_id_full, 'role') or hidden_text_for_llama370
                            if style_:
                                answer = my_groq.chat(f'({style_}) {message.text}',
                                                      chat_id_full,
                                                      my_db.get_user_property(chat_id_full, 'temperature'),
                                                      model = 'llama-3.1-70b-versatile',
                                                    #   model = 'llama3-70b-8192',
                                                      )
                            else:
                                answer = my_groq.chat(message.text,
                                                      chat_id_full,
                                                      my_db.get_user_property(chat_id_full, 'temperature'),
                                                      model = 'llama-3.1-70b-versatile',
                                                    #   model = 'llama3-70b-8192',
                                                      )
                            if fuzz.ratio(answer, tr("images was generated successfully", lang)) > 80:
                                my_groq.undo(chat_id_full)
                                message.text = f'/image {message.text}'
                                image_gen(message)
                                return

                            if chat_id_full not in WHO_ANSWERED:
                                WHO_ANSWERED[chat_id_full] = 'qroq-llama370'
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'

                            if not answer:
                                answer = 'Groq llama 3.1 70b ' + tr('did not answered, try to /reset and start again', lang)

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
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
                    #     bot_reply(message, f'{tr("Слишком длинное сообщение для openrouter, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_openrouter.MAX_REQUEST}')
                    #     return

                    with ShowAction(message, action):
                        try:
                            style_ = my_db.get_user_property(chat_id_full, 'role') or ''
                            status, answer = my_openrouter.chat(message.text, chat_id_full, system=style_)
                            WHO_ANSWERED[chat_id_full] = 'openrouter ' + my_openrouter.PARAMS[chat_id_full][0]
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'

                            if not answer:
                                answer = 'Openrouter ' + tr('did not answered, try to /reset and start again. Check your balance https://openrouter.ai/credits', lang)

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            my_log.log_echo(message, f'[openrouter {my_openrouter.PARAMS[chat_id_full][0]}] {answer}')
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
                            my_log.log2(f'tb:do_task:openrouter {error3}\n{error_traceback}')
                        return


                # если активирован режим общения с gpt-4o
                if chat_mode_ == 'gpt4o':
                    # не знаем какие там лимиты
                    if len(msg) > my_shadowjourney.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для gpt-4o, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_shadowjourney.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            answer = my_shadowjourney.chat(message.text, chat_id_full, system=hidden_text)
                            WHO_ANSWERED[chat_id_full] = 'gpt-4o '
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'

                            llama_helped = False
                            if not answer:
                                answer = 'GPT-4o ' + tr('did not answered, try to /reset and start again', lang)
                            # llama_helped = True
                            else:
                                my_shadowjourney.update_mem(message.text, answer, chat_id_full)

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            if llama_helped:
                                WHO_ANSWERED[chat_id_full] = f'👇gpt4o + llama3-70 {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'
                                my_log.log_echo(message, f'[groq-llama370] {answer}')
                            else:
                                my_log.log_echo(message, f'[gpt-4o] {answer}')
                            try:
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('gpt4o_chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'tb:do_task: {error}')
                                my_log.log2(f'tb:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('gpt4o_chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'tb:do_task:gpt4o {error3}\n{error_traceback}')
                        return



                # если активирован режим общения с gpt-4o-mini
                if chat_mode_ == 'gpt4omini':
                    if len(msg) > my_gpt4omini.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для gpt-4o-mini, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_gpt4omini.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            status_code, answer = my_gpt4omini.chat(message.text, chat_id_full, system=hidden_text)
                            WHO_ANSWERED[chat_id_full] = 'gpt-4o-mini '
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'

                            llama_helped = False
                            if not answer:
                                answer = 'GPT-4o-mini ' + tr('did not answered, try to /reset and start again', lang)
                            # llama_helped = True
                            # else:
                            #     my_gpt4omini.update_mem(message.text, answer, chat_id_full)

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            if llama_helped:
                                WHO_ANSWERED[chat_id_full] = f'👇gpt4omini + llama3-70 {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'
                                my_log.log_echo(message, f'[groq-llama370] {answer}')
                            else:
                                my_log.log_echo(message, f'[gpt-4o] {answer}')
                            try:
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('gpt4omini_chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'tb:do_task: {error}')
                                my_log.log2(f'tb:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('gpt4omini_chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'tb:do_task:gpt4omini {error3}\n{error_traceback}')
                        return



                # если активирован режим общения с gemma 2 9b
                if chat_mode_ == 'gemma2-9b':
                    if len(msg) > my_groq.MAX_REQUEST_GEMMA2_9B:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для gemma2 9b, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_groq.MAX_REQUEST_GEMMA2_9B}')
                        return

                    with ShowAction(message, action):
                        try:
                            style_ = my_db.get_user_property(chat_id_full, 'role') or ''
                            answer = my_groq.chat(message.text, chat_id_full, style=style_, model = 'gemma2-9b-it', timeout = 60)
                            if not answer:
                                time.sleep(5)
                                answer = my_groq.chat(message.text, chat_id_full, style=style_, model = 'gemma2-9b-it')
                            WHO_ANSWERED[chat_id_full] = 'gemma2-9b '
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'

                            if not answer:
                                answer = 'Gemma2 9b ' + tr('did not answered, try to /reset and start again', lang)

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            my_log.log_echo(message, f'[gemma2-9b] {answer}')
                            try:
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('gemma2-9b_chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'tb:do_task: {error}')
                                my_log.log2(f'tb:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('gemma2-9b_chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'tb:do_task:gemma2-9b {error3}\n{error_traceback}')
                        return



                # если активирован режим общения с haiku (duckduckgo)
                if chat_mode_ == 'haiku':
                    if len(msg) > my_ddg.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для haiku, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_ddg.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            # answer = my_ddg.chat(message.text, chat_id_full)
                            answer = my_ddg.chat(helped_query, chat_id_full, model='claude-3-haiku')
                            answer = answer.strip()
                            if not answer:
                                answer = tr('Haiku did not answered, try to /reset and start again', lang)
                            WHO_ANSWERED[chat_id_full] = 'haiku-ddg'
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            my_log.log_echo(message, f'[haiku-ddg] {answer}')
                            try:
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('haiku_chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'tb:do_task: {error}')
                                my_log.log2(f'tb:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('haiku_chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'tb:do_task:haiku {error3}\n{error_traceback}')
                        return


                # если активирован режим общения с gpt-4o-mini-ddg (duckduckgo)
                if chat_mode_ == 'gpt-4o-mini-ddg':
                    if len(msg) > my_ddg.MAX_REQUEST_4O_MINI:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для GPT 4o mini, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_ddg.MAX_REQUEST_4O_MINI}')
                        return

                    with ShowAction(message, action):
                        try:
                            # answer = my_ddg.chat(message.text, chat_id_full)
                            answer = my_ddg.chat(helped_query, chat_id_full, model = 'gpt-4o-mini')
                            answer = answer.strip()
                            if not answer:
                                answer = tr('GPT 4o mini did not answered, try to /reset and start again', lang)
                            WHO_ANSWERED[chat_id_full] = 'gpt-4o-mini-ddg'
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            my_log.log_echo(message, f'[gpt-4o-mini-ddg] {answer}')
                            try:
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('gpt-4o-mini-ddg_chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'tb:do_task: {error}')
                                my_log.log2(f'tb:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('gpt-4o-mini-ddg_chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'tb:do_task:gpt-4o-mini-ddg {error3}\n{error_traceback}')
                        return


@async_run
def activity_daemon():
    '''Restarts the bot if it's been inactive for too long, may be telegram collapsed.'''
    return # не работает почему то
    global ACTIVITY_DAEMON_RUN
    while ACTIVITY_DAEMON_RUN:
        time.sleep(1)
        if ACTIVITY_MONITOR['last_activity'] + ACTIVITY_MONITOR['max_inactivity'] < time.time():
            my_log.log2(f'tb:activity_daemon: reconnect after {ACTIVITY_MONITOR["max_inactivity"]} inactivity')
            restart(True)


@async_run
def load_msgs():
    """
    Load the messages from the start and help message files into the HELLO_MSG and HELP_MSG global variables.

    Parameters:
        None
    
    Returns:
        None
    """
    global HELLO_MSG, HELP_MSG
    
    try:
        with open(my_init.start_msg_file, 'rb') as f:
            HELLO_MSG = pickle.load(f)
    except Exception as error:
        my_log.log2(f'tb:load_msgs:hello {error}')
        HELLO_MSG = {}

    try:
        with open(my_init.help_msg_file, 'rb') as f:
            HELP_MSG = pickle.load(f)
    except Exception as error:
        my_log.log2(f'tb:load_msgs:help {error}')
        HELP_MSG = {}


def one_time_shot():
    try:
        if not os.path.exists('one_time_flag.txt'):
            pass

            # # удалить таблицу
            # try:
            #     my_db.CUR.execute("""DROP TABLE sum;""")
            #     my_db.CON.commit()
            # except Exception as error:
            #     my_log.log2(f'tb:one_time_shot: {error}')


            queries = [
                # '''ALTER TABLE users ADD COLUMN persistant_memory TEXT;''',
                # '''ALTER TABLE users ADD COLUMN api_key_gemini TEXT;''',
                # '''ALTER TABLE users ADD COLUMN api_key_groq TEXT;''',
                # '''ALTER TABLE users ADD COLUMN api_key_deepl TEXT;''',
                '''ALTER TABLE users ADD COLUMN dialog_gpt4omini BLOB;''',
                       ]
            for q in queries:
                try:
                    my_db.CUR.execute(q)
                    my_db.CON.commit()
                except Exception as error:
                    my_log.log2(f'tb:one_time_shot: {error}')


            # # запоминаем время последнего обращения к боту
            # LAST_TIME_ACCESS = SqliteDict('db/last_time_access.db', autocommit=True)
            # for key in LAST_TIME_ACCESS:
            #     value = LAST_TIME_ACCESS[key]
            #     my_db.set_user_property(key, 'last_time_access', value)
            # del LAST_TIME_ACCESS



            with open('one_time_flag.txt', 'w') as f:
                f.write('done')
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:one_time_shot: {error}\n{traceback_error}')


def main():
    """
    Runs the main function, which sets default commands and starts polling the bot.
    """
    bot.remove_webhook()

    load_msgs()

    my_gemini.load_users_keys()
    my_genimg.load_users_keys()
    my_groq.load_users_keys()
    my_trans.load_users_keys()
    my_db.init()

    one_time_shot()

    activity_daemon()

    log_group_daemon()

    # Remove webhook, it fails sometimes the set if there is a previous webhook
    bot.remove_webhook()
    time.sleep(1)

    if hasattr(cfg, 'WEBHOOK_DOMAIN') and hasattr(cfg, 'WEBHOOK_PORT') and hasattr(cfg, 'WEBHOOK_SSL_CERT') and hasattr(cfg, 'WEBHOOK_SSL_PRIV'):
        bot.run_webhooks(
            listen=cfg.WEBHOOK_DOMAIN,
            port = cfg.WEBHOOK_PORT,
            certificate=cfg.WEBHOOK_SSL_CERT,
            certificate_key=cfg.WEBHOOK_SSL_PRIV
        )
    else:
        # bot.polling(timeout=90, long_polling_timeout=90)
        bot.infinity_polling(timeout=90, long_polling_timeout=90)

    global LOG_GROUP_DAEMON_ENABLED, ACTIVITY_DAEMON_RUN
    LOG_GROUP_DAEMON_ENABLED = False
    ACTIVITY_DAEMON_RUN = False
    time.sleep(10)
    my_db.close()


if __name__ == '__main__':
    main()
