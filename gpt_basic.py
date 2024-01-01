#!/usr/bin/env python3

import datetime
import os
import json
import pickle
import random
import re
import sys
import time
import threading
import tiktoken

import enchant
from fuzzywuzzy import fuzz
import openai
import requests

import cfg
import utils
import my_dic
import my_google
import my_log
import my_trans


# clientside timeout
# openai.api_requestor.TIMEOUT_SECS = 150


CUSTOM_MODELS = my_dic.PersistentDict('db/custom_models.pkl')

# память диалогов {id:messages: list}
CHATS = my_dic.PersistentDict('db/dialogs.pkl')
# системные промты для чатов, роли или инструкции что и как делать в этом чате
# {id:prompt}
# PROMPTS = my_dic.PersistentDict('db/prompts.pkl')
# температура chatGPT {id:float(0-2)}
TEMPERATURE = {}
# замки диалогов {id:lock}
CHAT_LOCKS = {}


def ai(prompt: str = '', temp: float = 0.1, max_tok: int = 2000, timeou: int = 120, messages = None,
       chat_id = None, model_to_use: str = '') -> str:
    """Сырой текстовый запрос к GPT чату, возвращает сырой ответ
    """
    global CUSTOM_MODELS

    if messages == None:
        assert prompt != '', 'prompt не может быть пустым'
        messages = [{"role": "system", "content": """Ты искусственный интеллект отвечающий на запросы юзера."""},
                    {"role": "user", "content": prompt}]

    current_model = cfg.model
    if chat_id and chat_id in CUSTOM_MODELS:
        current_model = CUSTOM_MODELS[chat_id]

    # использовать указанную модель если есть
    current_model = current_model if not model_to_use else model_to_use

    response = ''

    # копируем и перемешиваем список серверов
    shuffled_servers = cfg.openai_servers[:]
    random.shuffle(shuffled_servers)

    # не использовать нагу для текстовых запросов
    shuffled_servers = [x for x in shuffled_servers if 'api.naga.ac' not in x[0]]

    for server in shuffled_servers:
        openai.base_url = server[0]

        try:
            client = openai.OpenAI(api_key = server[1])
            # тут можно добавить степень творчества(бреда) от 0 до 2 дефолт - temperature = 1
            completion = client.chat.completions.create(
                model = current_model,
                messages=messages,
                max_tokens=max_tok,
                temperature=temp,
                timeout=timeou
            )
            response = completion.choices[0].message.content
            if response:
                break
        except Exception as unknown_error1:
            if 'You exceeded your current quota, please check your plan and billing details.' in str(unknown_error1) \
                or 'The OpenAI account associated with this API key has been deactivated.' in str(unknown_error1):
                my_log.log2(f'gpt_basic.ai: {unknown_error1}\n\nServer: {openai.base_url}\n\n{server[1]}')
                cfg.openai_servers = [x for x in cfg.openai_servers if x[1] != server[1]]
                continue
            # if str(unknown_error1).startswith('HTTP code 200 from API'):
            #         # ошибка парсера json?
            #         text = str(unknown_error1)[24:]
            #         lines = [x[6:] for x in text.split('\n') if x.startswith('data:') and ':{"content":"' in x]
            #         content = ''
            #         for line in lines:
            #             parsed_data = json.loads(line)
            #             content += parsed_data["choices"][0]["delta"]["content"]
            #         if content:
            #             response = content
            #             break
            if 'Request timed out.' in str(unknown_error1) or 'cf_service_unavailable' in str(unknown_error1):
                my_log.log2(f'gpt_basic.ai: {unknown_error1}\n\nServer: {openai.base_url}\n\n{server[1]}\n\nsleep 10sec')
                time.sleep(10)
                continue
            # print(unknown_error1)
            my_log.log2(f'gpt_basic.ai: {unknown_error1}\n\nServer: {openai.base_url}')

    return check_and_fix_text(response)


def ai_instruct(prompt: str = '', temp: float = 0.1, max_tok: int = 2000, timeou: int = 120,
       model_to_use: str = 'gpt-3.5-turbo-instruct') -> str:
    """Сырой текстовый запрос к GPT чату, возвращает сырой ответ, для моделей instruct
    """

    assert prompt != '', 'prompt не может быть пустым'

    current_model = model_to_use

    response = ''
    
    # перемешиваем сервера
    shuffled_servers = cfg.openai_servers[:]
    random.shuffle(shuffled_servers)

    # не использовать нагу для текстовых запросов
    shuffled_servers = [x for x in shuffled_servers if 'api.naga.ac' not in x[0]]

    for server in shuffled_servers:
        openai.base_url = server[0]

        try:
            client = openai.OpenAI(api_key = server[1])

            completion = client.completions.create(
                model=current_model,
                prompt=prompt,
                max_tokens=max_tok,
                # temperature=temp,
                timeout=timeou
            )
            response = completion.choices[0].text
            if response:
                break
        except Exception as unknown_error1:
            if str(unknown_error1).startswith('HTTP code 200 from API'):
                    # ошибка парсера json?
                    text = str(unknown_error1)[24:]
                    lines = [x[6:] for x in text.split('\n') if x.startswith('data:') and ':{"content":"' in x]
                    content = ''
                    for line in lines:
                        parsed_data = json.loads(line)
                        content += parsed_data["choices"][0]["delta"]["content"]
                    if content:
                        response = content
                        break
            print(unknown_error1)
            my_log.log2(f'gpt_basic.ai: {unknown_error1}\n\nServer: {openai.base_url}')

    return check_and_fix_text(response)


def ai_compress(prompt: str, max_prompt: int  = 300, origin: str = 'user', force: bool = False) -> str:
    """сжимает длинное сообщение в чате для того что бы экономить память в контексте
    origin - чье сообщение, юзера или это ответ помощника. 'user' или 'assistant'
    force - надо ли сжимать сообщения которые короче чем заданная максимальная длинна. это надо что бы не сжать а просто резюмировать,
            превратить диалог в такое предложение что бы бинг его принял вместо диалога
    """
    assert origin in ('user', 'assistant', 'dialog')
    if len(prompt) > max_prompt or force:
        try:
            if origin == 'user':
                compressed_prompt = ai(f'Сократи текст до {max_prompt} символов так что бы сохранить смысл и важные детали. \
Этот текст является запросом юзера в переписке между юзером и ИИ. Используй короткие слова. Текст:\n{prompt}', max_tok = max_prompt)
            elif origin == 'assistant':
                compressed_prompt = ai(f'Сократи текст до {max_prompt} символов так что бы сохранить смысл и важные детали. \
Этот текст является ответом ИИ в переписке между юзером и ИИ. Используй короткие слова. Текст:\n{prompt}', max_tok = max_prompt)
            elif origin == 'dialog':
                compressed_prompt = ai(f'Резюмируй переписку между юзером и ассистентом до {max_prompt} символов, весь негативный контент исправь на нейтральный:\n{prompt}', max_tok = max_prompt)
            if len(compressed_prompt) < len(prompt) or force:
                return compressed_prompt
        except Exception as error:
            print(error)

        if len(prompt) > max_prompt:
            ziped = zip_text(prompt)
            if len(ziped) <= max_prompt:
                prompt = ziped
            else:
                prompt = prompt[:max_prompt]

    return prompt


def get_mem_as_string(chat_id_full: str) ->str:
    # обрезаем историю
    try:
        CHATS[chat_id_full] = CHATS[chat_id_full][-cfg.max_hist_lines:]
    except:
        pass

    if chat_id_full in CHATS:
        messages = CHATS[chat_id_full]
        messages2 = []
        for x in messages:
            if x['content'].startswith('[Info to help you answer'):
                end = x['content'].find(']') + 1
                x['content'] = x['content'][end:]
            messages2.append(x)
    prompt = '\n'.join(f'{"𝐔𝐒𝐄𝐑" if i["role"] == "user" else "𝐁𝐎𝐓" if i["role"] == "assistant" else "𝐒𝐘𝐒𝐓𝐄𝐌"} - {i["content"]}\n' for i in messages2) or ''
    prompt = prompt.replace('\n𝐁𝐎𝐓','𝐁𝐎𝐓')
    return prompt


def translate_text(text, fr = 'autodetect', to = 'ru'):
    """переводит текст с помощью GPT-чата, возвращает None при ошибке"""

    # если нет ключа то сразу отбой
    # if not openai.api_key: return None
    
    prompt = f'Исправь явные опечатки в тексте и разорванные строки которые там могли появиться после плохого OCR, переведи текст с языка ({fr}) на язык ({to}), \
разбей переведенный текст на абзацы для удобного чтения по возможности сохранив оригинальное разбиение на строки и абзацы. \
Ссылки и другие непереводимые элементы из текста надо сохранить в переводе. Текст это всё (до конца) что идет после двоеточия. \
Покажи только перевод без оформления и отладочной информации. Текст:'
    prompt += text

    try:
        r = ai(prompt)
    except Exception as e:
        print(e)
        return None
    return r


def clear_after_ocr(text: str) -> str:
    """
	Clears the text after performing OCR to fix obvious errors and typos that may have occurred during the OCR process. 
	Removes completely misrecognized characters and meaningless symbols. 
	Accuracy is important, so it is better to leave an error uncorrected if there is uncertainty about whether it is an error and how to fix it. 
	Preserves the original line and paragraph breaks. 
	Displays the result without formatting and debug information. 

	:param text: The text to be cleared after OCR.
	:type text: str
	:return: The cleared text.
	:rtype: str
    """
    
    return text
    
    prompt = 'Исправь явные ошибки и опечатки в тексте которые там могли появиться после плохого OCR. \
То что совсем плохо распозналось, бессмысленные символы, надо убрать. \
Важна точность, лучше оставить ошибку неисправленной если нет уверенности в том что это ошибка и её надо исправить именно так. \
Важно сохранить оригинальное разбиение на строки и абзацы. \
Не переводи на русский язык. \
Покажи результат без оформления и отладочной информации. Текст:'
    prompt += text
    try:
        r = ai(prompt)
    except Exception as error:
        print(f'gpt_basic.ai:clear_after_ocr: {error}')
        my_log.log2(f'gpt_basic.ai:clear_after_ocr: {error}')
        return text
    my_log.log2(f'gpt_basic.ai:clear_after_ocr:ok: {text}\n\n{r}')
    return r


def detect_ocr_command(text):
    """пытается понять является ли text командой распознать текст с картинки
    возвращает True, False
    """
    keywords = (
    'прочитай', 'читай', 'распознай', 'отсканируй', 'розпізнай', 'скануй', 'extract', 'identify', 'detect', 'ocr',
     'read', 'recognize', 'scan'
    )

    # сначала пытаемся понять по нечеткому совпадению слов
    if any(fuzz.ratio(text, keyword) > 70 for keyword in keywords): return True
    
    # пока что без GPT - ложные срабатывания ни к чему
    return False

    # if not openai.api_key: return False
    
    k = ', '.join(keywords)
    p = f'Пользователь прислал в телеграм чат картинку с подписью ({text}). В чате есть бот которые распознает текст с картинок по просьбе пользователей. \
Тебе надо определить по подписи хочет ли пользователь что бы с этой картинки был распознан текст с помощью OCR или подпись на это совсем не указывает. \
Ответь одним словом без оформления - да или нет или непонятно.'
    r = ai(p).lower().strip(' .')
    print(r)
    if r == 'да': return True
    #elif r == 'нет': return False
    return False


def check_and_fix_text(text):
    """пытаемся исправить странную особенность пиратского GPT сервера (только pawan?),
    он часто делает ошибку в слове, вставляет 2 вопросика вместо буквы"""

    # для винды нет enchant?
    if 'Windows' in utils.platform():
        return text

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

    # если не удалось подобрать слово из словаря то просто убираем этот символ, пусть лучше будет оопечатка чем мусор
    return text.replace('⁂', '')


def zip_text(text: str) -> str:
    """
    Функция для удаления из текста русских и английских гласных букв типа "а", "о", "e" и "a".
    Так же удаляются идущие подряд одинаковые символы
    """
    vowels = [  'о', 'О',        # русские
                'o', 'O']        # английские. не стоит наверное удалять слишком много

    # заменяем гласные буквы на пустую строку, используя метод translate и функцию maketrans
    text = text.translate(str.maketrans('', '', ''.join(vowels)))

    # убираем повторяющиеся символы
    # используем генератор списков для создания нового текста без повторов
    # сравниваем каждый символ с предыдущим и добавляем его, если они разные 
    new_text = "".join([text[i] for i in range(len(text)) if i == 0 or text[i] != text[i-1]])
    
    return new_text


def query_file(query: str, file_name: str, file_size: int, file_text: str) -> str:
    """
    Query a file using the chatGPT model and return the response.

    Args:
        query (str): The query to ask the chatGPT model.
        file_name (str): The name of the file.
        file_size (int): The size of the file in bytes.
        file_text (str): The content of the file.

    Returns:
        str: The response from the chatGPT model.
    """

    msg = f"""Ответь на запрос юзера по содержанию файла
Запрос: {query}
Имя файла: {file_name}
Размер файла: {file_size}
Текст из файла:


{file_text}
"""
    msg_size = len(msg)
    if msg_size > 99000:
        msg = msg[:99000]
        msg_size = 99000

    result = ''

    if msg_size < 15000:
        try:
            result = ai(msg, model_to_use = 'gpt-3.5-turbo-16k')
        except Exception as error:
            print(error)
            my_log.log2(f'gpt_basic:query_file: {error}')

    if not result and msg_size < 30000:
        try:
            result = ai(msg, model_to_use = 'claude-2-100k')
        except Exception as error:
            print(error)
            my_log.log2(f'gpt_basic:query_file: {error}')

    if not result and msg_size <= 99000:
        try:
            result = ai(msg, model_to_use = 'claude-instant-100k')
        except Exception as error:
            print(error)
            my_log.log2(f'gpt_basic:query_file: {error}')

    if not result:
        try:
            result = ai(msg[:15000], model_to_use = 'gpt-3.5-turbo-16k')
        except Exception as error:
            print(error)
            my_log.log2(f'gpt_basic:query_file: {error}')

    return result


def stt_after_repair(text: str) -> str:
    query = f"""Исправь текст, это аудиозапись, в ней могут быть ошибки распознавания речи.
Надо переписать так что бы было понятно что хотел сказать человек и оформить удобно для чтения, разделить на абзацы,
добавить комментарии в неоднозначные места.


{text}
"""
    result = ai(query, model_to_use = 'gpt-3.5-turbo-16k')
    return result


def stt(audio_file: str) -> str:
    """
    Transcribes an audio file to text using OpenAI API.

    Args:
        audio_file (str): The path to the audio file.

    Returns:
        str: The transcribed text.

    Raises:
        FileNotFoundError: If the audio file does not exist.
    """

    #список серверов на которых доступен whisper
    servers = [x for x in cfg.openai_servers if x[2]]

    assert len(servers) > 0, 'No openai whisper servers configured'

    audio_file_fh = open(audio_file, "rb")

    # перемешиваем сервера
    shuffled_servers = servers[:]
    random.shuffle(shuffled_servers)

    for server in shuffled_servers:
        openai.base_url = server[0]
        # openai.api_key = server[1]
        try:
            client = openai.OpenAI(api_key=server[1])
            translation = client.audio.transcriptions.create(
               model="whisper-1",
               file=audio_file_fh
            )
            if translation.text:
                break
        except Exception as error:
            print(error)
            my_log.log2(f'gpt_basic:stt: {error}\n\nServer: {server[0]}')

    return translation.text


def translate_image_prompt(prompt: str) -> str:
    """
    Translates the given image prompt into English if it is not already in English, otherwise leaves it as it is.

    Args:
        prompt (str): The image prompt to be translated.

    Returns:
        str: The translated image prompt in English.
    """
    prompt_tr = ''
    try:
        prompt_tr = ai_instruct(f'Translate into english if it is not english, else leave it as it is: {prompt}')
    except Exception as image_prompt_translate:
        my_log.log2(f'gpt_basic:image_gen:translate_prompt: {str(image_prompt_translate)}\n\n{prompt}')
    prompt_tr = prompt_tr.strip()
    if not prompt_tr:
        try:
            prompt_tr = my_trans.translate_text2(prompt, 'en')
        except Exception as google_translate_error:
            my_log.log2(f'gpt_basic:image_gen:translate_prompt:google_translate: {str(google_translate_error)}\n\n{prompt}')
        if not prompt_tr:
            prompt_tr = prompt
    return prompt_tr


def image_gen(prompt: str, amount: int = 10, size: str ='1024x1024'):
    """
    Generates a specified number of images based on a given prompt.

    Parameters:
        - prompt (str): The text prompt used to generate the images.
        - amount (int, optional): The number of images to generate. Defaults to 10.
        - size (str, optional): The size of the generated images. Must be one of '1024x1024', '512x512', or '256x256'. Defaults to '1024x1024'.

    Returns:
        - list: A list of URLs pointing to the generated images.
    """

    #список серверов на которых доступно рисование
    servers = [x for x in cfg.openai_servers if x[3]]

    # перемешиваем сервера
    shuffled_servers = servers[:]
    random.shuffle(shuffled_servers)

    if len(servers) == 0:
        return []

    # prompt_tr = translate_image_prompt(prompt)
    prompt_tr = prompt

    assert amount <= 10, 'Too many images to gen'
    assert size in ('1024x1024','512x512','256x256'), 'Wrong image size'

    my_log.log2(f'gpt_basic:image_gen: {prompt}\n{prompt_tr}')
    results = []
    for server in shuffled_servers:
        if len(results) >= amount:
            break
        openai.base_url = server[0]
        try:
            client = openai.OpenAI(api_key=server[1])
            response = client.images.generate(
                model="dall-e-3",
                prompt = prompt_tr,
                n = amount,
                size=size,
                quality = 'standard',
            )
            if response:
                results += [x.url for x in response.data]
        except AttributeError:
            pass
        except Exception as error:
            print(error)
            my_log.log2(f'gpt_basic:image_gen: {error}\n\nServer: {server[0]}')
    return results


def get_list_of_models():
    """
    Retrieves a list of models from the OpenAI servers.

    Returns:
        list: A list of model IDs.
    """
    result = []
    for server in cfg.openai_servers:
        openai.base_url = server[0]
        try:
            client = openai.OpenAI(api_key=server[1])
            model_lst = client.models.list()
            for i in model_lst.data:
                result += [i.id,]
        except Exception as error:
            print(error)
            my_log.log2(f'gpt_basic:get_list_of_models: {error}\n\nServer: {server[0]}')
    return sorted(list(set(result)))


def tr(text: str, lang: str = 'ru') -> str:
    """
    Translates text from one language to another.
    """
    return my_trans.translate_text2(text, lang)


def chat(chat_id: str, query: str, user_name: str = 'noname', lang: str = 'ru',
         is_private: bool = True, chat_name: str = 'noname chat') -> str:
    """
    The chat function is responsible for handling user queries and generating responses
    using the ChatGPT model.

    Parameters:
    - chat_id: str, the ID of the chat
    - query: str, the user's query
    - user_name: str, the user's name (default: 'noname')
    - lang: str, the language of the chat (default: 'ru')
    - is_private: bool, indicates whether the chat is private or not (default: True)
    - chat_name: str, the name of the chat (default: 'noname chat')

    Returns:
    - str, the response generated by the ChatGPT model
    """
    if chat_id in CHAT_LOCKS:
        lock = CHAT_LOCKS[chat_id]
    else:
        lock = threading.Lock()
        CHAT_LOCKS[chat_id] = lock

    with lock:
        # в каждом чате своя исотрия диалога бота с юзером
        if chat_id in CHATS:
            messages = CHATS[chat_id]
        else:
            messages = []
        # теперь ее надо почистить что бы влезла в запрос к GPT
        # просто удаляем все кроме max_hist_lines последних
        if len(messages) > cfg.max_hist_lines:
            messages = messages[cfg.max_hist_lines:]
        # удаляем первую запись в истории до тех пор пока общее количество токенов не
        # станет меньше cfg.max_hist_bytes
        # удаляем по 2 сразу так как первая - промпт для бота
        while utils.count_tokens(messages) > cfg.max_hist_bytes:
            messages = messages[2:]
        # добавляем в историю новый запрос и отправляем
        messages = messages + [{"role":    "user",
                                "content": query}]

        formatted_date = datetime.datetime.now().strftime("%d %B %Y %H:%M")

        # в каждом чате своя температура
        if chat_id in TEMPERATURE:
            temp = TEMPERATURE[chat_id]
        else:
            temp = 0

#         # в каждом чате свой собственный промт
#         curr_place = tr('приватный телеграм чат', lang) if is_private else \
# tr('публичный телеграм чат', lang)
#         if not is_private:
#             curr_place = f'{curr_place} "{chat_name}"'
#         sys_prompt = f'{tr("Сейчас ", lang)} {formatted_date} , \
# {tr("ты находишься в ", lang)} {curr_place} \
# {tr("и отвечаешь пользователю с ником", lang)} "{user_name}", \
# {tr("локаль пользователя: ", lang)} "{lang}"'
#         if chat_id in PROMPTS:
#             current_prompt = PROMPTS[chat_id]
#         else:
#             # по умолчанию формальный стиль
#             PROMPTS[chat_id] = [{"role": "system",
#                                  "content": tr(utils.gpt_start_message1, lang)}]
#             current_prompt =   [{"role": "system",
#                                  "content": tr(utils.gpt_start_message1, lang)}]
#         current_prompt = [{"role": "system", "content": sys_prompt}] + current_prompt
        current_prompt = []

        # пытаемся получить ответ
        resp = ''
        try:
            resp = ai(prompt = '', temp = temp, messages = current_prompt + messages,
                      chat_id=chat_id)
            if resp:
                messages = messages + [{"role":    "assistant",
                                        "content": resp}]
            else:
                # не сохраняем диалог, нет ответа
                # если в последнем сообщении нет текста (глюк) то убираем его
                if messages[-1]['content'].strip() == '':
                    messages = messages[:-1]
                CHATS[chat_id] = messages or []
                return tr('ChatGPT не ответил.', lang)
        # бот не ответил или обиделся
        except AttributeError:
            # не сохраняем диалог, нет ответа
            return tr('Не хочу говорить об этом. Или не могу.', lang)
        # произошла ошибка переполнения ответа
        except openai.BadRequestError as error2:
            if """This model's maximum context length is""" in str(error2):
                # чистим историю, повторяем запрос
                p = '\n'.join(f'{i["role"]} - {i["content"]}\n' for i in messages) or \
                    tr('Пусто', lang)
                # сжимаем весь предыдущий разговор до cfg.max_hist_compressed символов
                r = ai_compress(p, cfg.max_hist_compressed, 'dialog')
                messages = [{'role':'system','content':r}] + messages[-1:]
                # и на всякий случай еще
                while utils.count_tokens(messages) > cfg.max_hist_compressed:
                    messages = messages[2:]

                try:
                    resp = ai(prompt = '', temp=temp,
                              messages = current_prompt + messages,
                              chat_id=chat_id)
                except Exception as error3:
                    print(error3)
                    return tr('ChatGPT не ответил.', lang)

                # добавляем в историю новый запрос и отправляем в GPT, если он не
                # пустой, иначе удаляем запрос юзера из истории
                if resp:
                    messages = messages + [{"role":    "assistant",
                                            "content": resp}]
                else:
                    return tr('ChatGPT не ответил.', lang)
            else:
                print(error2)
                return tr('ChatGPT не ответил.', lang)

        # сохраняем диалог, на данном этапе в истории разговора должны быть 2 последних 
        # записи несжатыми
        messages = messages[:-2]
        # если запрос юзера был длинным то в истории надо сохранить его коротко
        if len(query) > cfg.max_hist_mem:
            new_text = ai_compress(query, cfg.max_hist_mem, 'user')
            # заменяем запрос пользователя на сокращенную версию
            messages += [{"role":    "user",
                          "content": new_text}]
        else:
            messages += [{"role":    "user",
                          "content": query}]
        # если ответ бота был длинным то в истории надо сохранить его коротко
        if len(resp) > cfg.max_hist_mem:
            new_resp = ai_compress(resp, cfg.max_hist_mem, 'assistant')
            messages += [{"role":    "assistant",
                          "content": new_resp}]
        else:
            messages += [{"role":    "assistant",
                          "content": resp}]
        CHATS[chat_id] = messages or []

        return resp or tr('ChatGPT не ответил.', lang)


def chat_reset(chat_id: str):
    """
    Reset the chat with the given chat_id.
    
    Parameters:
        chat_id (str): The ID of the chat to reset.
    
    Returns:
        None
    """
    if chat_id in CHATS:
        CHATS[chat_id] = []


def console_chat_test():
    """
    This function is a console chat test. It allows the user to interact with a chatbot
    by entering queries in the console. The function takes no parameters.

    Parameters:
        None

    Returns:
        None
    """
    chat_id = 'test'
    user = 'Маша Борзунова'
    lang = 'ru'
    is_private = False
    chat_name = 'Помощь всем во всём'

    while True:
        query = input('> ')
        if query == 'exit':
            break
        if query == 'clear':
            chat_reset(chat_id=chat_id)
            print('OK')
            continue
        if query == 'mem':
            print('')
            mem = [x for x in CHATS[chat_id]]
            for x in mem:
                print(x)
            print('')
            continue
        response = chat(chat_id='test', query=query, user_name=user, lang=lang,
                        is_private=is_private, chat_name=chat_name)
        print(response)


def check_phone_number(number: str) -> str:
    """проверяет чей номер, откуда звонили"""
    urls = [f'https://zvonili.com/phone/{number}',
            f'https://abonentik.ru/7{number}',
            f'https://www.list-org.com/search?type=phone&val=%2B7{number}'
            ]
    text = my_google.download_text(urls, no_links=True)
    query = f'''
Определи по тексту какой регион, какой оператор, и не связан ли он с мошенничеством,
ответь в удобной для чтения форме с разделением на абзацы и с использованием
жирного текста для акцентирования внимания,
ответь кратко, но если связано с мошенничеством то напиши почему ты так решил подробно.

Номер +7{number}

Текст:

{text}
'''
    response = ai(query)
    return response


def moderation(text: str) -> bool:
    """
    Checks if the given text violates any moderation rules.

    Parameters:
        text (str): The text to be checked for moderation.

    Returns:
        bool: True if the text is flagged for moderation, False otherwise.
    """
    # перемешиваем сервера
    shuffled_servers = cfg.openai_servers[:]
    random.shuffle(shuffled_servers)

    result = False
    for server in shuffled_servers:
        openai.base_url = server[0]
        try:
            client = openai.OpenAI(api_key=server[1])
            response = client.moderations.create(input=text)
            if response:
                result = response.results[0].flagged
                break
        except Exception as error:
            print(error)
            my_log.log2(f'gpt_basic.moderation: {error}\n\nServer: {openai.base_url}')
    return result


def tts(text: str, voice: str = 'alloy', model: str = 'tts-1') -> bytes:
    """
    Generates an audio file from the given text using the TTS API.
    voice = [alloy, echo, fable, onyx, nova, shimmer]
    model = [tts-1, tts-1-hd]

    Parameters:
        text (str): The text to convert to audio.
    """
    # перемешиваем сервера
    shuffled_servers = cfg.openai_servers[:]
    random.shuffle(shuffled_servers)

    for server in shuffled_servers:
        openai.base_url = server[0]

        try:
            client = openai.OpenAI(api_key=server[1])
            response = client.audio.speech.create(
                model=model,
                voice=voice,
                input=text,
                response_format='opus',
                speed=1
            )

            if response.content:
                break
        except Exception as unknown_error1:
            my_log.log2(f'gpt_basic.tts: {unknown_error1}\n\nServer: {server[0]}')
    
    return response.content


def get_balances() -> str:
    """не работает, что то изменилось в API"""
    result = ''
    for server in [x for x in cfg.openai_servers if 'api.openai.com' in x[0]]:
        secret_key = server[1]
        response = requests.get(
            "https://api.openai.com/dashboard/billing/credit_grants",
            headers={"Authorization": "Bearer {}".format(secret_key)},
        )
        if response.status_code == 200:
            credits = response.json()["credits"]
            result += f'{server[1][:6]}: {credits}\n'
        else:
            result += f'{server[1][:6]}: {response.status_code}\n'
    return result


def count_tokens(text: str, model: str = 'gpt-3.5-turbo') -> int:
    """
    Count the number of tokens in the given text using the specified model.

    Parameters:
        text (str): The input text.
        model (str, optional): The name of the model to use for tokenizing. Defaults to 'gpt-3.5-turbo'.

    Returns:
        int: The number of tokens in the text.
    """
    encoding = tiktoken.encoding_for_model(model)
    return len(encoding.encode(text))


def translate_instruct(text: str, lang: str):
    prompt = f"""
Translate the following text to language [{lang}], leave it as is if not sure:

==============
{text}
==============
"""
    result = ai_instruct(prompt)
    return result


if __name__ == '__main__':
    tts_text = """Перси со значением прочистил горло и посмотрел на другой конец стола, где сидели Гарри, Рон и Гермиона:

– Ты знаешь, о чем я, папа. – И чуточку повысил голос: – Сверхсекретное мероприятие.

Рон закатил глаза и пробормотал тихонько:

– Он пытается заставить нас спросить, что за мероприятие, с тех пор как пошел на работу. Не иначе выставка толстодонных котлов.

В центре стола миссис Уизли спорила с Биллом о его серьге – видимо, совсем недавнем приобретении.
"""

    print(count_tokens('раз два три четыре пять'))
    print(count_tokens('One two three four five'))
    print(count_tokens('一二三四五'))
    print(count_tokens('אחד שתיים שלוש ארבע חמש'))
    
    # print(translate_instruct(tts_text, 'ar'))
    # open('1.mp3', 'wb').write(tts('напиши 10 главных героев книги незнайка на луне'))

    # print(ai_instruct('напиши 5 главных героев книги незнайка на луне'))
    # print(ai('напиши 5 главных героев книги незнайка на луне'))
    # print(moderation(''))
    # print(stt('1.ogg'))
    # print(image_gen('командер Спок, приветствие', 1))
    # open('1.ogg', 'wb').write(tts(tts_text, voice='echo', model = 'tts-1-hd'))
    # print(get_balances())
    # print(get_list_of_models())
    # print(count_tokens('Раз два три четыре пять.'))
    # print(count_tokens('One two three four five.'))

    # print(query_file('сколько цифр в файле и какая их сумма', 'test.txt', 100, '1\n2\n2\n1'))

    # for x in range(5, 15):
    #     print(ai(f'1+{x}='))

    # for i in get_list_of_models():
        # print(i)

    #print(ai(open('1.txt', 'r', encoding='utf-8').read()[:15000], max_tok = 2000))

    # print(check_phone_number('9284655834'))
    # console_chat_test()

    sys.exit()

    if len(sys.argv) != 2:
        print("Usage: gptbasic.py filename|'request to qpt'")
        sys.exit(1)
    t = sys.argv[1]
    if os.path.exists(t):
        print(ai(open(t).read(), max_tok = 2000))
    else:
        print(ai(t, max_tok = 2000))
