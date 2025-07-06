#!/usr/bin/env python3
# pip install -U google-genai
# https://github.com/GoogleCloudPlatform/generative-ai/blob/main/gemini/getting-started/intro_gemini_2_0_flash.ipynb
# 
# если недоступно в этой стране то можно попробовать добавить эот в hosts файл
# 50.7.85.220 gemini.google.com
# 50.7.85.220 aistudio.google.com
# 50.7.85.220 generativelanguage.googleapis.com
# 50.7.85.220 alkalimakersuite-pa.clients6.google.com
# 50.7.85.220 notebooklm.google
# 50.7.85.220 notebooklm.google.com

# 50.7.85.220 labs.google
# 50.7.85.220 o.pki.goog


import io
import random
import time
import threading
import traceback
from pprint import pprint

import PIL
from google import genai
from google.genai.types import (
    GenerateContentConfig,
    SafetySetting,
    Part,
    FunctionDeclaration,
    GoogleSearch,
    HarmBlockThreshold,
    HarmCategory,
    ThinkingConfig,
    Tool,
    ToolCodeExecution,
)
from sqlitedict import SqliteDict

import cfg
import my_db
import my_log
import my_skills
import my_skills_general
import utils_llm


TIMEOUT = 120

MAX_REQUEST = 300000

SAFETY_SETTINGS = [
    SafetySetting(
        category="HARM_CATEGORY_DANGEROUS_CONTENT",
        threshold="BLOCK_NONE",
    ),
    SafetySetting(
        category="HARM_CATEGORY_HARASSMENT",
        threshold="BLOCK_NONE",
    ),
    SafetySetting(
        category="HARM_CATEGORY_HATE_SPEECH",
        threshold="BLOCK_NONE",
    ),
    SafetySetting(
        category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
        threshold="BLOCK_NONE",
    ),
]


DEFAULT_MODEL = "gemini-2.0-flash-exp"
DEFAULT_MODEL_FALLBACK = "gemini-2.0-flash-lite-preview-02-05"

# клиенты привязываются к ключам {id:key}
# новая связь образуется случайно для распределения нагрузки на ключи
# и сохраняется до замены ключа, при удалении ключа надо будет удалять его связи
CLIENTS = SqliteDict('db/gemini_clients.db', autocommit=True)
CLIENTS_LOCK = threading.Lock()


def get_client(chat_id: str = "") -> genai.Client:
    """
    Get client by chat_id.

    If `chat_id` is empty, it will be set to 'test'.
    If `chat_id` is not present in `CLIENTS`, a new client with a random API key will be created.
    If `chat_id` is present in `CLIENTS`, the existing client will be returned.

    Args:
        chat_id (str): The chat id to get the client for.

    Returns:
        genai.Client: The client for the given chat id.
    """
    try:
        if not chat_id:
            chat_id = 'test'

        with CLIENTS_LOCK:
            if chat_id not in CLIENTS or not CLIENTS[chat_id]:
                CLIENTS[chat_id] = random.choice(cfg.gemini_keys)
            return genai.Client(api_key=CLIENTS[chat_id])

    except Exception as error:
        raise Exception(f'Failed to get client: {chat_id} {error}')


def get_config(
    system_instruction: str = "",
    max_output_tokens: int = 8000,
    temperature: float = 1,
    tools: list = [],
    ):
    gen_config = GenerateContentConfig(
        temperature=temperature,
        # top_p=0.95,
        # top_k=20,
        # candidate_count=1,
        # seed=5,
        max_output_tokens=max_output_tokens,
        system_instruction=system_instruction,
        safety_settings=SAFETY_SETTINGS,
        tools = tools,
        # stop_sequences=["STOP!"],
        # presence_penalty=0.0,
        # frequency_penalty=0.0,
        )

    return gen_config


def chat2(
    query: str,
    chat_id: str = '',
    temperature: float = 1,
    model: str = '',
    system: str = '',
    max_tokens: int = 8000,
    timeout: int = TIMEOUT
    ) -> str:

    try:
        image = None
        if isinstance(query, str):
            query = query[:MAX_REQUEST]
        elif isinstance(query, list):
            for i in range(len(query)):
                if isinstance(query[i], str):
                    query[i] = query[i][:MAX_REQUEST]
                elif isinstance(query[i], bytes): # image
                    image = io.BytesIO(query[i])
                    break
            query = [x for x in query if isinstance(x, str) or isinstance(x, Part)]

        if temperature < 0:
            temperature = 0
        if temperature > 2:
            temperature = 2
        if max_tokens < 10:
            max_tokens = 10
        if max_tokens > 8000:
            max_tokens = 8000

        if not model:
            model = DEFAULT_MODEL

        if not chat_id:
            chat_id = 'test'

        mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_gemini')) or []

        if system == '':
            system = None

        SKILLS = [
            my_skills.search_google,
            my_skills.download_text_from_url,
            my_skills.calc,
            my_skills_general.get_time_in_timezone,
            my_skills.get_weather,
            my_skills.get_currency_rates,
            ]

        time_start = time.time()
        round_i = 0
        while round_i < 4:
            round_i += 1

            if time.time() > time_start + (timeout-1):
                my_log.log_gemini(f'my_gemini_v2:chat2:1: stop after timeout {round(time.time() - time_start, 2)}\n{model}\n{chat_id}\n{query[:100]}')
                return ''

            client = get_client(chat_id)
            if image:
                file_ = client.files.upload(file = image, config = {'mime_type': 'image/jpg'})
                query.append(Part.from_uri(file_uri=file_.uri, mime_type='image/jpg'))
            chat = client.chats.create(
                model=DEFAULT_MODEL,
                config=get_config(
                    system_instruction=system,
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                    tools = SKILLS,
                )
            )
            chat._curated_history = mem # можно так?

            try:
                resp = chat.send_message(message = query)
            except Exception as error:
                traceback_error = traceback.format_exc()
                my_log.log_gemini(f'my_gemini_v2:chat2:2: {error}\n{model}\n{CLIENTS[chat_id]}\n{query[:100]}\n\n{traceback_error}')
                round_i += 1
                continue

            try:
                result = resp.text
            except Exception as error2:
                if resp.candidates[0].finish_reason:
                    return ''
                traceback_error = traceback.format_exc()
                my_log.log_gemini(f'my_gemini_v2:chat2:3: {error2}\n{model}\n{CLIENTS[chat_id]}\n{resp}\n\n{traceback_error}')
                round_i += 1
                continue

            result = result.strip()

            if result:
                # если в ответе есть отсылка к использованию tool code то оставляем только ее что бы бот мог вызвать функцию
                # if result.startswith('```tool_code') and result.endswith('```'):
                #     result = result[11:-3]
                result = utils_llm.extract_and_replace_tool_code(result)

                my_db.add_msg(chat_id, model)

                my_db.set_user_property(chat_id, 'dialog_gemini', my_db.obj_to_blob(chat._curated_history))

                return result

            round_i += 1

        my_log.log_gemini(f'my_gemini_v2:chat2:4:no results after 4 tries, query: {query}\n{model}')
        return ''
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_gemini(f'my_gemini_v2:chat2:5: {error} {chat_id} {model} {temperature} {system} {max_tokens} {timeout}\n\n{traceback_error}')
        return ''


def reset(chat_id: str, model: str = ''):
    """
    Resets the chat history for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to reset.
        model (str): The model name.

    Returns:
        None
    """
    mem = []
    my_db.set_user_property(chat_id, 'dialog_gemini', my_db.obj_to_blob(mem))


def get_mem_as_string(chat_id: str, md: bool = False, model: str = '') -> str:
    """
    Returns the chat history as a string for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to get the history for.
        md (bool, optional): Whether to format the output as Markdown. Defaults to False.
        model (str, optional): The name of the model.

    Returns:
        str: The chat history as a string.
    """
    if not chat_id:
        chat_id = 'test'

    mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_gemini')) or []

    result = ''
    for x in mem:
        role = x.role
        if role == 'user': role = '𝐔𝐒𝐄𝐑'
        if role == 'model': role = '𝐁𝐎𝐓'
        try:
            if len(x.parts) == 1:
                if  isinstance(x.parts[0].text, str):
                    text = x.parts[0].text.split(']: ', maxsplit=1)[1]
                else:
                    continue
            else:
                text = ''
                for p in x.parts:
                    text += str(p.text) + '\n\n'
                text = text.strip()
                # text = text.split(']: ', maxsplit=1)[1]
        except IndexError:
            if len(x.parts) == 1:
                if isinstance(x.parts[0].text, str):
                    text = x.parts[0].text
                else:
                    continue
            else:
                text = x.parts[-1].text
        if text.startswith('[Info to help you answer'):
            end = text.find(']') + 1
            text = text[end:].strip()
        if md:
            result += f'{role}:\n\n{text}\n\n'
        else:
            result += f'{role}: {text}\n'
        if role == '𝐁𝐎𝐓':
            if md:
                result += '\n\n'
            else:
                result += '\n'
    return result.strip()


def chat_cli(user_id: str = '', model: str = ''):
    reset(user_id, model)
    while 1:
        q = input('>')
        if q == 'mem':
            print(get_mem_as_string(user_id, model = model))
            continue
        elif '.jpg' in q or '.png' in q or '.webp' in q:
            img = PIL.Image.open(open(q, 'rb'))
            q = ['опиши картинку', img]

        r = chat2(q, user_id, model=model)
        print(r)


def test_url():
    video = Part.from_uri(
        file_uri="https://www.youtube.com/watch?v=3KtWfp0UopM",
        mime_type="video/mp4",
    )

    thinking_config = ThinkingConfig(
        include_thoughts=True,
        thinking_budget=10000
    )

    client = get_client()
    response = client.models.generate_content(
        model = 'gemini-2.5-flash-preview-04-17',
        contents=[
            video,
            "перескажи кратко что в видео",
        ],
        config=GenerateContentConfig(
            thinking_config=thinking_config,
        ),
    )

    print(response.text)


if __name__ == "__main__":
    my_db.init(backup=False)

    # print(chat2('привет как дела'))
    # chat_cli()

    # q = [
    #     'опиши картинку',
    #     open(r"C:\Users\user\Downloads\samples for ai\мат задачи 2.jpg" , 'rb').read()
    # ]
    # print(chat2(q))

    # chat._curated_history = [Content[]]
    # Content.role = 'user'|'model'
    # Content.parts = [Part[]]
    # Part.text = 'напиши 1 слово в ответ. 2+2='
    # Part.thought = None

    test_url()

    my_db.close()

