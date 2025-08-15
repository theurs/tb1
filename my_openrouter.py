#!/usr/bin/env python3

import base64
import json
import re
import requests
import time
import threading
import traceback
from typing import Any, Dict, List, Optional

import langcodes
from openai import OpenAI, APIStatusError
from sqlitedict import SqliteDict

import cfg
import my_db
import my_log
import my_skills_storage
import utils


# keys {user_id(str):key(str)}
KEYS = SqliteDict('db/open_router_keys.db', autocommit=True)
# {user_id(str):list(model, temperature, max_tokens, maxhistlines, maxhistchars)}
PARAMS = SqliteDict('db/open_router_params.db', autocommit=True)
DEFAULT_FREE_MODEL = 'qwen/qwen3-8b:free'
PARAMS_DEFAULT = [DEFAULT_FREE_MODEL, 1, 4000, 20, 12000]

DEFAULT_FREE_MODEL_FOR_TRANSLATE = 'mistralai/mistral-small-3.2-24b-instruct:free'

# сколько запросов хранить
MAX_MEM_LINES = 10


DEFAULT_TIMEOUT = 120
MAX_TOOL_OUTPUT_LEN = 40000


# блокировка чатов что бы не испортить историю 
# {id:lock}
LOCKS = {}

# не принимать запросы больше чем, это ограничение для телеграм бота, в этом модуле оно не используется
MAX_REQUEST = 1000000
MAX_SUM_REQUEST = 1000000


BASE_URL = "https://openrouter.ai/api/v1"
BASE_URL_BH = 'https://bothub.chat/api/v2/openai/v1'


# если модель не хочет отвечать то возвращает это
FILTERED_SIGN = '________________________________________________________________________--------_____________'


# {user_id: (tokens_in, tokens_out)}
PRICE = {}


SYSTEM_ = []


def clear_mem(mem, user_id: str):
    if user_id not in PARAMS:
        PARAMS[user_id] = ['meta-llama/llama-3-8b-instruct:free', 1, 2000, 5, 6000]
    model, temperature, max_tokens, maxhistlines, maxhistchars = PARAMS[user_id]

    while 1:
        sizeofmem = count_tokens(mem)
        if sizeofmem <= maxhistchars:
            break
        try:
            mem = mem[2:]
        except IndexError:
            mem = []
            break

    return mem[-maxhistlines*2:]
    #return mem[-MAX_MEM_LINES*2:]


def count_tokens(mem: List[Dict[str, Any]]) -> int:
    return sum([len(str(m.get('content', ''))) for m in mem])


def ai(
    prompt: str = '',
    mem: Optional[List[Dict[str, Any]]] = None,
    user_id: str = '',
    system: str = '',
    model: str = '',
    temperature: float = 1.0,
    max_tokens: int = 8000,
    timeout: int = DEFAULT_TIMEOUT,
    response_format: str = 'text',
    json_schema: Optional[Dict] = None,
    reasoning_effort_value_: str = 'none',
    tools: Optional[List[Dict]] = None,
    available_tools: Optional[Dict] = None,
    max_tools_use: int = 10,
) -> str:
    """
    Core entry point for LLM interaction, orchestrating API calls and tool usage.

    This function manages the entire request lifecycle: it retrieves API keys,
    injects system prompts, handles multi-step tool execution loops, and makes
    the final generation call. It also tracks token usage for the given user_id
    in the global `PRICE` dictionary.

    Args:
        prompt: The user's current input string.
        mem: The preceding conversation history.
        user_id: Unique identifier for the user, used for keys, params, and logging.
        system: A system-level instruction for the model's behavior.
        model: The specific model ID to use. If empty, uses the user's default.
        temperature: Controls the randomness of the output. Adjusted for some models.
        max_tokens: The maximum number of tokens for the *final* generated response.
        timeout: Timeout in seconds for each individual API request.
        response_format: The desired output format, e.g., 'text' or 'json'.
        json_schema: A specific JSON schema to enforce if response_format is 'json'.
        reasoning_effort_value_: Overrides the user's default reasoning effort setting.
        tools: A list of tool schemas available for the model to call.
        available_tools: A dictionary mapping tool names to their callable functions.
        max_tools_use: The maximum number of tool calls allowed in a single turn.

    Returns:
        The AI's generated text response. Can also return an error message string,
        a specific sign for content filtering, or an empty string on failure.
    """
    if not prompt and not mem:
        return ''

    # CRITICAL: Initialize or reset the token counter for this specific user and call.
    PRICE[user_id] = (0, 0)


    key = _get_api_key(user_id, model)
    if not key:
        return ''


    start_time = time.monotonic()
    effective_timeout = timeout * 2 if tools and available_tools else timeout

    if user_id not in PARAMS:
        PARAMS[user_id] = PARAMS_DEFAULT
    if user_id != 'test':
        model_, temp_, max_tokens_, _, _ = PARAMS[user_id]
        if not model:
            model = model_
        if max_tokens == 8000: # Use user default if not overridden
            max_tokens = max_tokens_
    else:
        if not model:
            model = DEFAULT_FREE_MODEL

    if 'llama' in model.lower() and temperature > 0:
        temperature = temperature / 2

    mem_ = mem[:] if mem else []

    # --- System Prompt Injection ---
    now = utils.get_full_time()
    # Prepare a list of standard system prompts
    _get_system_prompt()
    standard_systems = [
        f'Current date and time: {now}',
        *SYSTEM_
    ]
    # Add user_id prompt if available, crucial for tools
    if user_id:
        standard_systems.insert(1, f'Use this telegram chat id (user id) for API function calls: {user_id}')

    # Insert user-provided custom system prompt first to give it priority
    if system:
        mem_.insert(0, {"role": "system", "content": system})

    # Insert standard system prompts in reverse to maintain order at the top
    for s_prompt in reversed(standard_systems):
        mem_.insert(0, {"role": "system", "content": s_prompt})


    if prompt:
        mem_.append({"role": "user", "content": prompt})
    # --- End of System Prompt Injection ---


    URL = my_db.get_user_property(user_id, 'base_api_url') or BASE_URL

    # --- Parameter Preparation ---
    sdk_params: Dict[str, Any] = {
        'model': model,
        'messages': mem_,
        'temperature': temperature,
    }

    # Determine the reasoning effort value but DON'T format it for the API.
    # The helper function will handle the provider-specific formatting.
    reasoning_effort = my_db.get_user_property(user_id, 'openrouter_reasoning_effort') or 'none'
    if reasoning_effort_value_ != 'none':
        reasoning_effort = reasoning_effort_value_

    if reasoning_effort and reasoning_effort != 'none':
        sdk_params['reasoning_effort_value'] = reasoning_effort


    if response_format == 'json' or json_schema:
        sdk_params['response_format'] = {'type': 'json_object'}

    # --- Tool-use path ---
    if tools and available_tools:

        # сохраняем маркер для проверки валидности chat_id в модуле my_skills*
        if user_id:
            my_skills_storage.STORAGE_ALLOWED_IDS[user_id] = user_id

        sdk_params['tools'] = tools
        sdk_params['tool_choice'] = "auto"
        sdk_params['max_tokens'] = 4096

        for call_count in range(max_tools_use):
            if time.monotonic() - start_time > effective_timeout:
                return "Global timeout exceeded in tool-use loop."

            try:
                sdk_params['messages'] = mem_
                message_dict = _execute_chat_completion(sdk_params, key, URL, timeout, user_id)

                if not message_dict:
                    # If helper returns None, it means a non-recoverable error occurred
                    my_log.log_openrouter(f'ai:tool-loop: API call failed for user {user_id}')
                    break

                # If the model decides to respond directly without using a tool
                if not message_dict.get('tool_calls'):
                    return message_dict.get('content') or ""

                # Sanitize and append the assistant's response to history
                sanitized_message: Dict[str, Any] = {"role": "assistant"}
                if message_dict.get("content"):
                    sanitized_message["content"] = message_dict["content"]
                if message_dict.get("tool_calls"):
                    sanitized_message["tool_calls"] = message_dict["tool_calls"]
                mem_.append(sanitized_message)


                for tool_call in message_dict['tool_calls']:
                    function_name = tool_call['function']['name']
                    tool_output = ""
                    if function_name in available_tools:
                        function_to_call = available_tools[function_name]
                        try:
                            args = json.loads(tool_call['function']['arguments'])
                            tool_output = function_to_call(**args)
                            if isinstance(tool_output, str) and len(tool_output) > MAX_TOOL_OUTPUT_LEN:
                                tool_output = tool_output[:MAX_TOOL_OUTPUT_LEN]
                        except Exception as e:
                            tool_output = f"Error executing tool '{function_name}': {e}"
                            my_log.log_openrouter(f"Error executing tool: {e}\n{traceback.format_exc()}")
                    else:
                        tool_output = f"Error: Tool '{function_name}' not found."

                    mem_.append({"role": "tool", "tool_call_id": tool_call['id'], "content": str(tool_output)})

            except ValueError:
                # This is the controlled signal that the model doesn't support tools.
                # Silently break the loop and proceed to the final non-tool response.
                break
            except Exception as e:
                error_str = str(e)
                if 'filtered' in error_str.lower(): return FILTERED_SIGN
                my_log.log_openrouter(f'ai:tool-loop: unhandled error: {e} [user_id: {user_id}]')
                # For unexpected errors, it's better to break and try a final response
                break

        if call_count == max_tools_use - 1:
            mem_.append({"role": "user", "content": "Tool call limit reached. Summarize your findings."})

    # --- Final response generation ---
    final_params = sdk_params.copy()
    final_params.pop('tools', None)
    final_params.pop('tool_choice', None)
    final_params['messages'] = mem_
    final_params['max_tokens'] = max_tokens

    try:
        final_message = _execute_chat_completion(final_params, key, URL, timeout, user_id)
        if final_message:
            return final_message.get('content') or ''
        return '' # Return empty string on failure

    except Exception as e:
        error_str = str(e)
        if 'filtered' in error_str.lower(): return FILTERED_SIGN
        my_log.log_openrouter(f'ai:final-call: {e} [user_id: {user_id}]')
        return error_str


def _execute_chat_completion(
    sdk_params: Dict[str, Any],
    key: str,
    url: str,
    timeout: int,
    user_id: str
) -> Optional[Dict[str, Any]]:
    """
    Executes the chat completion call with built-in retry logic and
    provider-specific parameter formatting.

    This helper function handles the low-level details of making the API call.
    It formats parameters like 'reasoning_effort' based on the target provider's
    requirements and silently retries if a model doesn't support a specific feature
    like system prompts or developer instructions.

    Args:
        sdk_params: Parameters for the API call, including an abstract 'reasoning_effort_value'.
        key: The API key.
        url: The base URL for the API.
        timeout: The request timeout in seconds.
        user_id: The user's identifier for token tracking.

    Returns:
        The 'message' part of the response dictionary on success, or None on fatal errors.

    Raises:
        ValueError: If the model signals it doesn't support a feature like tools.
        ConnectionError: For actual network or severe, unrecoverable API errors.
    """
    current_params = sdk_params.copy()

    # Extract the abstract reasoning effort value. It will be formatted below.
    reasoning_effort_value = current_params.pop('reasoning_effort_value', None)

    for attempt in range(2): # Allow one retry for recoverable errors
        try:
            # --- Provider-specific formatting logic ---
            # This block adds the correct reasoning parameter only on the first attempt.
            if reasoning_effort_value and attempt == 0:
                is_openai_compatible = not ('openrouter' in url or 'cerebras' in url)
                if 'cerebras' in url:
                    current_params['reasoning_effort'] = reasoning_effort_value
                elif not is_openai_compatible:
                    current_params['reasoning'] = {"effort": reasoning_effort_value}
                # For standard OpenAI compatible APIs, no parameter is added as it's not supported.

            # --- API Call ---
            is_openai_compatible = not ('openrouter' in url or 'cerebras' in url)
            if is_openai_compatible:
                client = OpenAI(api_key=key, base_url=url)
                response = client.chat.completions.create(**current_params, timeout=timeout)
                if response.usage:
                    in_t, out_t = PRICE.get(user_id, (0, 0))
                    PRICE[user_id] = (in_t + response.usage.prompt_tokens, out_t + response.usage.completion_tokens)
                return response.choices[0].message.model_dump()
            else:
                post_url = url if url.endswith('/chat/completions') else url + '/chat/completions'
                post_url = re.sub(r'(?<!:)//', '/', post_url)
                http_response = requests.post(
                    url=post_url, headers={"Authorization": f"Bearer {key}"}, json=current_params, timeout=timeout
                )

                if http_response.status_code == 200:
                    response_data = http_response.json()
                    if 'usage' in response_data:
                        in_t, out_t = PRICE.get(user_id, (0, 0))
                        prompt_tokens = response_data['usage'].get('prompt_tokens', 0)
                        completion_tokens = response_data['usage'].get('completion_tokens', 0)
                        PRICE[user_id] = (in_t + prompt_tokens, out_t + completion_tokens)
                    return response_data['choices'][0]['message']
                else:
                    raise ConnectionError(http_response.text)

        except (ConnectionError, APIStatusError) as e:
            error_text = str(e).lower()

            # --- Specific error handling for retry ---
            # Case 1: Model doesn't support reasoning/developer instruction.
            if attempt == 0 and 'developer instruction is not enabled' in error_text:
                # Silently remove the unsupported parameters and retry.
                current_params.pop('reasoning_effort', None)
                current_params.pop('reasoning', None)
                reasoning_effort_value = None # Prevent re-adding it on the next loop
                continue # Go to the next attempt

            # Case 2 (NEW): Model does not support system prompts.
            elif attempt == 0 and ('system' in error_text and 'role' in error_text):
                # This error indicates the model rejected the 'system' role.
                # We log it and strip system messages for a retry.
                my_log.log_openrouter(f'_execute_chat_completion: Model {sdk_params["model"]} may not support system prompts. Retrying without them.')
                current_params['messages'] = [
                    msg for msg in current_params['messages'] if msg.get('role') != 'system'
                ]
                continue # Go to the next attempt

            # Case 3: Model doesn't support tools. Signal the caller to stop trying.
            if 'tool' in error_text and ('support' in error_text or 'endpoints' in error_text):
                raise ValueError("Model does not support tools.") from e

            # If it's a different error or the retry failed, log it and raise.
            my_log.log_openrouter(f'_execute_chat_completion: Unrecoverable API Error on attempt {attempt+1}: {e}')
            raise ConnectionError(f"API Error: {e}") from e

        except Exception as e:
            my_log.log_openrouter(f'_execute_chat_completion: Unhandled Exception: {e}\n{traceback.format_exc()}')
            return None # Return None for completely unexpected errors

    return None # Fallback if the retry loop finishes without returning


def _get_api_key(user_id: str, model: str = '') -> Optional[str]:
    """
    Retrieves the appropriate API key based on user_id and model.
    Handles test user, user-specific keys, and default free model keys.

    Returns:
        The API key as a string, or None if no valid key is found.
    """
    # Case 1: Test user with a global key in config
    if user_id == 'test' and hasattr(cfg, 'OPEN_ROUTER_KEY') and cfg.OPEN_ROUTER_KEY:
        return cfg.OPEN_ROUTER_KEY

    # Case 2: User has a specific key stored
    if user_id in KEYS and KEYS[user_id]:
        return KEYS[user_id]

    # Case 3: User has no key, but is using a default free model
    if model == DEFAULT_FREE_MODEL and hasattr(cfg, 'OPEN_ROUTER_KEY'):
        return cfg.OPEN_ROUTER_KEY

    # Case 4: No valid key found
    my_log.log_openrouter(f'_get_api_key: No valid key found for user_id: {user_id}, model: {model}')
    return None


def update_mem(query: str, resp: str, chat_id: str) -> None:
    """
    Appends a user query and an assistant response to the conversation history,
    trims it, removes consecutive duplicates, and saves it to the database.

    Args:
        query (str): The user's message.
        resp (str): The assistant's response.
        chat_id (str): The unique identifier for the chat.
    """
    try:
        # Retrieve current memory or initialize if it doesn't exist
        mem: List[Dict[str, str]] = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_openrouter')) or []

        # Append new messages
        mem.extend([
            {'role': 'user', 'content': query},
            {'role': 'assistant', 'content': resp}
        ])

        # Trim memory to fit size constraints
        mem = clear_mem(mem, chat_id)

        # Defensive check to remove consecutive identical messages.
        # This prevents history corruption from network retries or other glitches.
        if not mem:
            final_mem = []
        else:
            final_mem = [mem[0]]
            for i in range(1, len(mem)):
                if mem[i] != mem[i - 1]:
                    final_mem.append(mem[i])

        # Save the updated and cleaned memory
        my_db.set_user_property(chat_id, 'dialog_openrouter', my_db.obj_to_blob(final_mem))

    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_openrouter(
            f'update_mem: {error}\n\n{error_traceback}\n\nQuery: {query}\n\nResp: {resp}'
        )


def _call_ai_with_retry(
    *args: Any,
    retries: int = 3,
    delay: int = 2,
    **kwargs: Any
) -> str:
    """
    Calls the ai function with a retry mechanism.

    Args:
        *args: Positional arguments to pass to the ai function.
        retries (int): The number of retries if the call returns an empty string.
        delay (int): The delay in seconds between retries.
        **kwargs: Keyword arguments to pass to the ai function.

    Returns:
        The response from the ai function, or an empty string if all retries fail.
    """
    # The first attempt is made outside the loop of retries
    text = ai(*args, **kwargs)
    if text and text != FILTERED_SIGN:
        return text

    for _ in range(retries):
        time.sleep(delay)
        text = ai(*args, **kwargs)
        if text and text != FILTERED_SIGN:
            return text
    return ''


def chat(
    query: str,
    chat_id: str = '',
    temperature: float = 1,
    system: str = '',
    model: str = '',
    timeout: int = DEFAULT_TIMEOUT,
    json_schema: Optional[Dict] = None,
    reasoning_effort_value_: str = 'none',
    tools: Optional[List[Dict]] = None,
    available_tools: Optional[Dict] = None
) -> str:
    """
    Manages a chat conversation, including history loading, AI interaction, and state saving.

    This function acts as a high-level orchestrator. It acquires a lock for the
    chat, retrieves the conversation history, calls the AI, and then delegates
    the saving of the updated history to `update_mem`.

    Args:
        query (str): The user's input message.
        chat_id (str): The unique identifier for the conversation.
        temperature (float): Controls the randomness of the AI's output.
        system (str): A system-level instruction for the AI.
        model (str): The specific model to use for the response.
        timeout (int): The timeout for the AI API call.
        json_schema (Optional[Dict]): A JSON schema to enforce for the response.
        reasoning_effort_value_ (str): Overrides the default reasoning effort.
        tools (Optional[List[Dict]]): A list of available tool schemas.
        available_tools (Optional[Dict]): A map of tool names to callable functions.

    Returns:
        str: The AI's response, or an empty string on failure or content filtering.
    """
    global LOCKS

    # Ensure a lock exists for the given chat_id to prevent race conditions
    if chat_id not in LOCKS:
        LOCKS[chat_id] = threading.Lock()
    lock = LOCKS[chat_id]

    with lock:
        # Load conversation history from the database
        mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_openrouter')) or []

        # Call the AI with retry logic
        text = _call_ai_with_retry(
            query,
            mem,
            user_id=chat_id,
            temperature=temperature,
            system=system,
            model=model,
            timeout=timeout,
            json_schema=json_schema,
            reasoning_effort_value_=reasoning_effort_value_,
            tools=tools,
            available_tools=available_tools
        )

        # Handle the case where the response was filtered
        if text == FILTERED_SIGN:
            return ''

        # If the response is valid, update the message count and conversation history
        if text:
            my_db.add_msg(chat_id, 'openrouter')
            # Delegate the task of updating and saving memory to the specialized function
            update_mem(query, text, chat_id)

        return text


def chat_cli(model: str = ''):
    reset('test')
    while 1:
        q = input('>')
        if q == 'mem':
            print(get_mem_as_string('test'))
            continue
        r = chat(q, 'test', model = model, system='отвечай всегда на языке')
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
        my_log.log_openrouter(f'force: Failed to force message in chat {chat_id}: {error}\n\n{error_traceback}')


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
        my_log.log_openrouter(f'undo:Failed to undo chat {chat_id}: {error}\n\n{error_traceback}')


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
        my_log.log_openrouter(f'get_mem_as_string: {error}\n\n{error_traceback}')
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


def translate(text: str, from_lang: str = '', to_lang: str = '', help: str = '', censored: bool = False, model: str = '') -> str:
    """
    Translates the given text from one language to another.

    Args:
        text (str): The text to be translated.
        from_lang (str, optional): The language of the input text. If not specified, the language will be automatically detected.
        to_lang (str, optional): The language to translate the text into. If not specified, the text will be translated into Russian.
        help (str, optional): Help text for tranlator.
        censored (bool): This parameter is kept for backward compatibility and is no longer used.
        model (str, optional): The specific AI model to use for translation.

    Returns:
        str: The translated text, or an empty string if translation fails or is filtered.
    """
    if not model:
        model = DEFAULT_FREE_MODEL_FOR_TRANSLATE

    if from_lang == '':
        from_lang = 'autodetect'
    if to_lang == '':
        to_lang = 'ru'
    try:
        from_lang_name = langcodes.Language.make(language=from_lang).display_name(language='en') if from_lang != 'autodetect' else 'autodetect'
    except Exception as e:
        my_log.log_translate(f'my_openrouter:translate:error: {e}\n\n{traceback.format_exc()}')
        from_lang_name = from_lang

    try:
        to_lang_name = langcodes.Language.make(language=to_lang).display_name(language='en')
    except Exception as e:
        my_log.log_translate(f'my_openrouter:translate:error: {e}\n\n{traceback.format_exc()}')
        to_lang_name = to_lang

    # Consolidate prompt creation
    context_help = f", this can help you to translate better [{help}]" if help else ""
    query = f'Translate from language [{from_lang_name}] to language [{to_lang_name}], your reply should only be the translated text{context_help}:\n\n{text}'

    # The censorship logic has been removed. The `censored` parameter is ignored.
    translated_text = ai(
        prompt=query,
        user_id='test',
        temperature=1,
        max_tokens=8000,
        model=model
    )

    if translated_text == FILTERED_SIGN:
        return ''

    return translated_text


def list_models(user_id: str = "") -> Optional[List[str]]:
    """
    Retrieves a list of available models for a given user.

    Args:
        user_id: The ID of the user.

    Returns:
        A list of model IDs if successful, None if no API key is found, or an empty list if an error occurs.
    """
    key: Optional[str] = None

    if hasattr(cfg, 'OPEN_ROUTER_KEY') and cfg.OPEN_ROUTER_KEY and user_id == 'test':
        key = cfg.OPEN_ROUTER_KEY
    elif user_id not in KEYS or not KEYS[user_id]:
        return None  # Explicitly return None if no key is found
    else:
        key = KEYS[user_id]

    url: str = my_db.get_user_property(user_id, 'base_api_url') or BASE_URL
    if url.endswith('/chat/completions'):
        url = url[:-17]

    try:
        client = OpenAI(
            api_key=key,
            base_url=url,
        )
        model_list = client.models.list()
        result: List[str] = [x.id for x in model_list]  # Type hint for clarity
        return result
    except Exception as e:  # More specific exception handling is recommended in production
        traceback_error: str = traceback.format_exc()
        my_log.log_openrouter(f'list_models:{e}\n\n{traceback_error}')
        return []  # Return empty list on error


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


def img2txt(
    image_data: bytes | str,
    prompt: str = 'Describe picture',
    model: str = '',
    temperature: float = 1,
    max_tokens: int = 4000,
    timeout: int = DEFAULT_TIMEOUT,
    chat_id: str = '',
    system: str = '',
    reasoning_effort_value_: str = 'none'
) -> str:
    """
    Describes an image by preparing a multimodal payload and calling the main ai function.

    Args:
        image_data: The image data as bytes, or the path to the image file.
        prompt: The prompt to guide the description. Defaults to 'Describe picture'.
        model: The model to use for generating the description.
        temperature: The temperature for the generation 0-2.
        max_tokens: The maximum number of tokens to generate.
        timeout: The request timeout in seconds.
        chat_id: The user ID for fetching specific configurations.
        system: An optional system prompt.
        reasoning_effort_value_: Overrides the user's reasoning effort setting.

    Returns:
        A string containing the description of the image, or an empty string if an error occurs.
    """
    # handle if image_data is a path to a file
    if isinstance(image_data, str):
        try:
            with open(image_data, 'rb') as f:
                image_data = f.read()
        except FileNotFoundError:
            my_log.log_openrouter(f'img2txt: File not found at path: {image_data}')
            return ''

    # encode image to base64
    img_b64_str = base64.b64encode(image_data).decode('utf-8')
    img_type = 'image/png'  # assuming png, other formats might work

    # construct the payload for a multimodal request
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{img_type};base64,{img_b64_str}"},
                },
            ],
        }
    ]

    # Delegate the actual API call to the centralized 'ai' function
    return ai(
        mem=messages,
        user_id=chat_id,
        system=system,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        reasoning_effort_value_=reasoning_effort_value_
    )


def txt2img(
    prompt: str,
    model = '',
    temperature: float = 1,
    max_tokens: int = 4000,
    timeout: int = DEFAULT_TIMEOUT,
    chat_id: str = '',
    ) -> List[bytes]:

    key = KEYS[chat_id]

    if chat_id not in PARAMS:
        PARAMS[chat_id] = PARAMS_DEFAULT

    model_, temperature, max_tokens, maxhistlines, maxhistchars = PARAMS[chat_id]
    if not model:
        model = model_

    URL = my_db.get_user_property(chat_id, 'base_api_url') or BASE_URL

    client = OpenAI(
    api_key=key,
    base_url=URL
    )

    params = {
        'model': model,
        'prompt': prompt,
        'n': 1,
        'size': '1024x1024',
    }

    req = client.images.generate(**params)

    image_url = json.loads(req.model_dump_json())['data'][0]['url']
    print(image_url)


def _get_system_prompt() -> str:
    global SYSTEM_

    if not SYSTEM_:
        import my_skills_general
        SYSTEM_ = my_skills_general.SYSTEM_

    return SYSTEM_


if __name__ == '__main__':
    pass
    my_db.init(backup=False)


    # print(img2txt(r'C:\Users\user\Downloads\samples for ai\картинки\мат задачи 3.jpg', 'извлеки весь текст с картинки, сохрани форматирование', model = 'qwen/qwen2.5-vl-32b-instruct:free', chat_id='test'))


    print(translate('привет дурында, сказала Кагги-Кар', from_lang='ru', to_lang='en'))


    reset('test')
    chat_cli(model='openai/gpt-5-nano')

    # txt2img(
    #     'Girl, portrait, European appearance, long black messy straight hair, dark red sunglasses with a faint red glow coming out from behind it, thin lips, cheekbones, frowning, cyberpunk style, realistic style, dark style, cyberpunk, wearing a red satin waistcoat vest and a necktie over a white satin shirt',
    #     'dall-e-3',
    #     chat_id='[11111] [0]'
    #     )


    # with open(r'C:\Users\user\Downloads\samples for ai\myachev_Significant_Digits_-_znachaschie_tsifryi_106746.txt', 'r', encoding='utf-8') as f:
    #     text = f.read()
    # r = ai(f'сделай хороший перевод на английский этого текста:\n\n{text[:100000]}',
    #          user_id='test',
    #          model = 'openai/gpt-5-nano',
    #          max_tokens=40000,
    #          timeout=6000,
    #          reasoning_effort_value_='minimal')
    # r = r[1]
    # with open('C:/Users/user/Downloads/2.txt', 'w', encoding='utf-8') as f:
    #     f.write(r)
    # print(len(r), r[:1000])


    # a = ai('напиши 10 цифр словами от 0 до 9, в одну строку через запятую', user_id='[1651196] [0]', temperature=0.1, model = 'gemini-flash-1.5-exp')
    # b = ai('напиши 10 цифр словами от 0 до 9, в одну строку через запятую', user_id='test', temperature=0.1, model = 'google/gemini-flash-1.5')
    # print(a, b)

    # chat_cli(model = 'meta-llama/llama-3.1-8b-instruct:free')
    my_db.close()
