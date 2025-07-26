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
import tempfile
import traceback
import threading
import time
from flask import Flask, request, jsonify
from decimal import Decimal, getcontext
from typing import Any, Dict, List, Optional, Union

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
import my_cohere
import my_db
import my_ddg
import my_doc_translate
import my_github
import my_google
import my_gemini
import my_gemini_general
import my_gemini3
import my_gemini_live_text
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
import my_skills_storage
import my_stat
import my_stt
import my_svg
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
NEW_KEYBOARD = SqliteDict('db/new_keyboard_installed.db', autocommit=True)


# запоминаем группы файлов (для правильного приема групп текстовых файлов)
# {user_id: message_group_id}
FILE_GROUPS = {}


# {user_id:(date, image),} keep up to UNCAPTIONED_IMAGES_MAX images
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


def edit_image_detect(text: str, lang: str) -> bool:
    '''
    Пытается определить есть ли в строке маркер EDIT IMAGE
    '''
    try:
        if text and text.strip():
            text = text.strip()
        else:
            return False
        if "EDIT IMAGE" in text and len(text) < 30:
            return True
        elif "EDIT IMAGE" in text and len(text) > 30 and 'edit_image(' in text:
            return True
        elif text == tr('Changed image successfully.', lang):
            return True
        elif text in ('Изображение создается.',):
            return True
        elif text.startswith(('<<GENERATE IMAGE>>','<<CREATE IMAGE>>')):
            return True
        else:
            return False
    except Exception as e:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:edit_image_detect: {e}\n{traceback_error}')
        return False


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

        translated = my_gemini3.translate(text, to_lang=lang, help=help, censored=True)
        if not translated:
            # time.sleep(1)
            # try again and another ai engine
            translated = my_groq.translate(text, to_lang=lang, help=help)
            if not translated:
                my_log.log_translate(f'gemini\n\n{text}\n\n{lang}\n\n{help}')

        if not translated:
            translated = my_trans.translate(text, lang)

        if not translated and not help:
            translated = my_groq.translate(text, to_lang=lang, help=help)

        if not translated and not help:
            translated = my_gemini3.translate(text, to_lang=lang, help=help)

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

        mode = my_db.get_user_property(chat_id_full, 'chat_mode')

        # Updates the memory of the selected bot based on the chat mode.
        if any(mode.startswith(m) for m in ('gemini', 'gemma')):
            my_gemini3.update_mem(query, resp, chat_id_full, model=mode)
        elif 'openrouter' in mode:
            my_openrouter.update_mem(query, resp, chat_id_full)
        elif 'qwen3' in mode:
            my_openrouter_free.update_mem(query, resp, chat_id_full)
        elif mode in ('mistral', 'magistral'):
            my_mistral.update_mem(query, resp, chat_id_full)
        elif mode in ('gpt-4o', 'gpt_41', 'gpt_41_mini', 'deepseek_r1', 'deepseek_v3'):
            my_github.update_mem(query, resp, chat_id_full)
        elif 'cohere' in mode:
            my_cohere.update_mem(query, resp, chat_id_full)
        else:
            raise Exception(f'Unknown chat mode: {mode}')
    except Exception as unexpected_error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:add_to_bots_mem:{unexpected_error}\n\n{traceback_error}')


def img2img(
    text,
    lang: str,
    chat_id_full: str,
    query: str = '',
    model: str = '',
    temperature: float = 0,
    system_message: str = '',
    timeout: int = 120,
    ) -> Optional[bytes]:
    """
    Regenerate the image using query.

    Args:
        text (str): The image file URL or downloaded data(bytes).
        lang (str): The language code for the image description.
        chat_id_full (str): The full chat ID.
        query (str): The user's query text.
        model (str): gemini model
        temperature (float): temperature
        system_message (str): system message (role/style)
        timeout (int): timeout

    Returns:
        str: new image as jpg bytes.
    """
    images = [text,]

    return my_gemini_genimg.regenerate_image(query, sources_images=images, user_id=chat_id_full)


def img2txt(
    text,
    lang: str,
    chat_id_full: str,
    query: str = '',
    model: str = '',
    temperature: float = 0,
    system_message: str = '',
    timeout: int = 120,
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

    Returns:
        str: The text description of the image.
    """
    try:
        query = query.strip()
        query__ = query
        time_to_answer_start = time.time()

        # если запрос начинается на ! то надо редактировать картинку а не отвечать на вопрос
        if query.startswith('!'):
            r = img2img(
                text,
                lang,
                chat_id_full,
                query[1:],
                model,
                temperature,
                system_message,
                timeout
            )
            if r:
                add_to_bots_mem(tr('User asked to edit image', lang) + f' <prompt>{query[1:]}</prompt>', tr('Changed image successfully.', lang), chat_id_full)
            else:
                add_to_bots_mem(tr('User asked to edit image', lang) + f' <prompt>{query[1:]}</prompt>', tr('Failed to edit image.', lang), chat_id_full)
            return r

        if temperature is None:
            temperature = my_db.get_user_property(chat_id_full, 'temperature') or 1
        if system_message is None:
            system_message = my_db.get_user_property(chat_id_full, 'role') or ''

        if isinstance(text, bytes):
            data = text
        else:
            data = utils.download_image_as_bytes(text)

        original_query = query or tr('Describe in detail what you see in the picture. If there is text, write it out in a separate block. If there is very little text, then write a prompt to generate this image.', lang)

        if not query:
            query = tr('Describe the image, what do you see here? Extract all text and show it preserving text formatting. Write a prompt to generate the same image - use markdown code with syntax highlighting ```prompt\n/img your prompt in english```', lang)
        if 'markdown' not in query.lower() and 'latex' not in query.lower():
            query = query + '\n\n' + my_init.get_img2txt_prompt(tr, lang)

        text = ''
        qr_code = my_qrcode.get_text(data)
        if qr_code:
            query = f"{query}\n\n{tr('QR Code was automatically detected on the image, it`s text:', lang)} {qr_code}"

        try:
            chat_mode = my_db.get_user_property(chat_id_full, 'chat_mode')

            system_message_gemini = system_message
            if 'gemini' in chat_mode:
                system_message_gemini = system_message + '\n\n' + tr("Если ты не можешь ответить на запрос пользователя то ответь словом 'STOP', никаких других слов не должно быть, не отвечай что ты не можешь что то сделать.", lang)


            # запрос на OCR?
            if query__ == 'OCR':
                if not text:
                    text = my_mistral.ocr_image(data, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_mistral_ocr'
            # если запрос - gpt то сначала пробуем через gpt
            if query__ == 'gpt':
                if not text:
                    text = my_github.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, model=my_github.BIG_GPT_41_MODEL, system=system_message, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + my_github.BIG_GPT_41_MODEL
                    else:
                        text = my_github.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, model=my_github.DEFAULT_41_MINI_MODEL, system=system_message, timeout=timeout)
                        if text:
                            WHO_ANSWERED[chat_id_full] = 'img2txt_' + my_github.DEFAULT_41_MINI_MODEL

                if not text:
                    text = my_github.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, model=my_github.BIG_GPT_MODEL, system=system_message, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + my_github.BIG_GPT_MODEL
                    else:
                        text = my_github.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, model=my_github.DEFAULT_MODEL, system=system_message, timeout=timeout)
                        if text:
                            WHO_ANSWERED[chat_id_full] = 'img2txt_' + my_github.DEFAULT_MODEL


            # попробовать с помощью openrouter
            # если модель не указана явно то определяем по режиму чата
            if not model and not text:
                if not text and chat_mode == 'openrouter':
                    text = my_openrouter.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, system=system_message, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + 'openrouter'

                # if not text and chat_mode == 'qwen3':
                #     text = my_openrouter_free.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, system=system_message, timeout=timeout)
                #     if text:
                #         WHO_ANSWERED[chat_id_full] = 'img2txt_' + 'qwen3'

                elif not text and chat_mode == 'gpt-4o':
                    text = my_github.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, model=my_github.BIG_GPT_MODEL, system=system_message, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + my_github.BIG_GPT_MODEL
                    else:
                        text = my_github.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, model=my_github.DEFAULT_MODEL, system=system_message, timeout=timeout)
                        if text:
                            WHO_ANSWERED[chat_id_full] = 'img2txt_' + my_github.DEFAULT_MODEL

                elif not text and chat_mode == 'gpt_41':
                    text = my_github.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, model=my_github.BIG_GPT_41_MODEL, system=system_message, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + my_github.BIG_GPT_41_MODEL
                    else:
                        text = my_github.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, model=my_github.DEFAULT_41_MINI_MODEL, system=system_message, timeout=timeout)
                        if text:
                            WHO_ANSWERED[chat_id_full] = 'img2txt_' + my_github.DEFAULT_41_MINI_MODEL

                elif not text and chat_mode == 'gpt_41_mini':
                    text = my_github.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, model=my_github.DEFAULT_41_MINI_MODEL, system=system_message, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + my_github.DEFAULT_41_MINI_MODEL
                    else:
                        text = my_github.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, model=my_github.DEFAULT_MODEL, system=system_message, timeout=timeout)
                        if text:
                            WHO_ANSWERED[chat_id_full] = 'img2txt_' + my_github.DEFAULT_MODEL

                elif not text and chat_mode == 'gemini15':
                    text = my_gemini3.img2txt(data, query, model=cfg.gemini_pro_model, temp=temperature, chat_id=chat_id_full, system=system_message_gemini, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + cfg.gemini_pro_model
                elif not text and chat_mode == 'gemini25_flash':
                    text = my_gemini3.img2txt(data, query, model=cfg.gemini25_flash_model, temp=temperature, chat_id=chat_id_full, system=system_message_gemini, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + cfg.gemini25_flash_model
                elif not text and chat_mode == 'gemini-exp':
                    text = my_gemini3.img2txt(data, query, model=cfg.gemini_exp_model, temp=temperature, chat_id=chat_id_full, system=system_message_gemini, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + cfg.gemini_exp_model
                elif not text and chat_mode == 'gemini-learn':
                    text = my_gemini3.img2txt(data, query, model=cfg.gemini_learn_model, temp=temperature, chat_id=chat_id_full, system=system_message_gemini, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + cfg.gemini_learn_model
                elif not text and chat_mode == 'gemma3_27b':
                    text = my_gemini3.img2txt(data, query, model=cfg.gemma3_27b_model, temp=temperature, chat_id=chat_id_full, system=system_message, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + cfg.gemma3_27b_model
                elif not text and chat_mode == 'gemini-lite':
                    text = my_gemini3.img2txt(data, query, model=cfg.gemini_flash_light_model, temp=temperature, chat_id=chat_id_full, system=system_message_gemini, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + cfg.gemini_flash_light_model
                elif not text and chat_mode == 'gemini':
                    text = my_gemini3.img2txt(data, query, model=cfg.gemini_flash_model, temp=temperature, chat_id=chat_id_full, system=system_message_gemini, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + cfg.gemini_flash_model


            # если модель не указана явно и не был получен ответ в предыдущем блоке то используем
            # стандартную модель (возможно что еще раз)
            if not model and not text:
                model = cfg.img2_txt_model

            # сначала попробовать с помощью дефолтной модели
            if not text:
                if 'gpt' in model:
                    text = my_github.img2txt(data, query, chat_id=chat_id_full, model=model, temperature=temperature, system=system_message, timeout=timeout)
                    if not text:
                        text = my_gemini3.img2txt(data, query, model=model, temp=temperature, chat_id=chat_id_full, system=system_message_gemini, timeout=timeout)
                else:
                    text = my_gemini3.img2txt(data, query, model=model, temp=temperature, chat_id=chat_id_full, system=system_message_gemini, timeout=timeout)
                if text:
                    WHO_ANSWERED[chat_id_full] = 'img2txt_' + model


            # если это была джемини про то пробуем ее фолбек
            if not text and model == cfg.gemini_pro_model:
                text = my_gemini3.img2txt(data, query, model=cfg.gemini_pro_model_fallback, temp=temperature, chat_id=chat_id_full, system=system_message_gemini, timeout=timeout)
                if text:
                    WHO_ANSWERED[chat_id_full] = 'img2txt_' + cfg.gemini_pro_model_fallback

            # если это была не джемини лайт то пробуем ее
            if not text and model != cfg.gemini_flash_light_model:
                text = my_gemini3.img2txt(data, query, model=cfg.gemini_flash_light_model, temp=temperature, chat_id=chat_id_full, system=system_message_gemini, timeout=timeout)
                if text:
                    WHO_ANSWERED[chat_id_full] = 'img2txt_' + cfg.gemini_flash_light_model


            # флеш25 фолбек
            if not text and model == cfg.gemini25_flash_model:
                text = my_gemini3.img2txt(data, query, model=cfg.gemini25_flash_model_fallback, temp=temperature, chat_id=chat_id_full, system=system_message_gemini, timeout=timeout)
                if text:
                    WHO_ANSWERED[chat_id_full] = 'img2txt_' + cfg.gemini25_flash_model_fallback

            # флеш фолбек
            if not text and model == cfg.gemini_flash_model:
                text = my_gemini3.img2txt(data, query, model=cfg.gemini_flash_model_fallback, temp=temperature, chat_id=chat_id_full, system=system_message_gemini, timeout=timeout)
                if text:
                    WHO_ANSWERED[chat_id_full] = 'img2txt_' + cfg.gemini_flash_model_fallback

            # если ответ длинный и в нем очень много повторений то вероятно это зависший ответ
            # передаем эстафету следующему претенденту
            if len(text) > 2000 and my_transcribe.detect_repetitiveness_with_tail(text):
                text = ''



            # джемини отказалась отвечать?
            if 'stop' in text.lower() and len(text) < 10:
                text = ''



            # далее пробуем gpt4.1 из гитхаба
            if not text:
                text = my_github.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, model=my_github.BIG_GPT_41_MODEL, system=system_message, timeout=timeout)
                if text:
                    WHO_ANSWERED[chat_id_full] = 'img2txt_' + my_github.BIG_GPT_41_MODEL
                else:
                    text = my_github.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, model=my_github.DEFAULT_41_MINI_MODEL, system=system_message, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + my_github.DEFAULT_41_MINI_MODEL


            # gpt 4o
            if not text:
                text = my_github.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, model=my_github.BIG_GPT_MODEL, system=system_message, timeout=timeout)
                if text:
                    WHO_ANSWERED[chat_id_full] = 'img2txt_' + my_github.BIG_GPT_MODEL
                else:
                    text = my_github.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, model=my_github.DEFAULT_MODEL, system=system_message, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + my_github.DEFAULT_MODEL


            # llama-4-maverick at groq
            if not text:
                text = my_groq.img2txt(data, query, model = 'meta-llama/llama-4-maverick-17b-128e-instruct', temperature=temperature, chat_id=chat_id_full, system=system_message, timeout=timeout)
                if text:
                    WHO_ANSWERED[chat_id_full] = 'img2txt_' + 'meta-llama/llama-4-maverick-17b-128e-instruct'

        except Exception as img_from_link_error:
            traceback_error = traceback.format_exc()
            my_log.log2(f'tb:img2txt1: {img_from_link_error}\n\n{traceback_error}')

        if text:
            # если режим не джемини или ответил не джемини значит надо добавить в память ответ вручную
            if 'gemini' not in chat_mode or 'gemini' not in WHO_ANSWERED.get(chat_id_full, ''):
                add_to_bots_mem(tr('User asked about a picture:', lang) + ' ' + original_query, text, chat_id_full)

        if chat_id_full in WHO_ANSWERED:
            if text:
                WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'
            else:
                del WHO_ANSWERED[chat_id_full]


        # добавляем в UNCAPTIONED_IMAGES[chat_id_full] эту картинку что бы она стала последней
        UNCAPTIONED_IMAGES[chat_id_full] = (time.time(), data)

        # если запрос на редактирование
        if edit_image_detect(text, lang):
            if 'gemini' in chat_mode:
                my_gemini3.undo(chat_id_full)

            last_image = UNCAPTIONED_IMAGES[chat_id_full][1] if chat_id_full in UNCAPTIONED_IMAGES else None
            r = img2img(
                last_image,
                lang,
                chat_id_full,
                query__,
                model,
                temperature,
                system_message,
                timeout
            )
            if r:
                add_to_bots_mem(tr('User asked to edit image', lang) + f' <prompt>{query[1:]}</prompt>', tr('Changed image successfully.', lang), chat_id_full)
            else:
                add_to_bots_mem(tr('User asked to edit image', lang) + f' <prompt>{query[1:]}</prompt>', tr('Failed to edit image.', lang), chat_id_full)
            return r

        return text
    except Exception as unexpected_error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:img2txt2:{unexpected_error}\n\n{traceback_error}')
        return ''


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


        # обновить клавиатуру старым юзерам
        if is_private:
            if chat_id_full not in NEW_KEYBOARD:
                bot_reply_tr(message, 'New keyboard installed.',
                            parse_mode='HTML',
                            disable_web_page_preview=True,
                            reply_markup=get_keyboard('start', message))
                NEW_KEYBOARD[chat_id_full] = True


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


def bot_reply(message: telebot.types.Message,
              msg: str,
              parse_mode: str = None,
              disable_web_page_preview: bool = None,
              reply_markup: telebot.types.InlineKeyboardMarkup = None,
              send_message: bool = False,
              not_log: bool = False,
              allow_voice: bool = False):
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
            send_long_message(message, msg, parse_mode=parse_mode,
                                disable_web_page_preview=disable_web_page_preview,
                                reply_markup=reply_markup, allow_voice=allow_voice)
        else:
            reply_to_long_message(message, msg, parse_mode=parse_mode, disable_web_page_preview=disable_web_page_preview,
                            reply_markup=reply_markup, allow_voice=allow_voice)
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
            if my_db.get_user_property(chat_id_full, 'tts_gender'):
                voice = f'tts_{my_db.get_user_property(chat_id_full, "tts_gender")}'
            else:
                voice = 'tts_female'

            sorted_possible_voices = my_gemini_tts.POSSIBLE_VOICES
            # Создаем словарь для голосов Gemini динамически
            gemini_voices_dict = {f"tts_gemini_{voice}": "Gemini" for voice in sorted_possible_voices}
            voices = {
                'tts_female': tr('MS жен.', lang, 'это сокращенный текст на кнопке, полный текст - "Microsoft женский", тут имеется в виду женский голос для TTS от микрософта, сделай перевод таким же коротким что бы уместится на кнопке'),
                'tts_male': tr('MS муж.', lang, 'это сокращенный текст на кнопке, полный текст - "Microsoft мужской", тут имеется в виду мужской голос для TTS от микрософта, сделай перевод таким же коротким что бы уместится на кнопке'),
                'tts_google_female': 'Google',

                'tts_openai_alloy': 'OpenAI',
                'tts_openai_ash': 'OpenAI',
                'tts_openai_ballad': 'OpenAI',
                'tts_openai_coral': 'OpenAI',
                'tts_openai_echo': 'OpenAI',
                'tts_openai_fable': 'OpenAI',
                'tts_openai_onyx': 'OpenAI',
                'tts_openai_nova': 'OpenAI',
                'tts_openai_sage': 'OpenAI',
                'tts_openai_shimmer': 'OpenAI',
                'tts_openai_verse': 'OpenAI',

                **gemini_voices_dict
            }

            if voice in voices:
                voice_title = voices[voice]
            else:
                my_db.set_user_property(chat_id_full, 'tts_gender', 'female')
                voice_title = voices['tts_female']

            chat_mode = my_db.get_user_property(chat_id_full, 'chat_mode')

            markup  = telebot.types.InlineKeyboardMarkup(row_width=1)

            if chat_mode == 'gemini':
                msg = '✅ Gemini 2.0 Flash '
            else:
                msg = 'Gemini 2.0 Flash'
            button_gemini_flash20 = telebot.types.InlineKeyboardButton(msg, callback_data='select_gemini_flash')

            if chat_mode == 'gemini25_flash':
                msg = '✅ Gemini 2.5 Flash'
            else:
                msg = 'Gemini 2.5 Flash'
            button_gemini_flash25 = telebot.types.InlineKeyboardButton(msg, callback_data='select_gemini25_flash')

            if chat_mode == 'gemini15':
                msg = '✅ Gemini 2.5 Pro'
            else:
                msg = 'Gemini 2.5 Pro'
            button_gemini_pro = telebot.types.InlineKeyboardButton(msg, callback_data='select_gemini_pro')

            if chat_mode == 'gemini-exp':
                msg = '✅ Gemini exp'
            else:
                msg = 'Gemini exp'
            button_gemini_exp = telebot.types.InlineKeyboardButton(msg, callback_data='select_gemini-exp')

            if chat_mode == 'gemma3_27b':
                msg = '✅ Gemma 3 27b'
            else:
                msg = 'Gemma 3 27b'
            button_gemini_pro15 = telebot.types.InlineKeyboardButton(msg, callback_data='select_gemma3_27b')

            if chat_mode == 'gemini-learn':
                msg = '✅ Gemini LearnLM 2.0 Flash'
            else:
                msg = 'Gemini LearnLM 2.0 Flash'
            button_gemini_learnlm = telebot.types.InlineKeyboardButton(msg, callback_data='select_gemini-learn')

            if chat_mode == 'gemini-lite':
                msg = '✅ Gemini 2.5 Flash Lite'
            else:
                msg = 'Gemini 2.5 Flash Lite'
            button_gemini_lite = telebot.types.InlineKeyboardButton(msg, callback_data='select_gemini-lite')

            if chat_mode == 'mistral':
                msg = '✅ Mistral'
            else:
                msg = 'Mistral'
            button_mistral = telebot.types.InlineKeyboardButton(msg, callback_data='select_mistral')

            if chat_mode == 'magistral':
                msg = '✅ Magistral'
            else:
                msg = 'Magistral'
            button_magistral = telebot.types.InlineKeyboardButton(msg, callback_data='select_magistral')

            if chat_mode == 'gpt-4o':
                msg = '✅ GPT-4o'
            else:
                msg = 'GPT-4o'
            button_gpt_4o = telebot.types.InlineKeyboardButton(msg, callback_data='select_gpt-4o')

            if chat_mode == 'gpt_41':
                msg = '✅ GPT 4.1'
            else:
                msg = 'GPT 4.1'
            button_gpt_41 = telebot.types.InlineKeyboardButton(msg, callback_data='select_gpt_41')

            if chat_mode == 'gpt_41_mini':
                msg = '✅ GPT 4.1 mini'
            else:
                msg = 'GPT 4.1 mini'
            button_gpt_41_mini = telebot.types.InlineKeyboardButton(msg, callback_data='select_gpt_41_mini')

            if chat_mode == 'deepseek_v3':
                msg = '✅ DeepSeek V3'
            else:
                msg = 'DeepSeek V3'
            button_deepseek_v3 = telebot.types.InlineKeyboardButton(msg, callback_data='select_deepseek_v3')

            if chat_mode == 'deepseek_r1':
                msg = '✅ DeepSeek R1'
            else:
                msg = 'DeepSeek R1'
            button_deepseek_r1 = telebot.types.InlineKeyboardButton(msg, callback_data='select_deepseek_r1')

            if chat_mode == 'cohere':
                msg = '✅ Command A'
            else:
                msg = 'Command A'
            button_cohere = telebot.types.InlineKeyboardButton(msg, callback_data='select_cohere')

            if chat_mode == 'openrouter':
                msg = '✅ OpenRouter'
            else:
                msg = 'OpenRouter'
            button_openrouter = telebot.types.InlineKeyboardButton(msg, callback_data='select_openrouter')

            if chat_mode == 'qwen3':
                msg = '✅ Qwen 3'
            else:
                msg = 'Qwen 3'
            button_qwen3 = telebot.types.InlineKeyboardButton(msg, callback_data='select_qwen3')


            msg = '==='
            button_filler1 = telebot.types.InlineKeyboardButton(msg, callback_data='switch_do_nothing')

            markup.row(button_gemini_flash25, button_mistral)
            markup.row(button_qwen3, button_cohere)
            markup.row(button_gpt_4o, button_gpt_41)
            markup.row(button_gemini_pro, button_gemini_flash20)
            markup.row(button_deepseek_v3, button_openrouter)
            # markup.row(button_gemini_lite)

            if voice_title in ('OpenAI', 'Gemini'):
                markup.row(button_filler1)

            button1 = telebot.types.InlineKeyboardButton(f"{tr('📢Голос:', lang)} {voice_title}", callback_data=voice)
            if my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                button2 = telebot.types.InlineKeyboardButton(tr('✅ 🗣️ Только голос', lang), callback_data='voice_only_mode_disable')
            else:
                button2 = telebot.types.InlineKeyboardButton(tr('☑️ 🗣️ Только голос', lang), callback_data='voice_only_mode_enable')
            markup.row(button1, button2)
            if voice_title == 'OpenAI':
                if 'alloy' in voice:
                    button1 = telebot.types.InlineKeyboardButton('📢 Alloy', callback_data='switch_do_nothing')
                else:
                    button1 = telebot.types.InlineKeyboardButton('Alloy', callback_data='switch_openai_alloy')
                if 'ash' in voice:
                    button2 = telebot.types.InlineKeyboardButton('📢 Ash', callback_data='switch_do_nothing')
                else:
                    button2 = telebot.types.InlineKeyboardButton('Ash', callback_data='switch_openai_ash')
                if 'ballad' in voice:
                    button3 = telebot.types.InlineKeyboardButton('📢 Ballad', callback_data='switch_do_nothing')
                else:
                    button3 = telebot.types.InlineKeyboardButton('Ballad', callback_data='switch_openai_ballad')
                if 'coral' in voice:
                    button4 = telebot.types.InlineKeyboardButton('📢 Coral', callback_data='switch_do_nothing')
                else:
                    button4 = telebot.types.InlineKeyboardButton('Coral', callback_data='switch_openai_coral')
                if 'echo' in voice:
                    button5 = telebot.types.InlineKeyboardButton('📢 Echo', callback_data='switch_do_nothing')
                else:
                    button5 = telebot.types.InlineKeyboardButton('Echo', callback_data='switch_openai_echo')
                if 'fable' in voice:
                    button6 = telebot.types.InlineKeyboardButton('📢 Fable', callback_data='switch_do_nothing')
                else:
                    button6 = telebot.types.InlineKeyboardButton('Fable', callback_data='switch_openai_fable')
                if 'onyx' in voice:
                    button7 = telebot.types.InlineKeyboardButton('📢 Onyx', callback_data='switch_do_nothing')
                else:
                    button7 = telebot.types.InlineKeyboardButton('Onyx', callback_data='switch_openai_onyx')
                if 'nova' in voice:
                    button8 = telebot.types.InlineKeyboardButton('📢 Nova', callback_data='switch_do_nothing')
                else:
                    button8 = telebot.types.InlineKeyboardButton('Nova', callback_data='switch_openai_nova')
                if 'sage' in voice:
                    button9 = telebot.types.InlineKeyboardButton('📢 Sage', callback_data='switch_do_nothing')
                else:
                    button9 = telebot.types.InlineKeyboardButton('Sage', callback_data='switch_openai_sage')
                if 'shimmer' in voice:
                    button10 = telebot.types.InlineKeyboardButton('📢 Shimmer', callback_data='switch_do_nothing')
                else:
                    button10 = telebot.types.InlineKeyboardButton('Shimmer', callback_data='switch_openai_shimmer')
                if 'verse' in voice:
                    button11 = telebot.types.InlineKeyboardButton('📢 Verse', callback_data='switch_do_nothing')
                else:
                    button11 = telebot.types.InlineKeyboardButton('Verse', callback_data='switch_openai_verse')

                markup.row(button1, button2, button3, button4)
                markup.row(button5, button6, button7, button8)
                markup.row(button9, button10, button11)


            if voice_title == 'Gemini':
                # Список для хранения кнопок текущей строки
                current_row_buttons = []

                for voice_name in sorted_possible_voices:
                    # Определяем текст кнопки: '📢 VoiceName' если выбран, иначе 'VoiceName'
                    # Условие 'voice_name in voice' работает, если 'voice' - это 'tts_gemini_VoiceName'
                    if voice_name in voice:
                        button_text = f'📢 {voice_name}'
                        callback_data_value = 'switch_do_nothing' # Ничего не делать, если уже выбран
                    else:
                        button_text = voice_name
                        callback_data_value = f'switch_gemini_{voice_name}' # Переключиться на этот голос

                    button = telebot.types.InlineKeyboardButton(button_text, callback_data=callback_data_value)
                    current_row_buttons.append(button)

                    # Если в текущей строке 3 кнопки, добавляем их в разметку и очищаем список для следующей строки
                    if len(current_row_buttons) == 3:
                        markup.row(*current_row_buttons) # * распаковывает список в отдельные аргументы
                        current_row_buttons = []

                # Добавляем оставшиеся кнопки, если их количество не кратно 3
                if current_row_buttons:
                    markup.row(*current_row_buttons)

            if voice_title in ('OpenAI', 'Gemini'):
                markup.row(button_filler1)

            if my_db.get_user_property(chat_id_full, 'disabled_kbd'):
                button1 = telebot.types.InlineKeyboardButton(tr('☑️Чат-кнопки', lang), callback_data='disable_chat_kbd')
            else:
                button1 = telebot.types.InlineKeyboardButton(tr('✅Чат-кнопки', lang), callback_data='enable_chat_kbd')

            other_notification = my_db.get_user_property(chat_id_full, 'action_style') or ''
            if not other_notification:
                button2 = telebot.types.InlineKeyboardButton(tr('☑️ 🔔 Other notification', lang), callback_data='switch_action_style')
            else:
                button2 = telebot.types.InlineKeyboardButton(tr('✅ 🔔 Other notification', lang), callback_data='switch_action_style')
            markup.row(button1, button2)


            if my_db.get_user_property(chat_id_full, 'transcribe_only'):
                button1 = telebot.types.InlineKeyboardButton(tr('✅ 📝 Voice to text mode', lang), callback_data='transcribe_only_chat_disable')
            else:
                button1 = telebot.types.InlineKeyboardButton(tr('☑️ 📝 Voice to text mode', lang), callback_data='transcribe_only_chat_enable')
            if my_db.get_user_property(chat_id_full, 'send_message'):
                button2 = telebot.types.InlineKeyboardButton(tr('✅ ↩️ Do not reply', lang), callback_data='send_message_chat_switch')
            else:
                button2 = telebot.types.InlineKeyboardButton(tr('☑️ ↩️ Do not reply', lang), callback_data='send_message_chat_switch')
            markup.row(button1, button2)

            if voice_title in ('OpenAI', 'Gemini'):
                markup.row(button_filler1)

            speech_to_text_engine = my_db.get_user_property(chat_id_full, 'speech_to_text_engine') or my_stt.DEFAULT_STT_ENGINE
            if speech_to_text_engine == 'auto':
                button0 = telebot.types.InlineKeyboardButton('🎤Auto', callback_data='switch_do_nothing')
            else:
                button0 = telebot.types.InlineKeyboardButton('Auto', callback_data='switch_speech_to_text_auto')
            if speech_to_text_engine == 'whisper':
                button1 = telebot.types.InlineKeyboardButton('🎤Whisper', callback_data='switch_do_nothing')
            else:
                button1 = telebot.types.InlineKeyboardButton('Whisper', callback_data='switch_speech_to_text_whisper')
            if speech_to_text_engine == 'gemini':
                button2 = telebot.types.InlineKeyboardButton('🎤Gemini', callback_data='switch_do_nothing')
            else:
                button2 = telebot.types.InlineKeyboardButton('Gemini', callback_data='switch_speech_to_text_gemini')
            if speech_to_text_engine == 'google':
                button3 = telebot.types.InlineKeyboardButton('🎤Google', callback_data='switch_do_nothing')
            else:
                button3 = telebot.types.InlineKeyboardButton('Google', callback_data='switch_speech_to_text_google')
            if speech_to_text_engine == 'assembly.ai':
                button4 = telebot.types.InlineKeyboardButton('🎤AssemblyAI', callback_data='switch_do_nothing')
            else:
                button4 = telebot.types.InlineKeyboardButton('AssemblyAI', callback_data='switch_speech_to_text_assembly.ai')
            if speech_to_text_engine == 'deepgram_nova3':
                button5 = telebot.types.InlineKeyboardButton('🎤Deepgram', callback_data='switch_do_nothing')
            else:
                button5 = telebot.types.InlineKeyboardButton('Deepgram', callback_data='switch_speech_to_text_deepgram_nova3')
            if speech_to_text_engine == 'voxtral':
                button6 = telebot.types.InlineKeyboardButton('🎤Voxtral', callback_data='switch_do_nothing')
            else:
                button6 = telebot.types.InlineKeyboardButton('Voxtral', callback_data='switch_speech_to_text_voxtral')
            markup.row(button0, button1, button2)
            markup.row(button6, button3, button4)
            markup.row(button5)

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
                    button = telebot.types.InlineKeyboardButton(tr('✅ 🤖 Автоответы в чате', lang), callback_data='admin_chat')
                else:
                    button = telebot.types.InlineKeyboardButton(tr('☑️ 🤖 Автоответы в чате', lang), callback_data='admin_chat')
                if not is_private:
                    markup.add(button)

            button = telebot.types.InlineKeyboardButton(tr('🙈Закрыть меню', lang), callback_data='erase_answer')
            markup.add(button)

            return markup
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
    try:
        message = call.message
        chat_id = message.chat.id
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        MSG_CONFIG = get_config_msg(chat_id_full, lang)

        if call.data == 'clear_history':
            # обработка нажатия кнопки "Стереть историю"
            reset_(message)
            bot.delete_message(message.chat.id, message.message_id)

        elif call.data == 'image_prompt_describe':
            COMMAND_MODE[chat_id_full] = ''
            image_prompt = tr(my_init.PROMPT_DESCRIBE, lang)
            process_image_stage_2(image_prompt, chat_id_full, lang, message)

        elif call.data == 'image_prompt_text':
            COMMAND_MODE[chat_id_full] = ''
            image_prompt = tr(my_init.PROMPT_COPY_TEXT, lang)
            process_image_stage_2(image_prompt, chat_id_full, lang, message)

        elif call.data == 'image_prompt_ocr':
            COMMAND_MODE[chat_id_full] = ''
            image_prompt = 'OCR'
            process_image_stage_2(image_prompt, chat_id_full, lang, message)

        elif call.data == 'image_prompt_text_tts':
            COMMAND_MODE[chat_id_full] = ''
            image_prompt = tr(my_init.PROMPT_COPY_TEXT_TTS, lang)
            process_image_stage_2(image_prompt, chat_id_full, lang, message)

        elif call.data == 'image_prompt_text_tr':
            COMMAND_MODE[chat_id_full] = ''
            image_prompt = tr(my_init.PROMPT_COPY_TEXT_TR, lang)
            process_image_stage_2(image_prompt, chat_id_full, lang, message)

        elif call.data == 'image_prompt_generate':
            COMMAND_MODE[chat_id_full] = ''
            image_prompt = tr(my_init.PROMPT_REPROMPT, lang) + \
                        '\n\n```prompt\n/img image generation prompt in english```\n\n'
            process_image_stage_2(image_prompt, chat_id_full, lang, message, temp = 1.5)

        elif call.data == 'image_prompt_solve':
            COMMAND_MODE[chat_id_full] = ''
            image_prompt = tr(my_init.PROMPT_SOLVE, lang) + ' ' + f'Answer in [{lang}] language.'
            process_image_stage_2(image_prompt, chat_id_full, lang, message, model = cfg.img2_txt_model_solve, temp = 0, timeout = 60)

        elif call.data == 'image_prompt_qrcode':
            COMMAND_MODE[chat_id_full] = ''
            if chat_id_full in UNCAPTIONED_IMAGES:
                img = UNCAPTIONED_IMAGES[chat_id_full][1]
                text = my_qrcode.get_text(img)
                if text:
                    bot_reply(message, text)
                    add_to_bots_mem(tr('user asked to get the text from an qrcode image', lang), text, chat_id_full)
                    return
            bot_reply_tr(message, 'No image found or text not found')

        elif call.data == 'image_prompt_repeat_last':
            COMMAND_MODE[chat_id_full] = ''
            process_image_stage_2(UNCAPTIONED_PROMPTS[chat_id_full], chat_id_full, lang, message)

        elif call.data.startswith('buy_stars_'):
            
            amount = int(call.data.split('_')[-1])
            if amount == 0:
                bot_reply_tr(message, 'Please enter the desired amount of stars you would like to donate', reply_markup=get_keyboard('command_mode', message))
                COMMAND_MODE[chat_id_full] = 'enter_start_amount'
                return
            prices = [telebot.types.LabeledPrice(label = "XTR", amount = amount)]
            try:
                bot.send_invoice(
                    call.message.chat.id,
                    title=tr('Donate stars amount:', lang) + ' ' + str(amount),
                    description = tr('Donate stars amount:', lang) + ' ' + str(amount),
                    invoice_payload="stars_donate_payload",
                    provider_token = "",  # Для XTR этот токен может быть пустым
                    currency = "XTR",
                    prices = prices,
                    reply_markup = get_keyboard(f'pay_stars_{amount}', message)
                )
            except Exception as error:
                my_log.log_donate(f'tb:callback_inline_thread1: {error}\n\n{call.message.chat.id} {amount}')
                bot_reply_tr(message, 'An unexpected error occurred during the payment process. Please try again later. If the problem persists, contact support.')

        elif call.data == 'continue_gpt':
            # обработка нажатия кнопки "Продолжай GPT"
            message.dont_check_topic = True
            message.next_button_pressed = True
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
                                text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config', message, 'admin'))
        elif call.data == 'erase_answer':
            # обработка нажатия кнопки "Стереть ответ"
            COMMAND_MODE[chat_id_full] = ''
            try:
                bot.delete_message(message.chat.id, message.message_id)
            except telebot.apihelper.ApiTelegramException as error:
                if "Bad Request: message can't be deleted for everyone" not in str(error):
                    traceback_error = traceback.format_exc()
                    my_log.log2(f'tb:callback_inline_thread2: {str(error)}\n\n{traceback_error}')
        elif call.data == 'tts':
            text = message.text or message.caption
            text = text.strip()
            if text:
                detected_lang = my_tts.detect_lang_carefully(text)
                if not detected_lang:
                    detected_lang = lang or "de"

                rewrited_text = my_gemini3.rewrite_text_for_tts(text, chat_id_full)
                message.text = f'/tts {detected_lang} {rewrited_text}'
                tts(message)
        elif call.data.startswith('select_lang-'):
            l = call.data[12:]
            message.text = f'/lang {l}'
            language(message)
        elif call.data in ('translate', 'translate_chat'):
            # реакция на клавиатуру, кнопка перевести текст
            with ShowAction(message, 'typing'):
                text = message.text if message.text else message.caption
                entities = message.entities if message.entities else message.caption_entities
                kbd = 'translate' if call.data == 'translate' else 'chat'
                text = my_log.restore_message_text(text, entities)
                translated = tr(text, lang, help = 'Please, provide a high-quality artistic translation, format the output using Markdown.', save_cache = False)
                html = utils.bot_markdown_to_html(translated)

                if translated and translated != text:
                    if message.text:
                        func = bot.edit_message_text
                    else:
                        func = bot.edit_message_caption
                    func(
                        chat_id=message.chat.id,
                        message_id=message.message_id,
                        text=html,
                        parse_mode='HTML',
                        disable_web_page_preview = True,
                        reply_markup=get_keyboard(kbd, message))

        elif call.data.startswith('search_pics_'):
            # Поиск картинок в дак дак гоу
            if chat_id_full not in GOOGLE_LOCKS:
                GOOGLE_LOCKS[chat_id_full] = threading.Lock()
            with GOOGLE_LOCKS[chat_id_full]:
                hash_ = call.data[12:]
                if hash_ in SEARCH_PICS:
                    with ShowAction(message, 'upload_photo'):
                        query = SEARCH_PICS[hash_]
                        images = []
                        if hasattr(cfg, 'TAVILY_KEYS') and len(cfg.TAVILY_KEYS) > 0:
                            images = my_tavily.search_images(query, user_id=chat_id_full)
                        if not images:
                            images = my_ddg.get_images(query)

                        medias = []

                        if images:
                            medias = [telebot.types.InputMediaPhoto(x[0], caption = x[1][:900] if x[1] is not None else '') for x in images]

                        if medias:
                            msgs_ids = send_media_group(
                                message,
                                message.chat.id,
                                medias,
                                reply_to_message_id=message.message_id,
                            )
                            log_message(msgs_ids)
                            return
                        bot_reply_tr(message, 'Не смог найти картинки по этому запросу.')
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
                    try:
                        m = send_document(
                            message,
                            message.chat.id,
                            document=buf,
                            message_thread_id=message.message_thread_id,
                            caption=fname,
                            visible_file_name = fname
                        )
                    except telebot.apihelper.ApiTelegramException as error:
                        if 'message thread not found' not in str(error):
                            raise error
                        m = send_document(
                            message,
                            message.chat.id,
                            document=buf,
                            caption=fname,
                            visible_file_name = fname
                        )
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
            COMMAND_MODE[chat_id_full] = ''

        elif call.data == 'select_mistral':
            my_db.set_user_property(chat_id_full, 'chat_mode', 'mistral')
        elif call.data == 'select_magistral':
            my_db.set_user_property(chat_id_full, 'chat_mode', 'magistral')
        elif call.data == 'select_gpt-4o':
            if chat_id_full in my_github.USER_KEYS:
                my_db.set_user_property(chat_id_full, 'chat_mode', 'gpt-4o')
            else:
                bot_reply_tr(message, 'Insert your github key first. /keys')
        elif call.data == 'select_gpt_41':
            if chat_id_full in my_github.USER_KEYS:
                my_db.set_user_property(chat_id_full, 'chat_mode', 'gpt_41')
            else:
                bot_reply_tr(message, 'Insert your github key first. /keys')
        elif call.data == 'select_gpt_41_mini':
            if chat_id_full in my_github.USER_KEYS:
                my_db.set_user_property(chat_id_full, 'chat_mode', 'gpt_41_mini')
            else:
                bot_reply_tr(message, 'Insert your github key first. /keys')
        elif call.data == 'select_deepseek_r1':
            my_db.set_user_property(chat_id_full, 'chat_mode', 'deepseek_r1')
        elif call.data == 'select_deepseek_v3':
            my_db.set_user_property(chat_id_full, 'chat_mode', 'deepseek_v3')
        elif call.data == 'select_cohere':
            my_db.set_user_property(chat_id_full, 'chat_mode', 'cohere')
        elif call.data == 'select_gemini_flash':
            my_db.set_user_property(chat_id_full, 'chat_mode', 'gemini')
        elif call.data == 'select_gemini25_flash':
            my_db.set_user_property(chat_id_full, 'chat_mode', 'gemini25_flash')
        elif call.data == 'select_gemini-lite':
            my_db.set_user_property(chat_id_full, 'chat_mode', 'gemini-lite')
        elif call.data == 'select_gemini-exp':
            my_db.set_user_property(chat_id_full, 'chat_mode', 'gemini-exp')
        elif call.data == 'select_gemini-learn':
            my_db.set_user_property(chat_id_full, 'chat_mode', 'gemini-learn')
        elif call.data == 'select_gemma3_27b':
            my_db.set_user_property(chat_id_full, 'chat_mode', 'gemma3_27b')
        elif call.data == 'select_gemini_pro':
            # SECONDS_IN_MONTH = 60 * 60 * 24 * 30
            # last_donate_time = my_db.get_user_property(chat_id_full, 'last_donate_time') or 0
            # donater = time.time() - last_donate_time < SECONDS_IN_MONTH
            # if (chat_id_full in my_gemini_general.USER_KEYS and my_gemini_general.USER_KEYS[chat_id_full]) or donater:
            #     my_db.set_user_property(chat_id_full, 'chat_mode', 'gemini15')
            # else:
            #     bot_reply_tr(message, 'Надо вставить свои ключи что бы использовать PRO модель. Команда /keys')
            my_db.set_user_property(chat_id_full, 'chat_mode', 'gemini15')
        elif call.data == 'select_openrouter':
            if chat_id_full in my_openrouter.KEYS:
                my_db.set_user_property(chat_id_full, 'chat_mode', 'openrouter')
            else:
                bot_reply_tr(message, 'Надо вставить свои ключи что бы использовать openrouter. Команда /openrouter')
        elif call.data == 'select_qwen3':
            my_db.set_user_property(chat_id_full, 'chat_mode', 'qwen3')

        elif call.data == 'general_reset':
            reset_(message, say = True, chat_id_full = chat_id_full)

        elif call.data == 'tts_female' and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'tts_gender', 'male')
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id,
                                text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config', message))

        elif call.data == 'tts_male' and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'tts_gender', 'google_female')
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id,
                                text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config', message))

        elif call.data == 'tts_google_female' and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'tts_gender', 'gemini_Achernar')
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id,
                                text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config', message))

        elif call.data.startswith('tts_gemini') and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'tts_gender', 'openai_alloy')
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id,
                                text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config', message))

        elif call.data.startswith('tts_openai') and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'tts_gender', 'female')
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id,
                                text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config', message))

        elif call.data.startswith('switch_openai_') and is_admin_member(call):
            voice = call.data.split('_')[-1]
            my_db.set_user_property(chat_id_full, 'tts_gender', f'openai_{voice}')
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id,
                                text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config', message))

        elif call.data.startswith('switch_gemini_') and is_admin_member(call):
            voice = call.data.split('_')[-1]
            my_db.set_user_property(chat_id_full, 'tts_gender', f'gemini_{voice}')
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id,
                                text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config', message))

        elif call.data.startswith('switch_do_nothing') and is_admin_member(call):
            pass

        elif call.data == 'send_message_chat_switch' and is_admin_member(call):
            send_message = my_db.get_user_property(chat_id_full, 'send_message') or False
            if send_message:
                my_db.set_user_property(chat_id_full, 'send_message', False)
            else:
                my_db.set_user_property(chat_id_full, 'send_message', True)
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                    text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config', message))

        elif call.data == 'switch_action_style':
            action_style = my_db.get_user_property(chat_id_full, 'action_style') or ''
            if not action_style:
                my_db.set_user_property(chat_id_full, 'action_style', 'message')
            else:
                my_db.set_user_property(chat_id_full, 'action_style', '')
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                    text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config', message))

        elif call.data == 'voice_only_mode_disable' and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'voice_only_mode', False)
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config', message))
        elif call.data == 'voice_only_mode_enable'  and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'voice_only_mode', True)
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config', message))
        elif call.data == 'transcribe_only_chat_disable' and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'transcribe_only', False)
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config', message))
        elif call.data == 'transcribe_only_chat_enable'  and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'transcribe_only', True)
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config', message))


        elif call.data.startswith('switch_speech_to_text_') and is_admin_member(call):
            speech_to_text_engine = call.data.split('_')[-1]
            if '_nova3' in call.data:
                speech_to_text_engine = call.data.split('_')[-2] + '_' + call.data.split('_')[-1]
            my_db.set_user_property(chat_id_full, 'speech_to_text_engine', speech_to_text_engine)
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id,
                                text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config', message))
        elif call.data == 'disable_chat_kbd' and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'disabled_kbd', False)
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config', message))
        elif call.data == 'enable_chat_kbd' and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'disabled_kbd', True)
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config', message))
        if call.data.startswith('select_'):
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                text = MSG_CONFIG, disable_web_page_preview = True, reply_markup=get_keyboard('config', message))
    except Exception as unexpected_error:
        if 'Bad Request: message is not modified' in str(unexpected_error) or \
           'Bad Request: message to be replied not found' in str(unexpected_error) or \
           'Bad Request: message to edit not found' in str(unexpected_error):
            return
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:callback_query_handler: {unexpected_error}\n\n{traceback_error}')


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
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    # Проверка на подписку/донат
    if not check_donate(message, chat_id_full, lang):
        return

    # --- ПРИОРИТЕТНАЯ ОБРАБОТКА ДЛЯ /transcribe ---
    if chat_id_full in COMMAND_MODE and COMMAND_MODE[chat_id_full] == 'transcribe':
        try:
            file_info, file_name = (None, 'unknown')
            if message.voice:
                file_info = bot.get_file(message.voice.file_id)
                file_name = 'telegram voice message'
            elif message.audio:
                file_info = bot.get_file(message.audio.file_id)
                file_name = message.audio.file_name
            elif message.video:
                file_info = bot.get_file(message.video.file_id)
                file_name = message.video.file_name
            elif message.video_note:
                file_info = bot.get_file(message.video_note.file_id)
            elif message.document:
                file_info = bot.get_file(message.document.file_id)
                file_name = message.document.file_name
            
            if file_info:
                downloaded_file = bot.download_file(file_info.file_path)
                transcribe_file(downloaded_file, file_name, message)
            else:
                 bot_reply_tr(message, 'Could not get file info for transcription.')
        except telebot.apihelper.ApiTelegramException as e:
            if 'file is too big' in str(e):
                bot_reply_tr(message, 'Too big file. Try /transcribe command. (Button - [Too big file])')
        except Exception as e:
            my_log.log2(f'tb:handle_voice:transcribe_mode_error: {e}')
            bot_reply_tr(message, 'Error during transcription.')
        finally:
            COMMAND_MODE[chat_id_full] = ''
        return


    # --- Механизм сбора группы сообщений ---
    if chat_id_full not in MESSAGE_QUEUE_AUDIO_GROUP:
        MESSAGE_QUEUE_AUDIO_GROUP[chat_id_full] = [message]
        last_state = MESSAGE_QUEUE_AUDIO_GROUP[chat_id_full]
        n = 10
        while n > 0:
            n -= 1
            time.sleep(0.1)
            new_state = MESSAGE_QUEUE_AUDIO_GROUP.get(chat_id_full, [])
            if len(last_state) != len(new_state):
                last_state = new_state
                n = 10
    else:
        MESSAGE_QUEUE_AUDIO_GROUP[chat_id_full].append(message)
        return

    messages_to_process = MESSAGE_QUEUE_AUDIO_GROUP.pop(chat_id_full, [])
    if not messages_to_process:
        return

    try:
        COMMAND_MODE[chat_id_full] = ''
        # --- ЕДИНАЯ ЛОГИКА ОБРАБОТКИ ДЛЯ ВСЕХ СЛУЧАЕВ ---

        # Если это одиночный файл без подписи в режиме "только транскрипция"
        is_transcribe_only = (
            my_db.get_user_property(chat_id_full, 'transcribe_only') and
            len(messages_to_process) == 1 and
            not messages_to_process[0].caption
        )
        is_voice_only_mode = my_db.get_user_property(chat_id_full, 'voice_only_mode') or 0

        with ShowAction(messages_to_process[0], 'typing'):
            # Вспомогательная функция для параллельной транскрипции
            def transcribe_in_parallel(msg_to_transcribe):
                try:
                    file_info, file_name = (None, 'unknown.ogg')
                    if msg_to_transcribe.voice:
                        file_info = bot.get_file(msg_to_transcribe.voice.file_id)
                        file_name = f'voice_message_{msg_to_transcribe.message_id}.ogg'
                    elif msg_to_transcribe.audio:
                        file_info = bot.get_file(msg_to_transcribe.audio.file_id)
                        file_name = msg_to_transcribe.audio.file_name or f'audio_{msg_to_transcribe.message_id}.mp3'
                    elif msg_to_transcribe.video:
                        file_info = bot.get_file(msg_to_transcribe.video.file_id)
                        file_name = msg_to_transcribe.video.file_name or f'video_{msg_to_transcribe.message_id}.mp4'
                    elif msg_to_transcribe.video_note:
                        file_info = bot.get_file(msg_to_transcribe.video_note.file_id)
                        file_name = f'video_note_{msg_to_transcribe.message_id}.mp4'
                    elif msg_to_transcribe.document:
                        file_info = bot.get_file(msg_to_transcribe.document.file_id)
                        file_name = msg_to_transcribe.document.file_name
                    if file_info:
                        downloaded_file = bot.download_file(file_info.file_path)
                        transcription = my_stt.stt(downloaded_file, lang, chat_id_full)
                        return {'filename': file_name, 'transcription': transcription or '[ERROR: Transcription failed]'}
                except Exception as e:
                    my_log.log2(f'tb:handle_voice:transcribe_in_parallel_error: {e}')
                return {'filename': 'error_file', 'transcription': '[ERROR: Processing failed]'}

            # Запускаем транскрипцию в потоках
            transcribed_data = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                futures = [executor.submit(transcribe_in_parallel, msg) for msg in messages_to_process]
                for future in concurrent.futures.as_completed(futures):
                    transcribed_data.append(future.result())


            # Показываем транскрипцию пользователю ---
            # Собираем весь распознанный текст в одно сообщение
            full_transcription_text = ""
            for item in transcribed_data:
                # Добавляем имя файла, если файлов больше одного
                if len(transcribed_data) > 1:
                    full_transcription_text += f"<b>{utils.html.escape(item['filename'])}:</b>\n"
                full_transcription_text += f"{utils.html.escape(item.get('transcription', ''))}\n\n"

            full_transcription_text = full_transcription_text.strip()

            # Отправляем, если есть что отправлять, и если это не режим "только голос"
            if full_transcription_text and not is_voice_only_mode:
                bot_reply(messages_to_process[0], full_transcription_text,
                          parse_mode='HTML',
                          reply_markup=get_keyboard('translate', messages_to_process[0]))

            # Если это был режим transcribe_only, на этом все
            if is_transcribe_only:
                return


            # Если это был режим transcribe_only, просто отправляем текст и выходим
            if is_transcribe_only:
                transcription = transcribed_data[0].get('transcription', '')
                if transcription and not transcription.startswith('[ERROR'):
                    bot_reply(messages_to_process[0], utils.bot_markdown_to_html(transcription),
                              parse_mode='HTML',
                              reply_markup=get_keyboard('translate', messages_to_process[0]))
                else:
                    bot_reply_tr(messages_to_process[0], 'Не удалось распознать текст')
                return

            # Собираем все подписи из группы
            combined_caption = "\n".join(
                [my_log.restore_message_text(msg.caption, msg.caption_entities) for msg in messages_to_process if msg.caption]
            ).strip()

            # Формируем XML-подобный промпт
            xml_prompt = "<audio_batch_analysis_request>\n"
            if combined_caption:
                xml_prompt += f"    <user_instruction>\n        {utils.html.escape(combined_caption)}\n    </user_instruction>\n"
            else:
                # Если подписей не было, но файл всего один, считаем, что пользователь просто хочет транскрипцию и ответ от ЛЛМ
                if len(messages_to_process) == 1:
                     xml_prompt += f"    <user_instruction>\n        {tr('User sent an audio file.', lang)}\n    </user_instruction>\n"
                else: # Если файлов много без подписи
                     xml_prompt += f"    <user_instruction>\n        {tr('User sent a batch of audio files.', lang)}\n    </user_instruction>\n"

            xml_prompt += "    <audio_files>\n"
            for item in transcribed_data:
                xml_prompt += "        <file>\n"
                xml_prompt += f"            <filename>{utils.html.escape(item['filename'])}</filename>\n"
                xml_prompt += f"            <transcription>\n                {utils.html.escape(item.get('transcription', ''))}\n            </transcription>\n"
                xml_prompt += "        </file>\n"
            xml_prompt += "    </audio_files>\n"
            xml_prompt += "</audio_batch_analysis_request>"

            # Создаем "фейковое" сообщение и передаем собранный запрос в основной обработчик
            fake_message = messages_to_process[0]
            fake_message.text = xml_prompt
            fake_message.entities = []

            echo_all(fake_message)

    except Exception as e:
        error_traceback = traceback.format_exc()
        my_log.log2(f'tb:handle_voice_main_logic: {e}\n{error_traceback}')
        # Гарантированно очищаем очередь, если что-то пошло не так
        if chat_id_full in MESSAGE_QUEUE_AUDIO_GROUP:
            del MESSAGE_QUEUE_AUDIO_GROUP[chat_id_full]


# @bot.message_handler(content_types = ['voice', 'video', 'video_note', 'audio'], func=authorized)
# @async_run
# def handle_voice(message: telebot.types.Message):
#     """Автоматическое распознавание текст из голосовых сообщений и аудио файлов"""
#     try:
#         is_private = message.chat.type == 'private'
#         chat_id_full = get_topic_id(message)
#         lang = get_lang(chat_id_full, message)

#         # рано
#         # COMMAND_MODE[chat_id_full] = ''

#         # проверка на подписку
#         if not check_donate(message, chat_id_full, lang):
#             return

#         supch = my_db.get_user_property(chat_id_full, 'superchat') or 0
#         if supch == 1:
#             is_private = True

#         message.caption = my_log.restore_message_text(message.caption, message.caption_entities)

#         # if check_blocks(get_topic_id(message)) and not is_private:
#         #     return
#         # определяем какое имя у бота в этом чате, на какое слово он отзывается
#         bot_name = my_db.get_user_property(chat_id_full, 'bot_name') or BOT_NAME_DEFAULT
#         if not is_private:
#             if not message.caption or not message.caption.startswith('?') or \
#                 not message.caption.startswith(f'@{_bot_name}') or \
#                     not message.caption.startswith(bot_name):
#                 return

#         if chat_id_full in VOICE_LOCKS:
#             lock = VOICE_LOCKS[chat_id_full]
#         else:
#             lock = threading.Lock()
#             VOICE_LOCKS[chat_id_full] = lock

#         with lock:
#             # Скачиваем аудиофайл во временный файл
#             file_name = 'unknown'
#             try:
#                 file_info = None
#                 if message.voice:
#                     file_info = bot.get_file(message.voice.file_id)
#                     file_name = 'telegram voice message'
#                 elif message.audio:
#                     file_info = bot.get_file(message.audio.file_id)
#                     file_name = message.audio.file_name
#                 elif message.video:
#                     file_info = bot.get_file(message.video.file_id)
#                     file_name = message.video.file_name
#                 elif message.video_note:
#                     file_info = bot.get_file(message.video_note.file_id)
#                 elif message.document:
#                     file_info = bot.get_file(message.document.file_id)
#                     file_name = message.document.file_name
#                 else:
#                     bot_reply_tr(message, 'Unknown message type')
#             except telebot.apihelper.ApiTelegramException as error:
#                 if 'file is too big' in str(error):
#                     bot_reply_tr(message, 'Too big file. Try /transcribe command. (Button - [Too big file])')
#                     return
#                 else:
#                     raise error

#             # Создание временного файла
#             with tempfile.NamedTemporaryFile(delete=True) as temp_file:
#                 file_path = temp_file.name + (utils.get_file_ext(file_info.file_path) or 'unknown')

#             downloaded_file = bot.download_file(file_info.file_path)


            # ## /transcribe ###################################################################################
            # # если отправили аудио файл для транскрибации в субтитры
            # if chat_id_full in COMMAND_MODE and COMMAND_MODE[chat_id_full] == 'transcribe':
            #     transcribe_file(downloaded_file, file_name, message)
            #     return
            # ## /transcribe ###################################################################################


#             COMMAND_MODE[chat_id_full] = ''


#             with open(file_path, 'wb') as new_file:
#                 new_file.write(downloaded_file)

#             # Распознаем текст из аудио
#             if my_db.get_user_property(chat_id_full, 'voice_only_mode'):
#                 action = 'record_audio'
#             else:
#                 action = 'typing'
#             with ShowAction(message, action):
#                 try:
#                     # prompt = tr('Распознай аудиозапись и исправь ошибки.', lang)
#                     prompt = ''
#                     text = my_stt.stt(file_path, lang, chat_id_full, prompt)
#                 except Exception as error_stt:
#                     my_log.log2(f'tb:handle_voice: {error_stt}')
#                     text = ''

#                 utils.remove_file(file_path)

#                 text = text.strip()
#                 # Отправляем распознанный текст
#                 if text:
#                     if my_db.get_user_property(chat_id_full, 'voice_only_mode'):
#                         # в этом режиме не показываем распознанный текст а просто отвечаем на него голосом
#                         pass
#                     else:
#                         bot_reply(message, utils.bot_markdown_to_html(text),
#                                 parse_mode='HTML',
#                                 reply_markup=get_keyboard('translate', message))
#                 else:
#                     if my_db.get_user_property(chat_id_full, 'voice_only_mode'):
#                         message.text = f'/tts {lang or "de"} ' + tr('Не удалось распознать текст', lang)
#                         tts(message)
#                     else:
#                         bot_reply_tr(message, 'Не удалось распознать текст')

#                 # и при любом раскладе отправляем текст в обработчик текстовых сообщений, возможно бот отреагирует на него если там есть кодовые слова
#                 if text:
#                     if not my_db.get_user_property(chat_id_full, 'transcribe_only'):
#                         # message.text = f'voice message: {text}'
#                         if message.caption:
#                             message.text = f'{message.caption}\n\n{tr("Audio message transcribed:", lang)}\n\n{text}'
#                         else:
#                             message.text = text
#                         echo_all(message)
#     except Exception as unknown:
#         traceback_error = traceback.format_exc()
#         my_log.log2(f'tb:handle_voice: {unknown}\n{traceback_error}')


@bot.message_handler(content_types = ['location',], func=authorized)
@async_run
def handle_location(message: telebot.types.Message):
    """Если юзер прислал геолокацию"""
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        COMMAND_MODE[chat_id_full] = ''

        # проверка на подписку
        if not check_donate(message, chat_id_full, lang):
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
        if not check_donate(message, chat_id_full, lang):
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


def proccess_image(chat_id_full: str, image: bytes, message: telebot.types.Message):
    '''The user sent an image without a caption.  Ask the user what to do with it,
    save the image, and display a keyboard with options.

    Args:
        chat_id_full: The full chat ID string.
        image: The image data as bytes.
        message: The Telegram message object.
    '''
    try:
        with UNCAPTIONED_IMAGES_LOCK:
            current_date = time.time()

            # Store the image and timestamp associated with the chat ID.
            UNCAPTIONED_IMAGES[chat_id_full] = (current_date, image)

            # Limit the storage to UNCAPTIONED_IMAGES_MAX uncaptioned images.
            if len(UNCAPTIONED_IMAGES) > UNCAPTIONED_IMAGES_MAX:
                # Sort the images by timestamp (oldest first).
                sorted_images = sorted(UNCAPTIONED_IMAGES.items(), key=lambda item: item[1][0])
                # Get the IDs of the oldest images to delete.
                user_ids_to_delete = [user_id for user_id, (date, image) in sorted_images[:len(UNCAPTIONED_IMAGES) - UNCAPTIONED_IMAGES_MAX]]
                # Delete the oldest images.
                for user_id in user_ids_to_delete:
                    try:
                        UNCAPTIONED_IMAGES.pop(user_id, None)
                    except KeyError:
                        pass

            # Set the command mode for the chat to 'image_prompt'.
            COMMAND_MODE[chat_id_full] = 'image_prompt'
            
            # Retrieve the last prompt used by the user for uncaptioned images, if any.
            user_prompt = ''
            if chat_id_full in UNCAPTIONED_PROMPTS:
                user_prompt = UNCAPTIONED_PROMPTS[chat_id_full]

            # Get the user's language.
            lang = get_lang(chat_id_full, message)
            # Create the message to send to the user.
            msg = tr('What would you like to do with this image?\n\nStart query with symbol ! to edit picture, Example: !change the color of the clothes to red', lang)
            msg += '\n\n' + image_info(image, lang)
            # Append the last prompt to the message, if available.
            if user_prompt:
                msg += '\n\n' + tr('Repeat my last request', lang) + ':\n\n' + utils.truncate_text(user_prompt)

            # Send the message to the user with the appropriate keyboard.
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
    timeout: int = 120):
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
            # Define default prompts.
            default_prompts = (
                tr(my_init.PROMPT_DESCRIBE, lang),
                tr(my_init.PROMPT_COPY_TEXT, lang),
                tr(my_init.PROMPT_COPY_TEXT_TTS, lang),
                tr(my_init.PROMPT_COPY_TEXT_TR, lang),
                tr(my_init.PROMPT_REPROMPT, lang),
                tr(my_init.PROMPT_SOLVE, lang),
                tr(my_init.PROMPT_QRCODE, lang),
            )

            # Save the user's prompt if it's not one of the default prompts.
            if not any(default_prompt in image_prompt for default_prompt in default_prompts):
                UNCAPTIONED_PROMPTS[chat_id_full] = image_prompt

            # Retrieve the image data if available.
            if chat_id_full in UNCAPTIONED_IMAGES:
                # Process the image based on the user's prompt.
                text = img2txt(
                    text = UNCAPTIONED_IMAGES[chat_id_full][1],
                    lang = lang,
                    chat_id_full = chat_id_full,
                    query = image_prompt,
                    model = model,
                    temperature = temp,
                    timeout = timeout
                )
                # Send the processed text to the user.
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
                else:
                    # Send an error message if the image processing fails.
                    bot_reply_tr(message, "I'm sorry, I wasn't able to process that image or understand your request.")
            else:
                # Send a message if the image is no longer available.
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
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        COMMAND_MODE[chat_id_full] = ''
        # проверка на подписку
        if not check_donate(message, chat_id_full, lang):
            return

        if chat_id_full in COMMAND_MODE and COMMAND_MODE[chat_id_full] != 'transcribe':
            COMMAND_MODE[chat_id_full] = ''

        is_private = message.chat.type == 'private'
        supch = my_db.get_user_property(chat_id_full, 'superchat') or 0
        if supch == 1:
            is_private = True

        chat_id = message.chat.id

        message.caption = my_log.restore_message_text(message.caption, message.caption_entities)

        # if check_blocks(chat_id_full) and not is_private:
        #     return
        bot_name = my_db.get_user_property(chat_id_full, 'bot_name') or BOT_NAME_DEFAULT
        if not is_private:
            if not message.caption or not message.caption.startswith('?') or \
                not message.caption.startswith(f'@{_bot_name}') or \
                    not message.caption.startswith(bot_name):
                return

        if chat_id_full in DOCUMENT_LOCKS:
            lock = DOCUMENT_LOCKS[chat_id_full]
        else:
            lock = threading.Lock()
            DOCUMENT_LOCKS[chat_id_full] = lock

        pandoc_support = my_init.PANDOC_SUPPORT_LIST

        if not message.document.mime_type:
            message.document.mime_type = 'application/xml'

        with lock:
            # if message.media_group_id
            # если прислали текстовый файл или pdf
            # то скачиваем и вытаскиваем из них текст и показываем краткое содержание
            if is_private :

                if message.document and message.document.mime_type.startswith('audio/') or \
                    message.document and message.document.mime_type.startswith('video/') or \
                    message.document.file_name.lower().endswith('.aac'):
                    handle_voice(message)
                    return

                if message.document and message.document.mime_type.startswith(('image/','animation/gif')) and message.document.mime_type not in ('image/svg+xml', 'image/vnd.djvu+multipage',):
                    handle_photo(message)
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

                    caption = message.caption or ''
                    caption = caption.strip()

                    # если подпись начинается на load то это запрос на загрузку сохраненной памяти
                    if caption == 'load':
                        # bytes to string
                        mem_dict = utils_llm.text_to_mem_dict(downloaded_file)
                        reset_(message, say = False)
                        for k, v in mem_dict.items():
                            add_to_bots_mem(k, v, chat_id_full)
                        bot_reply_tr(message, 'Память загружена из файла.')
                        return

                    # если подпись к документу начинается на !tr то это запрос на перевод
                    # и через пробел должен быть указан язык например !tr ru
                    if caption.startswith('!tr '):
                        target_lang = caption[4:].strip()
                        if target_lang:
                            bot_reply_tr(message, 'Translating it will take some time...')
                            new_fname = message.document.file_name if hasattr(message, 'document') else 'noname.txt'
                            new_data = my_doc_translate.translate_file_in_dialog(
                                downloaded_file,
                                lang,
                                target_lang,
                                fname = new_fname,
                                chat_id_full = chat_id_full)
                            if new_data:
                                new_fname2 = f'(translated by @{_bot_name}) {new_fname}'
                                m = send_document(
                                    message,
                                    message.chat.id,
                                    new_data,
                                    reply_to_message_id=message.message_id,
                                    message_thread_id=message.message_thread_id,
                                    caption=new_fname2,
                                    visible_file_name=new_fname2,
                                    disable_notification=True
                                )
                                log_message(m)
                                return
                            else:
                                bot_reply_tr(message, 'Translation failed.')
                                return


                    file_bytes = io.BytesIO(downloaded_file)
                    text = ''
                    if message.document.mime_type == 'application/pdf':
                        if message.caption and message.caption.startswith('!') and not message.caption.startswith('!tr '):
                            message.caption = message.caption[1:].strip()
                            caption = message.caption or ''
                            caption = caption.strip()
                            text = my_pdf.get_text(downloaded_file)
                        else:
                            LIMIT = cfg.LIMIT_PDF_OCR if hasattr(cfg, 'LIMIT_PDF_OCR') else 20
                            amount_of_pages = my_pdf.count_pages_in_pdf(downloaded_file) or 0
                            if amount_of_pages > LIMIT:
                                text = my_mistral.ocr_pdf(downloaded_file, timeout=300)
                            else:
                                text = my_pdf.get_text(downloaded_file)
                            if not text and amount_of_pages > LIMIT:
                                text = my_pdf.get_text(downloaded_file)
                            elif not text and amount_of_pages < LIMIT:
                                text = my_mistral.ocr_pdf(downloaded_file, timeout=300)
                    elif message.document.mime_type == 'application/zip':
                        text = my_zip.extract_and_concatenate(downloaded_file)
                    elif message.document.mime_type in pandoc_support:
                        ext = utils.get_file_ext(file_info.file_path)
                        text = my_pandoc.fb2_to_text(file_bytes.read(), ext)
                    elif message.document.mime_type == 'image/svg+xml' or message.document.file_name.lower().endswith('.psd'):
                        try:
                            if message.document.file_name.lower().endswith('.psd'):
                                image = my_psd.convert_psd_to_jpg(file_bytes.read())
                            elif message.document.mime_type == 'image/svg+xml':
                                image = my_svg.convert_svg_to_png_bytes(file_bytes.read())
                            else:
                                bot_reply_tr(message, f'Unknown image type {message.document.mime_type}')
                                return
                            image = utils.resize_image_dimention(image)
                            image = utils.resize_image(image)
                            #send converted image back
                            m = send_photo(
                                message,
                                message.chat.id,
                                image,
                                reply_to_message_id=message.message_id,
                                message_thread_id=message.message_thread_id,
                                caption=message.document.file_name + '.png',
                            )
                            log_message(m)
                            if not message.caption:
                                proccess_image(chat_id_full, image, message)
                                return
                            text = img2txt(image, lang, chat_id_full, message.caption)
                            if text:
                                text = utils.bot_markdown_to_html(text)
                                # text += tr("<b>Every time you ask a new question about the picture, you have to send the picture again.</b>", lang)
                                bot_reply(message, text, parse_mode='HTML',
                                                    reply_markup=get_keyboard('translate', message))
                            else:
                                bot_reply_tr(message, 'Sorry, I could not answer your question.')
                            return
                        except Exception as error:
                            my_log.log2(f'tb:handle_document:svg: {error}')
                            bot_reply_tr(message, 'Не удалось распознать изображение')
                            return
                    else:
                        text = utils.extract_text_from_bytes(downloaded_file)
                        if not text:
                            bot_reply_tr(message, 'Unknown type of file.')
                            my_log.log2(f'tb:handle_document: unknown file or empty text {message.document.mime_type} Name: {message.document.file_name} Size: {file_info.file_size}')
                            return

                    if text and text.strip():
                        # если это группа файлов, то прибавляем этот файл к группе
                        if message.media_group_id:

                            if (chat_id_full in FILE_GROUPS and FILE_GROUPS[chat_id_full] != message.media_group_id) or chat_id_full not in FILE_GROUPS:
                                # drop old text
                                prev_text = ''
                            else:
                                prev_text = my_db.get_user_property(chat_id_full, 'saved_file')
                            FILE_GROUPS[chat_id_full] = message.media_group_id

                            my_db.set_user_property(chat_id_full, 'saved_file_name', 'group of files')

                            text = f'{prev_text}\n\n<FILE>\n<NAME>\n{message.document.file_name if hasattr(message, "document") else "noname.txt"}\n</NAME>\n<TEXT>\n{text}\n</TEXT>\n</FILE>\n\n'
                            if len(text) > 1000000:
                                text = text[-1000000:]
                            my_db.set_user_property(chat_id_full, 'saved_file', text.strip())
                            bot_reply(message, tr('The file has been added to the group of files, use /ask to query it', lang) + ': ' + message.document.file_name if hasattr(message, 'document') else 'noname.txt')
                        else:
                            # если админ отправил .conf файл и внутри есть нужные поля для настройки ваиргарда то применить этот конфиг
                            if message.from_user.id in cfg.admins and message.document.file_name.endswith('.conf'):
                                if process_wg_config(text, message):
                                    bot_reply_tr(message, 'OK')
                                    return

                            summary = my_sum.summ_text(text, 'text', lang, caption)
                            my_db.set_user_property(chat_id_full, 'saved_file_name', message.document.file_name if hasattr(message, 'document') else 'noname.txt')
                            my_db.set_user_property(chat_id_full, 'saved_file', text)
                            summary_html = utils.bot_markdown_to_html(summary)
                            if summary_html.strip():
                                bot_reply(
                                    message,
                                    summary_html,
                                    parse_mode='HTML',
                                    disable_web_page_preview = True,
                                    reply_markup=get_keyboard('translate', message)
                                )
                            bot_reply_tr(message, 'Use /ask command to query or delete this file. Example:\n/ask generate a short version of part 1.\n? How many persons was invited.')

                            caption_ = tr("юзер попросил ответить по содержанию файла", lang)
                            if caption:
                                caption_ += ', ' + caption
                            add_to_bots_mem(
                                caption_,
                                f'{tr("бот посмотрел файл и ответил:", lang)} {summary}',
                                chat_id_full)
                    else:
                        bot_reply_tr(message, 'Не удалось получить никакого текста из документа.')
                    return
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:handle_document: {unknown}\n{traceback_error}')
        bot_reply_tr(message, 'Unknown error. It may be a password in the file.')
        return

    my_log.log2(f'tb:handle_document: Unknown type of file: {message.document.mime_type}')
    bot_reply_tr(message, 'Unknown type of file.')


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
        images = []

        with concurrent.futures.ThreadPoolExecutor() as executor:
            results = [executor.submit(download_image_from_message, message) for message in MESSAGES]
            for f in concurrent.futures.as_completed(results):
                images.append(f.result())

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
        COMMAND_MODE[chat_id_full] = ''
        current_list = my_gemini3.list_models(include_context=True)
        prev_list = KV_STORAGE.get('gemini_models', '')
        KV_STORAGE['gemini_models'] = current_list

        # Если предыдущий список отличается от текущего:
        if prev_list != current_list:
            # Преобразуем списки в наборы строк (каждая строка – модель)
            prev_models = set(prev_list.splitlines())
            current_models = current_list.splitlines()

            # Вычисляем новые модели
            new_models = {model for model in current_models if model not in prev_models}

            # Формируем итоговое сообщение, выделяя новые модели тегом <b>
            msg_lines = []
            for model in current_models:
                if model in new_models:
                    msg_lines.append(f"<b>{model}</b>")
                else:
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


@bot.message_handler(commands=['openrouter', 'bothub'], func=authorized_owner)
@async_run
def openrouter(message: telebot.types.Message):
    """Юзеры могут добавить свои ключи для openrouter.ai и пользоваться платным сервисом через моего бота"""
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)
        COMMAND_MODE[chat_id_full] = ''

        key = ''
        args = message.text.split(maxsplit=1)
        if len(args) > 1:
            key = args[1].strip()
        if chat_id_full not in my_openrouter.PARAMS:
            my_openrouter.PARAMS[chat_id_full] = my_openrouter.PARAMS_DEFAULT
        if key:
            if (key.startswith('sk-or-v1-') and len(key) == 73) or (len(key) == 212):
                my_openrouter.KEYS[chat_id_full] = key
                bot_reply_tr(message, 'Key added successfully!')
                if len(key) == 212: # bothub
                    my_db.set_user_property(chat_id_full, 'base_api_url', my_openrouter.BASE_URL_BH)
                elif (key.startswith('sk-or-v1-') and len(key) == 73):
                    my_db.set_user_property(chat_id_full, 'base_api_url', my_openrouter.BASE_URL)
                my_db.set_user_property(chat_id_full, 'chat_mode', 'openrouter')
                return
            elif key.startswith('https://'): # change base api url
                bot_reply_tr(message, 'Base API URL changed!')
                my_db.set_user_property(chat_id_full, 'base_api_url', key)
                return
            elif key.startswith('ghp_') and len(key) == 40: # GitHub PAT (https://github.com/settings/tokens)
                my_openrouter.KEYS[chat_id_full] = key
                my_db.set_user_property(chat_id_full, 'base_api_url', my_github.BASE_URL)
                bot_reply_tr(message, 'Key added successfully!')
                my_db.set_user_property(chat_id_full, 'chat_mode', 'openrouter')
                return
            else: # treat as a key
                my_openrouter.KEYS[chat_id_full] = key
                bot_reply_tr(message, 'Key added successfully!')
                my_db.set_user_property(chat_id_full, 'chat_mode', 'openrouter')
                return
        else:
            msg = tr('You can use your own key from https://openrouter.ai/keys or https://bothub.chat/profile/for-developers to access all AI supported.', lang)
            if chat_id_full in my_openrouter.KEYS and my_openrouter.KEYS[chat_id_full]:
                key = my_openrouter.KEYS[chat_id_full]
            if key:
                my_db.set_user_property(chat_id_full, 'chat_mode', 'openrouter')
                your_url = my_db.get_user_property(chat_id_full, 'base_api_url') or my_openrouter.BASE_URL
                msg = f'{tr("Your base api url:", lang)} [{your_url}]\n'
                msg += f'{tr("Your key:", lang)} [{key[:12]}...]\n'
                currency = my_db.get_user_property(chat_id_full, 'openrouter_currency') or '$'
                msg += f'{tr("Model price:", lang)} in {my_db.get_user_property(chat_id_full, "openrouter_in_price") or 0}{currency} / out {my_db.get_user_property(chat_id_full, "openrouter_out_price") or 0}{currency} /model_price'
            model, temperature, max_tokens, maxhistlines, maxhistchars = my_openrouter.PARAMS[chat_id_full]
            timeout_ = my_db.get_user_property(chat_id_full, 'openrouter_timeout') or my_openrouter.DEFAULT_TIMEOUT
            msg += '\n\n'+ tr('Current settings: ', lang) + f'\n[model {model}]\n[temp {temperature}]\n[max tokens {max_tokens}]\n[maxhistlines {maxhistlines}]\n[maxhistchars {maxhistchars}]\n[timeout {timeout_}]\n'
            msg += '\n\n' + tr('''/model <model> see available models at https://openrouter.ai/models or https://bothub.chat/models
/list_models - show all models scanned
/temp <temperature> - 0.1 ... 2.0
/maxtokens <max_tokens> - maximum response size, see model details
/maxhistlines <maxhistlines> - how many lines in history
/maxhistchars <maxhistchars> - how many chars in history
/set_timeout <timeout> - 2-1000 seconds

Usage: /openrouter <api key> or <api base url>
/openrouter https://openrouter.ai/api/v1 (ok)
https://bothub.chat/api/v2/openai/v1 (ok)
https://api.groq.com/openai/v1 (ok)
https://api.mistral.ai/v1 (ok)
https://api.x.ai/v1 (ok)
https://api.openai.com/v1 (ok)

/help2 for more info
''', lang)
            bot_reply(message, msg, disable_web_page_preview=True)
    except Exception as error:
        error_tr = traceback.format_exc()
        my_log.log2(f'tb:openrouter:{error}\n\n{error_tr}')


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
        unique_originals = my_db.get_unique_originals()
        
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
def users_keys_for_gemini(message: telebot.types.Message):
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

            if keys:
                added_flag = False
                with my_gemini_general.USER_KEYS_LOCK:
                    # my_gemini_general.USER_KEYS[chat_id_full] = keys
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

        msg = tr('Usage: /keys API KEYS space separated (gemini, groq)', lang) + '\n\n' + \
                 '<blockquote>/keys xxxxx yyyy zzz\n/keys xxxxx</blockquote>\n\n' + \
                 tr('This bot requires free API keys. At least first 2 keys are required.', lang) + '\n\n' + \
                 tr('Please <b>use only FREE keys</b>. Do not use paid accounts. If you have a paid account, please create a new one.', lang)+'\n\n'+\
                 '0️⃣ Free VPN: https://www.vpnjantit.com/\n\n' + \
                 '1️⃣ https://www.youtube.com/watch?v=6aj5a7qGcb4\nhttps://ai.google.dev/\nhttps://aistudio.google.com/apikey\n\n' + \
                 '2️⃣ https://github.com/theurs/tb1/tree/master/pics/groq\nhttps://console.groq.com/keys\n\n' + \
                 '\n\nhttps://console.mistral.ai/api-keys/\n\nhttps://dashboard.cohere.com/api-keys\n\nhttps://github.com/settings/tokens (classic, unlimited time, empty rights)'

        bot_reply(message, msg, disable_web_page_preview = True, parse_mode='HTML', reply_markup = get_keyboard('donate_stars', message))

        # показать юзеру его ключи
        if is_private:
            gemini_keys = my_gemini_general.USER_KEYS[chat_id_full] if chat_id_full in my_gemini_general.USER_KEYS else []
            mistral_keys = [my_mistral.USER_KEYS[chat_id_full],] if chat_id_full in my_mistral.USER_KEYS else []
            cohere_keys = [my_cohere.USER_KEYS[chat_id_full],] if chat_id_full in my_cohere.USER_KEYS else []
            github_keys = [my_github.USER_KEYS[chat_id_full],] if chat_id_full in my_github.USER_KEYS else []
            groq_keys = [my_groq.USER_KEYS[chat_id_full],] if chat_id_full in my_groq.USER_KEYS else []
            openrouter_keys = [my_openrouter.KEYS[chat_id_full],] if chat_id_full in my_openrouter.KEYS else []
            msg = tr('Your keys:', lang) + '\n\n'

            if openrouter_keys:
                msg += f'🔑️ Openrouter [...{openrouter_keys[0][-4:]}]\n'
            else:
                msg += '🔒 Openrouter\n'
            if gemini_keys:
                msg += f'🔑️ Gemini [...{gemini_keys[0][-4:]}]\n'
            else:
                msg += '🔒 Gemini\n'
            if groq_keys:
                msg += f'🔑️ Groq [...{groq_keys[0][-4:]}]\n'
            else:
                msg += '🔒 Groq\n'
            if mistral_keys:
                msg += f'🔑️ Mistral [...{mistral_keys[0][-4:]}]\n'
            else:
                msg += '🔒 Mistral\n'
            if cohere_keys:
                msg += f'🔑️ Cohere [...{cohere_keys[0][-4:]}]\n'
            else:
                msg += '🔒 Cohere\n'
            if github_keys:
                msg += f'🔑️ Github [...{github_keys[0][-4:]}]\n'
            else:
                msg += '🔒 Github\n'

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


def send_all_files_from_storage(message, chat_id_full):
    '''
    Отправляет файлы из хранилища для файлов в my_skills_storage.STORAGE если они там есть
    '''
    try: # если в ответе есть файлы, то отправляем его
        # Получаем данные из STORAGE.
        # Предполагается, что хранимый элемент - это плоский список
        #  [{type,filename,data},{}]
        items = my_skills_storage.STORAGE.get(chat_id_full)
        if items:
            for item in items:
                try:
                    _type, filename, data = item['type'], item['filename'], item['data']
                    if _type in ('excel file', 'docx file', 'text file'):
                        m = send_document(
                            message=message,
                            chat_id=message.chat.id,
                            document=data,
                            reply_to_message_id = message.message_id,
                            reply_markup=get_keyboard('hide', message),
                            caption=filename,
                            visible_file_name=filename,
                        )
                        log_message(m)
                        continue
                    elif _type in ('image/png file',):
                        m = send_photo(
                            message=message,
                            chat_id=message.chat.id,
                            photo=data,
                            reply_to_message_id = message.message_id,
                            reply_markup=get_keyboard('hide', message),
                            caption=filename,
                        )
                        log_message(m)
                        continue
                    elif _type in ('pdf file',):
                        m = send_document(
                            message=message,
                            chat_id=message.chat.id,
                            document=data,
                            reply_to_message_id = message.message_id,
                            reply_markup=get_keyboard('hide', message),
                            caption=filename,
                            visible_file_name=filename,
                        )
                        log_message(m)
                        continue
                except Exception as individual_error:
                    traceback_error = traceback.format_exc()
                    # Логируем ошибку для этого конкретного элемента, но продолжаем цикл
                    my_log.log2(f'tb:send_all_files_from_storage:1: for chat {chat_id_full}, item {i}: {individual_error}\n\n{traceback_error}')
                    continue

            # После попытки отправки всех потенциальных файлов, удаляем запись из STORAGE
            my_skills_storage.STORAGE.pop(chat_id_full)

    except Exception as general_error:
        # Этот блок ловит ошибки, не связанные с отправкой конкретного элемента (например, проблемы с получением данных из STORAGE или неверный формат)
        my_skills_storage.STORAGE.pop(chat_id_full) # Удаляем запись в случае общей ошибки
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:send_all_files_from_storage:2: for chat {chat_id_full}: {general_error}\n\n{traceback_error}')


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
        if not check_donate(message, chat_id_full, lang):
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
        if not check_donate(message, chat_id_full, lang):
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
@bot.message_handler(commands=['style', 'role'], func=authorized_owner)
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
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

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
        _mode = message.text.split(maxsplit=3)[2].strip()

        my_db.set_user_property(_user, 'chat_mode', _mode)

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
        elif mode == 'qwen3':
            my_openrouter_free.force(chat_id_full, text)
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
        elif mode == 'qwen3':
            my_openrouter_free.undo(chat_id_full)
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
            elif mode == 'qwen3':
                my_openrouter_free.reset(chat_id_full)
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


@bot.message_handler(commands=['style2'], func=authorized_admin)
@async_run
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
        if mode == 'qwen3':
            prompt = my_openrouter_free.get_mem_as_string(chat_id_full, md = True) or ''
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

        if 'gemini' in my_db.get_user_property(chat_id_full, 'chat_mode') or 'gemma' in my_db.get_user_property(chat_id_full, 'chat_mode'):
            if 'gemma' in my_db.get_user_property(chat_id_full, 'chat_mode'):
                prompt = my_db.get_user_property(chat_id_full, 'chat_mode') + '\n\n'
            else:
                prompt = 'Gemini ' + my_db.get_user_property(chat_id_full, 'chat_mode') + '\n\n'
            prompt += my_gemini3.get_mem_as_string(chat_id_full, model=my_db.get_user_property(chat_id_full, 'chat_mode')) or tr('Empty', lang)
        elif my_db.get_user_property(chat_id_full, 'chat_mode') == 'openrouter':
            prompt = 'Openrouter\n\n'
            prompt += my_openrouter.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        elif my_db.get_user_property(chat_id_full, 'chat_mode') == 'qwen3':
            prompt = 'Qwen 3 235b a22b\n\n'
            prompt += my_openrouter_free.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        elif my_db.get_user_property(chat_id_full, 'chat_mode') == 'mistral':
            prompt = 'Mistral Large\n\n'
            prompt += my_mistral.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        elif my_db.get_user_property(chat_id_full, 'chat_mode') == 'magistral':
            prompt = 'Magistral Medium\n\n'
            prompt += my_mistral.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        elif my_db.get_user_property(chat_id_full, 'chat_mode') == 'gpt-4o':
            prompt = 'GPT-4o\n\n'
            prompt += my_github.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        elif my_db.get_user_property(chat_id_full, 'chat_mode') == 'gpt_41':
            prompt = 'GPT 4.1\n\n'
            prompt += my_github.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        elif my_db.get_user_property(chat_id_full, 'chat_mode') == 'gpt_41_mini':
            prompt = 'GPT 4.1 mini\n\n'
            prompt += my_github.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        elif my_db.get_user_property(chat_id_full, 'chat_mode') == 'deepseek_r1':
            prompt = 'DeepSeek R1\n\n'
            prompt += my_github.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        elif my_db.get_user_property(chat_id_full, 'chat_mode') == 'deepseek_v3':
            prompt = 'DeepSeek V3\n\n'
            prompt += my_github.get_mem_as_string(chat_id_full) or tr('Empty', lang)
        elif my_db.get_user_property(chat_id_full, 'chat_mode') == 'cohere':
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
        elif target_chat_mode == 'qwen3':
            target_mem_string = my_openrouter_free.get_mem_as_string(target_user_id_str)
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
        role = my_db.get_user_property(chat_id_full, 'role')

        COMMAND_MODE[chat_id_full] = ''
        # проверка на подписку
        if not check_donate(message, chat_id_full, lang):
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
    """Generates an image using the Gemini 2.0 Flash Experimental model.
    /flux <[1|2|3|4]> <prompt> - up to 4 pictures per request, default 1
    """
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        COMMAND_MODE[chat_id_full] = ''

        # Check for donations
        if not check_donate(message, chat_id_full, lang):
            return

        # Lock to prevent concurrent requests
        if chat_id_full in IMG_GEN_LOCKS_GEM_IMG:
            lock = IMG_GEN_LOCKS_GEM_IMG[chat_id_full]
        else:
            lock = threading.Lock()
            IMG_GEN_LOCKS_GEM_IMG[chat_id_full] = lock

        # не ставить запросы от одного юзера в очередь
        if lock.locked():
            if hasattr(cfg, 'ALLOW_PASS_NSFW_FILTER') and utils.extract_user_id(chat_id_full) in cfg.ALLOW_PASS_NSFW_FILTER:
                pass
            else:
                return

        help_text = f"""/gem <[1|2|3|4]> <prompt>

{tr('Generate 1-4 images with the Gemini 2.0 Flash Experimental model', lang)}
"""

        with lock:
            # Get prompt
            parts = message.text.split(maxsplit=2)  # Split into command, model number, and prompt
            if len(parts) < 2:
                bot_reply(message, help_text)
                COMMAND_MODE[chat_id_full] = 'gem'
                return

            try:
                if len(parts) == 2:
                    num = 1
                    prompt = parts[1].strip()
                else:
                    num = parts[1].strip()
                    prompt = parts[2].strip()
            except IndexError:
                bot_reply_tr(message, help_text)
                return

            if not prompt or prompt in ('1', '2', '3', '4'):
                bot_reply_tr(message, help_text)
                return

            # Parse model choice, default to 1 if not specified or invalid
            if num in ('1', '2', '3', '4'):
                num = int(num)
            else:
                if num not in (1, 2, 3, 4):
                    prompt = f'{num} {prompt}'
                    num = 1  # Default to model 1

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

                    images = my_genimg.gemini_flash(reprompt, num = num, user_id=chat_id_full)
                    if images:
                        caption_model = my_gemini_genimg.MODEL
                    else:
                        bot_reply_tr(message, "Generation failed.")
                        return

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

                        add_to_bots_mem(message.text, f'The bot successfully generated images on the external service <service>Gemini 2.0 Flash Experimental</service> based on the request <prompt>{prompt}</prompt>', chat_id_full)
                    else:
                        bot_reply_tr(message, tr("Image generation failed. (No images generated.)\n\nA prompt that is too long can cause this error. You can try using '!' before the prompt to fix it. In this case, the prompt must be in English only.", lang))

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
    """Generates an image using the Flux Nebius model.
    /flux [1|2|3] <prompt>
    1 - модель "black-forest-labs/flux-dev" (указывается как третий параметр в функции flux_nebius_gen1)
    2 - black-forest-labs/flux-schnell
    3 - stability-ai/sdxl
    """
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        COMMAND_MODE[chat_id_full] = ''

        # Check for donations
        if not check_donate(message, chat_id_full, lang):
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

        help_text = f"""/flux [1|2|3] <prompt>

1 - black-forest-labs/flux-dev
/flux 1 {tr('cat in space', lang)}

2 - black-forest-labs/flux-schnell
/flux 2 {tr('cat in space', lang)}

3 - stability-ai/sdxl
/flux 3 {tr('cat in space', lang)}

/flux {tr('cat in space', lang)} - {tr('same as /flux 1', lang)}
"""

        with lock:
            # Get prompt
            parts = message.text.split(maxsplit=2)  # Split into command, model number, and prompt
            if len(parts) < 2:
                bot_reply(message, help_text)
                return

            try:
                if len(parts) > 2:
                    model_choice = parts[1].strip()
                    prompt = parts[2].strip()
                else:
                    model_choice = '1'
                    prompt = parts[1].strip()
            except IndexError:
                prompt = ''
                bot_reply_tr(message, "/flux [1|2|3] <prompt>\n\n" + tr("Generate images using the Flux Nebius model.", lang))
                return

            if not prompt or prompt in ('1', '2', '3'):
                bot_reply_tr(message, "/flux [1|2|3] <prompt>\n\n" + tr("Generate images using the Flux Nebius model.", lang))
                return

            # Parse model choice, default to 1 if not specified or invalid
            if model_choice in ('1', '2', '3'):
                model_index = int(model_choice)
            else:
                model_index = 1  # Default to model 1
                prompt = f'{model_choice} {prompt}'

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

                    # Select the appropriate model based on model_index
                    if model_index == 1:
                        images = my_genimg.flux_nebius_gen1(reprompt, negative_prompt, model = 'black-forest-labs/flux-dev') # Explicitly pass the model name
                        if images:
                            my_db.add_msg(chat_id_full, 'img Flux-dev Nebius')
                        caption_model = 'black-forest-labs/flux-dev'
                    elif model_index == 2:
                        images = my_genimg.flux_nebius_gen1(reprompt, negative_prompt, model = 'black-forest-labs/flux-schnell')
                        if images:
                            my_db.add_msg(chat_id_full, 'img Flux-schnell Nebius')
                        caption_model = 'black-forest-labs/flux-schnell'
                    elif model_index == 3:
                        images = my_genimg.flux_nebius_gen1(reprompt, negative_prompt, model = 'stability-ai/sdxl')
                        if images:
                            my_db.add_msg(chat_id_full, 'img SDXL Nebius')
                        caption_model = 'stability-ai/sdxl'
                    else:
                        bot_reply_tr(message, "Invalid model number. Use 1, 2 or 3.")
                        return


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


@bot.message_handler(commands=['image','image:','Image:','IMAGE:','img', 'IMG', 'Image', 'Img', 'i', 'I', 'imagine', 'imagine:', 'Imagine', 'Imagine:', 'generate', 'gen', 'Generate', 'Gen', 'art', 'Art', 'picture', 'pic', 'Picture', 'Pic'], func=authorized)
@async_run
def image_gen(message: telebot.types.Message):
    """Generates a picture from a description"""
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)


        if message.text.lower().startswith('/i'):
            if chat_id_full in IMG_MODE_FLAG:
                del IMG_MODE_FLAG[chat_id_full]


        # # в группе рисовать можно только тем у кого есть все ключи или подписка или админы
        # if message.chat.id < 0:
        #     chat_id_full_from = f'[{message.from_user.id}] [0]'
        #     user_id = message.from_user.id
        #     have_keys = (chat_id_full_from in my_gemini_general.USER_KEYS and chat_id_full_from in my_groq.USER_KEYS) or \
        #             user_id in cfg.admins or \
        #             (my_db.get_user_property(chat_id_full_from, 'telegram_stars') or 0) >= 50
        #     if not have_keys:
        #         return


        # не использовать бинг для рисования запрещенки, он за это банит
        NSFW_FLAG = False
        if message.text.endswith('NSFW'):
            NSFW_FLAG = True
            message.text = message.text[:-4]

        # забаненный в бинге юзер
        if my_db.get_user_property(chat_id_full, 'blocked_bing'):
            NSFW_FLAG = True

        # if NSFW_FLAG:
        #     bot_reply(message, tr('Images was blocked.', lang) + ' ' + 'https://www.google.com/search?q=nsfw', disable_web_page_preview=True)
        #     return

        show_timeout = 5 # как долго показывать активность

        # рисовать только бингом, команда /bing
        BING_FLAG = 0
        if message.text.endswith('[{(BING)}]'):
            message.text = message.text[:-10]
            BING_FLAG = 1


        # 10х и 20х отключены пока
        # BING_FLAG = 0

        if chat_id_full in IMG_GEN_LOCKS:
            lock = IMG_GEN_LOCKS[chat_id_full]
        else:
            # lock = threading.Lock()
            lock = NoLock() # временно отключаем блокировку, юзеры смогут делать несколько запросов одновременно
            IMG_GEN_LOCKS[chat_id_full] = lock

        COMMAND_MODE[chat_id_full] = ''
        # проверка на подписку
        if not check_donate(message, chat_id_full, lang):
            return



        # не ставить в очередь рисование, кроме белого списка
        # if lock.locked():
        #     if hasattr(cfg, 'ALLOW_PASS_NSFW_FILTER') and utils.extract_user_id(chat_id_full) in cfg.ALLOW_PASS_NSFW_FILTER:
        #         pass
        #     else:
        #         return



        # # не ставить в очередь рисование x10 x20 bing
        # if lock.locked() and BING_FLAG > 1:
        #     return

        with lock:

            # замедление для юзеров из черного списка
            # случайное время от 1 до 4 минут
            # пауза до включения отображения активности что бы не дрочить сервер телеграма зря
            if hasattr(cfg, 'SLOW_MODE_BING') and utils.extract_user_id(chat_id_full) in cfg.SLOW_MODE_BING:
                if my_db.count_imaged_per24h(chat_id_full) > 500:
                    time.sleep(random.randint(60, 240))

            draw_text = tr('draw', lang)
            if lang == 'ru':
                draw_text = 'нарисуй'
            if lang == 'en':
                draw_text = 'draw'
            help = f"""/image {tr('Text description of the picture, what to draw.', lang)}

/image {tr('космический корабль в полете', lang)}
/img {tr('средневековый замок с рвом и мостом', lang)}
/i {tr('подводный мир с рыбами и кораллами', lang)}
<b>{draw_text}</b> {tr('красивый сад с цветами и фонтаном', lang)}

{tr('Use /bing command for Bing only.', lang)}

{tr('Use /flux command for black-forest-labs/flux-dev only.', lang)}

{tr('Use /gem command for Gemini only.', lang)}

{tr('Write what to draw, what it looks like.', lang)}
"""
            message.text = my_log.restore_message_text(message.text, message.entities)
            prompt = message.text.split(maxsplit = 1)

            if len(prompt) > 1:
                prompt = prompt[1].strip()
                COMMAND_MODE[chat_id_full] = ''

                if prompt == tr('Продолжай', lang):
                    return

                if prompt:
                    if chat_id_full in IMG_MODE_FLAG:
                        if IMG_MODE_FLAG[chat_id_full] == 'bing':
                            BING_FLAG = 1

                # get chat history for content
                conversation_history = my_gemini3.get_mem_as_string(chat_id_full) or ''

                conversation_history = conversation_history[-8000:]
                # как то он совсем плохо стал работать с историей, отключил пока что
                conversation_history = ''

                with ShowAction(message, 'upload_photo', max_timeout = show_timeout):
                    moderation_flag = False

                    if NSFW_FLAG:
                        images = my_genimg.gen_images(prompt, moderation_flag, chat_id_full, conversation_history, use_bing = False)
                    else:
                        if BING_FLAG:
                            bf = BING_FAILS[chat_id_full] if chat_id_full in BING_FAILS else [0, 0]
                            if bf[0] >= 5:
                                if time.time() - bf[1] > 5 * 60:
                                    bf = [0, 0]
                            if bf[0] < 5:
                                images = my_genimg.gen_images_bing_only(prompt, chat_id_full, conversation_history, BING_FLAG)
                                if not images:
                                    bf[0] += 1
                                    bf[1] = time.time()
                            else:
                                images = []
                                time.sleep(random.randint(5,10))
                            if not images:
                                bot_reply_tr(message, 'Bing не смог ничего нарисовать.')
                            BING_FAILS[chat_id_full] = bf
                        else:
                            images = my_genimg.gen_images(prompt, moderation_flag, chat_id_full, conversation_history, use_bing = True)

                    # try flux if no results
                    if not images and hasattr(cfg, 'USE_FLUX_IF_EMPTY_IMAGES') and cfg.USE_FLUX_IF_EMPTY_IMAGES:
                        prompt = prompt.strip()
                        # remove trailing !
                        prompt = re.sub(r'^!+', '', prompt).strip()
                        message.text = f'/flux {prompt}'
                        image_flux_gen(message)
                        return

                    medias = []
                    has_good_images = False
                    for x in images:
                        if isinstance(x, bytes):
                            has_good_images = True
                            break
                    for i in images:
                        if isinstance(i, str):
                            if i.startswith('moderation') and not has_good_images:
                                bot_reply_tr(message, 'Ваш запрос содержит потенциально неприемлемый контент.')
                                return
                            elif 'error1_Bad images' in i and not has_good_images:
                                bot_reply_tr(message, 'Ваш запрос содержит неприемлемый контент.')
                                return
                            if not has_good_images and not i.startswith('https://'):
                                bot_reply_tr(message, i)
                                return
                        d = None
                        bot_addr = f'https://t.me/{_bot_name}'
                        caption_ = re.sub(r"(\s)\1+", r"\1\1", prompt)[:900]
                        # caption_ = prompt[:900]
                        if isinstance(i, str):
                            d = utils.download_image_as_bytes(i)
                            if len(d) < 2000: # placeholder?
                                continue
                            caption_ = f'{bot_addr} bing.com\n\n' + caption_
                            my_db.add_msg(chat_id_full, 'img ' + 'bing.com')
                        elif isinstance(i, bytes):
                            if utils.fast_hash(i) in my_genimg.WHO_AUTOR:
                                nn_ = '\n\n'
                                author = my_genimg.WHO_AUTOR[utils.fast_hash(i)]
                                caption_ = f"{bot_addr} {author}{nn_}{caption_}"
                                my_db.add_msg(chat_id_full, 'img ' + author)
                                del my_genimg.WHO_AUTOR[utils.fast_hash(i)]
                            else:
                                caption_ = f'{bot_addr} error'
                            d = i
                        if d:
                            try:
                                medias.append(telebot.types.InputMediaPhoto(d, caption = caption_[:900]))
                            except Exception as add_media_error:
                                error_traceback = traceback.format_exc()
                                my_log.log2(f'tb:image:add_media_bytes: {add_media_error}\n\n{error_traceback}')

                    if len(medias) > 0:
                        # делим картинки на группы до 10шт в группе, телеграм не пропускает больше за 1 раз
                        chunk_size = 10
                        chunks = [medias[i:i + chunk_size] for i in range(0, len(medias), chunk_size)]

                        send_images_to_user(chunks, message, chat_id_full, medias, images)

                        if pics_group and not NSFW_FLAG:
                            send_images_to_pic_group(chunks, message, chat_id_full, prompt)

                        add_to_bots_mem(message.text, f'The bot successfully generated images on the external services <service>bing, fusion, flux, nebius, gemini</service> based on the request <prompt>{prompt}</prompt>', chat_id_full)

                    else:
                        bot_reply_tr(message, 'Could not draw anything.')

                        my_log.log_echo(message, '[image gen error] ')

                        add_to_bots_mem(message.text, 'FAIL', chat_id_full)

            else:
                COMMAND_MODE[chat_id_full] = 'image'
                bot_reply(message, help, parse_mode = 'HTML', reply_markup=get_keyboard('command_mode', message))
    except Exception as error_unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:image:send: {error_unknown}\n{traceback_error}')


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
        args = message.text.split(maxsplit=2)

        try:
            uid = int(args[1])
            text = args[2]
            bot.send_message(uid, text, message_thread_id = 0, disable_notification=True)
            bot_reply_tr(message, 'Message sent.')
            my_log.log_echo(message, f'Admin sent message to user {uid}: {text}')
            return
        except:
            pass
        bot_reply_tr(message, 'Usage: /msg userid_as_int text to send from admin to user')
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:message_to_user: {unknown}\n{traceback_error}')


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
                result = my_gemini.ai(q[:my_gemini_general.MAX_SUM_REQUEST], temperature=temperature, tokens_limit=8000, model = cfg.gemini25_flash_model, system=role)
                if not result:
                    result = my_gemini.ai(q[:my_gemini_general.MAX_SUM_REQUEST], temperature=temperature, tokens_limit=8000, model = cfg.gemini_flash_model, system=role)
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
        if not check_donate(message, chat_id_full, lang):
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
        if not check_donate(message, chat_id_full, lang):
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
        if chat_id_full not in NEW_KEYBOARD:
            NEW_KEYBOARD[chat_id_full] = True

        # no language in user info, show language selector
        if not user_have_lang:
            language(message)

        # reset_(message, say = False)
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
            my_db.delete_user_property(chat_id_full, 'openrouter_timeout') # added to delete

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


@bot.message_handler(commands=['id'], func = authorized_log)
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

        try:
            if is_admin:
                arg = message.text.split(maxsplit=1)[1].strip()
                if arg:
                    if '[' not in arg:
                        arg = f'[{arg}] [0]'
                    chat_id_full = arg
        except IndexError:
            pass

        user_id = message.from_user.id
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
            'qwen3': my_openrouter_free.DEFAULT_MODEL,
            'bothub': 'bothub.chat',
        }
        if user_model == 'openrouter':
            if 'bothub' in (my_db.get_user_property(chat_id_full, 'base_api_url') or ''):
                user_model = 'bothub'
        if user_model in models.keys():
            user_model = f'<b>{models[user_model]}</b>'

        telegram_stars = my_db.get_user_property(chat_id_full, 'telegram_stars') or 0

        total_msgs = my_db.get_total_msg_user(chat_id_full)
        # totals_pics = my_db.get_user_property(chat_id_full, 'image_generated_counter') or 0
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

        last_donate_time = my_db.get_user_property(chat_id_full, 'last_donate_time') or 0
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

        if last_donate_time:
            msg += f'\n\n{tr("Подписка:", lang)} {utils.format_timestamp(last_donate_time)}'

        if my_db.get_user_property(chat_id_full, 'chat_mode') == 'openrouter':
            msg += f' <b>{open_router_model}</b>'

        tstarsmsg = tr('Telegram stars:', lang, help = 'Telegram Stars is a new feature that allows users to buy and spend Stars, a new digital currency, on digital goods and services within the Telegram ecosystem, like ebooks, online courses, or items in Telegram games.')
        if telegram_stars:
            msg += f'\n\n🌟 {tstarsmsg} {telegram_stars} /stars'
        else:
            msg += f'\n\n⭐️ {tstarsmsg} {telegram_stars} /stars'

        gemini_keys = my_gemini_general.USER_KEYS[chat_id_full] if chat_id_full in my_gemini_general.USER_KEYS else []
        groq_keys = [my_groq.USER_KEYS[chat_id_full],] if chat_id_full in my_groq.USER_KEYS else []
        mistral_keys = [my_mistral.USER_KEYS[chat_id_full],] if chat_id_full in my_mistral.USER_KEYS else []
        cohere_keys = [my_cohere.USER_KEYS[chat_id_full],] if chat_id_full in my_cohere.USER_KEYS else []
        github_keys = [my_github.USER_KEYS[chat_id_full],] if chat_id_full in my_github.USER_KEYS else []
        openrouter_keys = [my_openrouter.KEYS[chat_id_full],] if chat_id_full in my_openrouter.KEYS else []

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
        if mistral_keys:
            msg += '🔑️ Mistral\n'
        else:
            msg += '🔒 Mistral\n'
        if cohere_keys:
            msg += '🔑️ Cohere\n'
        else:
            msg += '🔒 Cohere\n'
        if github_keys:
            msg += '🔑️ Github\n'
        else:
            msg += '🔒 Github\n'

        if my_db.get_user_property(chat_id_full, 'blocked'):
            msg += f'\n{tr("User was banned.", lang)}\n'

        if my_db.get_user_property(chat_id_full, 'blocked_totally'):
            msg += f'\n{tr("User was banned totally.", lang)}\n'

        if my_db.get_user_property(chat_id_full, 'blocked_bing'):
            msg += f'\n{tr("User was banned in bing.com.", lang)}\n'

        if str(message.chat.id) in DDOS_BLOCKED_USERS and not my_db.get_user_property(chat_id_full, 'blocked'):
            msg += f'\n{tr("User was temporarily banned.", lang)}\n'

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
        module_name = message.text.split(' ', 1)[1].strip()
        modules = module_name.split()
        if len(modules) > 1:
            for module in modules:
                message.text = f'/reload {module}'
                reload_module(message)
            return

        with RELOAD_LOCK:
            # Проверяем существование файла и корректируем имя
            if not os.path.exists(f"{module_name}.py"):
                if module_name.startswith('my_') and os.path.exists(f"{module_name[3:]}.py"):
                    module_name = module_name[3:]
                elif not module_name.startswith('my_') and os.path.exists(f"my_{module_name}.py"):
                    module_name = f"my_{module_name}"
                else:
                    raise Exception(f"Файл для модуля '{module_name}' не найден")

            module = importlib.import_module(module_name)
            importlib.reload(module)

            # реинициализация модуля
            if module_name in ('my_gemini', 'my_gemini3'):
                my_gemini_general.load_users_keys()
                my_skills.init()
            elif module_name == 'my_groq':
                my_groq.load_users_keys()
            elif module_name == 'my_mistral':
                my_mistral.load_users_keys()
            elif module_name == 'my_github':
                my_github.load_users_keys()
            elif module_name == 'my_nebius':
                my_nebius.load_users_keys()
            elif module_name == 'my_cohere':
                my_cohere.load_users_keys()
            elif module_name == 'my_init':
                load_msgs()
            elif module_name == 'my_skills':
                my_skills.init()
            elif module_name == 'my_db':
                db_backup = cfg.DB_BACKUP if hasattr(cfg, 'DB_BACKUP') else True
                db_vacuum = cfg.DB_VACUUM if hasattr(cfg, 'DB_VACUUM') else False
                my_db.init(db_backup, db_vacuum)

            msg = f'{tr("Модуль успешно перезагружен:", lang)} {module_name}'
            bot_reply(message, msg)
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


def send_long_message(message: telebot.types.Message, resp: str, parse_mode:str = None, disable_web_page_preview: bool = None,
                      reply_markup: telebot.types.InlineKeyboardMarkup = None, allow_voice: bool = False):
    """отправляем сообщение, если оно слишком длинное то разбивает на 2 части либо отправляем как текстовый файл"""
    reply_to_long_message(message=message, resp=resp, parse_mode=parse_mode,
                          disable_web_page_preview=disable_web_page_preview,
                          reply_markup=reply_markup, send_message = True,
                          allow_voice=allow_voice)


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
                reply_markup=reply_markup
            )
        else:
            m = bot.reply_to(
                message,
                chunk,
                parse_mode=parse_mode,
                link_preview_options=preview,
                reply_markup=reply_markup
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
            # my_log.log2(chunk)

            _send_message(message, chunk, '', preview, reply_markup, send_message, resp, retry_times)


def reply_to_long_message(
    message: telebot.types.Message,
    resp: str,
    parse_mode: str = None,
    disable_web_page_preview: bool = None,
    reply_markup: telebot.types.InlineKeyboardMarkup = None,
    send_message: bool = False,
    allow_voice: bool = False):
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

        if parse_mode == 'HTML':
            chunks = utils.split_html(resp, 3800)
        else:
            chunks = utils.split_text(resp, 3800)

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
        if parse_mode == 'HTML':
            tables = my_md_tables_to_png.find_markdown_tables(resp)
            graphs = my_plantweb.find_code_snippets(resp)
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
) -> telebot.types.Message | None:
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


def check_donate(message: telebot.types.Message, chat_id_full: str, lang: str) -> bool:
    '''
    Если общее количество сообщений превышает лимит то надо проверить подписку
    и если не подписан то предложить подписаться.

    Если у юзера есть все ключи, и есть звезды в достаточном количестве то
    звезды надо потреблять всё равно, что бы не накапливались.
    '''
    try:
        SECONDS_IN_MONTH = 60 * 60 * 24 * 30
        # если ожидается нестандартная сумма то пропустить
        if chat_id_full in COMMAND_MODE and COMMAND_MODE[chat_id_full] == 'enter_start_amount':
            return True

        if message.from_user.id in CHECK_DONATE_LOCKS:
            lock = CHECK_DONATE_LOCKS[message.from_user.id]
        else:
            CHECK_DONATE_LOCKS[message.from_user.id] = threading.Lock()
            lock = CHECK_DONATE_LOCKS[message.from_user.id]
        with lock:
            try:
                chat_mode = my_db.get_user_property(chat_id_full, 'chat_mode')
                # если админ или это в группе происходит то пропустить или режим чата = openrouter
                if message.from_user.id in cfg.admins or chat_id_full.startswith('[-') or message.from_user.id == BOT_ID or chat_mode == 'openrouter':
                    return True

                # если за сутки было меньше 10 запросов то пропустить
                # msgs24h = my_db.count_msgs_last_24h(chat_id_full)
                # max_per_day = cfg.MAX_FREE_PER_DAY if hasattr(cfg, 'MAX_FREE_PER_DAY') else 10
                # if msgs24h <= max_per_day:
                #     return True

                # юзеры у которых есть 2 ключа не требуют подписки,
                # но если есть звезды то их надо снимать чтоб не копились
                have_keys = 0
                if chat_id_full in my_gemini_general.USER_KEYS:
                    have_keys += 1
                if chat_id_full in my_groq.USER_KEYS:
                    have_keys += 1
                if chat_id_full in my_mistral.USER_KEYS:
                    have_keys += 1
                if chat_id_full in my_cohere.USER_KEYS:
                    have_keys += 1
                if chat_id_full in my_github.USER_KEYS:
                    have_keys += 1
                have_keys = have_keys > 1

                total_messages = my_db.count_msgs_total_user(chat_id_full)
                MAX_TOTAL_MESSAGES = cfg.MAX_TOTAL_MESSAGES if hasattr(cfg, 'MAX_TOTAL_MESSAGES') else 500000
                DONATE_PRICE = cfg.DONATE_PRICE if hasattr(cfg, 'DONATE_PRICE') else 50

                if total_messages > MAX_TOTAL_MESSAGES:
                    last_donate_time = my_db.get_user_property(chat_id_full, 'last_donate_time') or 0
                    if time.time() - last_donate_time > SECONDS_IN_MONTH:
                        stars = my_db.get_user_property(chat_id_full, 'telegram_stars') or 0
                        if stars >= DONATE_PRICE:
                            my_db.set_user_property(chat_id_full, 'last_donate_time', time.time())
                            my_db.set_user_property(chat_id_full, 'telegram_stars', stars - DONATE_PRICE)
                            my_log.log_donate_consumption(f'{chat_id_full} -{DONATE_PRICE} stars')
                            # msg = tr(f'You need {DONATE_PRICE} stars for a month of free access.', lang)
                            msg = tr('You have enough stars for a month of free access. Thank you for your support!', lang)
                            bot_reply(message, msg, disable_web_page_preview = True, reply_markup = get_keyboard('donate_stars', message))
                        else:
                            if have_keys:
                                pass
                            else:
                                msg = tr(f'You need {DONATE_PRICE} stars for a month of free access.', lang)
                                msg += '\n\n' + tr('You have not enough stars for a month of free access.\n\nYou can get free access if bring all free keys, see /keys command for instruction.', lang)
                                bot_reply(message, msg, disable_web_page_preview = True, reply_markup = get_keyboard('donate_stars', message))
                                # my_log.log_donate_consumption_fail(f'{chat_id_full} user have not enough stars {stars}')
                                return False
            except Exception as unexpected_error:
                error_traceback = traceback.format_exc()
                my_log.log2(f'tb:check_donate: {chat_id_full}\n\n{unexpected_error}\n\n{error_traceback}')

    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:check_donate: {unknown}\n{traceback_error}')

    return True


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

        # проверка на подписку
        if not check_donate(message, chat_id_full, lang):
            return

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


@bot.message_handler(content_types = ['photo', 'sticker', 'animation'], func=authorized)
@async_run
def handle_photo(message: telebot.types.Message):
    """Обработчик фотографий. Сюда же попадают новости которые создаются как фотография
    + много текста в подписи, и пересланные сообщения в том числе"""
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        COMMAND_MODE[chat_id_full] = ''
        # проверка на подписку
        if not check_donate(message, chat_id_full, lang):
            return

        # catch groups of images
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

        message.caption = my_log.restore_message_text(message.caption, message.caption_entities)

        if message.caption and message.caption.startswith(('/img ', '/image ', '/gem ', '/flux ', '/bing ')):
            # заменить первое слово на !
            message.caption = message.caption.replace('/img ', '!', 1).replace('/image ', '!', 1).replace('/gem ', '!', 1).replace('/flux ', '!', 1).replace('/bing ', '!', 1)

        try:
            is_private = message.chat.type == 'private'
            supch = my_db.get_user_property(chat_id_full, 'superchat') or 0
            is_reply = message.reply_to_message and message.reply_to_message.from_user.id == BOT_ID
            if supch == 1:
                is_private = True

            msglower = message.caption.lower() if message.caption else ''

            bot_name = my_db.get_user_property(chat_id_full, 'bot_name') or BOT_NAME_DEFAULT
            bot_name_was_used = False
            # убираем из запроса кодовое слово
            if msglower.startswith((f'{bot_name} ', f'{bot_name},', f'{bot_name}\n')):
                bot_name_was_used = True
                message.caption = message.caption[len(f'{bot_name} '):].strip()

            state = ''
            bot_name2 = f'@{_bot_name}'
            # убираем из запроса имя бота в телеграме
            if msglower.startswith((f'{bot_name2} ', f'{bot_name2},', f'{bot_name2}\n')):
                bot_name_was_used = True
                message.caption = message.caption[len(f'{bot_name2} '):].strip()
            elif is_private or is_reply or bot_name_was_used:
                state = 'describe'
            elif msglower.startswith('?'):
                state = 'describe'
                message.caption = message.caption[1:]


            if not is_private and not state == 'describe':
                if not message.caption or not message.caption.startswith('?') or \
                    not bot_name_was_used:
                    return

            if is_private:
                # Если прислали медиагруппу то делаем из нее коллаж, и обрабатываем как одну картинку
                # Если картинок больше 4 то вытаскиваем из каждой текст отдельно и пытаемся собрать в 1 большой текст
                if len(MESSAGES) > 1:
                    # найти сообщение у которого есть caption
                    caption = ''
                    for msg in MESSAGES:
                        if msg.caption:
                            caption = msg.caption
                            break
                    caption = caption.strip()
                    with ShowAction(message, 'typing'):
                        images = [download_image_from_message(msg) for msg in MESSAGES]

                        # Если прислали группу картинок и запрос начинается на ! то перенаправляем запрос в редактирование картинок
                        if caption.startswith('!'):
                            caption = caption[1:]

                            image = my_gemini_genimg.regenerate_image(
                                prompt = caption,
                                sources_images=images,
                                user_id=chat_id_full)
                            if image:
                                m = send_photo(
                                    message,
                                    message.chat.id,
                                    disable_notification=True,
                                    photo=image,
                                    reply_to_message_id=message.message_id,
                                    reply_markup=get_keyboard('hide', message)
                                )
                                log_message(m)
                                add_to_bots_mem(tr('User asked to edit images', lang) + f' <prompt>{caption}</prompt>', tr('Changed images successfully.', lang), chat_id_full)
                                return
                            else:
                                bot_reply_tr(message, 'Failed to edit images.')
                                add_to_bots_mem(tr('User asked to edit images', lang) + f' <prompt>{caption}</prompt>', tr('Failed to edit images.', lang), chat_id_full)
                                return

                        if len(images) > 4:
                            big_text = ''
                            # соединить группы картинок по 4
                            images_ = utils.create_image_collages(images)
                            if images_:
                                images = images_

                            for image in images:
                                if image:
                                    try:
                                        text = img2txt(
                                            text = image,
                                            lang = lang,
                                            chat_id_full = chat_id_full,
                                            query=tr('text', lang),
                                            model = cfg.gemini_flash_light_model,
                                            temperature=0.1,
                                            system_message=tr('Give me all text from image, no any other words but text from this image', lang),
                                            timeout=60,
                                            )
                                        if text:
                                            big_text += text + '\n\n'
                                    except Exception as bunch_of_images_error1:
                                        my_log.log2(f'tb:handle_photo1: {bunch_of_images_error1}')
                            if big_text:
                                try:
                                    bot_reply(
                                        message,
                                        big_text,
                                        disable_web_page_preview=True,
                                        )
                                    if caption:
                                        message.text = f'{tr("User sent a bunch of images with text and caption:", lang)} {caption}\n\n{big_text}'
                                        do_task(message)
                                    else:
                                        add_to_bots_mem(
                                            query=tr('User sent images.', lang),
                                            resp = f"{tr('Got text from images:', lang)}\n\n{big_text}",
                                            chat_id_full=chat_id_full,
                                        )
                                except Exception as bunch_of_images_error2:
                                    my_log.log2(f'tb:handle_photo2: {bunch_of_images_error2}')
                            else:
                                bot_reply_tr(message, 'No any text in images.')
                            return
                        else:
                            if sys.getsizeof(images) > 10 * 1024 *1024:
                                bot_reply_tr(message, 'Too big files.')
                                return
                            try:
                                result_image_as_bytes = utils.make_collage(images)
                            except Exception as make_collage_error:
                                # my_log.log2(f'tb:handle_photo1: {make_collage_error}')
                                bot_reply_tr(message, 'Too big files.')
                                return
                            if len(result_image_as_bytes) > 10 * 1024 *1024:
                                result_image_as_bytes = utils.resize_image(result_image_as_bytes, 10 * 1024 *1024)
                            try:
                                m = send_photo(
                                    message,
                                    message.chat.id,
                                    result_image_as_bytes,
                                    reply_to_message_id=message.message_id,
                                    reply_markup=get_keyboard('hide', message)
                                )
                                log_message(m)
                            except Exception as send_img_error:
                                my_log.log2(f'tb:handle_photo2: {send_img_error}')
                            width, height = utils.get_image_size(result_image_as_bytes)
                            if width >= 1280 or height >= 1280:
                                try:
                                    m = send_document(
                                        message,
                                        message.chat.id,
                                        result_image_as_bytes,
                                        # caption='images.jpg',
                                        visible_file_name='images.jpg',
                                        disable_notification=True,
                                        reply_to_message_id=message.message_id,
                                        reply_markup=get_keyboard('hide', message)
                                    )
                                    log_message(m)
                                except Exception as send_doc_error:
                                    my_log.log2(f'tb:handle_photo3: {send_doc_error}')
                            my_log.log_echo(message, f'Made collage of {len(images)} images.')
                            if not caption:
                                proccess_image(chat_id_full, result_image_as_bytes, message)
                                return
                            text = img2txt(result_image_as_bytes, lang, chat_id_full, caption)
                            if text:
                                if isinstance(text, str):
                                    text = utils.bot_markdown_to_html(text)
                                    # text += tr("<b>Every time you ask a new question about the picture, you have to send the picture again.</b>", lang)
                                    bot_reply(message, text, parse_mode='HTML',
                                                        reply_markup=get_keyboard('translate', message),
                                                        disable_web_page_preview=True)
                                elif isinstance(text, bytes):
                                    m = send_photo(
                                        message,
                                        message.chat.id,
                                        text,
                                        reply_to_message_id=message.message_id,
                                        reply_markup=get_keyboard('hide', message),
                                    )
                                    log_message(m)
                                    return
                            else:
                                bot_reply_tr(message, 'Sorry, I could not answer your question.')
                            return


            if chat_id_full in IMG_LOCKS:
                lock = IMG_LOCKS[chat_id_full]
            else:
                lock = threading.Lock()
                IMG_LOCKS[chat_id_full] = lock

            # если юзер хочет найти что то по картинке
            if chat_id_full in COMMAND_MODE and COMMAND_MODE[chat_id_full] == 'google':
                with ShowAction(message, 'typing'):
                    image = download_image_from_message(message)
                    query = tr('The user wants to find something on Google, but he sent a picture as a query. Try to understand what he wanted to find and write one sentence that should be used in Google to search to fillfull his intention. Write just one sentence and I will submit it to Google, no extra words please.', lang)
                    google_query = img2txt(image, lang, chat_id_full, query)
                if google_query:
                    message.text = f'/google {google_query}'
                    bot_reply(message, tr('Googling:', lang) + f' {google_query}')
                    google(message)
                else:
                    bot_reply_tr(message, 'No results.', lang)
                return

            with lock:
                # распознаем что на картинке с помощью гугл джемини
                if state == 'describe':
                    with ShowAction(message, 'typing'):
                        image = download_image_from_message(message)

                        if not image:
                            # my_log.log2(f'tb:handle_photo4: не удалось распознать документ или фото {str(message)}')
                            return

                        if len(image) > 10 * 1024 *1024:
                            image = utils.resize_image(image, 10 * 1024 *1024)

                        image = utils.heic2jpg(image)
                        if not message.caption:
                            proccess_image(chat_id_full, image, message)
                            return
                        # грязный хак, для решения задач надо использовать мощную модель
                        if 'реши' in message.caption.lower() or 'solve' in message.caption.lower() \
                            or 'задач' in message.caption.lower() or 'задан' in message.caption.lower():
                            text = img2txt(image, lang, chat_id_full, message.caption, model = cfg.img2_txt_model_solve, temperature=0)
                        else:
                            text = img2txt(image, lang, chat_id_full, message.caption)
                        if text:
                            if isinstance(text, str):
                                text = utils.bot_markdown_to_html(text)
                                # text += tr("<b>Every time you ask a new question about the picture, you have to send the picture again.</b>", lang)
                                bot_reply(message, text, parse_mode='HTML',
                                                    reply_markup=get_keyboard('translate', message),
                                                    disable_web_page_preview=True)
                            elif isinstance(text, bytes):
                                m = send_photo(
                                    message,
                                    message.chat.id,
                                    text,
                                    reply_to_message_id=message.message_id,
                                    reply_markup=get_keyboard('hide', message)
                                )
                                log_message(m)
                                return
                        else:
                            bot_reply_tr(message, 'Sorry, I could not answer your question.')
                    return
        except Exception as error:
            traceback_error = traceback.format_exc()
            my_log.log2(f'tb:handle_photo6: {error}\n{traceback_error}')
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:handle_photo7: {unknown}\n{traceback_error}')


@bot.message_handler(func=authorized)
def echo_all(message: telebot.types.Message, custom_prompt: str = '') -> None:
    thread = threading.Thread(target=do_task, args=(message, custom_prompt))
    thread.start()
def do_task(message, custom_prompt: str = ''):
    """default handler"""
    try:
        message.text = my_log.restore_message_text(message.text, message.entities)
        if message.forward_date:
            full_name_forwarded_from = message.forward_from.full_name if hasattr(message.forward_from, 'full_name') else 'Noname'
            username_forwarded_from = message.forward_from.username if hasattr(message.forward_from, 'username') else 'Noname'
            message.text = f'forward sender name {full_name_forwarded_from} (@{username_forwarded_from}): {message.text}'
        message.text += '\n\n'

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

        message.text = message.text.strip()

        if custom_prompt:
            message.text = custom_prompt

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

        msg = message.text.lower()

        # проверка на подписку
        if not check_donate(message, chat_id_full, lang):
            return

        # detect /tts /t /tr /trans command
        if msg.startswith('/tts'):
            tts(message)
            return

        if msg.startswith(('/t', '/tr', '/trans')):
            trans(message)
            return

        chat_mode_ = my_db.get_user_property(chat_id_full, 'chat_mode')


        # но даже если ключ есть всё равно больше 300 сообщений в день нельзя
        if chat_mode_ in ('gemini15', 'gemini-exp') and my_db.count_msgs_last_24h(chat_id_full) > 300:
            chat_mode_ = 'gemini25_flash'


        # обработка \image это неправильное /image
        if (msg.startswith('\\image ') and is_private):
            message.text = message.text.replace('/', '\\', 1)
            image_gen(message)
            return

        # не обрабатывать неизвестные команды, если они не в привате, в привате можно обработать их как простой текст
        chat_bot_cmd_was_used = False


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
                    if chat_id_full in IMG_MODE_FLAG and 'bing' in IMG_MODE_FLAG[chat_id_full]:
                        message.text = f'/bing {message.text}'
                    else:
                        message.text = f'/img {message.text}'
                    image_gen(message)
                if COMMAND_MODE[chat_id_full] == 'ask':
                    message.text = f'/ask {message.text}'
                    ask_file(message)
                if COMMAND_MODE[chat_id_full] == 'ask2':
                    message.text = f'/ask2 {message.text}'
                    ask_file2(message)
                if COMMAND_MODE[chat_id_full] == 'gem':
                    message.text = f'/gem {message.text}'
                    image_gemini_gen(message)
                elif COMMAND_MODE[chat_id_full] == 'tts':
                    message.text = f'/tts {message.text}'
                    tts(message)
                elif COMMAND_MODE[chat_id_full] == 'memo':
                    message.text = f'/memo {message.text}'
                    memo_handler(message)
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
                elif COMMAND_MODE[chat_id_full] == 'image_prompt':
                    image_prompt = message.text
                    process_image_stage_2(image_prompt, chat_id_full, lang, message)
                elif COMMAND_MODE[chat_id_full] == 'enter_start_amount':
                    try:
                        amount = int(message.text)
                    except ValueError:
                        amount = 0
                    if amount:
                        prices = [telebot.types.LabeledPrice(label = "XTR", amount = amount)]
                        try:
                            bot.send_invoice(
                                message.chat.id,
                                title=tr(f'Donate stars amount:', lang) + ' ' + str(amount),
                                description = tr(f'Donate stars amount:', lang) + ' ' + str(amount),
                                invoice_payload="stars_donate_payload",
                                provider_token = "",  # Для XTR этот токен может быть пустым
                                currency = "XTR",
                                prices = prices,
                                reply_markup = get_keyboard(f'pay_stars_{amount}', message)
                            )
                        except Exception as error:
                            my_log.log_donate(f'tb:do_task: {error}\n\n{message.chat.id} {amount}')
                            bot_reply_tr(message, 'Invalid input. Please try the donation process again. Make sure the donation amount is correct. It might be too large or too small.')
                    else:
                        bot_reply_tr(message, 'Invalid input. Please try the donation process again.')
                if COMMAND_MODE[chat_id_full] != 'transcribe':
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
                                response, text__ = my_groq.check_phone_number(number)
                                my_db.add_msg(chat_id_full, my_groq.DEFAULT_MODEL)
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
        if my_sum.is_valid_url(message.text) and (is_private or bot_name_used):
            if utils.is_image_link(message.text):
                    proccess_image(chat_id_full, utils.download_image_as_bytes(message.text), message)
                    return
            else:
                if chat_id_full in COMMAND_MODE and COMMAND_MODE[chat_id_full] == 'transcribe':
                    transcribe_file(message.text, utils.get_filename_from_url(message.text), message)
                else:
                    message.text = '/sum ' + message.text
                    summ_text(message)
                return
        if chat_id_full in COMMAND_MODE and COMMAND_MODE[chat_id_full] == 'transcribe':
            COMMAND_MODE[chat_id_full] = ''
            return


        # сбрасываем режим команды
        COMMAND_MODE[chat_id_full] = ''


        # проверяем не начинается ли на вопросик и если да и в памяти есть файл то перенаправляем в команду /ask
        if msg.startswith('?') and my_db.get_user_property(chat_id_full, 'saved_file_name') and msg != '?':
            message.text = '/ask ' + message.text[1:]
            ask_file(message)
            return


        # # проверяем просят ли нарисовать что-нибудь
        # translated_draw = tr('нарисуй', lang)
        # pattern = r"^(" + translated_draw + r"|нарисуй|нарисуйте|draw)[ ,.\n]+"
        # if re.match(pattern, message.text, re.IGNORECASE):
        #     prompt = re.sub(pattern, "", message.text, flags=re.IGNORECASE).strip()
        #     if prompt:
        #         message.text = f"/image {prompt}"
        #         image_gen(message)
        #         return
        #     else:
        #         pass # считать что не сработало


        # можно перенаправить запрос к гуглу, но он долго отвечает
        # не локализуем
        if re.match(r"^(гугл|google)[ ,.\n]+", message.text, re.IGNORECASE):
            query = re.sub(r"^(гугл|google)[ ,.\n]+", "", message.text, flags=re.IGNORECASE).strip()
            if query:
                message.text = f"/google {query}"
                google(message)
                return


        # так же надо реагировать если это ответ в чате на наше сообщение или диалог происходит в привате
        elif is_reply or is_private or bot_name_used or chat_bot_cmd_was_used or (hasattr(message, 'next_button_pressed') and message.next_button_pressed):
            if len(msg) > cfg.max_message_from_user:
                my_db.set_user_property(chat_id_full, 'saved_file_name', 'big_request_auto_saved_to_file.txt')
                my_db.set_user_property(chat_id_full, 'saved_file', message.text)
                bot_reply(message, f'{tr("Слишком длинное сообщение для чат-бота было автоматически сохранено как файл, используйте команду /ask  что бы задавать вопросы по этому тексту:", lang)} {len(msg)} {tr("из", lang)} {cfg.max_message_from_user}')
                return

            if my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                action = 'record_audio'
                message.text = f'[{tr("голосовое сообщение, возможны ошибки распознавания речи, отвечай просто без форматирования текста - ответ будет зачитан вслух", lang)}]: ' + message.text
            else:
                action = 'typing'


            # formatted_date = utils.get_full_time()
            user_role = my_db.get_user_property(chat_id_full, 'role') or ''
            hidden_text = f'{my_db.get_user_property(chat_id_full, "role") or ""}'

            memos = my_db.blob_to_obj(my_db.get_user_property(chat_id_full, 'memos')) or []
            if memos:
                hidden_text += '\n\nUser asked you to keep in mind this memos: '
                hidden_text += '\n'.join(memos)


            # for DDG who dont support system_prompt
            helped_query = f'{hidden_text} {message.text}'
            helped_query = helped_query.strip()

            if chat_id_full not in CHAT_LOCKS:
                CHAT_LOCKS[chat_id_full] = threading.Lock()
            with CHAT_LOCKS[chat_id_full]:
                gmodel = 'unknown'
                if chat_mode_ == 'gemini':
                    gmodel = cfg.gemini_flash_model
                if chat_mode_ == 'gemini25_flash':
                    gmodel = cfg.gemini25_flash_model
                elif chat_mode_ == 'gemini15':
                    gmodel = cfg.gemini_pro_model
                elif chat_mode_ == 'gemini-lite':
                    gmodel = cfg.gemini_flash_light_model
                elif chat_mode_ == 'gemini-exp':
                    gmodel = cfg.gemini_exp_model
                elif chat_mode_ == 'gemini-learn':
                    gmodel = cfg.gemini_learn_model
                elif chat_mode_ == 'gemma3_27b':
                    gmodel = cfg.gemma3_27b_model

                WHO_ANSWERED[chat_id_full] = chat_mode_

                if chat_mode_.startswith(('gemini', 'gemma')):
                    WHO_ANSWERED[chat_id_full] = gmodel
                time_to_answer_start = time.time()


                def command_in_answer(answer: str, message: telebot.types.Message) -> bool:
                    try:
                        answer = utils.html.unescape(answer)
                    except Exception as error:
                        my_log.log2(f'tb:command_in_answer: {error}\n{answer}')

                    if answer.startswith('```'):
                        answer = answer[3:]
                    if answer.startswith(('/img ', '/image ', '/image: ', '/bing ', '/flux ', '/gem ', '/tts ', '/google ', '/trans ', '/sum ', '/reset', '/calc ', '/ask ')):
                        cmd = answer.split(maxsplit=1)[0]
                        message.text = answer
                        if cmd == '/img' or cmd == '/image':
                            image_gen(message)
                        elif cmd == '/bing':
                            image_bing_gen(message)
                        elif cmd == '/flux':
                            image_flux_gen(message)
                        elif cmd == '/gem':
                            image_gemini_gen(message)
                        elif cmd == '/ask':
                            ask_file(message)
                        elif cmd == '/tts':
                            message.text = utils.html_to_markdown(answer)
                            tts(message)
                        elif cmd == '/google':
                            google(message)
                        elif cmd == '/trans':
                            trans(message)
                        elif cmd == '/sum':
                            summ_text(message)
                        elif cmd == '/reset':
                            reset_(message)
                        elif cmd == '/calc':
                            message.text = f'{answer} {tr("Answer in my language please", lang)}, [language = {lang}].'
                            calc_gemini(message)
                        return True

                    if answer.startswith(('{"was_translated": "true"', '{&quot;was_translated&quot;: &quot;true&quot;,')):
                        message.text = f'/img {message.text}'
                        image_gen(message)
                        return True

                    return False

                if not my_db.get_user_property(chat_id_full, 'temperature'):
                    my_db.set_user_property(chat_id_full, 'temperature', GEMIMI_TEMP_DEFAULT)

                answer = ''

                # если активирован режим общения с Gemini
                if chat_mode_.startswith(('gemini', 'gemma')):
                    if len(msg) > my_gemini.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для Gemini, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_gemini.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            temp = my_db.get_user_property(chat_id_full, 'temperature') or 1

                            # у флеш 2.5 лайт мысли отключены по умолчанию, их надо вручную включать
                            THINKING_BUDGET = -1
                            if gmodel == cfg.gemini_flash_light_model:
                                THINKING_BUDGET = 20000

                            answer = my_gemini3.chat(
                                message.text,
                                chat_id_full,
                                temp,
                                model = gmodel,
                                system = hidden_text,
                                use_skills=True,
                                THINKING_BUDGET = THINKING_BUDGET
                            )

                            if not answer and gmodel == cfg.gemini_pro_model:
                                gmodel = cfg.gemini_pro_model_fallback
                                answer = my_gemini3.chat(
                                    message.text,
                                    chat_id_full,
                                    temp,
                                    model = gmodel,
                                    system = hidden_text,
                                    use_skills=True
                                )
                                WHO_ANSWERED[chat_id_full] = gmodel

                            if not answer and gmodel == cfg.gemini_flash_model:
                                gmodel = cfg.gemini_flash_model_fallback
                                answer = my_gemini3.chat(
                                    message.text,
                                    chat_id_full,
                                    temp,
                                    model = gmodel,
                                    system = hidden_text,
                                    use_skills=True
                                )
                                WHO_ANSWERED[chat_id_full] = gmodel

                            if not answer and gmodel == cfg.gemini25_flash_model:
                                gmodel = cfg.gemini25_flash_model_fallback
                                answer = my_gemini3.chat(
                                    message.text,
                                    chat_id_full,
                                    temp,
                                    model = gmodel,
                                    system = hidden_text,
                                    use_skills=True
                                )
                                WHO_ANSWERED[chat_id_full] = gmodel

                            if not answer and gmodel == cfg.gemini_flash_light_model:
                                gmodel = cfg.gemini_flash_light_model_fallback
                                answer = my_gemini3.chat(
                                    message.text,
                                    chat_id_full,
                                    temp,
                                    model = gmodel,
                                    system = hidden_text,
                                    use_skills=True,
                                    THINKING_BUDGET = THINKING_BUDGET,
                                )
                                WHO_ANSWERED[chat_id_full] = gmodel

                            if not answer and gmodel == cfg.gemini_learn_model:
                                gmodel = cfg.gemini_learn_model_fallback
                                answer = my_gemini3.chat(
                                    message.text,
                                    chat_id_full,
                                    temp,
                                    model = gmodel,
                                    system = hidden_text,
                                    use_skills=True
                                )
                                WHO_ANSWERED[chat_id_full] = gmodel

                            if not answer and gmodel == cfg.gemini_exp_model:
                                gmodel = cfg.gemini_exp_model_fallback
                                answer = my_gemini3.chat(
                                    message.text,
                                    chat_id_full,
                                    temp,
                                    model = gmodel,
                                    system = hidden_text,
                                    use_skills=True
                                )
                                WHO_ANSWERED[chat_id_full] = gmodel

                            if not answer and gmodel == cfg.gemma3_27b_model:
                                gmodel = cfg.gemma3_27b_model_fallback
                                answer = my_gemini3.chat(
                                    message.text,
                                    chat_id_full,
                                    temp,
                                    model = gmodel,
                                    system = hidden_text,
                                    use_skills=True
                                )
                                WHO_ANSWERED[chat_id_full] = gmodel


                            # если обычное джемини не ответили (перегруз?) то попробовать лайв версию
                            if not answer:
                                gmodel = cfg.gemini_flash_live_model
                                answer = my_gemini3.chat(
                                    message.text,
                                    chat_id_full,
                                    temp,
                                    model = gmodel,
                                    system = hidden_text,
                                    use_skills=True
                                )
                                WHO_ANSWERED[chat_id_full] = gmodel


                            # если ответ длинный и в нем очень много повторений то вероятно это зависший ответ
                            # передаем эстафету следующему претенденту (ламе)
                            if len(answer) > 2000 and my_transcribe.detect_repetitiveness_with_tail(answer):
                                answer = ''


                            if chat_id_full not in WHO_ANSWERED:
                                WHO_ANSWERED[chat_id_full] = gmodel
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'


                            if edit_image_detect(answer, lang):
                                if chat_id_full in WHO_ANSWERED:
                                    del WHO_ANSWERED[chat_id_full]
                                # отменяем ответ
                                my_gemini3.undo(chat_id_full)

                                last_image = UNCAPTIONED_IMAGES[chat_id_full][1] if chat_id_full in UNCAPTIONED_IMAGES else None
                                query = message.text
                                if not last_image:
                                    r = ''
                                    bot_reply_tr(message, 'There is no uncaptioned image to edit.')
                                else:
                                    r = img2img(
                                        text=last_image,
                                        lang=lang,
                                        chat_id_full=chat_id_full,
                                        query=query,
                                        model=gmodel,
                                        temperature=temp,
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
                                return

                            flag_gpt_help = False
                            if not answer:
                                mem__ = my_gemini3.get_mem_for_llama(chat_id_full, lines_amount = 10, model = gmodel)

                                answer = my_mistral.ai(
                                    message.text,
                                    mem = mem__,
                                    user_id=chat_id_full,
                                    system=hidden_text,
                                    temperature=temp)

                                cohere_used = False
                                if not answer:
                                    answer = my_cohere.ai(
                                        message.text,
                                        mem_ = mem__,
                                        user_id=chat_id_full,
                                        system=hidden_text,
                                        temperature=temp)
                                    cohere_used = True

                                flag_gpt_help = True
                                if not answer:
                                    answer = 'Gemini ' + tr('did not answered, try to /reset and start again', lang)

                                my_gemini3.update_mem(message.text, answer, chat_id_full, model = my_db.get_user_property(chat_id_full, 'chat_mode'))

                            if answer.startswith('The bot successfully generated images on the external services'):
                                undo_cmd(message, show_message=False)
                                message.text = f'/img {message.text}'
                                image_gen(message)
                                return

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            if flag_gpt_help:
                                help_model = 'cohere' if cohere_used else 'mistral'
                                WHO_ANSWERED[chat_id_full] = f'👇{gmodel} + {help_model} {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'
                                my_log.log_echo(message, f'[{gmodel} + {help_model}] {answer}')
                            else:
                                my_log.log_echo(message, f'[{gmodel}] {answer}')


                            # отправляем файлы если они были сгенерированы в скилах
                            send_all_files_from_storage(message, chat_id_full)


                            try:
                                if command_in_answer(answer, message):
                                    return
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'tb:do_task: {error}')
                                my_log.log2(f'tb:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'tb:do_task:{gmodel} {error3}\n{error_traceback}')


                # если активирован режим общения с openrouter
                elif chat_mode_ == 'openrouter':
                    with ShowAction(message, action):
                        try:
                            timeout_ = my_db.get_user_property(chat_id_full, 'openrouter_timeout') or my_openrouter.DEFAULT_TIMEOUT
                            status, answer = my_openrouter.chat(
                                message.text,
                                chat_id_full,
                                system=hidden_text,
                                timeout = timeout_)
                            if answer:
                                def float_to_string(num):
                                    getcontext().prec = 8  # устанавливаем точность
                                    num = Decimal(str(num))  # преобразуем в Decimal
                                    num = num.quantize(Decimal('1e-7')) # округляем до 7 знаков
                                    return str(num).rstrip('0').rstrip('.') #удаляем нули и точку
                                if chat_id_full in my_openrouter.PRICE:
                                    price_in = my_db.get_user_property(chat_id_full, 'openrouter_in_price')
                                    price_out = my_db.get_user_property(chat_id_full, 'openrouter_out_price')
                                    if price_in or price_out:
                                        price_in = Decimal(str(price_in)) / 1000000
                                        price_out = Decimal(str(price_out)) / 1000000
                                        t_in = my_openrouter.PRICE[chat_id_full][0]
                                        t_out = my_openrouter.PRICE[chat_id_full][1]
                                        p_in = t_in * price_in
                                        p_out = t_out * price_out
                                        currency = my_db.get_user_property(chat_id_full, 'openrouter_currency') or '$'
                                        s = f'\n\n`[IN ({t_in}) {float_to_string(p_in)} + OUT ({t_out}) {float_to_string(p_out)} = {float_to_string(p_in+p_out)} {currency}]`'
                                        answer += s
                                    del my_openrouter.PRICE[chat_id_full]
                            WHO_ANSWERED[chat_id_full] = 'openrouter ' + my_openrouter.PARAMS[chat_id_full][0]
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'

                            if not answer:
                                answer = 'Openrouter ' + tr('did not answered, try to /reset and start again. Check your balance or /help2', lang)

                            if answer.startswith('The bot successfully generated images on the external services'):
                                undo_cmd(message, show_message=False)
                                message.text = f'/img {message.text}'
                                image_gen(message)
                                return

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            my_log.log_echo(message, f'[openrouter {my_openrouter.PARAMS[chat_id_full][0]}] {answer}')
                            try:
                                if command_in_answer(answer, message):
                                    return
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'tb:do_task: {error}')
                                my_log.log2(f'tb:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'tb:do_task:openrouter {error3}\n{error_traceback}')


                # если активирован режим общения с Mistral Large
                elif chat_mode_ == 'mistral':
                    if len(msg) > my_mistral.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для Mistral Large, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_mistral.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            answer = my_mistral.chat(
                                message.text,
                                chat_id_full,
                                temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                system=hidden_text,
                                model = my_mistral.DEFAULT_MODEL,
                                use_skills=False,
                            )

                            WHO_ANSWERED[chat_id_full] = my_mistral.DEFAULT_MODEL
                            autor = WHO_ANSWERED[chat_id_full]
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'

                            if not answer:
                                answer = my_mistral.chat(
                                    message.text,
                                    chat_id_full,
                                    temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                    system=hidden_text,
                                    model = my_mistral.FALLBACK_MODEL,
                                    use_skills=False,
                                )
                                WHO_ANSWERED[chat_id_full] = my_mistral.FALLBACK_MODEL
                                autor = WHO_ANSWERED[chat_id_full]
                                WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'

                            # отправляем файлы если они были сгенерированы в скилах
                            send_all_files_from_storage(message, chat_id_full)

                            if answer.startswith('The bot successfully generated images on the external services'):
                                undo_cmd(message, show_message=False)
                                message.text = f'/img {message.text}'
                                image_gen(message)
                                return

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            answer = answer.strip()
                            if not answer:
                                answer = f'{autor} ' + tr('did not answered, try to /reset and start again.', lang)

                            my_log.log_echo(message, f'[{autor}] {answer}')

                            try:
                                if command_in_answer(answer, message):
                                    return
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'tb:do_task: {error}')
                                my_log.log2(f'tb:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'tb:do_task:mistral {error3}\n{error_traceback}')


                # если активирован режим общения с Magistral Medium
                elif chat_mode_ == 'magistral':
                    if len(msg) > my_mistral.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для Magistral Medium, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_mistral.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            answer = my_mistral.chat(
                                message.text,
                                chat_id_full,
                                temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                system=hidden_text,
                                model = my_mistral.MAGISTRAL_MODEL,
                            )

                            if not answer:
                                answer = my_mistral.chat(
                                    message.text,
                                    chat_id_full,
                                    temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                    system=hidden_text,
                                    model = my_mistral.MAGISTRAL_MODEL_SMALL,
                                )

                            WHO_ANSWERED[chat_id_full] = 'Magistral Medium'
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'

                            if answer.startswith('The bot successfully generated images on the external services'):
                                undo_cmd(message, show_message=False)
                                message.text = f'/img {message.text}'
                                image_gen(message)
                                return

                            thoughts, answer = utils_llm.split_thoughts(answer)
                            thoughts = utils.bot_markdown_to_html(thoughts)

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            answer = answer.strip()
                            if not answer:
                                answer = 'Magistral Medium ' + tr('did not answered, try to /reset and start again.', lang)

                            my_log.log_echo(message, f'[Magistral Medium] {answer}')

                            try:
                                if command_in_answer(answer, message):
                                    return
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'tb:do_task: {error}')
                                my_log.log2(f'tb:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'tb:do_task:magistral {error3}\n{error_traceback}')


                # если активирован режим общения с Qwen 3 235b a22b
                elif chat_mode_ == 'qwen3':
                    if len(msg) > my_openrouter_free.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для Qwen 3 235b a22b, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_openrouter_free.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            answer = my_openrouter_free.chat(
                                message.text,
                                chat_id_full,
                                temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                system=hidden_text,
                                model = my_openrouter_free.DEFAULT_MODEL,
                            )

                            WHO_ANSWERED[chat_id_full] = 'Qwen 3 235b a22b'
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'

                            thoughts, answer = utils_llm.split_thoughts(answer)
                            thoughts = utils.bot_markdown_to_html(thoughts)

                            if answer.startswith('The bot successfully generated images on the external services'):
                                undo_cmd(message, show_message=False)
                                message.text = f'/img {message.text}'
                                image_gen(message)
                                return

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            answer = answer.strip()
                            if not answer:
                                answer = 'Qwen 3 235b a22b ' + tr('did not answered, try to /reset and start again.', lang)

                            my_log.log_echo(message, f'[Qwen 3 235b a22b] {answer}')

                            try:
                                if command_in_answer(answer, message):
                                    return
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'tb:do_task: {error}')
                                my_log.log2(f'tb:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'tb:do_task:qwen3 {error3}\n{error_traceback}')


                # если активирован режим общения с gpt-4o
                elif chat_mode_ == 'gpt-4o':
                    if len(msg) > my_github.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для GPT-4o, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_github.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            answer = my_github.chat(
                                message.text,
                                chat_id_full,
                                temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                system=hidden_text,
                                model = my_github.BIG_GPT_MODEL,
                            )
                            if not answer:
                                answer = my_github.chat(
                                    message.text,
                                    chat_id_full,
                                    temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                    system=hidden_text,
                                    model = my_github.DEFAULT_MODEL,
                                )
                                WHO_ANSWERED[chat_id_full] = 'GPT-4o-mini'
                            else:
                                WHO_ANSWERED[chat_id_full] = 'GPT-4o'

                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'

                            if answer.startswith('The bot successfully generated images on the external services'):
                                undo_cmd(message, show_message=False)
                                message.text = f'/img {message.text}'
                                image_gen(message)
                                return

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            answer = answer.strip()
                            if not answer:
                                answer = 'GPT-4o ' + tr('did not answered, try to /reset and start again.', lang)

                            my_log.log_echo(message, f'[GPT-4o] {answer}')

                            try:
                                if command_in_answer(answer, message):
                                    return
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'tb:do_task: {error}')
                                my_log.log2(f'tb:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'tb:do_task:gpt-4o {error3}\n{error_traceback}')


                # если активирован режим общения с gpt_41
                elif chat_mode_ == 'gpt_41':
                    if len(msg) > my_github.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для GPT 4.1, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_github.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            answer = my_github.chat(
                                message.text,
                                chat_id_full,
                                temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                system=hidden_text,
                                model = my_github.BIG_GPT_41_MODEL,
                            )
                            if not answer:
                                answer = my_github.chat(
                                    message.text,
                                    chat_id_full,
                                    temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                    system=hidden_text,
                                    model = my_github.DEFAULT_41_MINI_MODEL,
                                )
                                WHO_ANSWERED[chat_id_full] = 'GPT 4.1 mini'
                            else:
                                WHO_ANSWERED[chat_id_full] = 'GPT 4.1'

                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'

                            if answer.startswith('The bot successfully generated images on the external services'):
                                undo_cmd(message, show_message=False)
                                message.text = f'/img {message.text}'
                                image_gen(message)
                                return

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            answer = answer.strip()
                            if not answer:
                                answer = 'GPT 4.1 ' + tr('did not answered, try to /reset and start again.', lang)

                            my_log.log_echo(message, f'[GPT 4.1] {answer}')

                            try:
                                if command_in_answer(answer, message):
                                    return
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'tb:do_task: {error}')
                                my_log.log2(f'tb:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'tb:do_task:gpt_41 {error3}\n{error_traceback}')


                # если активирован режим общения с gpt_41_mini
                elif chat_mode_ == 'gpt_41_mini':
                    if len(msg) > my_github.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для GPT 4.1 mini, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_github.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            answer = my_github.chat(
                                message.text,
                                chat_id_full,
                                temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                system=hidden_text,
                                model = my_github.DEFAULT_41_MINI_MODEL,
                            )
                            if not answer:
                                answer = my_github.chat(
                                    message.text,
                                    chat_id_full,
                                    temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                    system=hidden_text,
                                    model = my_github.DEFAULT_MODEL,
                                )
                                WHO_ANSWERED[chat_id_full] = 'GPT 4.1 mini'
                            else:
                                WHO_ANSWERED[chat_id_full] = 'GPT 4.1 mini'

                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'

                            if answer.startswith('The bot successfully generated images on the external services'):
                                undo_cmd(message, show_message=False)
                                message.text = f'/img {message.text}'
                                image_gen(message)
                                return

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            answer = answer.strip()
                            if not answer:
                                answer = 'GPT 4.1 mini ' + tr('did not answered, try to /reset and start again.', lang)

                            my_log.log_echo(message, f'[GPT 4.1 mini] {answer}')

                            try:
                                if command_in_answer(answer, message):
                                    return
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'tb:do_task: {error}')
                                my_log.log2(f'tb:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'tb:do_task:gpt_41_mini {error3}\n{error_traceback}')


                # если активирован режим общения с DeepSeek R1
                elif chat_mode_ == 'deepseek_r1':
                    if len(msg) > my_nebius.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для DeepSeek R1, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_nebius.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            answer = my_nebius.chat(
                                message.text,
                                chat_id_full,
                                temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                system=hidden_text,
                                model = my_nebius.DEFAULT_MODEL,
                            )
                            if not answer:
                                answer = my_nebius.chat(
                                    message.text,
                                    chat_id_full,
                                    temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                    system=hidden_text,
                                    model = my_nebius.DEFAULT_MODEL_FALLBACK,
                                    max_tokens = 4000,
                                )
                                WHO_ANSWERED[chat_id_full] = 'DeepSeek R1+V3'
                            else:
                                WHO_ANSWERED[chat_id_full] = 'DeepSeek R1'

                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'

                            answer = answer.strip()
                            if not answer:
                                answer = 'DeepSeek R1 ' + tr('did not answered, try to /reset and start again.', lang)

                            thoughts, answer = utils_llm.split_thoughts(answer)
                            thoughts = utils.bot_markdown_to_html(thoughts)

                            if answer.startswith('The bot successfully generated images on the external services'):
                                undo_cmd(message, show_message=False)
                                message.text = f'/img {message.text}'
                                image_gen(message)
                                return

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            # answer = utils_llm.reconstruct_html_answer_with_thoughts(thoughts, answer)

                            my_log.log_echo(message, f'[DeepSeek R1] {answer}')

                            try:
                                if command_in_answer(answer, message):
                                    return
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'tb:do_task: {error}')
                                my_log.log2(f'tb:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'tb:do_task:deepseek_r1 {error3}\n{error_traceback}')


                # если активирован режим общения с DeepSeek V3
                elif chat_mode_ == 'deepseek_v3':
                    if len(msg) > my_nebius.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для DeepSeek V3, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_nebius.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            answer = my_nebius.chat(
                                message.text,
                                chat_id_full,
                                temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                system=hidden_text,
                                model = my_nebius.DEFAULT_MODEL,
                            )
                            if not answer:
                                answer = my_nebius.chat(
                                    message.text,
                                    chat_id_full,
                                    temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                    system=hidden_text,
                                    model = my_nebius.DEFAULT_MODEL_FALLBACK,
                                    max_tokens = 4000,
                                )
                                WHO_ANSWERED[chat_id_full] = 'DeepSeek V3+R1'
                            else:
                                WHO_ANSWERED[chat_id_full] = 'DeepSeek V3'

                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'

                            answer = answer.strip()
                            if not answer:
                                answer = 'DeepSeek V3 ' + tr('did not answered, try to /reset and start again.', lang)

                            thoughts, answer = utils_llm.split_thoughts(answer)
                            thoughts = utils.bot_markdown_to_html(thoughts)

                            if answer.startswith('The bot successfully generated images on the external services'):
                                undo_cmd(message, show_message=False)
                                message.text = f'/img {message.text}'
                                image_gen(message)
                                return

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            # answer = utils_llm.reconstruct_html_answer_with_thoughts(thoughts, answer)

                            my_log.log_echo(message, f'[DeepSeek V3] {answer}')

                            try:
                                if command_in_answer(answer, message):
                                    return
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'tb:do_task: {error}')
                                my_log.log2(f'tb:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'tb:do_task:deepseek_v3 {error3}\n{error_traceback}')


                # если активирован режим общения с Command A
                elif chat_mode_ == 'cohere':
                    if len(msg) > my_cohere.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для Command A, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_cohere.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            answer = my_cohere.chat(
                                message.text,
                                chat_id_full,
                                temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                system=hidden_text,
                                model = my_cohere.DEFAULT_MODEL,
                            )

                            WHO_ANSWERED[chat_id_full] = 'Command A'
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(time.time() - time_to_answer_start)}👇'

                            if answer.startswith('The bot successfully generated images on the external services'):
                                undo_cmd(message, show_message=False)
                                message.text = f'/img {message.text}'
                                image_gen(message)
                                return

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            answer = answer.strip()
                            if not answer:
                                answer = 'Command A ' + tr('did not answered, try to /reset and start again.', lang)

                            my_log.log_echo(message, f'[Command A] {answer}')

                            try:
                                if command_in_answer(answer, message):
                                    return
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                                
                            except Exception as error:
                                print(f'tb:do_task: {error}')
                                my_log.log2(f'tb:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'tb:do_task:cohere {error3}\n{error_traceback}')


    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:do_task: {unknown}\n{traceback_error}')


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
                my_db.CUR.execute('VACUUM;')
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

        my_gemini_general.load_users_keys()
        my_groq.load_users_keys()
        my_mistral.load_users_keys()
        my_cohere.load_users_keys()
        my_github.load_users_keys()
        my_nebius.load_users_keys()
        my_skills.init()

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
        # my_gemini_live_text.chat_cli()
        # print(my_mistral.transcribe_audio(r'C:\Users\user\Downloads\samples for ai\аудио\короткий диалог 3 голоса.m4a', language='en', get_timestamps=False))


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
