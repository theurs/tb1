#!/usr/bin/env python3


from aiogram import Bot, Dispatcher, types, executor
from aiogram import md
import io, os
import tempfile
import my_dic, my_ocr, my_trans, my_log, my_tts, my_stt
import chardet
import gpt_basic
import string
import openai
import enchant
import re
import subprocess

if os.path.exists('cfg.py'):
    from cfg import token
else:
    token = os.getenv('TOKEN')


bot = Bot(token=token)
dp = Dispatcher(bot)


# история диалогов для GPT chat
dp.dialogs = my_dic.PersistentDict('dialogs.pkl')

# в каких чатах выключены автопереводы
dp.blocks = my_dic.PersistentDict('blocks.pkl')

# в каких чатах какое у бота кодовое слово для обращения к боту
dp.bot_names = my_dic.PersistentDict('names.pkl')
# имя бота по умолчанию, в нижнем регистре без пробелов и символов
bot_name_default = 'бот'

# словарь с диалогами юзеров с чатботом
dialogs = dp.dialogs
# словарь с номерами каналов в которых заблокирован автоперевод
blocks = dp.blocks
# словарь с именами ботов разными в разных чатах
bot_names = dp.bot_names

# диалог всегда начинается одинаково
gpt_start_message = [{"role":    "system",
                      "content": "Ты информационная система отвечающая на запросы юзера."}]


def check_and_fix_text(text):
    """пытаемся исправить странную особенность пиратского GPT сервера, он часто делает ошибку в слове, вставляет 2 вопросика вместо буквы"""
    ru = enchant.Dict("ru_RU")

    # убираем из текста всё кроме русских букв, 2 странных символа меняем на 1 что бы упростить регулярку
    text = text.replace('��', '⁂')
    russian_letters = re.compile('[^⁂а-яА-ЯёЁ\s]')
    text2 = russian_letters.sub(' ', text)
    
    words = text2.split()
    for word in words:
        if '⁂' in word:
            suggestions = ru.suggest(word)
            if len(suggestions) > 0:
                text = text.replace(word, suggestions[0])
    return text.replace('⁂', '')


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



def dialog_add_user_request_bing(chat_id, text):
    """добавляет в историю переписки с юзером его новый запрос и ответ от Bing
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
    # удаляем первую запись в истории до тех пор пока общее количество токенов не станет меньше 2000
    while (count_tokens(new_messages) > 2000):
        new_messages = new_messages[1:]
    
    # добавляем в историю новый запрос и отправляем в bing
    new_messages = new_messages + [{"role":    "user",
                                    "content": text}]
                                    
    # для бинга надо сконвертировать историю по другому
    # в строчку с разделением на строки с помощью \n
    # user - hello
    # bing - hi
    # user - 2+2?
    # bing - 4
    # user - who was first on the moon:
    
    bing_prompt = ''.join(f'{i["role"]} - {i["content"]}\n' for i in new_messages)
    
    resp = subprocess.run(['/usr/bin/python3', '/home/ubuntu/tb/bingai.py', bing_prompt], stdout=subprocess.PIPE)
    resp = resp.stdout.decode('utf-8')
    if resp.startswith('Bing: '):
        resp = resp[6:]
    if resp.startswith('Привет, это Bing.'):
        resp = resp[18:]
    if resp:
        resp = check_and_fix_text(resp)
        new_messages = new_messages + [{"role":    "assistant",
                                         "content": resp}]
        # сохраняем диалог
        dialogs[chat_id] = new_messages or []
        #for i in dialogs[chat_id]:
        #    print(i)
        #print('\n\n')
    else:
        new_messages = new_messages[:-1]
        return ''
    return resp


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
    # удаляем первую запись в истории до тех пор пока общее количество токенов не станет меньше 2000
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
            while (count_tokens(new_messages) > 1000):
                new_messages = new_messages[1:]
            new_messages = new_messages[:-2]
            try:   
                resp = gpt_basic.ai(prompt = text, messages = gpt_start_message + new_messages)
            except Exception as e:
                print(e)
            # добавляем в историю новый запрос и отправляем в GPT, если он не пустой, иначе удаляем запрос юзера из истории
            if resp:
                resp = check_and_fix_text(resp)
                new_messages = new_messages + [{"role":    "assistant",
                                                "content": resp}]
            else:
                new_messages = new_messages[:-1]
                return ''
        else:
            print(e)
            new_messages = new_messages[:-1]
            return ''
    
    # сохраняем диалог
    dialogs[chat_id] = new_messages or []
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



@dp.message_handler(commands=['name',])
async def send_welcome(message: types.Message):
    """Меняем имя если оно подходящее, содержит только русские и английские буквы и не слишком длинное"""
    
    args = message.text.split()
    if len(args) > 1:
        new_name = args[1]
        
        # Строка содержит только русские и английские буквы и цифры после букв, но не в начале слова
        regex = r'^[a-zA-Zа-яА-ЯёЁ][a-zA-Zа-яА-ЯёЁ0-9]*$'
        if re.match(regex, new_name) and len(new_name) <= 10:
            await message.answer(f'Кодовое слово для обращения к боту изменено на ({args[1]}) для этого чата.')
            await my_log.log(message, f'Кодовое слово для обращения к боту изменено на ({args[1]}) для этого чата.')
            global bot_names
            bot_names[message.chat.id] = new_name.lower()
        else:
            await message.reply("Неправильное имя, можно только русские и английские буквы и цифры после букв, не больше 10 всего.")


@dp.message_handler(commands=['start', 'help'])
async def send_welcome(message: types.Message):
    # Отправляем приветственное сообщение
    await message.answer("""Этот бот может\n\nРаспознать текст с картинки, надо отправить картинку с подписью прочитай|распознай|ocr|итп\n\n\
Озвучить текст, надо прислать текстовый файл .txt с кодировкой UTF8 в приват или с подписью прочитай\n\n\
Сообщения на иностранном языке автоматически переводятся на русский, это можно включить|выключить командой замолчи|вернись\n\n\
Голосовые сообщения автоматически переводятся в текст\n\n\
GPT chat активируется словом бот - бот, привет. Что бы отчистить историю напишите забудь.\n\n""" + open('commands.txt').read())
    await my_log.log(message)


@dp.message_handler(commands=['trans'])
async def trans(message: types.Message):
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
    
    help_codes = """ar Арабский
bn Бенгальский
de Немецкий
en Английский
es Испанский
fr Французский
hi Хинди
id Индонезийский
it Итальянский
ja Японский
ko Корейский
ms Малайский
nl Голландский
pa Пенджаби
pl Польский
pt-BR Португальский (Бразилия)
pt-PT Португальский (Португалия)
ru Русский
sv Шведский
ta Тамильский
te Телугу
th Тайский
tr Турецкий
vi Вьетнамский
zh-CN Китайский (упрощенный)
zh-TW Китайский (традиционный)

И многие другие
"""
    args = message.text.split(' ', 2)[1:]
    if len(args) != 2:
        await message.reply('Использование: /trans <язык en|ru|...> <текст>\n\n' + help_codes)
        return
    lang, text = args
    # если язык не указан то это русский
    if lang not in supported_langs:
        text = lang + ' ' + text
        lang = 'ru'
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


    msg = message.text.lower()
    global blocks, bot_names
    
    
    # определяем какое имя у бота в этом чате, на какое слово он отзывается
    if chat_id in bot_names:
        bot_name = bot_names[chat_id]
    else:
        bot_name = bot_name_default
        bot_names[chat_id] = bot_name
    
    
    # если сообщение начинается на 'заткнись или замолчи' то ставим блокировку на канал и выходим
    if ((msg.startswith('замолчи') or msg.startswith('заткнись')) and (is_private or is_reply)) or msg.startswith(f'{bot_name} замолчи') or msg.startswith(f'{bot_name}, замолчи') or msg.startswith(f'{bot_name}, заткнись') or msg.startswith(f'{bot_name} заткнись'):
        blocks[chat_id] = 1
        await my_log.log(message, 'Включена блокировка автопереводов в чате')
        await bot.send_message(chat_id, 'Автоперевод выключен', parse_mode='Markdown')
        return
    # если сообщение начинается на 'вернись' то снимаем блокировку на канал и выходим
    if ((msg.startswith('вернись')) and (is_private or is_reply)) or (msg.startswith(f'{bot_name} вернись') or msg.startswith(f'{bot_name}, вернись')):
        blocks[chat_id] = 0
        await my_log.log(message, 'Выключена блокировка автопереводов в чате')
        await bot.send_message(chat_id, 'Автоперевод включен', parse_mode='Markdown')
        return


    # если сообщение начинается на 'забудь' то стираем историю общения GPT
    if (msg.startswith('забудь') and (is_private or is_reply)) or (msg.startswith(f'{bot_name} забудь') or msg.startswith(f'{bot_name}, забудь')):
        global dialogs
        dialogs[chat_id] = []
        await bot.send_message(chat_id, 'Ок', parse_mode='Markdown')
        await my_log.log(message, 'История GPT принудительно отчищена')
        return


    # определяем нужно ли реагировать. надо реагировать если сообщение начинается на 'бот ' или 'бот,' в любом регистре
    # можно перенаправить запрос к бингу, но он долго отвечает
    if msg.startswith('бинг ') or msg.startswith('бинг,'):
        await bot.send_chat_action(chat_id, 'typing')
        # добавляем новый запрос пользователя в историю диалога пользователя
        resp = dialog_add_user_request_bing(chat_id, message.text)
        if resp:
            if is_private:
                await bot.send_message(chat_id, resp, parse_mode='Markdown')
                await my_log.log(message, resp)
            else:
                await message.reply(resp, parse_mode='Markdown')
                await my_log.log(message, resp)
    # так же надо реагировать если это ответ в чате на наше сообщение или диалог происходит в привате  
    elif msg.startswith(f'{bot_name} ') or msg.startswith(f'{bot_name},') or is_reply or is_private:
        await bot.send_chat_action(chat_id, 'typing')
        # добавляем новый запрос пользователя в историю диалога пользователя
        resp = dialog_add_user_request(chat_id, message.text)
        if resp:
            if is_private:
                try:
                    await bot.send_message(chat_id, resp, parse_mode='Markdown')
                except Exceptaion as e:
                    print(e)
                    await bot.send_message(chat_id, md.quote_html(resp), parse_mode='Markdown')
            else:
                try:
                    await message.reply(resp, parse_mode='Markdown')
                except Exception as e:
                    print(e)
                    await message.reply(md.quote_html(resp), parse_mode='Markdown')
            await my_log.log(message, resp)
    else: # смотрим надо ли переводить текст
        if chat_id in blocks and blocks[chat_id] == 1:
            return
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
    """Обработчик видеосообщений. Сюда же относятся новости и репосты с видео"""
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
    """Обработчик фотографий. Сюда же попадают новости которые создаются как фотография + много текста в подписи, и пересланные сообщения в том числе"""
    # пересланные сообщения пытаемся перевести даже если в них картинка
    # новости в телеграме часто делают как картинка + длинная подпись к ней
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
    """Обработчик документов"""
    # начитываем текстовый файл только если его прислали в привате или с указанием прочитай/читай
    caption = message.caption or ''
    if message.chat.type == 'private' or caption.lower() in ['прочитай', 'читай']:
        # если текстовый файл то пытаемся озвучить как книгу. русский голос, скорость +50%
        if message.document.mime_type == 'text/plain':
            file_id = message.document.file_id
            file_info = await bot.get_file(file_id)
            file = await bot.download_file_by_id(file_id)
            text = file.read().decode('utf-8').strip()
        
            # Озвучиваем текст
            audio = my_tts.tts(text)
            await message.reply_voice(audio)
            return


    # дальше идет попытка распознать ПДФ файл, вытащить текст с изображений
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
    """Автоматическое распознавание текст из голосовых сообщений"""
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


@dp.message_handler(content_types=types.ContentType.AUDIO)
async def handle_audio(message: types.Message): 
    """Распознавание текст из аудио файлов"""
    caption = message.caption or ''
    if not(message.chat.type == 'private' or caption.lower() in ['распознай', 'расшифруй']):
        return

    # Создание временного файла 
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        file_path = temp_file.name
    
    # Скачиваем аудиофайл во временный файл
    file_id = message.audio.file_id
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
