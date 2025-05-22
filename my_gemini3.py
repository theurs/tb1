# https://github.com/GoogleCloudPlatform/generative-ai/blob/main/gemini/getting-started/intro_gemini_chat.ipynb


import cachetools.func
import io
import PIL
import time
import threading
import traceback

from typing import List, Optional, Any, Dict, Union

from google import genai
from google.genai.types import (
    GenerateContentConfig,
    GoogleSearch,
    ToolCodeExecution,
    UserContent,
    ModelContent,
    Content,
    Part,
    UserContent,
    Tool,
    SafetySetting
)

import cfg
import my_db
import my_gemini
import my_log
import utils


MODEL_ID = "gemini-2.0-flash"


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


def get_config(
    system_instruction: str = "",
    max_output_tokens: int = 8000,
    temperature: float = 1,
    tools: list = [],
    ):
    google_search_tool = Tool(google_search=GoogleSearch())
    toolcodeexecution = Tool(code_execution=ToolCodeExecution())
    gen_config = GenerateContentConfig(
        temperature=temperature,
        # top_p=0.95,
        # top_k=20,
        # candidate_count=1,
        # seed=5,
        max_output_tokens=max_output_tokens,
        system_instruction=system_instruction or None,
        safety_settings=SAFETY_SETTINGS,
        # tools = tools,
        tools = [google_search_tool, toolcodeexecution],
        # stop_sequences=["STOP!"],
        # presence_penalty=0.0,
        # frequency_penalty=0.0,
        )

    return gen_config


@cachetools.func.ttl_cache(maxsize=10, ttl = 10 * 60)
def img2txt(
    data_: bytes,
    prompt: str = "Что на картинке?",
    temp: float = 1,
    model: str = cfg.gemini25_flash_model,
    json_output: bool = False,
    chat_id: str = '',
    use_skills: str = False,
    system: str = '',
    timeout: int = my_gemini.TIMEOUT,
    ) -> str:
    '''
    Convert image to text.
    '''
    for _ in range(2):
        try:
            # надо уменьшить или загружать через облако, или просто не делать слишком большое
            if len(data_) > 20000000:
                data_ = utils.resize_image(data_, 20000000)

            data = io.BytesIO(data_)
            img = PIL.Image.open(data)
            q = [prompt, img]

            res = chat(
                q,
                chat_id=chat_id,
                temperature=temp,
                model = model,
                system=system,
                timeout=timeout
            )

            return res
        except Exception as error:
            if 'cannot identify image file' in str(error):
                return ''
            traceback_error = traceback.format_exc()
            my_log.log_gemini(f'my_gemini3:img2txt1: {error}\n\n{traceback_error}')
        time.sleep(2)
    my_log.log_gemini('my_gemini3:img2txt2: 4 tries done and no result')
    return ''


# надо будет чистить память от картинок, удалять все кроме последней
# надо будет учитывать таймаут хотя бы в повторных запросах в цикле
def chat(
    query: str,
    chat_id: str = '',
    temperature: float = 1,
    model: str = '',
    system: str = '',
    max_tokens: int = 8000,
    max_chat_lines: int = my_gemini.MAX_CHAT_LINES,
    max_chat_mem_chars: int = my_gemini.MAX_CHAT_MEM_CHARS,
    timeout: int = my_gemini.TIMEOUT,
    ) -> str:
    """Interacts with a generative AI model (presumably Gemini) to process a user query.

    This function sends a query to a generative AI model, manages the conversation history,
    handles API key rotation, and provides options for using skills (external tools),
    controlling output format, and managing memory.

    Args:
        query: The user's input query string.
        chat_id: An optional string identifier for the chat session.  Used for retrieving and updating conversation history.
        temperature:  A float controlling the randomness of the response.  Should be between 0 and 2.
        model: The name of the generative model to use. If empty, defaults to `cfg.gemini25_flash_model`.
        system: An optional string representing the system prompt or instructions for the model.
        max_tokens: The maximum number of tokens allowed in the response.
        use_skills: A boolean flag indicating whether to enable the use of external tools (skills).
        max_chat_lines: The maximum number of conversation turns to store in history.
        max_chat_mem_chars: The maximum number of characters to store in the conversation history.
        timeout: The request timeout in seconds.

    Returns:
        A string containing the model's response, or an empty string if an error occurs or the response is empty.

    Raises:
        None: The function catches and logs exceptions internally, returning an empty string on failure.
    """
    try:

        if isinstance(query, str):
            query = query[:my_gemini.MAX_SUM_REQUEST]
        if isinstance(query, list):
            query[0] = query[0][:my_gemini.MAX_SUM_REQUEST]

        if temperature < 0:
            temperature = 0
        if temperature > 2:
            temperature = 2

        if max_tokens < 10:
            max_tokens = 10
        if max_tokens > 8000:
            max_tokens = 8000

        if 'gemma-3' in model:
            if temperature:
                temperature = temperature/2

        model = model or cfg.gemini25_flash_model

        if chat_id:
            mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_gemini3')) or []
        else:
            mem = []

        client = genai.Client(api_key=my_gemini.get_next_key())

        chat = client.chats.create(
            model=model,
            config=get_config(
                system_instruction=system,
            ),
            history=mem,
        )

        resp = ''

        for _ in range(3):
            response = chat.send_message(query,)
            resp = response.text or ''
            if not resp:
                if "finish_reason=<FinishReason.STOP: 'STOP'>" in str(response): # модель ответила молчанием (по просьбе юзера)
                    resp = '...'
                    break
                time.sleep(2)
            else:
                break

        if resp:
            history = chat.get_history()
            history = history[-max_chat_lines*2:]
            my_db.set_user_property(chat_id, 'dialog_gemini3', my_db.obj_to_blob(history))
            if chat_id:
                my_db.add_msg(chat_id, model)

        return resp.strip()

    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_gemini(f'my_gemini3:chat:unknown_error {error}\n\n{traceback_error}\n{model}')
        return ''


def count_chars(mem) -> int:
    '''считает количество символов в чате'''
    total = 0
    for x in mem:
        for i in x.parts:
            if i.text:
                total += len(i.text)
    return total


def update_mem(query: str, resp: str, mem, model: str = ''):
    """
    Update the memory with the given query and response.

    Parameters:
        query (str): The input query.
        resp (str): The response to the query.
        mem: The memory object to update, if str than mem is a chat_id
        model (str): The model name.

    Returns:
        list: The updated memory object.
    """
    chat_id = ''
    if isinstance(mem, str): # if mem - chat_id
        chat_id = mem
        mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_gemini3')) or []

    u = UserContent(query)
    c = ModelContent(resp)
    mem.append(u)
    mem.append(c)

    mem = mem[-my_gemini.MAX_CHAT_LINES*2:]
    while count_chars(mem) > my_gemini.MAX_CHAT_MEM_CHARS:
        mem = mem[2:]

    if chat_id:
        my_db.set_user_property(chat_id, 'dialog_gemini3', my_db.obj_to_blob(mem))
    return mem


def force(chat_id: str, text: str, model: str = ''):
    '''update last bot answer with given text'''
    try:
        if chat_id in my_gemini.LOCKS:
            lock = my_gemini.LOCKS[chat_id]
        else:
            lock = threading.Lock()
            my_gemini.LOCKS[chat_id] = lock
        with lock:
            mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_gemini3')) or []
            # remove last bot answer and append new
            if len(mem) > 1:
                m = ModelContent(text)
                mem[-1] = m
                my_db.set_user_property(chat_id, 'dialog_gemini3', my_db.obj_to_blob(mem))
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_gemini(f'my_gemini3:force: Failed to force text in chat {chat_id}: {error}\n\n{error_traceback}\n\n{text}')


def undo(chat_id: str, model: str = ''):
    """
    Undo the last two lines of chat history for a given chat ID.

    Args:
        chat_id (str): The ID of the chat.
        model (str): The model name.

    Raises:
        Exception: If there is an error while undoing the chat history.

    Returns:
        None
    """
    try:
        if chat_id in my_gemini.LOCKS:
            lock = my_gemini.LOCKS[chat_id]
        else:
            lock = threading.Lock()
            my_gemini.LOCKS[chat_id] = lock
        with lock:
            mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_gemini3')) or []
            # remove 2 last lines from mem
            mem = mem[:-2]
            my_db.set_user_property(chat_id, 'dialog_gemini3', my_db.obj_to_blob(mem))
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_gemini(f'my_gemini3:undo:Failed to undo chat {chat_id}: {error}\n\n{error_traceback}')


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
    my_db.set_user_property(chat_id, 'dialog_gemini3', my_db.obj_to_blob(mem))


def get_mem_for_llama(chat_id: str, lines_amount: int = 3, model: str = '') -> List[Dict[str, str]]:
    """
    Retrieves the recent chat history for a given chat_id, adapting to the new memory structure.
    This function processes the memory to be suitable for Llama models, converting roles
    and stripping specific internal prefixes from the content.

    Parameters:
        chat_id (str): The unique identifier for the chat session.
        lines_amount (int, optional): The number of conversational turns (a user message
                                      and its corresponding model response) to retrieve.
                                      Defaults to 3. The function will fetch `lines_amount * 2`
                                      raw memory entries to cover these turns.
        model (str, optional): The name of the model. This parameter is currently unused
                               but kept for signature compatibility with other functions.

    Returns:
        list: The recent chat history as a list of dictionaries, where each dictionary
              has 'role' (either 'user' or 'assistant') and 'content' (the message text).
              Returns an empty list if no memory is found or an error occurs during processing.
    """
    # Initialize an empty list to store the processed memory entries.
    processed_memory: List[Dict[str, str]] = []

    # Calculate the total number of raw memory entries needed.
    # Each 'line' for Llama typically represents a full turn (user input + model response).
    # Since raw memory stores user and model messages as separate entries, we multiply by 2.
    raw_entries_to_fetch: int = lines_amount * 2

    # Retrieve the raw chat history from the database.
    # The new memory is stored under 'dialog_gemini3'.
    # If `get_user_property` returns None, or `blob_to_obj` results in None, default to an empty list.
    raw_memory: List[Union[Content, UserContent]] = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_gemini3')) or []

    # Slice the raw memory to get only the most recent entries,
    # adhering to the calculated `raw_entries_to_fetch` limit.
    recent_raw_memory = raw_memory[-raw_entries_to_fetch:]

    # Iterate through each entry in the recent raw memory.
    for entry in recent_raw_memory:
        # Determine the appropriate role for the Llama model's input.
        # 'user' role remains 'user'. 'model' role is mapped to 'assistant'.
        output_role: str
        if entry.role == 'user':
            output_role = 'user'
        elif entry.role == 'model':
            output_role = 'assistant'
        else:
            # Log a warning for unexpected roles; default to 'user' or raise an error
            # depending on desired robustness. This case should ideally not occur.
            my_log.log_gemini(f"my_gemini3:get_mem_for_llama: Unexpected role encountered: {entry.role}. Defaulting to 'user'.")
            output_role = 'user' # Fallback for unknown roles

        # Extract the text content from the entry's parts.
        # The new memory structure stores text within a list of `Part` objects.
        extracted_text: str = ''
        if entry.parts:
            # If there's only one part, directly use its text.
            if len(entry.parts) == 1:
                # Ensure the text attribute itself is not None.
                extracted_text = entry.parts[0].text if entry.parts[0].text is not None else ''
            else:
                # If there are multiple parts, concatenate their text contents.
                # Filter out any parts where text might be None before joining.
                parts_texts = [p.text for p in entry.parts if p.text is not None]
                # Join multiple text parts with double newlines for better readability in context.
                extracted_text = '\n\n'.join(parts_texts)

        # Handle and strip special internal prefixes like "[Info to help you answer: ...]".
        # These prefixes are typically internal notes for the model and should not be
        # passed as part of the conversation history to external models like Llama.
        if extracted_text.startswith('[Info to help you answer:'):
            # Find the closing bracket to determine the end of the info prefix.
            end_bracket_index = extracted_text.find(']')
            if end_bracket_index != -1:
                # Strip the prefix and any leading/trailing whitespace.
                extracted_text = extracted_text[end_bracket_index + 1:].strip()
            # If ']' is not found, the prefix is malformed; we proceed with the original text.

        # Add the processed entry to the result list only if its content is not empty
        # after all processing and stripping.
        if extracted_text:
            processed_memory.append({'role': output_role, 'content': extracted_text})

    try:
        # Final filtering to ensure all content entries are non-empty.
        # This acts as a safeguard, although the `if extracted_text:` check above
        # should largely handle this. This line mimics the original function's robustness.
        final_filtered_memory = [x for x in processed_memory if x['content']]
    except Exception as error:
        # Log any errors that occur during the final filtering step.
        my_log.log_gemini(f'my_gemini3:get_mem_for_llama: Error during final content filtering: {error}')
        return [] # Return an empty list in case of a critical error.

    return final_filtered_memory


def get_mem_as_string(chat_id: str, md: bool = False, model: str = '') -> str:
    """
    Returns the chat history as a string for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to get the history for.
        md (bool, optional): Whether to format the output as Markdown. Defaults to False.
        model (str, optional): The name of the model. (Note: this parameter is not used in the
                               provided logic but kept for signature compatibility).

    Returns:
        str: The chat history as a string.
    """
    mem: List[UserContent | Content] = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_gemini3')) or []

    result_string = ''
    for entry in mem:
        # Determine the role and format it for display.
        role_display = ''
        if entry.role == 'user':
            role_display = '𝐔𝐒𝐄𝐑'
        elif entry.role == 'model':
            role_display = '𝐁𝐎𝐓'
        # Add a fallback for unexpected roles, though not strictly necessary if roles are fixed.
        else:
            role_display = entry.role.upper() # Fallback for unknown roles

        # Extract text from the parts.
        # The new format separates text from role, so old split logic is removed.
        extracted_text = ''
        if entry.parts:
            # If there's only one part, directly use its text.
            if len(entry.parts) == 1:
                extracted_text = entry.parts[0].text if entry.parts[0].text is not None else ''
            # If there are multiple parts, concatenate their text with double newlines.
            else:
                # Filter out any parts where text might be None before joining.
                parts_texts = [p.text for p in entry.parts if p.text is not None]
                extracted_text = '\n\n'.join(parts_texts)

        # Handle the special "[Info to help you answer: ...]" prefix in the text.
        # This logic remains the same as it's content-specific, not format-specific.
        if extracted_text.startswith('[Info to help you answer:'):
            # Find the closing bracket and strip the info prefix.
            end_bracket_index = extracted_text.find(']')
            if end_bracket_index != -1:
                extracted_text = extracted_text[end_bracket_index + 1:].strip()
            # If no ']' is found, the prefix handling might be incomplete,
            # but we proceed with the original text in that case.

        # Format the output string based on the 'md' (Markdown) flag.
        if md:
            result_string += f'{role_display}:\n\n{extracted_text}\n\n'
        else:
            result_string += f'{role_display}: {extracted_text}\n'

        # Add an extra newline after bot's response for better readability in non-Markdown.
        if role_display == '𝐁𝐎𝐓':
            if md:
                result_string += '\n\n' # Already added by text formatting. Let's make it consistent.
            else:
                result_string += '\n' # Add an extra newline for separation in plain text.
    
    return result_string.strip()


def chat_cli():
    while 1:
        q = input('>')
        if q == 'mem':
            print(get_mem_as_string('test'))
            continue
        if q == 'llama':
            print(get_mem_for_llama('test'))
            continue
        if q == 'jpg':
            r = img2txt(
                open(r'C:\Users\user\Downloads\samples for ai\картинки\фотография улицы.png', 'rb').read(),
                'что там',
                chat_id='test',
            )
        elif q == 'upd':
            r = 'ok'
            update_mem('2+2', '4', 'test')
        elif q == 'force':
            r = 'ok'
            force('test', 'изменено')
        elif q == 'undo':
            r = 'ok'
            undo('test')
        elif q == 'reset':
            r = 'ok'
            reset('test')
        else:
            r = chat(q, 'test')
        print(r)


if __name__ == "__main__":
    my_db.init(backup=False)
    my_gemini.load_users_keys()

    chat_cli()

    my_db.close()
