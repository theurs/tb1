#!/usr/bin/env python3
# https://inference-docs.cerebras.ai/models/overview
# pip install -U cerebras_cloud_sdk


import cachetools.func
import json
import re
import time
import threading
import traceback
from typing import Any, Dict, List, Optional, Tuple


import langcodes
from cerebras.cloud.sdk import Cerebras
from sqlitedict import SqliteDict

import cfg
import my_cerebras_tools
import my_db
import my_log
import my_skills
import my_skills_general
import my_skills_storage
import utils


MODEL_GPT_OSS_120B = 'gpt-oss-120b'
MODEL_QWEN_3_CODER_480B = 'qwen-3-coder-480b'
MODEL_QWEN_3_235B_A22B_INSTRUCT = 'qwen-3-235b-a22b-instruct-2507'
MODEL_QWEN_3_235B_A22B_THINKING = 'qwen-3-235b-a22b-thinking-2507'
MODEL_LLAMA_4_MAVERICK_17B_128E_INSTRUCT = 'llama-4-maverick-17b-128e-instruct'
MODEL_LLAMA_4_SCOUT_17B_16E_INSTRUCT = 'llama-4-scout-17b-16e-instruct'
DEFAULT_MODEL = MODEL_GPT_OSS_120B
BACKUP_MODEL = MODEL_QWEN_3_235B_A22B_INSTRUCT

# системная инструкция для чат бота
SYSTEM_ = my_skills_general.SYSTEM_

# сколько запросов хранить
MAX_MEM_LINES = 30

DEFAULT_TIMEOUT = 60

# блокировка чатов что бы не испортить историю 
# {id:lock}
LOCKS = {}

# не принимать запросы больше чем, это ограничение для телеграм бота, в этом модуле оно не используется
MAX_REQUEST = 40000
MAX_SUM_REQUEST = 100000
maxhistchars = 50000

MAX_TOOL_OUTPUT_LEN = 30000

# каждый юзер дает свои ключи и они используются совместно со всеми
# каждый ключ дает всего 1000000 токенов в час и день так что чем больше тем лучше
# {full_chat_id as str: key}
# {'[9123456789] [0]': 'key', ...}
ALL_KEYS = []
USER_KEYS = SqliteDict('db/cerebras_user_keys.db', autocommit=True)
USER_KEYS_LOCK = threading.Lock()
CURRENT_KEYS_SET_LOCK = threading.Lock()
CURRENT_KEYS_SET = []


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


funcs_min = [
    my_skills.calc,
    my_skills.search_google_fast,
    my_skills.download_text_from_url,
]


funcs_medium = [
    my_skills.calc,
    my_skills.search_google_fast,
    my_skills.search_google_deep,
    my_skills.download_text_from_url,
    my_skills_general.save_to_txt,
    my_skills.query_user_file,
    my_skills.query_user_logs,
]


# кодеру не нужны лишние функции
funcs_coder = [
    my_skills.calc,
    my_skills.search_google_fast,
    my_skills.search_google_deep,
    my_skills.download_text_from_url,
    # my_skills_general.get_time_in_timezone,
    # my_skills.get_weather,
    # my_skills.get_currency_rates,
    # my_skills.tts,
    # my_skills.speech_to_text,
    # my_skills.edit_image,
    # my_skills.translate_text,
    # my_skills.translate_documents,
    # my_skills.text_to_image,
    my_skills.text_to_qrcode,
    my_skills_general.text_to_barcode,
    my_skills_general.save_to_txt,
    # my_skills_general.save_to_excel,
    # my_skills_general.save_to_docx,
    # my_skills_general.save_to_pdf,
    # my_skills_general.save_diagram_to_image,
    # my_skills.save_chart_and_graphs_to_image,
    my_skills.save_html_to_image,
    # my_skills.save_html_to_animation,
    # my_skills.save_natal_chart_to_image,
    # my_skills.send_tarot_cards,
    my_skills.query_user_file,
    my_skills.query_user_logs,
    # my_skills_general.get_location_name,
    # my_skills.help,
]


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
    reasoning_effort_value_: str = 'none',
    tools: Optional[List[Dict]] = None,
    available_tools: Optional[Dict] = None,
    max_tools_use: int = 20,
    key_: str = '',
) -> str:
    """
    Sends a request to the Cerebras AI API with comprehensive control and safety features.

    This function manages conversation history, system prompts, tool usage, and implements
    robust timeout and retry mechanisms to ensure stability.

    Behavior:
        - Global Timeout: The function has a total execution time limit to prevent indefinite
          hangs. This limit is `timeout` for standard requests and `timeout * 2` for requests
          that involve tools, to allow for multiple API calls and tool execution.
        - Per-Call Timeout: The `timeout` parameter is also applied to each individual API
          request sent to Cerebras.
        - Retry Logic: If an API call fails (except for invalid key errors), the function
          will retry up to 3 times with a 1-second delay between attempts.
        - Key Management: It uses a shared pool of API keys, automatically cycling through
          them and removing invalid keys upon failure.

    Args:
        prompt (str, optional): The user's current input prompt. Defaults to ''.
        mem (Optional[List[Dict[str, str]]], optional): The conversation history, a list
            of dictionaries with "role" and "content" keys. Defaults to None.
        user_id (str, optional): The unique identifier for the user, used for logging
            and context. Defaults to ''.
        system (str, optional): An additional system-level instruction for the model,
            prepended to the standard system prompts. Defaults to ''.
        model (str, optional): The specific model to use (e.g., 'gpt-oss-120b').
            Defaults to the value of DEFAULT_MODEL.
        temperature (float, optional): Controls the randomness of the output (0.0 to 2.0).
            Automatically halved for certain models like Llama and Qwen. Defaults to 1.0.
        max_tokens (int, optional): The maximum number of tokens to generate in the final
            response. Defaults to 16000.
        timeout (int, optional): The timeout in seconds for each individual API request.
            This value is also used as the base for the global timeout. Defaults to 60.
        response_format (str, optional): The desired format for the model's output. Can be
            'text' for plain text or 'json' for a JSON object. Defaults to 'text'.
        json_schema (Optional[Dict], optional): If `response_format` is 'json', this schema
            is enforced for structured JSON output. If None, any valid JSON is accepted.
            Defaults to None.
        reasoning_effort_value_ (str, optional): Overrides the user's default reasoning
            effort setting ('none', 'minimal', 'advanced', etc.). Defaults to 'none'.
        tools (Optional[List[Dict]], optional): A list of tool schemas available for the
            model to use. Defaults to None.
        available_tools (Optional[Dict], optional): A mapping of tool names to their
            callable Python functions. Defaults to None.
        max_tools_use (int, optional): The maximum number of tool calls the model can
            make in a single turn before being forced to answer. Defaults to 20.
        key_ (str, optional): A specific API key to use for this request, bypassing the
            round-robin key pool. Useful for testing or priority tasks. Defaults to ''.

    Returns:
        str: The AI's response as a string. Returns an empty string if the request fails
             after all retries or if it times out.
    """

    if not prompt and not mem:
        return ''

    if not ALL_KEYS:
        my_log.log_cerebras('API key not found')
        return ''

    start_time = time.monotonic()
    effective_timeout = timeout * 2 if tools and available_tools else timeout

    if not model:
        model = DEFAULT_MODEL

    if any(x in model.lower() for x in ('llama', 'gpt-oss', 'qwen')):
        temperature /= 2

    mem_ = mem[:] if mem else []

    now = utils.get_full_time()
    systems = [
        f'Current date and time: {now}\n',
        f'Use this telegram chat id (user id) for API function calls: {user_id}',
        *SYSTEM_
    ]
    # if 'gpt-oss' in model:
    #     systems.append('**IMPORTANT** Do not use table formatting in your answer unless the user explicitly requested it.')

    if system:
        mem_.insert(0, {"role": "system", "content": system})
    for s in reversed(systems):
        mem_.insert(0, {"role": "system", "content": s})
    if prompt:
        mem_.append({"role": "user", "content": prompt})

    # Proactively trim the memory before the first API call.
    mem_ = clear_mem(mem_, user_id)

    # --- 1. Centralized SDK parameter preparation ---
    reasoning_effort = 'none'
    if user_id:
        reasoning_effort = my_db.get_user_property(user_id, 'openrouter_reasoning_effort') or 'none'
    if reasoning_effort_value_ != 'none':
        reasoning_effort = reasoning_effort_value_

    if reasoning_effort == 'none' or 'qwen' in model or 'llama' in model:
        reasoning_effort = None
    elif reasoning_effort == 'minimal':
        reasoning_effort = 'low'

    # сохраняем маркер для проверки валидности chat_id в модуле my_skills*
    if user_id:
        my_skills_storage.STORAGE_ALLOWED_IDS[user_id] = user_id

    RETRY_MAX = 1 if key_ else 3
    api_key = ''
    for attempt in range(RETRY_MAX):
        api_key = key_ if key_ else get_next_key()
        if not api_key:
            return ''

        try:
            client = Cerebras(api_key=api_key)

            # Base parameters for all API calls
            sdk_params: Dict[str, Any] = {
                'model': model,
                'messages': mem_,
                'temperature': temperature,
                'timeout': timeout,
            }

            # Add conditional parameters that apply to both tool and non-tool paths
            if reasoning_effort:
                sdk_params['reasoning_effort'] = reasoning_effort

            if response_format == 'json':
                if json_schema:
                    sdk_params['response_format'] = {
                        "type": "json_schema",
                        "json_schema": {"name": "custom_schema", "strict": True, "schema": json_schema}
                    }
                else:
                    sdk_params['response_format'] = {'type': 'json_object'}

            # --- 2. Tool-use loop using the prepared sdk_params ---
            if tools and available_tools:
                # Add tool-specific parameters
                sdk_params['tools'] = tools
                sdk_params['tool_choice'] = "auto"

                max_calls = max_tools_use
                for call_count in range(max_calls):
                    if time.monotonic() - start_time > effective_timeout:
                        raise TimeoutError(f"Global timeout of {effective_timeout}s exceeded in tool-use loop.")

                    sdk_params['messages'] = mem_
                    response = client.chat.completions.create(**sdk_params)
                    message = response.choices[0].message

                    if not message.tool_calls:
                        return message.content or ""

                    # Append the assistant's response to memory, which contains the tool calls.
                    mem_.append(message.model_dump())

                    # Iterate over each tool call requested by the model.
                    for tool_call in message.tool_calls:
                        function_name = tool_call.function.name
                        tool_output = ""

                        if function_name in available_tools:
                            function_to_call = available_tools[function_name]
                            try:
                                # Arguments are a JSON string, so they must be parsed.
                                args = json.loads(tool_call.function.arguments)
                                tool_output = function_to_call(**args)
                                # Truncate long outputs to avoid context overflow.
                                if isinstance(tool_output, str) and len(tool_output) > MAX_TOOL_OUTPUT_LEN:
                                    tool_output = tool_output[:MAX_TOOL_OUTPUT_LEN]
                            except Exception as e:
                                tool_output = f"Error executing tool '{function_name}': {e}"
                                if 'got an unexpected keyword argument' not in str(e):
                                    my_log.log_cerebras(f"Error executing tool: {e}\n{traceback.format_exc()}")
                        else:
                            tool_output = f"Error: Tool '{function_name}' not found."

                        # Append the result of the tool call back to the message history.
                        mem_.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": str(tool_output),
                        })

                # After the loop, if the tool limit is reached, ask the model to summarize.
                mem_.append({"role": "user", "content": "Tool call limit reached. Summarize your findings based on the tools used."})

                final_params = sdk_params.copy()
                final_params.pop('tools', None)
                final_params.pop('tool_choice', None)
                final_params['messages'] = mem_

                if time.monotonic() - start_time > effective_timeout:
                    raise TimeoutError(f"Global timeout of {effective_timeout}s exceeded before final summarization.")

                final_response = client.chat.completions.create(**final_params)
                return final_response.choices[0].message.content or ""

            # --- 3. Non-tool path, now much simpler ---
            else:
                if time.monotonic() - start_time > effective_timeout:
                    raise TimeoutError(f"Global timeout of {effective_timeout}s exceeded.")

                sdk_params['max_completion_tokens'] = max_tokens

                chat_completion = client.chat.completions.create(**sdk_params)
                result = chat_completion.choices[0].message.content or ''

                if result:
                    return result.strip()

        except Exception as error:
            error_str = str(error)
            my_log.log_cerebras(f'ai: attempt {attempt + 1}/{RETRY_MAX} failed with error: {error_str} [user_id: {user_id}]')

            # --- PATCH START: Reactive context trimming ---
            if 'Please reduce the length of the messages or completion' in error_str:
                # The context is too long. Trim the history more aggressively and retry.
                # This logic is simpler because clear_mem handles preserving system prompts.
                mem_ = clear_mem(mem_[2:], user_id) # Remove oldest conversational pair and re-check
                if attempt < RETRY_MAX - 1:
                    time.sleep(1)
                    continue # Continue to the next attempt with the shortened mem_
                else:
                    return "" # Failed even after trimming
            # --- PATCH END ---

            if 'Please try again soon.' in error_str:
                return ''
            if 'Request timed out.' in error_str or 'Global timeout' in error_str:
                return ''
            if 'Wrong API key' in error_str:
                if not key_:
                    remove_key(api_key)

            if attempt < RETRY_MAX - 1:
                time.sleep(1)

    return ''



def clear_mem(mem: List[Dict[str, str]], user_id: str = '') -> List[Dict[str, str]]:
    """
    Trims conversation history to fit within token and line limits,
    always preserving system messages.

    Args:
        mem (List[Dict[str, str]]): The message history list.
        user_id (str): The user ID (currently unused but kept for signature consistency).

    Returns:
        List[Dict[str, str]]: The potentially trimmed message history.
    """
    # 1. Separate system messages from the main conversation
    system_messages = [m for m in mem if m.get("role") == "system"]
    conversation_messages = [m for m in mem if m.get("role") != "system"]

    # 2. Trim conversation by token count, preserving system messages' count
    # Remove the oldest pairs (user/assistant) until the total size is acceptable.
    while count_tokens(system_messages + conversation_messages) > maxhistchars:
        if len(conversation_messages) >= 2:
            conversation_messages = conversation_messages[2:]
        else:
            # Cannot trim further, break to prevent infinite loop
            break

    # 3. Trim conversation by total message line limit
    if len(conversation_messages) > MAX_MEM_LINES * 2:
        conversation_messages = conversation_messages[-(MAX_MEM_LINES * 2):]

    # 4. Recombine and return
    return system_messages + conversation_messages


def count_tokens(mem) -> int:
    return sum(len(m.get('content', '')) for m in mem if isinstance(m.get('content'), str))


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
    timeout: int = DEFAULT_TIMEOUT,
    tools: Optional[List[Dict]] = None,
    available_tools: Optional[Dict] = None
) -> str:

    global LOCKS

    if chat_id in LOCKS:
        lock = LOCKS[chat_id]
    else:
        lock = threading.Lock()
        LOCKS[chat_id] = lock


    with lock:
        mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_openrouter')) or []

        text = ai(
            query,
            mem,
            user_id=chat_id,
            temperature = temperature,
            system=system,
            model=model,
            timeout=timeout,
            tools=tools,
            available_tools=available_tools
        )

        if text:
            my_db.add_msg(chat_id, model)
            mem += [{'role': 'user', 'content': query}]
            mem += [{'role': 'assistant', 'content': text}]
            mem = clear_mem(mem, chat_id)
            my_db.set_user_property(chat_id, 'dialog_openrouter', my_db.obj_to_blob(mem))

        return text


def chat_cli(model: str = ''):
    reset('test')

    model = DEFAULT_MODEL if not model else model

    if 'gpt-oss' in model:
        TOOLS_SCHEMA, AVAILABLE_TOOLS = my_cerebras_tools.get_tools_gpt_oss(*funcs)
    else:
        TOOLS_SCHEMA, AVAILABLE_TOOLS = my_cerebras_tools.get_tools(*funcs)

    while 1:
        q = input('>')
        if q == 'mem':
            print(get_mem_as_string('test'))
            continue
        r = chat(q, 'test', model = model, tools=TOOLS_SCHEMA, available_tools=AVAILABLE_TOOLS)
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
            role = x.get('role', 'unknown')
            content = x.get('content')
            tool_calls = x.get('tool_calls')

            if role == 'user': role_display = '𝐔𝐒𝐄𝐑'
            elif role == 'assistant': role_display = '𝐁𝐎𝐓'
            elif role == 'system': role_display = '𝐒𝐘𝐒𝐓𝐄𝐌'
            elif role == 'tool': role_display = '𝐓𝐎𝐎𝐋'
            else: role_display = role.upper()

            text_to_display = ""
            if isinstance(content, str):
                if content.startswith('[Info to help you answer'):
                    end = content.find(']') + 1
                    text_to_display = content[end:].strip()
                else:
                    text_to_display = content
            elif tool_calls:
                # Format tool calls for readability
                calls = [f"Call to `{tc.get('function', {}).get('name')}` with args `{tc.get('function', {}).get('arguments')}`" for tc in tool_calls]
                text_to_display = "\n".join(calls)

            if md:
                result += f'**{role_display}:**\n\n{text_to_display}\n\n'
            else:
                result += f'{role_display}: {text_to_display}\n'

            if role_display in ('𝐁𝐎𝐓', '𝐓𝐎𝐎𝐋'):
                result += '\n' if md else ''

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
        json_schema=translation_schema,
        timeout=20
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


def test_key(key: str) -> bool:
    '''
    Tests a given key by making a simple request to the Cerebras AI API.
    '''
    r = ai('1+1=', key_=key.strip(), timeout=20)
    return bool(r)


def load_users_keys():
    """
    Load users' keys into memory and update the list of all keys available.
    """
    with USER_KEYS_LOCK:
        global USER_KEYS, ALL_KEYS
        ALL_KEYS = cfg.CEREBRAS_KEYS if hasattr(cfg, 'CEREBRAS_KEYS') and cfg.CEREBRAS_KEYS else []
        for user in USER_KEYS:
            key = USER_KEYS[user]
            if key not in ALL_KEYS:
                ALL_KEYS.append(key)


def remove_key(key: str):
    '''Removes a given key from the ALL_KEYS list and from the USER_KEYS dictionary.'''
    try:
        if not key:
            return
        if key in ALL_KEYS:
            try:
                with USER_KEYS_LOCK:
                    ALL_KEYS.remove(key)
            except ValueError:
                my_log.log_keys(f'remove_key: Invalid key {key} not found in ALL_KEYS list')

        keys_to_delete = []

        with USER_KEYS_LOCK:
            # remove key from USER_KEYS
            for user in USER_KEYS:
                if USER_KEYS[user] == key:
                    keys_to_delete.append(user)

            for user_key in keys_to_delete:
                del USER_KEYS[user_key]

            if keys_to_delete:
                my_log.log_keys(f'cerebras: Invalid key {key} removed from users {keys_to_delete}')
            else:
                my_log.log_keys(f'cerebras: Invalid key {key} was not associated with any user in USER_KEYS')

    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_cerebras(f'Failed to remove key {key}: {error}\n\n{error_traceback}')


def get_reprompt(prompt: str, conversation_history: str = '', chat_id: str = '') -> Tuple[str, str]:
    """
    Generates an improved prompt and a negative prompt for image generation
    using the Cerebras AI with structured JSON output.

    Args:
        prompt (str): The user's original prompt for the image.
        conversation_history (str): The preceding dialogue for context.
        chat_id (str): The user's ID for logging and model configuration.

    Returns:
        A tuple containing (reprompt, negative_reprompt).
    """
    try:
        clean_prompt = prompt.strip()
        # Handle the '!' prefix to use the prompt as-is without enhancement
        dont_enhance = clean_prompt.startswith('!')
        if dont_enhance:
            clean_prompt = re.sub(r'^!+', '', clean_prompt).strip()

        # Define the JSON schema for structured output from the AI
        reprompt_schema: Dict[str, Any] = {
            "type": "object",
            "properties": {
                "reprompt": {
                    "type": "string",
                    "description": "The enhanced, detailed, and translated prompt in English."
                },
                "negative_reprompt": {
                    "type": "string",
                    "description": "A list of concepts to exclude, e.g., 'ugly, blurry, watermark'."
                },
                "was_translated": {
                    "type": "boolean",
                    "description": "True if the original prompt was translated to English."
                },
                "lang_from": {
                    "type": "string",
                    "description": "The detected language code of the original prompt (e.g., 'ru', 'en')."
                },
                "moderation_sexual": {
                    "type": "boolean",
                    "description": "True if the prompt contains sexually explicit content."
                },
                "moderation_hate": {
                    "type": "boolean",
                    "description": "True if the prompt contains hate speech or violence."
                }
            },
            "required": ["reprompt", "negative_reprompt", "was_translated", "lang_from", "moderation_sexual", "moderation_hate"],
            "additionalProperties": False
        }

        # The instruction prompt for the AI model
        system_instruction = f"""
You are an expert prompt engineer for a text-to-image AI. Your task is to take a user's idea and transform it into a detailed, descriptive, and effective prompt in English up to 900 characters. You must also generate a corresponding negative prompt.

CRITICAL INSTRUCTIONS:
1.  **Analyze and Enhance:** Analyze the user's idea, using conversation history for context. If the idea is short, enrich it with details about style (e.g., 'photorealistic, 4k, cinematic lighting'), composition, and mood.
2.  **Translate to English:** The final `reprompt` MUST be in English.
3.  **Negative Prompt:** The `negative_reprompt` should include terms to prevent common image flaws (e.g., 'low quality, blurry, ugly, text, watermark, deformed, extra limbs').
4.  **Moderation:** Accurately flag any sexually explicit or hateful content.

USER'S IDEA: "{clean_prompt}"

CONVERSATION CONTEXT:
{conversation_history}
"""

        # Call the AI with JSON schema enforcement
        json_response = ai(
            prompt=system_instruction,
            user_id=chat_id,
            model=MODEL_QWEN_3_235B_A22B_INSTRUCT,
            temperature=1.5,
            response_format='json',
            json_schema=reprompt_schema,
            timeout=20
        )

        if not json_response:
            my_log.log_cerebras(f'get_reprompt: AI returned empty response for prompt: {prompt}')
            return '', ''

        data: Optional[Dict] = utils.string_to_dict(json_response)
        if not data:
            my_log.log_cerebras(f'get_reprompt: Failed to parse AI JSON response: {json_response}')
            return '', ''

        # Moderation check
        if data.get('moderation_sexual') or data.get('moderation_hate'):
            my_log.log_reprompt_moderation(f'get_reprompt: MODERATION triggered for prompt: {prompt} | Data: {data}')
            return 'MODERATION', '' # Adhering to the example's return style

        reprompt = data.get('reprompt', '')
        negative_reprompt = data.get('negative_reprompt', '')

        if not reprompt:
            return '', ''

        # Log for analysis
        log_final_reprompt = clean_prompt if dont_enhance else reprompt
        my_log.log_reprompt_moderations(f'get_reprompt:\n\nOriginal: {prompt}\n\nFinal: {log_final_reprompt}\n\nNegative: {negative_reprompt}')

        if dont_enhance:
            return clean_prompt, negative_reprompt

        return reprompt, negative_reprompt

    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_cerebras(f'get_reprompt: Unhandled exception for prompt "{prompt}": {error}\n\n{error_traceback}')
        return '', ''


@cachetools.func.ttl_cache(maxsize=100, ttl=15 * 60)
def rewrite_text_for_tts(text: str, user_id: str) -> str:
    """
    Rewrites text for TTS using structured JSON output from the AI.

    This function normalizes text by expanding numbers, symbols, and abbreviations
    into full words. It uses a strict JSON schema to ensure the AI's response is
    predictable and easy to parse. The result is cached for 15 minutes.

    Args:
        text (str): The text to rewrite.
        user_id (str): The user ID for tracking and model configuration.

    Returns:
        str: The rewritten text, or an empty string.
    """
    if not text.strip():
        return ""

    try:
        # Define the exact JSON schema for the AI's output.
        tts_schema: Dict[str, Any] = {
            "type": "object",
            "properties": {
                "rewritten_text": {
                    "type": "string",
                    "description": "The fully expanded and normalized text suitable for TTS."
                }
            },
            "required": ["rewritten_text"],
            "additionalProperties": False
        }

        # A detailed prompt instructing the AI to perform a specific task and use JSON.
        system_prompt = f"""
You are an AI assistant specializing in text normalization for Text-to-Speech (TTS). Your task is to rewrite the given text to be easily pronounceable by a computer voice.

CRITICAL RULES:
1.  **Expand, Don't Add:** Expand all abbreviations, symbols, and numbers into full words (e.g., 'Dr.' -> 'Doctor', '$5' -> 'five dollars', '2-3' -> 'two to three').
2.  **Preserve Meaning:** Do not alter the core meaning or add information not present in the original text.
3.  **Same Language:** The output language must match the input language.
4.  **Remove unreadable text:** Rewrite code, links etc any text that is not easily pronounceable or readable by a computer voice.
5.  **Transliterate foreign words in text:** Transliterate any foreign words into their closest equivalent of the main language.**

TEXT TO REWRITE:
{text}
"""
        # Call the AI, enforcing the JSON schema.
        json_response = ai(
            prompt=system_prompt,
            user_id=user_id,
            temperature=0.1,
            model=MODEL_QWEN_3_235B_A22B_INSTRUCT,
            response_format='json',
            json_schema=tts_schema,
            timeout=20
        )

        # Fallback if the primary model fails.
        if not json_response:
            json_response = ai(
                prompt=system_prompt,
                user_id=user_id,
                temperature=0.1,
                model=MODEL_LLAMA_4_MAVERICK_17B_128E_INSTRUCT,
                response_format='json',
                json_schema=tts_schema,
                timeout=20
            )

        if not json_response:
            return ''

        # Safely parse the JSON response.
        data: Optional[Dict] = utils.string_to_dict(json_response)
        if not data:
            my_log.log_cerebras(f'rewrite_text_for_tts: Failed to parse AI JSON response: {json_response}')
            return text

        rewritten_text = data.get('rewritten_text')
        if isinstance(rewritten_text, str):
            return rewritten_text.strip()

        return text

    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_cerebras(f'rewrite_text_for_tts: Unhandled exception for text "{text[:50]}...": {error}\n\n{error_traceback}')
        # On any exception, return the original text to prevent failure.
        return text


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
    load_users_keys()
    my_db.init(backup=False)
    my_skills.init()
    my_skills.my_groq.load_users_keys()

    # print(test_key(input('Key to test: ')))

    # print(format_models_for_telegram(list_models()))

    # print(img2txt(r'C:\Users\user\Downloads\samples for ai\картинки\мат задачи 3.jpg', prompt='вытащи весь текст с картинки как лучший в мире OCR'))

    # print(translate('Нужно срочно задеплоить фикс на прод, пока все не упало.', 'ru', 'en', help='IT slang, urgent situation with software deployment.'))
    # print(translate('Hello, my friend. We need to bypass this security system.', 'en', 'ru', help='Context is about hacking, collaborative tone.'))
    # print(translate('Без кота и жизнь не та, особенно когда дебажишь код.', 'ru', 'en', help='Informal, humorous, about programmer life.'))
    # print(translate('Haben Sie eine funktionierende API-Schnittstelle?', 'de', 'ru', help='Formal business/technical question.'))
    # print(translate('The quick brown fox jumps over the lazy dog.', 'en', 'ru', help='This is a pangram, a sentence used for testing typefaces.'))
    # print(translate('Лол, кек, чебурек, я просто в ауте с этого бага.', 'ru', 'en', help='Modern internet slang expressing being overwhelmed or frustrated.'))
    # print(translate('Je ne parle pas russe, mais je peux utiliser cet outil.', 'fr', 'ru', help='A user is talking about using a tool or software.'))
    # print(translate('Взломать пентагон через SQL-инъекцию? Это кринж.', 'ru', 'en', help='Informal cybersecurity context, using the modern slang word "cringe".'))
    # print(translate('Сколько стоит этот эксплойт нулевого дня?', 'ru', 'en', help='Specific cybersecurity term "zero-day exploit".'))

    # # --- Safe Prompts ---
    # print(get_reprompt('собака положила передние лапы на плечи девушки, их тень падает на старую полуразрушенную стену'))
    # print(get_reprompt('a cyberpunk hacker in a neon-lit alley, with code reflecting in his chrome glasses, cinematic lighting'))
    # print(get_reprompt('фантастический замок на летающем острове, водопады стекают в облака, стиль фэнтези'))
    # print(get_reprompt('un chaton mignon jouant avec une pelote de laine dans une bibliothèque, lumière du soleil', conversation_history='user: I need something cute and cozy.'))
    # print(get_reprompt('a hyper-realistic portrait of an old fisherman with a weathered face, looking at the stormy sea, 8k, detailed'))
    # print(get_reprompt('astronaut discovering an ancient alien artifact on a desolate martian landscape'))
    # print(get_reprompt('минимализм, японский дзен-сад с сакурой и прудом с карпами кои'))
    # # --- Prompts designed to fail moderation ---
    # print(get_reprompt('обнаженная пара занимается любовью в лесу, откровенная сцена'))
    # print(get_reprompt('человек в форме СС на фоне флага со свастикой'))
    # print(get_reprompt('кровавая сцена резни, много жертв, жестокость крупным планом'))

    # print(rewrite_text_for_tts('a hyper-realistic portrait of an old fisherman with a weathered face, looking at the stormy sea, 8k, detailed', 'test'))
    # print(rewrite_text_for_tts('The event is on 12/10/2025 at 4pm, and tickets cost ~$50-75.', 'test'))
    # print(rewrite_text_for_tts('The script failed with exit code 1. Check /var/log/app.log for details.', 'test'))
    # print(rewrite_text_for_tts('Доставка: 2-3 нед., цена 500-700 руб. Адрес: ул. Строителей, д. 15, кв. 4.', 'test'))
    # print(rewrite_text_for_tts('Hello world, this is a simple sentence.', 'test'))
    # print(rewrite_text_for_tts('For more info, please visit https://example.com/path?query=123#section', 'test'))
    # print(rewrite_text_for_tts('Dr. Smith from the U.K. is arriving on flight BA2490 at 5 p.m.', 'test'))
    # print(rewrite_text_for_tts('The formula for water is H2O. The result is >99%.', 'test'))
    # print(rewrite_text_for_tts('The item costs £20, which is about $25 or 23€.', 'test'))
    # print(rewrite_text_for_tts('My favorite cafe is "Счастье", the bill was 1500 RUB.', 'test'))

    # with open(r'C:\Users\user\Downloads\samples for ai\myachev_Significant_Digits_processed_by_sections.txt', 'r', encoding='utf-8') as f:
    #     text = f.read()
    # summary = sum_big_text(text, 'Кратский пересказ сделай')
    # print(summary)

    chat_cli(model='')
    # chat_cli(model=MODEL_QWEN_3_235B_A22B_THINKING)
    # не хватает токенов для описаний тулзов
    # chat_cli(model=MODEL_LLAMA_4_MAVERICK_17B_128E_INSTRUCT)

    my_db.close()
