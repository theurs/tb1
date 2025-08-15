# https://studio.nebius.ai/billing
# https://studio.nebius.ai/settings/api-keys


import base64
import json
import time
import threading
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple

from openai import OpenAI
from sqlitedict import SqliteDict

import cfg
import my_cerebras_tools
import my_db
import my_log
import my_skills_storage
import utils


BASE_URL = "https://api.studio.nebius.ai/v1/"

SYSTEM_ = []

# сколько запросов хранить
MAX_MEM_LINES = 40
MAX_HIST_CHARS = 60000
MAX_TOOL_OUTPUT_LEN = 60000


# блокировка чатов что бы не испортить историю
# {id:lock}
LOCKS: Dict[str, threading.Lock] = {}
_CHAT_LOCKS_LOCK = threading.Lock()


# не принимать запросы больше чем, это ограничение для телеграм бота, в этом модуле оно не используется
MAX_REQUEST = 40000
_KEYS_LOCK = threading.Lock()


DEFAULT_TIMEOUT = 120
DEFAULT_MODEL = 'deepseek-ai/DeepSeek-V3-0324'  # 'deepseek-ai/DeepSeek-R1-0528' # 'deepseek-ai/DeepSeek-R1'
DEFAULT_MODEL_FALLBACK = 'Qwen/Qwen3-30B-A3B'   # 'deepseek-ai/DeepSeek-V3'

DEFAULT_V3_MODEL = 'deepseek-ai/DeepSeek-V3-0324'


CURRENT_KEY_SET: List[str] = []


# каждый юзер дает свои ключи и они используются совместно со всеми
# каждый ключ дает всего 50/150 запросов в сутки так что чем больше тем лучше
# {full_chat_id as str: key}
# {'[9123456789] [0]': 'key', ...}
ALL_KEYS = []
USER_KEYS = SqliteDict('db/nebius_user_keys.db', autocommit=True)
USER_KEYS_LOCK = threading.Lock()


def clear_mem(mem: list, user_id: str) -> list:
    """
    Clears the memory (chat history) for a given user, ensuring it does not exceed the maximum allowed size.

    Args:
        mem (list): The chat history list.
        user_id (str): The user's ID.

    Returns:
        list: The trimmed chat history.
    """
    while True:
        sizeofmem = count_tokens(mem)
        if sizeofmem <= MAX_HIST_CHARS:
            break
        try:
            mem = mem[2:]
        except IndexError:
            mem = []
            break

    return mem[-MAX_MEM_LINES * 2 :]


def count_tokens(mem: list) -> int:
    """
    Counts the total number of tokens in the chat history.

    Args:
        mem (list): The chat history list.

    Returns:
        int: The total number of tokens.
    """
    return sum([len(m['content']) for m in mem])


def ai(
    prompt: str = '',
    mem: Optional[List[Dict[str, Any]]] = None,
    user_id: str = '',
    system: str = '',
    model: str = DEFAULT_MODEL,
    temperature: float = 1,
    max_tokens: int = 4000,
    timeout: float = DEFAULT_TIMEOUT,
    key_: Optional[str] = None,
    response_format: str = 'text',
    tools: Optional[List[Dict[str, Any]]] = None,
    available_tools: Optional[Dict[str, Callable[..., Any]]] = None,
    max_tools_use: int = 10
) -> str:
    """
    Sends a request to the Nebius AI API, assembling the message list internally.
    This function is stateless regarding history persistence but prepares the context for the API call.
    It supports tool-calling and JSON mode.
    """
    if not model:
        model = DEFAULT_MODEL

    if not prompt and not mem:
        return ''

    # Create a local, mutable copy of the conversation history
    mem_ = mem[:] if mem else []

    # Prepare system prompts and add them to the local history copy
    now = utils.get_full_time()
    system_prompts = (
        f'Current date and time: {now}\n',
        f'Use this telegram chat id (user id) for API function calls: {user_id}',
        *SYSTEM_
    )
    if system:
        mem_.insert(0, {"role": "system", "content": system})
    for s in reversed(system_prompts):
        mem_.insert(0, {"role": "system", "content": s})

    # Add the current user prompt
    if prompt:
        mem_.append({"role": "user", "content": prompt})

    start_time = time.monotonic()
    effective_timeout = timeout * 2 if tools and available_tools else timeout
    RETRY_MAX = 1 if key_ else 3

    for attempt in range(RETRY_MAX):
        if time.monotonic() - start_time > effective_timeout:
            my_log.log_nebius(f'ai: Global timeout of {effective_timeout}s exceeded.')
            return ''

        api_key = key_ or get_next_key()
        if not api_key:
            my_log.log_nebius('ai: No API keys available.')
            return ''

        try:
            client = OpenAI(api_key=api_key, base_url=BASE_URL)

            sdk_params: Dict[str, Any] = {
                'model': model,
                'temperature': temperature / 2,
                'timeout': timeout,
                'messages': mem_
            }

            if response_format == 'json_object':
                sdk_params['response_format'] = {'type': 'json_object'}

            # --- Tool-use path ---
            if tools and available_tools:

                # сохраняем маркер для проверки валидности chat_id в модуле my_skills*
                if user_id:
                    my_skills_storage.STORAGE_ALLOWED_IDS[user_id] = user_id

                sdk_params['tools'] = tools
                sdk_params['tool_choice'] = "auto"

                for _ in range(max_tools_use):
                    if time.monotonic() - start_time > effective_timeout:
                        raise TimeoutError("Global timeout exceeded in tool-use loop.")

                    response = client.chat.completions.create(**sdk_params)
                    message = response.choices[0].message

                    if not message.tool_calls:
                        return message.content or ""

                    # Append assistant's response and tool calls to our local history
                    mem_.append(message.model_dump(exclude_unset=True))

                    for tool_call in message.tool_calls:
                        function_name = tool_call.function.name
                        if function_name in available_tools:
                            function_to_call = available_tools[function_name]
                            try:
                                args = json.loads(tool_call.function.arguments)
                                tool_output = str(function_to_call(**args))
                                if len(tool_output) > MAX_TOOL_OUTPUT_LEN:
                                    tool_output = tool_output[:MAX_TOOL_OUTPUT_LEN]
                            except Exception as e:
                                tool_output = f"Error executing tool '{function_name}': {e}"
                        else:
                            tool_output = f"Error: Tool '{function_name}' not found."

                        mem_.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": function_name,
                            "content": tool_output,
                        })
                    # Update messages for the next iteration in the loop
                    sdk_params['messages'] = mem_

                # After max tool uses, ask for a final answer
                mem_.append({"role": "user", "content": "Tool call limit reached. Please provide a final answer."})
                final_params = sdk_params.copy()
                final_params.pop('tools', None)
                final_params.pop('tool_choice', None)
                final_response = client.chat.completions.create(**final_params)
                return final_response.choices[0].message.content or ""

            # --- Non-tool path ---
            else:
                sdk_params['max_tokens'] = max_tokens
                response = client.chat.completions.create(**sdk_params)
                result = response.choices[0].message.content or ''
                return result.strip()

        except Exception as error:
            my_log.log_nebius(f'ai: attempt {attempt + 1}/{RETRY_MAX} failed: {error}')
            if 'Bad credentials' in str(error):
                if not key_: remove_key(api_key)
                continue
            if 'context_length_exceeded' in str(error): return ''
            if 'Request timed out' in str(error): continue
            if attempt < RETRY_MAX - 1: time.sleep(1)

    return ''


def chat(
    query: str,
    chat_id: str = '',
    temperature: float = 1,
    system: str = '',
    model: str = '',
    max_tokens: int = 4000,
    tools: Optional[List[Dict[str, Any]]] = None,
    available_tools: Optional[Dict[str, Callable[..., Any]]] = None
) -> str:
    """
    Manages a chat session. It handles loading history, calling the `ai`
    function to get a response, and then updating/saving the history.
    """
    with _CHAT_LOCKS_LOCK:
        if chat_id not in LOCKS:
            LOCKS[chat_id] = threading.Lock()
        lock = LOCKS[chat_id]

    with lock:
        mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_openrouter')) or []

        text = ai(
            prompt=query,
            mem=mem,
            user_id=chat_id,
            system=system,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            available_tools=available_tools
        )

        if text:
            # Update and save history on successful response
            if chat_id:
                my_db.add_msg(chat_id, model or DEFAULT_MODEL)
            # The full interaction including tool calls is NOT in `text`.
            # We only save the initial prompt and the final text response.
            update_mem(query, text, chat_id)

        return text


def update_mem(query: str, resp: str, chat_id: str):
    """
    Updates the memory with the user query and assistant response.

    Args:
        query (str): The user query.
        resp (str): The assistant response.
        chat_id (str): The chat ID.

    Returns:
        None
    """
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
        my_log.log_nebius(f'my_nebius:update_mem: {error}\n\n{error_traceback}\n\n{query}\n\n{resp}\n\n{mem}')

    my_db.set_user_property(chat_id, 'dialog_openrouter', my_db.obj_to_blob(mem__))


def chat_cli(model: str = ''):
    """
    Command-line interface for interacting with the chat function.
    """

    def get_funcs():
        import my_cerebras
        return my_cerebras.funcs

    # Define a list of functions available for the CLI chat
    funcs = get_funcs()
    # Assume my_nebius_tools.get_tools exists and works like my_cerebras_tools.get_tools
    TOOLS_SCHEMA, AVAILABLE_TOOLS = my_cerebras_tools.get_tools(*funcs)

    reset('test')
    print("CLI chat ready. Model:", model or DEFAULT_MODEL)
    print("Available tools:", list(AVAILABLE_TOOLS.keys()))

    while True:
        q = input('>')
        if q.lower() == 'mem':
            print(get_mem_as_string('test'))
            continue
        if q.lower() in ('exit', 'quit'):
            break

        r = chat(
            q,
            'test',
            model=model,
            system='Отвечай всегда по-русски',
            tools=TOOLS_SCHEMA,
            available_tools=AVAILABLE_TOOLS
        )
        print(f"\nBOT: {r}\n")


def force(chat_id: str, text: str) -> None:
    """
    Updates the last bot answer in the chat history with the given text.

    Args:
        chat_id (str): The ID of the chat to update.
        text (str): The new text to replace the last bot answer with.

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
            mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_openrouter')) or [] # Retrieve chat memory from database
            if mem and len(mem) > 1: # Check if memory exists and has at least two messages (user and bot message)
                mem[-1]['content'] = text # Update the content of the last message (assuming it's the bot's last response)
                my_db.set_user_property(chat_id, 'dialog_openrouter', my_db.obj_to_blob(mem)) # Update the chat memory in the database
    except Exception as error: # Catch any exceptions during the process
        error_traceback = traceback.format_exc() # Get full traceback of the error
        my_log.log_nebius(f'Failed to force message in chat {chat_id}: {error}\n\n{error_traceback}') # Log error details to nebius


def undo(chat_id: str) -> None:
    """
    Removes the last two messages (user and bot) from the chat history for a given chat ID.

    Args:
        chat_id (str): The ID of the chat to undo the last messages from.

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
            mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_openrouter')) or [] # Retrieve chat memory from database
            mem = mem[:-2] # Remove the last two messages from the memory list
            my_db.set_user_property(chat_id, 'dialog_openrouter', my_db.obj_to_blob(mem)) # Update the chat memory in the database
    except Exception as error: # Catch any exceptions during the process
        error_traceback = traceback.format_exc() # Get full traceback of the error
        my_log.log_nebius(f'Failed to undo chat {chat_id}: {error}\n\n{error_traceback}') # Log error details to nebius


def reset(chat_id: str) -> None:
    """
    Resets the chat history for the specified chat ID by clearing the memory.

    Args:
        chat_id (str): The ID of the chat to reset.

    Returns:
        None
    """
    mem = [] # Initialize an empty list to represent empty memory
    my_db.set_user_property(chat_id, 'dialog_openrouter', my_db.obj_to_blob(mem)) # Update the chat memory in the database with empty memory, effectively resetting the chat


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
        my_log.log_nebius(f'get_mem_as_string: {error}\n\n{error_traceback}')
        return ''


def img2txt(
    image_data: bytes,
    prompt: str = 'Describe picture',
    model = DEFAULT_MODEL,
    temperature: float = 1,
    max_tokens: int = 4000,
    timeout: int = 120,
    chat_id: str = '',
    ) -> str:
    """
    Describes an image using the specified model and parameters.

    Args:
        image_data: The image data as bytes.
        prompt: The prompt to guide the description. Defaults to 'Describe picture'.
        model: The model to use for generating the description. Defaults to 'mistralai/pixtral-12b:free'.
        temperature: The temperature parameter for controlling the randomness of the output. Defaults to 1.
        max_tokens: The maximum number of tokens to generate. Defaults to 2000.
        timeout: The timeout for the request in seconds. Defaults to 120.

    Returns:
        A string containing the description of the image, or an empty string if an error occurs.
    """
    temperature = temperature/2
    if not model:
        model = DEFAULT_MODEL
    if not prompt:
        prompt = 'Describe picture'

    if isinstance(image_data, str):
        with open(image_data, 'rb') as f:
            image_data = f.read()

    img_b64_str = base64.b64encode(image_data).decode('utf-8')
    img_type = 'image/png'

    mem = [
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

    result = ''

    for _ in range(3):
        try:
            key = get_next_key()
            client = OpenAI(
                api_key = key,
                base_url = BASE_URL,
                )
            response = client.chat.completions.create(
                messages = mem,
                model = model,
                max_tokens = max_tokens,
                temperature = temperature,
                timeout = timeout,
                )
        except Exception as error_other:
            if 'Bad credentials' in str(error_other):
                remove_key(key)
                continue
            my_log.log_nebius(f'ai: {error_other}')
            return ''

        try:
            result = response.choices[0].message.content
            break
        except Exception as error:
            my_log.log_nebius(f'Failed to parse response: {error}\n\n{str(response)}')
            result = ''
            time.sleep(2)

    if chat_id:
        my_db.add_msg(chat_id, model)

    return result


def test_key(key: str) -> bool:
    '''
    Tests a given key by making a simple request to the Nebius AI API.
    '''
    r = ai('1+1=', key_=key.strip())
    return bool(r)


def txt2img(
    prompt: str,
    negative_prompt: str = '',
    model: str = "black-forest-labs/flux-dev", # black-forest-labs/flux-schnell, stability-ai/sdxl
    width: int = 1024,
    height: int = 1024,
    output_format: str = 'webp',
    seed: int = -1,
    num_interence_steps: int = 28,
    timeout: int = 60
    ) -> bytes:
    '''
    Generate image from text

    Args:
        prompt (str): The text prompt to generate an image from. Up to 2000 symbols.
        model (str, optional): The model to use for generating the image. Defaults to "black-forest-labs/flux-dev"
                               also available black-forest-labs/flux-schnell, stability-ai/sdxl
        width (int, optional): The width of the generated image. Defaults to 1024.
        height (int, optional): The height of the generated image. Defaults to 1024.
        output_format (str, optional): The format of the generated image. Defaults to 'webp'.
        negative_prompt (str, optional): The negative prompt to generate an image from. Defaults to ''.
        seed (int, optional): The seed to generate an image from. Defaults to -1.
        num_interence_steps (int, optional): The number of inference steps to generate an image. Defaults to 28.
        timeout (int, optional): The timeout for the request in seconds. Defaults to 60.

    Returns:
        bytes: The generated image data in bytes format.
    '''
    try:
        prompt = prompt.strip()[:1999]
        if not model:
            model = "black-forest-labs/flux-dev"

        if model == 'black-forest-labs/flux-schnell' and num_interence_steps > 16:
            num_interence_steps = 16

        key = get_next_key()
        client = OpenAI(
            base_url=BASE_URL,
            api_key=key,
        )

        response = client.images.generate(
            model=model,
            response_format="b64_json",
            extra_body={
                "response_extension": output_format,
                "width": width,
                "height": height,
                "num_inference_steps": num_interence_steps,
                "negative_prompt": negative_prompt,
                "seed": seed,
                "num_images": 1,
            },
            prompt=prompt,
            timeout=timeout,
        )

        image_data = response.data[0]
        b64_string = image_data.b64_json
        image_bytes = base64.b64decode(b64_string)

        return image_bytes
    except Exception as unknown_error:
        traceback_error = traceback.format_exc()
        my_log.log_nebius(f'Error: {unknown_error}\n{traceback_error}')
        return None


def test_txt2img():
    data = txt2img(
        "A whimsical image of Pippi Longstocking joyfully sailing in a small wooden rowboat on a serene lake, bright sunny "
        "day, lush green trees surrounding the lake, realism pro movie style.",
        )
    if data:
        with open(f'c:/users/user/downloads/1.webp', 'wb') as f:
            f.write(data)
            print('Image saved')
    else:
        print('Error')


def get_next_key() -> str:
    """
    Retrieves the next API key in a round-robin fashion.

    Returns:
        str: The next available API key.

    Raises:
        Exception: If no API keys are available.
    """
    global CURRENT_KEY_SET
    with _KEYS_LOCK: # Use the single unified lock
        if not CURRENT_KEY_SET:
            if ALL_KEYS:
                CURRENT_KEY_SET = ALL_KEYS[:]
        if CURRENT_KEY_SET:
            return CURRENT_KEY_SET.pop(0)
        else:
            # It's better to return an empty string or None than raise an unhandled exception
            return ''


def remove_key(key: str) -> None:
    '''
    Removes a given key from the ALL_KEYS list and from the USER_KEYS dictionary.
    This operation is now thread-safe.
    '''
    if not key:
        return

    try:
        with _KEYS_LOCK: # Protect all shared key structures
            # Remove from the main list if it exists
            if key in ALL_KEYS:
                try:
                    ALL_KEYS.remove(key)
                except ValueError:
                    # Key was removed by another thread between the `in` check and `remove`
                    pass

            # Also remove from the current rotating set to take effect immediately
            if key in CURRENT_KEY_SET:
                try:
                    CURRENT_KEY_SET.remove(key)
                except ValueError:
                    pass

            # Find all users associated with this key
            keys_to_delete = [user for user, user_key in USER_KEYS.items() if user_key == key]

            # Delete them from the database
            if keys_to_delete:
                for user_key_to_delete in keys_to_delete:
                    del USER_KEYS[user_key_to_delete]
                my_log.log_keys(f'nebius: Invalid key {key} removed from users {keys_to_delete}')
            else:
                # This can happen if the key was from cfg, not a user
                my_log.log_keys(f'nebius: Invalid key {key} removed (was not in USER_KEYS)')

    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_nebius(f'Failed to remove key {key}: {error}\n\n{error_traceback}')


def load_users_keys() -> None:
    """
    Load users' keys into memory and update the list of all keys available.
    This operation is thread-safe.
    """


    import my_skills_general
    global SYSTEM_
    SYSTEM_ = my_skills_general.SYSTEM_


    with _KEYS_LOCK: # Use the single unified lock
        global ALL_KEYS, USER_KEYS
        # Start with keys from config file
        cfg_keys = cfg.NEBIUS_AI_KEYS if hasattr(cfg, 'NEBIUS_AI_KEYS') and cfg.NEBIUS_AI_KEYS else []

        # Use a set to efficiently combine keys and remove duplicates
        combined_keys = set(cfg_keys)

        # Add keys from the user database
        for user in USER_KEYS:
            combined_keys.add(USER_KEYS[user])

        ALL_KEYS = list(combined_keys)


def check_all_keys() -> Tuple[List[str], List[str]]:
    """
    Tests all loaded Nebius keys by making a small API call with each.
    Prints a summary report to the console and returns lists of valid and invalid keys.

    Returns:
        A tuple containing two lists: (valid_keys, invalid_keys)
    """
    # Ensure we have the latest set of keys
    load_users_keys()

    if not ALL_KEYS:
        print("No Nebius keys found to check.")
        return [], []

    valid_keys: List[str] = []
    invalid_keys: List[str] = []

    total = len(ALL_KEYS)
    print(f"--- Starting to check {total} Nebius keys ---")

    for i, key in enumerate(ALL_KEYS, 1):
        # Provide real-time feedback but hide most of the key
        print(f"[{i}/{total}] Testing key {key[:5]}...{key[-4:]}... ", end="", flush=True)

        # test_key already exists and is perfect for this
        if test_key(key):
            print("VALID")
            valid_keys.append(key)
        else:
            print("INVALID")
            invalid_keys.append(key)

    # Print a clean summary at the end
    print("\n--- Nebius Key Check Summary ---")
    print(f"[+] Valid keys:   {len(valid_keys)}")
    print(f"[-] Invalid keys: {len(invalid_keys)}")
    if invalid_keys:
        print("    List of invalid keys:")
        for key in invalid_keys:
            print(f"    - {key[:5]}...{key[-4:]}")

    print("--------------------------------")

    return valid_keys, invalid_keys


if __name__ == "__main__":
    pass
    my_db.init(backup=False)
    load_users_keys()

    # check_all_keys()

    reset('test')
    chat_cli(model = DEFAULT_V3_MODEL)

    # print(img2txt('C:/Users/user/Downloads/samples for ai/мат задачи.jpg', 'реши задачи, в ответе используй юникод символы для математики вместо latex выражений', model = 'gpt-4o', temperature=0))
    # print(voice2txt('C:/Users/user/Downloads/1.ogg'))

    # test_txt2img()

    my_db.close()
