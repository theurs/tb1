#!/usr/bin/env python3


import glob
import os
import datetime
import telebot
import threading


lock = threading.Lock()


if not os.path.exists('logs'):
    os.mkdir('logs')
if not os.path.exists('logs2'):
    os.mkdir('logs2')


def log2(text: str) -> None:
    """для дебага"""
    global lock
    with lock:
        time_now = datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')
        log_file_path = 'logs/debug.log'
        open(log_file_path, 'a', encoding="utf-8").write(f'{time_now}\n\n{text}\n{"=" * 80}\n')
        open(log_file_path.replace('logs/', 'logs2/', 1), 'a', encoding="utf-8").write(f'{time_now}\n\n{text}\n{"=" * 80}\n')


def log_echo(message: telebot.types.Message, reply_from_bot: str = '', debug: bool = False) -> None:
    """записывает в журнал сообщение полученное обработчиком обычных сообщений либо ответ бота"""
    global lock
    time_now = datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')
    private_or_chat = 'private' if message.chat.type == 'private' else 'chat'
    chat_name = message.chat.username or message.chat.first_name or message.chat.title or ''
    user_name = message.from_user.first_name or message.from_user.username or ''
    chat_name = chat_name.replace('/', '⁄')
    user_name = user_name.replace('/', '⁄')

    logname = f'logs/[{chat_name}] [{private_or_chat}] [{message.chat.type}] [{message.chat.id}].log'.replace('[private] [private]', '[private]').replace('[chat] [supergroup]', '[chat]')

    topic_id = 0

    if message.reply_to_message and message.reply_to_message.is_topic_message:
        topic_id = message.reply_to_message.message_thread_id
    elif message.is_topic_message:
        topic_id = message.message_thread_id

    log_file_path = logname
    
    if debug:
        log_file_path = log_file_path + '.debug.log'

    if topic_id:
        log_file_path = log_file_path[:-4] + f' [{topic_id}].log'

    with lock:
        with open(log_file_path, 'a', encoding="utf-8") as log_file:
            if reply_from_bot:
                log_file.write(f"[{time_now}] [BOT]: {reply_from_bot}\n")
            else:
                log_file.write(f"[{time_now}] [{user_name}]: {message.text or message.caption or ''}\n")
        with open(log_file_path.replace('logs/', 'logs2/', 1), 'a', encoding="utf-8") as log_file:
            if reply_from_bot:
                log_file.write(f"[{time_now}] [BOT]: {reply_from_bot}\n")
            else:
                log_file.write(f"[{time_now}] [{user_name}]: {message.text or message.caption or ''}\n")



def log_media(message: telebot.types.Message) -> None:
    """записывает в журнал сообщение полученное обработчиком медиа файлов"""
    global lock
    time_now = datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')
    private_or_chat = 'private' if message.chat.type == 'private' else 'chat'
    chat_name = message.chat.username or message.chat.first_name or message.chat.title or ''
    user_name = message.from_user.first_name or message.from_user.username or ''
    chat_name = chat_name.replace('/', '⁄')
    user_name = user_name.replace('/', '⁄')

    caption = message.caption or ''

    logname = f'logs/[{chat_name}] [{private_or_chat}] [{message.chat.type}] [{message.chat.id}].log'.replace('[private] [private]', '[private]').replace('[chat] [supergroup]', '[chat]')

    topic_id = 0

    if message.reply_to_message and message.reply_to_message.is_topic_message:
        topic_id = message.reply_to_message.message_thread_id
    elif message.is_topic_message:
        topic_id = message.message_thread_id

    log_file_path = logname

    if topic_id:
        log_file_path = log_file_path[:-4] + f' [{topic_id}].log'

    if message.audio:
        file_name = message.audio.file_name
        file_size = message.audio.file_size
        file_duration = message.audio.duration
        file_title = message.audio.title
        file_mime_type = message.audio.mime_type
        with lock:
            with open(log_file_path, 'a', encoding="utf-8") as log_file:
                log_file.write(f"[{time_now}] [{user_name}]: [Отправил аудио файл] [caption: {caption}] [title: {file_title}] \
[filename: {file_name}] [filesize: {file_size}] [duration: {file_duration}] [mime type: {file_mime_type}]\n")
            with open(log_file_path.replace('logs/', 'logs2/', 1), 'a', encoding="utf-8") as log_file:
                log_file.write(f"[{time_now}] [{user_name}]: [Отправил аудио файл] [caption: {caption}] [title: {file_title}] \
[filename: {file_name}] [filesize: {file_size}] [duration: {file_duration}] [mime type: {file_mime_type}]\n")

    if message.voice:
        file_size = message.voice.file_size
        file_duration = message.voice.duration
        with lock:
            with open(log_file_path, 'a', encoding="utf-8") as log_file:
                log_file.write(f"[{time_now}] [{user_name}]: [Отправил голосовое сообщение] [filesize: \
{file_size}] [duration: {file_duration}]\n")
            with open(log_file_path.replace('logs/', 'logs2/', 1), 'a', encoding="utf-8") as log_file:
                log_file.write(f"[{time_now}] [{user_name}]: [Отправил голосовое сообщение] [filesize: \
{file_size}] [duration: {file_duration}]\n")

    if message.document:
        file_name = message.document.file_name
        file_size = message.document.file_size
        file_mime_type = message.document.mime_type
        with lock:
            with open(log_file_path, 'a', encoding="utf-8") as log_file:
                log_file.write(f"[{time_now}] [{user_name}]: [Отправил документ] [caption: {caption}] \
[filename: {file_name}] [filesize: {file_size}] [mime type: {file_mime_type}]\n")
            with open(log_file_path.replace('logs/', 'logs2/', 1), 'a', encoding="utf-8") as log_file:
                log_file.write(f"[{time_now}] [{user_name}]: [Отправил документ] [caption: {caption}] \
[filename: {file_name}] [filesize: {file_size}] [mime type: {file_mime_type}]\n")

    if message.photo or message.video:
        with lock:
            with open(log_file_path, 'a', encoding="utf-8") as log_file:
                log_file.write(f"[{time_now}] [{user_name}]: [Отправил фото] [caption]: {caption}\n")
        with lock:
            with open(log_file_path.replace('logs/', 'logs2/', 1), 'a', encoding="utf-8") as log_file:
                log_file.write(f"[{time_now}] [{user_name}]: [Отправил фото] [caption]: {caption}\n")


def log_google(request: str, respond: str):
    """записывает в журнал сообщение полученное обработчиком google"""
    time_now = datetime.datetime.now().strftime('%d-%m-%Y %H.%M.%S')
    log_file_path = f'logs/askgoogle at {time_now}.log'
    with open(log_file_path, 'a', encoding="utf-8") as log_file:
        log_file.write(f'{respond}\n\n{"="*40}\n\n{request}')
    with open(log_file_path.replace('logs/', 'logs2/', 1), 'a', encoding="utf-8") as log_file:
        log_file.write(f'{respond}\n\n{"="*40}\n\n{request}')


def purge(chat_id: int) -> bool:
    f1 = glob.glob(f'logs/*.log')
    f2 = glob.glob(f'logs2/*.log')
    f3 = f1 + f2
    f4 = [x for x in f3 if x.endswith(f'[{chat_id}].log') or x.endswith(f'[{chat_id}].log.debug.log')]
    try:
        for f in f4:
            os.remove(f)
    except Exception as unknown:
        log2(f'my_log:purge: {unknown}')
        return False
    return True

if __name__ == '__main__':
    pass
    purge(1651196)
    
