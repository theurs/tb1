#!/usr/bin/env python3


from aiogram import Bot, Dispatcher, types, executor
import io, os
import my_ocr, my_trans, my_log, my_tts
import chardet
import gpt_basic

if os.path.exists('cfg.py'):
    from cfg import token
else:
    token = os.getenv('TOKEN')


bot = Bot(token=token)
dp = Dispatcher(bot)


async def set_default_commands(dp):
    commands = []
    with open('commands.txt') as f:
        for line in f:
            try:
                command, description = line[1:].strip().split(' - ', 1)
                if command and description:
                    commands.append(types.BotCommand(command, description))
            except Exception as e:
                print(e)
    await dp.bot.set_my_commands(commands)


async def on_startup(dp):
    await set_default_commands(dp)


@dp.message_handler(commands=['start', 'help'])
async def send_welcome(message: types.Message):
    # Отправляем приветственное сообщение
    await message.reply("""Этот бот может\n\nРаспознать текст с картинки, надо отправить картинку с подписью прочитай|распознай|ocr|итп\n\n\
Озвучить текст, надо прислать тексотвый файл .txt с кодировкой UTF8\n\n""" + open('commands.txt').read())
    await my_log.log(message)


@dp.message_handler(commands=['trans'])
async def trans(message: types.Message):
    args = message.text.split(' ', 2)[1:]
    if len(args) != 2:
        await message.reply('Использование: /trans <язык en|ru|...> <текст>')
        return
    lang, text = args
    translated = my_trans.translate_text2(text, lang)
    if translated:
        await message.reply(translated)
    else:
        await message.reply('Ошибка перевода')


@dp.message_handler(commands=['tts']) 
async def tts(message: types.Message):
    args = message.get_args().split()
    if not args:
        await message.reply('Использование: /tts <текст>')
        return
    text = ' '.join(args)
    audio = my_tts.tts(text)
    await message.reply_voice(audio)


@dp.message_handler(commands=['tts2']) 
async def tts2(message: types.Message):
    args = message.get_args().split()
    if not args:
        await message.reply('Использование: /tts ru|en|uk|... <текст>')
        return
    text = ' '.join(args[1:])
    lang = args[0]
    audio = my_tts.tts(text, lang)
    await message.reply_voice(audio)


@dp.message_handler(commands=['tts3']) 
async def tts3(message: types.Message):
    args = message.get_args().split()
    if not args:
        await message.reply('Использование: /tts ru|en|uk|... +-xx% <текст>')
        return
    text = ' '.join(args[2:])
    lang = args[0]
    rate = args[1]
    audio = my_tts.tts(text, lang, rate)
    await message.reply_voice(audio)


@dp.message_handler()
async def echo(message: types.Message):
    if message.entities:
        if message.entities[0]['type'] in ('code', 'spoiler'):
            await my_log.log(message, 'code or spoiler in message')
            return
    text = my_trans.translate(message.text)
    if text:
        await message.answer(text)
        await my_log.log(message, text)
    else:
        await my_log.log(message, '')


@dp.message_handler(content_types=types.ContentType.VIDEO)
async def handle_video(message: types.Message):
    # пересланные сообщения пытаемся перевести даже если в них видео
    if "forward_from_chat" in message:
        if message.entities:
            if message.entities[0]['type'] in ('code', 'spoiler'):
                await my_log.log(message, 'code or spoiler in message')
                return
        # у видео нет текста но есть заголовок caption. его и будем переводить
        text = my_trans.translate(message.caption)
        if text:
            await message.answer(text)
            await my_log.log(message, text)
        else:
            await my_log.log(message, '')
        return


@dp.message_handler(content_types=types.ContentType.PHOTO)
async def handle_photo(message: types.Message):
    # пересланные сообщения пытаемся перевести даже если в них картинка
    if "forward_from_chat" in message:
        if message.entities:
            if message.entities[0]['type'] in ('code', 'spoiler'):
                await my_log.log(message, 'code or spoiler in message')
                return
        # у фотографий нет текста но есть заголовок caption. его и будем переводить
        text = my_trans.translate(message.caption)
        if text:
            await message.answer(text)
            await my_log.log(message, text)
        else:
            await my_log.log(message, '')
        return

    # распознаем текст только если есть команда для этого
    if not message.caption: return
    if not gpt_basic.detect_ocr_command(message.caption.lower()): return

    #chat_type = message.chat.type
    #if chat_type != types.ChatType.PRIVATE: return
    # получаем самую большую фотографию из списка
    photo = message.photo[-1]
    fp = io.BytesIO()
    # скачиваем фотографию в байтовый поток
    await photo.download(destination_file=fp)
    # распознаем текст на фотографии с помощью pytesseract
    text = my_ocr.get_text_from_image(fp.read())
    # отправляем распознанный текст пользователю
    if text.strip() != '':
        # если текст слишком длинный, отправляем его в виде текстового файла
        if len(text) > 4096:
            with io.StringIO(text) as f:
                f.name = 'text.txt'
                await message.reply_document(f)
                await my_log.log(message, '[OCR] Sent as file: ' + text)
        else:
            await message.reply(text)
            await my_log.log(message, '[OCR] ' + text)
    else:
        await my_log.log(message, '[OCR] no results')

    
@dp.message_handler(content_types=types.ContentType.DOCUMENT)
async def handle_document(message: types.Message):

    if message.document.mime_type == 'text/plain':

        file_id = message.document.file_id
        file_info = await bot.get_file(file_id)
        file = await bot.download_file_by_id(file_id)
        text = file.read().decode('utf-8').strip()
        #print(text)
        
        # Озвучиваем текст
        audio = my_tts.tts(text)
        await message.reply_voice(audio)
        return


    #отключено пока. слишком долго выполняется
    return
    
    # получаем самый большой документ из списка
    document = message.document
    # если документ не является PDF-файлом, отправляем сообщение об ошибке
    if document.mime_type != 'application/pdf':
        await message.reply('Это не PDF-файл.')
        return
    fp = io.BytesIO()
    # скачиваем документ в байтовый поток
    await message.document.download(destination_file=fp)
    # распознаем текст в документе с помощью функции get_text
    text = my_ocr.get_text(fp)
    # отправляем распознанный текст пользователю
    if text.strip() != '':
        # если текст слишком длинный, отправляем его в виде текстового файла
        if len(text) > 4096:
            with io.StringIO(text) as f:
                f.name = 'text.txt'
                await message.reply_document(f)
        else:
            await message.reply(text)


if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
