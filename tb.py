#!/usr/bin/env python3

import io
import os
import random
import re
import subprocess
import tempfile
import threading
import time

import openai
import telebot
from langdetect import detect_langs

import cfg
import gpt_basic
import my_dic
import my_log
import my_ocr
import my_stt
import my_trans
import my_tts
import utils


bot = telebot.TeleBot(cfg.token, skip_pending=True)
#telebot.apihelper.proxy = cfg.proxy_settings


# до 20 одновременных потоков для чата с гпт и бингом
semaphore_talks = threading.Semaphore(20)

# замок для блокировки постоянных словарей
lock_dicts = threading.Lock()
# история диалогов для GPT chat
dialogs = my_dic.PersistentDict('dialogs.pkl')
# в каких чатах выключены автопереводы
blocks = my_dic.PersistentDict('blocks.pkl')
# в каких чатах какое у бота кодовое слово для обращения к боту
bot_names = my_dic.PersistentDict('names.pkl')
# имя бота по умолчанию, в нижнем регистре без пробелов и символов
bot_name_default = 'бот'


class show_action(threading.Thread):
    """Поток который можно остановить. Беспрерывно отправляет в чат уведомление об активности.
    Телеграм автоматически гасит уведомление через 5 секунд, по-этому его надо повторять.
    Использовать в коде надо как то так
    with show_action(chat_id, 'typing'):
        делаем что-нибудь и пока делаем уведомление не гаснет
    
    """
    def __init__(self, chat_id, action):
        super().__init__()
        self.actions = [  "typing", "upload_photo", "record_video", "upload_video", "record_audio",
                         "upload_audio", "upload_document", "find_location", "record_video_note", "upload_video_note"]
        assert action in self.actions, f'Допустимые actions = {self.actions}'
        self.chat_id = chat_id
        self.action = action
        self.is_running = True
        #self.start()
        self.timerseconds = 1
        
    def run(self):
        while self.is_running:
            bot.send_chat_action(self.chat_id, self.action)
            n = 50
            while n > 0:
                time.sleep(0.1)
                n = n - self.timerseconds

    def stop(self):
        self.timerseconds = 50
        self.is_running = False

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
    global dialogs
    
    # что делать с слишком длинными запросами? пока будем просто игнорировать
    #if len(text) > 2000: ''
    
    # создаем новую историю диалогов с юзером из старой если есть
    # в истории диалогов не храним системный промпт
    if chat_id in dialogs:
        with lock_dicts:
            new_messages = dialogs[chat_id]
    else:
        new_messages = []
    # теперь ее надо почистить что бы влезла в запрос к GPT
    # просто удаляем все кроме 10 последний
    if len(new_messages) > 10:
        new_messages = new_messages[10:]
    # удаляем первую запись в истории до тех пор пока общее количество токенов не станет меньше 2000
    # удаляем по 2 сразу так как первая - промпт для бота
    while (utils.count_tokens(new_messages) > 2000):
        new_messages = new_messages[2:]
    
    # добавляем в историю новый запрос и отправляем
    new_messages = new_messages + [{"role":    "user",
                                    "content": text}]

    if engine == 'gpt':
        # пытаемся получить ответ
        try:
            resp = gpt_basic.ai(prompt = text, messages = utils.gpt_start_message + new_messages)
            if resp:
                new_messages = new_messages + [{"role":    "assistant",
                                                    "content": resp}]
            else:
                # не сохраняем диалог, нет ответа
                return 'GPT не ответил.'
        # бот не ответил или обиделся
        except AttributeError:
            # не сохраняем диалог, нет ответа
            return 'Не хочу говорить об этом. Или не могу.'
        # произошла ошибка переполнения ответа
        except openai.error.InvalidRequestError as error:
            if """This model's maximum context length is 4097 tokens. However, you requested""" in str(error):
                # чистим историю, повторяем запрос
                while (utils.count_tokens(new_messages) > 1000):
                    new_messages = new_messages[2:]
                new_messages = new_messages[:-2]
                try:
                    resp = gpt_basic.ai(prompt = text, messages = utils.gpt_start_message + new_messages)
                except Exception as error2:
                    print(error2)
                    return 'GPT не ответил.'
                # добавляем в историю новый запрос и отправляем в GPT, если он не пустой, иначе удаляем запрос юзера из истории
                if resp:
                    new_messages = new_messages + [{"role":    "assistant",
                                                    "content": resp}]
                else:
                    return 'GPT не ответил.'
            else:
                print(error)
                return 'GPT не ответил.'
    else:
        #bing_prompt = ''.join(f'{i["role"]} - {i["content"]}\n' for i in utils.gpt_start_message + new_messages)
        bing_prompt = text
        resp = subprocess.run(['/usr/bin/python3', '/home/ubuntu/tb/bingai.py', bing_prompt], stdout=subprocess.PIPE)
        #resp = subprocess.run(['/usr/bin/python3', '/home/user/V/4 python/2 telegram bot tesseract/test/bingai.py', bing_prompt], stdout=subprocess.PIPE)
        resp = resp.stdout.decode('utf-8')
        if resp:
            new_messages = new_messages + [{"role":    "assistant",
                                            "content": resp}]
        else:
            # не сохраняем диалог, нет ответа
            return 'Бинг не ответил.'

    # сохраняем диалог
    with lock_dicts:
        dialogs[chat_id] = new_messages or utils.gpt_start_message
    return resp


@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call: telebot.types.CallbackQuery):
    """Обработчик клавиатуры"""
    thread = threading.Thread(target=callback_inline_thread, args=(call,))
    thread.start()
def callback_inline_thread(call: telebot.types.CallbackQuery):
    """Обработчик клавиатуры"""
    with semaphore_talks:
        message = call.message
        is_private = message.chat.type == 'private'
        is_reply = message.reply_to_message is not None and message.reply_to_message.from_user.id == bot.get_me().id
        chat_id = message.chat.id
        global dialogs

        # клавиатура
        markup  = telebot.types.InlineKeyboardMarkup()
        button1 = telebot.types.InlineKeyboardButton("Дальше", callback_data='continue_gpt')
        button2 = telebot.types.InlineKeyboardButton("Забудь", callback_data='forget_all')
        button3 = telebot.types.InlineKeyboardButton("Скрой", callback_data='erase_answer')
        markup.add(button1, button2, button3)

        if call.data == 'clear_history':
            # обработка нажатия кнопки "Стереть историю"
            bot.edit_message_reply_markup(message.chat.id, message.message_id)
            with lock_dicts:
                dialogs[chat_id] = []
            bot.delete_message(message.chat.id, message.message_id)
        elif call.data == 'continue_gpt':
            # обработка нажатия кнопки "Продолжай GPT"
            bot.edit_message_reply_markup(message.chat.id, message.message_id)
            with show_action(chat_id, 'typing'):
                # добавляем новый запрос пользователя в историю диалога пользователя
                resp = dialog_add_user_request(chat_id, 'Продолжай', 'gpt')
                if resp:
                    if is_private:
                        try:
                            bot.send_message(chat_id, resp, parse_mode='Markdown', disable_web_page_preview = True, reply_markup=markup)
                        except Exception as error:    
                            print(error)
                            bot.send_message(chat_id, utils.escape_markdown(resp), parse_mode='Markdown', disable_web_page_preview = True, reply_markup=markup)
                    else:
                        try:
                            bot.reply_to(message, resp, parse_mode='Markdown', disable_web_page_preview = True, reply_markup=markup)
                        except Exception as error:    
                            print(error)
                            bot.reply_to(message, utils.escape_markdown(resp), parse_mode='Markdown', disable_web_page_preview = True, reply_markup=markup)
                my_log.log(message, resp)
        elif call.data == 'forget_all':
            # обработка нажатия кнопки "Забудь всё"
            bot.edit_message_reply_markup(message.chat.id, message.message_id)
            with lock_dicts:
                dialogs[chat_id] = []
        elif call.data == 'erase_answer':
            # обработка нажатия кнопки "Стереть ответ"
            bot.edit_message_reply_markup(message.chat.id, message.message_id)
            bot.delete_message(message.chat.id, message.message_id)


@bot.message_handler(content_types = ['audio'])
def handle_audio(message: telebot.types.Message):
    """Распознавание текст из аудио файлов"""
    thread = threading.Thread(target=handle_audio_thread, args=(message,))
    thread.start()
def handle_audio_thread(message: telebot.types.Message):
    """Распознавание текст из аудио файлов"""
    with semaphore_talks:
        caption = message.caption
        if not(message.chat.type == 'private' or caption.lower() in ['распознай', 'расшифруй']):
            return
        with show_action(message.chat.id, 'typing'):
            # Создание временного файла 
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                file_path = temp_file.name
            # Скачиваем аудиофайл во временный файл
            file_info = bot.get_file(message.audio.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            with open(file_path, 'wb') as new_file:
                new_file.write(downloaded_file)
            # Распознаем текст из аудио 
            text = my_stt.stt(file_path)
            os.remove(file_path)
            # Отправляем распознанный текст 
            if text.strip() != '':
                bot.reply_to(message, text)
                my_log.log(message, f'[ASR] {text}')
            else:
                my_log.log(message, '[ASR] no results')


@bot.message_handler(content_types = ['voice'])
def handle_voice(message: telebot.types.Message): 
    """Автоматическое распознавание текст из голосовых сообщений"""
    thread = threading.Thread(target=handle_voice_thread, args=(message,))
    thread.start()
def handle_voice_thread(message: telebot.types.Message): 
    """Автоматическое распознавание текст из голосовых сообщений"""
    with semaphore_talks:
        with show_action(message.chat.id, 'typing'):
            # Создание временного файла 
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                file_path = temp_file.name
            # Скачиваем аудиофайл во временный файл
            file_info = bot.get_file(message.voice.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            with open(file_path, 'wb') as new_file:
                new_file.write(downloaded_file)
            # Распознаем текст из аудио 
            text = my_stt.stt(file_path)
            os.remove(file_path)
            # Отправляем распознанный текст 
            if text.strip() != '':
                bot.reply_to(message, text)
                my_log.log(message, f'[ASR] {text}')
            else:
                my_log.log(message, '[ASR] no results')


@bot.message_handler(content_types = ['document'])
def handle_document(message: telebot.types.Message):
    """Обработчик документов"""
    thread = threading.Thread(target=handle_document_thread, args=(message,))
    thread.start()
def handle_document_thread(message: telebot.types.Message):
    """Обработчик документов"""
    with semaphore_talks:
        # начитываем текстовый файл только если его прислали в привате или с указанием прочитай/читай
        caption = message.caption or ''
        if message.chat.type == 'private' or caption.lower() in ['прочитай', 'читай']:
            with show_action(message.chat.id, 'record_audio'):
                # если текстовый файл то пытаемся озвучить как книгу. русский голос
                if message.document.mime_type == 'text/plain':
                    file_id = message.document.file_id
                    file_info = bot.get_file(file_id)
                    file = bot.download_file(file_info.file_path)
                    text = file.decode('utf-8')
                    try:
                        lang = detect_langs(text)[0].lang
                    except Exception as error:
                        lang = 'ru'
                        print(error)
                    # Озвучиваем текст
                    audio = my_tts.tts(text, lang)
                    if message.reply_to_message:
                        bot.send_voice(message.chat.id, audio, reply_to_message_id=message.reply_to_message.message_id)
                    else:
                        bot.send_voice(message.chat.id, audio)
                    my_log.log(message, f'tts file {text}')
                    return

        # дальше идет попытка распознать ПДФ файл, вытащить текст с изображений
        if message.chat.type == 'private' or caption.lower() in ['прочитай', 'читай']:
            with show_action(message.chat.id, 'upload_document'):
                # получаем самый большой документ из списка
                document = message.document
                # если документ не является PDF-файлом, отправляем сообщение об ошибке
                if document.mime_type != 'application/pdf':
                    bot.reply_to(message, 'Это не PDF-файл.')
                    return
                # скачиваем документ в байтовый поток
                file_id = message.document.file_id
                file_info = bot.get_file(file_id)
                file = bot.download_file(file_info.file_path)
                fp = io.BytesIO(file)

                # распознаем текст в документе с помощью функции get_text
                text = my_ocr.get_text(fp)
                # отправляем распознанный текст пользователю
                if text.strip() != '':
                    # если текст слишком длинный, отправляем его в виде текстового файла
                    if len(text) > 4096:
                        with io.StringIO(text) as f:
                            if message.reply_to_message:
                                bot.send_document(message.chat.id, document = f, visible_file_name = 'text.txt', caption='text.txt', reply_to_message_id = message.reply_to_message.id)
                            else:
                                bot.send_document(message.chat.id, document = f, visible_file_name = 'text.txt', caption='text.txt')
                    else:
                        bot.reply_to(message, text)


@bot.message_handler(content_types = ['photo'])
def handle_photo(message: telebot.types.Message):
    """Обработчик фотографий. Сюда же попадают новости которые создаются как фотография + много текста в подписи, и пересланные сообщения в том числе"""
    thread = threading.Thread(target=handle_photo_thread, args=(message,))
    thread.start()
def handle_photo_thread(message: telebot.types.Message):
    """Обработчик фотографий. Сюда же попадают новости которые создаются как фотография + много текста в подписи, и пересланные сообщения в том числе"""
    with semaphore_talks:
        # пересланные сообщения пытаемся перевести даже если в них картинка
        # новости в телеграме часто делают как картинка + длинная подпись к ней
        if message.forward_from_chat:
            # у фотографий нет текста но есть заголовок caption. его и будем переводить
            text = my_trans.translate(message.caption)
            if text:
                bot.send_message(message.chat.id, text)
                my_log.log(message, text)
            else:
                my_log.log(message, '')
            return

        # распознаем текст только если есть команда для этого
        if not message.caption: return
        if not gpt_basic.detect_ocr_command(message.caption.lower()): return
        with show_action(message.chat.id, 'typing'):
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
                        if message.reply_to_message:
                            bot.send_document(message.chat.id, f, reply_to_message_id=message.reply_to_message.message_id)
                        else:
                            bot.send_document(message.chat.id, f)
                        my_log.log(message, '[OCR] Sent as file: ' + text)
                else:
                    if message.reply_to_message:
                        bot.send_message(message.chat.id, text, message.reply_to_message.message_id)
                    else:
                        bot.send_message(message.chat.id, text)
                    my_log.log(message, '[OCR] ' + text)
            else:
                my_log.log(message, '[OCR] no results')


@bot.message_handler(content_types = ['video'])
def handle_video(message: telebot.types.Message):
    """Обработчик видеосообщений. Сюда же относятся новости и репосты с видео"""
    thread = threading.Thread(target=handle_video_thread, args=(message,))
    thread.start()
def handle_video_thread(message: telebot.types.Message):
    """Обработчик видеосообщений. Сюда же относятся новости и репосты с видео"""
    with semaphore_talks:
        # пересланные сообщения пытаемся перевести даже если в них видео
        if message.forward_from_chat:
            # у видео нет текста но есть заголовок caption. его и будем переводить
            text = my_trans.translate(message.caption)
            if text:
                bot.send_message(message.chat.id, text)
                my_log.log(message, text)
            else:
                my_log.log(message, "")


@bot.message_handler(commands=['mem'])
def send_debug_history(message: telebot.types.Message):
    # Отправляем текущую историю сообщений
    with lock_dicts:
        global dialogs
        
        chat_id = message.chat.id
        
        # клавиатура
        markup  = telebot.types.InlineKeyboardMarkup(row_width = 2)
        button1 = telebot.types.InlineKeyboardButton("Стереть историю", callback_data='clear_history')
        button2 = telebot.types.InlineKeyboardButton("Скрыть", callback_data='erase_answer')
        markup.add(button1, button2)

        # создаем новую историю диалогов с юзером из старой если есть
        if chat_id in dialogs:
            new_messages = dialogs[chat_id]
        else:
            new_messages = utils.gpt_start_message
        prompt = '\n'.join(f'{i["role"]} - {i["content"]}\n' for i in new_messages) or 'Пусто'
        try:
            bot.send_message(chat_id, prompt, disable_web_page_preview = True, reply_markup=markup)
        except Exception as error:
            print(error)
            bot.send_message(chat_id, utils.escape_markdown(prompt), disable_web_page_preview = True, reply_markup=markup)


@bot.message_handler(commands=['tts3']) 
def tts3(message: telebot.types.Message):
    thread = threading.Thread(target=tts3_thread, args=(message,))
    thread.start()
def tts3_thread(message: telebot.types.Message):
    with semaphore_talks:
        args = message.text.split()[1:]
        if not args:
            bot.reply_to(message, 'Использование: /tts ru|en|uk|... +-xx% <текст>')
            return
        text = ' '.join(args[2:])
        lang = args[0]
        rate = args[1]
        with show_action(message.chat.id, 'record_audio'):
            audio = my_tts.tts(text, lang, rate)
            if message.reply_to_message:
                bot.send_voice(message.chat.id, audio, reply_to_message_id = message.reply_to_message.message_id)
            else:
                bot.send_voice(message.chat.id, audio)


@bot.message_handler(commands=['tts2']) 
def tts2(message: telebot.types.Message):
    thread = threading.Thread(target=tts2_thread, args=(message,))
    thread.start()
def tts2_thread(message: telebot.types.Message):
    with semaphore_talks:
        args = message.text.split()[1:]
        if not args:
            bot.reply_to(message, 'Использование: /tts ru|en|uk|... <текст>')
            return
        text = ' '.join(args[1:])
        lang = args[0]
        with show_action(message.chat.id, 'record_audio'):
            audio = my_tts.tts(text, lang, rate)
            if message.reply_to_message:
                bot.send_voice(message.chat.id, audio, reply_to_message_id = message.reply_to_message.message_id)
            else:
                bot.send_voice(message.chat.id, audio)


@bot.message_handler(commands=['tts']) 
def tts(message: telebot.types.Message):
    thread = threading.Thread(target=tts_thread, args=(message,))
    thread.start()
def tts_thread(message: telebot.types.Message):
    with semaphore_talks:
        args = message.text.split()[1:]
        if not args:
            bot.reply_to(message, 'Использование: /tts <текст>')
            return
        text = ' '.join(args)
        with show_action(message.chat.id, 'record_audio'):
            audio = my_tts.tts(text, lang, rate)
            if message.reply_to_message:
                bot.send_voice(message.chat.id, audio, reply_to_message_id = message.reply_to_message.message_id)
            else:
                bot.send_voice(message.chat.id, audio)

@bot.message_handler(commands=['trans'])
def trans(message: telebot.types.Message):
    thread = threading.Thread(target=trans_thread, args=(message,))
    thread.start()
def trans_thread(message: telebot.types.Message):
    with semaphore_talks:
        supported_langs = [
        'af', 'am', 'ar', 'as', 'ay', 'az', 'ba', 'be', 'bg', 'bho', 'bm', 'bn', 
        'bo', 'bs', 'ca', 'ceb', 'ckb', 'co', 'cs', 'cv', 'cy', 'da', 'de', 'doi', 
        'dv', 'ee', 'el', 'en', 'eo', 'es', 'et', 'eu', 'fa', 'fi', 'fj', 'fo', 
        'fr', 'fr-CA', 'fy', 'ga', 'gd', 'gl', 'gn', 'gom', 'gu', 'ha', 'haw', 
        'he', 'hi', 'hmn', 'hr', 'hsb', 'ht', 'hu', 'hy', 'id', 'ig', 'ikt', 'ilo',
        'is', 'it', 'iu', 'iu-Latn', 'ja', 'jv', 'ka', 'kk', 'km', 'kn', 'ko', 
        'kri', 'ku', 'ky', 'la', 'lb', 'lg', 'ln', 'lo', 'lt', 'lus', 'lv', 'lzh',
        'mai', 'mg', 'mhr', 'mi', 'mk', 'ml', 'mn', 'mn-Mong', 'mni-Mtei', 'mr', 
        'mrj', 'ms', 'mt', 'my', 'ne', 'nl', 'no', 'nso', 'ny', 'om', 'or', 'otq', 
        'pa', 'pap', 'pl', 'prs', 'ps', 'pt-BR', 'pt-PT', 'qu', 'ro', 'ru', 'rw', 
        'sa', 'sah', 'sd', 'si', 'sk', 'sl', 'sm', 'sn', 'so', 'sq', 'sr-Cyrl', 
        'sr-Latn', 'st', 'su', 'sv', 'sw', 'ta', 'te', 'tg', 'th', 'ti', 'tk', 'tl',
        'tlh-Latn', 'to', 'tr', 'ts', 'tt', 'tw', 'ty', 'udm', 'ug', 'uk', 'ur', 
        'uz', 'vi', 'xh', 'yi', 'yo', 'yua', 'yue', 'zh-CN', 'zh-TW', 'zu']
        
        help_codes = """de Немецкий
en Английский
es Испанский
fr Французский
ja Японский
pl Польский
ru Русский

И многие другие
    """
        args = message.text.split(' ', 2)[1:]
        if len(args) > 1:
            lang, text = args
        else:
            lang = 'ru'
            text = args[0]
        # если язык не указан то это русский
        if lang not in supported_langs:
            text = lang + ' ' + text
            lang = 'ru'
        translated = my_trans.translate_text2(text, lang)
        if translated:
            bot.reply_to(message, translated)
        else:
            bot.reply_to(message, 'Ошибка перевода')


@bot.message_handler(commands=['name'])
def send_welcome(message: telebot.types.Message):
    """Меняем имя если оно подходящее, содержит только русские и английские буквы и не слишком длинное"""
    
    args = message.text.split()
    if len(args) > 1:
        new_name = args[1]
        
        # Строка содержит только русские и английские буквы и цифры после букв, но не в начале слова
        regex = r'^[a-zA-Zа-яА-ЯёЁ][a-zA-Zа-яА-ЯёЁ0-9]*$'
        if re.match(regex, new_name) and len(new_name) <= 10:
            with lock_dicts:
                global bot_names
                bot_names[message.chat.id] = new_name.lower()
            bot.send_message(message.chat.id, f'Кодовое слово для обращения к боту изменено на ({args[1]}) для этого чата.')
            my_log.log(message, f'Кодовое слово для обращения к боту изменено на ({args[1]}) для этого чата.')
        else:
            bot.reply_to(message, "Неправильное имя, можно только русские и английские буквы и цифры после букв, не больше 10 всего.")


@bot.message_handler(commands=['start', 'help'])
def send_welcome(message: telebot.types.Message):
    # Отправляем приветственное сообщение
    bot.send_message(message.chat.id, """Этот бот может\n\nРаспознать текст с картинки, надо отправить картинку с подписью прочитай|распознай|ocr|итп\n\n\
Озвучить текст, надо прислать текстовый файл .txt с кодировкой UTF8 в приват или с подписью прочитай\n\n\
Сообщения на иностранном языке автоматически переводятся на русский, это можно включить|выключить командой замолчи|вернись\n\n\
Голосовые сообщения автоматически переводятся в текст\n\n\
GPT chat активируется словом бот - бот, привет. Что бы отчистить историю напишите забудь.\n\n""" + open('commands.txt').read())
    my_log.log(message)


@bot.message_handler(func=lambda message: True)
def echo_all(message: telebot.types.Message) -> None:
    """Обработчик текстовых сообщений"""
    thread = threading.Thread(target=do_task, args=(message,))
    thread.start()
def do_task(message):
    """функция обработчик сообщений работающая в отдельном потоке"""
    with semaphore_talks:
        # определяем откуда пришло сообщение  
        is_private = message.chat.type == 'private'
        # является ли это ответом на наше сообщение
        is_reply = message.reply_to_message is not None and message.reply_to_message.from_user.id == bot.get_me().id
        # id куда писать ответ
        chat_id = message.chat.id

        msg = message.text.lower()
        global blocks, bot_names, dialogs

        with lock_dicts:
            # определяем какое имя у бота в этом чате, на какое слово он отзывается
            if chat_id in bot_names:
                bot_name = bot_names[chat_id]
            else:
                bot_name = bot_name_default
                bot_names[chat_id] = bot_name 
            # если сообщение начинается на 'заткнись или замолчи' то ставим блокировку на канал и выходим
            if ((msg.startswith('замолчи') or msg.startswith('заткнись')) and (is_private or is_reply)) or msg.startswith(f'{bot_name} замолчи') or msg.startswith(f'{bot_name}, замолчи') or msg.startswith(f'{bot_name}, заткнись') or msg.startswith(f'{bot_name} заткнись'):
                blocks[chat_id] = 1
                my_log.log(message, 'Включена блокировка автопереводов в чате')
                bot.send_message(chat_id, 'Автоперевод выключен', parse_mode='Markdown')
                return
            # если сообщение начинается на 'вернись' то снимаем блокировку на канал и выходим
            if ((msg.startswith('вернись')) and (is_private or is_reply)) or (msg.startswith(f'{bot_name} вернись') or msg.startswith(f'{bot_name}, вернись')):
                blocks[chat_id] = 0
                my_log.log(message, 'Выключена блокировка автопереводов в чате')
                bot.send_message(chat_id, 'Автоперевод включен', parse_mode='Markdown')
                return
            # если сообщение начинается на 'забудь' то стираем историю общения GPT
            if (msg.startswith('забудь') and (is_private or is_reply)) or (msg.startswith(f'{bot_name} забудь') or msg.startswith(f'{bot_name}, забудь')):
                dialogs[chat_id] = []
                bot.send_message(chat_id, 'Ок', parse_mode='Markdown')
                my_log.log(message, 'История GPT принудительно отчищена')
                return

        # клавиатура
        markup  = telebot.types.InlineKeyboardMarkup()
        button1 = telebot.types.InlineKeyboardButton("Дальше", callback_data='continue_gpt')
        button2 = telebot.types.InlineKeyboardButton("Забудь", callback_data='forget_all')
        button3 = telebot.types.InlineKeyboardButton("Скрой", callback_data='erase_answer')
        markup.add(button1, button2, button3)
        
        # определяем нужно ли реагировать. надо реагировать если сообщение начинается на 'бот ' или 'бот,' в любом регистре
        # можно перенаправить запрос к бингу, но он долго отвечает
        if msg.startswith('бинг ') or msg.startswith('бинг,'):
            # message.text = message.text[len(f'бинг '):] # убираем из запроса кодовое слово
            with show_action(chat_id, 'typing'):
                # добавляем новый запрос пользователя в историю диалога пользователя
                resp = dialog_add_user_request(chat_id, message.text[5:], 'bing')
                if resp:
                    if is_private:
                        try:
                            bot.send_message(chat_id, resp, parse_mode='Markdown', disable_web_page_preview = True, reply_markup=markup)
                        except Exception as error:
                            print(error)
                            bot.send_message(chat_id, utils.escape_markdown(resp), parse_mode='Markdown', disable_web_page_preview = True, reply_markup=markup)
                    else:
                        try:
                            bot.reply_to(message, resp, parse_mode='Markdown', disable_web_page_preview = True, reply_markup=markup)
                        except Exception as error:
                            print(error)
                            bot.reply_to(message, utils.escape_markdown(resp), parse_mode='Markdown', disable_web_page_preview = True, reply_markup=markup)
                    my_log.log(message, resp)
        # так же надо реагировать если это ответ в чате на наше сообщение или диалог происходит в привате
        elif msg.startswith(f'{bot_name} ') or msg.startswith(f'{bot_name},') or is_reply or is_private:
            if msg.startswith(f'{bot_name} ') or msg.startswith(f'{bot_name},'):
                message.text = message.text[len(f'{bot_name} '):] # убираем из запроса кодовое слово
            # добавляем новый запрос пользователя в историю диалога пользователя
            with show_action(chat_id, 'typing'):
                resp = dialog_add_user_request(chat_id, message.text, 'gpt')
                if resp:
                    if is_private:
                        try:
                            bot.send_message(chat_id, resp, parse_mode='Markdown', disable_web_page_preview = True, reply_markup=markup)
                        except Exception as error:    
                            print(error)
                            bot.send_message(chat_id, utils.escape_markdown(resp), parse_mode='Markdown', disable_web_page_preview = True, reply_markup=markup)
                    else:
                        try:
                            bot.reply_to(message, resp, parse_mode='Markdown', disable_web_page_preview = True, reply_markup=markup)
                        except Exception as error:    
                            print(error)
                            bot.reply_to(message, utils.escape_markdown(resp), parse_mode='Markdown', disable_web_page_preview = True, reply_markup=markup)
                    my_log.log(message, resp)
        else: # смотрим надо ли переводить текст
            with lock_dicts:
                if chat_id in blocks and blocks[chat_id] == 1:
                    return
            # if message.entities: # не надо если там спойлеры
            #     if message.entities[0]['type'] in ('code', 'spoiler'):
            #         my_log.log(message, 'code or spoiler in message')
            #         return
            text = my_trans.translate(message.text)
            if text:
                bot.send_message(chat_id, text, parse_mode='Markdown')
                my_log.log(message, text)


def set_default_commands():
    """регистрирует команды бота из файла commands.txt
/start - Приветствие
/help - Помощь
/cmd1 - Функция 1
/cmd2 - Функция 2
    """
    commands = []
    with open('commands.txt') as f:
        for line in f:
            try:
                command, description = line[1:].strip().split(' - ', 1)
                if command and description:
                    commands.append(telebot.types.BotCommand(command, description))
            except Exception as e:
                print(e)
    bot.set_my_commands(commands)


if __name__ == '__main__':
    # обновление регистрации команд при запуске
    set_default_commands()
    bot.polling()
