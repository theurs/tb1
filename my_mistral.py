#!/usr/bin/env python3
# pip install -U mistralai pysrt


import base64
import json
import os
import subprocess
import time
import threading
import tempfile
import traceback
from typing import Any, Callable, Dict, List, Optional, Union

import cachetools.func
import openai
import pysrt
from mistralai import Mistral
from mistralai.models import SDKError, TimestampGranularity
from mistralai.extra.exceptions import MistralClientException
from mistralai.types import UNSET
from sqlitedict import SqliteDict

import cfg
import my_db
import my_log
import my_cerebras_tools
import my_split_audio
import utils


BASE_URL = 'https://api.mistral.ai/v1'


# системные сообщения
SYSTEM_ = []


#
# память диалога храниться в базе openrouter тк совместима с ним
#
#

# сколько запросов хранить
MAX_MEM_LINES = 20
MAX_HIST_CHARS = 60000


# блокировка чатов что бы не испортить историю
# {id:lock}
LOCKS = {}

# каждый юзер дает свои ключи и они используются совместно со всеми
# каждый ключ дает всего 500000 токенов в минуту так что чем больше тем лучше
# {full_chat_id as str: key}
# {'[9123456789] [0]': 'key', ...}
ALL_KEYS = []
USER_KEYS = SqliteDict('db/mistral_user_keys.db', autocommit=True)
USER_KEYS_LOCK = threading.Lock()
CURRENT_KEYS_SET_LOCK = threading.Lock()

# не принимать запросы больше чем, это ограничение для телеграм бота, в этом модуле оно не используется
MAX_REQUEST = 40000

# максимальный размер суммаризации
# MAX_SUM_REQUEST = 128*1000*3 # 128k tokens, 3 char per token
MAX_SUM_REQUEST = 100000


DEFAULT_MODEL = 'mistral-large-latest'
FALLBACK_MODEL = 'mistral-medium-latest'
CODE_MODEL = 'codestral-latest'
CODE_MODEL_FALLBACK = 'codestral-2405'
VISION_MODEL = 'pixtral-large-latest'
SMALL_MODEL = 'mistral-small-latest'
MEDIUM_MODEL = 'mistral-medium-latest'
OCR_MODEL = 'mistral-ocr-latest'
MAGISTRAL_MODEL = 'magistral-medium-latest'
MAGISTRAL_MODEL_SMALL = 'magistral-small-latest'


CURRENT_KEYS_SET = []


SPEECH_TO_TEXT_LOCK = threading.Lock()



def get_weather(city: str):
    """Получить текущую погоду для указанного города."""
    # Это фиктивная реализация
    return f"Погода в городе {city} солнечная, 25 градусов по Цельсию."


def calculator(expression: str):
    """Вычислить математическое выражение."""
    try:
        # ... реализация ...
        return str(eval(expression, {'__builtins__': {}}, {}))
    except Exception as e:
        return f"Ошибка при вычислении выражения: {e}"


# def get_next_key() -> str:
#     '''
#     Return round robin key from ALL_KEYS
#     '''
#     global CURRENT_KEYS_SET
#     if not CURRENT_KEYS_SET:
#         if ALL_KEYS:
#             CURRENT_KEYS_SET = ALL_KEYS[:]

#     if CURRENT_KEYS_SET:
#         return CURRENT_KEYS_SET.pop(0)
#     else:
#         raise Exception('mistral_keys is empty')


def get_next_key() -> str:
    '''
    Return round robin key from ALL_KEYS
    '''
    with CURRENT_KEYS_SET_LOCK: # ADDED LOCK
        global CURRENT_KEYS_SET
        if not CURRENT_KEYS_SET:
            if ALL_KEYS:
                CURRENT_KEYS_SET = ALL_KEYS[:]

        if CURRENT_KEYS_SET:
            return CURRENT_KEYS_SET.pop(0)
        else:
            # Raising an exception is better than returning empty string
            # as it indicates a configuration problem.
            raise ValueError('mistral_keys is empty')


# def ai(
#     prompt: str = '',
#     mem = None,
#     user_id: str = '',
#     system: str = '',
#     model = '',
#     temperature: float = 1,
#     max_tokens: int = 8000,
#     timeout: int = 120,
#     key_: str = '',
#     json_output: bool = False,
#     use_skills: bool = False
#     ) -> str:

#     if not len(ALL_KEYS) and not key_:
#         return ''

#     if not model:
#         model = DEFAULT_MODEL

#     messages = list(mem) if mem is not None else []

#     # Системные промпты (без изменений)
#     now = utils.get_full_time()
#     systems = (
#         f'Current date and time: {now}\n',
#         f'Telegram user id you talking with: {user_id}\n',
#         'Ask again if something is unclear in the request\n',
#         'You (assistant) are currently working in a Telegram bot. The Telegram bot automatically extracts text from any type of files sent to you by the user, such as documents, images, audio recordings, etc., so that you can fully work with any files.\n',
#         "If the user's request cannot be fulfilled using the available tools or direct actions, the assistant(you) must treat the request as a request to generate text (e.g., providing code as text), not a request to perform an action (e.g., executing code or interacting with external systems not directly supported by tools) (intention mismatch).\n",
#         "To edit image user can send image with caption starting ! symbol\n",
#     )

#     if system:
#         messages.insert(0, {"role": "system", "content": system})
#     for s in reversed(systems):
#         messages.insert(0, {"role": "system", "content": s})
#     if prompt:
#         messages.append({"role": "user", "content": prompt})

#     text = ''
#     key = ''
#     start_time = time.time()

#     # Внешний цикл для повторных попыток при ошибках сети
#     for _ in range(3):
#         time_left = timeout - (time.time() - start_time)
#         if time_left <= 0:
#             my_log.log_mistral(f'ai:0: timeout | {key} | {user_id}\n\n{model}\n\n{prompt}')
#             break

#         try:
#             key = get_next_key() if not key_ else key_
#             client = openai.OpenAI(api_key=key, base_url=BASE_URL)

#             # --- Начало новой логики с циклом для многошаговых вызовов ---

#             MAX_TOOL_CALL_STEPS = 5 # Предохранитель от бесконечных циклов
#             for _ in range(MAX_TOOL_CALL_STEPS):
                
#                 api_params = {
#                     'model': model,
#                     'messages': messages,
#                     'temperature': int(temperature/2),
#                     'max_tokens': max_tokens,
#                     'timeout': int(time_left),
#                 }

#                 if json_output:
#                     api_params['response_format'] = {"type": "json_object"}
#                 elif use_skills:
#                     api_params['tools'] = tools
#                     api_params['tool_choice'] = "auto"

#                 response = client.chat.completions.create(**api_params)
#                 response_message = response.choices[0].message
#                 tool_calls = response_message.tool_calls

#                 # Если модель запросила вызов инструментов
#                 if tool_calls:
#                     time.sleep(1)
#                     # Добавляем ответ ассистента (с намерением вызвать инструменты) в историю
#                     messages.append(response_message)

#                     # Выполняем все запрошенные инструменты
#                     for tool_call in tool_calls:
#                         function_name = tool_call.function.name
#                         function_to_call = available_tools.get(function_name)

#                         if function_to_call:
#                             try:
#                                 function_args = json.loads(tool_call.function.arguments)
#                                 function_response = function_to_call(**function_args)
#                                 messages.append({
#                                     "tool_call_id": tool_call.id,
#                                     "role": "tool",
#                                     "name": function_name,
#                                     "content": function_response,
#                                 })
#                             except Exception as e:
#                                 my_log.log_mistral(f"Error executing tool {function_name}: {e}")
#                                 messages.append({
#                                     "tool_call_id": tool_call.id,
#                                     "role": "tool",
#                                     "name": function_name,
#                                     "content": f"Error: {e}",
#                                 })
#                         else:
#                              messages.append({
#                                 "tool_call_id": tool_call.id,
#                                 "role": "tool",
#                                 "name": function_name,
#                                 "content": f"Error: Tool '{function_name}' not found.",
#                             })
#                     # Продолжаем цикл для следующего шага
#                     continue

#                 # Если вызовов инструментов нет - это финальный ответ
#                 else:
#                     text = response_message.content.strip() if response_message.content else ''
#                     break # Выходим из цикла многошаговых вызовов

#             # --- Конец новой логики ---

#             if text:
#                 if user_id:
#                     my_db.add_msg(user_id, model)
#                 break  # Выходим из внешнего цикла повторных попыток

#             # Если вышли из цикла по лимиту шагов, а текста нет
#             if not text:
#                  my_log.log_mistral(f'ai: Exceeded max tool steps ({MAX_TOOL_CALL_STEPS}) | {key} | {user_id}')
#                  break # Прерываем попытки

#         except Exception as error2:
#             if 'The maximum context length' in str(error2):
#                 messages = [msg for msg in messages if msg['role'] == 'system']
#                 messages += (mem or [])[-4:] # Берем только последние сообщения
#                 if prompt: messages.append({"role": "user", "content": prompt})
#                 continue # Повторяем попытку с урезанной историей
#             if 'Unauthorized' in str(error2):
#                 if not key_:
#                     remove_key(key)
#                     my_log.log_mistral(f'ai:2: {error2} | {key} | {user_id}')
#                 else:
#                     return ''
#             my_log.log_mistral(f'ai:3: {error2} | {key} | {user_id}\n\n{model}\n\n{prompt}')
#             time.sleep(2)

#     # Вызов резервной модели, если основная не справилась
#     if not text and model == DEFAULT_MODEL:
#         # Убедимся, что не передаем историю с вызовами инструментов в резервную модель
#         final_mem = list(mem) if mem is not None else []
#         return ai(prompt, final_mem, user_id, system, FALLBACK_MODEL, temperature, max_tokens, time_left, key_, json_output)

#     return text


def ai(
    prompt: str = '',
    mem: Optional[List[Dict[str, Any]]] = None,
    user_id: str = '',
    system: str = '',
    model: str = '',
    temperature: float = 1.0,
    max_tokens: int = 8000,
    timeout: int = 120,
    response_format: Optional[Dict[str, Any]] = None,
    tools: Optional[List[Dict]] = None,
    available_tools: Optional[Dict[str, Callable]] = None,
    tool_choice: Optional[str] = None,
    key_: str = '',
) -> str:
    """
    Sends a request to the Mistral AI API with tool-use and retry logic.

    Args:
        prompt (str, optional): The user's input. Defaults to ''.
        mem (Optional[List[Dict[str, Any]]], optional): Conversation history. Defaults to None.
        user_id (str, optional): Unique user identifier. Defaults to ''.
        system (str, optional): System-level instructions. Defaults to ''.
        model (str, optional): The model to use. Defaults to DEFAULT_MODEL.
        temperature (float, optional): Controls randomness (0.0-2.0). Defaults to 1.0.
        max_tokens (int, optional): Max tokens in the final response. Defaults to 8000.
        timeout (int, optional): Timeout in seconds for each API call. Defaults to 120.
        response_format (Optional[Dict[str, Any]], optional): Enforces a response format, e.g., {"type": "json_object"}. Defaults to None.
        tools (Optional[List[Dict]], optional): A list of tool schemas for the model. Defaults to None.
        available_tools (Optional[Dict[str, Callable]], optional): A map of tool names to their Python functions. Defaults to None.
        tool_choice (Optional[str], optional): Controls tool usage ('auto', 'any', 'none'). Defaults to 'auto' if tools are provided.
        key_ (str, optional): A specific API key to use, bypassing the key pool. Defaults to ''.

    Returns:
        str: The AI's response, or an empty string on failure.
    """
    if not ALL_KEYS and not key_:
        my_log.log_mistral('ai: No API keys available.')
        return ''

    if not model:
        model = DEFAULT_MODEL

    # Initialize messages from memory
    messages: List[Dict[str, Any]] = list(mem) if mem is not None else []

    # Inject system prompts
    now = utils.get_full_time()
    system_prompts = [
        f'Current date and time: {now}',
        f'Telegram user id you are talking with: {user_id}',
        *SYSTEM_
        # 'You (assistant) are currently working in a Telegram bot. The Telegram bot automatically extracts text from any type of files sent to you by the user, such as documents, images, audio recordings, etc., so that you can fully work with any files.',
        # "If the user's request cannot be fulfilled using the available tools or direct actions, the assistant(you) must treat the request as a request to generate text (e.g., providing code as text), not a request to perform an action (e.g., executing code or interacting with external systems not directly supported by tools) (intention mismatch).",
        # "To edit an image, the user can send an image with a caption starting with the '!' symbol.",
    ]
    if system:
        messages.insert(0, {"role": "system", "content": system})
    for s in reversed(system_prompts):
        messages.insert(0, {"role": "system", "content": s})

    # Add user prompt if provided
    if prompt:
        messages.append({"role": "user", "content": prompt})

    text = ''
    api_key = ''
    start_time = time.time()

    # Outer loop for network retries
    for attempt in range(3):
        time_left = timeout - (time.time() - start_time)
        if time_left <= 0:
            my_log.log_mistral(f'ai: Global timeout exceeded | {api_key} | {user_id}')
            break

        try:
            api_key = key_ if key_ else get_next_key()
            client = openai.OpenAI(api_key=api_key, base_url=BASE_URL)

            # Inner loop for multi-step tool calls
            MAX_TOOL_CALL_STEPS = 5  # Safety break to prevent infinite loops
            for _ in range(MAX_TOOL_CALL_STEPS):
                # Prepare API parameters for this step
                api_params: Dict[str, Any] = {
                    'model': model,
                    'messages': messages,
                    'temperature': temperature / 2, # Mistral prefers lower temp
                    'max_tokens': max_tokens,
                    'timeout': int(time_left),
                }

                if response_format:
                    api_params['response_format'] = response_format

                # Enable tools if they are provided
                if tools and available_tools:
                    api_params['tools'] = tools
                    # Default to 'auto' if not specified, allowing the model to decide
                    api_params['tool_choice'] = tool_choice or "auto"

                # Make the API call
                response = client.chat.completions.create(**api_params)
                response_message = response.choices[0].message
                tool_calls = response_message.tool_calls

                # If the model requested tool calls, process them
                if tool_calls:
                    # Append the assistant's response (requesting the tool) to history
                    messages.append(response_message)

                    # Execute all requested tools
                    for tool_call in tool_calls:
                        function_name = tool_call.function.name
                        function_to_call = available_tools.get(function_name)

                        tool_output = ''
                        if function_to_call:
                            try:
                                function_args = json.loads(tool_call.function.arguments)
                                tool_output = function_to_call(**function_args)
                            except Exception as e:
                                error_msg = f"Error executing tool {function_name}: {e}"
                                my_log.log_mistral(error_msg)
                                tool_output = error_msg
                        else:
                            tool_output = f"Error: Tool '{function_name}' not found."

                        # Append the tool's result to history
                        messages.append({
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": function_name,
                            "content": str(tool_output), # Ensure content is a string
                        })
                    # Continue the loop to get the next response from the model
                    continue

                # If no tool calls, this is the final answer
                else:
                    text = response_message.content.strip() if response_message.content else ''
                    break  # Exit the tool-use loop

            # If the loop finished, we have our final text or it timed out
            if text:
                break  # Exit the outer retry loop

            # If loop exited due to max steps without a final answer
            if not text:
                my_log.log_mistral(f'ai: Exceeded max tool steps ({MAX_TOOL_CALL_STEPS}) | {api_key} | {user_id}')
                break # Stop retrying, this is a logic issue

        except Exception as error:
            error_str = str(error)
            if 'The maximum context length' in error_str:
                # Prune history and retry
                system_msgs = [msg for msg in messages if msg.get('role') == 'system']
                user_history = [msg for msg in messages if msg.get('role') != 'system']
                messages = system_msgs + user_history[-4:]
                continue
            if 'Unauthorized' in error_str:
                if not key_:
                    remove_key(api_key)
                my_log.log_mistral(f'ai: Unauthorized key removed | {api_key} | {user_id}')
                # For unauthorized, we retry with a new key immediately in the next loop iteration
            else:
                my_log.log_mistral(f'ai: Unexpected error on attempt {attempt+1} | {error} | {api_key} | {user_id}')
                if attempt < 2:
                    time.sleep(2) # Wait before the next retry

    # Fallback logic if the primary model failed and no text was generated
    if not text and model == DEFAULT_MODEL:
        my_log.log_mistral(f"ai: Primary model '{model}' failed. Falling back to '{FALLBACK_MODEL}'.")
        # Use original memory for fallback to avoid sending complex tool history
        fallback_mem = list(mem) if mem is not None else []
        return ai(prompt, fallback_mem, user_id, system, FALLBACK_MODEL, temperature, max_tokens, int(time_left), key_=key_, response_format=response_format)

    return text


def img2txt(
    image_data: bytes,
    prompt: str = 'Describe picture',
    model = VISION_MODEL,
    temperature: float = 1,
    max_tokens: int = 8000,
    timeout: int = 120,
    chat_id: str = '',
    system: str = '',
    ) -> str:
    """
    Describes an image using the specified model and parameters.

    Args:
        image_data: The image data as bytes.
        prompt: The prompt to guide the description. Defaults to 'Describe picture'.
        model: The model to use for generating the description. Defaults to VISION_MODEL.
        temperature: The temperature parameter for controlling the randomness of the output. Defaults to 1.
        max_tokens: The maximum number of tokens to generate. Defaults to 8000.
        timeout: The timeout for the request in seconds. Defaults to 120.

    Returns:
        A string containing the description of the image, or an empty string if an error occurs.
    """
    if not len(ALL_KEYS):
        return ''

    if not model:
        model = VISION_MODEL

    if isinstance(image_data, str):
        with open(image_data, 'rb') as f:
            image_data = f.read()

    img_base = base64.b64encode(image_data).decode('utf-8')

    mem = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": prompt
                },
                {
                    "type": "image_url",
                    "image_url": f"data:image/jpeg;base64,{img_base}" 
                }
            ]
        }
    ]
    if system:
        mem.insert(0, {'role': 'system', 'content': system})

    key = ''
    for _ in range(3):
        try:
            key = get_next_key()
            client = openai.OpenAI(
                api_key = key,
                base_url = BASE_URL,
            )
            response = client.chat.completions.create(
                model = model,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                messages = mem,
            )
            result = response.choices[0].message.content
            if chat_id:
                my_db.add_msg(chat_id, model)
            break
        except Exception as error:
            if 'Unauthorized' in str(error):
                remove_key(key)
                my_log.log_mistral(f'img2txt: {error} {key}')
            my_log.log_mistral(f'img2txt: Failed to parse response: {error}')
            result = ''
            time.sleep(2)

    return result


def _clear_ocred_text(text: str) -> str:
    return text.strip().replace('\\#', '#')


@cachetools.func.ttl_cache(maxsize=10, ttl=1 * 60)
def ocr_image(
    image_data: bytes,
    timeout: int = 120,
    ) -> str:
    '''
    Use OCR to extract text from an image

    Args:
        image_data: The image data as bytes or file name.
        timeout: The timeout for the request in seconds. Defaults to 120.

    Returns:
        A string containing the description of the image, or an empty string if an error occurs.
    '''
    api_key = ''
    try:
        if not len(ALL_KEYS):
            return ''

        if isinstance(image_data, str):
            with open(image_data, 'rb') as f:
                image_data = f.read()

        base64_image = base64.b64encode(image_data).decode('utf-8')

        api_key = get_next_key()
        client = Mistral(api_key=api_key)

        ocr_response = client.ocr.process(
            timeout_ms=timeout * 1000,
            include_image_base64=False,
            model="mistral-ocr-latest",
            document={
                "type": "image_url",
                "image_url": f"data:image/jpeg;base64,{base64_image}" 
            }
        )
        resp = ''
        for page in ocr_response.pages:
            resp += page.markdown.strip()
            resp += '\n'

        return _clear_ocred_text(resp)

    except Exception as error:
        if 'Unauthorized' in str(error):
            remove_key(api_key)
            return ocr_image(image_data, timeout)
        my_log.log_mistral(f'ocr_image:ocr: {error}')
        return ''


@cachetools.func.ttl_cache(maxsize=10, ttl=1 * 60)
def ocr_pdf(
    image_data: bytes,
    timeout: int = 300,
    ) -> str:
    '''
    Use OCR to extract text from an image

    Args:
        image_data: The pdf data as bytes or file name.
        timeout: The timeout for the request in seconds. Defaults to 120.

    Returns:
        A string containing the description of the image, or an empty string if an error occurs.
    '''
    tmp_fname = ''
    client = None
    uploaded_pdf = None
    api_key = ''
    try:
        if not len(ALL_KEYS):
            return ''

        if isinstance(image_data, str):
            with open(image_data, 'rb') as f:
                image_data = f.read()

        tmp_fname = utils.get_tmp_fname() + '.pdf'
        with open(tmp_fname, 'wb') as f:
            f.write(image_data)

        api_key = get_next_key()
        client = Mistral(api_key=api_key)

        uploaded_pdf = client.files.upload(
            timeout_ms = 60 * 1000, # минуту на загрузку
            file={
                "file_name": tmp_fname,
                "content": open(tmp_fname, "rb"),
            },
            purpose="ocr"
        )  

        signed_url = client.files.get_signed_url(file_id=uploaded_pdf.id)

        ocr_response = client.ocr.process(
            model="mistral-ocr-latest",
            include_image_base64 = False,
            timeout_ms=timeout * 1000,
            document={
                "type": "document_url",
                "document_url": signed_url.url,
            }
        )

        client.files.delete(file_id=uploaded_pdf.id, timeout_ms = 30 * 1000)
        utils.remove_file(tmp_fname)

        resp = ''
        for page in ocr_response.pages:
            resp += page.markdown.strip()
            resp += '\n'

        return _clear_ocred_text(resp)

    except Exception as error:
        if tmp_fname:
            utils.remove_file(tmp_fname)
        if client and uploaded_pdf:
            client.files.delete(file_id=uploaded_pdf.id, timeout_ms = timeout * 1000)

        if 'Unauthorized' in str(error):
            remove_key(api_key)
            return ocr_pdf(image_data, timeout)

        my_log.log_mistral(f'ocr_image:ocr_pdf: {error}')
        return ''


def format_to_srt(transcription_result: dict) -> str:
    """
    Преобразует результат транскрибации от API Mistral в формат субтитров SRT,
    используя библиотеку pysrt.

    Args:
        transcription_result: Словарь (dict), полученный от функции transcribe_audio 
                              с параметром get_timestamps=True.

    Returns:
        Строку с содержимым в формате .srt или пустую строку, если входные данные неверны.
    """
    if not isinstance(transcription_result, dict) or 'segments' not in transcription_result:
        my_log.log_mistral('format_to_srt: Invalid input, expected a dict with a "segments" key.')
        return ""

    subs = pysrt.SubRipFile()

    for i, segment in enumerate(transcription_result['segments'], start=1):
        sub = pysrt.SubRipItem(
            index=i,  # Явно зададим индекс для надежности
            start=pysrt.SubRipTime(seconds=segment['start']),
            end=pysrt.SubRipTime(seconds=segment['end']),
            text=segment['text'].strip()
        )
        subs.append(sub)

    srt_content = "\n\n".join(str(item) for item in subs)

    # Добавим финальный перенос строки для соответствия стандарту
    if srt_content:
        srt_content += "\n"

    return srt_content


def _call_mistral_api(
    audio_bytes: bytes,
    language: str | None,
    get_timestamps: bool,
    timeout: int
) -> Union[dict, None]:
    """
    Вызывает Mistral API. Возвращает полный JSON-ответ (dict) при успехе
    или None в случае ошибки.
    """
    with SPEECH_TO_TEXT_LOCK:
        if not ALL_KEYS:
            my_log.log_mistral('transcribe_audio: No keys available.')
            return None

        MAX_RETRIES = 3
        RETRY_DELAY = 5
        RETRY_DELAY_500 = 60

        for attempt in range(MAX_RETRIES):
            api_key = get_next_key()
            if not api_key:
                my_log.log_mistral('transcribe_audio: No API key retrieved from get_next_key().')
                return None

            try:
                client = Mistral(api_key=api_key)

                file_data = {
                    "content": audio_bytes,
                    "file_name": "audio.wav",
                }

                timestamp_granularities_param: Optional[List[TimestampGranularity]] = \
                    [TimestampGranularity.SEGMENT] if get_timestamps else None

                timeout_ms_param = timeout * 1000

                transcription_response = client.audio.transcriptions.complete(
                    model="voxtral-mini-latest",
                    file=file_data,
                    language=language if language is not None else UNSET,
                    timestamp_granularities=timestamp_granularities_param,
                    timeout_ms=timeout_ms_param
                )

                return transcription_response.model_dump()

            except SDKError as e:
                if e.status_code == 401:
                    my_log.log_mistral(f'_call_mistral_api: Unauthorized key {api_key}')
                    continue # Try with next API key if unauthorized
                elif e.status_code == 500:
                    my_log.log_mistral(f'_call_mistral_api: HTTP error ({e.status_code}): Retrying after {RETRY_DELAY_500} seconds...')
                    time.sleep(RETRY_DELAY_500)
                    continue # Retry after a longer delay for server errors
                my_log.log_mistral(f'_call_mistral_api: Mistral API HTTP error ({e.status_code}): {e.message} - {e.body}')
                if e.status_code < 500: # For other client errors (e.g., 400 Bad Request), do not retry
                    return None
            except MistralClientException as e:
                my_log.log_mistral(f'_call_mistral_api: Mistral client error: {e}. Retrying...')
            except Exception as e:
                my_log.log_mistral(f'_call_mistral_api: Unexpected error: {e}')
                return None

            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)

        my_log.log_mistral(f'_call_mistral_api: Failed after {MAX_RETRIES} retries.')
        return None


def _get_audio_duration(file_path: str) -> float | None:
    """Получает длительность аудио в секундах с помощью ffprobe."""
    command = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except Exception as e:
        my_log.log_mistral(f"_get_audio_duration: Failed for '{file_path}': {e}")
        return None


MAX_TRANSCRIBE_SECONDS = 4 * 60 * 60
def transcribe_audio(
    audio_data: bytes|str,
    language: str | None = None,
    get_timestamps: bool = False,
    timeout: int = 300
) -> str:
    """
    Транскрибирует аудиофайл. Если файл больше 10 минут, он нарезается на части.

    Args:
        audio_data (bytes|str): Аудиофайл в байтовом или строковом формате.
        language (str, optional): Язык, на котором требуется транскрибировать. Defaults to None.
        get_timestamps (bool, optional): Флаг, указывающий, нужно ли возвращать субтитры. Defaults to False.

    Returns:
        - Если get_timestamps=False: Распознанный текст (str).
        - Если get_timestamps=True: Субтитры в формате SRT (str). !!Нормально не работает, по-этому принудительно отключается пока
        - В случае ошибки возвращает пустую строку.
    """
    # !!Нормально не работает, по-этому принудительно отключается пока
    get_timestamps = False

    MAX_DURATION_SECONDS = 10 * 60

    temp_file_path = None
    chunks_dir = None

    try:
        if isinstance(audio_data, bytes):
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as fp:
                fp.write(audio_data)
                temp_file_path = fp.name
            input_file_path = temp_file_path
        else:
            input_file_path = audio_data

        if not os.path.exists(input_file_path):
            my_log.log_mistral(f'transcribe_audio: Input file not found: {input_file_path}')
            return ""

        duration = _get_audio_duration(input_file_path)
        if duration is None:
            return ""

        # --- ПУТЬ A: Файл большой, требует нарезки и сборки ---
        if duration > MAX_DURATION_SECONDS:
            # my_log.log_mistral(f"Audio duration ({duration}s) > {MAX_DURATION_SECONDS}s. Splitting.")

            chunk_paths = my_split_audio.split_audio_by_silence(
                input_audio_file=input_file_path,
                target_duration_seconds=MAX_DURATION_SECONDS
            )
            if not chunk_paths:
                my_log.log_mistral("Failed to split audio. Aborting.")
                return ""

            chunks_dir = os.path.dirname(chunk_paths[0])
            all_transcriptions = []
            cumulative_offset = 0.0  # Суммарная длительность предыдущих чанков

            # Контейнер для всех субтитров из всех чанков
            final_srt = pysrt.SubRipFile()

            for i, chunk_path in enumerate(chunk_paths):
                with open(chunk_path, 'rb') as f:
                    chunk_bytes = f.read()

                transcription_result = _call_mistral_api(chunk_bytes, language, get_timestamps, timeout)

                if transcription_result is None or 'segments' not in transcription_result:
                    my_log.log_mistral(f"Failed to transcribe chunk {chunk_path}. Aborting.")
                    return ""

                # Если нужен только текст, просто добавляем его в список
                if not get_timestamps:
                    all_transcriptions.append(transcription_result.get('text', '').strip())
                # Если нужны субтитры, обрабатываем сегменты со смещением
                else:
                    for segment in transcription_result['segments']:
                        sub = pysrt.SubRipItem(
                            start=pysrt.SubRipTime(seconds=(cumulative_offset + segment['start'])),
                            end=pysrt.SubRipTime(seconds=(cumulative_offset + segment['end'])),
                            text=segment['text'].strip()
                        )
                        final_srt.append(sub)

                # Обновляем смещение, добавляя длительность ТЕКУЩЕГО чанка
                chunk_duration = _get_audio_duration(chunk_path)
                if chunk_duration:
                    cumulative_offset += chunk_duration
                else:
                    my_log.log_mistral(f"Could not get duration for chunk {chunk_path}. Timestamps will be incorrect.")

            # Возвращаем результат в зависимости от get_timestamps
            if not get_timestamps:
                return "\n\n".join(all_transcriptions)
            else:
                final_srt.clean_indexes() # Перенумеровываем индексы (1, 2, 3...)
                # Правильное формирование строки SRT из объектов SubRipItem
                srt_content = "\n\n".join(str(item) for item in final_srt)
                if srt_content:
                    srt_content += "\n" # Добавляем финальный перенос строки, как в формате SRT
                return srt_content


        # --- ПУТЬ B: Файл маленький, обрабатываем напрямую ---
        else:
            # my_log.log_mistral(f"Audio duration ({duration}s) is within limit. Direct transcription.")
            with open(input_file_path, 'rb') as f:
                file_bytes = f.read()

            result = _call_mistral_api(file_bytes, language, get_timestamps, timeout)

            if result is None:
                return ""

            if not get_timestamps:
                return result.get('text', '').strip()
            else:
                # Используем вашу существующую функцию для простого случая
                return format_to_srt(result)

    except Exception as e:
        my_log.log_mistral(f"transcribe_audio: Unexpected error in main block: {e}")
        return ""

    finally:
        # Гарантированная очистка временных файлов
        if temp_file_path and os.path.exists(temp_file_path):
            utils.remove_file(temp_file_path)
        if chunks_dir and os.path.exists(chunks_dir):
            utils.remove_dir(chunks_dir)


def clear_mem(mem, user_id: str):
    while 1:
        sizeofmem = count_tokens(mem)
        if sizeofmem <= MAX_HIST_CHARS:
            break
        try:
            mem = mem[2:]
        except IndexError:
            mem = []
            break

    return mem[-MAX_MEM_LINES*2:]


def count_tokens(mem) -> int:
    return sum([len(m['content']) for m in mem])


def update_mem(query: str, resp: str, chat_id: str):
    mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_openrouter')) or []
    mem += [{'role': 'user', 'content': query}]
    mem += [{'role': 'assistant', 'content': resp}]
    mem = clear_mem(mem, chat_id)

    mem__ = []
    try:
        i = 0
        while i < len(mem):
            if i == 0 or mem[i] != mem[i-1]:
                mem__.append(mem[i])
            i += 1
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_mistral(f'update_mem: {error}\n\n{error_traceback}\n\n{query}\n\n{resp}\n\n{mem}')

    my_db.set_user_property(chat_id, 'dialog_openrouter', my_db.obj_to_blob(mem__))


def chat(
    query: str,
    chat_id: str = '',
    temperature: float = 1,
    system: str = '',
    model: str = '',
    do_not_update_history: bool = False,
    timeout: int = 120,
    tools: Optional[List[Dict]] = None,
    available_tools: Optional[Dict[str, Callable]] = None,
    tool_choice: Optional[str] = None,
    ) -> str:
    global LOCKS
    if chat_id in LOCKS:
        lock = LOCKS[chat_id]
    else:
        lock = threading.Lock()
        LOCKS[chat_id] = lock
    with lock:
        mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_openrouter')) or []
        mem_ = mem[:]

        text = ai(
            query,
            mem_,
            user_id=chat_id,
            temperature = temperature,
            system=system,
            model=model,
            timeout=timeout,
            tools=tools,
            available_tools=available_tools,
            tool_choice=tool_choice,
        )

        if text and not do_not_update_history:
            mem += [{'role': 'user', 'content': query}]
            mem += [{'role': 'assistant', 'content': text}]
            mem = clear_mem(mem, chat_id)
            my_db.set_user_property(chat_id, 'dialog_openrouter', my_db.obj_to_blob(mem))
        return text
    return ''


def chat_cli(
    model: str = '',
    tools: Optional[List[Dict]] = None,
    available_tools: Optional[Dict[str, Callable]] = None,
    tool_choice: Optional[str] = None,
):
    reset('test')
    while 1:
        q = input('>')
        if q == 'mem':
            print(get_mem_as_string('test'))
            continue
        r = chat(
            q,
            'test',
            model = model,
            system='отвечай всегда по-русски',
            tools=tools,
            available_tools=available_tools,
            tool_choice=tool_choice,
        )
        print(r)


def force(chat_id: str, text: str):
    '''update last bot answer with given text'''
    try:
        if chat_id in LOCKS:
            lock = LOCKS[chat_id]
        else:
            lock = threading.Lock()
            LOCKS[chat_id] = lock
        with lock:
            mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_openrouter')) or []
            if mem and len(mem) > 1:
                mem[-1]['content'] = text
                my_db.set_user_property(chat_id, 'dialog_openrouter', my_db.obj_to_blob(mem))
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_mistral(f'force:Failed to force message in chat {chat_id}: {error}\n\n{error_traceback}')


def undo(chat_id: str):
    """
    Undo the last two lines of chat history for a given chat ID.

    Args:
        chat_id (str): The ID of the chat.

    Raises:
        Exception: If there is an error while undoing the chat history.

    Returns:
        None
    """
    try:
        if chat_id in LOCKS:
            lock = LOCKS[chat_id]
        else:
            lock = threading.Lock()
            LOCKS[chat_id] = lock
        with lock:
            mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_openrouter')) or []
            # remove 2 last lines from mem
            mem = mem[:-2]
            my_db.set_user_property(chat_id, 'dialog_openrouter', my_db.obj_to_blob(mem))
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_mistral(f'undo: Failed to undo chat {chat_id}: {error}\n\n{error_traceback}')


def reset(chat_id: str):
    """
    Resets the chat history for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to reset.

    Returns:
        None
    """
    mem = []
    my_db.set_user_property(chat_id, 'dialog_openrouter', my_db.obj_to_blob(mem))


def get_mem_as_string(chat_id: str, md: bool = False) -> str:
    """
    Returns the chat history as a string for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to get the history for.

    Returns:
        str: The chat history as a string.
    """
    try:
        mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_openrouter')) or []
        result = ''
        for x in mem:
            role = x['role']
            if role == 'user': role = '𝐔𝐒𝐄𝐑'
            if role == 'assistant': role = '𝐁𝐎𝐓'
            if role == 'system': role = '𝐒𝐘𝐒𝐓𝐄𝐌'
            text = x['content']
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
        return result 
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_mistral(f'get_mem_as_string: {error}\n\n{error_traceback}')
        return ''


# def remove_key(key: str):
#     '''Removes a given key from the ALL_KEYS list and from the USER_KEYS dictionary.'''
#     try:
#         if not key:
#             return
#         if key in ALL_KEYS:
#             try:
#                 ALL_KEYS.remove(key)
#             except ValueError:
#                 my_log.log_keys(f'remove_key: Invalid key {key} not found in ALL_KEYS list')

#         keys_to_delete = []
#         with USER_KEYS_LOCK:
#             # remove key from USER_KEYS
#             for user in USER_KEYS:
#                 if USER_KEYS[user] == key:
#                     keys_to_delete.append(user)

#             for user_key in keys_to_delete:
#                 del USER_KEYS[user_key]

#             if keys_to_delete:
#                 my_log.log_keys(f'mistral: Invalid key {key} removed from users {keys_to_delete}')
#             else:
#                 my_log.log_keys(f'mistral: Invalid key {key} was not associated with any user in USER_KEYS')

#     except Exception as error:
#         error_traceback = traceback.format_exc()
#         my_log.log_mistral(f'mistral: Failed to remove key {key}: {error}\n\n{error_traceback}')


def remove_key(key: str):
    '''Removes a given key from the ALL_KEYS list and from the USER_KEYS dictionary.'''
    try:
        if not key:
            return
        
        # Protect the global key lists during modification
        with CURRENT_KEYS_SET_LOCK:
            if key in ALL_KEYS:
                try:
                    ALL_KEYS.remove(key)
                except ValueError:
                    pass # Already removed by another thread
            # Invalidate the current round-robin set
            global CURRENT_KEYS_SET
            CURRENT_KEYS_SET = []

        keys_to_delete = []
        # Protect the user keys database during modification
        with USER_KEYS_LOCK:
            for user in USER_KEYS:
                if USER_KEYS[user] == key:
                    keys_to_delete.append(user)

            for user_key in keys_to_delete:
                del USER_KEYS[user_key]

            if keys_to_delete:
                my_log.log_keys(f'mistral: Invalid key {key} removed from users {keys_to_delete}')

    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_mistral(f'mistral: Failed to remove key {key}: {error}\n\n{error_traceback}')


# def load_users_keys():
#     """
#     Load users' keys into memory and update the list of all keys available.
#     """
#     with USER_KEYS_LOCK:
#         global USER_KEYS, ALL_KEYS
#         ALL_KEYS = cfg.MISTRALAI_KEYS if hasattr(cfg, 'MISTRALAI_KEYS') and cfg.MISTRALAI_KEYS else []
#         for user in USER_KEYS:
#             key = USER_KEYS[user]
#             if key not in ALL_KEYS:
#                 ALL_KEYS.append(key)


def load_users_keys():
    """
    Load users' keys into memory and update the list of all keys available.
    """

    global SYSTEM_
    import my_skills_general
    SYSTEM_ = my_skills_general.SYSTEM_

    # This lock ensures that we are not reading from a partially updated DB
    with USER_KEYS_LOCK:
        user_keys_list = [USER_KEYS[user] for user in USER_KEYS]

    # This lock protects the global ALL_KEYS and CURRENT_KEYS_SET lists
    with CURRENT_KEYS_SET_LOCK:
        global ALL_KEYS
        base_keys = cfg.MISTRALAI_KEYS if hasattr(cfg, 'MISTRALAI_KEYS') and cfg.MISTRALAI_KEYS else []
        
        all_keys_set = set(base_keys)
        all_keys_set.update(user_keys_list)
        ALL_KEYS = list(all_keys_set)
        
        # Invalidate the current round-robin set
        global CURRENT_KEYS_SET
        CURRENT_KEYS_SET = []


def test_key(key: str) -> bool:
    '''
    Tests a given key by making a simple request to the Mistral AI API.
    '''
    r = ai('1+1=', key_=key.strip())
    return bool(r)


def sum_big_text(text:str, query: str, temperature: float = 1, model = DEFAULT_MODEL) -> str:
    """
    Generates a response from an AI model based on a given text,
    query, and temperature.

    Args:
        text (str): The complete text to be used as input.
        query (str): The query to be used for generating the response.
        temperature (float, optional): The temperature parameter for controlling the randomness of the response. Defaults to 0.1.

    Returns:
        str: The generated response from the AI model.
    """
    query = f'''{query}\n\n{text[:MAX_SUM_REQUEST]}'''
    r = ai(query, temperature=temperature, model = model)
    if not r and model == DEFAULT_MODEL:
        r = ai(query, temperature=temperature, model = FALLBACK_MODEL)
    return r


def get_reprompt_for_image(prompt: str, chat_id: str = '') -> tuple[str, str, bool, bool] | None:
    """
    Generates a detailed prompt for image generation based on user query and conversation history.

    Args:
        prompt: User's query for image generation.

    Returns:
        A tuple of four elements: (positive prompt, negative prompt, moderation_sexual, moderation_hate)
        or None if an error occurred.
    """

    result = ai(
        prompt,
        temperature=1.5,
        json_output=True,
        model=DEFAULT_MODEL,
        user_id=chat_id,
        )
    result_dict = utils.string_to_dict(result)
    if result_dict:
        reprompt = ''
        negative_prompt = ''
        moderation_sexual = False
        moderation_hate = False
        if 'reprompt' in result_dict:
            reprompt = result_dict['reprompt']
        if 'negative_reprompt' in result_dict:
            negative_prompt = result_dict['negative_reprompt']
        if 'negative_prompt' in result_dict:
            negative_prompt = result_dict['negative_prompt']
        if 'moderation_sexual' in result_dict:
            moderation_sexual = result_dict['moderation_sexual']
            if moderation_sexual:
                my_log.log_reprompt_moderation(f'MODERATION image reprompt failed: {prompt}')
        if 'moderation_hate' in result_dict:
            moderation_hate = result_dict['moderation_hate']
            if moderation_hate:
                my_log.log_reprompt_moderation(f'MODERATION image reprompt failed: {prompt}')

        if reprompt and negative_prompt:
            return reprompt, negative_prompt, moderation_sexual, moderation_hate
    return None


def test_chat():
    import my_skills, my_skills_general
    import my_groq
    my_groq.load_users_keys()
    funcs = [
        my_skills.calc,
        my_skills.search_google_fast,
        my_skills.search_google_deep,
        my_skills.download_text_from_url,
        my_skills_general.get_time_in_timezone,
        my_skills.get_weather,
        my_skills.get_currency_rates,
        my_skills.tts,
        my_skills.speech_to_text,
        my_skills.edit_image,
        my_skills.translate_text,
        my_skills.translate_documents,
        my_skills.text_to_image,
        my_skills.text_to_qrcode,
        my_skills_general.save_to_txt,
        my_skills_general.save_to_excel,
        my_skills_general.save_to_docx,
        my_skills_general.save_to_pdf,
        my_skills_general.save_diagram_to_image,
        my_skills.save_chart_and_graphs_to_image,
        my_skills.save_html_to_image,
        my_skills.save_html_to_animation,
        my_skills.save_natal_chart_to_image,
        my_skills.send_tarot_cards,
        my_skills.query_user_file,
        my_skills.query_user_logs,
        my_skills_general.get_location_name,
        my_skills.help,
    ]

    TOOLS, AVAILABLE_TOOLS = my_cerebras_tools.get_tools(*funcs)
    chat_cli(model = MEDIUM_MODEL, tools=TOOLS, available_tools=AVAILABLE_TOOLS)


if __name__ == '__main__':
    pass
    my_db.init(backup=False)
    load_users_keys()

    test_chat()

    # print(ai('сделай хороший перевод на английский этого текста:\n\n"Привет, как дела?"'))

    # print(img2txt('C:/Users/user/Downloads/3.jpg', 'извлеки весь текст с картинки, сохрани форматирование'))
    # print(img2txt('C:/Users/user/Downloads/2.jpg', 'реши все задачи, ответ по-русски'))
    # print(img2txt('C:/Users/user/Downloads/3.png', 'какой ответ и почему, по-русски'))

    # print(ocr_image(r'C:/Users/user/Downloads/samples for ai/картинки/мат задачи 2.jpg'))
    # print(ocr_pdf(r'C:/Users/user/Downloads/samples for ai/картинки/20220816043638.pdf'))

    # with open('C:/Users/user/Downloads/1.txt', 'r', encoding='utf-8') as f:
    #     text = f.read()

    # print(sum_big_text(text, 'сделай подробный пересказ по тексту'))


    # trgt=r'C:\Users\user\AppData\Local\Temp\tmpjekvkdii\1_part_01.ogg'
    # trgt=r'C:\Users\user\Downloads\samples for ai\аудио\кусок радио-т подкаста несколько голосов.mp3'
    # r=transcribe_audio(
    #     trgt,
    #     language='ru',
    #     get_timestamps=True,
    #     timeout=300
    # )
    # with open('C:/Users/user/Downloads/1.txt', 'w', encoding='utf-8') as f:
    #     f.write(r)

    # print(get_reprompt_for_image(''))

    my_db.close()
