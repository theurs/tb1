#!/usr/bin/env python3


import os
import datetime
import telebot
import threading


lock = threading.Lock()


def log(message: telebot.types.Message, reply_from_bot: str = '') -> None:
    global lock
    log_file_path = os.path.join(os.getcwd(), f'logs_{message.chat.id}.log')
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
    log_file_path = 'debug.log'
    open(log_file_path, 'a').write(f'{text}\n\n')


def log_echo(message: telebot.types.Message, reply_from_bot: str = '') -> None:
    global lock
    time_now = datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')
    private_or_chat = 'private' if message.chat.type == 'private' else 'chat'
    chat_name = message.chat.username or message.chat.first_name or message.chat.title or ''
    user_name = message.from_user.first_name or message.from_user.username or ''

    log_file_path = os.path.join(os.getcwd(), f'logs [{chat_name}] [{private_or_chat}] [{message.chat.type}] [{message.chat.id}] [echo].log')

    with lock:
        with open(log_file_path, 'a') as log_file:
            if reply_from_bot:
                log_file.write(f"[{time_now}] [BOT]: {reply_from_bot}\n")
            else:
                log_file.write(f"[{time_now}] [{user_name}]: {message.text or message.caption or ''}\n")
            

if __name__ == '__main__':
    pass
