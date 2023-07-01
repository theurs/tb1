#!/usr/bin/env python3


import os
import datetime
import telebot
import threading


lock = threading.Lock()


if not os.path.exists('logs'):
    os.mkdir('logs')


def log(message: telebot.types.Message, reply_from_bot: str = '') -> None:
    global lock
    #log_file_path = os.path.join(os.getcwd(), f'logs/{message.chat.id}.log')
    log_file_path = f'logs/{message.chat.id}.log'
    with lock:
        with open(log_file_path, 'a') as log_file:
            time_now = datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')
            log_file.write(f"[{time_now}] [{message.chat.type}] [{('user' if message.chat.type == 'private' else 'chat')} \
{message.chat.username or message.chat.first_name or message.chat.title or ''}] [{message.from_user.first_name or message.from_user.username or ''}]: \
{message.text or message.caption}\n")
            if reply_from_bot:
                log_file.write(f"[{time_now}] Bot replied: {reply_from_bot}\n")
            log_file.write('\n\n')


def log2(text: str) -> None:
    """для дебага"""
    log_file_path = 'logs/debug.log'
    open(log_file_path, 'a').write(f'{text}\n=========================================================================================\n')


def log_echo(message: telebot.types.Message, reply_from_bot: str = '') -> None:
    """записывает в журнал сообщение полученное обработчиком обычных сообщений либо ответ бота"""
    global lock
    time_now = datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')
    private_or_chat = 'private' if message.chat.type == 'private' else 'chat'
    chat_name = message.chat.username or message.chat.first_name or message.chat.title or ''
    user_name = message.from_user.first_name or message.from_user.username or ''

    logname = f'logs/[{chat_name}] [{private_or_chat}] [{message.chat.type}] [{message.chat.id}].log'.replace('[private] [private]', '[private]').replace('[chat] [supergroup]', '[chat]')
    log_file_path = logname
    #log_file_path = os.path.join(os.getcwd(), logname)

    with lock:
        with open(log_file_path, 'a') as log_file:
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

    caption = message.caption or ''

    logname = f'logs/[{chat_name}] [{private_or_chat}] [{message.chat.type}] [{message.chat.id}].log'.replace('[private] [private]', '[private]').replace('[chat] [supergroup]', '[chat]')
    log_file_path = logname
    #log_file_path = os.path.join(os.getcwd(), logname)

    if message.audio:
        file_name = message.audio.file_name
        file_size = message.audio.file_size
        file_duration = message.audio.duration
        file_title = message.audio.title
        file_mime_type = message.audio.mime_type
        with lock:
            with open(log_file_path, 'a') as log_file:
                log_file.write(f"[{time_now}] [{user_name}]: [Отправил аудио файл] [caption: {caption}] [title: {file_title}] \
[filename: {file_name}] [filesize: {file_size}] [duration: {file_duration}] [mime type: {file_mime_type}]\n")

    if message.voice:
        file_size = message.voice.file_size
        file_duration = message.voice.duration
        with lock:
            with open(log_file_path, 'a') as log_file:
                log_file.write(f"[{time_now}] [{user_name}]: [Отправил голосовое сообщение] [filesize: \
{file_size}] [duration: {file_duration}]\n")

    if message.document:
        file_name = message.document.file_name
        file_size = message.document.file_size
        file_mime_type = message.document.mime_type
        with lock:
            with open(log_file_path, 'a') as log_file:
                log_file.write(f"[{time_now}] [{user_name}]: [Отправил документ] [caption: {caption}] \
[filename: {file_name}] [filesize: {file_size}] [mime type: {file_mime_type}]\n")

    if message.photo or message.video:
        with lock:
            with open(log_file_path, 'a') as log_file:
                log_file.write(f"[{time_now}] [{user_name}]: [Отправил фото] [caption]: {caption}\n")


if __name__ == '__main__':
    pass
    log2('1')
    
