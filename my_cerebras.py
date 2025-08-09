#!/usr/bin/env python3
# https://inference-docs.cerebras.ai/models/overview
# pip install -U cerebras_cloud_sdk


import time
import threading
import traceback
from typing import Any, Dict, List, Optional


import langcodes
from cerebras.cloud.sdk import Cerebras

import cfg
import my_db
import my_log
import utils


MODEL_GPT_OSS_120B = 'gpt-oss-120b'
MODEL_QWEN_3_CODER_480B = 'qwen-3-coder-480b'
MODEL_QWEN_3_235B_A22B_INSTRUCT = 'qwen-3-235b-a22b-instruct-2507'
MODEL_LLAMA_4_MAVERICK_17B_128E_INSTRUCT = 'llama-4-maverick-17b-128e-instruct'
DEFAULT_MODEL = MODEL_GPT_OSS_120B # https://inference-docs.cerebras.ai/models/openai-oss
BACKUP_MODEL = MODEL_QWEN_3_235B_A22B_INSTRUCT


# сколько запросов хранить
MAX_MEM_LINES = 30

DEFAULT_TIMEOUT = 60

# блокировка чатов что бы не испортить историю 
# {id:lock}
LOCKS = {}

# не принимать запросы больше чем, это ограничение для телеграм бота, в этом модуле оно не используется
MAX_REQUEST = 40000
MAX_SUM_REQUEST = 100000
maxhistchars = 60000

ROUND_ROBIN_KEYS = []


def clear_mem(mem, user_id: str = '') -> List[Dict[str, str]]:
    while 1:
        sizeofmem = count_tokens(mem)
        if sizeofmem <= maxhistchars:
            break
        try:
            mem = mem[2:]
        except IndexError:
            mem = []
            break

    return mem[-MAX_MEM_LINES*2:]


def count_tokens(mem) -> int:
    return sum([len(m['content']) for m in mem])


def get_next_key():
    '''
    Дает один ключ из всех, последовательно перебирает доступные ключи
    '''
    if not hasattr(cfg, 'CEREBRAS_KEYS') or not cfg.CEREBRAS_KEYS:
        return ''

    global ROUND_ROBIN_KEYS

    if not ROUND_ROBIN_KEYS:
        keys = cfg.CEREBRAS_KEYS[:]
        ROUND_ROBIN_KEYS = keys[:]

    return ROUND_ROBIN_KEYS.pop(0)


def ai(
    prompt: str = '',
    mem: Optional[List[Dict[str, str]]] = None,
    user_id: str = '',
    system: str = '',
    model: str = '',
    temperature: float = 1.0,
    max_tokens: int = 16000,
    timeout: int = DEFAULT_TIMEOUT,
    response_format: str = 'text',
    json_schema: Optional[Dict] = None,
    reasoning_effort_value_: str = 'none'
) -> str:
    """
    Sends a request to the Cerebras AI API with refined control over output format.

    Args:
        prompt (str): The user's current prompt.
        mem (Optional[List[Dict[str, str]]]): The conversation history.
        user_id (str): The unique identifier for the user.
        system (str): An additional system-level instruction for the model.
        model (str): The specific model to use for the completion.
        temperature (float): Controls the randomness of the output.
        max_tokens (int): The maximum number of tokens to generate.
        timeout (int): The timeout for the API request in seconds.
        response_format (str): 'text' for standard output, or 'json' to enable
            one of the JSON output modes.
        json_schema (Optional[Dict]): If response_format is 'json', this schema
            will be enforced for structured output. If None, simple
            unstructured JSON mode is used.
        reasoning_effort_value_ (str): Overrides the user's default
            reasoning effort setting.

    Returns:
        str: The AI's response as a string, or an empty string on failure.
    """
    if not prompt and not mem:
        return ''

    if not hasattr(cfg, 'CEREBRAS_KEYS') or not cfg.CEREBRAS_KEYS:
        return ''

    if not model:
        model = DEFAULT_MODEL

    if any(x in model.lower() for x in ('llama', 'gpt-oss', 'qwen')):
        temperature /= 2

    mem_ = mem[:] if mem else []

    now = time.strftime('%Y-%m-%d %H:%M:%S')
    systems = (
        f'Current date and time: {now}\n',
        f'Telegram user id you talking with: {user_id}\n',
        'Ask again if something is unclear in the request\n',
        'You (assistant) are currently working in a Telegram bot. The Telegram bot automatically extracts text from any type of files sent to you by the user, such as documents, images, audio recordings, etc., so that you can fully work with any files.\n',
        "If the user's request cannot be fulfilled using the available tools or direct actions, the assistant(you) must treat the request as a request to generate text (e.g., providing code as text), not a request to perform an action (e.g., executing code or interacting with external systems not directly supported by tools) (intention mismatch).\n",
        "To edit image user can send image with caption starting ! symbol\n",
    )

    if system:
        mem_.insert(0, {"role": "system", "content": system})
    for s in reversed(systems):
        mem_.insert(0, {"role": "system", "content": s})
    if prompt:
        mem_.append({"role": "user", "content": prompt})

    reasoning_effort = 'none'
    if user_id:
        reasoning_effort = my_db.get_user_property(user_id, 'openrouter_reasoning_effort') or 'none'
    if reasoning_effort_value_ != 'none':
        reasoning_effort = reasoning_effort_value_
    
    if reasoning_effort == 'none':
        reasoning_effort = None
    elif reasoning_effort == 'minimal':
        reasoning_effort = 'low'

    RETRY_MAX = 3
    for _ in range(RETRY_MAX):
        api_key = get_next_key()
        if not api_key:
            return ''

        try:
            client = Cerebras(api_key=api_key)

            sdk_params = {
                'messages': mem_,
                'model': model,
                'max_completion_tokens': max_tokens,
                'temperature': temperature,
                'timeout': timeout,
            }
            if reasoning_effort:
                sdk_params['reasoning_effort'] = reasoning_effort

            if response_format == 'json':
                if json_schema:
                    sdk_params['response_format'] = {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "custom_schema",
                            "strict": True,
                            "schema": json_schema
                        }
                    }
                else:
                    sdk_params['response_format'] = {'type': 'json_object'}

            chat_completion = client.chat.completions.create(**sdk_params)
            result = chat_completion.choices[0].message.content or ''

            if result:
                return result.strip()

        except Exception as error:
            my_log.log_cerebras(f'ai:1: {error} [user_id: {user_id}]')

    return ''


def update_mem(query: str, resp: str, chat_id: str):
    '''
    Добавляет запись в память
    '''
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
        my_log.log_cerebras(f'update_mem: {error}\n\n{error_traceback}\n\n{query}\n\n{resp}\n\n{mem}')

    my_db.set_user_property(chat_id, 'dialog_openrouter', my_db.obj_to_blob(mem__))


def chat(
    query: str,
    chat_id: str = '',
    temperature: float = 1,
    system: str = '',
    model: str = '',
    timeout: int = DEFAULT_TIMEOUT
) -> str:

    global LOCKS

    if chat_id in LOCKS:
        lock = LOCKS[chat_id]
    else:
        lock = threading.Lock()
        LOCKS[chat_id] = lock

    with lock:
        mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_openrouter')) or []

        text = ai(query, mem, user_id=chat_id, temperature = temperature, system=system, model=model, timeout=timeout)

        if text:
            my_db.add_msg(chat_id, model)
            mem += [{'role': 'user', 'content': query}]
            mem += [{'role': 'assistant', 'content': text}]
            mem = clear_mem(mem, chat_id)
            my_db.set_user_property(chat_id, 'dialog_openrouter', my_db.obj_to_blob(mem))

        return text


def chat_cli(model: str = ''):
    reset('test')
    while 1:
        q = input('>')
        if q == 'mem':
            print(get_mem_as_string('test'))
            continue
        r = chat(q, 'test', model = model)
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
        my_log.log_cerebras(f'force: Failed to force message in chat {chat_id}: {error}\n\n{error_traceback}')


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
        my_log.log_cerebras(f'undo:Failed to undo chat {chat_id}: {error}\n\n{error_traceback}')


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
        my_log.log_cerebras(f'get_mem_as_string: {error}\n\n{error_traceback}')
        return ''


def sum_big_text(text:str, query: str, temperature: float = 1, model: str = '', max_size: int = None) -> str:
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
    query = f'''{query}\n\n{text[:max_size or MAX_SUM_REQUEST]}'''
    r = ai(query, user_id='test', temperature=temperature, model=model)
    return r


def translate(
    text: str,
    from_lang: str = '',
    to_lang: str = '',
    help: str = '',
    # model: str = MODEL_LLAMA_4_MAVERICK_17B_128E_INSTRUCT
    model: str = MODEL_QWEN_3_235B_A22B_INSTRUCT
) -> str:
    """
    Translates text using native JSON Schema enforcement, combined with a robust
    parsing strategy to handle potentially malformed responses from the AI.

    Args:
        text (str): The text to be translated.
        from_lang (str): The source language code (e.g., 'en'). Autodetects if empty.
        to_lang (str): The target language code (e.g., 'ru'). Defaults to 'ru'.
        help (str): Additional context to improve translation quality.
        model (str): The specific AI model to use for the translation.

    Returns:
        str: The translated text, or an empty string if any step fails.
    """
    if not text.strip():
        return ''

    source_lang = from_lang or 'autodetect'
    target_lang = to_lang or 'ru'

    try:
        source_lang_name = langcodes.Language.make(language=source_lang).display_name('en') \
            if source_lang != 'autodetect' else 'autodetect'
        target_lang_name = langcodes.Language.make(language=target_lang).display_name('en')
    except langcodes.LanguageTagError as e:
        my_log.log_cerebras(f'translate: Invalid language code: {e}')
        return ''

    # Define the exact JSON schema for the translation output.
    translation_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "translation": {"type": "string"}
        },
        "required": ["translation"],
        "additionalProperties": False
    }

    context_hint = f"ADDITIONAL CONTEXT TO HELP YOU TRANSLATE: [{help}]" if help else ""

    prompt = f"""
You are an expert translator with decades of experience in a wide range of fields.
Your task is to provide a precise and natural-sounding translation of the TEXT from [{source_lang_name}] to [{target_lang_name}].
{context_hint}

CRITICAL INSTRUCTIONS:
1.  **STYLE AND REGISTER:** Your translation must be highly accurate and perfectly mirror the style and register (formal, informal, technical, etc.) of the original text.
2.  **INTENT:** Do not give a literal, word-for-word translation. Your primary goal is to capture the original meaning, nuance, and intent.
3.  **SLANG AND IDIOMS:** If the text contains slang or idioms, you must find the closest cultural and contextual equivalent in the target language.

TEXT:
{text}
"""

    mem = [{"role": "user", "content": f"{prompt}\n\nTEXT:\n{text}"}]

    # Call the AI, requesting a strictly structured JSON output.
    json_response = ai(
        mem=mem,
        user_id='translate_service',
        temperature=0.1,
        model=model,
        response_format='json',
        json_schema=translation_schema
    )

    if not json_response:
        my_log.log_cerebras(f'translate: AI returned an empty response.')
        return ''

    # --- Start of Restored Robust Parsing Logic ---
    # Use the specialized utility to handle potentially malformed JSON strings.
    data: Optional[Dict] = utils.string_to_dict(json_response)

    if not data:
        my_log.log_cerebras(f'translate: Failed to convert AI response to dict: {json_response}')
        return ''

    try:
        # Sometimes the LLM wraps the response in a list: [{...}]
        if isinstance(data, list) and data:
            data = data[0]

        # After potentially unwrapping, ensure we have a dictionary.
        if not isinstance(data, dict):
            my_log.log_cerebras(f"translate: Parsed data is not a dict: {type(data)}")
            return ''

        translation = data.get('translation')

        # Handle nested dictionaries, a common LLM quirk.
        # e.g., {"translation": {"translation": "the actual text"}}
        if isinstance(translation, dict):
            return translation.get('translation', '')

        # The expected, correct case.
        if isinstance(translation, str):
            return translation

        # If 'translation' is present but not a string or dict (e.g., None), fail safely.
        my_log.log_cerebras(f"translate: 'translation' key has invalid type: {type(translation)}")
        return ''

    except Exception as e:
        my_log.log_cerebras(f'translate: Error extracting translation from dict - {e}: {data}')
        return ''


def list_models() -> Optional[List[str]]:
    """
    Retrieves a list of available models for a given user.

    Args:

    Returns:
        A list of model IDs if successful, None if no API key is found, or an empty list if an error occurs.
    """
    key: Optional[str] = None

    key = get_next_key()

    if not key:
        return None

    try:
        client = Cerebras(
            api_key=key,
        )
        model_list = client.models.list()
        result: List[str] = [x.id for x in model_list.data]
        return result
    except Exception as e:
        traceback_error: str = traceback.format_exc()
        my_log.log_cerebras(f'list_models:{e}\n\n{traceback_error}')
        return []


def format_models_for_telegram(models: List[str]) -> str:
    """
    Categorizes, sorts, and formats a list of models for display in Telegram using Markdown.
    Handles models with prefixes and numeric components for better organization.

    Args:
        models: A list of model names.

    Returns:
        A formatted string ready for Telegram.
    """

    categories: Dict[str, List[str]] = {}
    for model in models:
        parts = model.split('-')  # Splitting by '-' to account for prefixes. Customize if needed
        prefix = parts[0] if parts else "Other" # Main category based on the prefix
        if prefix not in categories:
            categories[prefix] = []
        categories[prefix].append(model)

    output = ""
    sorted_categories = sorted(categories.keys())

    def _sort_key(model: str):
        parts = []
        for part in model.split('-'):
            if part.isdigit():
                parts.append(part.zfill(4))  # Pad with zeros to a fixed width (e.g., 4)
            elif part.replace('.', '', 1).isdigit():
                parts.append(part)  # floats are okay to be compared as strings
            else:
                parts.append(part)
        return tuple(parts)

    for category in sorted_categories:
        output += f"**{category}:**\n"  # Bold category header
        sorted_models = sorted(categories[category], key=lambda x: _sort_key(x)) # Sorting models intelligently
        output += "\n".join([f"- `{model}`" for model in sorted_models]) + "\n\n"

    return output


# нет ни одной модели поддерживающей визуальное описание?
# def img2txt(
#     image_data: bytes,
#     prompt: str = 'Describe picture',
#     model: str = MODEL_LLAMA_4_MAVERICK_17B_128E_INSTRUCT,
#     temperature: float = 1,
#     max_tokens: int = 4000,
#     timeout: int = DEFAULT_TIMEOUT,
#     chat_id: str = '',
#     system: str = '',
#     reasoning_effort_value_: str = 'none'
# ) -> str:
#     """
#     Describes an image using the Cerebras API.

#     Args:
#         image_data: The image data as bytes, or the path to the image file.
#         prompt: The prompt to guide the description. Defaults to 'Describe picture'.
#         model: The model to use for generating the description. If empty, uses a default vision model.
#         temperature: The temperature for the generation 0-2.
#         max_tokens: The maximum number of tokens to generate.
#         timeout: The request timeout in seconds.
#         chat_id: The user ID for fetching specific configurations.
#         system: An optional system prompt.
#         reasoning_effort_value_: Overrides the user's reasoning effort setting.

#     Returns:
#         A string containing the description of the image, or an empty string if an error occurs.
#     """
#     # handle if image_data is a path to a file
#     if isinstance(image_data, str):
#         try:
#             with open(image_data, 'rb') as f:
#                 image_data = f.read()
#         except FileNotFoundError:
#             my_log.log_cerebras(f'img2txt: File not found at path: {image_data}')
#             return ''

#     if any(x in model.lower() for x in ('llama', 'gpt-oss', 'qwen')):
#         temperature = temperature / 2

#     # encode image to base64
#     img_b64_str = base64.b64encode(image_data).decode('utf-8')
#     img_type = 'image/png' # assuming png, but other formats might work

#     # construct the payload for a multimodal request
#     messages = [
#         {
#             "role": "user",
#             "content": [
#                 {"type": "text", "text": prompt},
#                 {
#                     "type": "image_url",
#                     "image_url": {"url": f"data:{img_type};base64,{img_b64_str}"},
#                 },
#             ],
#         }
#     ]

#     # prepend a system message if one is provided
#     if system:
#         messages.insert(0, {'role': 'system', 'content': system})

#     # determine the reasoning effort based on user settings
#     reasoning_effort = 'none'
#     if chat_id:
#         reasoning_effort = my_db.get_user_property(chat_id, 'openrouter_reasoning_effort') or 'none'
#     if reasoning_effort_value_ != 'none':
#         reasoning_effort = reasoning_effort_value_
    
#     # the SDK expects None for default, not the string 'none'
#     if reasoning_effort in ('none', 'auto'):
#         reasoning_effort = None
#     elif reasoning_effort == 'minimal':
#         reasoning_effort = 'low'

#     # retry logic for network resilience
#     RETRY_MAX = 3
#     for attempt in range(RETRY_MAX):

#         api_key = get_next_key()
#         if not api_key:
#             my_log.log_cerebras('img2txt: No API key available.')
#             return ''

#         try:
#             client = Cerebras(api_key=api_key)

#             chat_completion = client.chat.completions.create(
#                 messages=messages,
#                 model=model,
#                 max_completion_tokens=max_tokens,
#                 temperature=temperature,
#                 reasoning_effort=reasoning_effort,
#                 timeout=timeout,
#             )

#             result = chat_completion.choices[0].message.content or ''
#             if result:
#                 return result.strip()

#             my_log.log_cerebras(f'img2txt: attempt {attempt+1}: Empty response from model {model}')

#         except Exception as e:
#             my_log.log_cerebras(f'img2txt: attempt {attempt+1} failed for user {chat_id}: {e}')
#             if attempt < RETRY_MAX - 1:
#                 time.sleep(1) # wait before retrying

#     return '' # return empty string if all attempts fail


if __name__ == '__main__':
    pass
    my_db.init(backup=False)

    # print(format_models_for_telegram(list_models()))

    # print(img2txt(r'C:\Users\user\Downloads\samples for ai\картинки\мат задачи 3.jpg', prompt='вытащи весь текст с картинки как лучший в мире OCR'))

    print(translate('Нужно срочно задеплоить фикс на прод, пока все не упало.', 'ru', 'en', help='IT slang, urgent situation with software deployment.'))
    print(translate('Hello, my friend. We need to bypass this security system.', 'en', 'ru', help='Context is about hacking, collaborative tone.'))
    print(translate('Без кота и жизнь не та, особенно когда дебажишь код.', 'ru', 'en', help='Informal, humorous, about programmer life.'))
    print(translate('Haben Sie eine funktionierende API-Schnittstelle?', 'de', 'ru', help='Formal business/technical question.'))
    print(translate('The quick brown fox jumps over the lazy dog.', 'en', 'ru', help='This is a pangram, a sentence used for testing typefaces.'))
    print(translate('Лол, кек, чебурек, я просто в ауте с этого бага.', 'ru', 'en', help='Modern internet slang expressing being overwhelmed or frustrated.'))
    print(translate('Je ne parle pas russe, mais je peux utiliser cet outil.', 'fr', 'ru', help='A user is talking about using a tool or software.'))
    print(translate('Взломать пентагон через SQL-инъекцию? Это кринж.', 'ru', 'en', help='Informal cybersecurity context, using the modern slang word "cringe".'))
    print(translate('Сколько стоит этот эксплойт нулевого дня?', 'ru', 'en', help='Specific cybersecurity term "zero-day exploit".'))

    # with open(r'C:\Users\user\Downloads\samples for ai\myachev_Significant_Digits_processed_by_sections.txt', 'r', encoding='utf-8') as f:
    #     text = f.read()
    # summary = sum_big_text(text, 'Кратский пересказ сделай')
    # print(summary)

    chat_cli(model='')

    my_db.close()
