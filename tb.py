#!/usr/bin/env python3


from aiogram import Bot, Dispatcher, types, executor
import io, os
import tempfile
import my_dic, my_ocr, my_trans, my_log, my_tts, my_stt
import chardet
import gpt_basic
import string
import openai
import enchant
import re

if os.path.exists('cfg.py'):
    from cfg import token
else:
    token = os.getenv('TOKEN')


bot = Bot(token=token)
dp = Dispatcher(bot)


# история диалогов для GPT chat
dp.dialogs = my_dic.PersistentDict('dialogs.pkl')
dialogs = dp.dialogs
# диалог всегда начинается одинаково
gpt_start_message = [{"role":    "system",
                      "content": "Ты информационная система отвечающая на запросы юзера."}]


def check_and_fix_text(text):
    """пытаемся исправить странную особенность пиратского GPT сервера, он часто делает ошибку в слове, вставляет 2 вопросика вместо буквы"""
    ru = enchant.Dict("ru_RU")

    # убираем из текста всё кроме русских букв
    text = text.replace('��', '⁂')
    russian_letters = re.compile('[^⁂а-яА-ЯёЁ\s]')
    text2 = russian_letters.sub(' ', text)
    
    words = text2.split()
    for i, word in enumerate(words):
        if '⁂' in word:
            suggestions = ru.suggest(word)
            if len(suggestions) > 0:
                text = text.replace(word, suggestions[0])
            print(word)
            print(suggestions)
    return text


def count_tokens(messages):
    """пытаемся посчитать количество токенов в диалоге юзера с ботом"""
    if messages:
        messages = gpt_start_message + messages
        text = ''.join([msg['content'] + ' ' for msg in messages])
        #words_and_chars = len(text.split())
        #symbols = sum(text.count(x) for x in string.punctuation)
        #words_and_chars += symbols
        words_and_chars = len(text)
        return words_and_chars
    return 0


def dialog_add_user_request(chat_id, text):
    """добавляет в историю переписки с юзером его новый запрос и ответ от GPT
    делает запрос и возвращает ответ"""
    
    global dialogs
    
    # что делать с слишком длинными запросами? пока будем просто игнорить
    #if len(text) > 2000: ''
    
    # создаем новую историю диалогов с юзером из старой если есть
    try:
        new_messages = dialogs[chat_id]
    except Exception as e:
        print('New dialog with: ' + str(e))
        new_messages = []
    
    # теперь ее надо почистить что бы влезла в запрос к GPT
    # просто удаляем все кроме 10 последний
    if len(new_messages) > 10:
        new_messages = new_messages[10:]
    # удаляем первую запись в истории до тех пор пока общее количество токенов не станет меньше 1000
    while (count_tokens(new_messages) > 2000):
        new_messages = new_messages[1:]
    
    # добавляем в историю новый запрос и отправляем в GPT
    new_messages = new_messages + [{"role":    "user",
                                    "content": text}]
    try:
        resp = gpt_basic.ai(prompt = text, messages = gpt_start_message + new_messages)
        # добавляем в историю новый запрос и отправляем в GPT, если он не пустой, иначе удаляем запрос юзера из истории
        if resp:
            resp = check_and_fix_text(resp)
            new_messages = new_messages + [{"role":    "assistant",
                                                "content": resp}]
        else:
            new_messages = new_messages[:-1]
    # бот не ответил и обиделся
    except AttributeError:
        # чистим историю, повторяем запрос
        new_messages = new_messages[:-2]
        resp = 'Не хочу говорить об этом.'
        # добавляем в историю новый запрос и отправляем в GPT, если он не пустой, иначе удаляем запрос юзера из истории
        # if resp:
        #     resp = check_and_fix_text(resp)
        #     new_messages = new_messages + [{"role":    "assistant",
        #                                      "content": resp}]
    except openai.error.InvalidRequestError as e:
        if """This model's maximum context length is 4097 tokens. However, you requested""" in str(e):
            # чистим историю, повторяем запрос
            #while (count_tokens(new_messages) > 1000):
            #    new_messages = new_messages[1:]
            new_messages = new_messages[:-2]
            resp = gpt_basic.ai(prompt = text, messages = gpt_start_message + new_messages)
            # добавляем в историю новый запрос и отправляем в GPT, если он не пустой, иначе удаляем запрос юзера из истории
            if resp:
                resp = check_and_fix_text(resp)
                new_messages = new_messages + [{"role":    "assistant",
                                                "content": resp}]
        else:
            print(e)
        return ''
    
    # сохраняем диалог
    dialogs[chat_id] = new_messages or []
    for i in dialogs[chat_id]:
        print(i)
    print('\n\n')
    return resp


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
    await message.answer("""Этот бот может\n\nРаспознать текст с картинки, надо отправить картинку с подписью прочитай|распознай|ocr|итп\n\n\
Озвучить текст, надо прислать текстовый файл .txt с кодировкой UTF8\n\nСообщения на иностранном языке автоматически переводятся на русский\n\n\
Голосовые сообщения автоматически переводятся в текст\n\nGPT chat активируется словом бот - бот, привет. Что бы отчистить историю напишите забудь.\n\n""" + open('commands.txt').read())
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
    """Обработчик текстовых сообщений"""
    
    # определяем откуда пришло сообщение  
    is_private = message.chat.type == 'private'
    #is_chat_or_superchat = message.chat.type in ['group', 'supergroup'] 

    # является ли это ответом на наше сообщение
    is_reply = message.reply_to_message is not None and message.reply_to_message.from_user.id == bot.id

    # id куда писать ответ
    chat_id = message.chat.id  

    # если сообщение начинается на 'забудь' то стираем историю общения GPT
    if (message.text.lower().startswith('забудь') and (is_private or is_reply)) or (message.text.lower().startswith('бот забудь') or message.text.lower().startswith('бот, забудь')):
        global dialogs
        dialogs[chat_id] = []
        await bot.send_message(chat_id, 'Ок', parse_mode='Markdown')
        await my_log.log(message, 'История GPT принудительно отчищена')
        return

    
    # определяем нужно ли реагировать. надо реагировать если сообщение начинается на 'бот ' или 'бот,' в любом регистре
    # так же надо реагировать если это ответ в чате на наше сообщение или диалог происходит в привате  
    if message.text.lower().startswith('бот ') or message.text.lower().startswith('бот,') or is_reply or is_private:  
        await bot.send_chat_action(chat_id, 'typing')
        #await bot.send_message(chat_id, message.text)
        # добавляем новый запрос пользователя в историю диалога пользователя
        resp = dialog_add_user_request(chat_id, message.text)
        if resp:
            if is_private:
                await bot.send_message(chat_id, resp, parse_mode='Markdown')
                await my_log.log(message, resp)
            else:
                await message.reply(resp, parse_mode='Markdown')
                await my_log.log(message, resp)
    else: # смотрим надо ли переводить текст
        if message.entities: # не надо если там спойлеры
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


@dp.message_handler(content_types=types.ContentType.VOICE)
async def handle_voice(message: types.Message): 
    # Создание временного файла 
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        file_path = temp_file.name
    
    # Скачиваем аудиофайл во временный файл
    file_id = message.voice.file_id
    await bot.download_file_by_id(file_id, file_path)
    
    # Распознаем текст из аудио 
    text = my_stt.stt(file_path)
    
    os.remove(file_path)
    
    # Отправляем распознанный текст 
    if text.strip() != '':
        await message.reply(text)
        await my_log.log(message, f'[ASR] {text}')
    else:
        await my_log.log(message, '[ASR] no results')


if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
