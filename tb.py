#!/usr/bin/env python3

import io
import html
import os
import random
import re
import tempfile
import datetime
import threading
import time

#import markdown2
import openai
import PyPDF2
import telebot
from langdetect import detect_langs

import bingai
import cfg
import gpt_basic
import my_dic
import my_log
import my_ocr
import my_stt
import my_trans
import my_tts
import utils


# устанавливаем рабочую папку = папке в которой скрипт лежит
os.chdir(os.path.abspath(os.path.dirname(__file__)))


bot = telebot.TeleBot(cfg.token, skip_pending=True)
_bot_name = bot.get_me().username
#my_log.log2(str(bot.get_me()))
#telebot.apihelper.proxy = cfg.proxy_settings


# телеграм группа для отправки сгенерированных картинок
try:
    pics_group = cfg.pics_group
    pics_group_url = cfg.pics_group_url
except Exception as error:
    print(error)
    pics_group = 0

# до 40 одновременных потоков для чата с гпт и бингом
semaphore_talks = threading.Semaphore(40)

# папка для постоянных словарей, памяти бота
if not os.path.exists('db'):
    os.mkdir('db')

# замок для блокировки постоянных словарей
lock_dicts = threading.Lock()
# история диалогов для GPT chat
dialogs = my_dic.PersistentDict('db/dialogs.pkl')
# в каких чатах выключены автопереводы
blocks = my_dic.PersistentDict('db/blocks.pkl')

# в каких чатах какой промт
prompts = my_dic.PersistentDict('db/prompts.pkl')

# запоминаем промпты для повторения рисования
image_prompt = my_dic.PersistentDict('db/image_prompts.pkl')

# запоминаем диалоги в чатах для того что бы потом можно было сделать самморизацию, выдать краткое содержание
chat_logs = my_dic.PersistentDict('db/chat_logs.pkl')

# для запоминания ответов на команду /sum
sum_cache = my_dic.PersistentDict('db/sum_cache.pkl')

# для запоминания всех сгенерированных изображений и запросов
# тут есть ключ 'total' в котором хранится счетчик записей
# записи состоят из counter_id: (prompt, images) где
# counter_id - порядковый номер для возможности перечесления последних записей в обратном порядке
# prompt - строка запроса, что хотел нарисовать юзер
# images - веб адреса картинок которые нарисовал ИИ по запросу
#          пока что в этом списке по 1 картинке, выводить по несколько сразу не получается
#          телеграм не дает прикреплять кнопки к нескольким картинкам
images_db = my_dic.PersistentDict('db/images_db.pkl')

# в каких чатах какое у бота кодовое слово для обращения к боту
bot_names = my_dic.PersistentDict('db/names.pkl')
# имя бота по умолчанию, в нижнем регистре без пробелов и символов
bot_name_default = 'бот'

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


class show_action(threading.Thread):
    """Поток который можно остановить. Беспрерывно отправляет в чат уведомление об активности.
    Телеграм автоматически гасит уведомление через 5 секунд, по-этому его надо повторять.

    Использовать в коде надо как то так
    with show_action(chat_id, 'typing'):
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
    global dialogs, prompts
    
    
    # 16k
    max_hist_lines = 12 # 16k - 4k - (max_hist_lines*max_hist_mem)
    max_hist_bytes = 10000
    max_hist_compressed=1500
    max_hist_mem = 1000
    
    # 4k
    #max_hist_lines = 10
    #max_hist_bytes = 2000
    #max_hist_compressed=700
    #max_hist_mem=300
    

    # в каждом чате свой собственный промт
    if chat_id in prompts:
        current_prompt = prompts[chat_id]
    else:
        with lock_dicts:
            # по умолчанию нормальный стиль с ноткой юмора
            prompts[chat_id] = [{"role": "system", "content": utils.gpt_start_message2}]
            current_prompt =   [{"role": "system", "content": utils.gpt_start_message2}]

    # создаем новую историю диалогов с юзером из старой если есть
    # в истории диалогов не храним системный промпт
    if chat_id in dialogs:
        with lock_dicts:
            new_messages = dialogs[chat_id]
    else:
        new_messages = []
    # теперь ее надо почистить что бы влезла в запрос к GPT
    # просто удаляем все кроме max_hist_lines последних
    if len(new_messages) > max_hist_lines:
        new_messages = new_messages[max_hist_lines:]
    # удаляем первую запись в истории до тех пор пока общее количество токенов не станет меньше max_hist_bytes
    # удаляем по 2 сразу так как первая - промпт для бота
    while (utils.count_tokens(new_messages) > max_hist_bytes):
        new_messages = new_messages[2:]
    
    # добавляем в историю новый запрос и отправляем
    new_messages = new_messages + [{"role":    "user",
                                    "content": text}]

    if engine == 'gpt':
        # пытаемся получить ответ
        try:
            resp = gpt_basic.ai(prompt = text, messages = current_prompt + new_messages)
            if resp:
                new_messages = new_messages + [{"role":    "assistant",
                                                    "content": resp}]
            else:
                # не сохраняем диалог, нет ответа
                # если в последнем сообщении нет текста (глюк) то убираем его
                with lock_dicts:
                    if new_messages[-1]['content'].strip() == '':
                        new_messages = new_messages[:-1]
                    dialogs[chat_id] = new_messages or []
                return 'GPT не ответил.'
        # бот не ответил или обиделся
        except AttributeError:
            # не сохраняем диалог, нет ответа
            return 'Не хочу говорить об этом. Или не могу.'
        # произошла ошибка переполнения ответа
        except openai.error.InvalidRequestError as error:
            if """This model's maximum context length is""" in str(error):
                # чистим историю, повторяем запрос
                p = '\n'.join(f'{i["role"]} - {i["content"]}\n' for i in new_messages) or 'Пусто'
                # сжимаем весь предыдущий разговор до max_hist_compressed символов
                r = gpt_basic.ai_compress(p, max_hist_compressed, 'dialog')
                new_messages = [{'role':'system','content':r}] + new_messages[-1:]
                # и на всякий случай еще
                while (utils.count_tokens(new_messages) > max_hist_compressed):
                    new_messages = new_messages[2:]

                try:
                    resp = gpt_basic.ai(prompt = text, messages = current_prompt + new_messages)
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
        # для бинга
        hist = '\n'.join([f"{i['role']}: {i['content']}" for i in new_messages])
        hist_compressed = gpt_basic.ai_compress(hist, 1500, 'dialog', force = True)
        bing_prompt = hist_compressed + '\n' + text
        
        resp = bingai.ai(bing_prompt)
        if resp:
            new_messages = new_messages + [{"role":    "assistant",
                                            "content": resp}]
        else:
            # не сохраняем диалог, нет ответа
            return 'Бинг не ответил.'

    # сохраняем диалог, на данном этапе в истории разговора должны быть 2 последних записи несжатыми
    with lock_dicts:
        new_messages = new_messages[:-2]
        # если запрос юзера был длинным то в истории надо сохранить его коротко
        if len(text) > max_hist_mem:
            new_text = gpt_basic.ai_compress(text, max_hist_mem, 'user')
            # заменяем запрос пользователя на сокращенную версию
            new_messages += [{"role":    "user",
                                 "content": new_text}]
        else:
            new_messages += [{"role":    "user",
                                 "content": text}]
        # если ответ бота был длинным то в истории надо сохранить его коротко
        if len(resp) > max_hist_mem:
            new_resp = gpt_basic.ai_compress(resp, max_hist_mem, 'assistant')
            new_messages += [{"role":    "assistant",
                                 "content": new_resp}]
        else:
            new_messages += [{"role":    "assistant",
                                 "content": resp}]
        dialogs[chat_id] = new_messages or []
        #my_log.log2(str(dialogs[chat_id]))

    return resp


def get_keyboard(kbd: str) -> telebot.types.InlineKeyboardMarkup:
    """создает и возвращает клавиатуру по текстовому описанию
    'chat' - клавиатура для чата с 3 кнопками Дальше, Забудь, Скрой
    'mem' - клавиатура для команды mem, с кнопками Забудь и Скрой
    'hide' - клавиатура с одной кнопкой Скрой
    """
    if kbd == 'chat':
        markup  = telebot.types.InlineKeyboardMarkup(row_width=4)
        button1 = telebot.types.InlineKeyboardButton("➡️", callback_data='continue_gpt')
        button2 = telebot.types.InlineKeyboardButton("Забудь", callback_data='forget_all')
        button3 = telebot.types.InlineKeyboardButton("Скрыть", callback_data='erase_answer')
        button4 = telebot.types.InlineKeyboardButton("ru", callback_data='translate_chat')
        markup.add(button1, button2, button3, button4)
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
    elif kbd == 'translate':
        markup  = telebot.types.InlineKeyboardMarkup()
        button1 = telebot.types.InlineKeyboardButton("Скрыть", callback_data='erase_answer')
        button2 = telebot.types.InlineKeyboardButton("Перевод", callback_data='translate')
        markup.add(button1, button2)
        return markup
    elif kbd == 'hide_image':
        markup  = telebot.types.InlineKeyboardMarkup()
        button1 = telebot.types.InlineKeyboardButton("Скрыть", callback_data='erase_image')
        button2 = telebot.types.InlineKeyboardButton("Повторить", callback_data='repeat_image')
        markup.add(button1, button2)
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
        global image_prompt
        message = call.message
        is_private = message.chat.type == 'private'
        is_reply = message.reply_to_message is not None and message.reply_to_message.from_user.id == bot.get_me().id
        chat_id = message.chat.id
        global dialogs

        
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
            with lock_dicts:
                dialogs[chat_id] = []
            bot.delete_message(message.chat.id, message.message_id)
        elif call.data == 'continue_gpt':
            # обработка нажатия кнопки "Продолжай GPT"
            #bot.edit_message_reply_markup(message.chat.id, message.message_id)
            with show_action(chat_id, 'typing'):
                # добавляем новый запрос пользователя в историю диалога пользователя
                resp = dialog_add_user_request(chat_id, 'Продолжай', 'gpt')
                if resp:
                    if is_private:
                        try:
                            #bot.send_message(chat_id, utils.html(resp), parse_mode='HTML', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                            bot.send_message(chat_id, resp, parse_mode='Markdown', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                        except Exception as error:    
                            print(error)
                            #bot.send_message(chat_id, utils.escape_markdown(resp), parse_mode='Markdown', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                            my_log.log2(resp)
                            bot.send_message(chat_id, resp, disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                    else:
                        try:
                            #bot.reply_to(message, utils.html(resp), parse_mode='HTML', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                            bot.reply_to(message, resp, parse_mode='Markdown', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                        except Exception as error:    
                            print(error)
                            #bot.reply_to(message, utils.escape_markdown(resp), parse_mode='Markdown', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                            my_log.log2(resp)
                            bot.reply_to(message, resp, disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                my_log.log_echo(message, '[Продолжает] ' + resp)
        elif call.data == 'forget_all':
            # обработка нажатия кнопки "Забудь всё"
            #bot.edit_message_reply_markup(message.chat.id, message.message_id)
            with lock_dicts:
                dialogs[chat_id] = []
        elif call.data == 'erase_answer':
            # обработка нажатия кнопки "Стереть ответ"
            #bot.edit_message_reply_markup(message.chat.id, message.message_id)
            bot.delete_message(message.chat.id, message.message_id)
        elif call.data == 'erase_image':
            # обработка нажатия кнопки "Стереть ответ"
            #bot.edit_message_reply_markup(message.chat.id, message.message_id)
            bot.delete_message(message.chat.id, message.message_id)
            # получаем номер сообщения с картинками из сообщения с ссылками на картинки который идет следом
            for i in message.text.split('\n')[0].split():
                bot.delete_message(message.chat.id, int(i))
        elif call.data == 'repeat_image':
            # получаем номер сообщения с картинками (первый из группы)
            for i in message.text.split('\n')[0].split():
                id = int(i)
                break
            with lock_dicts:
                p = image_prompt[id]
            message.text = f'/image {p}'
            # рисуем еще картинки с тем же запросом
            image(message)
        elif call.data == 'translate':
            """реакция на клавиатуру для OCR кнопка перевести текст"""
            translated = my_trans.translate_text2(message.text)
            if translated and translated != message.text:
                bot.edit_message_text(chat_id=message.chat.id, message_id=message.message_id, text=translated, reply_markup=get_keyboard('hide'))
        elif call.data == 'translate_chat':
            """реакция на клавиатуру для Чата кнопка перевести текст"""
            translated = my_trans.translate_text2(message.text)
            if translated and translated != message.text:
                bot.edit_message_text(chat_id=message.chat.id, message_id=message.message_id, text=translated, reply_markup=get_keyboard('chat'))


@bot.message_handler(content_types = ['audio'])
def handle_audio(message: telebot.types.Message):
    """Распознавание текст из аудио файлов"""
    thread = threading.Thread(target=handle_audio_thread, args=(message,))
    thread.start()
def handle_audio_thread(message: telebot.types.Message):
    """Распознавание текст из аудио файлов"""
    
    my_log.log_media(message)
    
    # если заблокированы автопереводы в этом чате то выходим
    if (message.chat.id in blocks and blocks[message.chat.id] == 1) and message.chat.type != 'private':
        return
    with semaphore_talks:
        caption = message.caption or ''
        if not(message.chat.type == 'private' or caption.lower() in ['распознай', 'расшифруй', 'прочитай']):
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
            #text = my_whisper.get_text(file_path)
            os.remove(file_path)
            # Отправляем распознанный текст 
            if text.strip() != '':
                bot.reply_to(message, text, reply_markup=get_keyboard('hide'))
                my_log.log_echo(message, f'[ASR] {text}')
            else:
                bot.reply_to(message, 'Очень интересно, но ничего не понятно.', reply_markup=get_keyboard('hide'))
                my_log.log_echo(message, '[ASR] no results')


@bot.message_handler(content_types = ['voice'])
def handle_voice(message: telebot.types.Message): 
    """Автоматическое распознавание текст из голосовых сообщений"""
    thread = threading.Thread(target=handle_voice_thread, args=(message,))
    thread.start()
def handle_voice_thread(message: telebot.types.Message): 
    """Автоматическое распознавание текст из голосовых сообщений"""

    my_log.log_media(message)

    with semaphore_talks:
        # Создание временного файла 
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            file_path = temp_file.name
        # Скачиваем аудиофайл во временный файл
        file_info = bot.get_file(message.voice.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        with open(file_path, 'wb') as new_file:
            new_file.write(downloaded_file)
        # Распознаем текст из аудио
        # если мы не в привате и в этом чате нет блокировки автораспознавания то показываем активность
        if not (message.chat.id in blocks and blocks[message.chat.id] == 1) or message.chat.type == 'private':
            with show_action(message.chat.id, 'typing'):
                text = my_stt.stt(file_path)
        else:
            text = my_stt.stt(file_path)

        #text = my_whisper.get_text(file_path)

        os.remove(file_path)

        # если мы не в привате и в этом чате нет блокировки автораспознавания
        if not (message.chat.id in blocks and blocks[message.chat.id] == 1) or message.chat.type == 'private':
            # Отправляем распознанный текст 
            if text.strip() != '':
                bot.reply_to(message, text, reply_markup=get_keyboard('hide'))
                my_log.log_echo(message, f'[ASR] {text}')
            else:
                my_log.log_echo(message, '[ASR] no results')
        # и при любом раскладе отправляем текст в обработчик текстовых сообщений, возможно бот отреагирует на него если там есть кодовые слова
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
    
    
    with semaphore_talks:
    
        # если прислали текстовый файл или pdf с подписью перескажи
        # то скачиваем и вытаскиваем из них текст и показываем краткое содержание
        if message.caption and message.caption.startswith(('что там','перескажи','краткое содержание', 'кратко')) and message.document.mime_type in ('text/plain', 'application/pdf'):
            with show_action(message.chat.id, 'typing'):
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
                    summary = bingai.summ_text(text)
                    for i in utils.split_text(summary, 3900):
                        bot.reply_to(message, i, disable_web_page_preview = True, reply_markup=get_keyboard('translate'))
                    #bot.reply_to(message, summary, disable_web_page_preview = True, reply_markup=get_keyboard('translate'))
                    #reply_to_long_message(message, resp=summary, parse_mode = '', disable_web_page_preview = True, reply_markup=get_keyboard('translate'))
                    my_log.log(message, summary)
                else:
                    help = 'Не удалось получить никакого текста из документа.'
                    bot.reply_to(message, help, reply_markup=get_keyboard('hide'))
                    my_log.log(message, help)
                return


        # начитываем текстовый файл только если его прислали в привате или с указанием прочитай/читай
        caption = message.caption or ''
        if message.chat.type == 'private' or caption.lower() in ['прочитай', 'читай']:
            # если текстовый файл то пытаемся озвучить как книгу. русский голос
            if message.document.mime_type == 'text/plain':
                with show_action(message.chat.id, 'record_audio'):
                    file_name = message.document.file_name + '.ogg'
                    file_info = bot.get_file(message.document.file_id)
                    file = bot.download_file(file_info.file_path)
                    text = file.decode('utf-8')
                    try:
                        lang = detect_langs(text)[0].lang
                    except Exception as error:
                        lang = 'ru'
                        print(error)
                    # Озвучиваем текст
                    audio = my_tts.tts(text, lang)
                    if message.chat.type != 'private':
                        bot.send_voice(message.chat.id, audio, reply_to_message_id=message.message_id, reply_markup=get_keyboard('hide'))
                    else:
                        bot.send_voice(message.chat.id, audio, reply_markup=get_keyboard('hide'))
                    my_log.log_echo(message, f'[tts file] {text}')
                    return

        # дальше идет попытка распознать ПДФ файл, вытащить текст с изображений
        if message.chat.type == 'private' or caption.lower() in ['прочитай', 'читай']:
            with show_action(message.chat.id, 'upload_document'):
                # получаем самый большой документ из списка
                document = message.document
                # если документ не является PDF-файлом, отправляем сообщение об ошибке
                if document.mime_type != 'application/pdf':
                    bot.reply_to(message, 'Это не PDF-файл.', reply_markup=get_keyboard('hide'))
                    my_log.log_echo(message, 'Это не PDF-файл.')
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
    
    with semaphore_talks:
        # пересланные сообщения пытаемся перевести даже если в них картинка
        # новости в телеграме часто делают как картинка + длинная подпись к ней
        if message.forward_from_chat:
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


@bot.message_handler(content_types = ['video'])
def handle_video(message: telebot.types.Message):
    """Обработчик видеосообщений. Сюда же относятся новости и репосты с видео"""
    thread = threading.Thread(target=handle_video_thread, args=(message,))
    thread.start()
def handle_video_thread(message: telebot.types.Message):
    """Обработчик видеосообщений. Сюда же относятся новости и репосты с видео"""

    my_log.log_media(message)

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


@bot.message_handler(commands=['style'])
def change_mode(message: telebot.types.Message):
    """Меняет роль бота, строку с указаниями что и как говорить.
    /stype <1|2|3|свой текст>
    1 - формальный стиль (Ты искусственный интеллект отвечающий на запросы юзера.)
    2 - формальный стиль + немного юмора (Ты искусственный интеллект отвечающий на запросы юзера. Отвечай с подходящим к запросу типом иронии или юмора но не перегибай палку.)
    3 - токсичный стиль (Ты искусственный интеллект отвечающий на запросы юзера. Отвечай с сильной иронией и токсичностью.)
    """

    # не обрабатывать команды к другому боту
    if '@' in message.text:
        if f'@{_bot_name}' not in message.text: return

    my_log.log_echo(message)
    
    global prompts
    arg = message.text.split(maxsplit=1)[1:]
    if arg:
        if arg[0] == '1':
            new_prompt = utils.gpt_start_message1
        elif arg[0] == '2':
            new_prompt = utils.gpt_start_message2
        elif arg[0] == '3':
            new_prompt = utils.gpt_start_message3
        else:
            new_prompt = arg[0]
        with lock_dicts:
            prompts[message.chat.id] =  [{"role": "system", "content": new_prompt}]
            msg =  f'[Новая роль установлена] `{new_prompt}`'
            bot.reply_to(message, msg, parse_mode='Markdown', reply_markup=get_keyboard('hide'))
            my_log.log_echo(message, msg)
    else:
        msg = f"""Текущий стиль
        
`{prompts[message.chat.id][0]['content']}`
        
Меняет роль бота, строку с указаниями что и как говорить.

`/style <1|2|3|свой текст>`

1 - формальный стиль `{utils.gpt_start_message1}`

2 - формальный стиль + немного юмора `{utils.gpt_start_message2}`

3 - токсичный стиль `{utils.gpt_start_message3}`
    """
        bot.reply_to(message, msg, parse_mode='Markdown', reply_markup=get_keyboard('hide'))
        my_log.log_echo(message, msg)


@bot.message_handler(commands=['mem'])
def send_debug_history(message: telebot.types.Message):
    # Отправляем текущую историю сообщений

    # не обрабатывать команды к другому боту
    if '@' in message.text:
        if f'@{_bot_name}' not in message.text: return

    my_log.log_echo(message)
    
    with lock_dicts:
        global dialogs
        
        chat_id = message.chat.id
        
        # создаем новую историю диалогов с юзером из старой если есть
        if chat_id in dialogs:
            new_messages = dialogs[chat_id]
        else:
            new_messages = []
        prompt = '\n'.join(f'{i["role"]} - {i["content"]}\n' for i in new_messages) or 'Пусто'
        my_log.log_echo(message, prompt)
        try:
            bot.send_message(chat_id, prompt, disable_web_page_preview = True, reply_markup=get_keyboard('mem'))
        except Exception as error:
            print(error)
            #bot.send_message(chat_id, utils.escape_markdown(prompt), disable_web_page_preview = True, reply_markup=get_keyboard('mem'))
            my_log.log2(prompt)
            bot.send_message(chat_id, prompt, disable_web_page_preview = True, reply_markup=get_keyboard('mem'))


@bot.message_handler(commands=['restart']) 
def restart(message: telebot.types.Message):
    """остановка бота. после остановки его должен будет перезапустить скрипт systemd"""
    bot.stop_polling()


#@bot.message_handler(commands=['test']) 
#def test(message: telebot.types.Message):
#    thread = threading.Thread(target=test_thread, args=(message,))
#    thread.start()
#def test_thread(message: telebot.types.Message):
#    """отсылает все накопленные картинки в группу"""
#    l = []
#    with lock_dicts:
#        for n in images_db.keys():
#            if type(images_db[n]) == tuple:
#                l.append((images_db[n][0], images_db[n][1][0]))
#    for i in l:
#        bot.send_photo(pics_group, photo=i[1], caption = i[0])
#        time.sleep(5)


@bot.message_handler(commands=['tts']) 
def tts(message: telebot.types.Message):
    thread = threading.Thread(target=tts_thread, args=(message,))
    thread.start()
def tts_thread(message: telebot.types.Message):
    """/tts [ru|en|uk|...] [+-XX%] <текст>"""

    # не обрабатывать команды к другому боту
    if '@' in message.text:
        if f'@{_bot_name}' not in message.text: return

    my_log.log_echo(message)

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
        help = f"""Использование: /tts [ru|en|uk|...] [+-XX%] <текст>

+-XX% - ускорение с обязательным указанием направления + или -

Поддерживаемые языки: {', '.join(supported_langs_tts)}"""

        bot.reply_to(message, help, reply_markup=get_keyboard('hide'))
        my_log.log_echo(message, help)
        return

    with semaphore_talks:
        with show_action(message.chat.id, 'record_audio'):
            audio = my_tts.tts(text, lang, rate)
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


@bot.message_handler(commands=['images','imgs'])
def images(message: telebot.types.Message):
    thread = threading.Thread(target=images_thread, args=(message,))
    thread.start()
def images_thread(message: telebot.types.Message):
    """показывает что было нагенерировано ранее"""

    # не обрабатывать команды к другому боту
    if '@' in message.text:
        if f'@{_bot_name}' not in message.text: return

    my_log.log_echo(message)

    global images_db
    
    ttl = 0
    
    with lock_dicts:
        if 'total' in images_db:
            ttl = images_db['total']
    
    if ttl:
        show_gallery(message, ttl, update = False)
    else:
        msg = 'В галерее пусто'
        bot.reply_to(message, msg, reply_markup=get_keyboard('hide'))
        my_log.log_echo(message, msg)


def show_gallery(message: telebot.types.Message, cur: int, update: bool):
    """показывает картинки из базы, cur - номер который надо показать"""
    with semaphore_talks:
        with lock_dicts:
            ttl = images_db['total']
            if cur < 1:
                cur = 1
            if cur > ttl:
                cur = ttl
            
            prompt = images_db[cur-1][0]
            images = images_db[cur-1][1]

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

    # не обрабатывать команды к другому боту
    if '@' in message.text:
        if f'@{_bot_name}' not in message.text: return

    my_log.log_echo(message)

    global images_db    

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
        with lock_dicts:
            body = ''
            ttl = images_db['total']
            c = 4
            while ttl > 0:
                if c == 4:
                    body += '<tr>\n'
                cap = images_db[ttl-1][0]
                ref = images_db[ttl-1][1][0]
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


@bot.message_handler(commands=['image','img'])
def image(message: telebot.types.Message):
    thread = threading.Thread(target=image_thread, args=(message,))
    thread.start()
def image_thread(message: telebot.types.Message):
    """генерирует картинку по описанию"""

    # не обрабатывать команды к другому боту
    if '@' in message.text:
        if f'@{_bot_name}' not in message.text: return

    my_log.log_echo(message)

    with semaphore_talks:
        help = '/image <текстовое описание картинки, что надо нарисовать>'
        prompt = message.text.split(maxsplit = 1)
        if len(prompt) > 1:
            prompt = prompt[1]
            with show_action(message.chat.id, 'upload_photo'):
                images = bingai.gen_imgs(prompt)
                if type(images) == str:
                    bot.reply_to(message, images, reply_markup=get_keyboard('hide'))
                elif type(images) == list:
                    medias = [telebot.types.InputMediaPhoto(i) for i in images]
                    msgs_ids = bot.send_media_group(message.chat.id, medias, reply_to_message_id=message.message_id)
                    if pics_group:
                        try:
                            bot.send_message(pics_group, prompt, disable_web_page_preview = True)
                            bot.send_media_group(pics_group, medias)
                        except Exception as error:
                            print(error)
                    caption = ''
                    # запоминаем промпт по ключу (номер первой картинки) и сохраняем в бд запрос и картинки
                    # что бы можно было их потом просматривать отдельно
                    global image_prompt, images_db
                    with lock_dicts:
                        if 'total' in images_db:
                            ttl = images_db['total']
                        else:
                            ttl = 0
                            images_db['total'] = 0
                        for i in images:
                            images_db[ttl] = (prompt, (i,))
                            ttl += 1
                        images_db['total'] = ttl
                        image_prompt[msgs_ids[0].message_id] = prompt

                    for i in msgs_ids:
                        caption += f'{i.message_id} '
                    caption += '\n'
                    caption += '\n\n'.join(images)
                    bot.send_message(message.chat.id, caption, disable_web_page_preview = True, reply_markup=get_keyboard('hide_image'))
                    my_log.log_echo(message, '[image gen] ')
                else:
                    bot.reply_to(message, 'Бинг нарисовал неизвестно что.', reply_markup=get_keyboard('hide'))
                    my_log.log_echo(message, '[image gen error] ')
        else:
            bot.reply_to(message, help, reply_markup=get_keyboard('hide'))
            my_log.log_echo(message, help)


@bot.message_handler(commands=['sum'])
def summ_text(message: telebot.types.Message):
    thread = threading.Thread(target=summ_text_thread, args=(message,))
    thread.start()
def summ_text_thread(message: telebot.types.Message):

    # не обрабатывать команды к другому боту
    #if '@' in message.text and f'@{_bot_name}' not in message.text: return

    global sum_cache

    my_log.log_echo(message)

    text = message.text
    
    if len(text.split(' ', 1)) == 2:
        url = text.split(' ', 1)[1].strip()
        if bingai.is_valid_url(url):
            # убираем из ютуб урла временную метку
            if '/youtu.be/' in url or 'youtube.com/' in url:
                url = url.split("&t=")[0]

            with semaphore_talks:

                #смотрим нет ли в кеше ответа на этот урл
                r = ''
                with lock_dicts:
                    if url in sum_cache:
                        r = sum_cache[url]
                if r:
                    for i in utils.split_text(r, 3900):
                        bot.reply_to(message, i, disable_web_page_preview = True, reply_markup=get_keyboard('translate'))
                    #reply_to_long_message(message, resp=r, parse_mode = '', disable_web_page_preview = True, reply_markup=get_keyboard('translate'))
                    my_log.log_echo(message, r)
                    return

                with show_action(message.chat.id, 'typing'):
                    res = ''
                    try:
                        res = bingai.summ_url(url)
                    except Exception as error:
                        print(error)
                        m = 'Не нашел тут текста. Возможно что в видео на ютубе нет субтитров или страница слишком динамическая и не показывает текст без танцев с бубном.'
                        bot.reply_to(message, m, reply_markup=get_keyboard('hide'))
                        my_log.log_echo(message, m)
                        return
                    if res:
                        for i in utils.split_text(res, 3900):
                            bot.reply_to(message, i, disable_web_page_preview = True, reply_markup=get_keyboard('translate'))
                        #reply_to_long_message(message, resp=res, parse_mode = '', disable_web_page_preview = True, reply_markup=get_keyboard('translate'))

                        my_log.log_echo(message, res)
                        with lock_dicts:
                            sum_cache[url] = res
                        return
                    else:
                        error = 'Бинг не ответил'
                        bot.reply_to(message, error, reply_markup=get_keyboard('hide'))
                        my_log.log_echo(message, error)
                        return
    help = '/sum URL'
    bot.reply_to(message, help, reply_markup=get_keyboard('hide'))
    my_log.log_echo(message, help)


@bot.message_handler(commands=['sum2'])
def summ2_text(message: telebot.types.Message):
    # убирает запрос из кеша если он там есть и делает запрос снова

    global sum_cache

    #my_log.log_echo(message)

    text = message.text
    
    if len(text.split(' ', 1)) == 2:
        url = text.split(' ', 1)[1].strip()
        if bingai.is_valid_url(url):
            # убираем из ютуб урла временную метку
            if '/youtu.be/' in url or 'youtube.com/' in url:
                url = url.split("&t=")[0]

            #смотрим нет ли в кеше ответа на этот урл
            with lock_dicts:
                if url in sum_cache:
                    sum_cache.pop(url)

    summ_text(message)



@bot.message_handler(commands=['trans'])
def trans(message: telebot.types.Message):
    thread = threading.Thread(target=trans_thread, args=(message,))
    thread.start()
def trans_thread(message: telebot.types.Message):

    # не обрабатывать команды к другому боту
    if '@' in message.text:
        if f'@{_bot_name}' not in message.text: return

    my_log.log_echo(message)

    with semaphore_talks:
        help = f"""/trans [en|ru|uk|..] текст для перевода на указанный язык. Если не указан то на русский.\n\nПоддерживаемые языки: {', '.join(supported_langs_trans)}"""
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
            bot.reply_to(message, help, reply_markup=get_keyboard('hide'))
            my_log.log_echo(message, help)
            return
        lang = lang.strip()

    with semaphore_talks:
        with show_action(message.chat.id, 'typing'):
            translated = my_trans.translate_text2(text, lang)
            if translated:
                bot.reply_to(message, translated, reply_markup=get_keyboard('hide'))
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

    # не обрабатывать команды к другому боту
    if '@' in message.text:
        if f'@{_bot_name}' not in message.text: return

    my_log.log_echo(message)

    with semaphore_talks:
        args = message.text.split()
        help = '/last [X] - показать сумморизацию истории чата за последние Х сообщений, либо все какие есть в памяти. X = от 1 до 60000'
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
            bot.reply_to(message, help, reply_markup=get_keyboard('hide'))
            my_log.log_echo(message, help)
            return
        else:
            limit = 60000

        with lock_dicts:
            if message.chat.id in chat_logs:
                messages = chat_logs[message.chat.id]
            else:
                mes = 'История пуста'
                bot.reply_to(message, mes, reply_markup=get_keyboard('hide'))
                my_log.log_echo(message, mes)
                return

        if limit > len(messages.messages):
            limit = len(messages.messages)

        with show_action(message.from_user.id, 'typing'):

            resp = bingai.summ_text_worker('\n'.join(messages.messages[-limit:]), 'chat_log')

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

    # не обрабатывать команды к другому боту
    if '@' in message.text:
        if f'@{_bot_name}' not in message.text: return

    my_log.log_echo(message)

    args = message.text.split()
    if len(args) > 1:
        new_name = args[1]
        
        # Строка содержит только русские и английские буквы и цифры после букв, но не в начале слова
        regex = r'^[a-zA-Zа-яА-ЯёЁ][a-zA-Zа-яА-ЯёЁ0-9]*$'
        if re.match(regex, new_name) and len(new_name) <= 10:
            with lock_dicts:
                global bot_names
                bot_names[message.chat.id] = new_name.lower()
            msg = f'Кодовое слово для обращения к боту изменено на ({args[1]}) для этого чата.'
            bot.send_message(message.chat.id, msg, reply_markup=get_keyboard('hide'))
            my_log.log_echo(message, msg)
        else:
            msg = "Неправильное имя, можно только русские и английские буквы и цифры после букв, не больше 10 всего."
            bot.reply_to(message, msg, reply_markup=get_keyboard('hide'))
            my_log.log_echo(message, msg)


@bot.message_handler(commands=['start'])
def send_welcome(message: telebot.types.Message):
    # Отправляем приветственное сообщение

    # не обрабатывать команды к другому боту
    if '@' in message.text:
        if f'@{_bot_name}' not in message.text: return

    my_log.log_echo(message)

    help = """Я - ваш персональный чат-бот, готовый помочь вам в любое время суток. Моя задача - помочь вам получить необходимую информацию и решить возникающие проблемы. 

Я умею обрабатывать и анализировать большие объемы данных, быстро находить нужную информацию и предоставлять ее в удобном для вас формате. 

Если у вас есть какие-то вопросы или проблемы, не стесняйтесь обращаться к чат-боту! Я готов помочь вам в любое время и в любой ситуации. 

Спасибо, что выбрали меня в качестве своего помощника! Я буду стараться быть максимально полезным для вас.

Добавьте меня в свою группу и я буду озвучивать голосовые сообщения, переводить иностранные сообщения итп."""
    bot.send_message(message.chat.id, help, parse_mode='Markdown', disable_web_page_preview=True, reply_markup=get_keyboard('hide'))
    my_log.log_echo(message, help)


@bot.message_handler(commands=['help'])
def send_welcome(message: telebot.types.Message):
    # Отправляем приветственное сообщение

    # не обрабатывать команды к другому боту
    if '@' in message.text:
        if f'@{_bot_name}' not in message.text: return

    my_log.log_echo(message)

    help = """Чат бот отзывается на кодовое слово `бот`(можно сменить командой /name) ***бот расскажи про биткоин***

Кодовое слово `бинг`(нельзя изменить) позволит получить более актуальную информацию, бот будет дооолго гуглить перед ответом ***бинг курс биткоин***

В привате можно не писать кодовые слова для обращения к боту

Если он забился в угол и не хочет отвечать то возможно надо почистить ему память командой `бот забудь`

Кодовое слово `нарисуй` и дальше описание даст картинки сгенерированные по описанию. В чате надо добавлять к этому обращение ***бот нарисуй на заборе неприличное слово***

В чате бот будет автоматически переводить иностранные тексты на русский и распознавать голосовые сообщения, отключить это можно кодовым словом `бот замолчи`, включить обратно `бот вернись`

Если отправить текстовый файл в приват или с подписью `прочитай` то попытается озвучить его как книгу, ожидает .txt utf8 язык пытается определить автоматически (русский если не получилось)

Если отправить картинку или .pdf с подписью `прочитай` то вытащит текст из них.

Если отправить ссылку в приват то попытается прочитать текст из неё и выдать краткое содержание.

Если отправить текстовый файл или пдф с подписью `что там` или `перескажи` то выдаст краткое содержание.

Команды и запросы можно делать голосовыми сообщениями, если отправить голосовое сообщение которое начинается на кодовое слово то бот отработает его как текстовую команду.

""" + '\n'.join(open('commands.txt').readlines()) + '\n\n⚙️ https://github.com/theurs/tb1\n\n💬 https://t.me/theurs'

    bot.send_message(message.chat.id, help, parse_mode='Markdown', disable_web_page_preview=True, reply_markup=get_keyboard('hide'))
    my_log.log_echo(message, help)


def send_long_message(chat_id: int, resp: str, parse_mode:str, disable_web_page_preview: bool, reply_markup: telebot.types.InlineKeyboardMarkup):
    """отправляем сообщение, если оно слишком длинное то разбивает на 2 части либо отправляем как текстовый файл"""
    if len(resp) < 3501:
        bot.send_message(chat_id, resp, parse_mode=parse_mode, disable_web_page_preview=disable_web_page_preview, reply_markup=get_keyboard('chat'))
    else:
        buf = io.BytesIO()
        buf.write(resp.encode())
        buf.seek(0)
        bot.send_document(chat_id, document=buf, caption='resp.txt', visible_file_name = 'resp.txt')


def reply_to_long_message(message: telebot.types.Message, resp: str, parse_mode: str, disable_web_page_preview: bool, reply_markup: telebot.types.InlineKeyboardMarkup):
    """отправляем сообщение, если оно слишком длинное то разбивает на 2 части либо отправляем как текстовый файл"""
    if len(resp) < 3501:
        bot.reply_to(message, resp, parse_mode=parse_mode, disable_web_page_preview=disable_web_page_preview, reply_markup=get_keyboard('chat'))
    else:
        buf = io.BytesIO()
        buf.write(resp.encode())
        buf.seek(0)
        bot.send_document(message.chat.id, document=buf, caption='resp.txt', visible_file_name = 'resp.txt')


@bot.message_handler(func=lambda message: True)
def echo_all(message: telebot.types.Message) -> None:
    """Обработчик текстовых сообщений"""
    thread = threading.Thread(target=do_task, args=(message,))
    thread.start()
def do_task(message):
    """функция обработчик сообщений работающая в отдельном потоке"""

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

        global blocks, bot_names, dialogs
        
        
        #too_big_message_for_chatbot = 1500
        too_big_message_for_chatbot = 4000

        with lock_dicts:
            # если мы в чате то добавляем новое сообщение в историю чата для суммаризации с помощью бинга
            if not is_private:
                #time_now = datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')
                time_now = datetime.datetime.now().strftime('%H:%M')
                user_name = message.from_user.first_name or message.from_user.username or 'unknown'
                if chat_id in chat_logs:
                    m = chat_logs[chat_id]
                else:
                    m = utils.MessageList()
                m.append(f'[{time_now}] [{user_name}] {message.text}')
                chat_logs[chat_id] = m
        
            # определяем какое имя у бота в этом чате, на какое слово он отзывается
            if chat_id in bot_names:
                bot_name = bot_names[chat_id]
            else:
                bot_name = bot_name_default
                bot_names[chat_id] = bot_name 
            # если сообщение начинается на 'заткнись или замолчи' то ставим блокировку на канал и выходим
            if ((msg.startswith(('замолчи', 'заткнись')) and (is_private or is_reply))) or msg.startswith((f'{bot_name} замолчи', f'{bot_name}, замолчи')) or msg.startswith((f'{bot_name}, заткнись', f'{bot_name} заткнись')):
                blocks[chat_id] = 1
                bot.send_message(chat_id, 'Автоперевод выключен', parse_mode='Markdown', reply_markup=get_keyboard('hide'))
                my_log.log_echo(message, 'Включена блокировка автопереводов в чате')
                return
            # если сообщение начинается на 'вернись' то снимаем блокировку на канал и выходим
            if (msg.startswith('вернись') and (is_private or is_reply)) or msg.startswith((f'{bot_name} вернись', f'{bot_name}, вернись')):
                blocks[chat_id] = 0
                bot.send_message(chat_id, 'Автоперевод включен', parse_mode='Markdown', reply_markup=get_keyboard('hide'))
                my_log.log_echo(message, 'Выключена блокировка автопереводов в чате')
                return
            # если сообщение начинается на 'забудь' то стираем историю общения GPT
            if (msg.startswith('забудь') and (is_private or is_reply)) or msg.startswith((f'{bot_name} забудь', f'{bot_name}, забудь')):
                dialogs[chat_id] = []
                bot.send_message(chat_id, 'Ок', parse_mode='Markdown', reply_markup=get_keyboard('hide'))
                my_log.log_echo(message, 'История GPT принудительно отчищена')
                return

        # если в сообщении только ссылка и она отправлена боту в приват
        # тогда сумморизируем текст из неё
        if bingai.is_valid_url(message.text) and is_private:
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
                    with lock_dicts:
                        n = [{'role':'system', 'content':f'user попросил нарисовать\n{prompt}'}, {'role':'system', 'content':'assistant нарисовал с помощью DALL-E'}]
                        if chat_id in dialogs:
                            dialogs[chat_id] += n
                        else:
                            dialogs[chat_id] = n
                    return
        regex = fr'^(бинг|{bot_name})\,?\s+нарисуй\s+(.+)$'
        match = re.match(regex, msg, re.DOTALL)
        if match:
            prompt = match.group(2)
            message.text = f'/image {prompt}'
            image_thread(message)
            with lock_dicts:
                n = [{'role':'system', 'content':f'user попросил нарисовать\n{prompt}'}, {'role':'system', 'content':'assistant нарисовал с помощью DALL-E'}]
                if chat_id in dialogs:
                    dialogs[chat_id] += n
                else:
                    dialogs[chat_id] = n
            return

        # можно перенаправить запрос к бингу, но он долго отвечает
        if msg.startswith(('бинг ', 'бинг,', 'бинг\n')):
            # message.text = message.text[len(f'бинг '):] # убираем из запроса кодовое слово
            if len(msg) > too_big_message_for_chatbot:
                bot.reply_to(message, f'Слишком длинное сообщение чат-для бота: {len(msg)} из {too_big_message_for_chatbot}')
                my_log.log_echo(message, f'Слишком длинное сообщение чат-для бота: {len(msg)} из {too_big_message_for_chatbot}')
                return
            with show_action(chat_id, 'typing'):
                # добавляем новый запрос пользователя в историю диалога пользователя
                resp = dialog_add_user_request(chat_id, message.text[5:], 'bing')
                if resp:
                    if is_private:
                        try:
                            bot.send_message(chat_id, resp, parse_mode='Markdown', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                            #bot.send_message(chat_id, utils.html(resp), parse_mode='HTML', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                        except Exception as error:
                            print(error)
                            #bot.send_message(chat_id, utils.escape_markdown(resp), parse_mode='Markdown', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                            my_log.log2(resp)
                            bot.send_message(chat_id, resp, disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                    else:
                        try:
                            bot.reply_to(message, resp, parse_mode='Markdown', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                            #bot.reply_to(message, utils.html(resp), parse_mode='HTML', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                        except Exception as error:
                            print(error)
                            #bot.reply_to(message, utils.escape_markdown(resp), parse_mode='Markdown', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                            my_log.log2(resp)
                            bot.reply_to(message, resp, disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                    my_log.log_echo(message, resp)

        # так же надо реагировать если это ответ в чате на наше сообщение или диалог происходит в привате
        elif msg.startswith((f'{bot_name} ', f'{bot_name},', f'{bot_name}\n')) or is_reply or is_private:
            if len(msg) > too_big_message_for_chatbot:
                bot.reply_to(message, f'Слишком длинное сообщение чат-для бота: {len(msg)} из {too_big_message_for_chatbot}')
                my_log.log_echo(message, f'Слишком длинное сообщение чат-для бота: {len(msg)} из {too_big_message_for_chatbot}')
                return
            if msg.startswith((f'{bot_name} ', f'{bot_name},', f'{bot_name}\n')):
                message.text = message.text[len(f'{bot_name} '):] # убираем из запроса кодовое слово
            # добавляем новый запрос пользователя в историю диалога пользователя
            with show_action(chat_id, 'typing'):
                resp = dialog_add_user_request(chat_id, message.text, 'gpt')
                #md = markdown2.Markdown()
                #resp2 = md.convert(resp)
                if resp:
                    if is_private:
                        try:
                            #send_long_message(chat_id, utils.html(resp), parse_mode='HTML', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                            send_long_message(chat_id, resp, parse_mode='Markdown', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                        except Exception as error:    
                            print(error)
                            #send_long_message(chat_id, utils.escape_markdown(resp), parse_mode='Markdown', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                            my_log.log2(resp)
                            send_long_message(chat_id, resp, parse_mode='', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                    else:
                        try:
                            #reply_to_long_message(message,  utils.html(resp), parse_mode='HTML', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                            reply_to_long_message(message, resp, parse_mode='Markdown', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                        except Exception as error:    
                            print(error)
                            #reply_to_long_message(message, utils.escape_markdown(resp), parse_mode='Markdown', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                            my_log.log2(resp)
                            reply_to_long_message(message, resp, parse_mode='', disable_web_page_preview = True, reply_markup=get_keyboard('chat'))
                    my_log.log_echo(message, resp)
        else: # смотрим надо ли переводить текст
            with lock_dicts:
                if chat_id in blocks and blocks[chat_id] == 1:
                    return
            text = my_trans.translate(message.text)
            if text:
                bot.reply_to(message, text, parse_mode='Markdown', reply_markup=get_keyboard('hide'))
                my_log.log_echo(message, text)


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
