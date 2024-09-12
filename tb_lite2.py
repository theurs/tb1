#!/usr/bin/env python3


import telebot
import cfg
import utils

from telebot import apihelper

#apihelper.API_URL = 'http://0.0.0.0:8081/bot{0}/{1}'
#apihelper.FILE_URL = 'http://0.0.0.0:8081'


bot = telebot.TeleBot(cfg.token2, skip_pending=True)
bot.log_out()


@bot.message_handler(commands=['start'])
def command_code(message: telebot.types.Message):
    # reply hello
    bot.reply_to(message, 'Hello')



@bot.message_handler(content_types=['document', 'photo', 'audio', 'video', 'voice'])
def handle_docs_photo(message):
    """Обрабатывает документы, фото, аудио, видео и голосовые сообщения, 
       полученные от пользователя, скачивает их и отправляет 
       фактический размер скачанного файла."""
    
    file_id = None
    
    if message.document:
        file_id = message.document.file_id
    elif message.photo:
        file_id = message.photo[-1].file_id  # Выбираем фото с наибольшим разрешением
    elif message.audio:
        file_id = message.audio.file_id
    elif message.video:
        file_id = message.video.file_id
    elif message.voice:
        file_id = message.voice.file_id

    if file_id:
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        file_size = len(downloaded_file)
        
        bot.reply_to(message, f"Размер скачанного файла: {file_size} байт")




if __name__ == '__main__':
    bot.polling()
