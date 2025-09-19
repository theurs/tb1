#!/usr/bin/env python3


import base64
import concurrent.futures
import io
import importlib
import hashlib
import os
import pickle
import random
import re
import subprocess
import sys
import traceback
import threading
import time
from flask import Flask, request, jsonify
from decimal import Decimal, getcontext
from multiprocessing.pool import ThreadPool
from typing import Any, Dict, List, Optional, Union, Tuple

import langcodes
import pendulum
import PIL
import telebot
from fuzzywuzzy import fuzz
from sqlitedict import SqliteDict

import cfg
import md2tgmd
import my_alert
import my_init
import my_genimg
import my_cerebras
import my_cerebras_tools
import my_cmd_callback
import my_cmd_document
import my_cmd_img
import my_cmd_img2txt
import my_cmd_photo
import my_cmd_text
import my_cmd_voice
import my_cohere
import my_db
import my_ddg
import my_doc_translate
import my_github
import my_google
# import my_gemini_embedding
import my_gemini_general
import my_gemini3
import my_gemini_tts
import my_gemini_genimg
import my_gemini_google
import my_groq
import my_log
import my_md_tables_to_png
import my_mistral
import my_nebius
import my_pdf
import my_psd
import my_openrouter
import my_openrouter_free
import my_pandoc
import my_plantweb
import my_skills
import my_skills_general
import my_skills_storage
import my_stat
import my_stt
import my_svg
import my_subscription
import my_sum
import my_tavily
import my_qrcode
import my_trans
import my_transcribe
import my_tts
import my_ytb
import my_zip
import utils
import utils_llm
from utils import async_run


START_TIME = time.time()


# устанавливаем рабочую папку = папке в которой скрипт лежит
os.chdir(os.path.abspath(os.path.dirname(__file__)))

# папка для постоянных словарей, памяти бота
if not os.path.exists('db'):
    os.mkdir('db')


# API для доступа к функциям бота (бинг в основном)
FLASK_APP = Flask(__name__)


if hasattr(cfg, 'SKIP_PENDING') and cfg.SKIP_PENDING:
    bot = telebot.TeleBot(cfg.token, skip_pending=True)
else:
    bot = telebot.TeleBot(cfg.token)


_bot_name = bot.get_me().username
BOT_ID = bot.get_me().id
cfg._BOT_NAME = _bot_name


# телеграм группа для отправки сгенерированных картинок
pics_group = cfg.pics_group if hasattr(cfg, 'pics_group') else None



# {id: 'img'|'bing'|None}
# когда юзер нажимает на кнопку /img то ожидается ввод промпта для рисования всеми способами
# но когда юзер вводит команду /bing то ожидается ввод промпта для рисования толлько бинга
IMG_MODE_FLAG = {}

# {user_id: (fail counter, datetime)}
# запоминаем сколько раз подряд бинг не смог ничего нарисовать для этого юзера, если больше 5 то блокируем на 5 минут
BING_FAILS = {}

# сообщения приветствия и помощи
HELLO_MSG = {}
HELP_MSG = {}

# хранилище для запросов на поиск картинок
# {hash: search query}
SEARCH_PICS = {}

# используется в команде /reload
RELOAD_LOCK = threading.Lock()

# блокировка чата что бы юзер не мог больше 1 запроса делать за раз,
# только для запросов к гпт*. {chat_id_full(str):threading.Lock()}
CHAT_LOCKS = {}

# блокировка отправки картинок в галерею
LOCK_PICS_GROUP = threading.Lock()

# блокировка на выполнение одновременных команд sum, google, image, document handler, voice handler
# {chat_id:threading.Lock()}
GOOGLE_LOCKS = {}
SUM_LOCKS = {}
IMG_GEN_LOCKS = {}
IMG_GEN_LOCKS_FLUX = {}
IMG_GEN_LOCKS_GEM_IMG = {}
DOCUMENT_LOCKS = {}
VOICE_LOCKS = {}
IMG_LOCKS = {}
TTS_LOCKS = {}

# key:value storage
# used for any other key:value needs
KV_STORAGE = SqliteDict('db/kv_storage.db', autocommit=True)

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
# так же ловим пачки картинок(медиагруппы)+текст, после пересылки картинки с инструкцией от юзера
# они разделяются на 2 части, отдельно подпись от юзера и отдельно картинки
MESSAGE_QUEUE_GRP = {}
MESSAGE_QUEUE_AUDIO_GROUP = {}

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
# NEW_KEYBOARD = SqliteDict('db/new_keyboard_installed.db', autocommit=True)


# запоминаем группы файлов (для правильного приема групп текстовых файлов)
# {user_id: message_group_id}
FILE_GROUPS = {}


# {user_id:(date, image, list(images)),} keep up to UNCAPTIONED_IMAGES_MAX images
UNCAPTIONED_IMAGES_MAX = 100
UNCAPTIONED_IMAGES = SqliteDict('db/user_images.db', autocommit = True)
# {user_id: image_prompt}
UNCAPTIONED_PROMPTS = SqliteDict('db/user_image_prompts.db', autocommit = True)
UNCAPTIONED_IMAGES_LOCK = threading.Lock()


# {message.from_user.id: threading.Lock(), }
CHECK_DONATE_LOCKS = {}


class NoLock: # грязный хак что бы отключить замок (временный костыль)
    def __enter__(self):
        pass  # Ничего не делаем при входе в блок with

    def __exit__(self, exc_type, exc_value, traceback):
        pass  # Ничего не делаем при выходе из блока with


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

LOCK_FOR_SHOW_ACTION_LOCKS = threading.Lock()
# {chat_id:lock}
SHOW_ACTION_LOCKS = {}

class ShowAction(threading.Thread):
    """A thread that can be stopped. Continuously sends a notification of activity to the chat.
    Telegram automatically extinguishes the notification after 5 seconds, so it must be repeated.

    To use in the code, you need to do something like this:
    with ShowAction(message, 'typing'):
        do something and while doing it the notification does not go out
    """
    def __init__(self, message: telebot.types.Message, action: str = 'typing', max_timeout: int = 5):
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
        self.max_timeout = max_timeout
        self.chat_id = message.chat.id
        self.full_chat_id = get_topic_id(message)
        self.thread_id = message.message_thread_id
        self.lang = get_lang(self.full_chat_id, message)
        self.is_topic = True if message.is_topic_message else False
        self.action = action
        self.is_running = True
        self.timerseconds = 1
        self.started_time = time.time()

        # '' - отображение стандартным для телеграма стилем
        # 'message' - отображение в виде сообщения о том что бот что то пишет, сообщение удаляется автоматически
        self.action_style = my_db.get_user_property(self.full_chat_id, 'action_style') or ''

        MSG = '...'
        if self.action_style == 'message':
            if self.action in ("typing", "upload_document", "find_location"):
                MSG = '⌛ ' + tr('Creating a response...', self.lang)
            elif self.action in ("upload_photo",):
                MSG = '⌛ ' + tr('Creating an image...', self.lang)
            elif self.action in ("record_video", "record_video_note"):
                MSG = '⌛ ' + tr('Creating a video...', self.lang)
            elif self.action in ("record_audio", "upload_audio"):
                MSG = '⌛ ' + tr('Creating an audio file...', self.lang)

            self.action_message = bot.send_message(
                self.chat_id,
                MSG,
                message_thread_id = self.thread_id,
                disable_notification=True,
                )

    def run(self):
        with LOCK_FOR_SHOW_ACTION_LOCKS:
            if self.full_chat_id not in SHOW_ACTION_LOCKS:
                SHOW_ACTION_LOCKS[self.full_chat_id] = threading.Lock()
        with SHOW_ACTION_LOCKS[self.full_chat_id]:
            while self.is_running:
                if time.time() - self.started_time > 60 * self.max_timeout:
                    self.stop()
                    # my_log.log2(f'tb:1:show_action:stoped after 5min [{self.chat_id}] [{self.thread_id}] is topic: {self.is_topic} action: {self.action}')
                    return
                try:
                    if not self.action_style:
                        if self.is_topic:
                            bot.send_chat_action(self.chat_id, self.action, message_thread_id = self.thread_id, timeout=30)
                        else:
                            bot.send_chat_action(self.chat_id, self.action, timeout=30)
                except Exception as error:
                    if 'A request to the Telegram API was unsuccessful. Error code: 429. Description: Too Many Requests' not in str(error):
                        if 'Forbidden: bot was blocked by the user' in str(error):
                            self.stop()
                            return
                        my_log.log2(f'tb:show_action:2:run: {str(error)} | {self.full_chat_id}')
                n = 50
                while n > 0:
                    time.sleep(0.1)
                    n = n - self.timerseconds

    def stop(self):
        self.timerseconds = 50
        self.is_running = False
        try:
            if not self.action_style:
                bot.send_chat_action(self.chat_id, 'cancel', message_thread_id = self.thread_id, timeout=30)
            elif self.action_style == 'message':
                bot.delete_message(self.chat_id, self.action_message.message_id)
        except Exception as error:
            if 'Forbidden: bot was blocked by the user' in str(error):
                self.stop()
                return
            my_log.log2(f'tb:show_action:stop:3: {str(error)} | {self.full_chat_id}')

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


def get_uptime() -> str:
    """Calculates and returns the uptime in a human-readable format (English).

    Returns:
        str: Uptime formatted as a string, e.g., "1 day, 2 hours, 3 minutes, 4 seconds".
    """
    try:
        uptime = time.time() - START_TIME
        uptime_seconds = int(uptime)
        days = uptime_seconds // 86400
        hours = (uptime_seconds % 86400) // 3600
        minutes = (uptime_seconds % 3600) // 60
        seconds = uptime_seconds % 60

        uptime_formatted = ""
        if days > 0:
            uptime_formatted += f"{days} day{'s' if days > 1 else ''} "
        if hours > 0 or days > 0:
            uptime_formatted += f"{hours} hour{'s' if hours > 1 else ''} "
        if minutes > 0 or hours > 0 or days > 0:
            uptime_formatted += f"{minutes} minute{'s' if minutes > 1 else ''} "
        uptime_formatted += f"{seconds} second{'s' if seconds > 1 else ''}"

        return uptime_formatted
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:get_uptime: {unknown}\n{traceback_error}')
        return 'unknown'


def tr(text: str, lang: str, help: str = '', save_cache: bool = True) -> str:
    """
    This function translates text to the specified language,
    using either the AI translation engine or the standard translation engine.
    Here, caching needs to be disabled for strings that might be too numerous,
    which are created individually on request, because all saved strings will then be translated
    into all possible languages, which is a very expensive operation.

    Args:
        text: The text to translate.
        lang: The language to translate to.
        help: The help text for ai translator.
        save_cache: Whether to save the translated text in the DB on disk.

    Returns:
        The translated text.
    """
    try:
        # if lang == 'fa':
        #     lang = 'en'
        if lang == 'ua':
            lang = 'uk'

        if not help:
            help = 'its a gui message in telegram bot, keep it same format and average size to fit gui'

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

        if not translated:
            translated = my_cerebras.translate(text, to_lang=lang, help=help)

        if not translated:
            translated = my_gemini3.translate(text, to_lang=lang, help=help, censored=True)

        if not translated:
            translated = my_groq.translate(text, to_lang=lang, help=help)

        if not translated:
            translated = my_trans.translate(text, lang)


        if not translated:
            translated = text
            TRANS_CACHE.set(cache_key_hash, translated)
            return text

        TRANS_CACHE.set(cache_key_hash, translated)
        if save_cache:
            my_db.update_translation(text, lang, help, translated)

        if isinstance(translated, str):
            return translated
        else:
            traceback_error = traceback.format_exc()
            my_log.log2(f'tb:tr: переводчик вернул что то вместо строки {type(translated)}\n\n{str(translated)}\n\n{traceback_error}')
            return text
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:tr: {unknown}\n{traceback_error}')
        return text


def add_to_bots_mem(query: str, resp: str, chat_id_full: str):
    """
    Updates the memory of the selected bot based on the chat mode.

    Args:
        query: The user's query text.
        resp: The bot's response.
        chat_id_full: The full chat ID.
    """
    try:
        query = query.strip()
        resp = resp.strip()
        if not query or not resp:
            return

        mode = my_db.get_user_property(chat_id_full, 'chat_mode') or ''

        # Updates the memory of the selected bot based on the chat mode.
        if any(mode.startswith(m) for m in ('gemini', 'gemma')):
            my_gemini3.update_mem(query, resp, chat_id_full, model=mode)
        elif 'openrouter' in mode:
            my_openrouter.update_mem(query, resp, chat_id_full)

        elif 'cloacked' in mode:
            my_openrouter_free.update_mem(query, resp, chat_id_full)

        elif 'qwen3' in mode:
            my_cerebras.update_mem(query, resp, chat_id_full)
        elif 'qwen3coder' in mode:
            my_cerebras.update_mem(query, resp, chat_id_full)
        elif 'llama4' in mode:
            my_cerebras.update_mem(query, resp, chat_id_full)
        elif 'gpt_oss' in mode:
            my_cerebras.update_mem(query, resp, chat_id_full)
        elif mode in ('mistral', 'magistral'):
            my_mistral.update_mem(query, resp, chat_id_full)
        elif mode in ('gpt-4o', 'gpt_41', 'gpt_41_mini', 'deepseek_r1', 'deepseek_v3'):
            my_github.update_mem(query, resp, chat_id_full)
        elif 'cohere' in mode:
            my_cohere.update_mem(query, resp, chat_id_full)
        else:
            raise Exception(f'Unknown chat mode: {mode} for chat_id_full: {chat_id_full}')
    except Exception as unexpected_error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:add_to_bots_mem:{unexpected_error}\n\n{traceback_error}')


def img2img(
    text: bytes|List[bytes],
    lang: str,
    chat_id_full: str,
    query: str = '',
    model: str = '',
    temperature: float = 1, # почему тут было 0?
    system_message: str = '',
    timeout: int = 120,
) -> Optional[bytes]:
    """
    Regenerate the image using a query.
    Tries OpenRouter first, then falls back to the old method.

    Args:
        text (bytes): The source image data.
        lang (str): The language code (unused, for compatibility).
        chat_id_full (str): The full chat ID for logging.
        query (str): The user's prompt for the edit.
        model (str): The model to use (for OpenRouter).
        temperature (float): Generation temperature.
        system_message (str): System message for the model.
        timeout (int): Request timeout in seconds.

    Returns:
        Optional[bytes]: The new image as bytes, or None on failure.
    """
    return my_cmd_img2txt.img2img(
        text=text,
        lang=lang,
        chat_id_full=chat_id_full,
        query=query,
        model=model,
        temperature=temperature,
        system_message=system_message,
        timeout=timeout,
    )


def img2txt(
    text,
    lang: str,
    chat_id_full: str,
    query: str = '',
    model: str = '',
    temperature: float = 0,
    system_message: str = '',
    timeout: int = 120,
    images: List[bytes|str] = [],
    ) -> str:
    """
    Generate the text description of an image.

    Args:
        text (str): The image file URL or downloaded data(bytes).
        lang (str): The language code for the image description.
        chat_id_full (str): The full chat ID.
        query (str): The user's query text.
        model (str): gemini model
        temperature (float): temperature
        system_message (str): system message (role/style)
        timeout (int): timeout
        images (List[bytes|str]): List of image data or URLs.

    Returns:
        str: The text description of the image.
    """
    return my_cmd_img2txt.img2txt(
        text=text,
        lang=lang,
        chat_id_full=chat_id_full,
        query=query,
        model=model,
        temperature=temperature,
        system_message=system_message,
        timeout=timeout,
        images=images,
        WHO_ANSWERED=WHO_ANSWERED,
        UNCAPTIONED_IMAGES=UNCAPTIONED_IMAGES,
        add_to_bots_mem=add_to_bots_mem,
        tr=tr,
    )


def get_lang(user_id: str, message: telebot.types.Message = None) -> str:
    """
    Returns the language corresponding to the given ID.

    Args:
        user_id (str): The ID of the user.
        message (telebot.types.Message, optional): The message object. Defaults to None.

    Returns:
        str: The language corresponding to the given user ID.
    """
    try:
        lang = my_db.get_user_property(user_id, 'lang')

        if not lang:
            lang = cfg.DEFAULT_LANGUAGE
            if message:
                lang = message.from_user.language_code or cfg.DEFAULT_LANGUAGE
            my_db.set_user_property(user_id, 'lang', lang)

        lang = lang.lower()
        if lang == 'pt-br':
            lang = 'pt'
        if lang.startswith('zh-'):
            lang = 'zh'
        if lang == 'ka-ge':
            lang = 'ka'

        return lang
    except Exception as unexpected_error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:get_lang:{unexpected_error}\n\n{traceback_error}')
        return cfg.DEFAULT_LANGUAGE


def get_topic_id(message: telebot.types.Message) -> str:
    """
    Get the topic ID from a Telegram message.

    Parameters:
        message (telebot.types.Message): The Telegram message object.

    Returns:
        str: '[chat.id] [topic.id]'
    """
    try:
        chat_id = message.chat.id
        topic_id = 0

        if message.reply_to_message and message.reply_to_message.is_topic_message:
            topic_id = message.reply_to_message.message_thread_id
        elif message.is_topic_message:
            topic_id = message.message_thread_id

        return f'[{chat_id}] [{topic_id}]'
    except Exception as unexpected_error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:get_topic_id:{unexpected_error}\n\n{traceback_error}')


def get_id_parameters_for_function(message: telebot.types.Message, chat_id_full: str = None) -> str:
    '''
    Пытается получить единственный параметр у функции - id, возвращает либо chat_id_full
    id - либо int либо пара int-ов с скобками или без
    если int то результат [int] [0]
    если пара интов то результат [int1] [int2]
    Используется в командах типа /reset <id> /purge <id> /mem <id> /save <id>
    где требуются админские полномочия
    '''
    if chat_id_full is None:
        chat_id_full = get_topic_id(message)

    args = message.text.split(maxsplit=1)
    if len(args) > 1: # Проверка на наличие аргументов после /reset
        potential_id = args[1].strip()
        if message.from_user.id in cfg.admins: # Проверка, является ли пользователь админом
            # Попытка разобрать potential_id как форматы ID пользователя/чата
            target_chat_id_full = None
            try:
                user_id = int(potential_id) # Попытка преобразовать в целое число (user_id)
                target_chat_id_full = f'[{user_id}] [0]'
            except ValueError:
                try:
                    parts = potential_id.replace('[','').replace(']','').split() # Попытка формата '[int] [int]'
                    if len(parts) == 2:
                        chat_id = int(parts[0])
                        topic_id = int(parts[1])
                        target_chat_id_full = f'[{chat_id}] [{topic_id}]'
                except ValueError:
                    pass # Если разбор не удался, считать командой пользователя без ID

            if target_chat_id_full: # Если был разобран валидный ID цели
                chat_id_full = target_chat_id_full
    return chat_id_full


def extract_user_id(message: telebot.types.Message) -> int:
    """
    Extracts the user ID from the message text.

    Args:
        message: The message object.

    Returns:
        The user ID, or None if not found.
    """
    try:
        user_ids = utils.extract_large_ids(message.text)
        return user_ids[0] if user_ids else None
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:extract_user_id {error}\n\n{traceback_error}')
        return None


def check_blocked_user(id_: str, from_user_id: int, check_trottle = True):
    """Raises an exception if the user is blocked and should not be replied to"""
    for x in cfg.admins:
        if id_ == f'[{x}] [0]':
            return
    user_id = id_.replace('[','').replace(']','').split()[0]
    if check_trottle:
        if not request_counter.check_limit(user_id):
            # my_log.log2(f'tb:check_blocked_user: User {id_} is blocked for DDoS')
            raise Exception(f'user {user_id} in ddos stop list, ignoring')

    from_user_id = f'[{from_user_id}] [0]'
    if my_db.get_user_property(from_user_id, 'blocked'):
        # my_log.log2(f'tb:check_blocked_user: User {from_user_id} is blocked')
        raise Exception(f'user {from_user_id} in stop list, ignoring')

    if my_db.get_user_property(id_, 'blocked'):
        # my_log.log2(f'tb:check_blocked_user: User {id_} is blocked')
        raise Exception(f'user {user_id} in stop list, ignoring')


def is_admin_member(message: telebot.types.Message) -> bool:
    """Checks if the user is an admin member of the chat."""
    try:
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
            # if int(user_id) != int(chat_id):
            #     my_log.log2(f'User {user_id} is {member} of {chat_id}')
            return False
    except Exception as unexpected_error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:is_admin_member:{unexpected_error}\n\n{traceback_error}')


def is_for_me(message: telebot.types.Message) -> bool:
    """Checks who the command is addressed to, this bot or another one.

    /cmd@botname args

    Returns (True/False, 'the same command but without the bot name').
    If there is no bot name at all, assumes that the command is addressed to this bot.
    """
    try:
        chat_id_full = get_topic_id(message)
        cmd = message.text
        supch = my_db.get_user_property(chat_id_full, 'superchat') or 0
        is_private = message.chat.type == 'private' or supch

        # если не в привате, то есть в чате
        if not is_private and message.text:
            if message.text.startswith('/'):
                cmd_ = message.text.split(maxsplit=1)[0].strip()
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
    except Exception as unexpected_error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:is_for_me:{unexpected_error}\n\n{traceback_error}')


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
    try:
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
    except Exception as unexpected_error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:log_group_daemon:{unexpected_error}\n\n{traceback_error}')


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
    try:
        with LOG_GROUP_MESSAGES_LOCK:
            if _chat_full_id in DDOS_BLOCKED_USERS:
                return
            current_time = time.perf_counter_ns()
            value = (_type, _text, _chat_full_id, _chat_name, _m_ids, _message_chat_id, _message_message_id)
            if value not in LOG_GROUP_MESSAGES.values():
                LOG_GROUP_MESSAGES[current_time] = value
    except Exception as unexpected_error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:log_message_add:{unexpected_error}\n\n{traceback_error}')


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
        if not message:
            return

        if isinstance(message, telebot.types.Message) and hasattr(cfg, 'DO_NOT_LOG') and message.chat.id in cfg.DO_NOT_LOG:
            return
        if isinstance(message, list) and hasattr(cfg, 'DO_NOT_LOG') and message[0].chat.id in cfg.DO_NOT_LOG:
            return

        if not hasattr(cfg, 'LOGS_GROUP') or not cfg.LOGS_GROUP:
            return

        if isinstance(message, telebot.types.Message):
            chat_full_id = get_topic_id(message)
            chat_name = utils.get_username_for_log(message)
            # if utils.extract_user_id(chat_full_id) in DDOS_BLOCKED_USERS.keys():
            #     return

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

            # do not copy-log list of images if heavy load
            if len(LOG_GROUP_MESSAGES) > 30:
                return

            chat_full_id = get_topic_id(message[0])
            # if utils.extract_user_id(chat_full_id) in DDOS_BLOCKED_USERS.keys():
            #     return
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
    try:
        is_private = message.chat.type == 'private'

        # # banned users do nothing
        # chat_id_full = get_topic_id(message)
        # if my_db.get_user_property(chat_id_full, 'blocked'):
        #     return False

        if not (is_private or is_admin_member(message)):
            authorized_log(message)
            bot_reply_tr(message, "This command is only available to administrators")
            return False
        return authorized(message)
    except Exception as unexpected_error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:authorized_owner:{unexpected_error}\n\n{traceback_error}')
        return False


def authorized_admin(message: telebot.types.Message) -> bool:
    """if admin"""
    try:
        if message.from_user.id not in cfg.admins:
            authorized_log(message)
            bot_reply_tr(message, "This command is only available to administrators")
            my_log.log_auth(f'User {message.from_user.id} is not admin. Text: {message.text} Caption: {message.caption}')
            return False
            # raise Exception(f'User {message.from_user.id} is not admin')
        return authorized(message)
    except Exception as unexpected_error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:authorized_admin: {unexpected_error}\n\n{traceback_error}')
        return False


def authorized_callback(call: telebot.types.CallbackQuery) -> bool:
    # никаких проверок для админов
    try:
        if call.from_user.id in cfg.admins:
            return True

        chat_id_full = f'[{call.from_user.id}] [0]'
        # banned users do nothing
        if my_db.get_user_property(chat_id_full, 'blocked'):
            return False

        if not my_db.get_user_property(chat_id_full, 'chat_mode'):
            my_db.set_user_property(chat_id_full, 'chat_mode', cfg.chat_mode_default)

        # check for blocking and throttling
        try:
            check_blocked_user(chat_id_full, call.from_user.id, check_trottle=False)
        except:
            return False

        return True
    except Exception as unexpected_error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:authorized_callback:{unexpected_error}\n\n{traceback_error}')
        return False


def check_subscription(message: telebot.types.Message) -> bool:
    """проверка обязательной подписки на канал"""
    try:
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
            my_log.log2(f'tb:check_subscription: {error}\n\n{error_traceback}\n\n{u_id}')

        # Пользователь подписан, обновляем кэш
        subscription_cache[u_id] = current_time
        return True
    except Exception as unexpected_error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:check_subscription:{unexpected_error}\n\n{traceback_error}')
    return True


def chat_enabled(message: telebot.types.Message) -> bool:
    """check if chat is enabled"""
    try:
        chat_id_full = get_topic_id(message)
        if message.chat.type == 'private':
            return True
        return bool(my_db.get_user_property(chat_id_full, 'chat_enabled'))
    except Exception as unexpected_error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:chat_enabled:{unexpected_error}\n\n{traceback_error}')
    return False


def authorized(message: telebot.types.Message) -> bool:
    """
    Check if the user is authorized based on the given message.

    Parameters:
        message (telebot.types.Message): The message object containing the chat ID and user ID.

    Returns:
        bool: True if the user is authorized, False otherwise.
    """
    try:
        text = message.text or ''
        caption = message.caption or ''

        # full block, no logs
        chat_id_full = get_topic_id(message)
        from_user_id = f'[{message.from_user.id}] [0]'
        if my_db.get_user_property(chat_id_full, 'blocked_totally') or my_db.get_user_property(from_user_id, 'blocked_totally'):
            # my_log.log_auth(f'tb:authorized:1: User {chat_id_full} is blocked totally. Text: {text} Caption: {caption}')
            return False


        # ignore not allowed groups
        if hasattr(cfg, 'ALLOWED_GROUPS'):
            chat_id = message.chat.id
            if chat_id < 0:
                if chat_id not in cfg.ALLOWED_GROUPS:
                    # my_log.log_auth(f'tb:authorized:2: User {chat_id_full} is not in allowed groups. Text: {text} Caption: {caption}')
                    return False


        if not my_db.get_user_property(chat_id_full, 'chat_mode'):
            my_db.set_user_property(chat_id_full, 'chat_mode', cfg.chat_mode_default)

        # do not process commands to another bot /cmd@botname args
        if is_for_me(message)[0]:
            message.text = is_for_me(message)[1]
        else:
            # my_log.log_auth(f'tb:authorized:2: User {chat_id_full} is not authorized. Do not process commands to another bot /cmd@botname args. Text: {text} Caption: {caption}')
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
            my_log.log_auth(f'tb:authorized:3: user {chat_id_full} is blocked. Text: {text} Caption: {caption}')
            return False

        # if this chat was forcibly left (banned), then when trying to enter it immediately exit
        # I don't know how to do that, so I have to leave only when receiving any event
        if my_db.get_user_property(str(message.chat.id), 'auto_leave_chat'):
            try:
                bot.leave_chat(message.chat.id)
                my_log.log_auth('tb:authorized:4:leave_chat: auto leave ' + str(message.chat.id))
            except Exception as leave_chat_error:
                my_log.log_auth(f'tb:authorized:5:live_chat_error: {leave_chat_error}')
            return False

        my_db.set_user_property(chat_id_full, 'last_time_access', time.time())

        # trottle only messages addressed to me
        is_private = message.chat.type == 'private'
        supch = my_db.get_user_property(chat_id_full, 'superchat') or 0
        if supch == 1:
            is_private = True


        # # обновить клавиатуру старым юзерам
        # if message.chat.type == 'private':
        #     if chat_id_full not in NEW_KEYBOARD:
        #         bot_reply_tr(message, 'New keyboard installed.',
        #                     parse_mode='HTML',
        #                     disable_web_page_preview=True,
        #                     reply_markup=get_keyboard('start', message))
        #         NEW_KEYBOARD[chat_id_full] = True


        is_reply = message.reply_to_message and message.reply_to_message.from_user.id == BOT_ID


        bot_name = my_db.get_user_property(chat_id_full, 'bot_name') or BOT_NAME_DEFAULT

        bot_name_used = False
        if msg.startswith((f'{bot_name} ', f'{bot_name},', f'{bot_name}\n')):
            bot_name_used = True

        bot_name2 = f'@{_bot_name}'
        if msg.startswith((f'{bot_name2} ', f'{bot_name2},', f'{bot_name2}\n')):
            bot_name_used = True


        if message.text:
            if msg.startswith('.'):
                msg = msg[1:]


            if is_reply or is_private or bot_name_used:
                # check for blocking and throttling
                try:
                    check_blocked_user(chat_id_full, message.from_user.id)
                except:
                    my_log.log_auth(f'tb:authorized:6: User {chat_id_full} is blocked. Text: {text} Caption: {caption}')
                    return False
        else:
            try:
                if is_reply or is_private or bot_name_used:
                    check_blocked_user(chat_id_full, message.from_user.id)
            except:
                my_log.log_auth(f'tb:authorized:7: User {chat_id_full} is blocked. Text: {text} Caption: {caption}')
                return False

        if message.text:
            if not chat_enabled(message) and not message.text.startswith('/enable'):
                if message.text and message.text.startswith('/'):
                    bot_reply(message, f'Not enabled here. Use /enable@{_bot_name} to enable in this chat.')
                return False
        if not check_subscription(message):
            my_log.log_auth(f'tb:authorized:8: User {chat_id_full} is not subscribed. Text: {text} Caption: {caption}')
            return False

        # этого тут быть не должно но яхз что пошло не так, дополнительная проверка
        if my_db.get_user_property(chat_id_full, 'blocked'):
            my_log.log_auth(f'tb:authorized:9:  User {chat_id_full} is blocked')
            return False

        return True
    except Exception as unexpected_error:
        traceback_error = traceback.format_exc()
        my_log.log_auth(f'tb:authorized:10: {unexpected_error}\n\n{traceback_error}')
        return False


def authorized_log(message: telebot.types.Message) -> bool:
    """
    Only log and banned
    """
    try:
        # full block, no logs
        chat_id_full = get_topic_id(message)
        if my_db.get_user_property(chat_id_full, 'blocked_totally'):
            return False

        if not my_db.get_user_property(chat_id_full, 'chat_mode'):
            my_db.set_user_property(chat_id_full, 'chat_mode', cfg.chat_mode_default)

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
        if my_db.get_user_property(str(message.chat.id), 'auto_leave_chat'):
            try:
                bot.leave_chat(message.chat.id)
                my_log.log2('tb:leave_chat: auto leave ' + str(message.chat.id))
            except Exception as leave_chat_error:
                my_log.log2(f'tb:auth:live_chat_error: {leave_chat_error}')
            return False

        return True
    except Exception as unexpected_error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:authorized_log:{unexpected_error}\n\n{traceback_error}')
        return True # логи по умолчанию - ок


def bot_reply_tr(
    message: telebot.types.Message,
    msg: str,
    parse_mode: str = None,
    disable_web_page_preview: bool = None,
    reply_markup: telebot.types.InlineKeyboardMarkup = None,
    send_message: bool = False,
    not_log: bool = False,
    allow_voice: bool = False,
    save_cache: bool = True,
    help: str = ''):
    """Translate and send message from bot and log it
    send_message - send message or reply (ignored, used value from db)
    """
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)
        msg = tr(msg, lang, help, save_cache)
        bot_reply(message, msg, parse_mode, disable_web_page_preview, reply_markup, send_message, not_log, allow_voice)
    except Exception as unexpected_error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:bot_reply_tr:{unexpected_error}\n\n{traceback_error}')


def bot_reply(
    message: telebot.types.Message,
    msg: str,
    parse_mode: str = None,
    disable_web_page_preview: bool = None,
    reply_markup: telebot.types.InlineKeyboardMarkup = None,
    send_message: bool = False,
    not_log: bool = False,
    allow_voice: bool = False,
    collapse_text: bool = False
):
    """Send message from bot and log it
    send_message - send message or reply (ignored, used value from db)
    """
    try:
        if reply_markup is None:
            reply_markup = get_keyboard('hide', message)

        if not not_log:
            my_log.log_echo(message, msg)

        send_message = my_db.get_user_property(get_topic_id(message), 'send_message') or False

        if send_message:
            send_long_message(
                message,
                msg, 
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
                reply_markup=reply_markup,
                allow_voice=allow_voice,
                collapse_text=collapse_text
            )
        else:
            reply_to_long_message(
                message,
                msg, 
                parse_mode=parse_mode, 
                disable_web_page_preview=disable_web_page_preview,
                reply_markup=reply_markup,
                allow_voice=allow_voice,
                collapse_text=collapse_text
            )
    except Exception as unexpected_error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:bot_reply: {unexpected_error}\n\n{traceback_error}')


def get_config_msg(chat_id_full: str, lang: str) -> str:
    '''
    Формирует сообщение с конфигурацией бота
    '''
    try:
        role = my_db.get_user_property(chat_id_full, 'role') or ''
        if role:
            role_ = f'<blockquote expandable>{utils.bot_markdown_to_html(role)[:3000]}</blockquote>'
        else:
            role_ = ''
        bot_name = my_db.get_user_property(chat_id_full, 'bot_name') or BOT_NAME_DEFAULT
        MSG_CONFIG = f"""<b>{tr('Bot name:', lang)}</b> {bot_name} /name

<b>{tr('Bot style(role):', lang)}</b> /style {role_}

<b>{tr('User language:', lang)}</b> {tr(langcodes.Language.make(language=lang).display_name(language='en'), lang)} /lang"""
        return MSG_CONFIG
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:get_config_msg: {unknown}\n{traceback_error}')
        return tr('ERROR', lang)


# --- Helper functions for button creation ---

def _create_selection_button(
    text: str,
    value: str,
    current_value: str,
    callback_prefix: str
) -> telebot.types.InlineKeyboardButton:
    """Creates a button with a checkmark if it's the selected item."""
    prefix = '✅ ' if value == current_value else ''
    callback_data = 'switch_do_nothing' if value == current_value else f"{callback_prefix}{value}"
    return telebot.types.InlineKeyboardButton(f"{prefix}{text}", callback_data=callback_data)

def _create_toggle_button(
    text: str, # Expects pre-translated text
    is_enabled: bool,
    callback_base: str
) -> telebot.types.InlineKeyboardButton:
    """Creates a toggle button. Expects pre-translated text."""
    prefix = '✅' if is_enabled else '☑️'
    state_for_callback = 'disable' if is_enabled else 'enable'
    return telebot.types.InlineKeyboardButton(f"{prefix} {text}", callback_data=f"{callback_base}_{state_for_callback}")


# --- Builder functions for each config sub-menu (with translation context) ---

def _build_config_main_menu(lang: str) -> telebot.types.InlineKeyboardMarkup:
    """Builds the main config menu (Level 1)."""
    # Pre-cache all translations for this menu with context
    texts = {
        'models': tr('Модели', lang, help="UI button text for 'Models'. Short. E.g., 'Models', 'Modelle'"),
        'speech': tr('Речь', lang, help="UI button text for 'Speech' settings. Short. E.g., 'Speech', 'Sprache'"),
        'behavior': tr('Поведение', lang, help="UI button text for 'Behavior' settings. Short. E.g., 'Behavior', 'Verhalten'"),
        'close': tr('Закрыть', lang, help="UI button text for 'Close'. Short. E.g., 'Close', 'Schließen'"),
    }

    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    btn_models = telebot.types.InlineKeyboardButton(f"🧠 {texts['models']}", callback_data='config_models')
    btn_speech = telebot.types.InlineKeyboardButton(f"🔊 {texts['speech']}", callback_data='config_speech')
    btn_behavior = telebot.types.InlineKeyboardButton(f"⚙️ {texts['behavior']}", callback_data='config_behavior')
    btn_close = telebot.types.InlineKeyboardButton(f"🙈 {texts['close']}", callback_data='erase_answer')
    markup.row(btn_models, btn_speech)
    markup.row(btn_behavior, btn_close)
    return markup

def _build_config_models_menu(chat_id_full: str, lang: str) -> telebot.types.InlineKeyboardMarkup:
    """Builds the model selection menu (Level 2)."""
    texts = {
        'back': tr('Назад', lang, help="UI button text for 'Back'. Short. E.g., 'Back', 'Zurück'"),
    }

    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    chat_mode = my_db.get_user_property(chat_id_full, 'chat_mode') or cfg.chat_mode_default

    # Model names are proper nouns, not translated
    models = [
        ('Gemini 2.5 Flash', 'gemini25_flash'), ('Mistral', 'mistral'),
        ('GPT OSS 120b', 'gpt_oss'), ('Qwen 3', 'qwen3'),
        ('Gemini 2.5 Pro', 'gemini15'), ('Command A', 'cohere'),
        ('GPT-4o', 'gpt-4o'), ('GPT 4.1', 'gpt_41'),
        ('Qwen 3 Coder 480b', 'qwen3coder'), ('Gemini 2.0 flash', 'gemini'),
        ('DeepSeek V3', 'deepseek_v3'), ('OpenRouter', 'openrouter'),
        ('Cloacked', 'cloacked'), ('Gemini 2.5 Flash Lite', 'gemini-lite'),
    ]

    buttons = [_create_selection_button(name, val, chat_mode, 'select_') for name, val in models]
    for i in range(0, len(buttons), 2):
        markup.row(*buttons[i:i+2])

    markup.add(telebot.types.InlineKeyboardButton(f"⬅️ {texts['back']}", callback_data='config'))
    return markup

def _build_config_speech_menu(lang: str) -> telebot.types.InlineKeyboardMarkup:
    """Builds the speech settings navigation menu (Level 2)."""
    texts = {
        'tts': tr('Голос для ответа (TTS)', lang, help="UI button text. For 'Voice for response (TTS)'. Keep it clear."),
        'stt': tr('Распознавание речи (STT)', lang, help="UI button text. For 'Speech recognition (STT)'. Keep it clear."),
        'back': tr('Назад', lang, help="UI button text for 'Back'. Short. E.g., 'Back', 'Zurück'"),
    }

    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    btn_tts = telebot.types.InlineKeyboardButton(f"🗣️ {texts['tts']}", callback_data='config_tts')
    btn_stt = telebot.types.InlineKeyboardButton(f"🎤 {texts['stt']}", callback_data='config_stt')
    btn_back = telebot.types.InlineKeyboardButton(f"⬅️ {texts['back']}", callback_data='config')
    markup.add(btn_tts, btn_stt, btn_back)
    return markup

def _build_config_stt_menu(chat_id_full: str, lang: str) -> telebot.types.InlineKeyboardMarkup:
    """Builds the STT engine selection menu (Level 3)."""
    texts = {
        'back': tr('Назад', lang, help="UI button text for 'Back'. Short. E.g., 'Back', 'Zurück'"),
    }

    markup = telebot.types.InlineKeyboardMarkup(row_width=3)
    current_engine = my_db.get_user_property(chat_id_full, 'speech_to_text_engine') or my_stt.DEFAULT_STT_ENGINE

    # Engine names are proper nouns, not translated
    engines = [
        ("Auto", "auto"), ("Whisper", "whisper"), ("Gemini", "gemini"),
        ("Voxtral", "voxtral"), ("Google", "google"), ("AssemblyAI", "assembly.ai"),
        ("Deepgram", "deepgram_nova3")
    ]

    buttons = [_create_selection_button(name, val, current_engine, 'switch_speech_to_text_') for name, val in engines]
    markup.row(*buttons[0:3])
    markup.row(*buttons[3:6])
    markup.row(buttons[6])
    markup.add(telebot.types.InlineKeyboardButton(f"⬅️ {texts['back']}", callback_data='config_speech'))
    return markup

def _build_config_tts_menu(chat_id_full: str, lang: str) -> telebot.types.InlineKeyboardMarkup:
    """Builds the complete TTS voice selection menu (Level 3)."""
    # Pre-cache all translations for this menu
    texts = {
        'ms_female': tr('MS жен.', lang, help="UI button text. Very short, for 'Microsoft female voice'. E.g., 'MS fem.'"),
        'ms_male': tr('MS муж.', lang, help="UI button text. Very short, for 'Microsoft male voice'. E.g., 'MS masc.'"),
        'voice_prompt': tr('📢Голос:', lang, help="UI button label prefix for 'Voice:'. Keep it short. E.g., 'Voice:'"),
        'voice_only': tr('Только голос', lang, help="UI button toggle for 'Voice only' mode. E.g., 'Voice only'"),
        'back': tr('Назад', lang, help="UI button text for 'Back'. Short. E.g., 'Back', 'Zurück'"),
    }

    markup = telebot.types.InlineKeyboardMarkup(row_width=4)
    current_voice_key = my_db.get_user_property(chat_id_full, 'tts_gender') or 'female'
    current_voice_provider_cb = f'tts_{current_voice_key}'

    gemini_voices_dict = {f"tts_gemini_{voice}": "Gemini" for voice in my_gemini_tts.POSSIBLE_VOICES}

    voice_providers = {
        'tts_female': texts['ms_female'],
        'tts_male': texts['ms_male'],
        'tts_google_female': 'Google',
        **{f'tts_openai_{v}': 'OpenAI' for v in ['alloy', 'ash', 'ballad', 'coral', 'echo', 'fable', 'onyx', 'nova', 'sage', 'shimmer', 'verse']},
        **gemini_voices_dict
    }

    voice_title = voice_providers.get(current_voice_provider_cb, texts['ms_female'])

    btn_provider = telebot.types.InlineKeyboardButton(f"{texts['voice_prompt']} {voice_title}", callback_data=current_voice_provider_cb)
    is_voice_only = my_db.get_user_property(chat_id_full, 'voice_only_mode')
    # CORRECT CALL with 3 arguments
    btn_voice_only = _create_toggle_button(texts['voice_only'], is_voice_only, 'voice_only_mode')
    markup.row(btn_provider, btn_voice_only)

    filler = telebot.types.InlineKeyboardButton("---", callback_data='switch_do_nothing')
    markup.row(filler)

    if voice_title == 'OpenAI':
        openai_voices = ['alloy', 'ash', 'ballad', 'coral', 'echo', 'fable', 'onyx', 'nova', 'sage', 'shimmer', 'verse']
        current_selection = current_voice_key.replace('openai_', '')
        buttons = [_create_selection_button(v.capitalize(), v, current_selection, 'switch_openai_') for v in openai_voices]
        for i in range(0, len(buttons), 4):
            markup.row(*buttons[i:i+4])
    elif voice_title == 'Gemini':
        current_selection = current_voice_key.replace('gemini_', '')
        buttons = [_create_selection_button(v, v, current_selection, 'switch_gemini_') for v in sorted(my_gemini_tts.POSSIBLE_VOICES)]
        for i in range(0, len(buttons), 3):
            markup.row(*buttons[i:i+3])

    markup.add(telebot.types.InlineKeyboardButton(f"⬅️ {texts['back']}", callback_data='config_speech'))
    return markup

def _build_config_behavior_menu(message: telebot.types.Message, chat_id_full: str, lang: str) -> telebot.types.InlineKeyboardMarkup:
    """Builds the bot behavior toggles menu (Level 2)."""
    texts = {
        'chat_buttons': tr('Чат-кнопки', lang, help="UI button toggle. For 'Chat buttons' visibility. E.g., 'Chat buttons'"),
        'other_notification': tr('🔔 Other notification', lang, help="UI button toggle. For an alternative notification style. Keep concise."),
        'voice_to_text': tr('📝 Voice to text mode', lang, help="UI button toggle. For 'Voice to text mode'. E.g., 'Transcription mode'"),
        'do_not_reply': tr('↩️ Do not reply', lang, help="UI button toggle. For a mode where the bot doesn't reply. E.g., 'Do not reply'"),
        'auto_reply': tr('🤖 Автоответы в чате', lang, help="UI button toggle. For 'Auto-replies in chat'. E.g., 'Auto-replies'"),
        'memory': tr('Память (контекст)', lang, help="UI button toggle. For 'Memory'/'History' functionality. E.g., 'Memory (context)', 'Gedächtnis (Kontext)'"),
        'back': tr('Назад', lang, help="UI button text for 'Back'. Short. E.g., 'Back', 'Zurück'"),
    }

    markup = telebot.types.InlineKeyboardMarkup(row_width=2)

    # CORRECT CALLS with 3 arguments
    is_kbd_enabled = not my_db.get_user_property(chat_id_full, 'disabled_kbd')
    btn_kbd = _create_toggle_button(texts['chat_buttons'], is_kbd_enabled, 'chat_kbd')

    action_style_enabled = bool(my_db.get_user_property(chat_id_full, 'action_style'))
    btn_action = _create_toggle_button(texts['other_notification'], action_style_enabled, 'action_style')
    markup.row(btn_kbd, btn_action)

    is_transcribe_only = my_db.get_user_property(chat_id_full, 'transcribe_only')
    btn_transcribe = _create_toggle_button(texts['voice_to_text'], is_transcribe_only, 'transcribe_only_chat')

    is_no_reply = my_db.get_user_property(chat_id_full, 'send_message')
    btn_reply = _create_toggle_button(texts['do_not_reply'], is_no_reply, 'send_message_chat_switch')
    markup.row(btn_transcribe, btn_reply)

    default_size = 1000
    # Check if memory is enabled. It's enabled if the size is not explicitly 0.
    # The default size (e.g., 1000) means it's enabled.
    mem_state = my_db.get_user_property(chat_id_full, 'max_history_size')
    if mem_state is None: mem_state = default_size
    is_memory_enabled = mem_state != 0
    btn_memory = _create_toggle_button(texts['memory'], is_memory_enabled, 'histsize_toggle')
    markup.row(btn_memory)

    if message.chat.type != 'private':
        is_superchat = bool(my_db.get_user_property(chat_id_full, 'superchat'))
        btn_superchat = _create_toggle_button(texts['auto_reply'], is_superchat, 'admin_chat')
        markup.add(btn_superchat)

    markup.add(telebot.types.InlineKeyboardButton(f"⬅️ {texts['back']}", callback_data='config'))
    return markup


def get_keyboard(kbd: str, message: telebot.types.Message, flag: str = '') -> telebot.types.InlineKeyboardMarkup:
    """создает и возвращает клавиатуру по текстовому описанию
    'chat' - клавиатура для чата
    'mem' - клавиатура для команды mem, с кнопками Забудь и Скрой
    'hide' - клавиатура с одной кнопкой Скрой
    """
    try:
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
        elif kbd == 'voicechat':
            keyboard = telebot.types.ReplyKeyboardMarkup(
                row_width=1,
                resize_keyboard=True,
                one_time_keyboard=True
                )
            webAppTest = telebot.types.WebAppInfo("https://theurs.github.io/test/dollar.html") #создаем webappinfo - формат хранения url
            one_butt = telebot.types.KeyboardButton(text="Голосовой чат", web_app=webAppTest) #создаем кнопку типа webapp
            keyboard.add(one_butt) #добавляем кнопки в клавиатуру
            return keyboard #возвращаем клавиатуру
        elif kbd.startswith('pay_stars_'):
            amount = int(kbd.split('_')[-1])
            keyboard = telebot.types.InlineKeyboardMarkup()
            button1 = telebot.types.InlineKeyboardButton(text=tr("Donate stars amount:", lang) + ' ' + str(amount), pay = True)
            keyboard.add()
            return keyboard
        elif kbd == 'donate_stars':
            keyboard = telebot.types.InlineKeyboardMarkup(row_width=1)
            button1 = telebot.types.InlineKeyboardButton(text=tr("Donate 50 stars", lang), callback_data = "buy_stars_50")
            button2 = telebot.types.InlineKeyboardButton(text=tr("Donate 100 stars", lang), callback_data = "buy_stars_100")
            button3 = telebot.types.InlineKeyboardButton(text=tr("Donate 200 stars", lang), callback_data = "buy_stars_200")
            button4 = telebot.types.InlineKeyboardButton(text=tr("Donate custom amount of stars", lang), callback_data = "buy_stars_0")
            keyboard.add(button1, button2, button3, button4)
            return keyboard

        elif kbd == 'image_prompt':
            markup  = telebot.types.InlineKeyboardMarkup(row_width=2)
            button1 = telebot.types.InlineKeyboardButton(tr("Describe the image", lang), callback_data='image_prompt_describe')
            button2 = telebot.types.InlineKeyboardButton(tr("Extract text", lang), callback_data='image_prompt_text')
            button2_1 = telebot.types.InlineKeyboardButton(tr("Read aloud text", lang), callback_data='image_prompt_text_tts')
            button2_2 = telebot.types.InlineKeyboardButton(tr("Translate all text from image", lang), callback_data='image_prompt_text_tr')
            button2_3 = telebot.types.InlineKeyboardButton(tr("OCR", lang), callback_data='image_prompt_ocr')
            button3 = telebot.types.InlineKeyboardButton(tr("Create image generation prompt", lang), callback_data='image_prompt_generate')
            button4 = telebot.types.InlineKeyboardButton(tr("Solve the problem shown in the image", lang), callback_data='image_prompt_solve')
            button4_2 = telebot.types.InlineKeyboardButton(tr("Read QRCODE", lang), callback_data='image_prompt_qrcode')
            button6 = telebot.types.InlineKeyboardButton(tr("Cancel", lang), callback_data='erase_answer')
            if chat_id_full in UNCAPTIONED_PROMPTS:
                button5 = telebot.types.InlineKeyboardButton(tr("Repeat my last request", lang), callback_data='image_prompt_repeat_last')
                if chat_id_full in UNCAPTIONED_IMAGES and (my_qrcode.get_text(UNCAPTIONED_IMAGES[chat_id_full][1])):
                    markup.row(button1)
                    markup.row(button2, button2_1)
                    markup.row(button2_2, button2_3)
                    markup.row(button3)
                    markup.row(button4)
                    markup.row(button4_2)
                    markup.row(button5)
                    markup.row(button6)
                else:
                    markup.row(button1)
                    markup.row(button2, button2_1)
                    markup.row(button2_2, button2_3)
                    markup.row(button3)
                    markup.row(button4)
                    markup.row(button5)
                    markup.row(button6)
            else:
                if chat_id_full in UNCAPTIONED_IMAGES and (my_qrcode.get_text(UNCAPTIONED_IMAGES[chat_id_full][1])):
                    markup.row(button1)
                    markup.row(button2, button2_1)
                    markup.row(button2_2)
                    markup.row(button3)
                    markup.row(button4)
                    markup.row(button4_2)
                    markup.row(button6)
                else:
                    markup.row(button1)
                    markup.row(button2, button2_1)
                    markup.row(button2_2)
                    markup.row(button3)
                    markup.row(button4)
                    markup.row(button6)
            return markup

        elif kbd == 'download_saved_text':
            markup  = telebot.types.InlineKeyboardMarkup(row_width=2)
            button1 = telebot.types.InlineKeyboardButton('⬇️ ' + tr("Скачать", lang), callback_data='download_saved_text')
            button2 = telebot.types.InlineKeyboardButton('🗑️ ' + tr("Удалить", lang), callback_data='delete_saved_text')
            button3 = telebot.types.InlineKeyboardButton('❌ ' + tr("Отмена", lang), callback_data='cancel_command')
            markup.add(button1, button2)
            markup.add(button3)
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

        elif kbd == 'command_mode_transcribe':
            markup  = telebot.types.InlineKeyboardMarkup()
            button1 = telebot.types.InlineKeyboardButton(tr("Отмена", lang), callback_data='cancel_command')
            if hasattr(cfg, 'UPLOADER_URL') and cfg.UPLOADER_URL:
                button2 = telebot.types.InlineKeyboardButton(tr("Too big file?", lang), url=cfg.UPLOADER_URL)
                markup.add(button1)
                markup.add(button2)
            else:
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

        elif kbd in ('chat', 'translate'):
            if my_db.get_user_property(chat_id_full, 'disabled_kbd'):
                return None
            markup  = telebot.types.InlineKeyboardMarkup(row_width=5)
            button0 = telebot.types.InlineKeyboardButton("➡", callback_data='continue_gpt')
            button1 = telebot.types.InlineKeyboardButton('♻️', callback_data='general_reset')
            button2 = telebot.types.InlineKeyboardButton("🙈", callback_data='erase_answer')
            button3 = telebot.types.InlineKeyboardButton("📢", callback_data='tts')
            button4 = telebot.types.InlineKeyboardButton(lang, callback_data='translate_chat')
            markup.add(button0, button1, button2, button3, button4)
            return markup
        elif kbd.startswith('search_pics_'):
            markup  = telebot.types.InlineKeyboardMarkup(row_width=5)
            button0 = telebot.types.InlineKeyboardButton('📸', callback_data=f'search_pics_{kbd[12:]}')
            button1 = telebot.types.InlineKeyboardButton("♻️", callback_data='general_reset')
            button2 = telebot.types.InlineKeyboardButton("🙈", callback_data='erase_answer')
            button3 = telebot.types.InlineKeyboardButton("📢", callback_data='tts')
            button4 = telebot.types.InlineKeyboardButton(lang, callback_data='translate_chat')
            markup.add(button0, button1, button2, button3, button4)
            return markup


        elif kbd == 'config':
            return _build_config_main_menu(lang)
        elif kbd == 'config_models':
            return _build_config_models_menu(chat_id_full, lang)
        elif kbd == 'config_speech':
            return _build_config_speech_menu(lang)
        elif kbd == 'config_stt':
            return _build_config_stt_menu(chat_id_full, lang)
        elif kbd == 'config_tts':
            return _build_config_tts_menu(chat_id_full, lang) # Note: The full logic for this is complex
        elif kbd == 'config_behavior':
            return _build_config_behavior_menu(message, chat_id_full, lang)


        else:
            traceback_error = traceback.format_exc()
            raise Exception(f"Неизвестная клавиатура '{kbd}'\n\n{traceback_error}")
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:get_keyboard: {unknown}\n\n{traceback_error}')


@bot.callback_query_handler(func=authorized_callback)
@async_run
def callback_inline_thread(call: telebot.types.CallbackQuery):
    """Обработчик клавиатуры"""
    my_cmd_callback.callback_inline_thread(
        call=call,
        # Core objects
        bot=bot,
        # Global state dictionaries
        COMMAND_MODE=COMMAND_MODE,
        TTS_LOCKS=TTS_LOCKS,
        GOOGLE_LOCKS=GOOGLE_LOCKS,
        SEARCH_PICS=SEARCH_PICS,
        UNCAPTIONED_PROMPTS=UNCAPTIONED_PROMPTS,
        UNCAPTIONED_IMAGES=UNCAPTIONED_IMAGES,
        # Helper functions and classes
        get_topic_id=get_topic_id,
        get_lang=get_lang,
        tr=tr,
        get_config_msg=get_config_msg,
        bot_reply=bot_reply,
        bot_reply_tr=bot_reply_tr,
        get_keyboard=get_keyboard,
        add_to_bots_mem=add_to_bots_mem,
        log_message=log_message,
        send_document=send_document,
        send_media_group=send_media_group,
        is_admin_member=is_admin_member,
        ShowAction=ShowAction,
        # Command handler functions
        reset_=reset_,
        process_image_stage_2=process_image_stage_2,
        echo_all=echo_all,
        tts=tts,
        language=language,
    )


# Обработчик запросов перед оплатой
@bot.pre_checkout_query_handler(func=lambda query: True)
def handle_pre_checkout_query(pre_checkout_query: telebot.types.PreCheckoutQuery):
    try:
        bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
    except Exception as error:
        chat_id_full = get_topic_id(pre_checkout_query)
        lang = get_lang(chat_id_full, pre_checkout_query)
        my_log.log_donate(f'tb:handle_pre_checkout_query: {error}\n\n{str(pre_checkout_query)}')
        msg = tr("❌ Error while processing payment.", lang) + "\n\n" + str(error)
        bot_reply(pre_checkout_query.from_user.id, msg)


# Обработчик успешных платежей
@bot.message_handler(content_types=['successful_payment'])
def handle_successful_payment(message: telebot.types.Message):
    try:
        chat_full_id = get_topic_id(message)
        lang = get_lang(chat_full_id, message)
        user_id = message.from_user.id
        payment_id = message.successful_payment.provider_payment_charge_id
        amount = message.successful_payment.total_amount
        currency = message.successful_payment.currency

        # Сохранение информации о платеже в базе данных
        # save_payment(user_id, payment_id, amount, currency)
        my_log.log_donate(f'{user_id} {payment_id} {amount} {currency}')
        user_stars = my_db.get_user_property(chat_full_id, 'telegram_stars') or 0
        user_stars += amount
        my_db.set_user_property(chat_full_id, 'telegram_stars', user_stars)

        # Отправка подтверждающего сообщения о покупке
        msg = f'{tr("✅ Донат принят.", lang)} [{amount}]'
        try:
            bot_reply(message, msg)
        except Exception as error:
            my_log.log_donate(f'tb:handle_successful_payment: {error}\n\n{str(message)}')
            bot.send_message(message.chat.id, msg)

    except Exception as error:
        chat_full_id = get_topic_id(message)
        lang = get_lang(chat_full_id, message)
        traceback_error = traceback.format_exc()
        my_log.log_donate(f'tb:handle_successful_payment: {error}\n\n{str(message)}\n\n{traceback_error}')
        msg = tr("❌ Error while processing payment.", lang) + "\n\n" + str(error)
        bot.send_message(message.chat.id, msg)


# Обработчик команды /paysupport
@bot.message_handler(commands=['paysupport'])
def handle_pay_support(message):
    try:
        bot_reply_tr(message, 'Use /report command for contact human')
    except Exception as error:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)
        my_log.log_donate(f'tb:handle_pay_support: {error}\n\n{str(message)}')
        msg = tr("❌ Error while processing payment.", lang) + "\n\n" + str(error)
        bot.send_message(message.chat.id, msg)


def transcribe_file(data: bytes, file_name: str, message: telebot.types.Message):
    '''
    Транскрибирует аудио файл, отправляет в ответ субтитры, снимает 25 звезд за каждый час звука
    Если аудио короткое, до 5 минут то не снимает звезды

    Args: 
        data: Аудио файл в байтовом формате
        file_name: Название файла
        message: Сообщение
    '''
    try:
        bot_reply_tr(message, 'Processing audio file...')
        with ShowAction(message, 'typing', 15):
            if isinstance(data, str):
                data = utils.download_audio_file_as_bytes(data)
                if not data:
                    bot_reply_tr(message, 'Audio file not found')
                    return

            chat_id_full = get_topic_id(message)
            lang = get_lang(chat_id_full, message)

            text = my_stt.stt(
                input_file=data,
                lang=lang,
                chat_id=chat_id_full
            )

            if text:
                # send captions
                kbd = get_keyboard('hide', message) if message.chat.type != 'private' else None
                try:
                    m3 = send_document(
                        message,
                        message.chat.id,
                        text.encode('utf-8', 'replace'),
                        reply_to_message_id=message.message_id,
                        caption = tr(f'Transcription generated at @{_bot_name}', lang),
                        reply_markup=kbd,
                        parse_mode='HTML',
                        disable_notification = True,
                        visible_file_name = file_name + '.txt',
                        message_thread_id = message.message_thread_id,
                    )
                    log_message(m3)

                    # сохранить как файл для дальнейших вопросов по нему субтитры или srt или vtt или чистый текст
                    saved_text = text

                    my_db.set_user_property(chat_id_full, 'saved_file_name', f'transcribed audio file: captions_{utils.get_full_time().replace(":", "-")}.txt')
                    my_db.set_user_property(chat_id_full, 'saved_file', saved_text)

                    msg = tr('Transcription created successfully, use /ask command to query your text.', lang)

                    COMMAND_MODE[chat_id_full] = ''

                    bot_reply(message, msg)

                except Exception as error_transcribe:
                    my_log.log2(f'tb:handle_voice:transcribe: {error_transcribe}')
                    bot_reply_tr(message, 'Error, try again or cancel.', reply_markup=get_keyboard('command_mode',message))

            else:
                bot_reply_tr(message, 'Error, try again or cancel.', reply_markup=get_keyboard('command_mode',message))

    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:transcribe: {error}\n\n{str(message)}\n\n{traceback_error}')
        bot_reply_tr(message, 'Error, try again or cancel.', reply_markup=get_keyboard('command_mode',message))


@bot.message_handler(content_types=['voice', 'video', 'video_note', 'audio'], func=authorized)
@async_run
def handle_voice(message: telebot.types.Message):
    """
    Обрабатывает одиночные и сгруппированные аудио/видео сообщения.
    - Если активен режим /transcribe, обрабатывает файл немедленно.
    - В ином случае, собирает все приходящие файлы в группу, транскрибирует
      и отправляет в ЛЛМ в едином XML-подобном формате.
    """
    my_cmd_voice.handle_voice(
        message=message,

        # Core objects and constants
        bot=bot,
        BOT_ID=BOT_ID,
        _bot_name=_bot_name,
        BOT_NAME_DEFAULT=BOT_NAME_DEFAULT,

        # Global state dictionaries
        COMMAND_MODE=COMMAND_MODE,
        CHECK_DONATE_LOCKS=CHECK_DONATE_LOCKS,
        MESSAGE_QUEUE_AUDIO_GROUP=MESSAGE_QUEUE_AUDIO_GROUP,

        # Helper functions and classes
        get_topic_id=get_topic_id,
        get_lang=get_lang,
        tr=tr,
        bot_reply=bot_reply,
        bot_reply_tr=bot_reply_tr,
        get_keyboard=get_keyboard,
        transcribe_file=transcribe_file,
        ShowAction=ShowAction,

        # Command handler functions
        echo_all=echo_all,
    )


@bot.message_handler(content_types = ['location',], func=authorized)
@async_run
def handle_location(message: telebot.types.Message):
    """Если юзер прислал геолокацию"""
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        COMMAND_MODE[chat_id_full] = ''

        # проверка на подписку
        if not my_subscription.check_donate(message, chat_id_full, lang, COMMAND_MODE, CHECK_DONATE_LOCKS, BOT_ID, tr, bot_reply, get_keyboard):
            return

        message.text = f'{tr("User sent a location to your telegram bot:", lang)} {str(message.location)}'
        handle_photo_and_text(message)

    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:handle_location: {unknown}\n{traceback_error}')


@bot.message_handler(content_types = ['contact',], func=authorized)
@async_run
def handle_contact(message: telebot.types.Message):
    """Если юзер прислал контакст"""
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        COMMAND_MODE[chat_id_full] = ''

        # проверка на подписку
        if not my_subscription.check_donate(message, chat_id_full, lang, COMMAND_MODE, CHECK_DONATE_LOCKS, BOT_ID, tr, bot_reply, get_keyboard):
            return

        message.text = f'{tr("User sent a contact to your telegram bot:", lang)} {str(message.contact)}'
        handle_photo_and_text(message)

    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:handle_contact: {unknown}\n{traceback_error}')


def image_info(image_bytes: bytes, lang: str = "ru") -> str:
    """Extracts information from an image and formats it as a string.

    Args:
        image_bytes: The image data as bytes.
        lang: The language code for output labels. Defaults to 'ru'.

    Returns:
        A string containing image information. If an error occurs during 
        processing, returns an error message.
    """
    try:
        image = PIL.Image.open(io.BytesIO(image_bytes))

        # Translate labels using the provided language.
        size_label = tr("Size", lang)

        info_str = ''
        info_str += f"{size_label}: {image.width}x{image.height}\n"

        return info_str.strip()
    except Exception as e:
        error_message = tr("Error", lang)
        return f"{error_message}: {e}"


def proccess_image(
    chat_id_full: str,
    image: bytes,
    message: telebot.types.Message,
    original_images: Optional[List[bytes]] = None
) -> None:
    '''The user sent an image without a caption. Ask the user what to do with it,
    save the image, and display a keyboard with options.

    Args:
        chat_id_full: The full chat ID string.
        image: The main image data as bytes (single image or collage).
        message: The Telegram message object.
        original_images: A list of original image bytes for media groups.
    '''
    try:
        with UNCAPTIONED_IMAGES_LOCK:
            current_date = time.time()

            # If original_images is not provided, it's a single image.
            # Use the main 'image' as a list of one.
            images_to_store = original_images if original_images else [image]

            # Store the main image (for analysis) and the list of originals (for editing).
            UNCAPTIONED_IMAGES[chat_id_full] = (current_date, image, images_to_store)

            # Limit the storage to UNCAPTIONED_IMAGES_MAX uncaptioned images.
            if len(UNCAPTIONED_IMAGES) > UNCAPTIONED_IMAGES_MAX:
                sorted_images = sorted(UNCAPTIONED_IMAGES.items(), key=lambda item: item[1][0])
                user_ids_to_delete = [user_id for user_id, _ in sorted_images[:len(UNCAPTIONED_IMAGES) - UNCAPTIONED_IMAGES_MAX]]
                for user_id in user_ids_to_delete:
                    try:
                        UNCAPTIONED_IMAGES.pop(user_id, None)
                    except KeyError:
                        pass

            COMMAND_MODE[chat_id_full] = 'image_prompt'

            user_prompt = ''
            if chat_id_full in UNCAPTIONED_PROMPTS:
                user_prompt = UNCAPTIONED_PROMPTS[chat_id_full]

            lang = get_lang(chat_id_full, message)
            msg = tr('What would you like to do with this image?\n\nStart query with symbol ! to edit picture, Example: !change the color of the clothes to red', lang)
            # Use the main image (collage or single) for info display.
            msg += '\n\n' + image_info(image, lang)
            if user_prompt:
                msg += '\n\n' + tr('Repeat my last request', lang) + ':\n\n' + utils.truncate_text(user_prompt)

            bot_reply(message, msg, parse_mode = 'HTML', disable_web_page_preview=True, reply_markup = get_keyboard('image_prompt', message))
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:proccess_image: {unknown}\n{traceback_error}')


def process_image_stage_2(
    image_prompt: str,
    chat_id_full: str,
    lang: str,
    message: telebot.types.Message,
    model: str = '',
    temp: float = 1,
    timeout: int = 120
) -> None:
    '''Processes the user's chosen action for the uncaptioned image.

    Args:
        image_prompt: The user's chosen action or prompt.
        chat_id_full: The full chat ID string.
        lang: The user's language code.
        message: The Telegram message object.
        model: Model to use.
    '''
    try:
        with ShowAction(message, "typing"): # Display "typing" action while processing.
            default_prompts = (
                tr(my_init.PROMPT_DESCRIBE, lang),
                tr(my_init.PROMPT_COPY_TEXT, lang),
                tr(my_init.PROMPT_COPY_TEXT_TTS, lang),
                tr(my_init.PROMPT_COPY_TEXT_TR, lang),
                tr(my_init.PROMPT_REPROMPT, lang),
                tr(my_init.PROMPT_SOLVE, lang),
                tr(my_init.PROMPT_QRCODE, lang),
            )

            if not any(default_prompt in image_prompt for default_prompt in default_prompts):
                UNCAPTIONED_PROMPTS[chat_id_full] = image_prompt

            if chat_id_full in UNCAPTIONED_IMAGES:
                # Unpack the new data structure.
                _, collage_bytes, originals_list = UNCAPTIONED_IMAGES[chat_id_full]

                # Decide which image data to use based on the prompt.
                # Use originals list for editing (!), collage for analysis.
                image_data_to_use = originals_list if image_prompt.strip().startswith('!') else collage_bytes

                text = img2txt(
                    text=image_data_to_use, # This can be bytes or list[bytes] now.
                    lang=lang,
                    chat_id_full=chat_id_full,
                    query=image_prompt,
                    model=model,
                    temperature=temp,
                    timeout=timeout,
                    images=originals_list # Always pass the full list for context if needed.
                )

                if text:
                    if isinstance(text, str):
                        bot_reply(
                            message,
                            utils.bot_markdown_to_html(text),
                            disable_web_page_preview=True,
                            parse_mode='HTML',
                            reply_markup=get_keyboard('chat', message),
                        )
                        if image_prompt == tr(my_init.PROMPT_COPY_TEXT_TTS, lang):
                            message.text = f'/tts {my_gemini3.detect_lang(text, chat_id_full=chat_id_full)} {text}'
                            tts(message)
                    elif isinstance(text, bytes):
                        m = send_photo(
                            message,
                            message.chat.id,
                            text,
                            disable_notification=True,
                            reply_to_message_id=message.message_id,
                            reply_markup=get_keyboard('hide', message),
                        )
                        log_message(m)
                        return

                    # Check for and send any files generated by skills
                    send_all_files_from_storage(message, chat_id_full)

                else:
                    bot_reply_tr(message, "I'm sorry, I wasn't able to process that image or understand your request.")
            else:
                bot_reply_tr(message, 'The image has already faded from my memory.')
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:process_image_stage_2: {unknown}\n{traceback_error}')


def process_wg_config(text: str, message: telebot.types.Message) -> bool:
    '''
    Проверяет является ли текст конфигом ваиргарда, если да то
    применяет его и возвращает True иначе False
    Конфиг нужен для бинга в основном.
    '''
    try:
        values: dict[str, str | None] = {
            "Address": None,
            "PrivateKey": None,
            "publickey": None,
            "Endpoint": None,
        }
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            for key in values:
                # Используем регулярное выражение для поиска ключа с игнорированием регистра и пробелов
                match = re.match(rf"^\s*{key}\s*=\s*(.+?)\s*$", line, re.IGNORECASE)
                if match:
                    values[key] = match.group(1)
                    break  # Переходим к следующей строке, т.к. ключ уже найден для этой строки

        if not all(values.values()):
            return False

        AllowedIPs = '2.17.0.0/16, 2.16.0.0/16, 2.18.0.0/16, 2.19.0.0/16, 2.21.0.0/16, 2.22.0.0/16, 2.23.0.0/16,'\
                    ' 3.128.0.0/9, 13.104.0.0/14, 13.96.0.0/13, 13.64.0.0/11, 23.62.0.0/16, 44.192.0.0/11, 54.92.128.0/17,'\
                    ' 54.160.0.0/11, 54.208.0.0/13, 54.192.0.0/12, 54.220.0.0/15, 54.216.0.0/14, 54.144.0.0/12,'\
                    ' 54.64.0.0/11, 62.115.0.0/16, 64.233.0.0/16, 80.239.0.0/16, 88.221.0.0/16, 95.100.0.0/16,'\
                    ' 95.101.0.0/16, 104.110.0.0/16, 139.45.0.0/16, 142.250.0.0/15, 172.253.0.0/16, 172.217.0.0/16,'\
                    ' 173.194.0.0/16, 204.79.0.0/16, 209.85.0.0/16, 216.58.0.0/16, 3.209.228.0/16,'\
                    ' 34.195.101.0/16, 44.214.233.0/16, 3.216.231.0/16, 52.22.132.0/16, 44.208.13.0/16,'\
                    ' 173.194.0.0/16, 64.233.0.0/16, 34.64.0.0/10'

        Address = values['Address']
        PrivateKey = values['PrivateKey']
        publickey = values['publickey']
        Endpoint = values['Endpoint']

        target_wg1 = '/etc/wireguard/wg1.conf'
        target_body = f'''
[Interface]
Address = {Address}

PrivateKey = {PrivateKey}
[Peer]
publickey={publickey}

Endpoint = {Endpoint}

AllowedIPs = {AllowedIPs}
'''
        cmd = 'sudo systemctl restart wg-quick@wg1.service'

        with open(target_wg1, 'w') as f:
            f.write(target_body)

        with subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding=utils.get_codepage()) as proc:
            stdout, stderr = proc.communicate()
        out = stdout + '\n\n' + stderr
        out = f'```cmd\n{out}```'
        bot_reply(message, utils.bot_markdown_to_html(out), parse_mode='HTML')

        return True
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:process_wg_config: {unknown}\n{traceback_error}')
        return False


@bot.message_handler(content_types = ['document',], func=authorized)
@async_run
def handle_document(message: telebot.types.Message):
    """Обработчик документов"""
    my_cmd_document.handle_document(
        message=message,

        # Core objects and constants
        bot=bot,
        BOT_ID=BOT_ID,
        _bot_name=_bot_name,
        BOT_NAME_DEFAULT=BOT_NAME_DEFAULT,

        # Global state dictionaries
        COMMAND_MODE=COMMAND_MODE,
        DOCUMENT_LOCKS=DOCUMENT_LOCKS,
        CHECK_DONATE_LOCKS=CHECK_DONATE_LOCKS,
        FILE_GROUPS=FILE_GROUPS,

        # Helper functions and classes
        get_topic_id=get_topic_id,
        get_lang=get_lang,
        tr=tr,
        bot_reply=bot_reply,
        bot_reply_tr=bot_reply_tr,
        get_keyboard=get_keyboard,
        add_to_bots_mem=add_to_bots_mem,
        log_message=log_message,
        send_document=send_document,
        send_photo=send_photo,
        proccess_image=proccess_image,
        img2txt=img2txt,
        ShowAction=ShowAction,

        # Command handler functions
        handle_voice=handle_voice,
        handle_photo=handle_photo,
        reset_=reset_,
        process_wg_config=process_wg_config,
    )


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
        elif message.sticker:
            file_id = message.sticker.thumb.file_id
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
        # elif message.animation: # анимация как документ прилетает и обрабатывается выше
        #     file_id = message.animation.file_id
        #     try:
        #         file_info = bot.get_file(file_id)
        #     except telebot.apihelper.ApiTelegramException as error:
        #         if 'file is too big' in str(error):
        #             bot_reply_tr(message, 'Too big file.')
        #             return
        #         else:
        #             raise error
        #     file = bot.download_file(file_info.file_path)
        #     fp = io.BytesIO(file)
        #     image = fp.read()

        # h,w = utils.get_image_size(image)
        # if h > 5000 or w > 5000:
        #     # my_log.log2(f'tb:download_image_from_message: too big image {h}x{w}')
        #     return b''

        # уменьшить до 2000 пикселей и пережать в jpg 60% если еще не меньше 2000 и jpg

        # return utils.heic2jpg(image)
        # уменьшаем картинку до 2000 пикселей и переделываем в жпг
        return utils.resize_and_convert_to_jpg(image, 2000, 60)
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:download_image_from_message2: {error} {traceback_error}')
        return b''


def download_image_from_messages(MESSAGES: list) -> list:
    '''Download images from message list'''
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            images = list(executor.map(download_image_from_message, MESSAGES))
        return images
    except Exception as unexpected_error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:download_image_from_messages:{unexpected_error}\n\n{traceback_error}')
        return []


@bot.message_handler(commands=['config', 'settings', 'setting', 'options'], func=authorized_owner)
@async_run
def config(message: telebot.types.Message):
    """Меню настроек"""
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)
        COMMAND_MODE[chat_id_full] = ''

        MSG_CONFIG = get_config_msg(chat_id_full, lang)

        bot_reply(message, MSG_CONFIG, parse_mode='HTML', disable_web_page_preview = False, reply_markup=get_keyboard('config', message))
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:config: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['gmodels','gmodel','gm'], func=authorized_admin)
@async_run
def gmodel(message: telebot.types.Message):
    """Показывает модели доступные в gemini"""
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)
        COMMAND_MODE[chat_id_full] = ''
        current_list = my_gemini3.list_models(include_context=True)
        prev_list = KV_STORAGE.get('gemini_models', '')
        KV_STORAGE['gemini_models'] = current_list

        # Если предыдущий список отличается от текущего:
        if prev_list != current_list:
            # Преобразуем списки в наборы строк (каждая строка – модель)
            prev_models_set = set(prev_list.splitlines())
            current_models_list = current_list.splitlines()
            current_models_set = set(current_models_list) # Добавляем набор для удобства сравнения

            # Вычисляем новые модели
            new_models = {model for model in current_models_set if model not in prev_models_set}

            # Вычисляем удаленные модели (были в прошлом, но нет в текущем)
            removed_models = {model for model in prev_models_set if model not in current_models_set}

            msg_lines = []

            # Формируем итоговое сообщение, выделяя новые модели тегом <b>
            if new_models: # Добавляем заголовок, если есть новые модели
                msg_updated = tr("<b>Обновленный список моделей:</b>", lang)
                msg_lines.append(msg_updated)
                msg_lines.append('')
            for model in current_models_list:
                if model in new_models:
                    msg_lines.append(f"<b>{model}</b>")
                else:
                    msg_lines.append(model)

            # Если есть удаленные модели, добавляем их в тот же список
            if removed_models:
                msg_lines.append('\u200c') # Невидимый символ Zero Width Non-Joiner
                msg_removed = tr("<b>Удалённые модели (больше недоступны):</b>", lang)
                msg_lines.append(msg_removed)
                msg_lines.append('')
                for model in sorted(list(removed_models)): # Сортируем для читаемости
                    msg_lines.append(model)

            msg = "\n".join(msg_lines)

        else:
            # Если изменений нет, просто возвращаем текущий список
            msg = current_list

        bot_reply(message, msg, parse_mode='HTML')
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:gmodel: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['vacuum', 'vacuum_db', 'vacuumdb', 'clean', 'clean_db', 'cleandb', 'cleanup'], func=authorized_admin)
@async_run
def vacuum_db(message: telebot.types.Message):
    """Чистка базы (блокирует бота на какое то время)"""
    try:
        with ShowAction(message):
            chat_id_full = get_topic_id(message)
            COMMAND_MODE[chat_id_full] = ''
            bot_reply_tr(message, 'Cleaning database. Please wait...')
            result = my_db.drop_all_user_files_and_big_dialogs(delete_data=True)
            bot_reply(message, result)
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:vacuum_db: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['transcribe',], func=authorized_owner)
@async_run
def transcribe(message: telebot.types.Message):
    """
    Бот может транскрибировать аудиозапись, переделать ее в субтитры.
    Юзер должен сначала вызвать эту команду а затем кинуть файл или ссылку.
    """
    try:
        chat_id_full = get_topic_id(message)
        COMMAND_MODE[chat_id_full] = 'transcribe'
        help = 'Send an audio file or link to transcribe.'
        bot_reply_tr(message, help, reply_markup=get_keyboard('command_mode_transcribe', message))
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:transcribe: {unknown}\n{traceback_error}')


### Openrouter ################################################################


@bot.message_handler(commands=['model','Model'], func=authorized_owner)
@async_run
def model(message: telebot.types.Message):
    """Юзеры могут менять модель для openrouter.ai"""
    try:
        try:
            chat_id_full = get_topic_id(message)
            COMMAND_MODE[chat_id_full] = ''

            model = message.text.split(maxsplit=1)[1].strip()

            if chat_id_full not in my_openrouter.PARAMS:
                my_openrouter.PARAMS[chat_id_full] = my_openrouter.PARAMS_DEFAULT
            _, temperature, max_tokens, maxhistlines, maxhistchars = my_openrouter.PARAMS[chat_id_full]
            my_openrouter.PARAMS[chat_id_full] = [model, temperature, max_tokens, maxhistlines, maxhistchars]
            bot_reply_tr(message, 'Model changed.')
            return
        except IndexError:
            pass
        except Exception as error:
            error_tr = traceback.format_exc()
            my_log.log2(f'tb:model:{error}\n\n{error_tr}')
        bot_reply_tr(message, 'Usage: /model model_name see models at https://openrouter.ai/models', disable_web_page_preview=True)
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:model: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['maxhistlines',], func=authorized_owner)
@async_run
def maxhistlines(message: telebot.types.Message):
    """Юзеры могут менять maxhistlines для openrouter.ai"""
    try:
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
            bot_reply_tr(message, 'Maxhistlines changed.')
            return
        except IndexError:
            pass
        except Exception as error:
            error_tr = traceback.format_exc()
            my_log.log2(f'tb:model:{error}\n\n{error_tr}')
        bot_reply_tr(message, f'Usage: /maxhistlines maxhistlines 2-100', disable_web_page_preview=True)
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:maxhistlines: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['maxhistchars',], func=authorized_owner)
@async_run
def maxhistchars(message: telebot.types.Message):
    """Юзеры могут менять maxhistchars для openrouter.ai"""
    try:
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
        bot_reply_tr(message, 'Usage: /maxhistchars maxhistchars 2000-1000000', disable_web_page_preview=True)
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:maxhistchars: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['maxtokens',], func=authorized_owner)
@async_run
def maxtokens(message: telebot.types.Message):
    """Юзеры могут менять maxtokens для openrouter.ai"""
    try:
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
            bot_reply_tr(message, 'Maxtokens changed.')
            return
        except IndexError:
            pass
        except Exception as error:
            error_tr = traceback.format_exc()
            my_log.log2(f'tb:model:{error}\n\n{error_tr}')
        bot_reply_tr(message, 'Usage: /maxtokens maxtokens 10-8000', disable_web_page_preview=True)
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:maxtokens: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['model_price'], func=authorized_owner)
@async_run
def model_price(message: telebot.types.Message):
    """Пользователи могут устанавливать значения in_price и out_price,
       а также необязательный параметр currency."""
    try:
        chat_id_full = get_topic_id(message)
        COMMAND_MODE[chat_id_full] = ''

        try:
            prices_str = message.text.split(maxsplit=1)[1].strip()
            parts = prices_str.split()

            if len(parts) < 2 or len(parts) > 3:
                raise ValueError("Invalid number of parameters.")

            try:
                in_price = float(parts[0])
                out_price = float(parts[1])
            except ValueError:
                raise ValueError("Prices must be numeric.")

            if len(parts) == 3:
                currency = parts[2]
            else:
                currency = my_db.get_user_property(chat_id_full, 'openrouter_currency') or '$'

            my_db.set_user_property(chat_id_full, 'openrouter_in_price', in_price)
            my_db.set_user_property(chat_id_full, 'openrouter_out_price', out_price)
            my_db.set_user_property(chat_id_full, 'openrouter_currency', currency) # сохраняем валюту

            bot_reply_tr(message, 'Model prices changed.')
            return

        except IndexError:
            pass
        except ValueError as e:
            bot_reply_tr(message, str(e))
            return
        except Exception as error:
            error_tr = traceback.format_exc()
            my_log.log2(f'tb:model_price:{error}\n\n{error_tr}')

        bot_reply_tr(
            message,
            'Usage:\n\n'
            '/model_price in_price out_price [currency string ($|R|etc)]\n\n'
            '/model_price in_price/out_price [currency]\n\n'
            '/model_price 0 0 - do not show price'
        )
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:model_price: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['list_models'])
@async_run
def list_models_command(message: telebot.types.Message):
    """
    Handles the /list_models command, displaying available models to the user.
    """
    try:
        chat_id_full: str = get_topic_id(message)
        COMMAND_MODE[chat_id_full] = ''

        with ShowAction(message, 'typing'):
            available_models: Optional[List[str]] = my_openrouter.list_models(user_id=str(chat_id_full))

            if available_models is None:
                bot_reply_tr(message, "Error retrieving models. Check API key.")
                return

            if available_models:
                formatted_models: str = my_openrouter.format_models_for_telegram(available_models)
                lines = formatted_models.split('\n')
                # chunk 150 lines per chunk
                chunks = [lines[i:i + 150] for i in range(0, len(lines), 150)]
                for chunk in chunks:
                    ch = '\n'.join(chunk)
                    msg: str = utils.bot_markdown_to_html(ch)
                    bot_reply(message, msg, parse_mode="HTML")

            else:
                bot_reply_tr(message, "No models found.")

    except Exception as error:
        error_tr: str = traceback.format_exc()
        my_log.log2(f'tb:list_models:{error}\n\n{error_tr}')
        bot_reply_tr(message, "An error occurred while processing the request.")


@bot.message_handler(commands=['set_timeout', 'timeout'], func=authorized_owner)
@async_run
def set_timeout(message: telebot.types.Message):
    """Юзеры могут менять timeout для openrouter.ai"""
    try:
        chat_id_full = get_topic_id(message)

        COMMAND_MODE[chat_id_full] = ''

        try:
            timeout_ = int(message.text.split(maxsplit=1)[1].strip())
            if timeout_ < 2 or timeout_ > 1000:
                bot_reply_tr(message, 'Invalid parameters, please use /set_timeout <seconds> 2-1000')
                return
            my_db.set_user_property(chat_id_full, 'openrouter_timeout', timeout_)  # Use the new function
            bot_reply_tr(message, 'Timeout changed.')
            return
        except Exception as error:
            error_tr = traceback.format_exc()
            my_log.log2(f'tb:timeout:{error}\n\n{error_tr}')
        bot_reply_tr(message, f'Usage: /set_timeout <seconds> 2-1000', disable_web_page_preview=True)
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:timeout: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['reasoningeffort',], func=authorized_owner)
@async_run
def reasoningeffort(message: telebot.types.Message):
    """Юзеры могут менять reasoning effort для openrouter.ai"""
    try:
        chat_id_full = get_topic_id(message)
        COMMAND_MODE[chat_id_full] = ''

        try:
            effort_value = message.text.split(maxsplit=1)[1].strip().lower()

            valid_options = ['none', 'low', 'medium', 'high', 'minimal']

            if effort_value == 'none':
                stored_value = None
            elif effort_value in valid_options:
                stored_value = effort_value
            else:
                stored_value = effort_value # Позволяем свой вариант

            my_db.set_user_property(chat_id_full, 'openrouter_reasoning_effort', stored_value)
            bot_reply_tr(message, 'Reasoning effort changed.')
            return
        except IndexError:
            pass
        except Exception as error:
            error_tr = traceback.format_exc()
            my_log.log2(f'tb:reasoningeffort:{error}\n\n{error_tr}')

        # Обновленное сообщение об использовании
        bot_reply(message, 'Usage: /reasoningeffort [none|low|medium|high|minimal|custom_value]', disable_web_page_preview=True)
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:reasoningeffort: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['tool_use', 'tools'], func=authorized_owner)
@async_run
def tool_use(message: telebot.types.Message) -> None:
    """
    Sets the tool usage level for the user. Arguments are English-only.
    """
    # define the canonical, English-only options for the command
    VALID_OPTIONS: set[str] = {'off', 'min', 'medium', 'max'}

    try:
        chat_id_full: str = get_topic_id(message)
        lang: str = get_lang(chat_id_full, message)
        COMMAND_MODE[chat_id_full] = ''

        # --- Localized strings for bot responses ---
        # help text for the AI translator is provided for context
        texts: dict[str, str] = {
            'level_updated': tr('Tool use level updated.', lang),
            'usage_help': tr(
                'Usage: /tool_use [off|min|medium|max]\n\n'

                'Where the levels mean:\n'

                '• `off` - All tools are disabled (default).\n'

                '• `min` - Minimum: calculator & simple web search.\n'

                '• `medium` - Medium: advanced search types & file saving.\n'

                '• `max` - Maximum: all available functions.',
                lang,
                help="A help text explaining the arguments for the /tool_use command. 'min', 'medium', 'max' refer to levels of functionality."
            )
        }
        # --- End of localized strings ---

        try:
            # extract the chosen level from the message
            level_arg: str = message.text.split(maxsplit=1)[1].strip().lower()

            if level_arg in VALID_OPTIONS:
                # persist the setting in the database; the argument is the value
                my_db.set_user_property(chat_id_full, 'tool_use_level', level_arg)
                bot_reply(message, texts['level_updated'])
                return
            else:
                # if the option is not valid, fall through to show usage
                raise ValueError("Invalid tool use level")

        except (IndexError, ValueError):
            # handle case where no argument is provided or argument is invalid
            # fall through to show the detailed help message
            pass
        except Exception as e:
            # log other specific errors during processing
            my_log.log2(f"tb:tool_use:argument_error:{e}\n{traceback.format_exc()}")

        # provide detailed usage instructions
        bot_reply(message, utils.bot_markdown_to_html(texts['usage_help']), parse_mode='HTML')

    except Exception as unknown:
        # catch-all for any other unexpected errors
        traceback_error: str = traceback.format_exc()
        my_log.log2(f'tb:tool_use:unknown_error: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['openrouter', 'bothub'], func=authorized_owner)
@async_run
def openrouter(message: telebot.types.Message) -> None:
    """
    Manages user settings for OpenRouter.ai and other compatible services.
    Allows users to set their API key, base URL, and view current parameters.
    """
    try:
        chat_id_full: str = get_topic_id(message)
        lang: str = get_lang(chat_id_full, message)
        COMMAND_MODE[chat_id_full] = ''

        # --- Localized strings with detailed hints for the translator ---
        texts: dict[str, str] = {
            'your_base_url': tr("Your base api url:", lang, help="Refers to the base URL of an API endpoint, a technical term. For example: https://api.openai.com/v1"),
            'your_key': tr("Your key:", lang, help="Refers to a secret API key for authentication. For example: sk-or-v1-abc...xyz"),
            'model_price': tr("Model price:", lang, help="Refers to the cost of using an AI model. For example: 'Model price: $0.01 / 1k tokens'"),
            'current_settings': tr('Current settings: ', lang, help="A title for a list of current configuration parameters."),
            'key_added': tr('Key added successfully!', lang),
            'base_url_changed': tr('Base API URL changed!', lang),
            'main_help': tr('You can use your own key from https://openrouter.ai/keys or https://bothub.chat/profile/for-developers to access all AI supported.', lang, help="An introductory help message. Do not translate URLs."),
            'reasoning_effort': tr("reasoning effort", lang, help="The name of a parameter for an AI model that controls how much 'thinking' it does. The values are like 'low', 'medium', 'high'."),
            'tool_use': tr("tool use", lang, help="The name of a parameter for an AI model that controls its ability to use external tools like a calculator or web search. The values are like 'off', 'min', 'max'."),
            'commands_help': tr('''/model <model> see available models at https://openrouter.ai/models or https://bothub.chat/models
/list_models - show all models scanned
/temp <temperature> - 0.1 ... 2.0
/maxtokens <max_tokens> - maximum response size, see model details
/maxhistlines <maxhistlines> - how many lines in history
/maxhistchars <maxhistchars> - how many chars in history
/set_timeout <timeout> - 2-1000 seconds
/reasoningeffort [none|low|medium|high|minimal|custom_value]
/tool_use [off|min|medium|max]

Usage: /openrouter <api key> or <api base url>
/openrouter https://openrouter.ai/api/v1 (ok)
https://bothub.chat/api/v2/openai/v1 (ok)
https://api.groq.com/openai/v1 (ok)
https://api.mistral.ai/v1 (ok)
https://api.x.ai/v1 (ok)
https://api.openai.com/v1 (ok)
/help2 for more info
''', lang, help='''This is a help text listing available bot commands. 
IMPORTANT: Translate the descriptive text ONLY.
DO NOT TRANSLATE:
1. Commands (e.g., /model, /list_models, /temp).
2. Arguments in angle brackets (e.g., <model>, <temperature>).
3. Specific keywords (e.g., none, low, off, min, max, ok).
4. URLs (e.g., https://openrouter.ai/models).
Example for a Russian translation:
'/temp <temperature> - 0.1 ... 2.0' should become '/temp <temperature> - 0.1 ... 2.0'
'see available models at' should become 'смотрите доступные модели на'
'''
            ),
        }
        # --- End of localized strings ---

        key: str = ''
        args: list[str] = message.text.split(maxsplit=1)
        if len(args) > 1:
            key = args[1].strip()

        # ensure user params are initialized
        if chat_id_full not in my_openrouter.PARAMS:
            my_openrouter.PARAMS[chat_id_full] = my_openrouter.PARAMS_DEFAULT

        # handle if a key or URL is provided as an argument
        if key:
            if (key.startswith('sk-or-v1-') and len(key) == 73) or (len(key) == 212):
                my_openrouter.KEYS[chat_id_full] = key
                bot_reply(message, texts['key_added'])
                if len(key) == 212: # bothub key
                    my_db.set_user_property(chat_id_full, 'base_api_url', my_openrouter.BASE_URL_BH)
                elif (key.startswith('sk-or-v1-') and len(key) == 73): # openrouter key
                    my_db.set_user_property(chat_id_full, 'base_api_url', my_openrouter.BASE_URL)
                my_db.set_user_property(chat_id_full, 'chat_mode', 'openrouter')
                return
            elif key.startswith('https://'): # base api url
                bot_reply(message, texts['base_url_changed'])
                my_db.set_user_property(chat_id_full, 'base_api_url', key)
                return
            elif key.startswith('ghp_') and len(key) == 40: # GitHub PAT
                my_openrouter.KEYS[chat_id_full] = key
                my_db.set_user_property(chat_id_full, 'base_api_url', my_github.BASE_URL)
                bot_reply(message, texts['key_added'])
                my_db.set_user_property(chat_id_full, 'chat_mode', 'openrouter')
                return
            else: # treat as a generic key
                my_openrouter.KEYS[chat_id_full] = key
                bot_reply(message, texts['key_added'])
                my_db.set_user_property(chat_id_full, 'chat_mode', 'openrouter')
                return
        else:
            # display current status and help message if no argument is provided
            msg: str = texts['main_help']
            if chat_id_full in my_openrouter.KEYS and my_openrouter.KEYS[chat_id_full]:
                key = my_openrouter.KEYS[chat_id_full]

            if key:
                my_db.set_user_property(chat_id_full, 'chat_mode', 'openrouter')
                your_url: str = my_db.get_user_property(chat_id_full, 'base_api_url') or my_openrouter.BASE_URL
                msg = f"{texts['your_base_url']} [{your_url}]\n"
                msg += f"{texts['your_key']} [{key[:12]}...]\n"
                currency: str = my_db.get_user_property(chat_id_full, 'openrouter_currency') or '$'
                msg += f'{texts["model_price"]} in {my_db.get_user_property(chat_id_full, "openrouter_in_price") or 0}{currency} / out {my_db.get_user_property(chat_id_full, "openrouter_out_price") or 0}{currency} /model_price'

            # retrieve and format current settings
            model, temperature, max_tokens, maxhistlines, maxhistchars = my_openrouter.PARAMS[chat_id_full]
            timeout_: int = my_db.get_user_property(chat_id_full, 'openrouter_timeout') or my_openrouter.DEFAULT_TIMEOUT
            reasoning_effort_value: str = my_db.get_user_property(chat_id_full, 'openrouter_reasoning_effort') or 'none'
            tool_use_level: str = my_db.get_user_property(chat_id_full, 'tool_use_level') or 'off'

            # build the settings string
            settings_lines: list[str] = [
                f'[model {model}]',
                f'[temp {temperature}]',
                f'[max tokens {max_tokens}]',
                f'[maxhistlines {maxhistlines}]',
                f'[maxhistchars {maxhistchars}]',
                f'[timeout {timeout_}]',
                f'[{texts["reasoning_effort"]} {reasoning_effort_value if reasoning_effort_value is not None else "none"}]',
                f'[{texts["tool_use"]} {tool_use_level}]'
            ]

            msg += '\n\n' + texts['current_settings'] + '\n' + '\n'.join(settings_lines)
            msg += '\n\n' + texts['commands_help']

            bot_reply(message, msg, disable_web_page_preview=True)

    except Exception as error:
        error_tr: str = traceback.format_exc()
        my_log.log2(f'tb:openrouter:{error}\n\n{error_tr}')


### Openrouter ################################################################


@bot.message_handler(commands=['tgui'], func=authorized_admin)
@async_run
def translation_gui(message: telebot.types.Message):
    """Исправление перевода сообщений от бота

    # Usage: /tgui кусок текста который надо найти, это кривой перевод|||новый перевод, если не задан то будет автоперевод

    # тут перевод указан вручную
    # /tgui клавиши Близнецы добавлены|||ключи для Gemini добавлены

    # а тут будет автоперевод с помощью ии
    # /tgui клавиши Близнецы добавлены
    """
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
                        new_translation = my_gemini3.translate(original, to_lang = lang, help = help, censored=True)
                    if not new_translation:
                        new_translation = my_groq.translate(original, to_lang = lang, help = help)
                        my_db.add_msg(chat_id_full, my_groq.DEFAULT_MODEL)
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


@bot.message_handler(commands=['create_all_translations'], func=authorized_admin)
@async_run
def create_all_translations(message: telebot.types.Message):
    """Команда для создания переводов на все языки"""
    try:
        bot_reply_tr(message, 'Начинаю процесс создания переводов на все языки, это может занять много времени...')
        create_translations_for_all_languages()
        bot_reply_tr(message, 'Процесс создания переводов завершен.')
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:create_all_translations:{error}\n\n{traceback_error}')
        bot_reply(message, 'Произошла ошибка при создании переводов.')


def create_translations_for_all_languages():
    """
    Создает переводы на все языки для уникальных оригиналов.
    """
    # Получаем уникальные оригиналы и их подсказки из базы данных
    try:
        unique_originals: List[Tuple[str, str]] = my_db.get_unique_originals()

        for original, help_text in unique_originals:
            # Переводим на все поддерживаемые языки
            for target_lang in my_init.top_20_used_languages:
                try:
                    translated = tr(original, target_lang, help=help_text, save_cache=True)
                    my_log.log_translate(f'{target_lang}\n\n{original}\n\n{translated}')
                except Exception as error:
                    my_log.log_translate(f'Failed to translate: {original} to {target_lang}. Error: {str(error)}')
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:create_translations_for_all_languages: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['keys', 'key', 'Keys', 'Key'], func=authorized_owner)
@async_run
def users_keys_collector(message: telebot.types.Message):
    """Юзеры могут добавить свои бесплатные ключи для джемини в общий котёл"""
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)
        COMMAND_MODE[chat_id_full] = ''
        is_private = message.chat.type == 'private'

        if not is_private:
            bot_reply_tr(message, "This command is only available in private chat.")
            return

        args = message.text.split(maxsplit=1)
        if len(args) > 1:
            args[1] = args[1].strip()

            # is admin?
            match = re.match(r'^\d{4,15}', args[1])
            if match:
                found_number_str = match.group(0)
                chat_id_full = f'[{found_number_str}] [0]'

            # gemini keys
            keys = [x.strip() for x in args[1].split() if len(x.strip()) == 39]
            already_exists = any(key in my_gemini_general.ALL_KEYS for key in keys)
            if already_exists:
                msg = f'{tr("This key has already been added by someone earlier.", lang)} {keys}'
                keys = []
                bot_reply(message, msg)
            keys = [x for x in keys if x not in my_gemini_general.ALL_KEYS and x.startswith('AIza')]

            # mistral keys len = 32 and passed test
            keys_mistral = [x.strip() for x in args[1].split() if len(x.strip()) == 32 and my_mistral.test_key(x)]
            already_exists = any(key in my_mistral.ALL_KEYS for key in keys_mistral)
            if already_exists:
                keys_mistral = []
                msg = f'{tr("This key has already been added by someone earlier.", lang)}'
                bot_reply(message, msg)

            # cohere keys len = 40 and passed test
            keys_cohere = [x.strip() for x in args[1].split() if len(x.strip()) == 40 and not x.strip().startswith('ghp_') and my_cohere.test_key(x)]
            already_exists = any(key in my_cohere.ALL_KEYS for key in keys_cohere)
            if already_exists:
                keys_cohere = []
                msg = f'{tr("This key has already been added by someone earlier.", lang)}'
                bot_reply(message, msg)

            # github keys len = 40 and passed test
            keys_github = [x.strip() for x in args[1].split() if len(x.strip()) == 40 and x.strip().startswith('ghp_') and my_github.test_key(x)]
            already_exists = any(key in my_github.ALL_KEYS for key in keys_github)
            if already_exists:
                keys_github = []
                msg = f'{tr("This key has already been added by someone earlier.", lang)}'
                bot_reply(message, msg)

            # groq keys len=56, starts with "gsk_"
            keys_groq = [x.strip() for x in args[1].split() if len(x.strip()) == 56]
            if keys_groq and keys_groq[0] in my_groq.ALL_KEYS:
                keys_groq = []
                bot_reply_tr(message, 'Groq API key already exists!')
            keys_groq = [x for x in keys_groq if x not in my_groq.ALL_KEYS and x.startswith('gsk_')]

            # cerebras keys len=52, starts with 'csk-'
            keys_cerebras = [x.strip() for x in args[1].split() if len(x.strip()) == 52 and x.strip().startswith('csk-') and my_cerebras.test_key(x)]
            already_exists = any(key in my_cerebras.ALL_KEYS for key in keys_cerebras)
            if already_exists:
                keys_cerebras = []
                msg = f'{tr("This key has already been added by someone earlier.", lang)}'
                bot_reply(message, msg)

            if keys_mistral:
                my_mistral.USER_KEYS[chat_id_full] = keys_mistral[0]
                my_mistral.ALL_KEYS.append(keys_mistral[0])
                my_log.log_keys(f'Added new API key for Mistral: {chat_id_full} {keys_mistral}')
                bot_reply_tr(message, 'Added API key for Mistral successfully!')

            if keys_cohere:
                my_cohere.USER_KEYS[chat_id_full] = keys_cohere[0]
                my_cohere.ALL_KEYS.append(keys_cohere[0])
                my_log.log_keys(f'Added new API key for Cohere: {chat_id_full} {keys_cohere}')
                bot_reply_tr(message, 'Added API key for Cohere successfully!')

            if keys_github:
                my_github.USER_KEYS[chat_id_full] = keys_github[0]
                my_github.ALL_KEYS.append(keys_github[0])
                my_log.log_keys(f'Added new API key for github: {chat_id_full} {keys_github}')
                bot_reply_tr(message, 'Added API key for github successfully!')

            if keys_groq:
                my_groq.USER_KEYS[chat_id_full] = keys_groq[0]
                my_groq.ALL_KEYS.append(keys_groq[0])
                my_log.log_keys(f'Added new API key for Groq: {chat_id_full} {keys_groq}')
                bot_reply_tr(message, 'Added API key for Groq successfully!')

            if keys_cerebras:
                my_cerebras.USER_KEYS[chat_id_full] = keys_cerebras[0]
                my_cerebras.ALL_KEYS.append(keys_cerebras[0])
                my_log.log_keys(f'Added new API key for Cerebras: {chat_id_full} {keys_cerebras}')
                bot_reply_tr(message, 'Added API key for Cerebras successfully!')

            if keys:
                added_flag = False
                with my_gemini_general.USER_KEYS_LOCK:
                    new_keys = []
                    for key in keys:
                        if key not in my_gemini_general.ALL_KEYS and key not in cfg.gemini_keys:
                            if my_gemini3.test_new_key(key, chat_id_full):
                                my_gemini_general.ALL_KEYS.append(key)
                                new_keys.append(key)
                                added_flag = True
                                my_log.log_keys(f'Added new api key for Gemini: {chat_id_full} {key}')
                                my_db.set_user_property(chat_id_full, 'chat_mode', 'gemini15')
                                msg = tr('Added new API key for Gemini:', lang) + f' {key}'
                                bot_reply(message, msg)
                            else:
                                my_log.log_keys(f'Failed to add new API key for Gemini: {key}')
                                msg = tr('Failed to add new API key for Gemini:', lang) + f' {key}'
                                bot_reply(message, msg)
                if added_flag:
                    my_gemini_general.USER_KEYS[chat_id_full] = new_keys
                    bot_reply_tr(message, 'Added keys successfully!')
                    return

        msg = tr('Usage: /keys API KEYS space separated (gemini, groq, cerebras)', lang) + '\n\n' + \
                 '<blockquote>/keys xxxxx yyyy zzz\n/keys xxxxx</blockquote>\n\n' + \
                 tr('This bot requires free API keys. At least first 2 keys are required.', lang) + '\n\n' + \
                 tr('Please <b>use only FREE keys</b>. Do not use paid accounts. If you have a paid account, please create a new one.', lang)+'\n\n'+\
                 '0️⃣ Free VPN: https://www.vpnjantit.com/\n\n' + \
                 '1️⃣ https://www.youtube.com/watch?v=6aj5a7qGcb4\nhttps://ai.google.dev/\nhttps://aistudio.google.com/apikey\n\n' + \
                 '2️⃣ https://github.com/theurs/tb1/tree/master/pics/groq\nhttps://console.groq.com/keys\n\n' + \
                 '3️⃣ https://cloud.cerebras.ai/\n\n' + \
                 'https://console.mistral.ai/api-keys/\n\nhttps://dashboard.cohere.com/api-keys\n\nhttps://github.com/settings/tokens (classic, unlimited time, empty rights)'

        bot_reply(message, msg, disable_web_page_preview = True, parse_mode='HTML', reply_markup = get_keyboard('donate_stars', message))

        # показать юзеру его ключи
        if is_private:
            gemini_keys = my_gemini_general.USER_KEYS[chat_id_full] if chat_id_full in my_gemini_general.USER_KEYS else []
            mistral_keys = [my_mistral.USER_KEYS[chat_id_full],] if chat_id_full in my_mistral.USER_KEYS else []
            cohere_keys = [my_cohere.USER_KEYS[chat_id_full],] if chat_id_full in my_cohere.USER_KEYS else []
            github_keys = [my_github.USER_KEYS[chat_id_full],] if chat_id_full in my_github.USER_KEYS else []
            groq_keys = [my_groq.USER_KEYS[chat_id_full],] if chat_id_full in my_groq.USER_KEYS else []
            cerebras_keys = [my_cerebras.USER_KEYS[chat_id_full],] if chat_id_full in my_cerebras.USER_KEYS else []
            openrouter_keys = [my_openrouter.KEYS[chat_id_full],] if chat_id_full in my_openrouter.KEYS else []

            msg = tr('Your keys:', lang) + '\n\n'
            if cerebras_keys:
                msg += f'🔑 Cerebras [...{cerebras_keys[0][-4:]}]\n'
            else:
                msg += '🔒 Cerebras\n'
            if cohere_keys:
                msg += f'🔑 Cohere [...{cohere_keys[0][-4:]}]\n'
            else:
                msg += '🔒 Cohere\n'
            if gemini_keys:
                msg += f'🔑 Gemini [...{gemini_keys[0][-4:]}]\n'
            else:
                msg += '🔒 Gemini\n'
            if github_keys:
                msg += f'🔑 Github [...{github_keys[0][-4:]}]\n'
            else:
                msg += '🔒 Github\n'
            if groq_keys:
                msg += f'🔑 Groq [...{groq_keys[0][-4:]}]\n'
            else:
                msg += '🔒 Groq\n'
            if mistral_keys:
                msg += f'🔑 Mistral [...{mistral_keys[0][-4:]}]\n'
            else:
                msg += '🔒 Mistral\n'
            if openrouter_keys:
                msg += f'🔑 Openrouter [...{openrouter_keys[0][-4:]}]\n'
            else:
                msg += '🔒 Openrouter\n'

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
        if key not in my_gemini_general.ALL_KEYS:
            my_gemini_general.ALL_KEYS.append(key)
            my_gemini_general.USER_KEYS[uid] = [key,]
            bot_reply_tr(message, 'Added keys successfully!')
        else:
            for uid_ in [x for x in my_gemini_general.USER_KEYS.keys()]:
                if uid_ in my_gemini_general.USER_KEYS:
                    if my_gemini_general.USER_KEYS[uid_] == [key,]:
                        del my_gemini_general.USER_KEYS[uid_]
            my_gemini_general.USER_KEYS[uid] = [key,]
            bot_reply_tr(message, 'Added keys successfully!')
    except Exception as error:
        bot_reply_tr(message, 'Usage: /addkeys <user_id as int> <key>')


@bot.message_handler(commands=['donate', 'star', 'stars'], func=authorized_owner)
@async_run
def donate(message: telebot.types.Message):
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)
        if hasattr(cfg, 'DONATION_STRING'):
            help = cfg.DONATION_STRING
        else:
            help = '<None>'
        help += '\n\n' + tr('Your stars:', lang) + f' {my_db.get_user_property(chat_id_full, "telegram_stars") or 0}'
        bot_reply(message, help, parse_mode='HTML', disable_web_page_preview=True, reply_markup = get_keyboard('donate_stars', message))
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:donate: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['sdonate', 'sstar', 'sstars'], func=authorized_admin)
@async_run
def sdonate(message: telebot.types.Message):
    '''админ может добавить звезды пользователю
    использование - sdonate <id> <количество>'''
    try:
        try:
            args = message.text.split()
        except:
            args = []

        if len(args) == 3:
            chat_id_full = f'[{args[1]}] [0]'
            stars = int(args[2])
            user_stars = my_db.get_user_property(chat_id_full, 'telegram_stars') or 0
            my_db.set_user_property(chat_id_full, 'telegram_stars', user_stars + stars)
            my_log.log_donate(f'sdonate {chat_id_full} {stars}')
            bot_reply_tr(message, 'Added successfully!')
        else:
            bot_reply_tr(message, 'Usage: /sdonate id_as_int amount of fake stars')
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:sdonate: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['drop_subscription'], func=authorized_admin)
@async_run
def drop_subscription(message: telebot.types.Message):
    '''
    админ может удалить запись об активной подписке
    использование - sdonate <id> as int
    '''
    try:
        arg = message.text.split()[1]
        user_id = int(arg)

        if user_id:
            chat_id_full = f'[{user_id}] [0]'
            my_db.set_user_property(chat_id_full, 'last_donate_time', 0)
            my_log.log_donate(f'drop_subscription {chat_id_full}')
            bot_reply_tr(message, 'Dropped successfully!')

    except (IndexError, ValueError):
        pass
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:drop_subscription: {unknown}\n{traceback_error}')

    bot_reply_tr(message, 'Usage: /drop_subscription id_as_int')


def send_all_files_from_storage(message: telebot.types.Message, chat_id_full: str) -> None:
    """
    Sends files from the temporary storage for the given user.
    Images are grouped into media groups, while other file types are sent individually.
    """
    try:
        items = my_skills_storage.STORAGE.get(chat_id_full)
        if not items:
            return

        image_group = []
        other_files = []

        # Separate images from other file types
        for item in items:
            if item.get('type') and 'image' in item['type']:
                image_group.append(item)
            else:
                other_files.append(item)

        # Send images as a media group if there are any
        if image_group:
            media_to_send = []
            for item in image_group:
                filename, data = item.get('filename', 'image.png'), item.get('data')
                if data:
                    # Truncate caption to Telegram's limit
                    media_to_send.append(telebot.types.InputMediaPhoto(data, caption=filename[:900]))

            # Split into chunks of 10, as per Telegram's limit
            if media_to_send:
                chunk_size = 10
                chunks = [media_to_send[i:i + chunk_size] for i in range(0, len(media_to_send), chunk_size)]
                for chunk in chunks:
                    try:
                        sent_messages = send_media_group(
                            message=message,
                            chat_id=message.chat.id,
                            media=chunk,
                            reply_to_message_id=message.message_id
                        )
                        if sent_messages:
                            log_message(sent_messages)
                    except Exception as e:
                        my_log.log2(f'tb:send_all_files_from_storage:media_group_error: {e}')

        # Send other files individually
        for item in other_files:
            try:
                _type, filename, data = item.get('type'), item.get('filename'), item.get('data')
                if not all([_type, filename, data]):
                    continue

                m = None
                # Truncate caption to Telegram's limit
                safe_caption = filename[:900]

                if _type in ('excel file', 'docx file', 'text file', 'pdf file'):
                    m = send_document(
                        message=message, chat_id=message.chat.id, document=data,
                        reply_to_message_id=message.message_id, reply_markup=get_keyboard('hide', message),
                        caption=safe_caption, visible_file_name=filename,
                    )
                elif 'video' in _type:
                    m = send_video(
                        message=message, chat_id=message.chat.id, video=data,
                        caption=safe_caption, reply_to_message_id=message.message_id,
                        reply_markup=get_keyboard('hide', message),
                    )

                if m:
                    log_message(m)
            except Exception as individual_error:
                traceback_error = traceback.format_exc()
                my_log.log2(f'tb:send_all_files_from_storage:individual_item_error: {individual_error}\n\n{traceback_error}')
                continue

    except Exception as general_error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:send_all_files_from_storage:general_error: for chat {chat_id_full}: {general_error}\n\n{traceback_error}')
    finally:
        # Clear storage for the user after attempting to send
        my_skills_storage.STORAGE.pop(chat_id_full, None)


@bot.message_handler(commands=['calc', 'math'], func=authorized_owner)
@async_run
def calc_gemini(message: telebot.types.Message):
    """
    Calculate math expression with google gemini code execution tool
    """
    try:
        message.text = my_log.restore_message_text(message.text, message.entities)

        args = message.text.split(maxsplit=1)
        if len(args) == 2:
            arg = args[1]
        else:
            bot_reply_tr(message, 'Usage: /calc <expression>')
            return

        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)
        COMMAND_MODE[chat_id_full] = ''
        # проверка на подписку
        if not my_subscription.check_donate(message, chat_id_full, lang, COMMAND_MODE, CHECK_DONATE_LOCKS, BOT_ID, tr, bot_reply, get_keyboard):
            return

        with ShowAction(message, "typing"):
            answer, underground = my_gemini_google.calc(arg, chat_id_full)

            if answer:
                a = utils.bot_markdown_to_html(answer)
                if underground:
                    u = utils.bot_markdown_to_html(underground)
                    # bot_reply(message, u, parse_mode='HTML', disable_web_page_preview=True)
                    bot_reply(message, a, parse_mode='HTML', disable_web_page_preview=True)
                else:
                    bot_reply(message, a, parse_mode='HTML', disable_web_page_preview=True)
            else:
                bot_reply_tr(message, 'Calculation failed.')
            # add_to_bots_mem(arg, f'{underground}\n\n{answer}', chat_id_full)
            add_to_bots_mem(f'/calc {arg}', f'{answer}', chat_id_full)

            send_all_files_from_storage(message, chat_id_full)

    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:calc_gemini: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['ytb'], func=authorized_owner)
@async_run
def download_ytb_audio(message: telebot.types.Message):
    """
    Download, split and send chunks to user.
    """
    try:

        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        COMMAND_MODE[chat_id_full] = ''
        # проверка на подписку
        if not my_subscription.check_donate(message, chat_id_full, lang, COMMAND_MODE, CHECK_DONATE_LOCKS, BOT_ID, tr, bot_reply, get_keyboard):
            return

        url = message.text.split(maxsplit=1)
        if len(url) == 2:
            url = url[1]

            with ShowAction(message, "upload_audio"):            
                if my_ytb.valid_youtube_url(url):
                    title, pic, desc, size = my_ytb.get_title_and_poster(url)
                    if size == 0 or size > 6*60*60:
                        bot_reply_tr(message, 'Too big video for me.')
                        return
                    source_file = my_ytb.download_audio(url)
                    files = []
                    if source_file:
                        bot_reply_tr(message, 'Downloaded successfully, sending file.')
                        files = my_ytb.split_audio(source_file, 45)
                        bot_reply(message, desc[:4090], send_message=True, disable_web_page_preview=True)
                        if files:
                            image_stream = io.BytesIO(utils.download_image_for_thumb(pic))
                            try:
                                tmb = telebot.types.InputFile(image_stream)
                            except:
                                tmb = None

                            for fn in files:
                                with open(fn, 'rb') as f:
                                    data = f.read()
                                caption = f'{title} - {os.path.splitext(os.path.basename(fn))[0]}'
                                caption = f'{caption[:900]}\n\n{url}'

                                try:
                                    m = send_audio(
                                        message,
                                        message.chat.id,
                                        data,
                                        title = f'{os.path.splitext(os.path.basename(fn))[0]}.opus',
                                        caption = f'@{_bot_name} {caption}',
                                        thumbnail=tmb,
                                    )
                                    log_message(m)
                                except Exception as faild_upload_audio:
                                    my_log.log2(f'tb:download_ytb_audio1: {faild_upload_audio}')
                                    bot_reply_tr(message, 'Upload failed.')
                                    my_ytb.remove_folder_or_parent(source_file)
                                    if files and files[0] and source_file and files[0] != source_file:
                                        my_ytb.remove_folder_or_parent(files[0])
                                    return
                    else:
                        bot_reply_tr(message, 'Download failed.')

                    my_ytb.remove_folder_or_parent(source_file)
                    if files and files[0] and source_file and files[0] != source_file:
                        my_ytb.remove_folder_or_parent(files[0])
                    return

        bot_reply_tr(message, 'Usage: /ytb URL\n\nDownload and send audio from youtube (and other video sites).')
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:download_ytb_audio2: {error}\n\n{traceback_error}')


@bot.message_handler(commands=['memo', 'memos'], func=authorized_owner)
@async_run
def memo_handler(message: telebot.types.Message):
    """
    Попросить бота запомнить что то.

    Запомненное добавляется в системный промпт как список того что юзер просил запомнить.

    Если вызвать команду без аргумента то показывать список запомненного с номерами по
    которым можно удалить их
    """
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        # если есть список запрещенных юзеров в конфиге то проверить
        if hasattr(cfg, 'BLOCK_SYSTEM_MSGS') and cfg.BLOCK_SYSTEM_MSGS:
            if any([x for x in cfg.BLOCK_SYSTEM_MSGS if x == message.from_user.id]):
                bot_reply(message, "OK.")
                return

        COMMAND_MODE[chat_id_full] = ''

        arg = message.text.split(maxsplit=1)[1:]

        if arg:
            arg = arg[0]
            if len(arg) < 3 and arg.isdigit():
                memos = my_db.blob_to_obj(my_db.get_user_property(chat_id_full, 'memos')) or []
                arg = int(arg)
                if arg <= len(memos):
                    memos.pop(arg - 1)
                    my_db.set_user_property(chat_id_full, 'memos', my_db.obj_to_blob(memos))
                    bot_reply_tr(message, 'Memo was deleted.')
                elif len(memos) > 10:
                    bot_reply_tr(message, 'Too many memos. Delete some before add new.')
                else:
                    bot_reply_tr(message, 'There is no such memo.')
            else:
                memos = my_db.blob_to_obj(my_db.get_user_property(chat_id_full, 'memos')) or []
                arg = arg.strip()
                if len(arg) > 3:
                    if len(memos) > 10:
                        bot_reply_tr(message, 'Too many memos. Delete some before add new.')
                    else:

                        if utils_llm.detect_forbidden_prompt(arg):
                            my_log.log2(f'tb:memo_handler: Forbidden prompt: {chat_id_full} {arg}')
                            return

                        memos.append(arg)
                        my_db.set_user_property(chat_id_full, 'memos', my_db.obj_to_blob(memos))
                        bot_reply_tr(message, 'New memo was added.')
                else:
                    bot_reply_tr(message, 'Too short memo.')

        else:
            msg = tr("""
Usage : /memo &lt;text&gt; or &lt;number to delete&gt; - попросить бота запомнить что то

<code>/memo когда я говорю тебе нарисовать что то ты должен придумать профессиональный промпт для рисования на английском языке и ответить мне /flux your prompt</code>

<code>/memo когда пишешь код на питоне пиши комментарии в коде на английском а вне кода на русском, и соблюдай все правила оформления кода</code>

<code>/memo для записи математики используй символы из юникода вместо latex</code>
""", lang)
            memos = my_db.blob_to_obj(my_db.get_user_property(chat_id_full, 'memos')) or []
            i = 1
            for memo in memos:
                msg += f'\n\n[❌ {i}] {utils.html.escape(memo)}'
                i += 1
            COMMAND_MODE[chat_id_full] = 'memo'
            bot_reply(message, msg, reply_markup=get_keyboard('command_mode', message), parse_mode='HTML')

    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:memo_handler: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['memo_admin'], func=authorized_admin)
@async_run
def memo_admin_handler(message: telebot.types.Message):
    """
    Allows admins to manage memos for other users.

    Example:
    /memo_admin 76125467

    memo1

    memo2

    memo3
    """
    try:
        chat_id_full = get_topic_id(message)
        COMMAND_MODE[chat_id_full] = ''

        # Получаем только первую строку сообщения, чтобы извлечь команду и ID пользователя
        first_line = message.text.split('\n', 1)[0]

        # Регулярное выражение для извлечения ID пользователя.
        # Теперь оно ищет либо:
        # 1. Строку вида '[-цифры] [цифры]' или '[цифры] [цифры]' (например, '[-12345] [0]')
        # 2. Либо просто последовательность цифр (например, '12345')
        user_id_pattern = re.compile(r'^/memo_admin\s+((?:\[\-?\d+\] \[\d+\])|\d+)')
        match = user_id_pattern.match(first_line)

        if not match:
            # Если совпадения нет, значит ID не был предоставлен или формат неверный
            bot_reply_tr(message, "Usage: /memo_admin <user_id>\n\n[<memo_1>\n\n<memo_2>\n\n...<memo_10>]\n\n/memo_admin <user_id> - View existing memos", parse_mode='')
            return

        # Извлеченный ID пользователя (строка, например '12345' или '[12345] [0]')
        user_id_extracted = match.group(1)

        # Определяем полный формат ID чата для работы с базой данных
        user_chat_id_full = ""
        # Если извлеченный ID состоит только из цифр, форматируем его как '[цифры] [0]'
        if user_id_extracted.isdigit():
            user_chat_id_full = f'[{user_id_extracted}] [0]'
        else:
            # В противном случае, он уже должен быть в формате '[число] [число]'
            # Регулярка уже проверила его формат, так что дополнительная проверка не нужна.
            user_chat_id_full = user_id_extracted

        # Теперь обрабатываем заметки: просмотр или сохранение
        all_lines = message.text.split('\n')
        # Если в сообщении только одна строка (команда + ID)
        # или две строки, но вторая пустая, то это запрос на просмотр заметок
        if len(all_lines) == 1 or (len(all_lines) == 2 and not all_lines[1].strip()):
            memos = my_db.blob_to_obj(my_db.get_user_property(user_chat_id_full, 'memos')) or []
            if memos:
                msg = ''
                n = 1
                for memo in memos:
                    msg += f'\n\n[{n}] {memo}'
                    n += 1
                bot_reply(message, msg)
            else:
                bot_reply_tr(message, f"No memos found for user {user_id_extracted}.")
            return

        # Если есть дополнительные строки, то пользователь передал новые заметки для сохранения
        new_memos_raw = all_lines[1:] # Заметки начинаются со второй строки
        new_memos = [line.strip() for line in new_memos_raw if line.strip()] # Отфильтровываем пустые строки

        if new_memos:
            # Согласно логике исходного кода, новые заметки заменяют старые.
            combined_memos = new_memos
            if len(combined_memos) > 10:
                combined_memos = combined_memos[-10:] # Оставляем только последние 10
                bot_reply_tr(message, "Too many memos. Only the last 10 will be saved.")

            my_db.set_user_property(user_chat_id_full, 'memos', my_db.obj_to_blob(combined_memos))
            bot_reply_tr(message, f"Memos saved for user {user_id_extracted}.")
        else:
            # Обработка случаев, когда после команды с ID идут только пустые строки
            bot_reply_tr(message, "No valid memos provided to save. To view memos, use /memo_admin <user_id> without any additional lines.")

    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:memo_admin_handler: {unknown}\n{traceback_error}')
        bot_reply_tr(message, "An unexpected error occurred. Please check the format and try again.\nUsage:\n/memo_admin <user_id> [<memo_1>\n<memo_2>\n...<memo_10>]\n/memo_admin <user_id> - View existing memos", parse_mode='')


# вариант с такой лямбдой вызывает проблемы в функции is_for_me, туда почему то приходит команда без имени бота
# @bot.message_handler(func=lambda message: authorized_owner(message) and message.text.split()[0].lower() in ['/style', '/role'])
# что бы поймать слишком длинные сообщения придется положиться на обработчик текстовых сообщений
# он поймает соберет в кучу и вызвет эту команду
# @bot.message_handler(commands=['style', 'role'], func=authorized_owner)
# @async_run
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
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        # если есть список запрещенных юзеров в конфиге то проверить
        if hasattr(cfg, 'BLOCK_SYSTEM_MSGS') and cfg.BLOCK_SYSTEM_MSGS:
            if any([x for x in cfg.BLOCK_SYSTEM_MSGS if x == message.from_user.id]):
                bot_reply(message, "OK.")
                return

        COMMAND_MODE[chat_id_full] = ''

        DEFAULT_ROLES = my_init.get_default_roles(tr, lang)

        arg = message.text.split(maxsplit=1)[1:]

        if arg:
            arg = arg[0]
            if arg in ('<0>', '<1>', '<2>', '<3>', '<4>', '<5>', '<6>', '<7>', '<8>', '<9>'):
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
            elif arg == '6':
                new_prompt = DEFAULT_ROLES[5]
            elif arg == '7':
                new_prompt = DEFAULT_ROLES[6]
            elif arg == '8':
                new_prompt = DEFAULT_ROLES[7]
            elif arg == '9':
                new_prompt = DEFAULT_ROLES[8]
            elif arg == '0':
                new_prompt = ''
            else:
                new_prompt = arg

            if utils_llm.detect_forbidden_prompt(new_prompt):
                my_log.log2(f'tb:change_mode: Forbidden prompt: {chat_id_full} {new_prompt}')
                return

            my_db.set_user_property(chat_id_full, 'role', new_prompt)

            if new_prompt:
                msg =  f'{tr("New role was set.", lang)}'
            else:
                msg =  f'{tr("Roles was reset.", lang)}'
            bot_reply(message, msg, parse_mode='HTML', disable_web_page_preview=True)
        else:
            msg = f"""{tr('Меняет роль бота, строку с указаниями что и как говорить', lang)}

`/style <0|1|2|3|4|5|6|7|8|9|{tr('свой текст', lang)}>`

{tr('Сброс, нет никакой роли', lang)}
`/style 0`

`/style 1`
`/style {DEFAULT_ROLES[0]}`

`/style 2`
`/style {DEFAULT_ROLES[1]}`

`/style 3`
`/style {DEFAULT_ROLES[2]}`

{tr('Фокус на выполнение какой то задачи', lang)}
`/style 4`
`/style {DEFAULT_ROLES[3]}`

{tr('Неформальное общение', lang)}
`/style 5`
`/style {DEFAULT_ROLES[4]}`
    """

            # _user_id = utils.extract_user_id(chat_id_full)
            # if _user_id in cfg.admins:
            #     msg += '\n\n\n`/style ты можешь сохранять и запускать скрипты на питоне и баше через функцию run_script, в скриптах можно импортировать любые библиотеки и обращаться к сети и диску`'

            msg = utils.bot_markdown_to_html(msg)
            msg += f'''

{tr("Текущий стиль", lang)}
<blockquote expandable><code>/style {utils.html.escape(my_db.get_user_property(chat_id_full, 'role') or tr('нет никакой роли', lang))}</code></blockquote>
        '''

            bot_reply(message, msg, parse_mode='HTML')
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:set_style: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['set_stt_mode', 'stt'], func=authorized_admin)
@async_run
def set_stt_mode(message: telebot.types.Message):
    """
    Allows admins to set or view the Speech-to-Text (STT) engine for a specific user.

    Usage:
    /set_stt_mode <user_id as int> [new_mode]

    Available STT Engines:
    - auto
    - whisper
    - gemini
    - google
    - assembly.ai
    - deepgram_nova3

    Example:
    /set_stt_mode 123456789 whisper  # Sets the STT engine for user 123456789 to 'whisper'
    /set_stt_mode 123456789 # Show current mode
    """
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        parts = message.text.split()
        if len(parts) < 2 or len(parts) > 3:  # Correctly handle the command format
            user_id = extract_user_id(message) or message.from_user.id
            # Show user's current STT engine and available options
            current_stt_engine = my_db.get_user_property(f'[{user_id}] [0]', 'speech_to_text_engine') or my_stt.DEFAULT_STT_ENGINE
            msg = f"🎤 {tr('Current STT engine for user', lang)} {user_id}: **{current_stt_engine}**\n\n"
            msg += f"🗣 {tr('Available STT engines:', lang)} auto, whisper, gemini, google, assembly.ai, deepgram_nova3\n\n"
            msg += f"ℹ️ {tr('Usage:', lang)} /set_stt_mode <{tr('user_id', lang)} (int)> [<{tr('new_mode', lang)}>]\n"
            msg += f"Example:\n/set_stt_mode {user_id} whisper"
            msg = utils.bot_markdown_to_html(msg)
            bot_reply(message, msg, parse_mode='HTML')
            return

        user_id_str = parts[1]  # Get user ID as a string
        try:
            user_id = int(user_id_str)
        except ValueError:
            bot_reply(message, "Invalid user ID.  Please provide an integer.")
            return

        user_chat_id_full = f'[{user_id}] [0]'
        if len(parts) == 2:
            # No new mode specified, show current mode
            current_stt_engine = my_db.get_user_property(user_chat_id_full, 'speech_to_text_engine') or my_stt.DEFAULT_STT_ENGINE
            bot_reply(message, f"🎤 {tr('Current STT engine for user', lang)} {user_id}: <b>{current_stt_engine}</b>", parse_mode='HTML')
            return

        new_mode = parts[2].lower()

        if new_mode not in ('auto', 'whisper', 'gemini', 'google', 'assembly.ai', 'deepgram_nova3'):
            bot_reply(message, f"Invalid STT engine: {new_mode}. Available engines are auto, whisper, gemini, google, assembly.ai, deepgram_nova3")
            return

        my_db.set_user_property(user_chat_id_full, 'speech_to_text_engine', new_mode)

        bot_reply(message, f"✅ {tr('STT engine for user', lang)} {user_id} {tr('set to', lang)} {new_mode}.")

    except Exception as e:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:set_stt_mode: {e}\n{traceback_error}')
        bot_reply(message, f"❌ An error occurred: {str(e)}")


@bot.message_handler(commands=['set_chat_mode'], func=authorized_admin)
@async_run
def set_chat_mode(message: telebot.types.Message):
    """mandatory switch user from one chatbot to another"""
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        _user = f'[{message.text.split(maxsplit=3)[1].strip()}] [0]'
        _prev_mode = my_db.get_user_property(_user, 'chat_mode') or cfg.chat_mode_default
        _mode = message.text.split(maxsplit=3)[2].strip()

        my_db.set_user_property(_user, 'chat_mode', _mode)


        # перегружаем память из джемини в опенаи или обратно
        new_mem = []
        if 'gemini' in _prev_mode and 'gemini' not in _mode:
            # gemini to openai
            new_mem = my_gemini3.gemini_to_openai_mem(_user)
            if new_mem:
                my_db.set_user_property(_user, 'dialog_openrouter', my_db.obj_to_blob(new_mem))
        elif 'gemini' in _mode and 'gemini' not in _prev_mode:
            # openai to gemini
            new_mem = my_gemini3.openai_to_gemini_mem(_user)
            if new_mem:
                my_db.set_user_property(_user, 'dialog_gemini3', my_db.obj_to_blob(new_mem))


        msg = f'{tr("Changed: ", lang)} {_user} -> {_mode}.'

        bot_reply(message, msg)
    except:
        msg = f"{tr('Example usage: /set_chat_mode user_id_as_int new_mode', lang)} gemini15, gemini, ..."
        bot_reply(message, msg, parse_mode='HTML')


@bot.message_handler(commands=['disable_chat_mode'], func=authorized_admin)
@async_run
def disable_chat_mode(message: telebot.types.Message):
    """mandatory switch all users from one chatbot to another"""
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        _from = message.text.split(maxsplit=3)[1].strip()
        _to = message.text.split(maxsplit=3)[2].strip()

        n = 0
        for x in my_db.get_all_users_ids():
            if my_db.get_user_property(x, 'chat_mode') == _from:
                my_db.set_user_property(x, 'chat_mode', _to)
                my_db.set_user_property(x, 'chat_mode_prev', _from) # save for ability to restore
                n += 1

        msg = f'{tr("Changed: ", lang)} {n}.'
        bot_reply(message, msg)
    except:
        n = '\n\n'
        msg = f"{tr('Example usage: /disable_chat_mode FROM TO{n}Available:', lang)} gemini15, gemini"
        bot_reply(message, msg, parse_mode='HTML')


@bot.message_handler(commands=['disable_stt_mode'], func=authorized_admin)
@async_run
def disable_stt_mode(message: telebot.types.Message):
    """
    Принудительно переключает движок Speech-to-Text (STT) для всех пользователей
    с одного движка на другой.

    Использование:
    /disable_stt_mode <FROM_STT_ENGINE> <TO_STT_ENGINE>

    Пример:
    /disable_stt_mode whisper auto  # Переключает всех пользователей с 'whisper' на 'auto'
    """
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        parts = message.text.split(maxsplit=2) # Изменено maxsplit на 2 для двух аргументов
        AVAILABLE_STT_ENGINES = ['auto', 'whisper', 'gemini', 'google', 'assembly.ai', 'deepgram_nova3']
        if len(parts) != 3: # Проверяем, что есть ровно 3 части: команда, FROM, TO
            n = '\n\n'
            available_engines_str = ", ".join(AVAILABLE_STT_ENGINES)
            msg = f"{tr('Example usage: /disable_stt_mode FROM_STT_ENGINE TO_STT_ENGINE{n}Available:', lang)} {available_engines_str}"
            bot_reply(message, msg, parse_mode='HTML')
            return

        _from_stt = parts[1].strip().lower() # Движок, с которого переключаем
        _to_stt = parts[2].strip().lower()   # Движок, на который переключаем

        # Проверяем валидность указанных движков
        if _from_stt not in AVAILABLE_STT_ENGINES or _to_stt not in AVAILABLE_STT_ENGINES:
            available_engines_str = ", ".join(AVAILABLE_STT_ENGINES)
            msg = f"{tr('Invalid STT engine specified. Available:', lang)} {available_engines_str}"
            bot_reply(message, msg, parse_mode='HTML')
            return

        n_changed = 0 # Количество измененных пользователей
        all_users_ids = my_db.get_all_users_ids() # Получаем все ID пользователей

        for user_chat_id in all_users_ids:
            # Проверяем текущий STT движок пользователя
            current_stt_engine = my_db.get_user_property(user_chat_id, 'speech_to_text_engine')

            if current_stt_engine == _from_stt:
                my_db.set_user_property(user_chat_id, 'speech_to_text_engine', _to_stt)
                n_changed += 1

        msg = f'{tr("Changed STT engine for", lang)} {n_changed} {tr("users.", lang)} {tr("From", lang)} <b>{_from_stt}</b> {tr("to", lang)} <b>{_to_stt}</b>.'
        bot_reply(message, msg, parse_mode='HTML')

    except Exception as e:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:disable_stt_mode: {e}\n{traceback_error}')
        n = '\n\n'
        available_engines_str = ", ".join(AVAILABLE_STT_ENGINES)
        msg = f"{tr('An error occurred:', lang)} {str(e)}\n\n{tr('Example usage: /disable_stt_mode FROM_STT_ENGINE TO_STT_ENGINE{n}Available:', lang)} {available_engines_str}"
        bot_reply(message, msg, parse_mode='HTML')


@bot.message_handler(commands=['restore_chat_mode'], func=authorized_admin)
@async_run
def restore_chat_mode(message: telebot.types.Message):
    """
    Восстанавливает предыдущие режимы чата для всех пользователей, у которых они были сохранены.

    Используется для отмены действия команды /disable_chat_mode, которая принудительно меняет режим
    чата пользователя и сохраняет предыдущий режим в базе данных.

    Эта команда не принимает аргументов. Она перебирает всех пользователей в базе данных и для каждого пользователя:
    1. Проверяет, сохранен ли у него предыдущий режим чата (в свойстве 'chat_mode_prev').
    2. Если предыдущий режим сохранен, восстанавливает его в качестве текущего режима чата ('chat_mode') 
       и удаляет запись о предыдущем режиме.
    3. Если предыдущий режим не сохранен, ничего не делает для этого пользователя.

    После обработки всех пользователей отправляет сообщение с количеством восстановленных режимов.

    Доступ к команде есть только у администраторов бота.
    """
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        n = 0
        for user_id in my_db.get_all_users_ids():
            prev_mode = my_db.get_user_property(user_id, 'chat_mode_prev')
            if prev_mode:
                my_db.set_user_property(user_id, 'chat_mode', prev_mode)
                my_db.delete_user_property(user_id, 'chat_mode_prev')  # Удаляем сохраненный предыдущий режим
                n += 1

        msg = f'{tr("Reverted chat modes for", lang)} {n} {tr("users.", lang)}'
        bot_reply(message, msg)
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log2(f'tb:restore_chat_mode: {error}\n{error_traceback}')
        bot_reply_tr(message, "An error occurred while processing the command.")


def change_last_bot_answer(chat_id_full: str, text: str, message: telebot.types.Message):
    '''изменяет последний ответ от бота на text'''
    try:
        mode = my_db.get_user_property(chat_id_full, 'chat_mode')
        if any(mode.startswith(m) for m in ('gemini', 'gemma')):
            my_gemini3.force(chat_id_full, text, model = mode)
        elif mode == 'openrouter':
            my_openrouter.force(chat_id_full, text)

        elif mode == 'cloacked':
            my_openrouter_free.force(chat_id_full, text)

        elif mode == 'qwen3':
            my_cerebras.force(chat_id_full, text)
        elif mode == 'qwen3coder':
            my_cerebras.force(chat_id_full, text)
        elif mode == 'gpt_oss':
            my_cerebras.force(chat_id_full, text)
        elif mode == 'llama4':
            my_cerebras.force(chat_id_full, text)
        elif mode in ('mistral', 'magistral'):
            my_mistral.force(chat_id_full, text)
        elif mode in ('gpt-4o', 'gpt_41', 'gpt_41_mini', 'deepseek_r1', 'deepseek_v3'):
            my_github.force(chat_id_full, text)
        elif mode == 'cohere':
            my_cohere.force(chat_id_full, text)
        else:
            bot_reply_tr(message, 'History WAS NOT changed.')
            return
        bot_reply_tr(message, 'Last answer was updated.')
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:change_last_bot_answer: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['force',], func=authorized_log)
@async_run
def force_cmd(message: telebot.types.Message):
    """Update last bot answer"""
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)
        COMMAND_MODE[chat_id_full] = ''
        message.text = my_log.restore_message_text(message.text, message.entities)
        try:
            text = message.text.split(' ', maxsplit=1)[1]
            if text:
                change_last_bot_answer(chat_id_full, text, message)
                return
        except IndexError:
            pass

        msg = '/force text - ' + tr("Force the bot to respond with the given text, updating its memory as if it had generated that response itself. This command overrides the usual bot behavior and makes it say exactly what you specify.", lang)
        bot_reply(message, msg)
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:force_cmd: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['undo', 'u', 'U', 'Undo'], func=authorized_log)
@async_run
def undo_cmd(message: telebot.types.Message, show_message: bool = True):
    """Clear chat history last message (bot's memory)"""
    try:
        chat_id_full = get_topic_id(message)
        COMMAND_MODE[chat_id_full] = ''
        mode = my_db.get_user_property(chat_id_full, 'chat_mode')
        if any(mode.startswith(m) for m in ('gemini', 'gemma')):
            my_gemini3.undo(chat_id_full, model = mode)
        elif mode == 'openrouter':
            my_openrouter.undo(chat_id_full)

        elif mode == 'cloacked':
            my_openrouter_free.undo(chat_id_full)

        elif mode == 'qwen3':
            my_cerebras.undo(chat_id_full)
        elif mode == 'qwen3coder':
            my_cerebras.undo(chat_id_full)
        elif mode == 'gpt_oss':
            my_cerebras.undo(chat_id_full)
        elif mode == 'llama4':
            my_cerebras.undo(chat_id_full)
        elif mode in ('mistral', 'magistral'):
            my_mistral.undo(chat_id_full)
        elif mode in ('gpt-4o', 'gpt_41', 'gpt_41_mini', 'deepseek_r1', 'deepseek_v3'):
            my_github.undo(chat_id_full)
        elif mode == 'cohere':
            my_cohere.undo(chat_id_full)
        else:
            bot_reply_tr(message, 'History WAS NOT undone.')

        if show_message:
            bot_reply_tr(message, 'Last message was cancelled.')
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:undo: {unknown}\n{traceback_error}')


def reset_(message: telebot.types.Message, say: bool = True, chat_id_full: str = None):
    """Clear chat history (bot's memory)
    message - is message object (optional)
    say - bool, send message 'history cleared' or not (optional, default True)
    chat_id_full - is chat_id_full string (optional, if None then get_topic_id(message))
    """
    try:
        if chat_id_full is None: # Определяем chat_id_full, если он не передан явно
            chat_id_full = get_topic_id(message)

        mode = my_db.get_user_property(chat_id_full, 'chat_mode')

        if chat_id_full in UNCAPTIONED_IMAGES:
            del UNCAPTIONED_IMAGES[chat_id_full]

        # удалить сохраненный текст
        if my_db.get_user_property(chat_id_full, 'saved_file_name'):
            my_db.delete_user_property(chat_id_full, 'saved_file_name')
            my_db.delete_user_property(chat_id_full, 'saved_file')

        if mode:
            if 'gemini' in mode or 'gemma' in mode or 'gemma' in mode or 'gemma' in mode:
                my_gemini3.reset(chat_id_full, mode)
            elif mode == 'openrouter':
                my_openrouter.reset(chat_id_full)

            elif mode == 'cloacked':
                my_openrouter_free.reset(chat_id_full)

            elif mode == 'qwen3':
                my_cerebras.reset(chat_id_full)
            elif mode == 'qwen3coder':
                my_cerebras.reset(chat_id_full)
            elif mode == 'gpt_oss':
                my_cerebras.reset(chat_id_full)
            elif mode == 'llama4':
                my_cerebras.reset(chat_id_full)
            elif mode in ('mistral', 'magistral'):
                my_mistral.reset(chat_id_full)
            elif mode in ('gpt-4o', 'gpt_41', 'gpt_41_mini', 'deepseek_r1', 'deepseek_v3'):
                my_github.reset(chat_id_full)
            elif mode == 'cohere':
                my_cohere.reset(chat_id_full)
            else:
                if say and message: # Отправлять сообщение только если пользователь инициировал и say=True
                    bot_reply_tr(message, 'History WAS NOT cleared.')
                return

        if say and message: # Отправлять сообщение только если пользователь инициировал и say=True
            bot_reply_tr(message, 'History cleared.')
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:reset_: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['reset', 'clear', 'new'], func=authorized_log)
@async_run
def reset(message: telebot.types.Message):
    """Clear chat history (bot's memory)"""
    try:
        chat_id_full = get_topic_id(message) # По умолчанию - текущий чат
        lang = get_lang(chat_id_full, message)
        COMMAND_MODE[chat_id_full] = ''

        target_chat_id_full = get_id_parameters_for_function(message, chat_id_full)

        if target_chat_id_full != chat_id_full: # Если был разобран валидный ID цели
            reset_(message, say=False, chat_id_full=target_chat_id_full) # Сброс истории админом, без ответа "History cleared"
            msg = f'{tr("History cleared for:", lang)} {target_chat_id_full}'
            bot_reply(message, msg) # Подтверждение админу
            return # Выход, чтобы избежать сброса истории для текущего пользователя

        reset_(message, say=True) # Сброс истории пользователем самому себе
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:reset: {unknown}\n{traceback_error}')


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
        bot_reply_tr(message, 'Keyboard removed. Use /start to create a new keyboard.')
    except Exception as unknown:
        my_log.log2(f'tb:remove_keyboard: {unknown}')


# полагаемся на то что обработчик текстов перенаправит сюда
# @bot.message_handler(commands=['style2'], func=authorized_admin)
# @async_run
def change_style2(message: telebot.types.Message):
    '''change style for specific chat'''
    try:
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
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:change_style2: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['save'], func=authorized_owner)
@async_run
def save_history(message: telebot.types.Message):
    """
    Сохранить переписку в формате .docx и .odt
    Используя конвертер маркдауна pandoc
    pandoc -f markdown -t odt 1.md -o output.odt
    """
    try:
        chat_id_full = get_topic_id(message)
        COMMAND_MODE[chat_id_full] = ''

        chat_id_full = get_id_parameters_for_function(message, chat_id_full)
        mode = my_db.get_user_property(chat_id_full, 'chat_mode')

        prompt = ''
        if any(mode.startswith(m) for m in ('gemini', 'gemma')):
            prompt = my_gemini3.get_mem_as_string(chat_id_full, md = True, model = mode) or ''
        if mode == 'openrouter':
            prompt = my_openrouter.get_mem_as_string(chat_id_full, md = True) or ''

        if mode == 'cloacked':
            prompt = my_openrouter_free.get_mem_as_string(chat_id_full, md = True) or ''

        if mode == 'qwen3':
            prompt = my_cerebras.get_mem_as_string(chat_id_full, md = True) or ''
        if mode == 'qwen3coder':
            prompt = my_cerebras.get_mem_as_string(chat_id_full, md = True) or ''
        if mode == 'gpt_oss':
            prompt = my_cerebras.get_mem_as_string(chat_id_full, md = True) or ''
        if mode == 'llama4':
            prompt = my_cerebras.get_mem_as_string(chat_id_full, md = True) or ''
        if mode in ('mistral', 'magistral'):
            prompt = my_mistral.get_mem_as_string(chat_id_full, md = True) or ''
        if mode in ('gpt-4o', 'gpt_41', 'gpt_41_mini', 'deepseek_r1', 'deepseek_v3'):
            prompt = my_github.get_mem_as_string(chat_id_full, md = True) or ''
        if mode == 'cohere':
            prompt = my_cohere.get_mem_as_string(chat_id_full, md = True) or ''

        if prompt:
            docx = my_pandoc.convert_markdown_to_document(prompt, 'docx')
            if docx:
                m = send_document(
                    message,
                    message.chat.id,
                    document=docx,
                    message_thread_id=message.message_thread_id,
                    caption='resp.docx',
                    visible_file_name = 'resp.docx',
                    reply_markup=get_keyboard('hide', message)
                )
                log_message(m)

            md = prompt.encode('utf-8', errors='ignore')
            if md:
                m = send_document(
                    message,
                    message.chat.id,
                    document=md,
                    message_thread_id=message.message_thread_id,
                    caption='resp.md',
                    visible_file_name = 'resp.md',
                    reply_markup=get_keyboard('hide', message)
                )
                log_message(m)
            if not md and not docx:
                bot_reply_tr(message, 'Error while saving history.')
        else:
            bot_reply_tr(message, 'Memory is empty, nothing to save.')
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:save_history: {unknown}\n\n{traceback_error}')
        bot_reply_tr(message, 'An error occurred while processing the request.')


@bot.message_handler(commands=['mem'], func=authorized_owner)
@async_run
def send_debug_history(message: telebot.types.Message):
    """
    Отправляет текущую историю сообщений пользователю.
    """
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)
        COMMAND_MODE[chat_id_full] = ''

        chat_id_full = get_id_parameters_for_function(message, chat_id_full)
        chat_mode = my_db.get_user_property(chat_id_full, 'chat_mode') or ''

        if 'gemini' in chat_mode or 'gemma' in chat_mode:
            if 'gemma' in chat_mode:
                prompt = chat_mode + '\n\n'
            else:
                prompt = 'Gemini ' + chat_mode + '\n\n'
            prompt += my_gemini3.get_mem_as_string(chat_id_full, model=chat_mode) or tr('Empty', lang)
        elif chat_mode == 'openrouter':
            prompt = 'Openrouter\n\n'
            prompt += my_openrouter.get_mem_as_string(chat_id_full) or tr('Empty', lang)

        elif chat_mode == 'cloacked':
            prompt = 'Cloacked\n\n'
            prompt += my_openrouter_free.get_mem_as_string(chat_id_full) or tr('Empty', lang)

        elif chat_mode == 'qwen3':
            prompt = 'Qwen 3 235b a22b\n\n'
            prompt += my_cerebras.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        elif chat_mode == 'qwen3coder':
            prompt = 'Qwen 3 Coder 480b\n\n'
            prompt += my_cerebras.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        elif chat_mode == 'gpt_oss':
            prompt = 'GPT OSS 120b\n\n'
            prompt += my_cerebras.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        elif chat_mode == 'llama4':
            prompt = 'Llama 4\n\n'
            prompt += my_cerebras.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        elif chat_mode == 'mistral':
            prompt = 'Mistral Large\n\n'
            prompt += my_mistral.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        elif chat_mode == 'magistral':
            prompt = 'Magistral Medium\n\n'
            prompt += my_mistral.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        elif chat_mode == 'gpt-4o':
            prompt = 'GPT-4o\n\n'
            prompt += my_github.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        elif chat_mode == 'gpt_41':
            prompt = 'GPT 4.1\n\n'
            prompt += my_github.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        elif chat_mode == 'gpt_41_mini':
            prompt = 'GPT 4.1 mini\n\n'
            prompt += my_github.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        elif chat_mode == 'deepseek_r1':
            prompt = 'DeepSeek R1\n\n'
            prompt += my_github.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        elif chat_mode == 'deepseek_v3':
            prompt = 'DeepSeek V3\n\n'
            prompt += my_github.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        elif chat_mode == 'cohere':
            prompt = 'Command A\n\n'
            prompt += my_cohere.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        else:
            my_log.log2(f'tb:mem: unknown mode {my_db.get_user_property(chat_id_full, "chat_mode")}')
            return
        bot_reply(message, prompt, parse_mode = '', disable_web_page_preview = True, reply_markup=get_keyboard('mem', message))
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:mem: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['load'], func=authorized_admin)
@async_run
def load_memory_handler(message: telebot.types.Message):
    """
    Загружает "память" (историю чата) другого пользователя в текущий чат.
    Команда доступна только для администраторов.

    Использование: /load_memory <user_id>
    <user_id> может быть в одном из следующих форматов:
    - Одно целое число (ID пользователя), например: '12345'. Будет преобразовано в '[12345] [0]'.
    - Два целых числа, разделенных пробелом (ID пользователя и ID темы), например: '12345 67890'. Будет преобразовано в '[12345] [67890]'.
    - Строка в формате '[num1] [num2]', например: '[12345] [0]'.
    """
    try:
        current_chat_id_full = get_topic_id(message)
        lang = get_lang(current_chat_id_full, message)

        arg = message.text.split(maxsplit=1)[1:]

        if not arg:
            bot_reply_tr(message, 'Использование: /load_memory <user_id>. Укажите ID пользователя, память которого нужно загрузить.', lang)
            return

        user_id_raw = arg[0].strip()
        target_user_id_str = ''

        # Проверяем, соответствует ли строка уже формату '[num1] [num2]'
        match = re.match(r'^\[(\d+)\] \[(\d+)\]$', user_id_raw)
        if match:
            target_user_id_str = user_id_raw
        else:
            # Попытка разобрать как одно или два числа
            parts = user_id_raw.split()
            if len(parts) == 1 and parts[0].isdigit():
                # Одно число: преобразуем в формат '[num] [0]'
                target_user_id_str = f'[{parts[0]}] [0]'
            elif len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                # Два числа: преобразуем в формат '[num1] [num2]'
                target_user_id_str = f'[{parts[0]}] [{parts[1]}]'
            else:
                # Неверный формат ID пользователя
                bot_reply_tr(message, 'Неверный формат ID пользователя. Используйте одно число (например, "12345"), два числа (например, "12345 67890") или формат "[num1] [num2]".', lang)
                return

        # Получаем chat_mode целевого пользователя
        target_chat_mode = my_db.get_user_property(target_user_id_str, 'chat_mode')

        if not target_chat_mode:
            bot_reply_tr(message, f'Не удалось определить режим чата для пользователя с ID: {target_user_id_str}. Память не может быть загружена.', lang)
            return

        # Получаем строковое представление памяти целевого пользователя
        target_mem_string = ''
        if 'gemini' in target_chat_mode or 'gemma' in target_chat_mode:
            # Предполагается, что my_gemini3.get_mem_as_string возвращает строковое представление памяти
            target_mem_string = my_gemini3.get_mem_as_string(target_user_id_str, model=target_chat_mode)
        elif target_chat_mode == 'openrouter':
            target_mem_string = my_openrouter.get_mem_as_string(target_user_id_str)

        elif target_chat_mode == 'cloacked':
            target_mem_string = my_openrouter_free.get_mem_as_string(target_user_id_str)

        elif target_chat_mode == 'qwen3':
            target_mem_string = my_cerebras.get_mem_as_string(target_user_id_str)
        elif target_chat_mode == 'qwen3coder':
            target_mem_string = my_cerebras.get_mem_as_string(target_user_id_str)
        elif target_chat_mode == 'gpt_oss':
            target_mem_string = my_cerebras.get_mem_as_string(target_user_id_str)
        elif target_chat_mode == 'llama4':
            target_mem_string = my_cerebras.get_mem_as_string(target_user_id_str)
        elif target_chat_mode == 'mistral' or target_chat_mode == 'magistral':
            target_mem_string = my_mistral.get_mem_as_string(target_user_id_str)
        elif target_chat_mode.startswith('gpt-4') or target_chat_mode.startswith('deepseek'):
            target_mem_string = my_github.get_mem_as_string(target_user_id_str)
        elif target_chat_mode == 'cohere':
            target_mem_string = my_cohere.get_mem_as_string(target_user_id_str)
        else:
            bot_reply_tr(message, f'Неизвестный режим чата ({target_chat_mode}) для пользователя с ID: {target_user_id_str}. Невозможно загрузить память.', lang)
            return

        if not target_mem_string:
            bot_reply_tr(message, f'У пользователя с ID: {target_user_id_str} нет сохраненной памяти для текущего режима чата.', lang)
            return

        # Конвертируем строковое представление памяти в mem_dict
        # Предполагается, что utils_llm.text_to_mem_dict может обработать этот формат
        # и что он доступен в текущем контексте (как показано в примере "load").
        mem_dict = utils_llm.text_to_mem_dict(target_mem_string)

        # Очищаем текущую память чата
        # Предполагается, что reset_() сбрасывает текущую активную память бота
        reset_(message, say=False) # 'say=False' чтобы не отправлять сообщение о сбросе

        # Загружаем полученную память в текущий чат
        # Предполагается, что add_to_bots_mem добавляет элементы в текущую память бота
        for k, v in mem_dict.items():
            add_to_bots_mem(k, v, current_chat_id_full)

        bot_reply_tr(message, f'Память успешно загружена из пользователя с ID: {target_user_id_str}.', lang)

    except Exception as unknown:
        # В случае ошибки, выводим её. В реальном приложении здесь может быть логирование.
        traceback_error = traceback.format_exc() # Если доступны, можно использовать для подробного лога
        my_log.log2(f'tb:load_memory_handler: {unknown}\n{traceback_error}')
        bot_reply_tr(message, f'Произошла ошибка при загрузке памяти: {unknown}', lang)


@bot.message_handler(commands=['restart', 'reboot'], func=authorized_admin)
def restart(message):
    """остановка бота. после остановки его должен будет перезапустить скрипт systemd"""
    try:
        global LOG_GROUP_DAEMON_ENABLED
        if isinstance(message, telebot.types.Message):
            bot_reply_tr(message, 'Restarting bot, please wait')
        my_log.log2('tb:restart: !!!RESTART!!!')
        bot.stop_polling()
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:restart: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['leave'], func=authorized_admin)
@async_run
def leave_thread(message: telebot.types.Message):
    """выйти из чата"""
    try:
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
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:leave: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['revoke'], func=authorized_admin) 
@async_run
def revoke(message: telebot.types.Message):
    """разбанить чат(ы)"""
    try:
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
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:revoke: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['temperature', 'temp'], func=authorized_owner)
@async_run
def set_new_temperature(message: telebot.types.Message):
    """Changes the temperature for Gemini
    /temperature <0...2>
    Default is 0 - automatic
    The lower the temperature, the less creative the response, the less nonsense and lies,
    and the desire to give an answer
    """
    try:
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

{tr('''Меняет температуру для ИИ (только для текст, на картинки это не влияет)

Температура это параметр, который контролирует степень случайности генерируемого текста. Чем выше температура, тем более случайным и креативным будет текст. Чем ниже температура, тем более точным и сфокусированным будет текст.

Например, если вы хотите, чтобы бот сгенерировал стихотворение, вы можете установить температуру выше 1,5. Это будет способствовать тому, что бот будет выбирать более неожиданные и уникальные слова. Однако, если вы хотите, чтобы бот сгенерировал текст, который является более точным и сфокусированным, вы можете установить температуру ниже 0,5. Это будет способствовать тому, что бот будет выбирать более вероятные и ожидаемые слова.

По-умолчанию 1''', lang)}

`/temperature 0.5`
`/temperature 1.5`
`/temperature 2`

{tr('Сейчас температура', lang)} = {my_db.get_user_property(chat_id_full, 'temperature') or 1}
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
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:temperature: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['atemp'], func=authorized_admin)
@async_run
def atemp_command(message: telebot.types.Message):
    """
    Admin command to set or view a new temperature for a specific user.
    Usage: /atemp <user_id as int> [new temperature]
    If no temperature is provided, shows the current temperature.
    """
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        parts = message.text.split()
        if len(parts) < 2 or len(parts) > 3:
            bot_reply_tr(message, "Usage: /atemp <user_id as int> [new temperature]. If temperature is not provided, shows the current temperature.")
            return

        user_id = int(parts[1])
        user_chat_id_full = f'[{user_id}] [0]'

        if len(parts) == 2:
            # Show the current temperature
            current_temp = my_db.get_user_property(user_chat_id_full, 'temperature')
            if current_temp is not None:
                bot_reply_tr(message, f"Current temperature for user {user_id} is {current_temp}.")
            else:
                bot_reply_tr(message, f"Temperature not set for user {user_id}.")
            return

        new_temp = float(parts[2])

        if not (0 <= new_temp <= 2):
            raise ValueError("Temperature must be between 0 and 2 (inclusive).")


        # Store the temperature directly in the user's properties.
        my_db.set_user_property(user_chat_id_full, 'temperature', new_temp)

        # If openrouter is used, update the temperature parameter
        if user_chat_id_full in my_openrouter.PARAMS:
            model, _, max_tokens, maxhistlines, maxhistchars = my_openrouter.PARAMS[user_chat_id_full]
            my_openrouter.PARAMS[user_chat_id_full] = [model, new_temp, max_tokens, maxhistlines, maxhistchars]

        bot_reply_tr(message, f"Temperature for user {user_id} set to {new_temp}.")

    except ValueError as ve:
        bot_reply_tr(message, str(ve))
    except Exception as e:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:atemp_command: {e}\n{traceback_error}')
        bot_reply_tr(message, f"An error occurred: {str(e)}")


@bot.message_handler(commands=['alang'], func=authorized_admin)
def change_user_language(message):
    '''set lang for specific user'''
    try:
        # Разделяем команду на части
        parts = message.text.split()
        if len(parts) != 3:
            bot_reply_tr(message, "Неправильный формат команды. Используйте: /alang <user_id_as_int> <lang_code_2_letters>")
            return

        user_id = int(parts[1])
        new_lang = parts[2].lower()

        # Проверка допустимости кода языка ISO 639-1
        if len(new_lang) != 2 or not langcodes.Language.get(new_lang):
            bot_reply_tr(message, "Недопустимый код языка. Используйте двухбуквенный код ISO 639-1.")

        # Обновляем язык пользователя в базе данных
        my_db.set_user_property(f'[{user_id}] [0]', 'lang', new_lang)

        # Подтверждение успешного изменения
        bot_reply_tr(message, f"Язык пользователя {user_id} успешно изменен на {new_lang}.")
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:change_user_language: {error}\n{traceback_error}')
        bot_reply_tr(message, f"Произошла ошибка при обработке команды. {error}")


@bot.message_handler(commands=['lang', 'language'], func=authorized_owner)
@async_run
def language(message: telebot.types.Message):
    """change locale"""
    try:
        chat_id_full = get_topic_id(message)

        COMMAND_MODE[chat_id_full] = ''

        lang = get_lang(chat_id_full, message)

        supported_langs_trans2 = ', '.join([x for x in my_init.supported_langs_trans])

        if len(message.text.split()) < 2:
            msg = f'/lang {tr("двухбуквенный код языка. Меняет язык бота. Ваш язык сейчас: ", lang)} <b>{lang}</b> ({tr(langcodes.Language.make(language=lang).display_name(language="en"), lang).lower()})\n\n{tr("Возможные варианты:", lang)}\n{supported_langs_trans2}\n\n/lang en\n/lang de\n/lang uk\n...'
            bot_reply(message, msg, parse_mode='HTML', reply_markup=get_keyboard('select_lang', message))
            return

        new_lang = message.text.split(maxsplit=1)[1].strip().lower()
        if new_lang == 'ua':
            new_lang = 'uk'
        if new_lang in my_init.supported_langs_trans:
            my_db.set_user_property(chat_id_full, 'lang', new_lang)
            msg = f'{tr("Язык бота изменен на:", new_lang)} <b>{new_lang}</b> ({tr(langcodes.Language.make(language=new_lang).display_name(language="en"), new_lang).lower()})'
            bot_reply(message, msg, parse_mode='HTML')
        else:
            msg = f'{tr("Такой язык не поддерживается:", lang)} <b>{new_lang}</b>\n\n{tr("Возможные варианты:", lang)}\n{supported_langs_trans2}'
            bot_reply(message, msg, parse_mode='HTML')
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:language: {unknown}\n{traceback_error}')


# @bot.message_handler(commands=['tts'], func=authorized)
@async_run
def tts(message: telebot.types.Message, caption = None):
    """ /tts [ru|en|uk|...] [+-XX%] <текст>
        /tts <URL>
    """
    try:
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
                    ('https://vimeo.com/' in url) or \
                    ('vk.com' in url and '/video-' in url) or \
                    ('//my.mail.ru/v/' in url and '/video/' in url):
                    text = my_sum.get_text_from_youtube(url, language = lang)
                    text = my_gemini3.rebuild_subtitles(text, lang, chat_id_full)
                    if text:
                        text = utils.bot_markdown_to_html(text)
                        if len(text) > 1 and len(text) < 40000:
                            add_to_bots_mem(f'/tts {url}', text, chat_id_full)
                        bot_reply(message, text, parse_mode='HTML',
                                reply_markup=get_keyboard('translate', message),
                                disable_web_page_preview=True)
                else:
                    text = my_sum.download_text([url, ], 100000, no_links = True)
                    if text:
                        if len(text) > 1 and len(text) < 40000:
                            add_to_bots_mem(f'/tts {url}', text, chat_id_full)
                        bot_reply(message, text, parse_mode='',
                                reply_markup=get_keyboard('translate', message),
                                disable_web_page_preview=True)
                return

        pattern = r'/tts\s+((?P<lang>' + '|'.join(my_init.supported_langs_tts) + r')\s+)?\s*(?P<rate>([+-]\d{1,3}%\s+))?\s*(?P<text>.+)'
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

        if not text or llang not in my_init.supported_langs_tts:
            help = f"""{tr('Usage:', lang)} /tts [ru|en|uk|...] [+-XX%] <{tr('text to speech', lang)}>|<URL>

+-XX% - {tr('acceleration with mandatory indication of direction + or -', lang)}

/tts hello all
/tts en hello, let me speak -  {tr('force english', lang)}
/tts en +50% Hello at a speed of 1.5x - {tr('force english and speed', lang)}
/tts en12 Tell me your name. - {tr('12th english voice - "en-KE-Chilemba" or "en-KE-Asilia"', lang)}

{tr('''en, en2, de, it(male), ko(male), pt(female) and fr voices are multilingual, you can use them to change voice for any language
(/tts ru привет) and (/tts fr привет) will say hello in russian with 2 different voices''', lang)}

{tr('Supported languages:', lang)} https://telegra.ph/Edge-TTS-voices-06-26

{tr('Для OpenAI голосов можно передать инструкцию как говорить, для этого в начале текста укажите инструкцию между знаками <>\n/tts <говори капризным голосом как у маленького ребенка> привет как дела', lang)}

{tr('Для Gemini голосов инструкция передается в свободной форме. Переключание между голосами /config', lang)}

{tr('Write what to say to get a voice message.', lang)}
"""

            COMMAND_MODE[chat_id_full] = 'tts'
            bot_reply(message, md2tgmd.escape(help), parse_mode = 'MarkdownV2',
                    reply_markup=get_keyboard('command_mode', message),
                    disable_web_page_preview = True)
            return

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
                my_log.log2(f'tb:tts:1:error: trying universal voice for {llang} {rate} {gender} {text}')
                audio = my_tts.tts(text, 'de', rate, gender=gender)
            if audio:
                if message.chat.type != 'private':
                    m = send_voice(
                        message,
                        message.chat.id,
                        audio,
                        reply_to_message_id = message.message_id,
                        reply_markup=get_keyboard('hide', message), caption=caption
                    )
                else:
                    # In private, you don't need to add a keyboard with a delete button,
                    # you can delete it there without it, and accidental deletion is useless
                    try:
                        m = send_voice(
                            message,
                            message.chat.id,
                            audio,
                            caption=caption
                        )
                    except telebot.apihelper.ApiTelegramException as error:
                        if 'Bad Request: VOICE_MESSAGES_FORBIDDEN' in str(error):
                            bot_reply_tr(message, '⚠️ You have disabled sending voice messages to you in Telegram settings.')
                            return

                log_message(m)
                my_log.log_echo(message, f'[Sent voice message] [{gender}]')
                my_db.add_msg(chat_id_full, f'TTS {gender}')
            else:
                bot_reply_tr(message, 'Could not dub. You may have mixed up the language, for example, the German voice does not read in Russian.')
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:tts:2: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['google','Google'], func=authorized)
@async_run
def google(message: telebot.types.Message):
    """ищет в гугле перед ответом"""
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)
        role = my_db.get_user_property(chat_id_full, 'role') or ''

        COMMAND_MODE[chat_id_full] = ''
        # проверка на подписку
        if not my_subscription.check_donate(message, chat_id_full, lang, COMMAND_MODE, CHECK_DONATE_LOCKS, BOT_ID, tr, bot_reply, get_keyboard):
            return

        if chat_id_full not in GOOGLE_LOCKS:
            GOOGLE_LOCKS[chat_id_full] = threading.Lock()

        # не ставить запросы от одного юзера в очередь
        if GOOGLE_LOCKS[chat_id_full].locked():
            return

        with GOOGLE_LOCKS[chat_id_full]:
            try:
                q = message.text.split(maxsplit=1)[1]
            except Exception as error2:
                help = f"""/google {tr('текст запроса', lang)}

/google {tr('сколько на земле людей, точные цифры и прогноз', lang)}

{tr('гугл, сколько на земле людей, точные цифры и прогноз', lang)}

{tr('используйте знак ! в начале запроса что бы использовать другой механизм поиска /google !самый глубокий бункер в мире', lang)}

{tr('Напишите запрос в гугл', lang)}
"""
                COMMAND_MODE[chat_id_full] = 'google'
                bot_reply(message, md2tgmd.escape(help), parse_mode = 'MarkdownV2', disable_web_page_preview = False, reply_markup=get_keyboard('command_mode', message))
                return

            with ShowAction(message, 'typing'):
                COMMAND_MODE[chat_id_full] = ''
                r, text = my_google.search_v3(
                    q.lower(),
                    lang,
                    chat_id=chat_id_full,
                    role=role
                )
                if r:
                    r = r.strip()
                if not r:
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

                add_to_bots_mem(message.text, r, chat_id_full)
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:google: {unknown}\n{traceback_error}')


def update_user_image_counter(chat_id_full: str, n: int):
    try:
        if not my_db.get_user_property(chat_id_full, 'image_generated_counter'):
            my_db.set_user_property(chat_id_full, 'image_generated_counter', 0)
        my_db.set_user_property(chat_id_full, 'image_generated_counter', my_db.get_user_property(chat_id_full, 'image_generated_counter') + n)
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:update_user_image_counter: {unknown}\n{traceback_error}')


def get_user_image_counter(chat_id_full: str) -> int:
    try:
        if not my_db.get_user_property(chat_id_full, 'image_generated_counter'):
            my_db.set_user_property(chat_id_full, 'image_generated_counter', 0)
        return my_db.get_user_property(chat_id_full, 'image_generated_counter')
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:get_user_image_counter: {unknown}\n{traceback_error}')
        return 0


def check_vip_user(chat_id_full: str) -> bool:
    '''проверяет есть ли у юзера ключи или звезды'''
    try:
        user_id = utils.extract_user_id(chat_id_full)
        have_keys = chat_id_full in my_gemini_general.USER_KEYS or chat_id_full in my_groq.USER_KEYS or \
                user_id in cfg.admins or \
                (my_db.get_user_property(chat_id_full, 'telegram_stars') or 0) >= 100
        return have_keys
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:check_vip_user: {unknown}\n{traceback_error}')
        return False


def check_vip_user_gemini(chat_id_full: str) -> bool:
    '''проверяет есть ли у юзера ключи от gemini'''
    try:
        user_id = utils.extract_user_id(chat_id_full)
        have_keys = chat_id_full in my_gemini_general.USER_KEYS or user_id in cfg.admins
        return have_keys
    except Exception as error:
        my_log.log2(f'tb:check_vip_user_gemini: {error}\n{chat_id_full}')
        return False


@bot.message_handler(commands=['downgrade', ], func=authorized_admin)
@async_run
def downgrade_handler(message: telebot.types.Message):
    '''ищет юзеров у которых уже есть больше 1000 сообщений и при этом нет ключей и звёзд,
    если у таких юзеров выбран чат режим gemini pro то меняет его на gemini
    снова включить pro они смогут только добавив какой-нибудь ключ или звёзды
    '''
    try:
        users = my_db.find_users_with_many_messages()
        counter = 0
        for user in users:
            chat_mode = my_db.get_user_property(user, 'chat_mode')
            if chat_mode == 'gemini15':
                if not check_vip_user(user):
                    my_db.set_user_property(user, 'chat_mode', 'gemini')
                    counter += 1
        bot_reply_tr(message, 'Поиск юзеров завершен.')
        bot_reply(message, str(counter))
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:downgrade: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['gem', 'Gem', 'GEM', 'GEN', 'Gen', 'gen'], func=authorized)
@async_run
def image_gemini_gen(message: telebot.types.Message):
    """
    Generates 1-4 images using Gemini 2.5 in parallel, with a fallback to Gemini 2.0.
    /gem <[1-4]> <prompt> - generates N images.
    """
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        COMMAND_MODE[chat_id_full] = ''

        if not my_subscription.check_donate(message, chat_id_full, lang, COMMAND_MODE, CHECK_DONATE_LOCKS, BOT_ID, tr, bot_reply, get_keyboard):
            return

        lock = IMG_GEN_LOCKS_GEM_IMG.setdefault(chat_id_full, threading.Lock())

        if lock.locked():
            if not (hasattr(cfg, 'ALLOW_PASS_NSFW_FILTER') and utils.extract_user_id(chat_id_full) in cfg.ALLOW_PASS_NSFW_FILTER):
                return

        help_text = f"""/gem <[1|2|3|4]> <prompt>

{tr('Generates N images with Gemini 2.5, fallback to 2.0 if needed', lang)}
"""

        with lock:
            parts = message.text.split(maxsplit=2)
            if len(parts) < 2:
                bot_reply(message, help_text)
                COMMAND_MODE[chat_id_full] = 'gem'
                return

            try:
                if len(parts) == 2:
                    num = 1
                    prompt = parts[1].strip()
                else:
                    num_str = parts[1].strip()
                    prompt = parts[2].strip()
                    if num_str in ('1', '2', '3', '4'):
                        num = int(num_str)
                    else:
                        prompt = f"{num_str} {prompt}"
                        num = 1
            except IndexError:
                bot_reply(message, help_text)
                return

            if not prompt:
                bot_reply(message, help_text)
                return

            with ShowAction(message, 'upload_photo'):
                try:
                    reprompt, negative_prompt = my_genimg.get_reprompt(prompt, '', chat_id_full)
                    if reprompt == 'MODERATION':
                        bot_reply_tr(message, 'Ваш запрос содержит потенциально неприемлемый контент.')
                        return
                    if not reprompt:
                        bot_reply_tr(message, 'Could not translate your prompt. Try again.')
                        return

                    images: List[bytes] = []
                    model_name = ''

                    # Attempt to generate with the primary model (2.5) in parallel
                    try:
                        with concurrent.futures.ThreadPoolExecutor(max_workers=num) as executor:
                            # Submit 'num' generation tasks to the thread pool
                            futures = {executor.submit(my_openrouter_free.txt2img, reprompt, user_id=chat_id_full) for _ in range(num)}

                            results = []
                            for future in concurrent.futures.as_completed(futures):
                                try:
                                    result = future.result()
                                    if result:
                                        results.append(result)
                                except Exception as exc:
                                    my_log.log2(f'tb:image_gemini_gen: thread generated an exception: {exc}')

                            images = results

                        if images:
                            model_name = my_openrouter_free.GEMINI25_FLASH_IMAGE
                    except Exception as e:
                        my_log.log2(f"tb:image_gemini_gen: primary model 2.5 failed: {e}")
                        images = [] # Ensure images is empty on failure

                    # Fallback to the secondary model (2.0) if the primary failed
                    if not images:
                        try:
                            images = my_genimg.gemini_flash(reprompt, num=num, user_id=chat_id_full) or []
                            if images:
                                model_name = my_gemini_genimg.MODEL
                        except Exception as e:
                            my_log.log2(f"tb:image_gemini_gen: fallback model 2.0 failed: {e}")
                            images = []

                    if not images:
                        bot_reply_tr(message, "Generation failed on both models.")
                        return

                    # --- Simplified media preparation ---
                    medias = []
                    bot_addr = f'https://t.me/{_bot_name}'

                    for img in images:
                        caption = f'{bot_addr} {model_name}\n\n{prompt}'
                        caption = re.sub(r"(\s)\1+", r"\1\1", caption)[:1024]
                        medias.append(telebot.types.InputMediaPhoto(img, caption=caption))

                    if medias:
                        chunk_size = 10
                        chunks = [medias[i:i + chunk_size] for i in range(0, len(medias), chunk_size)]

                        send_images_to_user(chunks, message, chat_id_full, medias, images)

                        if pics_group:
                            send_images_to_pic_group(chunks, message, chat_id_full, reprompt)

                        add_to_bots_mem(message.text, f'The bot successfully generated images on external services <service>{model_name}</service> based on the request <prompt>{prompt}</prompt>', chat_id_full)

                except Exception as e:
                    error_traceback = traceback.format_exc()
                    my_log.log2(f"tb:image_gemini_gen: {e}\n{error_traceback}")
                    bot_reply_tr(message, tr("An error occurred during image generation.", lang))

    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:image_gemini_gen: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['flux'], func=authorized)
@async_run
def image_flux_gen(message: telebot.types.Message):
    """Generates an image using the Flux Nebius model ('black-forest-labs/flux-dev').
    /flux <prompt>
    """
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        COMMAND_MODE[chat_id_full] = ''

        # Check for donations
        if not my_subscription.check_donate(message, chat_id_full, lang, COMMAND_MODE, CHECK_DONATE_LOCKS, BOT_ID, tr, bot_reply, get_keyboard):
            return

        # Lock to prevent concurrent requests
        if chat_id_full in IMG_GEN_LOCKS_FLUX:
            lock = IMG_GEN_LOCKS_FLUX[chat_id_full]
        else:
            lock = threading.Lock()
            IMG_GEN_LOCKS_FLUX[chat_id_full] = lock

        # не ставить запросы от одного юзера в очередь
        if lock.locked():
            if hasattr(cfg, 'ALLOW_PASS_NSFW_FILTER') and utils.extract_user_id(chat_id_full) in cfg.ALLOW_PASS_NSFW_FILTER:
                pass
            else:
                return

        help_text = f"""/flux <prompt>

{tr('Generate images using the Flux Nebius model ("black-forest-labs/flux-dev").', lang)}
/flux {tr('cat in space', lang)}
"""

        with lock:
            # Get prompt
            parts = message.text.split(maxsplit=1)  # Split into command and prompt
            if len(parts) < 2:
                bot_reply(message, help_text)
                return

            prompt = parts[1].strip()

            if not prompt:
                bot_reply(message, help_text)
                return

            with ShowAction(message, 'upload_photo'):
                try:
                    # Get English prompt and negative prompt using the function
                    reprompt, negative_prompt = my_genimg.get_reprompt(prompt, '', chat_id_full)
                    if reprompt == 'MODERATION':
                        bot_reply_tr(message, 'Ваш запрос содержит потенциально неприемлемый контент.')
                        return
                    if not reprompt:
                        bot_reply_tr(message, 'Could not translate your prompt. Try again.')
                        return

                    # Directly use the desired model
                    model_name = 'black-forest-labs/flux-dev'
                    images = my_genimg.flux_nebius_gen1(reprompt, negative_prompt, model=model_name)
                    if images:
                        my_db.add_msg(chat_id_full, f'img {model_name} Nebius')
                    caption_model = model_name

                    medias = []
                    for i in images:
                        bot_addr = f'https://t.me/{_bot_name}'
                        caption_ = f'{bot_addr} {caption_model}\n\n{prompt}'
                        caption_ = re.sub(r"(\s)\1+", r"\1\1", caption_)[:900]
                        medias.append(telebot.types.InputMediaPhoto(i, caption=caption_))

                    if medias:
                        # делим картинки на группы до 10шт в группе, телеграм не пропускает больше за 1 раз
                        chunk_size = 10
                        chunks = [medias[i:i + chunk_size] for i in range(0, len(medias), chunk_size)]

                        # Send images to user
                        send_images_to_user(chunks, message, chat_id_full, medias, images)

                        # Send images to pics group (if enabled)
                        if pics_group:
                            send_images_to_pic_group(
                                chunks=chunks,
                                message=message,
                                chat_id_full=chat_id_full,
                                prompt=reprompt,
                            )

                        add_to_bots_mem(message.text, f'The bot successfully generated images on the external service <service>Nebius</service> based on the request <prompt>{prompt}</prompt>', chat_id_full)
                    else:
                        bot_reply_tr(message, tr("Image generation failed. (No images generated.)\n\nA prompt that is too long can cause this error. You can try using '!' before the prompt to fix it. In this case, the prompt must be in English only.", lang))

                except Exception as e:
                    error_traceback = traceback.format_exc()
                    my_log.log2(f"tb:image_flux_gen: {e}\n{error_traceback}")
                    bot_reply_tr(message, tr("An error occurred during image generation.", lang))
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:image_flux_gen: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['bing', 'Bing'], func=authorized)
@async_run
def image_bing_gen(message: telebot.types.Message):
    try:
        chat_id_full = get_topic_id(message)
        IMG_MODE_FLAG[chat_id_full] = 'bing'
        if my_db.get_user_property(chat_id_full, 'blocked_bing'):
            bot_reply_tr(message, 'Bing вас забанил.')
            time.sleep(2)
            return
        message.text += '[{(BING)}]'
        image_gen(message)
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:image_bing_gen: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['gpt', 'Gpt', 'GPT'], func=authorized)
@async_run
def image_bing_gen_gpt(message: telebot.types.Message):
    try:
        chat_id_full = get_topic_id(message)
        IMG_MODE_FLAG[chat_id_full] = 'gpt'
        if my_db.get_user_property(chat_id_full, 'blocked_bing'):
            bot_reply_tr(message, 'Bing вас забанил.')
            time.sleep(2)
            return
        message.text += '[{(GPT)}]'
        image_gen(message)
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:image_bing_gen: {unknown}\n{traceback_error}')


@async_run
def send_images_to_user(
    chunks: list,
    message: telebot.types.Message,
    chat_id_full: str,
    medias: list,
    images: list,):
    '''Отправляем картинки юзеру асинхронно
    '''
    try:
        for x in chunks:
            msgs_ids = send_media_group(
                message,
                message.chat.id,
                x,
                reply_to_message_id=message.message_id
            )

        try:
            log_message(msgs_ids)
        except UnboundLocalError:
            pass

        update_user_image_counter(chat_id_full, len(medias))

        log_msg = '[Send images] '
        for x in images:
            if isinstance(x, str):
                log_msg += x + ' '
            elif isinstance(x, bytes):
                log_msg += f'[binary file {round(len(x)/1024)}kb] '
        my_log.log_echo(message, log_msg)
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:send_images_to_user: {unknown}\n{traceback_error}')


@async_run
def send_images_to_pic_group(
    chunks: list,
    message: telebot.types.Message,
    chat_id_full: str,
    prompt: str,):
    '''Отправляем картинки в группу галереи асинхронно
    '''
    try:
        with LOCK_PICS_GROUP:

            translated_prompt = tr(prompt, 'ru', save_cache=False)

            hashtag = 'H' + chat_id_full.replace('[', '').replace(']', '')
            bot.send_message(pics_group, f'{utils.html.unescape(prompt[:800])} | #{hashtag} {message.from_user.id}',
                            link_preview_options=telebot.types.LinkPreviewOptions(is_disabled=False))

            ratio = fuzz.ratio(translated_prompt, prompt)
            if ratio < 70:
                bot.send_message(pics_group, f'{utils.html.unescape(translated_prompt[:800])} | #{hashtag} {message.from_user.id}',
                                link_preview_options=telebot.types.LinkPreviewOptions(is_disabled=False))

            for x in chunks:
                msgs = send_media_group(message, pics_group, x)
                # не посылать логи при отправке картинок в группу для логов Ж)
                # log_message(msgs)


    except Exception as unknown:
        if 'A request to the Telegram API was unsuccessful. Error code: 429. Description: Too Many Requests: retry after' in str(unknown):
            return
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:image:send_media_group_pics_group3: {unknown}\n\n{traceback_error}')


# вариант с такой лямбдой вызывает проблемы в функции is_for_me, туда почему то приходит команда без имени бота
# @bot.message_handler(func=lambda message: authorized(message) and message.text.split()[0].lower() in ['/image', '/img', '/i', '/imagine', '/generate', '/gen', '/art', '/picture', '/pic'])


@bot.message_handler(
    commands=[
        'image', 'image:', 'Image:', 'IMAGE:',
        'imag', 'Imag', 'IMAG',
        'img', 'IMG', 'Image', 'Img', 'i', 'I',
        'imagine', 'imagine:', 'Imagine', 'Imagine:',
        'generate', 'gen', 'Generate', 'Gen',
        'art', 'Art', 'picture', 'pic', 'Picture', 'Pic'
    ],
    func=authorized
)
@async_run
def image_gen(message: telebot.types.Message):
    """Generates a picture from a description"""
    my_cmd_img.image_gen(
        message=message,

        # Core objects and constants
        _bot_name = _bot_name,
        BOT_ID = BOT_ID,
        pics_group = pics_group,

        # Global state dictionaries
        IMG_MODE_FLAG = IMG_MODE_FLAG,
        COMMAND_MODE = COMMAND_MODE,
        IMG_GEN_LOCKS = IMG_GEN_LOCKS,
        BING_FAILS = BING_FAILS,
        CHECK_DONATE_LOCKS = CHECK_DONATE_LOCKS,

        # Helper functions and classes
        get_topic_id=get_topic_id,
        get_lang=get_lang,
        tr=tr,
        bot_reply=bot_reply,
        bot_reply_tr=bot_reply_tr,
        get_keyboard=get_keyboard,
        add_to_bots_mem=add_to_bots_mem,
        send_images_to_user=send_images_to_user,
        send_images_to_pic_group=send_images_to_pic_group,
        ShowAction=ShowAction,
        NoLock=NoLock,

        # Command handler functions
        image_flux_gen=image_flux_gen,
    )


@bot.message_handler(commands=['stats', 'stat'], func=authorized_admin)
@async_run
def stats(message: telebot.types.Message):
    """Функция, показывающая статистику использования бота."""
    try:
        with ShowAction(message, 'typing'):
            model_usage30 = my_db.get_model_usage(30)
            model_usage7 = my_db.get_model_usage(7)
            model_usage1 = my_db.get_model_usage(1)

            msg = f'Total messages in DB: {my_db.count_msgs_all()}'

            def format_model_usage(model_usage):
                output = ""
                if model_usage:
                    sorted_usage = sorted(model_usage.items(), key=lambda item: item[1], reverse=True)
                    for model, count in sorted_usage:
                        if not model.startswith('img '):
                            output += f'{model} - {count}\n'
                return output

            msg += '\n\n1 day\n'
            msg += format_model_usage(model_usage1)
            msg += '\n\n7 days\n'
            msg += format_model_usage(model_usage7)
            msg += '\n\n30 days\n'
            msg += format_model_usage(model_usage30)

            msg += f'\n\nTotal users: {my_db.get_total_msg_users()}'
            msg += f'\n\nActive users in 1 day: {my_db.get_total_msg_users_in_days(1)}'
            msg += f'\nActive users in 7 days: {my_db.get_total_msg_users_in_days(7)}'
            msg += f'\nActive users in 30 days: {my_db.get_total_msg_users_in_days(30)}'

            msg += f'\n\nNew users in 1 day: {my_db.count_new_user_in_days(1)}'
            msg += f'\nNew users in 7 day: {my_db.count_new_user_in_days(7)}'
            msg += f'\nNew users in 30 day: {my_db.count_new_user_in_days(30)}'

            msg += f'\n\nGemini keys: {len(my_gemini_general.ALL_KEYS)+len(cfg.gemini_keys)}'
            msg += f'\nGroq keys: {len(my_groq.ALL_KEYS)}'
            msg += f'\nMistral keys: {len(my_mistral.ALL_KEYS)}'
            msg += f'\nCohere keys: {len(my_cohere.ALL_KEYS)}'
            msg += f'\nGithub keys: {len(my_github.ALL_KEYS)}'
            msg += f'\nCerebras keys: {len(my_cerebras.ALL_KEYS)}'
            msg += f'\n\n Uptime: {get_uptime()}'

            usage_plots_image = my_stat.draw_user_activity(90)
            stat_data = my_stat.get_model_usage_for_days(90)
            # llm
            usage_plots_image2 = my_stat.visualize_usage(stat_data, mode = 'llm')
            # img
            usage_plots_image3 = my_stat.visualize_usage(stat_data, mode = 'img')

            bot_reply(message, msg)

            if usage_plots_image:
                m = send_photo(
                    message,
                    message.chat.id,
                    usage_plots_image,
                    disable_notification=True,
                    reply_to_message_id=message.message_id,
                    reply_markup=get_keyboard('hide', message),
                )
                log_message(m)

            if usage_plots_image2:
                m = send_photo(
                    message,
                    message.chat.id,
                    usage_plots_image2,
                    disable_notification=True,
                    reply_to_message_id=message.message_id,
                    reply_markup=get_keyboard('hide', message),
                )
                log_message(m)

            if usage_plots_image3:
                m = send_photo(
                    message,
                    message.chat.id,
                    usage_plots_image3,
                    disable_notification=True,
                    reply_to_message_id=message.message_id,
                    reply_markup=get_keyboard('hide', message),
                )
                log_message(m)
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:stats: {unknown}\n{traceback_error}')


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


@bot.message_handler(commands=['block'], func=authorized_admin)
@async_run
def block_command_handler(message: telebot.types.Message):
    """Handles the /block command to manage user blocking."""
    try:
        parts = message.text.split()
        if len(parts) < 2 or len(parts) > 3:
            bot_reply_tr(message, 'Usage: /block <add|add2|add3|del|del2|del3|list|list2|list3> <user_id>')
            return

        action, user_id = parts[1].lower(), extract_user_id(message)

        if not user_id and not action.startswith('list'):
            bot_reply_tr(message, "Неверный формат user_id")
            return

        level = 1
        if action.endswith("2") or action.endswith("3"):
            level = int(action[-1])
            action = action[:-1]

        if action == 'add':
            block_user(message, user_id, level, 'set')
        elif action == 'del':
            block_user(message, user_id, level, 'delete')
        elif action == 'list':
            list_blocked_users(message, level)
        else:
            bot_reply_tr(message, 'Usage: /block <add|add2|add3|del|del2|del3|list|list2|list3> <user_id>')
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:block_command_handler: {unknown}\n{traceback_error}')


def block_user(message: telebot.types.Message, user_id: int, level: int, operation: str):
    """Adds or removes a user from the block list with the specified level."""
    try:
        lang = get_lang(get_topic_id(message), message)

        block_properties = {
            1: 'blocked',
            2: 'blocked_bing',
            3: 'blocked_totally'
        }
        block_property = block_properties.get(level)

        if not block_property:
            bot_reply_tr(message, 'Invalid block level')
            return

        if operation == 'set':
            if not my_db.get_user_property(user_id, 'first_meet'):
                bot_reply(message, f'❌ {tr("Пользователь", lang)} {user_id} {tr("не найден в базе", lang)}\n')
                return
            my_db.set_user_property(user_id, block_property, True)
            bot_reply(message, f'✅ {tr("Пользователь", lang)} {user_id} {tr("добавлен в стоп-лист", lang)} (level {level})\n')

        elif operation == 'delete':
            if my_db.get_user_property(user_id, block_property):
                my_db.delete_user_property(user_id, block_property)
                bot_reply(message, f'✅ {tr("Пользователь", lang)} {user_id} {tr("удален из стоп-листа", lang)} (level {level})\n')
            else:
                bot_reply(message, f'❌ {tr("Пользователь", lang)} {user_id} {tr("не найден в стоп-листе", lang)} (level {level})\n')
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:block_user: {unknown}\n{traceback_error}')


def list_blocked_users(message: telebot.types.Message, level: int):
    """Displays the list of blocked users with the specified level."""
    try:
        lang = get_lang(get_topic_id(message), message)

        block_lists = {
            1: my_db.get_user_all_bad_ids,
            2: my_db.get_user_all_bad_bing_ids,
            3: my_db.get_user_all_bad_totally_ids
        }
        get_blocked_users = block_lists.get(level)

        if not get_blocked_users:
            bot_reply_tr(message, 'Invalid block level')
            return

        blocked_ids = get_blocked_users()

        if blocked_ids:
            bot_reply(message, '\n'.join(blocked_ids))
        else:
            bot_reply(message, f'{tr("Нет таких пользователей", lang)} (level {level})')
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:list_blocked_users: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['msg', 'm', 'message', 'mes'], func=authorized_admin)
@async_run
def message_to_user(message: telebot.types.Message):
    """отправка сообщения от админа юзеру"""
    try:
        # Extract everything after the command itself
        command_parts = message.text.split(maxsplit=1)
        if len(command_parts) < 2:
            bot_reply_tr(message, 'Usage: /msg <target_id> <text>\nTarget can be a user_id or a full [chat_id] [thread_id].')
            return

        args_str = command_parts[1].strip()

        target_id_str: Optional[str] = None
        text_to_send: Optional[str] = None
        chat_id: Optional[int] = None
        thread_id: int = 0

        # Pattern 1: Match [chat_id] [thread_id] format at the beginning of the arguments
        full_id_match = re.match(r'(\[-?\d+\]\s+\[\d+\])\s+(.*)', args_str, re.DOTALL)
        # Pattern 2: Match a simple integer user_id at the beginning
        simple_id_match = re.match(r'(-?\d+)\s+(.*)', args_str, re.DOTALL)

        if full_id_match:
            # Found the [chat_id] [thread_id] format
            target_id_str = full_id_match.group(1)
            text_to_send = full_id_match.group(2)
            # Extract numbers from the captured string
            ids = re.findall(r'-?\d+', target_id_str)
            chat_id = int(ids[0])
            thread_id = int(ids[1])
        elif simple_id_match:
            # Found the simple user_id format
            target_id_str = simple_id_match.group(1)
            text_to_send = simple_id_match.group(2)
            chat_id = int(target_id_str)
            thread_id = 0  # DMs don't have threads
        else:
            # No valid format found
            bot_reply_tr(message, 'Invalid command format. Could not find a valid target ID and message text.')
            return

        if not text_to_send:
            bot_reply_tr(message, "Message text cannot be empty.")
            return

        # Add a notification prefix for the user
        final_text = f"[Admin Notification] {text_to_send}"

        # Send the message to the parsed target
        bot.send_message(
            chat_id,
            final_text,
            message_thread_id=thread_id,
            disable_notification=True,
            parse_mode=''
        )
        bot_reply_tr(message, 'Message sent.')
        # Log the original text without the prefix
        my_log.log_echo(message, f'Admin sent message to {target_id_str}: {text_to_send}')

    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:message_to_user: {unknown}\n{traceback_error}')
        bot_reply_tr(message, f"An error occurred: {str(unknown)}")


@bot.message_handler(commands=['alert'], func=authorized_admin)
@async_run
def alert(message: telebot.types.Message):
    """Сообщение всем кого бот знает."""
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        if message.chat.id in cfg.admins:
            message.text = my_log.restore_message_text(message.text, message.entities)
            text = message.text[7:]
            if text:
                text = utils.bot_markdown_to_html(text)
                text = f'<b>{tr("Широковещательное сообщение от Верховного Администратора, не обращайте внимания", lang)}</b>' + '\n\n\n' + text

                ids = my_alert.get_targets(DDOS_BLOCKED_USERS, chat_id_full)

                for target in ids:
                    try:
                        bot.send_message(chat_id = target, message_thread_id = 0, text = text, parse_mode='HTML',
                                        disable_notification = True, reply_markup=get_keyboard('translate', message))
                        my_log.log2(f'tb:alert: sent to {target}')
                    except Exception as error2:
                        my_log.log2(f'tb:alert: FAILED sent to {target} {error2}')
                    time.sleep(0.3)
                ids = [str(x) for x in ids]
                bot_reply(message, 'Sent to: ' + ', '.join(ids) + '\n\nTotal: ' + str(len(ids)))
                return

        bot_reply_tr(message, '/alert <текст сообщения которое бот отправит всем кого знает, форматирование маркдаун> Только администраторы могут использовать эту команду')
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:alert: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['ask2', 'а2'], func=authorized)
@async_run
def ask_file2(message: telebot.types.Message):
    '''ответ по сохраненному файлу, вариант с чистым промптом'''
    try:
        message.text += '[123CLEAR321]'
        ask_file(message)
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:ask_file2: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['ask', 'а'], func=authorized)
@async_run
def ask_file(message: telebot.types.Message):
    '''ответ по сохраненному файлу, админ может запросить файл другого пользователя'''
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)
        role = my_db.get_user_property(chat_id_full, 'role')

        COMMAND_MODE[chat_id_full] = ''

        chat_id_full_target = get_id_parameters_for_function(message, chat_id_full)
        try:
            command_parts = message.text.split(maxsplit=2)
            if command_parts:
                if len(command_parts) > 1 and command_parts[1].isdigit() and message.from_user.id in cfg.admins:
                    # Админ запрашивает файл другого пользователя
                    chat_id_full_target = f'[{command_parts[1]}] [0]'
                    fname_target = my_db.get_user_property(chat_id_full_target, 'saved_file_name').strip()
                    ftext_target = my_db.get_user_property(chat_id_full_target, 'saved_file').strip()
                    if fname_target and ftext_target:
                        # save to chat_id_full
                        my_db.set_user_property(chat_id_full, 'saved_file_name', fname_target)
                        my_db.set_user_property(chat_id_full, 'saved_file', ftext_target)
                    message.text = command_parts[0] + ' '
                    if len(command_parts) == 3:
                        message.text += command_parts[2]
        except (IndexError, AttributeError):
            pass

        try:
            query = message.text.split(maxsplit=1)[1].strip()
        except IndexError:
            bot_reply_tr(
                message,
                'Usage:\n/ask <query saved text>\n? <query saved text> \n\nWhen you send a text document or link to the bot, it remembers the text, and in the future you can ask questions about the saved text.\n\nExamples:\n/ask What is the main topic of the text?\n/ask Summarize the text in 3 sentences\n? How many persons was invited.',
                )
            if my_db.get_user_property(chat_id_full, 'saved_file_name'):
                msg = f'{tr("Загружен файл/ссылка:", lang)} {my_db.get_user_property(chat_id_full, "saved_file_name")}\n\n{tr("Размер текста:", lang)} {len(my_db.get_user_property(chat_id_full, "saved_file")) or 0}\n\n{tr("Напишите запрос к этому файлу или нажмите [Отмена]", lang)}'
                bot_reply(
                    message,
                    msg,
                    disable_web_page_preview = True,
                    reply_markup=get_keyboard('download_saved_text', message)
                    )
                COMMAND_MODE[chat_id_full] = 'ask'
            return

        if my_db.get_user_property(chat_id_full, 'saved_file_name'):
            with ShowAction(message, 'typing'):

                ASK_MACRO = {}
                try:
                    with open('ask_macro.txt.dat', 'r', encoding = 'utf8') as f:
                        lines = f.readlines()
                        lines = [x.strip() for x in lines]
                    for line in lines:
                        if line:
                            cmd, subs = line.split(maxsplit=1)
                            ASK_MACRO[cmd] = subs
                except:
                    pass
                for x in ASK_MACRO.keys():
                    if query == x:
                        query = ASK_MACRO[x]
                        break

                if message.text.endswith('[123CLEAR321]'):
                    message.text = message.text[:-13]
                    q = f"{message.text}\n\n{tr('URL/file:', lang)} {my_db.get_user_property(chat_id_full, 'saved_file_name')}\n\n{tr('Saved text:', lang)} {my_db.get_user_property(chat_id_full, 'saved_file')}"
                else:
                    q = f'''{tr('Answer the user`s query using saved text and your own mind, answer plain text with fancy markdown formatting, do not use code block for answer.', lang)}

{tr('User query:', lang)} {query}

{tr('URL/file:', lang)} {my_db.get_user_property(chat_id_full, 'saved_file_name')}

{tr('Saved text:', lang)} {my_db.get_user_property(chat_id_full, 'saved_file')}
'''
                temperature = my_db.get_user_property(chat_id_full, 'temperature') or 1
                result = my_gemini3.chat(q[:my_gemini_general.MAX_SUM_REQUEST], temperature=temperature, model = cfg.gemini25_flash_model, system=role, do_not_update_history=True, empty_memory=True, chat_id=chat_id_full)
                if not result:
                    result = my_gemini3.chat(q[:my_gemini_general.MAX_SUM_REQUEST], temperature=temperature, model = cfg.gemini_flash_model, system=role, do_not_update_history=True, empty_memory=True, chat_id=chat_id_full)
                if not result:
                    result = my_cohere.ai(q[:my_cohere.MAX_SUM_REQUEST], system=role)
                if not result:
                    result = my_mistral.ai(q[:my_mistral.MAX_SUM_REQUEST], system=role)
                if not result:
                    result = my_groq.ai(q[:my_groq.MAX_SUM_REQUEST], temperature=temperature, max_tokens_ = 4000, system=role)

                if result:
                    answer = utils.bot_markdown_to_html(result)
                    bot_reply(message, answer, parse_mode='HTML', reply_markup=get_keyboard('translate', message))

                    add_to_bots_mem(
                        tr("The user asked to answer the question based on the saved text:", lang) + ' ' + \
                        f"{my_db.get_user_property(chat_id_full, 'saved_file_name')} \n {query}",
                        result,
                        chat_id_full
                    )
                else:
                    bot_reply_tr(message, 'No reply from AI')
                    return
        else:
            bot_reply_tr(message, 'Usage:\n/ask <query saved text>\n? <query saved text> \n\nWhen you send a text document or link to the bot, it remembers the text, and in the future you can ask questions about the saved text.\n\nExamples:\n/ask What is the main topic of the text?\n/ask Summarize the text in 3 sentences\n? How many persons was invited.')
            bot_reply_tr(message, 'No text was saved')
            return
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:ask: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['ping', 'echo'])
def ping(message: telebot.types.Message):
    try:
        bot.reply_to(message, 'pong')
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:ping: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['sum', 'Sum'], func=authorized)
@async_run
def summ_text(message: telebot.types.Message):
    '''
    Пересказ текстов, видеороликов, ссылок
    '''
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)
        role = my_db.get_user_property(chat_id_full, 'role') or ''

        COMMAND_MODE[chat_id_full] = ''
        # проверка на подписку
        if not my_subscription.check_donate(message, chat_id_full, lang, COMMAND_MODE, CHECK_DONATE_LOCKS, BOT_ID, tr, bot_reply, get_keyboard):
            return

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

                        #смотрим нет ли в кеше ответа на этот урл
                        r = my_db.get_from_sum(url_id)

                        if r:
                            with ShowAction(message, 'typing'):
                                my_db.set_user_property(chat_id_full, 'saved_file_name', url + '.txt')
                                text = my_sum.summ_url(url, lang = lang, deep = False, download_only=True, role=role)
                                my_db.set_user_property(chat_id_full, 'saved_file', text)
                                rr = utils.bot_markdown_to_html(r)
                                ask = tr('Use /ask command to query or delete this file. Example:\n/ask generate a short version of part 1.\n? How many persons was invited.', lang)
                                bot_reply(message, rr + '\n' + ask, disable_web_page_preview = True,
                                                    parse_mode='HTML',
                                                    reply_markup=get_keyboard('translate', message))
                                add_to_bots_mem(message.text, r, chat_id_full)
                                return

                        with ShowAction(message, 'typing'):
                            res = ''
                            try:
                                has_subs = my_sum.check_ytb_subs_exists(url, lang = lang)
                                if not has_subs and ('/youtu.be/' in url or 'youtube.com/' in url):
                                    bot_reply_tr(message, 'Видео с ютуба не содержит субтитров или не получилось их скачать.')
                                    return
                                if url.lower().startswith('http') and url.lower().endswith(('.mp3', '.ogg', '.aac', '.m4a', '.flac', '.mp4')):
                                    bot_reply_tr(message, 'Audiofile download and transcription started, please wait for a while.')
                                res, text = my_sum.summ_url(url, lang = lang, deep = False, role=role)
                                my_db.set_user_property(chat_id_full, 'saved_file_name', url + '.txt')
                                my_db.set_user_property(chat_id_full, 'saved_file', text)
                            except Exception as error2:
                                print(error2)
                                bot_reply_tr(
                                    message,
                                    'Не нашел тут текста. Возможно что в видео на ютубе нет субтитров или страница слишком динамическая '
                                    'и не показывает текст без танцев с бубном, или сайт меня не пускает.\n\nЕсли очень хочется '
                                    'то отправь мне текстовый файл .txt (utf8) с текстом этого сайта и подпиши <code>что там</code>',
                                    parse_mode='HTML')
                                return
                            if res:
                                rr = utils.bot_markdown_to_html(res)
                                ask = tr('Use /ask command to query or delete this file. Example:\n/ask generate a short version of part 1.\n? How many persons was invited.', lang)
                                bot_reply(message, rr + '\n' + ask, parse_mode='HTML',
                                                    disable_web_page_preview = True,
                                                    reply_markup=get_keyboard('translate', message))
                                my_db.set_sum_cache(url_id, res)
                                add_to_bots_mem(message.text, res, chat_id_full)
                                return
                            else:
                                bot_reply_tr(message, 'Не смог прочитать текст с этой страницы.')
                                return
            help = f"""{tr('Пример:', lang)} /sum https://youtu.be/3i123i6Bf-U

{tr('Или просто отправьте ссылку без текста.', lang)}

{tr('Давайте вашу ссылку и я перескажу содержание', lang)}"""
            COMMAND_MODE[chat_id_full] = 'sum'
            bot_reply(message, md2tgmd.escape(help), parse_mode = 'MarkdownV2', reply_markup=get_keyboard('command_mode', message))
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:summ_text: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['sum2'], func=authorized)
@async_run
def summ2_text(message: telebot.types.Message):
    # убирает запрос из кеша если он там есть и делает запрос снова
    try:
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
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:summ2_text: {unknown}\n{traceback_error}')


#@bot.message_handler(commands=['trans', 'tr', 't'], func=authorized)
@async_run
def trans(message: telebot.types.Message):
    '''
    Перевод текста
    '''
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        COMMAND_MODE[chat_id_full] = ''
        # проверка на подписку
        if not my_subscription.check_donate(message, chat_id_full, lang, COMMAND_MODE, CHECK_DONATE_LOCKS, BOT_ID, tr, bot_reply, get_keyboard):
            return

        help = f"""/trans [en|ru|uk|..] {tr('''текст для перевода на указанный язык

Если не указан то на ваш язык.''', lang)}

/trans uk hello world
/trans was ist das

{tr('Напишите что надо перевести', lang)}
"""
        if message.text.startswith('/t '):
            message.text = message.text.replace('/t', '/trans', 1)
        if message.text.startswith('/tr '):
            message.text = message.text.replace('/tr', '/trans', 1)
        # разбираем параметры
        # регулярное выражение для разбора строки
        pattern = r'^\/trans\s+((?:' + '|'.join(my_init.supported_langs_trans) + r')\s+)?\s*(.*)$'
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
            translated = tr(text, llang, save_cache=False, help = "Telegram bot's user used the /trans <lang> <text> command to translate this text.")
            if translated and translated != text:
                my_db.add_msg(chat_id_full, cfg.gemini25_flash_model)
                html = utils.bot_markdown_to_html(translated)
                bot_reply(message, html, parse_mode='HTML', reply_markup=get_keyboard('translate', message))
                add_to_bots_mem(message.text, translated, chat_id_full)
            else:
                # bot_reply_tr(message, 'Ошибка перевода')
                message.text = text
                do_task(message)
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:trans: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['name'], func=authorized_owner)
@async_run
def send_name(message: telebot.types.Message):
    """Меняем имя если оно подходящее, содержит только русские и английские буквы и не
    слишком длинное"""
    try:
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
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:send_name: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['start'], func = authorized_log)
@async_run
def send_welcome_start(message: telebot.types.Message):
    # Отправляем приветственное сообщение
    try:
        load_msgs()
        # проверить не изменился ли файл содержащий сообщения /start
        user_have_lang = None
        try:
            user_have_lang = message.from_user.language_code
        except Exception as error:
            my_log.log2(f'tb:start {error}\n\n{str(message)}')

        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        COMMAND_MODE[chat_id_full] = ''

        args = message.text.split(maxsplit = 1)
        if len(args) == 2:
            # if in number
            if args[1].isdigit():
                if args[1].lower() in [x.lower() for x in my_init.supported_langs_trans+['pt-br',]]:
                    lang = args[1].lower()
            else: # if file link for transcribe?
                arg = args[1]
                if arg and len(arg) == 30 and hasattr(cfg, 'PATH_TO_UPLOAD_FILES'):
                    p = os.path.join(cfg.PATH_TO_UPLOAD_FILES, arg)
                    if os.path.isfile(p):
                        with open(p, 'rb') as f:
                            data = f.read()
                        utils.remove_file(p)
                        transcribe_file(data, arg, message)
                    else:
                        bot_reply_tr(message, 'File not found')
                    return

        if lang in HELLO_MSG:
            help = HELLO_MSG[lang]
        else:
            help = my_init.start_msg
            my_log.log2(f'tb:send_welcome_start Unknown language: {lang}')

        bot_reply(
            message,
            help,
            parse_mode='HTML',
            disable_web_page_preview=True,
            reply_markup=get_keyboard('start', message),
            send_message=True)
        # if chat_id_full not in NEW_KEYBOARD:
        #     NEW_KEYBOARD[chat_id_full] = True

        # no language in user info, show language selector
        if not user_have_lang:
            language(message)

        # reset_(message, say = False)

        # set qwen3 model for arabic and farsi
        if lang in ('ar', 'ps', 'hi', 'fa'):
            my_db.set_user_property(chat_id_full, 'chat_mode', 'qwen3')

    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:start: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['help'], func = authorized_log)
@async_run
def send_welcome_help(message: telebot.types.Message):
    # Отправляем приветственное сообщение
    try:
        load_msgs()
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

        if message.from_user.id in cfg.admins and len(args) != 2:
            bot_reply(message, utils.bot_markdown_to_html(my_init.ADMIN_HELP), parse_mode='HTML', disable_web_page_preview=True)
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:help: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['help2'], func = authorized_log)
@async_run
def send_welcome_help2(message: telebot.types.Message):
    '''
    Дополнительное объяснение по ключам и опенроутеру
    '''
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)
        COMMAND_MODE[chat_id_full] = ''

        args = message.text.split(maxsplit = 1)
        if len(args) == 2:
            if args[1] in my_init.supported_langs_trans+['pt-br',]:
                lang = args[1]

        help = tr(my_init.help_msg2, lang)

        help = utils.bot_markdown_to_html(help)

        bot_reply(message, help, parse_mode='HTML', disable_web_page_preview=True)

    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:help: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['report'], func = authorized_log)
@async_run
def report_cmd_handler(message: telebot.types.Message):
    try:
        chat_id_full = get_topic_id(message)
        COMMAND_MODE[chat_id_full] = ''
        if hasattr(cfg, 'SUPPORT_GROUP'):
            bot_reply_tr(message, f'Support telegram group {cfg.SUPPORT_GROUP}\n\nUse it to send message to admin. \n\n<code>/report Something is not working here!</code>', parse_mode='HTML')
        try:
            args = message.text.split(maxsplit = 1)[1].strip()
        except IndexError:
            args = ''
        if args:
            msg = f'[Report from user {message.from_user.id}] {args}'
            my_log.log_reports(msg)
            bot.send_message(cfg.admins[0], msg, disable_notification=True)
            bot_reply_tr(message, 'Message sent.')
        else:
            if not hasattr(cfg, 'SUPPORT_GROUP'):
                bot_reply_tr(message, 'Use it to send message to admin.\n\n`/report Something is not working here!`')
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:report_cmd_handler: {unknown}\n{traceback_error}')


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

        chat_id_full = get_id_parameters_for_function(message, chat_id_full)

        if my_log.purge(message.chat.id):
            lang = get_lang(chat_id_full, message)

            with LOG_GROUP_MESSAGES_LOCK:
                for k in [x for x in LOG_GROUP_MESSAGES.keys()]:
                    data = LOG_GROUP_MESSAGES[k]
                    if data[2] == chat_id_full:
                        del LOG_GROUP_MESSAGES[k]

            # my_gemini3.reset(chat_id_full, model = my_db.get_user_property(chat_id_full, 'chat_mode'))
            my_gemini3.reset(chat_id_full)
            my_groq.reset(chat_id_full)
            my_openrouter.reset(chat_id_full)
            my_openrouter_free.reset(chat_id_full)
            my_mistral.reset(chat_id_full)
            my_cohere.reset(chat_id_full)
            my_ddg.reset(chat_id_full)
            if my_doc_translate.TRANSLATE_CACHE:
                my_doc_translate.TRANSLATE_CACHE.remove_by_owner(chat_id_full)

            my_skills_storage.STORAGE.pop(chat_id_full, None)

            # Delete User Properties
            my_db.delete_user_property(chat_id_full, 'role')
            my_db.delete_user_property(chat_id_full, 'persistant_memory')
            my_db.delete_user_property(chat_id_full, 'bot_name')  # Reset bot name to default
            my_db.delete_user_property(chat_id_full, 'temperature')
            my_db.delete_user_property(chat_id_full, 'lang') # reset language to default
            my_db.delete_user_property(chat_id_full, 'memos')
            my_db.delete_user_property(chat_id_full, 'chat_mode')
            my_db.delete_user_property(chat_id_full, 'chat_mode_prev')
            my_db.delete_user_property(chat_id_full, 'saved_file_name')
            my_db.delete_user_property(chat_id_full, 'saved_file')
            my_db.delete_user_property(chat_id_full, 'speech_to_text_engine')
            my_db.delete_user_property(chat_id_full, 'tts_gender')
            my_db.delete_user_property(chat_id_full, 'voice_only_mode')
            my_db.delete_user_property(chat_id_full, 'transcribe_only')
            my_db.delete_user_property(chat_id_full, 'disabled_kbd')
            my_db.delete_user_property(chat_id_full, 'openrouter_timeout')
            my_db.delete_user_property(chat_id_full, 'max_history_size')

            # Reset openrouter config
            if chat_id_full in my_openrouter.PARAMS:
                my_openrouter.PARAMS.pop(chat_id_full)

            if chat_id_full in UNCAPTIONED_IMAGES:
                del UNCAPTIONED_IMAGES[chat_id_full]


            # if chat_id_full in LOGS_GROUPS_DB:
            #     try:
            #         r = bot.delete_forum_topic(cfg.LOGS_GROUP, LOGS_GROUPS_DB[chat_id_full])
            #         del LOGS_GROUPS_DB[chat_id_full]
            #         if not r:
            #             my_log.log2(f'tb:purge_cmd_handler: {LOGS_GROUPS_DB[chat_id_full]} not deleted')
            #     except Exception as unknown:
            #         error_traceback = traceback.format_exc()
            #         my_log.log2(f'tb:purge_cmd_handler: {unknown}\n\n{chat_id_full}\n\n{error_traceback}')

            msg = f'{tr("Your logs was purged. Keep in mind there could be a backups and some mixed logs. It is hard to erase you from the internet.", lang)}'
        else:
            msg = f'{tr("Error. Your logs was NOT purged.", lang)}'
        bot_reply(message, msg)
    except Exception as unknown:
        error_traceback = traceback.format_exc()
        my_log.log2(f'tb:purge_cmd_handler: {unknown}\n\n{message.chat.id}\n\n{error_traceback}')


@bot.message_handler(commands=['id'], func=authorized_log)
@async_run
def id_cmd_handler(message: telebot.types.Message):
    """показывает id юзера и группы в которой сообщение отправлено"""
    try:
        chat_id_full = f'[{message.from_user.id}] [0]'
        group_id_full = f'[{message.chat.id}] [{message.message_thread_id or 0}]'
        gr_lang = get_lang(group_id_full, message)
        is_private = message.chat.type == 'private'

        if not is_private: # show only id in group
            activated = my_db.get_user_property(group_id_full, 'chat_enabled') or False
            activated = tr('Yes', gr_lang) if activated else tr('No', gr_lang)
            bot_name = my_db.get_user_property(group_id_full, 'bot_name') or BOT_NAME_DEFAULT
            chat_title = tr('Chat title:', gr_lang)
            bot_name_here = tr('Bot name here:', gr_lang)
            chat_activated = tr('Chat activated:', gr_lang)
            msg = utils.bot_markdown_to_html(f'{chat_title} `{message.chat.title or ""}`\n\nID: `{message.chat.id}`\n\n{tr("Thread:", gr_lang)} `{message.message_thread_id or 0}`\n\n{bot_name_here} `{bot_name}`\n\n{chat_activated} `{activated}`')
            bot_reply(message, msg, parse_mode='HTML')
            return

        if is_private:
            lang = get_lang(chat_id_full, message)
        else:
            lang = get_lang(group_id_full, message)

        COMMAND_MODE[chat_id_full] = ''

        is_admin = message.from_user.id in cfg.admins

        user_id = message.from_user.id

        try:
            if is_admin:
                arg = message.text.split(maxsplit=1)[1].strip()
                if arg:
                    if '[' not in arg:
                        user_id = arg
                        arg = f'[{arg}] [0]'
                    else:
                        user_id = arg.replace('[', '').replace(']', '').split(' ')[0].strip()
                    chat_id_full = arg
                    group_id_full = arg
        except IndexError:
            pass

        reported_language = message.from_user.language_code
        open_router_model, temperature, max_tokens, maxhistlines, maxhistchars = my_openrouter.PARAMS[chat_id_full] if chat_id_full in my_openrouter.PARAMS else my_openrouter.PARAMS_DEFAULT

        if is_private:
            user_model = my_db.get_user_property(chat_id_full, 'chat_mode') if my_db.get_user_property(chat_id_full, 'chat_mode') else cfg.chat_mode_default
        else:
            user_model = my_db.get_user_property(group_id_full, 'chat_mode') if my_db.get_user_property(group_id_full, 'chat_mode') else cfg.chat_mode_default
        models = {
            'gemini': cfg.gemini_flash_model,
            'gemini25_flash': cfg.gemini25_flash_model,
            'gemini15': cfg.gemini_pro_model,
            'gemini-lite': cfg.gemini_flash_light_model,
            'gemini-exp': cfg.gemini_exp_model,
            'gemini-learn': cfg.gemini_learn_model,
            'gemma3_27b': cfg.gemma3_27b_model,
            'mistral': my_mistral.DEFAULT_MODEL,
            'magistral': my_mistral.MAGISTRAL_MODEL,
            'gpt-4o': my_github.BIG_GPT_MODEL,
            'gpt_41': my_github.BIG_GPT_41_MODEL,
            'gpt_41_mini': my_github.DEFAULT_41_MINI_MODEL,
            'deepseek_r1': my_github.DEEPSEEK_R1_MODEL,
            'deepseek_v3': my_nebius.DEFAULT_V3_MODEL,
            'cohere': my_cohere.DEFAULT_MODEL,
            'openrouter': 'openrouter.ai',
            'cloacked': my_openrouter_free.CLOACKED_MODEL,
            'qwen3': my_cerebras.MODEL_QWEN_3_235B_A22B_THINKING,
            'qwen3coder': my_cerebras.MODEL_QWEN_3_CODER_480B,
            'gpt_oss': my_cerebras.MODEL_GPT_OSS_120B,
            'llama4': my_cerebras.MODEL_LLAMA_4_MAVERICK_17B_128E_INSTRUCT,
            'bothub': 'bothub.chat',
        }
        if user_model == 'openrouter':
            if 'bothub' in (my_db.get_user_property(chat_id_full, 'base_api_url') or ''):
                user_model = 'bothub'
        if user_model in models.keys():
            user_model = f'<b>{models[user_model]}</b>'

        telegram_stars: int = my_db.get_user_property(chat_id_full, 'telegram_stars') or 0

        total_msgs = my_db.get_total_msg_user(chat_id_full)
        totals_pics = my_db.get_pics_msg_user(chat_id_full)

        first_meet = my_db.get_user_property(chat_id_full, 'first_meet') or 0
        first_meet_dt = pendulum.from_timestamp(first_meet)
        try:
            first_meet_str = first_meet_dt.format('DD MMMM YYYY, dddd', locale=lang)
        except:
            first_meet_str = first_meet_dt.format('DD MMMM YYYY, dddd', locale='en')
        now = pendulum.now()
        diff = now - first_meet_dt

        try:
            delta_time_str = diff.in_words(locale=lang)
        except:
            delta_time_str = diff.in_words(locale='en')

        last_donate_time: float = my_db.get_user_property(chat_id_full, 'last_donate_time') or 0.0
        if time.time() - last_donate_time > 60*60*24*30:
            last_donate_time = 0

        msg = ''
        if is_admin:
            msg += f'Uptime: {get_uptime()}\n\n'
            msg += f'''{tr("Дата встречи:", lang)} {first_meet_str}
{delta_time_str}\n\n'''
        msg += f'''{tr("ID пользователя:", lang)} {user_id}

{tr("Количество сообщений/изображений:", lang)} {total_msgs-totals_pics}/{totals_pics}

{tr("ID группы:", lang)} {group_id_full}

{tr("Язык телеграма/пользователя:", lang)} {reported_language}/{lang}

{tr("Выбранная чат модель:", lang)} {user_model}'''

        if my_db.get_user_property(chat_id_full, 'chat_mode') == 'openrouter':
            msg += f' <b>{open_router_model}</b>'


        subscription_info = my_subscription.get_subscription_status_string(
            chat_id_full=chat_id_full,
            lang=lang,
            telegram_stars=telegram_stars,
            total_msgs=total_msgs,
            last_donate_time=last_donate_time,
            tr=tr,
        )
        msg += f'\n\n{subscription_info}'

        gemini_keys = my_gemini_general.USER_KEYS[chat_id_full] if chat_id_full in my_gemini_general.USER_KEYS else []
        groq_keys = [my_groq.USER_KEYS[chat_id_full],] if chat_id_full in my_groq.USER_KEYS else []
        mistral_keys = [my_mistral.USER_KEYS[chat_id_full],] if chat_id_full in my_mistral.USER_KEYS else []
        cohere_keys = [my_cohere.USER_KEYS[chat_id_full],] if chat_id_full in my_cohere.USER_KEYS else []
        github_keys = [my_github.USER_KEYS[chat_id_full],] if chat_id_full in my_github.USER_KEYS else []
        openrouter_keys = [my_openrouter.KEYS[chat_id_full],] if chat_id_full in my_openrouter.KEYS else []
        cerebras_keys = [my_cerebras.USER_KEYS[chat_id_full],] if chat_id_full in my_cerebras.USER_KEYS else []

        if cerebras_keys:
            msg += '\n\n🔑 Cerebras\n'
        else:
            msg += '\n\n🔒 Cerebras\n'
        if cohere_keys:
            msg += '🔑 Cohere\n'
        else:
            msg += '🔒 Cohere\n'
        if gemini_keys:
            msg += '🔑 Gemini\n'
        else:
            msg += '🔒 Gemini\n'
        if github_keys:
            msg += '🔑 Github\n'
        else:
            msg += '🔒 Github\n'
        if groq_keys:
            msg += '🔑 Groq\n'
        else:
            msg += '🔒 Groq\n'
        if mistral_keys:
            msg += '🔑 Mistral\n'
        else:
            msg += '🔒 Mistral\n'
        if openrouter_keys:
            msg += '🔑 OpenRouter\n'
        else:
            msg += '🔒 OpenRouter\n'

        if my_db.get_user_property(chat_id_full, 'blocked'):
            msg += f'\n{tr("User was banned.", lang)}'

        if my_db.get_user_property(chat_id_full, 'blocked_totally'):
            msg += f'\n{tr("User was banned totally.", lang)}'

        if my_db.get_user_property(chat_id_full, 'blocked_bing'):
            msg += f'\n{tr("User was banned in bing.com.", lang)}'

        if str(message.chat.id) in DDOS_BLOCKED_USERS and not my_db.get_user_property(chat_id_full, 'blocked'):
            msg += f'\n{tr("User was temporarily banned.", lang)}'

        if my_db.get_user_property(chat_id_full, 'persistant_memory'):
            msg += f'\n{tr("Что бот помнит о пользователе:", lang)}\n{my_db.get_user_property(chat_id_full, "persistant_memory")}'

        # показать имя бота, стиль, и мемо юзера админу
        if message.from_user.id in cfg.admins and chat_id_full != f'[{message.from_user.id}] [0]':
            style = utils.bot_markdown_to_html(my_db.get_user_property(chat_id_full, "role") or '').strip()
            bname = utils.bot_markdown_to_html(my_db.get_user_property(chat_id_full, "bot_name") or '').strip()
            memos = my_db.blob_to_obj(my_db.get_user_property(chat_id_full, 'memos')) or []
            memos_str = utils.bot_markdown_to_html('\n'.join(memos)).strip()
            temperature = my_db.get_user_property(chat_id_full, 'temperature')

            if bname:
                msg += f'\n\n<b>{tr("Bot name:", lang)}</b> {bname}'
            if style:
                msg += f'\n\n<b>{tr("Style:", lang)}</b> {style}'
            if memos_str:
                msg += f'\n\n<b>{tr("User memo:", lang)}</b> {memos_str}'
            if temperature and temperature != GEMIMI_TEMP_DEFAULT:
                msg += f'\n\n<b>{tr("Temperature:", lang)}</b> {temperature}'

        bot_reply(message, msg, parse_mode = 'HTML')
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log2(f'tb:id: {error}\n\n{error_traceback}\n\n{message}')


@bot.message_handler(commands=['reload'], func=authorized_admin)
@async_run
def reload_module(message: telebot.types.Message):
    '''command for reload imported module on the fly'''
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    try:
        # Получаем строку с именами модулей
        module_name_raw_parts = message.text.split(' ', 1)
        if len(module_name_raw_parts) < 2:
            bot_reply(message, tr("Укажите модуль(и) для перезагрузки.", lang))
            return

        # Разделяем имена модулей на список, используя set для уникальности
        initial_modules_to_process = set(module_name_raw_parts[1].strip().split())

        # Создаем окончательный список модулей для перезагрузки
        final_modules_to_reload = list(initial_modules_to_process)

        # Проверяем зависимость от 'skills' только один раз для всего набора модулей
        # и добавляем 'my_cerebras_tools' и 'my_gemini3' если 'skills' присутствует
        if any('skills' in x for x in initial_modules_to_process):
            if 'my_cerebras_tools' not in final_modules_to_reload:
                final_modules_to_reload.append('my_cerebras_tools')
            if 'my_gemini3' not in final_modules_to_reload:
                final_modules_to_reload.append('my_gemini3')

        results = []
        # Теперь итерируем по окончательному списку и перезагружаем каждый модуль
        for module_to_reload in sorted(final_modules_to_reload): # Сортируем для предсказуемого порядка
            with RELOAD_LOCK:
                current_module_name = module_to_reload

                # Проверяем существование файла и корректируем имя
                if not os.path.exists(f"{current_module_name}.py"):
                    if current_module_name.startswith('my_') and os.path.exists(f"{current_module_name[3:]}.py"):
                        current_module_name = current_module_name[3:]
                    elif not current_module_name.startswith('my_') and os.path.exists(f"my_{current_module_name}.py"):
                        current_module_name = f"my_{current_module_name}"
                    else:
                        raise Exception(f"Файл для модуля '{current_module_name}' не найден")

                module = importlib.import_module(current_module_name)
                importlib.reload(module)

                # Реинициализация модуля (остается без изменений)
                if current_module_name == 'my_gemini3':
                    my_gemini_general.load_users_keys()
                    my_skills.init()
                elif current_module_name == 'my_groq':
                    my_groq.load_users_keys()
                elif current_module_name == 'my_cerebras':
                    my_cerebras.load_users_keys()
                elif current_module_name == 'my_mistral':
                    my_mistral.load_users_keys()
                elif current_module_name == 'my_github':
                    my_github.load_users_keys()
                elif current_module_name == 'my_nebius':
                    my_nebius.load_users_keys()
                elif current_module_name == 'my_cohere':
                    my_cohere.load_users_keys()
                elif current_module_name == 'my_init':
                    load_msgs()
                elif current_module_name == 'my_skills':
                    my_skills.init()
                elif current_module_name == 'my_db':
                    db_backup = cfg.DB_BACKUP if hasattr(cfg, 'DB_BACKUP') else True
                    db_vacuum = cfg.DB_VACUUM if hasattr(cfg, 'DB_VACUUM') else False
                    my_db.init(db_backup, db_vacuum)

                results.append(f'{tr("Модуль успешно перезагружен:", lang)} {current_module_name}')

        # Отправляем общий ответ по всем перезагруженным модулям
        bot_reply(message, "\n".join(results))

    except Exception as e:
        my_log.log2(f"Ошибка при перезагрузке модуля: {e}")
        msg = f'{tr("Ошибка при перезагрузке модуля:", lang)}```ERROR\n{e}```'
        bot_reply(message, msg, parse_mode = 'MarkdownV2')


@bot.message_handler(commands=['enable'], func=authorized_owner)
@async_run
def enable_chat(message: telebot.types.Message):
    """что бы бот работал в чате надо его активировать там"""
    try:
        is_private = message.chat.type == 'private'
        if is_private:
            bot_reply_tr(message, "Use this command to activate bot in public chat.")
            return
        user_full_id = f'[{message.from_user.id}] [0]'
        admin_have_keys = (user_full_id in my_gemini_general.USER_KEYS and user_full_id in my_groq.USER_KEYS) or message.from_user.id in cfg.admins

        if admin_have_keys:
            chat_full_id = get_topic_id(message)
            my_db.set_user_property(chat_full_id, 'chat_enabled', True)
            user_lang = get_lang(user_full_id)
            my_db.set_user_property(chat_full_id, 'lang', user_lang)
            bot_reply_tr(message, 'Chat enabled.')
        else:
            bot_reply_tr(message, 'Что бы включить бота в публичном чате надо сначала вставить свои ключи. В приватном чате команды /id /keys /openrouter')
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:enable_chat: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['disable'], func=authorized_owner)
@async_run
def disable_chat(message: telebot.types.Message):
    """что бы бот не работал в чате надо его деактивировать там"""
    try:
        is_private = message.chat.type == 'private'
        if is_private:
            bot_reply_tr(message, "Use this command to deactivate bot in public chat.")
            return
        chat_id_full = get_topic_id(message)
        my_db.delete_user_property(chat_id_full, 'chat_enabled')
        bot_reply_tr(message, 'Chat disabled.')
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:disable_chat: {unknown}\n{traceback_error}')


@bot.message_handler(commands=['histsize', 'memsize'], func=authorized_owner)
@async_run
def set_history_size(message: telebot.types.Message) -> None:
    """
    Sets the number of last request/response pairs to keep in history for the user.
    """
    try:
        chat_id_full: str = get_topic_id(message)
        lang: str = get_lang(chat_id_full, message)
        COMMAND_MODE[chat_id_full] = ''

        # --- Pre-cache all translations for this command ---
        # A dictionary to hold all localized strings for the command's responses.
        texts: Dict[str, str] = {
            'size_set_to': tr('History size set to:', lang, help="A confirmation message shown after a user successfully sets a value. E.g., 'History size set to: 10'."),
            'not_set': tr('Not set', lang, help="Indicates that a user setting has no value yet. E.g., 'Current size: Not set'."),
            'help_main': tr('Sets the number of request/response pairs to keep in memory.', lang, help="A short, one-line explanation of the /histsize command's purpose."),
            'example': tr('Example:', lang, help="A label for a section showing command examples. E.g., 'Example:'."),
            'example_10': tr('Keep the last 10 interactions.', lang, help="A comment explaining what '/histsize 10' does."),
            'example_0': tr('No history (stateless mode).', lang, help="A comment explaining what '/histsize 0' does."),
            'current_size_label': tr('Current size:', lang, help="A label for displaying the current value of the setting. E.g., 'Current size: 50'.")
        }
        # --- End of translations ---

        parts: List[str] = message.text.split()
        default_size: int = getattr(cfg, 'DEFAULT_HISTORY_SIZE', 1000)

        if len(parts) == 2:
            try:
                new_size = int(parts[1])

                if 0 <= new_size <= 1000:
                    my_db.set_user_property(chat_id_full, 'max_history_size', new_size)
                    msg = f"{texts['size_set_to']} {new_size}"
                    bot_reply(message, msg)
                    return
            except ValueError:
                # Input is not a valid integer, fall through to show help.
                pass

        # Show help if no valid argument was provided.
        current_size_val = my_db.get_user_property(chat_id_full, 'max_history_size')
        if current_size_val is None: current_size_val = texts['not_set']
        elif current_size_val == 1000: current_size_display = texts['not_set']
        else: current_size_display = current_size_val

        help_text = f"""/histsize <0-1000>

{texts['help_main']}

{texts['example']}
`/histsize 10`  # {texts['example_10']}
`/histsize 0`   # {texts['example_0']}

{texts['current_size_label']} {current_size_display}
"""
        bot_reply(message, help_text)

    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:set_history_size: {unknown}\n{traceback_error}')


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
    try:
        def get_seconds(s):
            match = re.search(r"after\s+(?P<seconds>\d+)", s)
            if match:
                return int(match.group("seconds"))
            else:
                return 0

        bot_reply_tr(message, "Localization will take a long time, do not repeat this command.")

        most_used_langs = [x for x in my_init.supported_langs_trans if len(x) == 2]
        if hasattr(cfg, 'INIT_LANGS') and cfg.INIT_LANGS:
            most_used_langs = cfg.INIT_LANGS

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
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:set_default_command: {unknown}\n{traceback_error}')


def send_long_message(
    message: telebot.types.Message,
    resp: str,
    parse_mode:str = None,
    disable_web_page_preview: bool = None,
    reply_markup: telebot.types.InlineKeyboardMarkup = None,
    allow_voice: bool = False,
    collapse_text: bool = False
):
    """отправляем сообщение, если оно слишком длинное то разбивает на 2 части либо отправляем как текстовый файл"""
    reply_to_long_message(
        message=message,
        resp=resp,
        parse_mode=parse_mode,
        disable_web_page_preview=disable_web_page_preview,
        reply_markup=reply_markup, send_message = True,
        allow_voice=allow_voice,
        collapse_text=collapse_text
    )


def send_resp_as_file(message: telebot.types.Message,
                      resp: str,
                      reply_markup: telebot.types.InlineKeyboardMarkup = None,
                      lang: str = 'en',
                      ) -> None:
    """Send response as a file.

    Args:
        message: The message object.
        resp: The response string.
        reply_markup: The reply markup.
        lang: The language code.
    """
    with io.BytesIO() as buf:
        buf.write(resp.encode())
        buf.seek(0)
        cap = tr('Too big answer, sent as file', lang)
        fname = f'{utils.get_full_time()}.txt'.replace(':', '-')
        m = send_document(
            message,
            message.chat.id,
            document=buf,
            message_thread_id=message.message_thread_id,
            caption=cap,
            visible_file_name=fname,
            reply_markup=reply_markup
        )
        log_message(m)


def _send_message(
    message: telebot.types.Message,
    chunk: str,
    parse_mode: str,
    preview: telebot.types.LinkPreviewOptions,
    reply_markup: telebot.types.InlineKeyboardMarkup,
    send_message: bool,
    resp: str,
    retry_times: int
) -> None:
    """Send message or reply to a message.

    Args:
        message: The message object.
        chunk: The text chunk to send.
        parse_mode: The parse mode for the message.
        preview: Whether to show a link preview.
        reply_markup: The reply markup for the message.
        send_message: Whether to send a new message or reply to the existing one.
        resp: The full response text (used for error logging).
        retry_times: The number of retry attempts.
    """

    try:
        retry_times -= 1
        if retry_times == 0:
            return

        if send_message:
            m = bot.send_message(
                message.chat.id,
                chunk,
                message_thread_id=message.message_thread_id,
                parse_mode=parse_mode,
                link_preview_options=preview,
                reply_markup=reply_markup,
                disable_notification=True,
            )
        else:
            m = bot.reply_to(
                message,
                chunk,
                parse_mode=parse_mode,
                link_preview_options=preview,
                reply_markup=reply_markup,
                disable_notification=True,
            )
        log_message(m)
    except Exception as error:

        if 'Bad Request: message to be replied not found' in str(error):
            return

        elif "Error code: 400. Description: Bad Request: can't parse entities" in str(error):
            error_traceback = traceback.format_exc()
            my_log.log_parser_error(
                f'{str(error)}\n\n{error_traceback}\n\n{DEBUG_MD_TO_HTML.get(resp, "")}\n'
                f'=====================================================\n{resp}'
            )
            my_log.log_parser_error2(DEBUG_MD_TO_HTML.get(chunk, ""))
            if parse_mode:
                _send_message(message, chunk, '', preview, reply_markup, send_message, resp, retry_times)

        elif "Too Many Requests: retry after" in str(error):
            retry_after = utils.extract_retry_seconds(str(error))
            if retry_after == 0:
                retry_after = 10
            time.sleep(retry_after)
            _send_message(message, chunk, parse_mode, preview, reply_markup, send_message, resp, retry_times)

        elif 'Bad Request: message is too long' in str(error):
            # could not split into parts, splitting again and sending without formatting just in case
            chunks2 = utils.split_text(chunk, 3500)
            for chunk2 in chunks2:
                if not chunk2.strip():
                    continue
                _send_message(message, chunk2, '', preview, reply_markup, send_message, resp, retry_times)
        else:
            if parse_mode == 'HTML':
                chunk = utils.html.unescape(chunk)
                chunk = chunk.replace('<b>', '')
                chunk = chunk.replace('<i>', '')
                chunk = chunk.replace('</b>', '')
                chunk = chunk.replace('</i>', '')

            my_log.log2(
                f'tb:reply_to_long_message:1: {error}\n\nresp: {resp[:500]}\n\nparse_mode: {parse_mode}'
            )
            if 'Forbidden: bot was blocked by the user' in str(error):
                return
            # my_log.log2(chunk)

            _send_message(message, chunk, '', preview, reply_markup, send_message, resp, retry_times)


def reply_to_long_message(
    message: telebot.types.Message,
    resp: str,
    parse_mode: str = None,
    disable_web_page_preview: bool = None,
    reply_markup: telebot.types.InlineKeyboardMarkup = None,
    send_message: bool = False,
    allow_voice: bool = False,
    collapse_text: bool = False
):
    """
    Sends a message, splitting it into two parts if it's too long, or sending it as a text file.

    Args:
        message: The message object.
        resp: The response string.
        parse_mode: The parse mode.
        disable_web_page_preview: Whether to disable web page preview.
        reply_markup: The reply markup.
        send_message: Whether to send the message instead of replying.
        allow_voice: Whether to allow voice responses.
    """
    try:
        resp = resp
        if not resp:
            my_log.log2(f'tb:reply_to_long_message:2: empty message')
            return

        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        preview = telebot.types.LinkPreviewOptions(is_disabled=disable_web_page_preview)

        max_size = cfg.SPLIT_CHUNK_HTML if hasattr(cfg, 'SPLIT_CHUNK_HTML') else 3800

        if parse_mode == 'HTML':
            chunks = utils.split_html(resp, max_size)
        else:
            chunks = utils.split_text(resp, max_size)

        # collapse_text - HTML текст надо спрятать в <blockquote expandable> .. </blockquote>
        if collapse_text and parse_mode == 'HTML':
            chunks_ = []
            for chunk in chunks:
                chunks_.append('<blockquote expandable>' + chunk + '</blockquote>')
            chunks = chunks_


        # в режиме только голоса ответы идут голосом без текста и разделения на части
        if my_db.get_user_property(chat_id_full, 'voice_only_mode') and allow_voice:
            message.text = '/tts ' + '\n'.join(chunks)
            tts(message)
        else:

            if len(resp) > 40000 or len(chunks) > 9:
                if parse_mode == 'HTML':
                    send_resp_as_file(message, my_pandoc.convert_html_to_plain(resp), reply_markup, lang)
                else:
                    send_resp_as_file(message, resp, reply_markup, lang)
            else:
                for chunk in chunks:
                    if not chunk.strip():
                        my_log.log2(f'tb:reply_to_long_message:3: empty chunk')
                        continue
                    else:
                        _send_message(message, chunk, parse_mode, preview, reply_markup, send_message, resp, 5)

        # если есть таблицы в ответе то отправить их картинками в догонку
        tables = my_md_tables_to_png.find_markdown_tables(resp)
        if tables:
            for table in tables:
                try:
                    image = my_md_tables_to_png.markdown_table_to_image_bytes(table)
                    if image:
                        m = send_photo(
                            message,
                            chat_id=message.chat.id,
                            photo=image,
                            reply_to_message_id = message.message_id,
                            reply_markup=get_keyboard('hide', message),
                        )
                        log_message(m)
                except Exception as error:
                    my_log.log2(f'tb:do_task:send tables images: {error}')

        if parse_mode == 'HTML':
            # если есть графики в ответе то отправить их картинками в догонку
            graphs = my_plantweb.find_code_snippets(resp)
            if graphs:
                for graph in graphs:
                    try:
                        image = my_plantweb.text_to_png(
                            graph['code'],
                            engine=graph['engine'],
                            format='png'
                        )
                        if image and isinstance(image, bytes):
                            m = send_photo(
                                message,
                                chat_id=message.chat.id,
                                photo=image,
                                reply_to_message_id = message.message_id,
                                reply_markup=get_keyboard('hide', message),
                            )
                            log_message(m)
                    except Exception as error:
                        my_log.log2(f'tb:do_task:send graphs images: {error}')

    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:reply_to_long_message3: {unknown}\n{traceback_error}')

    # remove resp if any
    if resp in DEBUG_MD_TO_HTML:
        DEBUG_MD_TO_HTML.pop(resp)


def send_media_group(
    message: telebot.types.Message,
    chat_id: int | str,
    media: List[telebot.types.InputMediaAudio | telebot.types.InputMediaDocument | telebot.types.InputMediaPhoto | telebot.types.InputMediaVideo],
    disable_notification: bool | None = True,
    protect_content: bool | None = None,
    reply_to_message_id: int | None = None,
    timeout: int | None = 60,
    allow_sending_without_reply: bool | None = None,
    message_thread_id: int | None = None,
    reply_parameters: telebot.types.ReplyParameters | None = None,
    business_connection_id: str | None = None,
    message_effect_id: str | None = None,
    allow_paid_broadcast: bool | None = None
) -> list[telebot.types.Message]:
    '''
    bot.send_media_group wrapper
    посылает группу картинок, возвращает список сообщений
    при ошибке пытается сделать это несколько раз

    даже если указан reply_to_message_id всё равно смотрит в базу и если у юзера отключены
    реплаи то не испольует его
    '''
    full_chat_id = get_topic_id(message)
    reply = my_db.get_user_property(full_chat_id, 'send_message') or ''

    n = 5
    while n >= 0:
        n -= 1

        try:
            if not reply:
                r = bot.send_media_group(
                    chat_id=chat_id,
                    media=media,
                    disable_notification=disable_notification,
                    protect_content=protect_content,
                    reply_to_message_id=reply_to_message_id,
                    timeout=timeout,
                    allow_sending_without_reply=allow_sending_without_reply,
                    message_thread_id=message_thread_id,
                    reply_parameters=reply_parameters,
                    business_connection_id=business_connection_id,
                    message_effect_id=message_effect_id,
                    allow_paid_broadcast=allow_paid_broadcast
                )
            else:
                r = bot.send_media_group(
                    chat_id=chat_id,
                    media=media,
                    disable_notification=disable_notification,
                    protect_content=protect_content,
                    timeout=timeout,
                    allow_sending_without_reply=allow_sending_without_reply,
                    message_thread_id=message_thread_id,
                    reply_parameters=reply_parameters,
                    business_connection_id=business_connection_id,
                    message_effect_id=message_effect_id,
                    allow_paid_broadcast=allow_paid_broadcast
                )
            return r

        except Exception as error:

            if 'Error code: 500. Description: Internal Server Error' in str(error):
                my_log.log2(f'tb:send_media_group:1: {error}')
                time.sleep(10)
                continue

            # попробовать отправить не ответ на удаленное сообщение а просто сообщение
            if 'Bad Request: message to be replied not found' not in str(error):
                reply = not reply
                continue

            # если в ответе написано подождите столько то секунд то ждем столько то + 5
            seconds = utils.extract_retry_seconds(str(error))
            if seconds:
                time.sleep(seconds + 5)
                continue

            # неизвестная ошибка
            else:
                traceback_error = traceback.format_exc()
                my_log.log2(f'tb:send_media_group:2: {error}\n\n{traceback_error}')
                break

    return []


def send_document(
    message: telebot.types.Message,
    chat_id: int | str,
    document: Any | str,
    reply_to_message_id: int | None = None,
    caption: str | None = None,
    reply_markup: telebot.REPLY_MARKUP_TYPES | None = None,
    parse_mode: str | None = None,
    disable_notification: bool | None = True,
    timeout: int | None = 60,
    thumbnail: Any | str | None = None,
    caption_entities: List[telebot.types.MessageEntity] | None = None,
    allow_sending_without_reply: bool | None = None,
    visible_file_name: str | None = None,
    disable_content_type_detection: bool | None = None,
    data: Any | str | None = None,
    protect_content: bool | None = None,
    message_thread_id: int | None = None,
    thumb: Any | str | None = None,
    reply_parameters: telebot.types.ReplyParameters | None = None,
    business_connection_id: str | None = None,
    message_effect_id: str | None = None,
    allow_paid_broadcast: bool | None = None
) -> telebot.types.Message:
    '''
    bot.send_document wrapper

    посылает документ, возвращает сообщение или None
    при ошибке пытается сделать это несколько раз

    даже если указан reply_to_message_id всё равно смотрит в базу и если у юзера отключены
    реплаи то не испольует его
    '''

    full_chat_id = get_topic_id(message)
    reply = my_db.get_user_property(full_chat_id, 'send_message') or ''

    n = 5
    while n >= 0:
        n -= 1

        try:
            if not reply:
                r = bot.send_document(
                    chat_id=chat_id,
                    document=document,
                    reply_to_message_id=reply_to_message_id,
                    caption=caption,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                    disable_notification=disable_notification,
                    timeout=timeout,
                    thumbnail = thumbnail,
                    caption_entities = caption_entities,
                    allow_sending_without_reply=allow_sending_without_reply,
                    visible_file_name=visible_file_name,
                    disable_content_type_detection=disable_content_type_detection,
                    data=data,
                    protect_content=protect_content,
                    message_thread_id=message_thread_id,
                    thumb=thumb,
                    reply_parameters=reply_parameters,
                    business_connection_id=business_connection_id,
                    message_effect_id=message_effect_id,
                    allow_paid_broadcast=allow_paid_broadcast
                )
            else:
                r = bot.send_document(
                    chat_id=chat_id,
                    document=document,
                    caption=caption,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                    disable_notification=disable_notification,
                    timeout=timeout,
                    thumbnail = thumbnail,
                    caption_entities = caption_entities,
                    allow_sending_without_reply=allow_sending_without_reply,
                    visible_file_name=visible_file_name,
                    disable_content_type_detection=disable_content_type_detection,
                    data=data,
                    protect_content=protect_content,
                    message_thread_id=message_thread_id,
                    thumb=thumb,
                    reply_parameters=reply_parameters,
                    business_connection_id=business_connection_id,
                    message_effect_id=message_effect_id,
                    allow_paid_broadcast=allow_paid_broadcast
                )

            return r

        except Exception as error:

            if 'Error code: 500. Description: Internal Server Error' in str(error):
                my_log.log2(f'tb:send_document:1: {error}')
                time.sleep(10)
                continue

            # попробовать отправить не ответ на удаленное сообщение а просто сообщение
            if 'Bad Request: message to be replied not found' not in str(error):
                reply = not reply
                continue

            # если в ответе написано подождите столько то секунд то ждем столько то + 5
            seconds = utils.extract_retry_seconds(str(error))
            if seconds:
                time.sleep(seconds + 5)
                continue

            # неизвестная ошибка
            else:
                traceback_error = traceback.format_exc()
                my_log.log2(f'tb:send_document:2: {error}\n\n{traceback_error}')
                break

    return None


def send_video(
    message: telebot.types.Message,
    chat_id: int | str,
    video: Any | str,
    duration: int | None = None,
    width: int | None = None,
    height: int | None = None,
    thumbnail: Any | str | None = None,
    caption: str | None = None,
    parse_mode: str | None = None,
    caption_entities: List[telebot.types.MessageEntity] | None = None,
    supports_streaming: bool | None = True,
    disable_notification: bool | None = True,
    protect_content: bool | None = None,
    reply_to_message_id: int | None = None,
    allow_sending_without_reply: bool | None = None,
    reply_markup: telebot.REPLY_MARKUP_TYPES | None = None,
    timeout: int | None = 120,
    data: str | Any | None = None,  # совместимость, не используем
    message_thread_id: int | None = None,
    has_spoiler: bool | None = None,
    thumb: Any | str | None = None,  # deprecated alias
    reply_parameters: telebot.types.ReplyParameters | None = None,
    business_connection_id: str | None = None,
    message_effect_id: str | None = None,
    show_caption_above_media: bool | None = None,
    allow_paid_broadcast: bool | None = None,
    cover: Any | str | None = None,
    start_timestamp: int | None = None,
) -> telebot.types.Message:
    '''
    bot.send_video wrapper
    Отправляет mp4 как медиа (а не документ). Следит за reply-настройкой, делает ретраи.
    '''

    # alias: поддержим старое имя параметра thumb -> thumbnail
    if thumbnail is None and thumb is not None:
        thumbnail = thumb

    # Если пришли "сырые" байты/файлоподобный объект — обернем в InputFile с .mp4 именем
    try:
        from telebot.types import InputFile
        def to_inputfile_if_needed(obj, default_name: str):
            if isinstance(obj, (bytes, bytearray)):
                return InputFile(obj, filename=default_name)
            # file-like с read
            if hasattr(obj, 'read') and callable(getattr(obj, 'read', None)):
                # попытка вытащить имя
                fname = getattr(obj, 'name', None)
                if not fname or not str(fname).lower().endswith('.mp4'):
                    fname = default_name
                return InputFile(obj, filename=fname)
            return obj
        video = to_inputfile_if_needed(video, 'video.mp4')
        if thumbnail is not None:
            thumbnail = to_inputfile_if_needed(thumbnail, 'thumb.jpg')
        if cover is not None:
            cover = to_inputfile_if_needed(cover, 'cover.jpg')
    except Exception:
        pass

    full_chat_id = get_topic_id(message)
    reply = my_db.get_user_property(full_chat_id, 'send_message') or ''

    n = 5
    while n >= 0:
        n -= 1
        try:
            kwargs = dict(
                chat_id=chat_id,
                video=video,
                duration=duration,
                width=width,
                height=height,
                caption=caption,
                parse_mode=parse_mode,
                caption_entities=caption_entities,
                supports_streaming=supports_streaming,
                disable_notification=disable_notification,
                protect_content=protect_content,
                allow_sending_without_reply=allow_sending_without_reply,
                reply_markup=reply_markup,
                timeout=timeout,
                message_thread_id=message_thread_id,
                has_spoiler=has_spoiler,
                reply_parameters=reply_parameters,
                business_connection_id=business_connection_id,
                message_effect_id=message_effect_id,
                show_caption_above_media=show_caption_above_media,
                allow_paid_broadcast=allow_paid_broadcast,
                cover=cover,
                start_timestamp=start_timestamp,
            )
            if thumbnail is not None:
                kwargs['thumbnail'] = thumbnail
            if not reply:
                kwargs['reply_to_message_id'] = reply_to_message_id

            r = bot.send_video(**kwargs)
            return r

        except Exception as error:
            err = str(error)

            if 'Error code: 500. Description: Internal Server Error' in err:
                my_log.log2(f'tb:send_video:1: {error}')
                time.sleep(10)
                continue

            # убрать reply если исходный месседж исчез
            if 'Bad Request: message to be replied not found' in err:
                reply = True
                continue

            # слишком много запросов — подождать
            seconds = utils.extract_retry_seconds(err)
            if seconds:
                time.sleep(seconds + 5)
                continue

            # Популярные проблемы файла: попробуем запасной путь как документ
            if any(s in err for s in [
                'file is too big',
                'wrong file identifier',
                'invalid file HTTP URL',
                'failed to get HTTP URL content',
                'VIDEO_CONTENT_TYPE_INVALID',
                'wrong file_id specified',
            ]):
                try:
                    m = send_document(
                        message=message,
                        chat_id=chat_id,
                        document=video,
                        caption=caption,
                        parse_mode=parse_mode,
                        caption_entities=caption_entities,
                        disable_notification=disable_notification,
                        protect_content=protect_content,
                        reply_to_message_id=None if reply else reply_to_message_id,
                        allow_sending_without_reply=allow_sending_without_reply,
                        reply_markup=reply_markup,
                        timeout=timeout,
                        message_thread_id=message_thread_id,
                        reply_parameters=reply_parameters,
                        business_connection_id=business_connection_id,
                        message_effect_id=message_effect_id,
                        allow_paid_broadcast=allow_paid_broadcast,
                        visible_file_name='video.mp4',
                    )
                    log_message(m)
                    return m
                except Exception as e2:
                    my_log.log2(f'tb:send_video:doc_fallback: {e2}')
                    continue

            traceback_error = traceback.format_exc()
            my_log.log2(f'tb:send_video:2: {error}\n\n{traceback_error}')
            break

    return None


def send_photo(
    message: telebot.types.Message,
    chat_id: int | str,
    photo: Any | str,
    caption: str | None = None,
    parse_mode: str | None = None,
    caption_entities: List[telebot.types.MessageEntity] | None = None,
    disable_notification: bool | None = True,
    protect_content: bool | None = None,
    reply_to_message_id: int | None = None,
    allow_sending_without_reply: bool | None = None,
    reply_markup: telebot.REPLY_MARKUP_TYPES | None = None,
    timeout: int | None = 60,
    message_thread_id: int | None = None,
    has_spoiler: bool | None = None,
    reply_parameters: telebot.types.ReplyParameters | None = None,
    business_connection_id: str | None = None,
    message_effect_id: str | None = None,
    show_caption_above_media: bool | None = None,
    allow_paid_broadcast: bool | None = None
) -> telebot.types.Message:
    '''
    bot.send_photo wrapper

    посылает картинку, возвращает сообщение или None
    при ошибке пытается сделать это несколько раз

    даже если указан reply_to_message_id всё равно смотрит в базу и если у юзера отключены
    реплаи то не испольует его
    '''

    full_chat_id = get_topic_id(message)
    reply = my_db.get_user_property(full_chat_id, 'send_message') or ''

    n = 5
    while n >= 0:
        n -= 1

        try:
            x, y = utils.get_image_size(photo)
            if max(x, y) > 1280 or min(x, y) > 1280:
                # send as document too
                m = send_document(
                    message,
                    chat_id=chat_id,
                    document=photo,
                    caption=caption,
                    parse_mode=parse_mode,
                    caption_entities=caption_entities,
                    disable_notification=disable_notification,
                    protect_content=protect_content,
                    reply_to_message_id=reply_to_message_id,
                    allow_sending_without_reply=allow_sending_without_reply,
                    reply_markup=reply_markup,
                    timeout=timeout,
                    message_thread_id=message_thread_id,
                    reply_parameters=reply_parameters,
                    business_connection_id=business_connection_id,
                    message_effect_id=message_effect_id,
                    allow_paid_broadcast=allow_paid_broadcast,

                    # Параметры, специфичные для send_document, которые полезны при отправке изображения:
                    visible_file_name="image.png",
                    # thumb=thumbnail_data_or_file_id,
                )
                log_message(m)
                photo = utils.resize_image_to_dimensions(photo, 2000, 2000)

            if not reply:
                r = bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=caption,
                    parse_mode=parse_mode,
                    caption_entities=caption_entities,
                    disable_notification=disable_notification,
                    protect_content=protect_content,
                    reply_to_message_id=reply_to_message_id,
                    allow_sending_without_reply=allow_sending_without_reply,
                    reply_markup=reply_markup,
                    timeout=timeout,
                    message_thread_id=message_thread_id,
                    has_spoiler=has_spoiler,
                    reply_parameters=reply_parameters,
                    business_connection_id=business_connection_id,
                    message_effect_id=message_effect_id,
                    show_caption_above_media=show_caption_above_media,
                    allow_paid_broadcast=allow_paid_broadcast
                )
            else:
                r = bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=caption,
                    parse_mode=parse_mode,
                    caption_entities=caption_entities,
                    disable_notification=disable_notification,
                    protect_content=protect_content,
                    allow_sending_without_reply=allow_sending_without_reply,
                    reply_markup=reply_markup,
                    timeout=timeout,
                    message_thread_id=message_thread_id,
                    has_spoiler=has_spoiler,
                    reply_parameters=reply_parameters,
                    business_connection_id=business_connection_id,
                    message_effect_id=message_effect_id,
                    show_caption_above_media=show_caption_above_media,
                    allow_paid_broadcast=allow_paid_broadcast
                )
            return r

        except Exception as error:

            if 'Error code: 500. Description: Internal Server Error' in str(error):
                my_log.log2(f'tb:send_photo:1: {error}')
                time.sleep(10)
                continue

            # попробовать отправить не ответ на удаленное сообщение а просто сообщение
            if 'Bad Request: message to be replied not found' not in str(error):
                reply = not reply
                continue

            # если в ответе написано подождите столько то секунд то ждем столько то + 5
            seconds = utils.extract_retry_seconds(str(error))
            if seconds:
                time.sleep(seconds + 5)
                continue

            # неизвестная ошибка
            else:
                traceback_error = traceback.format_exc()
                my_log.log2(f'tb:send_photo:2: {error}\n\n{traceback_error}')
                break

    return None


def send_audio(
    message: telebot.types.Message,
    chat_id: int | str,
    audio: Any | str,
    caption: str | None = None,
    duration: int | None = None,
    performer: str | None = None,
    title: str | None = None,
    reply_to_message_id: int | None = None,
    reply_markup: telebot.REPLY_MARKUP_TYPES | None = None,
    parse_mode: str | None = None,
    disable_notification: bool | None = True,
    timeout: int | None = 120,
    thumbnail: Any | str | None = None,
    caption_entities: List[telebot.types.MessageEntity] | None = None,
    allow_sending_without_reply: bool | None = None,
    protect_content: bool | None = None,
    message_thread_id: int | None = None,
    thumb: Any | str | None = None,
    reply_parameters: telebot.types.ReplyParameters | None = None,
    business_connection_id: str | None = None,
    message_effect_id: str | None = None,
    allow_paid_broadcast: bool | None = None
) -> telebot.types.Message:
    '''
    bot.send_voice wrapper

    посылает аудио, возвращает сообщение или None
    при ошибке пытается сделать это несколько раз

    даже если указан reply_to_message_id всё равно смотрит в базу и если у юзера отключены
    реплаи то не испольует его
    '''

    full_chat_id = get_topic_id(message)
    reply = my_db.get_user_property(full_chat_id, 'send_message') or ''

    n = 5
    while n >= 0:
        n -= 1

        try:
            if not reply:
                r = bot.send_audio(
                    chat_id=chat_id,
                    audio=audio,
                    caption=caption,
                    duration=duration,
                    performer=performer,
                    title=title,
                    parse_mode=parse_mode,
                    caption_entities=caption_entities,
                    disable_notification=disable_notification,
                    protect_content=protect_content,
                    reply_to_message_id=reply_to_message_id,
                    allow_sending_without_reply=allow_sending_without_reply,
                    reply_markup=reply_markup,
                    timeout=timeout,
                    thumbnail = thumbnail,
                    message_thread_id=message_thread_id,
                    thumb=thumb,
                    reply_parameters=reply_parameters,
                    business_connection_id=business_connection_id,
                    message_effect_id=message_effect_id,
                    allow_paid_broadcast=allow_paid_broadcast
                )
            else:
                r = bot.send_audio(
                    chat_id=chat_id,
                    audio=audio,
                    caption=caption,
                    duration=duration,
                    performer=performer,
                    title=title,
                    parse_mode=parse_mode,
                    caption_entities=caption_entities,
                    disable_notification=disable_notification,
                    protect_content=protect_content,
                    allow_sending_without_reply=allow_sending_without_reply,
                    reply_markup=reply_markup,
                    timeout=timeout,
                    thumbnail = thumbnail,
                    message_thread_id=message_thread_id,
                    thumb=thumb,
                    reply_parameters=reply_parameters,
                    business_connection_id=business_connection_id,
                    message_effect_id=message_effect_id,
                    allow_paid_broadcast=allow_paid_broadcast
                )
            return r

        except Exception as error:

            if 'Error code: 500. Description: Internal Server Error' in str(error):
                my_log.log2(f'tb:send_audio:1: {error}')
                time.sleep(10)
                continue

            # попробовать отправить не ответ на удаленное сообщение а просто сообщение
            if 'Bad Request: message to be replied not found' not in str(error):
                reply = not reply
                continue

            # если в ответе написано подождите столько то секунд то ждем столько то + 5
            seconds = utils.extract_retry_seconds(str(error))
            if seconds:
                time.sleep(seconds + 5)
                continue

            # неизвестная ошибка
            else:
                traceback_error = traceback.format_exc()
                my_log.log2(f'tb:send_audio:2: {error}\n\n{traceback_error}')
                break

    return None


def send_voice(
    message: telebot.types.Message,
    chat_id: int | str,
    voice: Any | str,
    caption: str | None = None,
    duration: int | None = None,
    reply_to_message_id: int | None = None,
    reply_markup: telebot.REPLY_MARKUP_TYPES | None = None,
    parse_mode: str | None = None,
    disable_notification: bool | None = True,
    timeout: int | None = 120,
    caption_entities: List[telebot.types.MessageEntity] | None = None,
    allow_sending_without_reply: bool | None = None,
    protect_content: bool | None = None,
    message_thread_id: int | None = None,
    reply_parameters: telebot.types.ReplyParameters | None = None,
    business_connection_id: str | None = None,
    message_effect_id: str | None = None,
    allow_paid_broadcast: bool | None = None
) -> telebot.types.Message:
    '''
    bot.send_voice wrapper

    посылает голосовое сообщение, возвращает сообщение или None
    при ошибке пытается сделать это несколько раз

    даже если указан reply_to_message_id всё равно смотрит в базу и если у юзера отключены
    реплаи то не испольует его
    '''

    full_chat_id = get_topic_id(message)
    reply = my_db.get_user_property(full_chat_id, 'send_message') or ''

    n = 5
    while n >= 0:
        n -= 1

        try:
            if not reply:
                r = bot.send_voice(
                    chat_id=chat_id,
                    voice=voice,
                    caption=caption,
                    duration=duration,
                    parse_mode=parse_mode,
                    caption_entities=caption_entities,
                    disable_notification=disable_notification,
                    protect_content=protect_content,
                    reply_to_message_id=reply_to_message_id,
                    allow_sending_without_reply=allow_sending_without_reply,
                    reply_markup=reply_markup,
                    timeout=timeout,
                    message_thread_id=message_thread_id,
                    reply_parameters=reply_parameters,
                    business_connection_id=business_connection_id,
                    message_effect_id=message_effect_id,
                    allow_paid_broadcast=allow_paid_broadcast
                )
            else:
                r = bot.send_voice(
                    chat_id=chat_id,
                    voice=voice,
                    caption=caption,
                    duration=duration,
                    parse_mode=parse_mode,
                    caption_entities=caption_entities,
                    disable_notification=disable_notification,
                    protect_content=protect_content,
                    allow_sending_without_reply=allow_sending_without_reply,
                    reply_markup=reply_markup,
                    timeout=timeout,
                    message_thread_id=message_thread_id,
                    reply_parameters=reply_parameters,
                    business_connection_id=business_connection_id,
                    message_effect_id=message_effect_id,
                    allow_paid_broadcast=allow_paid_broadcast
                )
            return r

        except Exception as error:

            if 'Error code: 500. Description: Internal Server Error' in str(error):
                my_log.log2(f'tb:send_voice:1: {error}')
                time.sleep(10)
                continue

            # попробовать отправить не ответ на удаленное сообщение а просто сообщение
            if 'Bad Request: message to be replied not found' not in str(error):
                reply = not reply
                continue

            # если в ответе написано подождите столько то секунд то ждем столько то + 5
            seconds = utils.extract_retry_seconds(str(error))
            if seconds:
                time.sleep(seconds + 5)
                continue

            # неизвестная ошибка
            else:
                traceback_error = traceback.format_exc()
                my_log.log2(f'tb:send_voice:2: {error}\n\n{traceback_error}')
                break

    return None


@bot.message_handler(content_types = ['photo', "text"], func=authorized)
@async_run
def handle_photo_and_text(message: telebot.types.Message):
    """
    Обработчик текстовых сообщени и картинок, нужен что бы ловить пересланные картинки с подписью,
    телеграм разделяет их на 2 сообщения, отдельно подпись которую делает юзер к пересылаемой картинке
    и отдельно картинка.
    Картинок может быть несколько, текстовых сообщений тоже, их надо склеивать и пересылать дальше.

    Обработчик должен быть выше этих обработчиков но ниже чем все команды и пересылать в них.

    Если сообщений несколько и они разного типа то приоритет должен быть у картинок, текст надо
    добавлять им в caption, причем caption должен быть только у одной картинки
    (надо пробежаться по ним и убрать у всех кроме одного а у одного сделать склейку)
    """
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        # зачем тут сбрасывать? из за этого текстовый обработчик не получает команды
        # COMMAND_MODE[chat_id_full] = ''

        # catch groups of messages
        if chat_id_full not in MESSAGE_QUEUE_GRP:
            MESSAGE_QUEUE_GRP[chat_id_full] = [message,]
            last_state = MESSAGE_QUEUE_GRP[chat_id_full]
            n = 10
            while n > 0:
                n -= 1
                time.sleep(0.1)
                new_state = MESSAGE_QUEUE_GRP[chat_id_full]
                if last_state != new_state:
                    last_state = new_state
                    n = 10
        else:
            MESSAGE_QUEUE_GRP[chat_id_full].append(message)
            return


        if len(MESSAGE_QUEUE_GRP[chat_id_full]) > 1:
            MESSAGES = MESSAGE_QUEUE_GRP[chat_id_full]
        else:
            MESSAGES = [message,]
        del MESSAGE_QUEUE_GRP[chat_id_full]


        is_image = False
        combined_caption = ''


        # если не обращено к боту то нафиг
        MSG = MESSAGES[0]
        is_private = MSG.chat.type == 'private'
        supch = my_db.get_user_property(chat_id_full, 'superchat') or 0
        is_reply = message.reply_to_message and message.reply_to_message.from_user.id == BOT_ID
        bot_name2 = f'@{_bot_name}'
        bot_name1 = my_db.get_user_property(chat_id_full, 'bot_name') or BOT_NAME_DEFAULT
        bot_name_was_used = False
        # убираем из запроса имя бота в телеграме
        msglower = MSG.text.lower() if MSG.text else ''
        if not msglower:
            msglower = MSG.caption.lower() if MSG.caption else ''
        if msglower.startswith((f'{bot_name2} ', f'{bot_name2},', f'{bot_name2}\n')):
            bot_name_was_used = True
        if not bot_name_was_used and msglower.startswith((f'{bot_name1} ', f'{bot_name1},', f'{bot_name1}\n')):
            bot_name_was_used = True
        if re.match(r"^(гугл|google)[ ,.\n]+", msglower):
            bot_name_was_used = True
        if supch == 1 or is_reply or bot_name_was_used:
            is_private = True
        if not is_private:
            return


        # проходим по всем сообщениям и если есть картинки то зачищаем их подписи
        for MSG in MESSAGES:
            if MSG.photo:
                is_image = True
                combined_caption += my_log.restore_message_text(MSG.caption or '', MSG.caption_entities or []) + '\n\n'
                MSG.caption = ''
                MSG.caption_entities = []
        combined_caption = combined_caption.strip()


        # проверка на подписку
        if is_image:
            if chat_id_full in COMMAND_MODE:
                del COMMAND_MODE[chat_id_full]

        if not my_subscription.check_donate(message, chat_id_full, lang, COMMAND_MODE, CHECK_DONATE_LOCKS, BOT_ID, tr, bot_reply, get_keyboard):
            return


        # если есть картинки (в них уже зачищены подписи) тогда надо удалить текстовые соообщения
        # (точнее добавить текстовые сообщения сверху к объединенной подписи) и отправить
        # дальше только картинки но сначала в первую картинку надо добавить объединенную подпись
        if is_image:
            for MSG in MESSAGES[:]:
                if not MSG.photo:
                    text = my_log.restore_message_text(MSG.text or '', MSG.entities or [])
                    if text.strip():
                        combined_caption = text.strip() + '\n\n' + combined_caption
                    MESSAGES.remove(MSG)

            # в первое сообщение кладем общую подпись
            MESSAGES[0].caption = combined_caption
            MESSAGES[0].caption_entities = []

            for MSG in MESSAGES:
                handle_photo(MSG)

        # если картинок нет то просто отправить все сообщения в текстовый обработчик
        else:
            for MSG in MESSAGES:
                echo_all(MSG)

    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:handle_photo_and_text_unknown: {unknown}\n{traceback_error}')


def detect_img_answer(message: telebot.types.Message, answer: str) -> bool:
    '''
    Если в ответе есть признаки того что бот обнаружил запрос на рисование но вернул неадекватный ответ
    рисуем принудительно
    '''
    try:
        result = False

        msg = answer.lower().strip()
        if msg.startswith('```json') and msg.endswith('```'):
            msg = msg[7:-3].strip()
            answer = answer[7:-3].strip()
        elif msg.startswith('```') and msg.endswith('```'):
            msg = msg[3:-3].strip()
            answer = answer[3:-3].strip()

        if ('create image' in msg or 'generate image' in msg) and len(msg) < 20:
            result = True
            reprompt = message.text

        if msg.startswith('the bot successfully generated images on the external services'):
            result = True
            reprompt = message.text

        if not result:
            if msg.startswith('{') and msg.endswith('}'):
                try:
                    dict_ = utils.string_to_dict(answer)
                except Exception as e:
                    dict_ = None
                    my_log.log2(f'tb:detect_img_answer: {e}')
                if dict_ and isinstance(dict_, dict):
                    reprompt = dict_.get('reprompt', '')
                    was_translated = dict_.get('was_translated', '')
                    lang_from = dict_.get('lang_from', '')
                    moderation_sexual = dict_.get('moderation_sexual', '')
                    moderation_hate = dict_.get('moderation_hate', '')
                    if reprompt and was_translated and lang_from and moderation_sexual!='' and moderation_hate!='':
                        result = True

        if result:
            undo_cmd(message, show_message=False)
            message.text = f'/img {reprompt}'
            image_gen(message)

        return result

    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:detect_img_answer: {unknown}\n{traceback_error}')
        return False


def edit_image_detect(text: str, lang: str, chat_id_full: str, message: telebot.types.Message, hidden_text: str, gemini_mem: bool = False) -> bool:
    '''
    Пытается определить есть ли в строке маркер EDIT IMAGE
    '''
    result = False

    try:
        if text and text.strip():
            text = text.strip()
        else:
            result = False
        if "EDIT IMAGE" in text and len(text) < 30:
            result = True
        elif text.lower() == 'edit_image':
            result = True
        elif "EDIT IMAGE" in text and len(text) > 30 and 'edit_image(' in text:
            result = True
        elif text == tr('Changed image successfully.', lang):
            result = True
        elif text in ('Изображение создается.',):
            result = True
        else:
            result = False

        if result:
            if chat_id_full in WHO_ANSWERED:
                del WHO_ANSWERED[chat_id_full]
            # отменяем ответ
            if gemini_mem:
                my_gemini3.undo(chat_id_full)
            else:
                my_openrouter.undo(chat_id_full)

            source_images = UNCAPTIONED_IMAGES[chat_id_full][2] if chat_id_full in UNCAPTIONED_IMAGES else None
            query = message.text
            r = ''
            if not source_images:
                undo_cmd(message, show_message=False)
                message.text = f'/img {message.text}'
                image_gen(message)
            else:
                if gemini_mem:
                    r = img2img(
                        text=source_images,
                        lang=lang,
                        chat_id_full=chat_id_full,
                        query=query,
                        # model=gmodel, # это ломает повторный запрос на редактирование?
                        temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                        system_message=hidden_text,
                    )
                else:
                    r = img2img(
                        text=source_images,
                        lang=lang,
                        chat_id_full=chat_id_full,
                        query=query,

                        temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                        system_message=hidden_text,
                    )
            if r and isinstance(r, bytes):
                add_to_bots_mem(tr('User asked to edit image', lang) + f' <prompt>{query}</prompt>', tr('Changed image successfully.', lang), chat_id_full)
                m = send_photo(
                    message,
                    message.chat.id,
                    r,
                    disable_notification=True,
                    reply_to_message_id=message.message_id,
                    reply_markup=get_keyboard('hide', message),
                )
                log_message(m)
            else:
                add_to_bots_mem(tr('User asked to edit image', lang) + f' <prompt>{query}</prompt>', tr('Failed to edit image.', lang), chat_id_full)
                bot_reply_tr(message, 'Failed to edit image.')


    except Exception as e:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:edit_image_detect: {e}\n{traceback_error}')
        return False
    finally:
        return result


@bot.message_handler(content_types = ['photo', 'sticker', 'animation'], func=authorized)
@async_run
def handle_photo(message: telebot.types.Message):
    """Обработчик фотографий. Сюда же попадают новости которые создаются как фотография
    + много текста в подписи, и пересланные сообщения в том числе"""
    my_cmd_photo.handle_photo(
        message=message,

        # Core objects and constants
        bot=bot,
        BOT_ID=BOT_ID,
        _bot_name=_bot_name,
        BOT_NAME_DEFAULT=BOT_NAME_DEFAULT,

        # Global state dictionaries
        COMMAND_MODE=COMMAND_MODE,
        IMG_LOCKS=IMG_LOCKS,
        CHECK_DONATE_LOCKS=CHECK_DONATE_LOCKS,
        MESSAGE_QUEUE_IMG=MESSAGE_QUEUE_IMG,

        # Helper functions and classes
        get_topic_id=get_topic_id,
        get_lang=get_lang,
        tr=tr,
        bot_reply=bot_reply,
        bot_reply_tr=bot_reply_tr,
        get_keyboard=get_keyboard,
        add_to_bots_mem=add_to_bots_mem,
        log_message=log_message,
        send_document=send_document,
        send_photo=send_photo,
        proccess_image=proccess_image,
        img2txt=img2txt,
        send_all_files_from_storage=send_all_files_from_storage,
        ShowAction=ShowAction,
        download_image_from_message=download_image_from_message,
        img2img=img2img,

        # Command handler functions
        google=google,
        do_task=echo_all,
    )


@bot.message_handler(func=authorized)
def echo_all(message: telebot.types.Message, custom_prompt: str = '') -> None:
    thread = threading.Thread(target=do_task, args=(message, custom_prompt ))
    thread.start()
def do_task(message, custom_prompt = ''):
    """default handler"""
    my_cmd_text.do_task(
        message,

        # Core objects and constants
        bot=bot,
        request_counter=request_counter,
        BOT_ID=BOT_ID,
        _bot_name=_bot_name,

        # Global state dictionaries
        COMMAND_MODE=COMMAND_MODE,
        MESSAGE_QUEUE=MESSAGE_QUEUE,
        CHAT_LOCKS=CHAT_LOCKS,
        WHO_ANSWERED=WHO_ANSWERED,
        CHECK_DONATE_LOCKS=CHECK_DONATE_LOCKS,
        IMG_MODE_FLAG=IMG_MODE_FLAG,
        CACHE_CHECK_PHONE=CACHE_CHECK_PHONE,
        DEBUG_MD_TO_HTML=DEBUG_MD_TO_HTML,
        GEMIMI_TEMP_DEFAULT=GEMIMI_TEMP_DEFAULT,
        BOT_NAME_DEFAULT=BOT_NAME_DEFAULT,

        # Helper functions and classes
        get_topic_id=get_topic_id,
        get_lang=get_lang,
        tr=tr,
        bot_reply=bot_reply,
        bot_reply_tr=bot_reply_tr,
        get_keyboard=get_keyboard,
        reset_=reset_,
        undo_cmd=undo_cmd,
        detect_img_answer=detect_img_answer,
        edit_image_detect=edit_image_detect,
        send_all_files_from_storage=send_all_files_from_storage,
        transcribe_file=transcribe_file,
        proccess_image=proccess_image,
        process_image_stage_2=process_image_stage_2,
        ShowAction=ShowAction,
        getcontext=getcontext,

        # Command handler functions
        tts=tts,
        trans=trans,
        change_mode=change_mode,
        change_style2=change_style2,
        image_gen=image_gen,
        image_bing_gen=image_bing_gen,
        image_bing_gen_gpt=image_bing_gen_gpt,
        image_flux_gen=image_flux_gen,
        image_gemini_gen=image_gemini_gen,
        google=google,
        ask_file=ask_file,
        ask_file2=ask_file2,
        memo_handler=memo_handler,
        summ_text=summ_text,
        send_name=send_name,
        calc_gemini=calc_gemini,

        custom_prompt=custom_prompt,
    )


TIMESTAMP_START_FILE = 0
TIMESTAMP_HELP_FILE = 0
# @async_run
def load_msgs():
    """
    Load the messages from the start and help message files into the HELLO_MSG and HELP_MSG global variables.

    Parameters:
        None

    Returns:
        None
    """
    try:
        global HELLO_MSG, HELP_MSG, TIMESTAMP_START_FILE, TIMESTAMP_HELP_FILE

        changed_start = False
        changed_help = False

        timestamp_start = os.path.getmtime(my_init.start_msg_file)
        timestamp_help = os.path.getmtime(my_init.help_msg_file)

        if timestamp_start > TIMESTAMP_START_FILE or not HELLO_MSG:
            changed_start = True

        if timestamp_help > TIMESTAMP_HELP_FILE or not HELP_MSG:
            changed_help = True

        if changed_start:
            try:
                with open(my_init.start_msg_file, 'rb') as f:
                    HELLO_MSG = pickle.load(f)
            except Exception as error:
                my_log.log2(f'tb:load_msgs:hello {error}')
                HELLO_MSG = {}

        if changed_help:
            try:
                with open(my_init.help_msg_file, 'rb') as f:
                    HELP_MSG = pickle.load(f)
            except Exception as error:
                my_log.log2(f'tb:load_msgs:help {error}')
                HELP_MSG = {}
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:log_msgs: {unknown}\n{traceback_error}')


def one_time_shot():
    try:
        if not os.path.exists('one_time_flag.txt'):
            pass

            # my_gemini3.converts_all_mems()
            my_gemini3.remove_pics_from_all_mems()

            queries = [
                # '''ALTER TABLE users DROP COLUMN api_key_huggingface;''',

                # '''ALTER TABLE users DROP COLUMN dialog_gemini;''',
                # '''ALTER TABLE users ADD COLUMN dialog_gemini BLOB;''',

                # '''DELETE FROM translations;''',
                # '''DROP TABLE IF EXISTS im_suggests;''',
                # '''UPDATE users SET saved_file = NULL, saved_file_name = NULL;''',
            ]
            if queries:
                for q in queries:
                    try:
                        my_db.CUR.execute(q)
                    except Exception as error:
                        my_log.log2(f'tb:one_time_shot: {error}')
            my_db.CON.commit()

            # Выполняем VACUUM вне транзакции
            try:
                # my_db.CUR.execute('VACUUM;')
                my_db.CON.commit()
            except Exception as error:
                my_log.log2(f'tb:one_time_shot: VACUUM error: {error}')

            with open('one_time_flag.txt', 'w') as f:
                f.write('done')
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:one_time_shot: {error}\n{traceback_error}')


## rest api #######################################################################

@FLASK_APP.route('/bing', methods=['POST'])
def bing_api_post() -> Dict[str, Any]:
    """
    API endpoint for generating images using Bing.

    :return: A JSON response containing a list of URLs or an error message.
    """
    try:
        # Get JSON data from the request
        data: Dict[str, Any] = request.get_json()

        # Extract the prompt from the JSON data
        prompt: str = data.get('prompt', '')

        if not prompt:
            return jsonify({"error": "Prompt is required"}), 400

        # Generate images using Bing API
        image_urls: List[str] = my_genimg.gen_images_bing_only(prompt)
        # image_urls: List[str] = ['url1', 'url2', 'url3', 'url4']

        if not image_urls:
            return jsonify({"error": "No images generated"}), 404

        return jsonify({"urls": image_urls}), 200
    except Exception as e:
        my_log.log_bing_api(f'tb:bing_api_post: {e}')
        return jsonify({"error": str(e)}), 500


@FLASK_APP.route('/images', methods=['POST'])
def images_api_post() -> Dict[str, Any]:
    """
    API endpoint for generating images using all providers.

    :return: A JSON response containing a list of URLs (str) or base64 encoded image data (str) or an error message.
    """
    try:
        # Get JSON data from the request
        data: Dict[str, Any] = request.get_json()

        # Extract the prompt from the JSON data
        prompt: str = data.get('prompt', '')

        if not prompt:
            return jsonify({"error": "Prompt is required"}), 400

        # Generate images using available APIs, the result can be a list of strings (URLs) or bytes (image data)
        image_results: List[Union[str, bytes]] = my_genimg.gen_images(prompt, user_id='api_images')
        # image_results: List[Union[str, bytes]] = ['url1', b'image_data_1', 'url2', b'image_data_2']

        if not image_results:
            prompt = prompt.strip()
            # remove trailing !
            prompt = re.sub(r'^!+', '', prompt).strip()
            # Get English prompt and negative prompt using the function
            reprompt, negative_prompt = my_genimg.get_reprompt(prompt)
            if reprompt != 'MODERATION':
                image_results = my_genimg.flux_nebius_gen1(reprompt, negative_prompt, model = 'black-forest-labs/flux-dev')

        if not image_results:
            return jsonify({"error": "No images generated"}), 404

        # Process the results to convert bytes to base64 encoded strings
        processed_results: List[str] = []
        for item in image_results:
            if isinstance(item, bytes):
                # Encode bytes to base64 string
                processed_results.append(base64.b64encode(item).decode('utf-8'))
            else:
                # Assume it's a string (URL) and add it directly
                processed_results.append(item)

        return jsonify({"results": processed_results}), 200

    except Exception as e:
        my_log.log_bing_api(f'tb:images_api_post: {e}')
        return jsonify({"error": str(e)}), 500


@async_run
def run_flask(addr: str ='127.0.0.1', port: int = 58796):
    try:
        FLASK_APP.run(debug=True, use_reloader=False, host=addr, port = port)
    except Exception as error:
        my_log.log_bing_api(f'tb:run_flask: {error}')


## rest api #######################################################################


def main():
    """
    Runs the main function, which sets default commands and starts polling the bot.
    """
    try:

        db_backup = cfg.DB_BACKUP if hasattr(cfg, 'DB_BACKUP') else True
        db_vacuum = cfg.DB_VACUUM if hasattr(cfg, 'DB_VACUUM') else False
        my_db.init(db_backup, db_vacuum)

        load_msgs()

        my_cerebras.load_users_keys()
        my_gemini_general.load_users_keys()
        my_groq.load_users_keys()
        my_mistral.load_users_keys()
        my_cohere.load_users_keys()
        my_github.load_users_keys()
        my_nebius.load_users_keys()
        my_skills.init()
        my_openrouter_free.init()

        one_time_shot()

        log_group_daemon()

        if hasattr(cfg, 'BING_API') and cfg.BING_API:
            run_flask(addr='127.0.0.1', port=58796)
            # run_flask(addr='0.0.0.0', port=58796)

        time.sleep(1)


        # import my_gemini_voice
        # my_gemini_voice.test2_read_a_book_()
        # import my_gemini_imagen
        # my_gemini_imagen.test_imagen()
        # print(my_gemini3.chat('привет ты как', model = 'gemini-2.5-flash', chat_id='test', system='отвечай всегда по-русски'))
        # my_gemini3.trim_all()
        # print(my_mistral.transcribe_audio(r'C:\Users\user\Downloads\samples for ai\аудио\короткий диалог 3 голоса.m4a', language='en', get_timestamps=False))
        # my_cohere.list_models()
        # my_cohere.test_chat()


        bot.infinity_polling(timeout=90, long_polling_timeout=90)

        global LOG_GROUP_DAEMON_ENABLED
        LOG_GROUP_DAEMON_ENABLED = False
        time.sleep(10)
        my_db.close()
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:main: {unknown}\n{traceback_error}')


if __name__ == '__main__':
    main()
