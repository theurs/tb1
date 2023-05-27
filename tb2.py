#!/usr/bin/env python3


from aiogram import Bot, Dispatcher, types, executor
import io, os
import tempfile
import my_ocr, my_trans, my_log, my_tts, my_stt
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



#################################новый код#######################################
# история диалогов для GPT chat
dp.dialogs = {}
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

    await bot.send_chat_action(chat_id, 'typing')

    # определяем нужно ли реагировать. надо реагировать если сообщение начинается на 'бот ' или 'бот,' в любом регистре
    # так же надо реагировать если это ответ в чате на наше сообщение или диалог происходит в привате  
    if message.text.lower().startswith('бот ') or message.text.lower().startswith('бот,') or is_reply or is_private:  
        #await bot.send_message(chat_id, message.text)
        # добавляем новый запрос пользователя в историю диалога пользователя
        resp = dialog_add_user_request(chat_id, message.text)
        if resp:
            if is_private:
                await bot.send_message(chat_id, resp, parse_mode='Markdown')
            else:
                await message.reply(resp, parse_mode='Markdown')


#################################новый код#######################################


if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
