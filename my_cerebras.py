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

import cfg
import my_db
import my_log
import my_skills
import utils


MODEL_GPT_OSS_120B = 'gpt-oss-120b'
MODEL_QWEN_3_CODER_480B = 'qwen-3-coder-480b'
MODEL_QWEN_3_235B_A22B_INSTRUCT = 'qwen-3-235b-a22b-instruct-2507'
MODEL_QWEN_3_235B_A22B_THINKING = 'qwen-3-235b-a22b-thinking-2507'
MODEL_LLAMA_4_MAVERICK_17B_128E_INSTRUCT = 'llama-4-maverick-17b-128e-instruct'
MODEL_LLAMA_4_SCOUT_17B_16E_INSTRUCT = 'llama-4-scout-17b-16e-instruct'
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


##[tool use]######

def calc(expression: str, strict: bool, user_id: str) -> str:
    """Calculate expression with python. The expression can be strict or a free-form task;
    strict expressions are calculated on a simple calculator, while free-form expressions
    are executed on a virtual machine and can be of almost any complexity.

    Args:
        expression: The expression to calculate.
        strict: Whether the expression is strict or not.
        user_id: The telegram user ID to send the search results to.

    Returns:
        A string containing the result of the calculation.

    Examples: calc("56487*8731", strict=True, user_id="[12345678] [0]") -> '493187997'
              calc("pow(10, 2)", strict=True, user_id="[12345678] [0]") -> '100'
              calc("math.sqrt(2+2)/3", strict=True, user_id="[12345678] [0]") -> '0.6666666666666666'
              calc("decimal.Decimal('0.234234')*2", strict=True, user_id="[12345678] [0]") -> '0.468468'
              calc("numpy.sin(0.4) ** 2 + random.randint(12, 21)", strict=True, user_id="[12345678] [0]")
              calc('Generate lists of numbers for plotting the graph of the sin(x) function in the range from -5 to 5 with a step of 0.1.', strict=False, user_id="[12345678] [0]")
              etc
    Returns:
        A string containing the result of the calculation."""
    return my_skills.calc(expression, strict, user_id)


def search_google_fast(query: str, lang: str, user_id: str) -> str:
    """
    Fast searches Google for the given query and returns the search results.
    You are able to mix this functions with other functions and your own ability to get best results for your needs.
    This tool should not be used instead of other functions, such as text translation.

    Args:
        query: The search query string.
        lang: The language to use for the search - 'ru', 'en', etc.
        user_id: The user ID to send the search results to.

    Returns:
        A string containing the search results.
        In case of an error, returns a string 'ERROR' with the error description.
    """
    return my_skills.search_google_fast(query, lang, user_id)


def search_google_deep(query: str, lang: str, user_id: str) -> str:
    """
    Deep searches Google for the given query and returns the search results.
    You are able to mix this functions with other functions and your own ability to get best results for your needs.
    This tool can also find direct links to images.

    Args:
        query: The search query string.
        lang: The language to use for the search - 'ru', 'en', etc.
        user_id: The chat ID to send the search results to.

    Returns:
        A string containing the search results.
        In case of an error, returns a string 'ERROR' with the error description.
    """
    return my_skills.search_google_deep(query, lang, user_id)


def download_text_from_url(url: str) -> str:
    """Downloads text content from a URL, including YouTube subtitles.

    Fetches textual content from a web page or extracts subtitles from
    a YouTube video. The result is cached for one hour. The output is
    truncated to the MAX_REQUEST character limit.

    Args:
        url: The URL of the web page or YouTube video to process.

    Returns:
        The extracted text content. On failure, returns a string
        with error information.
    """
    return my_skills.download_text_from_url(url)


# The schemas tell the model HOW to use the tools.
calculator_schema = {
    "type": "function",
    "function": {
        # The exact name of the function to be called.
        "name": "calc",

        # This description is critical. The LLM uses it to decide WHEN to use this tool.
        "description": (
            "Executes a Python expression. It has two modes: "
            "1. Simple calculator (`strict=True`) for math formulas. "
            "2. Powerful virtual machine (`strict=False`) for complex, free-form tasks."
        ),

        # This defines the function's arguments.
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    # Description for the 'expression' parameter.
                    "description": "The mathematical formula (e.g., '5 * (2+3)') or a free-form task in natural language (e.g., 'plot a sine wave from -5 to 5')."
                },
                "strict": {
                    "type": "boolean",
                    # Description for the 'strict' parameter. Crucial for the model to choose correctly.
                    "description": "Set to `True` for simple math. Set to `False` for complex tasks, code generation, or natural language requests."
                },
                "user_id": {
                    "type": "string",
                    # Description for the 'user_id' parameter.
                    "description": "The unique telegram identifier for the user, passed from the system context. Example: '[12345678] [0]'"
                }
            },
            # A list of all mandatory parameters.
            "required": ["expression", "strict", "user_id"]
        }
    }
}

search_google_fast_schema = {
    "type": "function",
    "function": {
        # The exact name of the Python function.
        "name": "search_google_fast",

        # A clear, direct instruction for the LLM.
        # It defines the tool's purpose and its limitations.
        "description": (
            "Performs a fast Google search for current events, facts, or real-world data. "
            "This is for general-purpose searching. Do NOT use it for tasks that have a more "
            "specific tool, such as text translation."
        ),

        # Defines the function's arguments.
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    # A concise description of the 'query' parameter.
                    "description": "The search term or question to look up on Google."
                },
                "lang": {
                    "type": "string",
                    # Provides examples to guide the model.
                    "description": "The two-letter language code for the search (e.g., 'en', 'ru', 'de')."
                },
                "user_id": {
                    "type": "string",
                    # Clarifies the source of this parameter.
                    "description": "The unique telegram identifier for the user, passed from the system context. Example: '[12345678] [0]'"
                }
            },
            # All parameters are mandatory.
            "required": ["query", "lang", "user_id"]
        }
    }
}

search_google_deep_schema = {
    "type": "function",
    "function": {
        # The exact name of the Python function.
        "name": "search_google_deep",

        # A clear, direct instruction for the LLM.
        # It defines the tool's purpose and its limitations,
        # distinguishing it from the 'fast' search tool.
        "description": (
            "Performs an in-depth Google search when a quick search is not enough. "
            "Use this for complex queries requiring detailed information or "
            "when you specifically need to find direct links to images."
        ),

        # Defines the function's arguments.
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    # A concise description of the 'query' parameter.
                    "description": "The search term, question, or image description to look up on Google."
                },
                "lang": {
                    "type": "string",
                    # Provides examples to guide the model.
                    "description": "The two-letter language code for the search (e.g., 'en', 'ru', 'de')."
                },
                "user_id": {
                    "type": "string",
                    # Clarifies the source of this parameter.
                    "description": "The unique telegram identifier for the user, passed from the system context. Example: '[12345678] [0]'"
                }
            },
            # All parameters are mandatory.
            "required": ["query", "lang", "user_id"]
        }
    }
}

download_text_from_url_schema = {
    "type": "function",
    "function": {
        # The exact name of the Python function.
        "name": "download_text_from_url",

        # This description tells the LLM what the tool does and when to use it.
        # It specifically mentions handling web pages and YouTube subtitles.
        "description": (
            "Downloads the text content from a URL. "
            "It can extract text from standard web pages and also "
            "retrieve subtitles from YouTube videos. Use this to analyze "
            "or summarize content from a specific link provided by the user."
        ),

        # Defines the function's arguments.
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    # A clear description of the 'url' parameter.
                    "description": "The full URL of the web page or YouTube video to extract text from."
                }
            },
            # The 'url' parameter is mandatory.
            "required": ["url"]
        }
    }
}

TOOLS_SCHEMA = [
    calculator_schema,
    search_google_fast_schema,
    search_google_deep_schema,
    download_text_from_url_schema
]

# The map connects the tool name to the actual Python function.
AVAILABLE_TOOLS = {
    "calc": calc,
    "search_google_fast": search_google_fast,
    "search_google_deep": search_google_deep,
    "download_text_from_url": download_text_from_url
}
##[tool use]######


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
    max_tools_use: int = 20
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
        tools (Optional[List[Dict]]): A list of tool schemas for the model to use.
        available_tools (Optional[Dict]): A mapping of tool names to their callable functions.
        max_tools_use (int): The maximum number of tools to use in a single request.

    Returns:
        str: The AI's response as a string, or an empty string on failure.
    """

    # tools: Optional[List[Dict]] = TOOLS_SCHEMA
    # available_tools: Optional[Dict] = AVAILABLE_TOOLS

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
    if ('qwen' in model and 'thinking' not in model) or 'llama' in model:
        reasoning_effort = None

    RETRY_MAX = 3
    for _ in range(RETRY_MAX):
        api_key = get_next_key()
        if not api_key:
            return ''

        try:
            client = Cerebras(api_key=api_key)

            # If tools are provided, enter the tool-use loop.
            if tools and available_tools:
                max_calls = max_tools_use
                for call_count in range(max_calls):
                    response = client.chat.completions.create(
                        model=model,
                        messages=mem_,
                        tools=tools,
                        tool_choice="auto",
                        temperature=temperature,
                        timeout=timeout,
                    )
                    message = response.choices[0].message

                    # If no tool call, we have the final answer.
                    if not message.tool_calls:
                        return message.content or ""

                    # Process the tool call
                    mem_.append(message.model_dump())
                    tool_call = message.tool_calls[0]
                    function_name = tool_call.function.name

                    if function_name in available_tools:
                        function_to_call = available_tools[function_name]
                        try:
                            args = json.loads(tool_call.function.arguments)
                            tool_output = function_to_call(**args)
                        except Exception as e:
                            tool_output = f"Error executing tool: {e}"
                            my_log.log_cerebras(f'Error executing tool: {e}')
                    else:
                        tool_output = f"Error: Tool '{function_name}' not found."

                    mem_.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_output,
                    })

                # If loop finishes due to max_calls, force a final answer.
                mem_.append({"role": "user", "content": "Tool call limit reached. Summarize your findings."})
                final_response = client.chat.completions.create(model=model, messages=mem_)
                return final_response.choices[0].message.content or ""

            # If no tools, proceed with the original logic.
            else:
                sdk_params = {
                    'messages': mem_, 'model': model, 'max_completion_tokens': max_tokens,
                    'temperature': temperature, 'timeout': timeout,
                }
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

                chat_completion = client.chat.completions.create(**sdk_params)
                result = chat_completion.choices[0].message.content or ''

                if result:
                    return result.strip()

        except Exception as error:
            my_log.log_cerebras(f'ai:1: {error} [user_id: {user_id}]')

    return '' 


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


if __name__ == '__main__':
    pass
    my_db.init(backup=False)
    my_skills.init()
    my_skills.my_groq.load_users_keys()

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

    my_db.close()
