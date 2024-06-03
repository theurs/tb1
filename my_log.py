#!/usr/bin/env python3


import glob
import os
import datetime
import telebot
import threading

import cfg


lock = threading.Lock()


if not os.path.exists('logs'):
    os.mkdir('logs')
if not os.path.exists('logs2'):
    os.mkdir('logs2')


# -1 - do not log to files
# 0 - log users to log2/ only
# 1 - log users to log/ and log2/
LOG_MODE = cfg.LOG_MODE if hasattr(cfg, 'LOG_MODE') else 0


def trancate_log_file(log_file_path: str):
    """
    Truncates the log file at the given file path if it exceeds the maximum file size.

    Parameters:
        log_file_path (str): The path to the log file.

    Returns:
        None

    This function checks if the log file exists and if its size exceeds the maximum file size.
    If it does, it opens the file in read and write mode and truncates it by keeping only the
    last half of the data. The function uses the os module to check the file path and the cfg
    module to get the maximum file size if it is defined.

    Note:
        The function assumes that the log file is in UTF-8 encoding.
    """
    try:
        if not os.path.exists(log_file_path):
            return
        fsize = os.path.getsize(log_file_path)
        max_fsize = cfg.MAX_LOG_FILE_SIZE if hasattr(cfg, 'MAX_LOG_FILE_SIZE') else 20*1024*1024
        if fsize > max_fsize:
            with open(log_file_path, 'r+') as f:
                f.seek(fsize - max_fsize // 2) # Переходим к середине от превышения размера
                data = f.read() # Читаем оставшиеся данные
                f.seek(0) # Переходим в начало файла
                f.write(data) # Записываем последние данные
                f.truncate(len(data)) # Обрезаем файл        
    except Exception as unknown:
        print(f'my_log:trancate_log_file: {unknown}')


def log2(text: str, fname: str = '') -> None:
    """
    Writes the given text to a log file.

    Args:
        text (str): The text to be written to the log file.
        fname (str, optional): The name of the log file. Defaults to an empty string.

    Returns:
        None: This function does not return anything.

    This function writes the given text to a log file. If the `fname` parameter is provided,
    the log file will be named `debug-{fname}.log`, otherwise it will be named `debug.log`.
    The function checks the value of the `LOG_MODE` variable and writes the text to the log
    file accordingly. If `LOG_MODE` is 1, the text is appended to the log file located at
    `logs/debug-{fname}.log`. If `LOG_MODE` is 0, the text is appended to both the log
    files located at `logs/debug-{fname}.log` and `logs2/debug-{fname}.log`. After writing
    the text, the function calls the `truncate_log_file` function to truncate the log file
    if it exceeds the maximum size defined in the `cfg` module.

    Note:
        The function assumes that the log files are in UTF-8 encoding.
    """
    if LOG_MODE == -1:
        return

    global lock
    with lock:
        time_now = datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')
        if fname:
            log_file_path = f'logs/debug_{fname}.log'
        else:
            log_file_path = 'logs/debug.log'
        if LOG_MODE in (1,):
            open(log_file_path, 'a', encoding="utf-8").write(f'{time_now}\n\n{text}\n{"=" * 80}\n')
        if LOG_MODE in (0,1):
            open(log_file_path.replace('logs/', 'logs2/', 1), 'a', encoding="utf-8").write(f'{time_now}\n\n{text}\n{"=" * 80}\n')
        trancate_log_file(log_file_path)


def log_reprompts(text: str) -> None:
    """для логов переводов промптов для рисования"""
    log2(text, 'reprompts')


def log_gemini(text: str) -> None:
    """для логов gemini"""
    log2(text[:2000], 'gemini')


def log_keys(text: str) -> None:
    """для логов новых ключей"""
    log2(text, 'keys')


def log_openrouter(text: str) -> None:
    """для логов openrouter"""
    log2(text[:2000], 'openrouter')


def log_groq(text: str) -> None:
    """для логов groq"""
    log2(text[:2000], 'groq')


def log_entropy_detector(text: str) -> None:
    """для логов entropy_detector"""
    log2(text, 'entropy_detector')


def log_bing_success(text: str) -> None:
    """для логов удачных комбинаций бинга, когда ему удалось нарисовать что-нибудь"""
    log2(text, 'bing_success')


def log_bing_img(text: str) -> None:
    """для дебага ошибок bing_img с помощью ai"""
    log2(text, 'bing_img')


def log_huggin_face_api(text: str) -> None:
    """для логов от hugging_face_api"""
    log2(text, 'hugging_face_api')


def log_parser_error(text: str) -> None:
    """для дебага ошибок md->html конвертера"""
    log2(text, 'parser_error')


def log_translate(text: str) -> None:
    """для дебага ошибок автоперевода с помощью ai"""
    log2(text, 'translate')


def log_echo(message: telebot.types.Message, reply_from_bot: str = '', debug: bool = False) -> None:
    """записывает в журнал сообщение полученное обработчиком обычных сообщений либо ответ бота"""
    if hasattr(cfg, 'DO_NOT_LOG') and message.chat.id in cfg.DO_NOT_LOG:
        return

    if LOG_MODE == -1:
        return

    global lock
    time_now = datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')
    private_or_chat = 'private' if message.chat.type == 'private' else 'chat'
    chat_name = message.chat.username or message.chat.first_name or message.chat.title or ''
    user_name = message.from_user.first_name or message.from_user.username or ''
    chat_name = chat_name.replace('/', '⁄')
    user_name = user_name.replace('/', '⁄')
    if message.chat.type != 'private':
        user_name = f'{user_name} {message.from_user.id}'

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
        if LOG_MODE in (1,):
            with open(log_file_path, 'a', encoding="utf-8") as log_file:
                if reply_from_bot:
                    log_file.write(f"[{time_now}] [BOT]: {reply_from_bot}\n")
                else:
                    log_file.write(f"[{time_now}] [{user_name}]: {message.text or message.caption or ''}\n")
        if LOG_MODE in (0,1):
            with open(log_file_path.replace('logs/', 'logs2/', 1), 'a', encoding="utf-8") as log_file:
                if reply_from_bot:
                    log_file.write(f"[{time_now}] [BOT]: {reply_from_bot}\n")
                else:
                    log_file.write(f"[{time_now}] [{user_name}]: {message.text or message.caption or ''}\n")


def log_media(message: telebot.types.Message) -> None:
    """записывает в журнал сообщение полученное обработчиком медиа файлов"""
    if hasattr(cfg, 'DO_NOT_LOG') and message.chat.id in cfg.DO_NOT_LOG:
        return

    if LOG_MODE == -1:
        return

    global lock
    time_now = datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')
    private_or_chat = 'private' if message.chat.type == 'private' else 'chat'
    chat_name = message.chat.username or message.chat.first_name or message.chat.title or ''
    user_name = message.from_user.first_name or message.from_user.username or ''
    chat_name = chat_name.replace('/', '⁄')
    user_name = user_name.replace('/', '⁄')
    if message.chat.type != 'private':
        user_name = f'{user_name} {message.from_user.id}'

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
            if LOG_MODE in (1,):
                with open(log_file_path, 'a', encoding="utf-8") as log_file:
                    log_file.write(f"[{time_now}] [{user_name}]: [Отправил аудио файл] [caption: {caption}] [title: {file_title}] \
    [filename: {file_name}] [filesize: {file_size}] [duration: {file_duration}] [mime type: {file_mime_type}]\n")
            if LOG_MODE in (0,1):
                with open(log_file_path.replace('logs/', 'logs2/', 1), 'a', encoding="utf-8") as log_file:
                    log_file.write(f"[{time_now}] [{user_name}]: [Отправил аудио файл] [caption: {caption}] [title: {file_title}] \
    [filename: {file_name}] [filesize: {file_size}] [duration: {file_duration}] [mime type: {file_mime_type}]\n")

    if message.voice:
        file_size = message.voice.file_size
        file_duration = message.voice.duration
        with lock:
            if LOG_MODE in (1,):
                with open(log_file_path, 'a', encoding="utf-8") as log_file:
                    log_file.write(f"[{time_now}] [{user_name}]: [Отправил голосовое сообщение] [filesize: \
    {file_size}] [duration: {file_duration}]\n")
            if LOG_MODE in (0,1):
                with open(log_file_path.replace('logs/', 'logs2/', 1), 'a', encoding="utf-8") as log_file:
                    log_file.write(f"[{time_now}] [{user_name}]: [Отправил голосовое сообщение] [filesize: \
    {file_size}] [duration: {file_duration}]\n")

    if message.document:
        file_name = message.document.file_name
        file_size = message.document.file_size
        file_mime_type = message.document.mime_type
        with lock:
            if LOG_MODE in (1,):
                with open(log_file_path, 'a', encoding="utf-8") as log_file:
                    log_file.write(f"[{time_now}] [{user_name}]: [Отправил документ] [caption: {caption}] \
    [filename: {file_name}] [filesize: {file_size}] [mime type: {file_mime_type}]\n")
            if LOG_MODE in (0,1):
                with open(log_file_path.replace('logs/', 'logs2/', 1), 'a', encoding="utf-8") as log_file:
                    log_file.write(f"[{time_now}] [{user_name}]: [Отправил документ] [caption: {caption}] \
    [filename: {file_name}] [filesize: {file_size}] [mime type: {file_mime_type}]\n")

    if message.photo or message.video:
        if LOG_MODE in (1,):
            with lock:
                with open(log_file_path, 'a', encoding="utf-8") as log_file:
                    log_file.write(f"[{time_now}] [{user_name}]: [Отправил фото] [caption]: {caption}\n")
        if LOG_MODE in (0,1):
            with lock:
                with open(log_file_path.replace('logs/', 'logs2/', 1), 'a', encoding="utf-8") as log_file:
                    log_file.write(f"[{time_now}] [{user_name}]: [Отправил фото] [caption]: {caption}\n")



def purge(chat_id: int) -> bool:
    """
    Remove log files associated with the given chat_id and return True if successful, False otherwise.
    :param chat_id: An integer representing the chat ID
    :return: A boolean indicating the success of the purge operation
    """
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
