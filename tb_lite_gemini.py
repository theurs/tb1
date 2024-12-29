#!/usr/bin/env python3


import hashlib
import io
import time
import threading

import telebot
from sqlitedict import SqliteDict

import cfg
import my_gemini_light
import my_db
import my_tts
import utils
from utils import async_run


# Инициализация бота Telegram
bot = telebot.TeleBot(cfg.token_gemini_lite)

SYSTEMS = SqliteDict('db/gemini_light_systems.db', autocommit=True)
USERS = SqliteDict('db/gemini_light_users.db', autocommit=True)
TRANSLATIONS = SqliteDict('db/gemini_light_translations.db', autocommit=True)

# кеш для переводов в оперативной памяти
TRANS_CACHE = my_db.SmartCache()

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
                    print(f'tb:show_action:stoped after 5min [{self.chat_id}] [{self.thread_id}] is topic: {self.is_topic} action: {self.action}')
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
                        print(f'tb:show_action:run: {error}')
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
            print(f'tb:show_action: {error}')

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
        help: The help text for AI translator.
        save_cache: Whether to save the translated text in the DB.

    Returns:
        The translated text.
    """
    # Check if the language needs to be adjusted
    if lang == 'fa':
        lang = 'en'
    if lang == 'ua':
        lang = 'uk'

    # Create a unique key for the translation
    cache_key = (text, lang, help)
    cache_key_hash = hashlib.md5(str(cache_key).encode()).hexdigest()

    # First, check the faster cache
    translated = TRANS_CACHE.get(cache_key_hash)
    if translated:
        return translated

    # If not in cache, check TRANSLATIONS
    translated = TRANSLATIONS.get(cache_key_hash)
    if translated:
        # If found in TRANSLATIONS, add it to the faster cache
        TRANS_CACHE.set(cache_key_hash, translated)
        return translated

    # If not found in either, perform the translation
    translated = my_gemini_light.translate(text, to_lang=lang, help=help)

    # If translation failed, use the original text
    if not translated:
        translated = text

    # Save the new translation to both TRANS_CACHE and TRANSLATIONS if save_cache is True
    if save_cache:
        TRANS_CACHE.set(cache_key_hash, translated)
        TRANSLATIONS[cache_key_hash] = translated

    return translated


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


def authorized(message: telebot.types.Message) -> bool:
    if message.from_user.id in cfg.gemini_lite_admins or message.from_user.id in USERS.keys():
        return True
    bot_reply_tr(message, "This command is only available to authorized users")
    return False


def authorized_callback(call: telebot.types.CallbackQuery) -> bool:
    if call.from_user.id in cfg.gemini_lite_admins or call.from_user.id in USERS.keys():
        return True
    return False


def get_keyboard(kbd: str, message: telebot.types.Message, flag: str = '') -> telebot.types.InlineKeyboardMarkup:
    """создает и возвращает клавиатуру по текстовому описанию
    """
    chat_id_full = message.chat.id
    lang = message.from_user.language_code or cfg.DEFAULT_LANGUAGE

    if kbd == 'hide':
        markup  = telebot.types.InlineKeyboardMarkup()
        button1 = telebot.types.InlineKeyboardButton(tr("Hide", lang), callback_data='erase_answer')
        markup.add(button1)
        return markup
    elif kbd == 'gemini_chat' or kbd == 'chat':
        markup  = telebot.types.InlineKeyboardMarkup(row_width=5)
        button0 = telebot.types.InlineKeyboardButton("➡", callback_data='continue_gpt')
        button1 = telebot.types.InlineKeyboardButton('♻️', callback_data='gemini_reset')
        button2 = telebot.types.InlineKeyboardButton("🙈", callback_data='erase_answer')
        button3 = telebot.types.InlineKeyboardButton("📢", callback_data='tts')
        markup.add(button0, button1, button2, button3)
        return markup
    else:
        raise f"Неизвестная клавиатура '{kbd}'"


@bot.callback_query_handler(func=authorized_callback)
@async_run
def callback_inline_thread(call: telebot.types.CallbackQuery):
    """Обработчик клавиатуры"""

    message = call.message
    chat_id = message.chat.id
    chat_id_full = get_topic_id(message)
    user_full_id = f'[{call.from_user.id}] [0]'
    lang = message.from_user.language_code or cfg.DEFAULT_LANGUAGE

    if call.data == 'erase_answer':
        # обработка нажатия кнопки "Стереть ответ"
        bot.delete_message(message.chat.id, message.message_id)
    elif call.data == 'continue_gpt':
        # обработка нажатия кнопки "Продолжай GPT"
        message.dont_check_topic = True
        message.text = tr('Continue', lang)
        echo_all(message)
        return
    elif call.data == 'gemini_reset':
        my_gemini_light.reset(chat_id_full)
        bot_reply_tr(message, 'История диалога очищена.')
    elif call.data == 'tts':
        detected_lang = my_tts.detect_lang_carefully(message.text or message.caption or "")
        if not detected_lang:
            detected_lang = lang or "de"
        message.text = f'/tts {detected_lang} {message.text or message.caption or ""}'
        tts(message)


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
            try:
                if send_message:
                    m = bot.send_message(message.chat.id, chunk, message_thread_id=message.message_thread_id, parse_mode=parse_mode,
                                        link_preview_options=preview, reply_markup=reply_markup)
                else:
                    m = bot.reply_to(message, chunk, parse_mode=parse_mode,
                            link_preview_options=preview, reply_markup=reply_markup)
            except Exception as error:
                if "Error code: 400. Description: Bad Request: can't parse entities" in str(error):
                    pass
                else:
                    pass
                if parse_mode == 'HTML':
                    chunk = utils.html.unescape(chunk)
                    chunk = chunk.replace('<b>', '')
                    chunk = chunk.replace('<i>', '')
                    chunk = chunk.replace('</b>', '')
                    chunk = chunk.replace('</i>', '')
                if send_message:
                    m = bot.send_message(message.chat.id, chunk, message_thread_id=message.message_thread_id, parse_mode='',
                                        link_preview_options=preview, reply_markup=reply_markup)
                else:
                    m = bot.reply_to(message, chunk, parse_mode='', link_preview_options=preview, reply_markup=reply_markup)
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
    lang = message.from_user.language_code or cfg.DEFAULT_LANGUAGE
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

        # if not not_log:
        #     my_log.log_echo(message, msg)

        if send_message:
            send_long_message(message, msg, parse_mode=parse_mode,
                                disable_web_page_preview=disable_web_page_preview,
                                reply_markup=reply_markup, allow_voice=allow_voice)
        else:
            reply_to_long_message(message, msg, parse_mode=parse_mode, disable_web_page_preview=disable_web_page_preview,
                            reply_markup=reply_markup, allow_voice=allow_voice)
    except Exception as unknown:
        # my_log.log2(f'tb:bot_reply: {unknown}')
        pass


# Обработчик команды /start
@bot.message_handler(commands=['start'])
def send_welcome(message: telebot.types.Message):
    bot.reply_to(message, "Hello! I'm a bot, please talk to me!")


# Обработчик команды /id
@bot.message_handler(commands=['id'])
def show_id(message: telebot.types.Message):
    bot.reply_to(message, message.from_user.id)


# @bot.message_handler(content_types = ['photo', 'sticker'], func=authorized)
# @async_run
# def handle_photo(message: telebot.types.Message):
#     """Обработчик фотографий. Сюда же попадают новости которые создаются как фотография
#     + много текста в подписи, и пересланные сообщения в том числе"""

#     chat_id_full = message.chat.id
#     lang = message.from_user.language_code or cfg.DEFAULT_LANGUAGE

#     # catch groups of images up to 10
#     if chat_id_full not in MESSAGE_QUEUE_IMG:
#         MESSAGE_QUEUE_IMG[chat_id_full] = [message,]
#         last_state = MESSAGE_QUEUE_IMG[chat_id_full]
#         n = 10
#         while n > 0:
#             n -= 1
#             time.sleep(0.1)
#             new_state = MESSAGE_QUEUE_IMG[chat_id_full]
#             if last_state != new_state:
#                 last_state = new_state
#                 n = 10
#     else:
#         MESSAGE_QUEUE_IMG[chat_id_full].append(message)
#         return


#     if len(MESSAGE_QUEUE_IMG[chat_id_full]) > 1:
#         MESSAGES = MESSAGE_QUEUE_IMG[chat_id_full]
#     else:
#         MESSAGES = [message,]
#     del MESSAGE_QUEUE_IMG[chat_id_full]


#     try:
#         is_private = message.chat.type == 'private'
#         supch = my_db.get_user_property(chat_id_full, 'superchat') or 0
#         if supch == 1:
#             is_private = True

#         msglower = message.caption.lower() if message.caption else ''

#         # if (tr('что', lang) in msglower and len(msglower) < 30) or msglower == '':
#         if msglower.startswith('?'):
#             state = 'describe'
#             message.caption = message.caption[1:]

#         elif 'ocr' in msglower:
#             state = 'ocr'
#         elif is_private:
#             # state = 'translate'
#             # автопереводом никто не пользуется а вот описание по запросу популярно
#             state = 'describe'
#         else:
#             state = ''

#         bot_name = my_db.get_user_property(chat_id_full, 'bot_name') or BOT_NAME_DEFAULT
#         if not is_private and not state == 'describe':
#             if not message.caption or not message.caption.startswith('?') or \
#                 not message.caption.startswith(f'@{_bot_name}') or \
#                     not message.caption.startswith(bot_name):
#                 return

#         if is_private:
#             # Если прислали медиагруппу то делаем из нее коллаж, и обрабатываем как одну картинку
#             if len(MESSAGES) > 1:
#                 with ShowAction(message, 'typing'):
#                     images = [download_image_from_message(msg) for msg in MESSAGES]
#                     if sys.getsizeof(images) > 10 * 1024 *1024:
#                         bot_reply_tr(message, 'Too big files.')
#                         return
#                     try:
#                         result_image_as_bytes = utils.make_collage(images)
#                     except Exception as make_collage_error:
#                         my_log.log2(f'tb:handle_photo: {make_collage_error}')
#                         bot_reply_tr(message, 'Too big files.')
#                         return
#                     if len(result_image_as_bytes) > 10 * 1024 *1024:
#                         result_image_as_bytes = utils.resize_image(result_image_as_bytes, 10 * 1024 *1024)
#                     try:
#                         m = bot.send_photo( message.chat.id,
#                                             result_image_as_bytes,
#                                             disable_notification=True,
#                                             reply_to_message_id=message.message_id,
#                                             reply_markup=get_keyboard('hide', message))
#                         log_message(m)
#                     except Exception as send_img_error:
#                         my_log.log2(f'tb:handle_photo: {send_img_error}')
#                     width, height = utils.get_image_size(result_image_as_bytes)
#                     if width >= 1280 or height >= 1280:
#                         try:
#                             m = bot.send_document(
#                                 message.chat.id,
#                                 result_image_as_bytes,
#                                 # caption='images.jpg',
#                                 visible_file_name='images.jpg',
#                                 disable_notification=True,
#                                 reply_to_message_id=message.message_id,
#                                 reply_markup=get_keyboard('hide', message)
#                                 )
#                             log_message(m)
#                         except Exception as send_doc_error:
#                             my_log.log2(f'tb:handle_photo: {send_doc_error}')
#                     my_log.log_echo(message, f'Made collage of {len(images)} images.')
#                     if not message.caption:
#                         proccess_image(chat_id_full, result_image_as_bytes, message)
#                         return
#                     text = img2txt(result_image_as_bytes, lang, chat_id_full, message.caption)
#                     if text:
#                         text = utils.bot_markdown_to_html(text)
#                         # text += tr("<b>Every time you ask a new question about the picture, you have to send the picture again.</b>", lang)
#                         bot_reply(message, text, parse_mode='HTML',
#                                             reply_markup=get_keyboard('translate', message),
#                                             disable_web_page_preview=True)
#                     else:
#                         bot_reply_tr(message, 'Sorry, I could not answer your question.')
#                     return


#         if chat_id_full in IMG_LOCKS:
#             lock = IMG_LOCKS[chat_id_full]
#         else:
#             lock = threading.Lock()
#             IMG_LOCKS[chat_id_full] = lock

#         # если юзер хочет найти что то по картинке
#         if chat_id_full in COMMAND_MODE and COMMAND_MODE[chat_id_full] == 'google':
#             with ShowAction(message, 'typing'):
#                 image = download_image_from_message(message)
#                 query = tr('The user wants to find something on Google, but he sent a picture as a query. Try to understand what he wanted to find and write one sentence that should be used in Google to search to fillfull his intention. Write just one sentence and I will submit it to Google, no extra words please.', lang)
#                 google_query = img2txt(image, lang, chat_id_full, query)
#             if google_query:
#                 message.text = f'/google {google_query}'
#                 bot_reply(message, tr('Googling:', lang) + f' {google_query}')
#                 google(message)
#             else:
#                 bot_reply_tr(message, 'No results.', lang)
#             return

#         with lock:
#             with semaphore_talks:
#                 # распознаем что на картинке с помощью гугл джемини
#                 if state == 'describe':
#                     with ShowAction(message, 'typing'):
#                         image = download_image_from_message(message)
#                         if len(image) > 10 * 1024 *1024:
#                             image = utils.resize_image(image, 10 * 1024 *1024)
#                         if not image:
#                             my_log.log2(f'tb:handle_photo: не удалось распознать документ или фото {str(message)}')
#                             return

#                         image = utils.heic2jpg(image)
#                         if not message.caption:
#                             proccess_image(chat_id_full, image, message)
#                             return
#                         # грязный хак, для решения задач надо использовать мощную модель
#                         if 'реши' in message.caption.lower() or 'solve' in message.caption.lower():
#                             # text = img2txt(image, lang, chat_id_full, message.caption, model = cfg.gemini_exp_model)
#                             text = img2txt(image, lang, chat_id_full, message.caption, model = cfg.gemini_2_flash_thinking_exp_model)
#                         else:
#                             text = img2txt(image, lang, chat_id_full, message.caption)
#                         if text:
#                             text = utils.bot_markdown_to_html(text)
#                             # text += tr("<b>Every time you ask a new question about the picture, you have to send the picture again.</b>", lang)
#                             bot_reply(message, text, parse_mode='HTML',
#                                                 reply_markup=get_keyboard('translate', message),
#                                                 disable_web_page_preview=True)
#                         else:
#                             bot_reply_tr(message, 'Sorry, I could not answer your question.')
#                     return
#                 elif state == 'ocr':
#                     with ShowAction(message, 'typing'):
#                         if message.photo:
#                             photo = message.photo[-1]
#                             try:
#                                 file_info = bot.get_file(photo.file_id)
#                             except telebot.apihelper.ApiTelegramException as error:
#                                 if 'file is too big' in str(error):
#                                     bot_reply_tr(message, 'Too big file.')
#                                     return
#                                 else:
#                                     raise error
#                             image = bot.download_file(file_info.file_path)
#                         elif message.document:
#                             # скачиваем документ в байтовый поток
#                             file_id = message.document.file_id
#                             try:
#                                 file_info = bot.get_file(file_id)
#                             except telebot.apihelper.ApiTelegramException as error:
#                                 if 'file is too big' in str(error):
#                                     bot_reply_tr(message, 'Too big file.')
#                                     return
#                                 else:
#                                     raise error
#                             file = bot.download_file(file_info.file_path)
#                             fp = io.BytesIO(file)
#                             image = fp.read()
#                         else:
#                             my_log.log2(f'tb:handle_photo: не удалось распознать документ или фото {str(message)}')
#                             return

#                         image = utils.heic2jpg(image)
#                         # распознаем текст на фотографии с помощью pytesseract
#                         llang = get_ocr_language(message)
#                         if message.caption.strip()[3:]:
#                             llang = message.caption.strip()[3:].strip()
#                         text = my_ocr.get_text_from_image(image, llang)
#                         # отправляем распознанный текст пользователю
#                         if text.strip() != '':
#                             bot_reply(message, text, parse_mode='',
#                                                 reply_markup=get_keyboard('translate', message),
#                                                 disable_web_page_preview = True)

#                             text = text[:8000]
#                             add_to_bots_mem(f'{tr("юзер попросил распознать текст с картинки", lang)}',
#                                                 f'{tr("бот распознал текст и ответил:", lang)} {text}',
#                                                 chat_id_full)

#                         else:
#                             bot_reply_tr(message, '[OCR] no results')
#                     return
#                 elif state == 'translate':
#                     # пересланные сообщения пытаемся перевести даже если в них картинка
#                     # новости в телеграме часто делают как картинка + длинная подпись к ней
#                     if message.forward_from_chat and message.caption:
#                         # у фотографий нет текста но есть заголовок caption. его и будем переводить
#                         with ShowAction(message, 'typing'):
#                             text = my_trans.translate(message.caption)
#                         if text:
#                             bot_reply(message, text)
#                         else:
#                             my_log.log_echo(message, "Не удалось/понадобилось перевести.")
#                         return
#     except Exception as error:
#         traceback_error = traceback.format_exc()
#         my_log.log2(f'tb:handle_photo: {error}\n{traceback_error}')


# Обработчик текстовых сообщений (асинхронный)
@bot.message_handler(func=authorized)
@async_run
def echo_all(message: telebot.types.Message):
    query = message.text
    chat_id = str(message.chat.id)
    with ShowAction(message, 'typing'):
        system = SYSTEMS.get(chat_id, '')
        response = my_gemini_light.chat(query, chat_id, system = system)
        html = utils.bot_markdown_to_html(response)
        bot_reply(
            message,
            html,
            parse_mode = 'HTML',
            disable_web_page_preview = True,
            reply_markup = get_keyboard('chat', message)
            )


# Запуск бота
bot.infinity_polling(timeout=90, long_polling_timeout=90)
