#!/usr/bin/env python3
# pip install -U unidecode

import glob
import os
import datetime
import html
import re
import telebot
import threading
from collections import defaultdict
from unidecode import unidecode

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


def transliterate(text):
    # Преобразуем текст в его ASCII эквивалент
    text = unidecode(text)
    text = re.sub(r'[^a-zA-Z0-9_]+', '_', text.strip())
    return text


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


def log_bing_api(text: str) -> None:
    """для логов bingapi"""
    log2(text, 'bing_api')


def log_reprompts(text: str) -> None:
    """для логов переводов промптов для рисования"""
    log2(text, 'reprompts')


def log_reports(text: str) -> None:
    """для логов сообщений от юзеров к админу"""
    log2(text, 'reports')


def log_layout_switcher(orig: str, translated: str):
    """для логов автоисправления раскладки"""
    t = orig + '\n->\n' + translated
    log2(t, 'log_layout_switcher')

def log_transcribe(text: str) -> None:
    """для логов транскрибации аудио в субтитры"""
    log2(text, 'transcribe')

def log3(text: str) -> None:
    """для логов донатов (отладка)"""
    log2(text, 'donate_debug')

def log_donate(text: str) -> None:
    """для логов донатов"""
    log2(text, 'donate')

def log_donate_consumption(text: str) -> None:
    """для логов о потреблении донатов"""
    log2(text, 'donate_consumption')

def log_donate_consumption_fail(text: str) -> None:
    """для логов о потреблении донатов, когда не хватило"""
    log2(text, 'donate_consumption_fail')

def log_auth(text: str) -> None:
    """для логов авторизации"""
    log2(text, 'auth')

def log_gemini(text: str) -> None:
    """для логов gemini"""
    a = [
        '429 Resource has been exhausted (e.g. check quota)',
        '503 The model is overloaded. Please try again later.',
        'no results after 4 tries, query:',
    ]
    if any([x for x in a if x in text]):
        return
    log2(text[:2000], 'gemini')

def log_gemini_google(text: str) -> None:
    """для логов gemini_google"""
    log2(text[:2000], 'gemini_google')

def log_gemini_lite(text: str) -> None:
    """для логов gemini lite"""
    a = [
        '429 Resource has been exhausted (e.g. check quota)',
        '503 The model is overloaded. Please try again later.',
        'no results after 4 tries, query:',
    ]
    if any([x for x in a if x in text]):
        return
    log2(text[:2000], 'gemini_lite')

def log_ddg(text: str) -> None:
    """для логов ddg"""
    log2(text[:2000], 'ddg')

def log_stability_ai(text: str) -> None:
    """для логов stability_ai"""
    log2(text[:2000], 'stability_ai')

def log_keys(text: str) -> None:
    """для логов новых ключей"""
    log2(text, 'keys')

def log_openrouter(text: str) -> None:
    """для логов openrouter"""
    log2(text[:2000], 'openrouter')

def log_openrouter_free(text: str) -> None:
    """для логов openrouter free"""
    log2(text[:2000], 'openrouter_free')

def log_github(text: str) -> None:
    """для логов github"""
    log2(text[:2000], 'github')

def log_glm(text: str) -> None:
    """для логов glm"""
    log2(text[:2000], 'glm')

def log_deepgram(text: str) -> None:
    """для логов deepgram"""
    log2(text[:2000], 'deepgram')

def log_mistral(text: str) -> None:
    """для логов openrouter mistral"""
    log2(text[:2000], 'mistral')

def log_cohere(text: str) -> None:
    """для логов cohere"""
    log2(text[:2000], 'cohere')

def log_groq(text: str) -> None:
    """для логов groq"""
    log2(text[:2000], 'groq')

def log_entropy_detector(text: str) -> None:
    """для логов entropy_detector"""
    log2(text, 'entropy_detector')

def log_gemini_skills(text: str) -> None:
    """для логов вызовов функций в джемини"""
    log2(text, 'gemini_skills')

def log_bing_success(text: str) -> None:
    """для логов удачных комбинаций бинга, когда ему удалось нарисовать что-нибудь"""
    log2(text, 'bing_success')

def log_fish_speech(text: str) -> None:
    """для логов fish_speech"""
    log2(text, 'fish_speech')

def log_bing_img(text: str) -> None:
    """для дебага ошибок bing_img с помощью ai"""
    log2(text, 'bing_img')

def log_huggin_face_api(text: str) -> None:
    """для логов от hugging_face_api"""
    a = [
        'Model too busy, unable to get response in less than 60 second',
        'Rate limit reached. You reached free usage limit',
        'HTTPSConnectionPool(host=',
        'An error happened while trying to locate the file on the Hub and we cannot find the requested files in the local cache.',
        'Task not found for this model',
        'CUDA kernel errors might be asynchronously reported at some other API call, so the stacktrace below might be incorrect.',
        'Remote end closed connection without response',
        'Max requests total reached on image generation inference (3). Wait up to one minute before being able to process more Diffusion requests.',
    ]
    if any([x for x in a if x in text]):
        return
    log2(text, 'hugging_face_api')


def log_parser_error(text: str) -> None:
    """для дебага ошибок md->html конвертера"""
    log2(text, 'parser_error')


def log_parser_error2(text: str) -> None:
    """для дебага ошибок md->html конвертера,
    сохраняем отдельно файлы для удобства последующей проверки
    сохраним только тексты которые не прошли через фильтр телеграма
    """
    # check path ./parser_errors exists
    if not os.path.exists('parser_errors'):
        os.makedirs('parser_errors')

    if text.strip():
        with open(f'parser_errors/{datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")}.txt', 'w') as f:
            f.write(text)


def log_translate(text: str) -> None:
    """для дебага ошибок автоперевода с помощью ai"""
    log2(text, 'translate')


def restore_message_text(s1: str, l) -> str:
    """
    Функция принимает строку s1 и список l с описанием форматирования,
    и возвращает строку s0 с примененным форматированием.

    Args:
        s1: Строка, к которой нужно применить форматирование.
        l: Список словарей, описывающих форматирование.
        Каждый словарь содержит информацию о типе форматирования (type),
        начальной позиции (offset), длине (length) и языке (language,
        если применимо).

    Returns:
        Строка s0 с примененным форматированием.
    """
    if not l:
        return s1
    
    # Группируем элементы по их диапазонам
    formatted_intervals = defaultdict(list)
    for i in l:
        formatted_intervals[(i.offset, i.length)].append(i)

    s0 = ""
    last_pos = 0

    # Обрабатываем текст по интервалам
    for (offset, length), formats in sorted(formatted_intervals.items(), key=lambda x: x[0][0]):
        # Добавляем текст до текущего форматированного блока
        s0 += s1[last_pos:offset]
        
        # Извлекаем текст для форматирования
        formatted_text = s1[offset:offset + length]

        formatted_text_space_trailing_flag = False
        if formatted_text and formatted_text[-1] == ' ':
            formatted_text_space_trailing_flag = True

        formatted_text = formatted_text.strip()

        # Применяем все форматы последовательно
        for i in formats:
            if i.type == 'bold':
                formatted_text = f"**{formatted_text}**"
            elif i.type == 'italic':
                formatted_text = f"__{formatted_text}__"
            elif i.type == 'strikethrough':
                formatted_text = f"~~{formatted_text}~~"
            elif i.type == 'code':
                formatted_text = f"`{formatted_text}`"
            elif i.type == 'spoiler':
                formatted_text = f"||{formatted_text}||"
            elif i.type == 'underline':
                formatted_text = f"<u>{formatted_text}</u>"
            elif i.type == 'text_link':
                formatted_text = f"[{formatted_text}]({i.url})"
            elif i.type == 'blockquote' or i.type == 'expandable_blockquote':
                formatted_text = "> " + formatted_text.replace("\n", "\n> ")
            elif i.type == 'pre':
                if i.language:
                    formatted_text = f"```{i.language}\n{formatted_text}\n```"
                else:
                    formatted_text = f"```\n{formatted_text}\n```"
            else:
                if i.type not in (
                    'bot_command',
                    'cashtag',
                    'custom_emoji',
                    'email',
                    'hashtag',
                    'mention',
                    'phone_number',
                    'text_mention',
                    'url'
                ):
                    log2(f'Unknown message entity type {i.type} {formatted_text}')
        
        # Добавляем результат в итоговую строку
        s0 += formatted_text

        if formatted_text_space_trailing_flag:
            s0 += ' '

        # Обновляем индекс последней позиции
        last_pos = offset + length

    # Добавляем оставшийся текст после последнего форматирования
    s0 += s1[last_pos:]
    return s0


def log_echo(message: telebot.types.Message, reply_from_bot: str = '', debug: bool = False) -> None:
    """записывает в журнал сообщение полученное обработчиком обычных сообщений либо ответ бота"""
    if hasattr(cfg, 'DO_NOT_LOG') and message.chat.id in cfg.DO_NOT_LOG:
        return

    if LOG_MODE == -1:
        return

    global lock

    # original_message_text = message.text
    # message.text = restore_message_text(message.text, message.entities)

    time_now = datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')
    private_or_chat = 'private' if message.chat.type == 'private' else 'chat'
    chat_name = message.chat.username or message.chat.first_name or message.chat.title or ''
    user_name = message.from_user.first_name or message.from_user.username or ''
    chat_name = transliterate(chat_name)[:100]
    user_name = transliterate(user_name)[:100]
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
                    log_file.write(f"[{time_now}] [{user_name}]: {html.unescape(message.text) or html.unescape(message.caption) or ''}\n")
        if LOG_MODE in (0,1):
            with open(log_file_path.replace('logs/', 'logs2/', 1), 'a', encoding="utf-8") as log_file:
                if reply_from_bot:
                    log_file.write(f"[{time_now}] [BOT]: {reply_from_bot}\n")
                else:
                    log_file.write(f"[{time_now}] [{user_name}]: {html.unescape(message.text) or html.unescape(message.caption) or ''}\n")


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
    chat_name = transliterate(chat_name)[:100]
    user_name = transliterate(user_name)[:100]
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
    f1 = glob.glob('logs/*.log')
    f2 = glob.glob('logs2/*.log')
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

    # Пример использования функции:
    # example_text = "Пример текста на русском, а также китайский: 中文 以及 日本語。"
    # example_text += 'مرحبا بالعالم! 🌍'
    # example_text += 'ሰላም አለም! 🪐🎉🎊✨🎈'
    # transliterated_text = transliterate(example_text)
    # print(transliterated_text)
 
    log_parser_error2('test')
 