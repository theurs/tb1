#!/usr/bin/env python3
# pip install -U cohere
# hosts: 50.7.85.220 api.cohere.com


import base64
import io
import json
import random
import time
import threading
import traceback
from typing import Any, Callable, Dict, List, Optional

import cohere
import my_cerebras_tools
import PIL
from sqlitedict import SqliteDict

import cfg
import my_db
import my_log
import my_skills_storage
import utils


DEFAULT_TIMEOUT = 120

# MAX_SUM_REQUEST = 128 * 1000 * 3
MAX_QUERY_LENGTH = 100000
MAX_SUM_REQUEST = 100000
MAX_REQUEST = 20000

# вызывает проблемы с тулзами
# DEFAULT_MODEL = 'command-a-reasoning-08-2025' # 'command-a-03-2025'
# FALLBACK_MODEL = 'command-a-03-2025' # 'command-r-plus'
DEFAULT_MODEL = 'command-a-03-2025'
FALLBACK_MODEL = 'command-r-plus'

#FALLBACK_MODEL = 'command-r'
VISION_MODEL = 'command-a-vision-07-2025'
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
USER_KEYS = SqliteDict('db/cohere_user_keys.db', autocommit=True)
USER_KEYS_LOCK = threading.Lock()
CURRENT_KEYS_SET_LOCK = threading.Lock()
CURRENT_KEYS_SET = []

MAX_TOOL_OUTPUT_LEN = 60000

SYSTEM_ = []


def _construct_resp(resp) -> str:
    '''
    Создает из ответа модели строку
    '''
    r = ''
    if resp and resp.message and resp.message.content and isinstance(resp.message.content, list):
        for chunk in resp.message.content:
            if chunk.type == 'text':
                r += chunk.text
            elif chunk.type == 'thinking':
                r += f'<think>{chunk.thinking}</think>'
    return r


def ai(
    prompt: str = '',
    mem_: Optional[List[Dict[str, Any]]] = None,
    user_id: str = '',
    system: str = '',
    model_: str = '',
    temperature: float = 1,
    max_tokens_: int = 4000,
    timeout: int = DEFAULT_TIMEOUT,
    key_: str = '',
    json_output: bool = False,
    json_schema: Optional[Dict] = None,
    tools: Optional[List[Dict]] = None,
    available_tools: Optional[Dict[str, Callable]] = None,
    max_tools_use: int = 20,
) -> str:
    """
    Generates a response using the Cohere AI model with support for tool use and structured JSON.

    This function manages conversation history, system prompts, tool usage, and implements
    robust timeout and retry mechanisms inspired by the Cerebras implementation.

    Args:
        prompt (str, optional): The user's input prompt. Defaults to ''.
        mem_ (Optional[List[Dict[str, Any]]], optional): The conversation history. Defaults to None.
        user_id (str, optional): The user's ID for logging. Defaults to ''.
        system (str, optional): The system's initial message. Defaults to ''.
        model_ (str, optional): The name of the cohere model to use. Defaults to DEFAULT_MODEL.
        temperature (float, optional): The randomness of the generated response. Defaults to 1.
        max_tokens_ (int, optional): The maximum number of tokens in the final response. Defaults to 4000.
        timeout (int, optional): Timeout for each API call. Also the base for global timeout. Defaults to 120.
        key_ (str, optional): A specific API key to use. Defaults to ''.
        json_output (bool, optional): If True and no schema, requests a generic JSON object. Defaults to False.
        json_schema (Optional[Dict], optional): A JSON schema to enforce on the output. Defaults to None.
        tools (Optional[List[Dict]], optional): A list of tool schemas for the model. Defaults to None.
        available_tools (Optional[Dict[str, Callable]], optional): A map of tool names to functions. Defaults to None.
        max_tools_use (int, optional): Maximum number of tool calls in one turn. Defaults to 20.

    Returns:
        str: The generated response from the Cohere AI model. Returns an empty string if an error occurs.
    """
    start_time = time.monotonic()
    effective_timeout = timeout * 2 if tools and available_tools else timeout

    temperature = temperature / 2
    mem = mem_[:] if mem_ else []

    now = utils.get_full_time()
    systems = (
        f'Current date and time: {now}',
        f'Telegram user id you are talking with: {user_id}',
        'Assistant have many tools for serve better, it cat search, calculate, read web pages etc, see tools description',
        *SYSTEM_
    )

    if system:
        mem.insert(0, {"role": "system", "content": system})
    for s in reversed(systems):
        mem.insert(0, {"role": "system", "content": s})
    if prompt:
        mem.append({'role': 'user', 'content': prompt})

    if not mem:
        return ''

    model = model_ if model_ else DEFAULT_MODEL

    while count_tokens(mem) > MAX_QUERY_LENGTH + 100:
        mem = mem[2:]

    # сохраняем маркер для проверки валидности chat_id в модуле my_skills*
    if user_id:
        my_skills_storage.STORAGE_ALLOWED_IDS[user_id] = user_id

    RETRY_MAX = 1 if key_ else 4
    api_key = ''
    for attempt in range(RETRY_MAX):
        if time.monotonic() - start_time > effective_timeout:
            my_log.log_cohere(f'ai: Global timeout of {effective_timeout}s exceeded.')
            return ''

        api_key = key_ if key_ else get_next_key()
        if not api_key:
            my_log.log_cohere('ai: No API key available.')
            return ''

        try:
            client = cohere.ClientV2(api_key, timeout=timeout)

            # --- Tool-use loop ---
            if tools and available_tools:
                for _ in range(max_tools_use):
                    if time.monotonic() - start_time > effective_timeout:
                        raise TimeoutError(f"Global timeout exceeded in tool-use loop.")

                    response = client.chat(
                        messages=mem,
                        model=model,
                        temperature=temperature,
                        tools=tools,
                    )

                    message = response.message
                    if not message.tool_calls:
                        if user_id: my_db.add_msg(user_id, model)
                        return _construct_resp(response)

                    mem.append(message.model_dump())

                    tool_results = []
                    for tool_call in message.tool_calls:
                        function_name = tool_call.function.name
                        if function_name in available_tools:
                            function_to_call = available_tools[function_name]
                            try:
                                args = json.loads(tool_call.function.arguments)
                                tool_output = function_to_call(**args)
                                if isinstance(tool_output, str) and len(tool_output) > MAX_TOOL_OUTPUT_LEN:
                                    pass # my_log.log_cohere(f'Tool output from {function_name} is too long ({len(tool_output)} chars), cutting to {MAX_TOOL_OUTPUT_LEN}')
                                    tool_output = tool_output[:MAX_TOOL_OUTPUT_LEN]
                            except Exception as e:
                                tool_output = f"Error executing tool: {e}"
                                my_log.log_cohere(f'ai tool error: {e}')
                        else:
                            tool_output = f"Error: Tool '{function_name}' not found."

                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            # "content": [{"type": "document", "document": {"data": json.dumps(tool_output)}}]
                            "content": [{"type": "text", "text": str(tool_output)}]
                        })

                    mem.extend(tool_results)

                final_response = client.chat(
                    messages=mem, model=model, temperature=temperature
                )
                if user_id: my_db.add_msg(user_id, model)
                return _construct_resp(final_response)

            # --- Non-tool path ---
            else:
                response_format = {"type": "text"}
                if json_schema:
                    response_format = {"type": "json_object", "schema": json_schema}
                elif json_output:
                    response_format = {"type": "json_object"}

                response = client.chat(
                    messages=mem,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens_,
                    response_format=response_format,
                )

                resp = _construct_resp(response)
                if resp:
                    if user_id: my_db.add_msg(user_id, model)
                    return resp

        except Exception as error:
            error_str = str(error).lower()
            traceback_error = traceback.format_exc()
            my_log.log_cohere(f'ai: attempt {attempt + 1}/{RETRY_MAX} failed with error: {error} [user_id: {user_id}]\n\n{traceback_error}')
            if 'invalid api token' in error_str:
                if not key_: remove_key(api_key)
            elif 'timeout' in error_str or 'timed out' in error_str:
                pass # just try next key
            elif 'your request resulted in an invalid tool generation. Try updating the messages or tool definitions':
                break
            else: # for other errors, just try next key
                pass

        if attempt < RETRY_MAX - 1:
            time.sleep(1)

    # Fallback logic after all retries failed
    if model == DEFAULT_MODEL and not key_:
        return ai(prompt, mem, user_id, system, FALLBACK_MODEL, temperature, max_tokens_, timeout, key_, json_output, json_schema, tools, available_tools, max_tools_use)

    return ''


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
        my_log.log_cohere(f'update_mem: {error}\n\n{error_traceback}\n\n{query}\n\n{resp}\n\n{mem}')

    my_db.set_user_property(chat_id, 'dialog_openrouter', my_db.obj_to_blob(mem__))


def chat(
    query: str,
    chat_id: str = '',
    temperature: float = 1,
    system: str = '',
    model: str = '',
    tools: Optional[List[Dict]] = None,
    available_tools: Optional[Dict[str, Callable]] = None,
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
            model_=model,
            tools=tools,
            available_tools=available_tools
        )

        if text:
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
            available_tools=available_tools
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
        my_log.log_cohere(f'force:Failed to force message in chat {chat_id}: {error}\n\n{error_traceback}')


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
        my_log.log_cohere(f'undo: Failed to undo chat {chat_id}: {error}\n\n{error_traceback}')


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
        my_log.log_cohere(f'get_mem_as_string: {error}\n\n{error_traceback}')
        return ''


def sum_big_text(text:str, query: str, temperature: float = 1, model = DEFAULT_MODEL, role: str = '') -> str:
    """
    Generates a response from an AI model based on a given text,
    query, and temperature.

    Args:
        text (str): The complete text to be used as input.
        query (str): The query to be used for generating the response.
        temperature (float, optional): The temperature parameter for controlling the randomness of the response. Defaults to 0.1.
        role (str, optional): System prompt. Defaults to ''.

    Returns:
        str: The generated response from the AI model.
    """
    query = f'''{query}\n\n{text[:MAX_SUM_REQUEST]}'''
    r = ai(query, temperature=temperature, model_ = model, system=role)
    if not r and model == DEFAULT_MODEL:
        r = ai(query, temperature=temperature, model_ = FALLBACK_MODEL, system=role)
    return r.strip()


def test_key(key: str) -> bool:
    '''
    Tests a given key by making a simple request to the Cohere AI API.
    '''
    r = ai('1+1=', key_=key.strip())
    return bool(r)


def list_models():
    keys = ALL_KEYS
    random.shuffle(keys)
    keys = keys[:4]

    co = cohere.Client(api_key=keys[0], timeout=20)

    response = co.models.list()

    for m in response.models:
        print(m.name)


def img2txt(
    image_data: bytes,
    prompt: str = 'Describe picture',
    model = VISION_MODEL,
    temperature: float = 1,
    max_tokens: int = 4000,
    timeout: int = 120,
    chat_id: str = '',
    system: str = '',
    ) -> str:
    """
    Describes an image using the Cohere vision model, based on documentation.

    Args:
        image_data: The image data as bytes or a file path as a string.
        prompt: The prompt to guide the description. Defaults to 'Describe picture'.
        model: The model to use. Defaults to VISION_MODEL.
        temperature: The randomness of the output. Defaults to 1.
        max_tokens: The maximum number of tokens to generate. Defaults to 4000.
        timeout: The timeout for the request in seconds. Defaults to 120.
        chat_id: The chat ID to log the message count.
        system: An optional system prompt.

    Returns:
        A string containing the description of the image, or an empty string if an error occurs.
    """

    if not ALL_KEYS:
        my_log.log_cohere('img2txt: No API keys available.')
        return ''

    keys = ALL_KEYS[:]
    random.shuffle(keys)
    keys = keys[:4]

    try:
        if isinstance(image_data, str):
            # Если image_data - это путь к файлу
            img = PIL.Image.open(image_data)
        else:
            # Если image_data - это байты
            img = PIL.Image.open(io.BytesIO(image_data))

        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
        image_url = f"data:image/png;base64,{img_base64}"
    except Exception as e:
        my_log.log_cohere(f'img2txt: Failed to process image data: {e}')
        return ''

    mem = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}}
            ]
        }
    ]

    now = utils.get_full_time()
    systems = (
        f'Current date and time: {now}\n',
        'Ask again if something is unclear in the request',
        'You (assistant) are currently working in a Telegram bot. The Telegram bot automatically extracts text from any type of files sent to you by the user, such as documents, images, audio recordings, etc., so that you can fully work with any files.',
        "If the user's request cannot be fulfilled using the available tools or direct actions, the assistant(you) must treat the request as a request to generate text (e.g., providing code as text), not a request to perform an action (e.g., executing code or interacting with external systems not directly supported by tools) (intention mismatch).",
    )

    if system:
        mem.insert(0, {"role": "system", "content": system})
    for s in reversed(systems):
        mem.insert(0, {"role": "system", "content": s})

    for key in keys:
        try:
            client = cohere.ClientV2(key, timeout=timeout)
            response = client.chat(
                model=model,
                messages=mem,
                temperature=temperature / 2,
                max_tokens=max_tokens,
            )
            resp = response.message.content[0].text.strip()
            if resp:
                if chat_id:
                    my_db.add_msg(chat_id, model)
                return resp
        except Exception as error:
            error_str = str(error).lower()
            if 'invalid api token' in error_str or 'unauthorized' in error_str:
                remove_key(key)
                my_log.log_cohere(f'img2txt: Removed invalid key. Error: {error}')
            elif 'message must be at least 1 token long' in error_str:
                my_log.log_cohere(f'img2txt: Empty message error: {error}')
                return ''
            else:
                my_log.log_cohere(f'img2txt: API call failed with key {key[:5]}... Error: {error}')
            continue

    my_log.log_cohere(f'img2txt: Failed to get a response after trying {len(keys)} keys.')
    return ''


def remove_key(key: str) -> None:
    """
    Removes a given key from the ALL_KEYS list and from the USER_KEYS dictionary.
    This operation is thread-safe.
    """
    with USER_KEYS_LOCK:
        try:
            # Remove from the in-memory list if it exists
            if key in ALL_KEYS:
                ALL_KEYS.remove(key)

            # Find all users associated with this key to remove them from the database
            users_to_purge = [user for user, user_key in USER_KEYS.items() if user_key == key]

            if not users_to_purge:
                return

            # Remove the entries from the persistent dictionary
            for user in users_to_purge:
                del USER_KEYS[user]

            my_log.log_keys(f'cohere: Invalid key removed for users {users_to_purge}')

        except Exception as error:
            # Log any unexpected error during the key removal process
            error_traceback = traceback.format_exc()
            my_log.log_cohere(f'Failed to remove key {key}: {error}\n\n{error_traceback}')


def load_users_keys() -> None:
    """
    Load users' keys into memory from config and database.
    This operation is thread-safe.
    """

    global SYSTEM_
    import my_skills_general
    SYSTEM_ = my_skills_general.SYSTEM_

    global ALL_KEYS
    with USER_KEYS_LOCK:
        # Start with keys from the main config file
        base_keys = cfg.COHERE_AI_KEYS if hasattr(cfg, 'COHERE_AI_KEYS') and cfg.COHERE_AI_KEYS else []

        # Get all unique keys from user database and config
        user_keys = set(USER_KEYS.values())
        all_unique_keys = set(base_keys) | user_keys

        # Update the global list atomically
        ALL_KEYS = list(all_unique_keys)


def get_next_key() -> str:
    '''
    Return round robin key from ALL_KEYS
    '''
    with CURRENT_KEYS_SET_LOCK:
        global CURRENT_KEYS_SET
        if not CURRENT_KEYS_SET:
            if ALL_KEYS:
                CURRENT_KEYS_SET = ALL_KEYS[:]

        if CURRENT_KEYS_SET:
            return CURRENT_KEYS_SET.pop(0)
        else:
            return ''


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
        my_skills_general.text_to_barcode,
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
    chat_cli(tools=TOOLS, available_tools=AVAILABLE_TOOLS)


if __name__ == '__main__':
    pass
    my_db.init(backup=False)
    load_users_keys()

    # r = ai('ты какая модель?')
    # print(r)

    # print(test_key(input('Enter key: ')))

    # print(img2txt(r'C:\Users\user\Downloads\samples for ai\картинки\мат задачи 3.jpg', 'перепиши весь текст используя знаки из юникода вместо латеха'))

    test_chat()

    # list_models()

    # with open('C:/Users/user/Downloads/2.txt', 'r', encoding='utf-8') as f:
    #     text = f.read()
    # print(sum_big_text(text, 'сделай подробный пересказ по тексту'))

