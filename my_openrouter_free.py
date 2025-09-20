#!/usr/bin/env python3

import base64
import binascii
import json
import random
import requests
import time
import threading
import traceback
from typing import Optional, List, Union, Dict, Any

from sqlitedict import SqliteDict

import cfg
import my_db
import my_log
import utils


APP_SITE_URL: str = 'https://kun4sun.bot/123/'
APP_NAME: str = 'kun4sun_bot'


# системные сообщения
SYSTEM_ = []


# сколько запросов хранить
MAX_MEM_LINES = 30
MAX_HIST_CHARS = 50000

# блокировка чатов что бы не испортить историю
# {id:lock}
LOCKS = {}

# не принимать запросы больше чем, это ограничение для телеграм бота, в этом модуле оно не используется
MAX_REQUEST = 50000

DEFAULT_MODEL = 'qwen/qwen3-235b-a22b-07-25:free'
DEFAULT_MODEL_FALLBACK = 'qwen/qwen3-235b-a22b:free'
GEMINI25_FLASH_IMAGE = 'google/gemini-2.5-flash-image-preview:free'
# временная модель, неизвестная и ее бекап
CLOACKED_MODEL = 'x-ai/grok-4-fast:free'
CLOACKED_MODEL_FALLBACK = 'qwen/qwen3-235b-a22b:free'
CLOACKED_MODEL_FALLBACK2 = 'deepseek/deepseek-chat-v3.1:free'
CLOACKED_MODEL_FALLBACK3 = 'qwen/qwen3-235b-a22b:free'

# хранилище временно замороженных ключей {key: unfreeze_timestamp}
FROZEN_KEYS = SqliteDict('db/openrouter_frozen_keys.db', autocommit=True)
FROZEN_KEYS_LOCK = threading.Lock()
CURRENT_KEY_INDEX = 0
KEY_INDEX_LOCK = threading.Lock()


def freeze_key(key: str, duration_seconds: int = 86400) -> None:
    """
    Temporarily freezes a rate-limited API key and logs the duration.

    Args:
        key (str): The API key to freeze.
        duration_seconds (int): The duration in seconds for which the key will be frozen.
    """
    with FROZEN_KEYS_LOCK:
        unfreeze_time = time.time() + duration_seconds
        FROZEN_KEYS[key] = unfreeze_time

        # Create a human-readable duration string
        days, rem = divmod(duration_seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, _ = divmod(rem, 60)

        duration_parts = []
        if days > 0:
            duration_parts.append(f"{int(days)}d")
        if hours > 0:
            duration_parts.append(f"{int(hours)}h")
        if minutes > 0:
            duration_parts.append(f"{int(minutes)}m")

        duration_str = " ".join(duration_parts) if duration_parts else f"{duration_seconds}s"

        my_log.log_openrouter_free(
            f'Key ...{key[-4:]} frozen for {duration_str} until {time.ctime(unfreeze_time)}'
        )


def handle_rate_limit(key: str, response: Any) -> None:
    """
    Parses a rate limit response to freeze the key until the reset time.

    If the reset time can be parsed from the response headers, the key is
    frozen until that time plus a 60-second buffer. Otherwise, it falls
    back to the default freeze duration.

    Args:
        key (str): The API key to freeze.
        response (Any): The requests response object from the failed request.
    """
    try:
        # Attempt to parse the JSON response body
        data = response.json()

        # Navigate to the reset timestamp (in milliseconds)
        reset_timestamp_ms = data.get('error', {}).get('metadata', {}).get('headers', {}).get('X-RateLimit-Reset')

        if reset_timestamp_ms:
            # Convert to seconds and calculate duration from now
            reset_time_sec = int(reset_timestamp_ms) / 1000
            current_time_sec = time.time()

            # Add a small buffer (e.g., 60 seconds) to be safe
            duration_seconds = max(0, reset_time_sec - current_time_sec + 60)

            if duration_seconds > 0:
                # The freeze_key function now handles its own logging
                freeze_key(key, int(duration_seconds))
                return
    except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as e:
        # Log the parsing failure, but proceed to default freeze
        my_log.log_openrouter_free(f"Could not parse rate limit reset time: {e}. Falling back to default freeze.")

    # Fallback to default 24-hour freeze if parsing fails or timestamp is not found
    freeze_key(key)


def get_available_key() -> Optional[str]:
    """
    Retrieves the next available, non-frozen API key using a round-robin strategy
    and cleans up expired frozen keys.

    Returns:
        Optional[str]: An available API key, or None if no keys are available.
    """
    global CURRENT_KEY_INDEX
    with FROZEN_KEYS_LOCK:
        # Clean up expired keys from the frozen list
        current_time = time.time()
        expired_keys = [key for key, unfreeze_time in FROZEN_KEYS.items() if current_time > unfreeze_time]
        for key in expired_keys:
            del FROZEN_KEYS[key]
            my_log.log_openrouter_free(f'Key unfrozen: ...{key[-4:]}')

        # Get the list of all keys and filter out the currently frozen ones
        all_keys = cfg.OPEN_ROUTER_FREE_KEYS if hasattr(cfg, 'OPEN_ROUTER_FREE_KEYS') else []
        frozen_keys_set = set(FROZEN_KEYS.keys())
        available_keys = [key for key in all_keys if key not in frozen_keys_set]

    if not available_keys:
        # If no keys are available, check if any are frozen and report when the next one is free
        if FROZEN_KEYS:
            next_unfreeze_time = min(FROZEN_KEYS.values())
            remaining_seconds = max(0, next_unfreeze_time - current_time)

            # Human-readable duration
            days, rem = divmod(remaining_seconds, 86400)
            hours, rem = divmod(rem, 3600)
            minutes, _ = divmod(rem, 60)

            duration_parts = []
            if days > 0:
                duration_parts.append(f"{int(days)}d")
            if hours > 0:
                duration_parts.append(f"{int(hours)}h")
            # Show minutes if it's the largest unit or there's a remainder
            if minutes > 0 or not duration_parts:
                duration_parts.append(f"{int(minutes)}m")

            duration_str = " ".join(duration_parts) if duration_parts else "0m"

            my_log.log_openrouter_free(
                f'No available keys. Next unfreezes in ~{duration_str} at {time.ctime(next_unfreeze_time)}'
            )
        else:
            # This case means no keys are defined in the config at all
            my_log.log_openrouter_free('No available (non-frozen) API keys.')
        return None

    # Select the next key using round-robin logic in a thread-safe manner
    with KEY_INDEX_LOCK:
        # Ensure the index wraps around the current list of available keys
        index = CURRENT_KEY_INDEX % len(available_keys)
        key_to_return = available_keys[index]
        # Move to the next index for the subsequent call
        CURRENT_KEY_INDEX += 1

    return key_to_return


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


def ai(
    prompt: str = '',
    mem: Optional[List[Dict[str, Any]]] = None,
    user_id: str = '',
    system: str = '',
    model: str = DEFAULT_MODEL,
    temperature: float = 1.0,
    max_tokens: int = 4000,
    timeout: int = 120,
    response_format: Optional[Dict[str, str]] = None,
    tools: Optional[List[Dict]] = None,
    available_tools: Optional[Dict[str, Any]] = None,
    tool_choice: Optional[str] = None,
    max_tools_use: int = 10
) -> str:
    """
    Sends a request to the OpenRouter Free API with tool-use, JSON, and robust retry logic.

    Args:
        prompt (str, optional): The user's input. Defaults to ''.
        mem (Optional[List[Dict[str, Any]]], optional): Conversation history. Defaults to None.
        user_id (str, optional): Unique user identifier. Defaults to ''.
        system (str, optional): System-level instructions. Defaults to ''.
        model (str, optional): The model to use (must end in ':free'). Defaults to DEFAULT_MODEL.
        temperature (float, optional): Controls randomness. Defaults to 1.0.
        max_tokens (int, optional): Max tokens in the final response. Defaults to 4000.
        timeout (int, optional): Total timeout in seconds for all retries. Defaults to 120.
        response_format (Optional[Dict[str, str]], optional): Enforces a response format, e.g., {"type": "json_object"}. Defaults to None.
        tools (Optional[List[Dict]], optional): A list of tool schemas for the model. Defaults to None.
        available_tools (Optional[Dict[str, Any]], optional): A map of tool names to their Python functions. Defaults to None.
        tool_choice (Optional[str], optional): Controls tool usage ('auto', 'any', 'none'). Defaults to 'auto' if tools are provided.
        max_tools_use (int, optional): Safety limit for tool calls in a single turn. Defaults to 10.

    Returns:
        str: The AI's response, or an empty string on failure.
    """
    if not model or not model.endswith(':free') and model not in (CLOACKED_MODEL, CLOACKED_MODEL_FALLBACK):
        my_log.log_openrouter_free(f"ai: Model '{model}' is not a valid free model.")
        return ''

    if not prompt and not mem:
        return ''

    if not hasattr(cfg, 'OPEN_ROUTER_FREE_KEYS') or not cfg.OPEN_ROUTER_FREE_KEYS:
        my_log.log_openrouter_free("ai: No OPEN_ROUTER_FREE_KEYS configured.")
        return ''

    if 'llama' in model and temperature > 0:
        temperature /= 2
    if model in (CLOACKED_MODEL, CLOACKED_MODEL_FALLBACK):
        temperature /= 2

    reasoning = None
    if 'grok-4-fast' in model:
        reasoning = {'effort': 'medium'} # high, medium, low

    # Initialize messages from memory
    messages: List[Dict[str, Any]] = list(mem) if mem is not None else []

    # Inject system prompts
    now = utils.get_full_time()
    system_prompts = (
        f'Current date and time: {now}',
        f'Telegram user id you are talking with: {user_id}',
        *SYSTEM_
    )

    if system:
        messages.insert(0, {"role": "system", "content": system})
    for s in reversed(system_prompts):
        messages.insert(0, {"role": "system", "content": s})
    if prompt:
        messages.append({'role': 'user', 'content': prompt})

    result = ''
    start_time = time.monotonic()

    # Outer loop for network retries
    for attempt in range(3):
        if time.monotonic() - start_time > timeout:
            my_log.log_openrouter_free(f"ai: Global timeout of {timeout}s exceeded.")
            break

        key = get_available_key()
        if not key:
            # get_available_key already logs the reason
            return ''

        try:
            # Inner loop for multi-step tool calls
            for _ in range(max_tools_use):
                remaining_time = timeout - (time.monotonic() - start_time)
                if remaining_time <= 0:
                    raise requests.exceptions.Timeout("Global timeout exceeded within tool loop.")

                # Prepare API parameters for this step
                payload: Dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                if reasoning:
                    payload['reasoning'] = reasoning


                if response_format:
                    payload['response_format'] = response_format
                if tools and available_tools:
                    payload['tools'] = tools
                    payload['tool_choice'] = tool_choice or "auto"

                # Make the API call
                response = requests.post(
                    url="https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {key}",
                        "HTTP-Referer": APP_SITE_URL,
                        "X-Title": APP_NAME,
                    },
                    data=json.dumps(payload),
                    timeout=remaining_time,
                )

                # --- Handle response status ---
                if response.status_code == 429:
                    handle_rate_limit(key, response)
                    # Break inner loop and retry with a new key in the outer loop
                    break
                elif 400 <= response.status_code < 500:
                    my_log.log_openrouter_free(f'ai: Client error {response.status_code}. Aborting. Response: {response.text[:500]}')
                    return '' # No retry for client errors
                elif response.status_code >= 500:
                    my_log.log_openrouter_free(f'ai: Server error {response.status_code} on attempt {attempt + 1}. Retrying...')
                    time.sleep(5)
                    # Break inner loop and retry with a new key in the outer loop
                    break
                elif response.status_code != 200:
                    my_log.log_openrouter_free(f'ai: Unexpected status {response.status_code}. Retrying... Response: {response.text[:500]}')
                    break

                # --- Process successful response ---
                response_json = response.json()
                response_message = response_json['choices'][0]['message']
                tool_calls = response_message.get('tool_calls')

                if not tool_calls:
                    result = response_message.get('content', '').strip()
                    # Final answer received, break both loops
                    return result

                # Process tool calls
                messages.append(response_message)
                for tool_call in tool_calls:
                    function_name = tool_call['function']['name']
                    function_to_call = available_tools.get(function_name)
                    tool_output = ''

                    if function_to_call:
                        try:
                            function_args = json.loads(tool_call['function']['arguments'])
                            tool_output = function_to_call(**function_args)
                        except Exception as e:
                            tool_output = f"Error executing tool {function_name}: {e}"
                            my_log.log_openrouter_free(tool_output)
                    else:
                        tool_output = f"Error: Tool '{function_name}' not found."

                    messages.append({
                        "tool_call_id": tool_call['id'],
                        "role": "tool",
                        "name": function_name,
                        "content": str(tool_output),
                    })
                # Continue inner loop to get model's response to tool output
                continue
            else:
                # This 'else' belongs to the inner for-loop.
                # It runs if the loop completes without a 'break' (i.e., tool limit reached).
                my_log.log_openrouter_free(f"ai: Exceeded max tool calls ({max_tools_use}).")
                return "Tool call limit reached. Please try again."

        except requests.exceptions.RequestException as e:
            my_log.log_openrouter_free(f'ai: Request failed on attempt {attempt + 1}: {e}')
            if attempt < 2:
                time.sleep(2)

    if not result and model == DEFAULT_MODEL:
        return ai(prompt, mem, user_id, system, DEFAULT_MODEL_FALLBACK, temperature, max_tokens, timeout, response_format, tools, available_tools, tool_choice, max_tools_use)

    return result


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
        my_log.log_openrouter_free(f'my_openrouter:update_mem: {error}\n\n{error_traceback}\n\n{query}\n\n{resp}\n\n{mem}')

    my_db.set_user_property(chat_id, 'dialog_openrouter', my_db.obj_to_blob(mem__))


def chat(
    query: str,
    chat_id: str = '',
    temperature: float = 1,
    system: str = '',
    model: str = '',
    tools: Optional[List[Dict]] = None,
    available_tools: Optional[Dict[str, Any]] = None,
    tool_choice: Optional[str] = None,
) -> str:
    """
    Handles a turn in a conversation with a user, managing history and tool usage.

    This function acts as a thread-safe wrapper around the `ai` function. It retrieves
    the conversation history for a given chat_id, calls the core AI logic with the
    user's query and any available tools, and then updates the history with the
    new user message and the final AI response.

    Args:
        query (str): The user's current message.
        chat_id (str, optional): The unique identifier for the chat session.
            Defaults to ''.
        temperature (float, optional): Controls the randomness of the AI's output.
            Defaults to 1.
        system (str, optional): A one-time system prompt for this specific turn.
            Defaults to ''.
        model (str, optional): The specific model to use for this request.
            Defaults to ''.
        tools (Optional[List[Dict]], optional): The JSON schema definition of
            available tools. Defaults to None.
        available_tools (Optional[Dict[str, Any]], optional): A mapping of tool
            names to their callable Python functions. Defaults to None.
        tool_choice (Optional[str], optional): The strategy for tool usage
            (e.g., 'auto', 'none'). Defaults to None.

    Returns:
        str: The AI's final text response. Returns an empty string if the request fails.
    """
    global LOCKS
    if chat_id in LOCKS:
        lock = LOCKS[chat_id]
    else:
        lock = threading.Lock()
        LOCKS[chat_id] = lock

    with lock:
        mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_openrouter')) or []

        text = ai(
            prompt=query,
            mem=mem,
            user_id=chat_id,
            temperature=temperature,
            system=system,
            model=model,
            tools=tools,
            available_tools=available_tools,
            tool_choice=tool_choice,
        )

        if text:
            # Note: This logic for DB logging might need adjustment if free models change names
            if DEFAULT_MODEL in model:
                my_db.add_msg(chat_id, 'llama-4-maverick')
            elif DEFAULT_MODEL_FALLBACK in model:
                my_db.add_msg(chat_id, 'llama-4-scout')

            # This logic assumes the 'ai' function returns the final text after tool use.
            # The full history, including tool calls, is managed inside 'ai' but not returned.
            # So we append the original query and the final answer to the persistent memory.
            mem.append({'role': 'user', 'content': query})
            mem.append({'role': 'assistant', 'content': text})
            mem = clear_mem(mem, chat_id)
            my_db.set_user_property(chat_id, 'dialog_openrouter', my_db.obj_to_blob(mem))

        return text
    return ''


def chat_cli(
    model: str = '',
    tools: Optional[List[Dict]] = None,
    available_tools: Optional[Dict[str, Any]] = None,
    tool_choice: Optional[str] = None
):
    """
    Command-line interface for chatting with the AI for testing purposes.

    Args:
        model (str, optional): The model to use. Defaults to ''.
        tools (Optional[List[Dict]], optional): Tool schemas to be used. Defaults to None.
        available_tools (Optional[Dict[str, Any]], optional): Map of tool names to functions. Defaults to None.
        tool_choice (Optional[str], optional): Tool choice strategy. Defaults to None.
    """
    reset('test')
    while 1:
        q = input('>')
        if q == 'mem':
            print(get_mem_as_string('test'))
            continue
        r = chat(
            q,
            'test',
            model=model,
            system='отвечай всегда по-русски', # Example of a one-time system prompt
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
        my_log.log_openrouter_free(f'Failed to force message in chat {chat_id}: {error}\n\n{error_traceback}')


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
        my_log.log_openrouter_free(f'Failed to undo chat {chat_id}: {error}\n\n{error_traceback}')


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
        my_log.log_openrouter_free(f'get_mem_as_string: {error}\n\n{error_traceback}')
        return ''


def img2txt(
    image_data: bytes,
    prompt: str = 'Describe picture',
    model = DEFAULT_MODEL,
    temperature: float = 1,
    max_tokens: int = 2000,
    timeout: int = 120,
    chat_id: str = '',
    system: str = '',
    ) -> str:
    """
    Describes an image using the specified model and parameters.

    Args:
        image_data: The image data as bytes.
        prompt: The prompt to guide the description. Defaults to 'Describe picture'.
        model: The model to use for generating the description. Defaults to DEFAULT_MODEL.
        temperature: The temperature parameter for controlling the randomness of the output. Defaults to 1.
        max_tokens: The maximum number of tokens to generate. Defaults to 2000.
        timeout: The timeout for the request in seconds. Defaults to 120.

    Returns:
        A string containing the description of the image, or an empty string if an error occurs.
    """

    if isinstance(image_data, str):
        with open(image_data, 'rb') as f:
            image_data = f.read()

    if not model:
        model = DEFAULT_MODEL

    if not model.endswith(':free'):
        return ''

    if not prompt:
        prompt = 'Describe picture'
        return ''

    if not hasattr(cfg, 'OPEN_ROUTER_FREE_KEYS'):
        return ''

    if 'llama' in model and temperature > 0:
        temperature = temperature / 2

    base64_image = base64.b64encode(image_data).decode()

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
                "image_url": {
                    "url": f"data:image/jpeg;base64,{base64_image}"
                }
            }
        ]
        }
    ]
    if system:
        mem.insert(0, {'role': 'system', 'content': system})

    result = ''

    for _ in range(3):
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {random.choice(cfg.OPEN_ROUTER_FREE_KEYS)}",
                "HTTP-Referer": f"{APP_SITE_URL}",  # Optional, for including your app on openrouter.ai rankings.
                "X-Title": f"{APP_NAME}",  # Optional. Shows in rankings on openrouter.ai.
            },
            data=json.dumps({

                "model": model,
                "temperature": temperature,
                "messages": mem,
                "max_tokens": max_tokens

            }),
            timeout=timeout,
        )

        status = response.status_code
        if status == 200:
            try:
                result = response.json()['choices'][0]['message']['content'].strip()
                break
            except Exception as error:
                my_log.log_openrouter_free(f'Failed to parse response: {error}\n\n{str(response)}')
                result = ''
                time.sleep(2)
        else:
            my_log.log_openrouter_free(f'Bad response.status_code\n\n{str(response)[:2000]}')
            time.sleep(2)
    if chat_id:
        my_db.add_msg(chat_id, model)

    if not result and model == DEFAULT_MODEL:
        result = img2txt(image_data, prompt, DEFAULT_MODEL_FALLBACK, temperature, max_tokens, timeout, chat_id, system)

    return result


# def voice2txt(
#     voice_data: bytes,
#     model = 'google/gemini-flash-8b-1.5-exp',
#     temperature: float = 0,
#     max_tokens: int = 2000,
#     timeout: int = 120) -> str:
#     """
#     Transcribes audio data to text using the specified model and parameters.

#     Args:
#         voice_data: The audio data as bytes.
#         model: The model to use for generating the transcription. Defaults to 'google/gemini-flash-8b-1.5-exp'.
#         temperature: The temperature parameter for controlling the randomness of the output. Defaults to 0.
#         max_tokens: The maximum number of tokens to generate. Defaults to 2000.
#         timeout: The timeout for the request in seconds. Defaults to 120.

#     Returns:
#         A string containing the transcribed text, or an empty string if an error occurs.
#     """

#     if isinstance(voice_data, str):
#         with open(voice_data, 'rb') as f:
#             voice_data = f.read()

#     if not model:
#         model = 'google/gemini-flash-8b-1.5-exp'

#     # if not model.endswith(':free'):
#     #     return ''

#     if not hasattr(cfg, 'OPEN_ROUTER_FREE_KEYS'):
#         return ''

#     base64_voice = base64.b64encode(voice_data).decode()

#     result = ''

#     for _ in range(3):
#         response = requests.post(
#             url="https://openrouter.ai/api/v1/chat/completions",
#             headers={
#                 "Authorization": f"Bearer {random.choice(cfg.OPEN_ROUTER_FREE_KEYS)}",
#                 "HTTP-Referer": f"{APP_SITE_URL}",  # Optional, for including your app on openrouter.ai rankings.
#                 "X-Title": f"{APP_NAME}",  # Optional. Shows in rankings on openrouter.ai.
#             },
#             data=json.dumps({

#                 "model": model,
#                 "temperature": temperature,
#                 "messages": [
#                     {
#                     "role": "user",
#                     "content": [
#                         {
#                             "type": "text",
#                             "text": 'transcribe it'
#                         },
#                         {
#                             "type": "voice_url",
#                             "voice_url": {
#                                 "url": f"data:audio/mpeg;base64,{base64_voice}"
#                             }
#                         }
#                     ]
#                     }
#                 ],
#                 "max_tokens": max_tokens

#             }),
#             timeout=timeout,
#         )

#         status = response.status_code
#         if status == 200:
#             try:
#                 result = response.json()['text'].strip()
#                 break
#             except Exception as error:
#                 my_log.log_openrouter_free(f'Failed to parse response: {error}\n\n{str(response)}')
#                 result = ''
#                 time.sleep(2)
#         else:
#             my_log.log_openrouter_free(f'Bad response.status_code\n\n{str(response)[:2000]}')
#             time.sleep(2)

#     return result


#### flash25 image generate and edit ####


def _send_image_request(
    model: str,
    messages: List[Dict[str, Any]],
    user_id: str,
    timeout: int,
    log_context: str,
    temperature: float,
    key: str = '',
) -> Optional[bytes]:
    """
    Sends a request to the OpenRouter API for image generation or editing with a total timeout.

    This private helper function handles the entire request lifecycle, including
    authentication, payload construction, sending the request, retrying on
    server errors, and parsing the response to extract the image data, all
    within a cumulative timeout using a monotonic clock for reliability.

    Args:
        model (str): The model identifier to use for the request.
        messages (List[Dict[str, Any]]): The list of messages forming the conversation.
        user_id (str): The ID of the user initiating the request, for logging purposes.
        timeout (int): The total request timeout in seconds for all retries.
        log_context (str): A string identifier for the calling function (e.g., 'txt2img').
        temperature (float): The temperature for the generation.
        key (str): The API key to use for the request.

    Returns:
        Optional[bytes]: The image data as bytes if the request is successful, otherwise None.
    """
    if not hasattr(cfg, 'OPEN_ROUTER_FREE_KEYS') or not cfg.OPEN_ROUTER_FREE_KEYS:
        if not key:
            return None

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }

    # Disable safety filters for Google Gemini models
    if "gemini" in model.lower():
        payload["safety_settings"] = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]

    start_time = time.monotonic()  # Use monotonic clock for reliable timeout measurement

    for attempt in range(3):  # Retry loop
        elapsed_time = time.monotonic() - start_time
        remaining_time = timeout - elapsed_time

        # Check if the total time has expired
        if remaining_time <= 0:
            my_log.log_openrouter_free(f'{log_context}: Total timeout of {timeout}s exceeded. Aborting.')
            return None

        if not key:
            key = get_available_key()

        if not key:
            # The get_available_key function has already logged the details.
            return None

        try:
            response = requests.post(
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "HTTP-Referer": APP_SITE_URL,
                    "X-Title": APP_NAME,
                },
                data=json.dumps(payload),
                timeout=remaining_time,  # Use the remaining time for this attempt's timeout
            )

            # Handle rate limit error by freezing the key and retrying
            if response.status_code == 429:
                handle_rate_limit(key, response)
                my_log.log_openrouter_free(f'{log_context}: Rate limit exceeded for key. Freezing and retrying...')
                continue

            # Differentiate other client/server errors for logging
            if 400 <= response.status_code < 500:
                my_log.log_openrouter_free(f'{log_context}: Client error {response.status_code}. Aborting retries.\n{response.text[:500]}')
                return None  # No point in retrying client errors

            if response.status_code != 200:
                my_log.log_openrouter_free(f'{log_context}: Bad response status {response.status_code}. Retrying...\n{response.text[:500]}')
                time.sleep(5)
                continue

            json_response = None
            try:
                json_response = response.json()
                # Robust parsing using .get() to avoid KeyErrors
                base64_content = (json_response.get('choices', [{}])[0]
                                  .get('message', {})
                                  .get('images', [{}])[0]
                                  .get('image_url', {})
                                  .get('url'))

                if not base64_content:
                    if 'PROHIBITED_CONTENT' in str(response.text):
                        return None
                    # Check if there's a text response instead of an image URL.
                    # This indicates a model-level refusal or alternative reply, not a transient error.
                    if json_response:
                        text_content = (json_response.get('choices', [{}])[0]
                                        .get('message', {})
                                        .get('content'))
                        if text_content:
                            # my_log.log_openrouter_free(f'{log_context}: Received text response instead of image. Aborting.\nResponse: {text_content[:200].strip()}')
                            return None
                    my_log.log_openrouter_free(f'{log_context}: No image URL found in response. Aborting.\nResponse: {response.text[:500]}')
                    continue

                if 'base64,' in base64_content:
                    base64_content = base64_content.split('base64,', 1)[1].strip(') \n')

                if user_id:
                    my_db.add_msg(user_id, 'img ' + model)

                return base64.b64decode(base64_content)

            except (json.JSONDecodeError, IndexError, binascii.Error) as e:
                my_log.log_openrouter_free(f'{log_context}: Failed to parse/decode response: {e}\nResponse: {response.text[:500]}')
                time.sleep(5)

        except requests.exceptions.RequestException as e:
            # This will catch timeouts from requests and other connection errors
            my_log.log_openrouter_free(f'{log_context}: Request failed on attempt {attempt + 1}: {e}. Retrying...')
            time.sleep(5)

    return None


def txt2img(
    prompt: str,
    user_id: str = '',
    model: str = GEMINI25_FLASH_IMAGE,
    timeout: int = 60,
    system_prompt: str = '',
    temperature: float = 1.0,
    key: str = '',
) -> Optional[bytes]:
    """
    Generates an image from a text prompt using a specified model on OpenRouter.

    Args:
        prompt (str): The text prompt describing the desired image.
        user_id (str): The user's ID for logging purposes. Defaults to ''.
        model (str): The model to use for generation. Defaults to a free Gemini model.
        timeout (int): Request timeout in seconds. Defaults to 60.
        system_prompt (str): An optional system prompt to guide the model. Defaults to ''.
        temperature (float): The generation temperature. Defaults to 1.0.
        key (str): The API key to use for authentication. Defaults to ''.

    Returns:
        Optional[bytes]: The generated image data as bytes if successful, otherwise None.
    """

    # нет больше такой модели
    if model == 'google/gemini-2.5-flash-image-preview:free':
        return None

    if not model.endswith(':free'):
        if not key:
            my_log.log_openrouter_free(f"txt2img: Model '{model}' is not a free model.")
            return None

    messages: List[Dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    return _send_image_request(
        model=model,
        messages=messages,
        user_id=user_id,
        timeout=timeout,
        log_context='txt2img',
        temperature=temperature,
        key=key
    )


def edit_image(
    prompt: str,
    source_image: Union[bytes, str, List[Union[bytes, str]]],
    user_id: str = '',
    model: str = GEMINI25_FLASH_IMAGE,
    timeout: int = 60,
    system_prompt: str = '',
    temperature: float = 1.0,
    key: str = '',
) -> Optional[bytes]:
    """
    Edits an image based on a text prompt using a specified model on OpenRouter.
    Can accept one or more source images.

    Args:
        prompt (str): The text prompt describing the desired edit.
        source_image (Union[bytes, str, List[Union[bytes, str]]]): The source image(s)
            data as bytes, a file path (str), or a list of bytes/paths.
        user_id (str): The user's ID for logging purposes. Defaults to ''.
        model (str): The model to use for generation. Defaults to a free Gemini model.
        timeout (int): Request timeout in seconds. Defaults to 60.
        system_prompt (str): An optional system prompt to guide the model. Defaults to ''.
        temperature (float): The generation temperature. Defaults to 1.0.
        key (str): The API key to use for authentication. Defaults to ''.

    Returns:
        Optional[bytes]: The edited image data as bytes if successful, otherwise None.
    """

    # нет больше такой модели
    if model == 'google/gemini-2.5-flash-image-preview:free':
        return None

    if not model.endswith(':free'):
        if not key:
            my_log.log_openrouter_free(f"edit_image: Model '{model}' is not a free model.")
            return None

    # Normalize input to always be a list of images
    if isinstance(source_image, (bytes, str)):
        image_list = [source_image]
    else:
        image_list = source_image

    # Prepare content for the API message
    content_list: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]

    for image_item in image_list:
        img_bytes = image_item
        if isinstance(image_item, str):
            with open(image_item, 'rb') as f:
                img_bytes = f.read()

        base64_image = base64.b64encode(img_bytes).decode('utf-8')
        content_list.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
        })

    messages: List[Dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": content_list})

    return _send_image_request(
        model=model,
        messages=messages,
        user_id=user_id,
        timeout=timeout,
        log_context='edit_image',
        temperature=temperature,
        key=key
    )


def init():
    global SYSTEM_
    import my_skills_general
    SYSTEM_ = my_skills_general.SYSTEM_


#### flash25 image generate and edit ####

if __name__ == '__main__':
    pass
    my_db.init(backup=False)
    init()

    # reset('test')
    chat_cli(model = CLOACKED_MODEL)


    # with open(r'C:\Users\user\Downloads\samples for ai\большая книга.txt', 'r', encoding='utf-8') as f:
    #     text = f.read()
    # q = f'Кратко перескажи 32 главу\n\n {text[:600000]}'
    # r = ai(q, model = DEFAULT_MODEL_FALLBACK)
    # print(r)


    # print(img2txt('C:/Users/user/Downloads/1.jpg', 'что тут происходит, ответь по-русски', model='meta-llama/llama-3.2-11b-vision-instruct:free'))
    # print(img2txt(r'C:\Users\user\Downloads\samples for ai\картинки\мат задачи.jpg', 'что тут происходит, ответь по-русски', model='meta-llama/llama-4-maverick:free'))
    # print(voice2txt('C:/Users/user/Downloads/1.ogg'))

    # img = txt2img('сигарета в руке крупным планом', model='google/gemini-2.5-flash-image-preview', key=cfg.OPEN_ROUTER_KEY)
    # if img:
    #     with open(r'C:/Users/user/Downloads/1.png', 'wb') as f:
    #         f.write(img)

    # img1 = r'C:\Users\user\Downloads\samples for ai\картинки\студийное фото человека.png'
    # img2 = edit_image('помести его внутрь тардис, и пусть он курит папиросу', img1, model='google/gemini-2.5-flash-image-preview', key=cfg.OPEN_ROUTER_KEY)
    # if img2:
    #     with open(r'C:/Users/user/Downloads/2.png', 'wb') as f:
    #         f.write(img2)

    # img1 = r'C:\Users\user\Downloads\samples for ai\картинки\студийное фото человека.png'
    # img2 = r'C:\Users\user\Downloads\samples for ai\картинки\фотография улицы.png'
    # img3 = edit_image('помести человека на улице', (img1, img2))
    # if img3:
    #     with open(r'C:/Users/user/Downloads/3.png', 'wb') as f:
    #         f.write(img3)


    my_db.close()
