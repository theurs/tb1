# https://github.com/GoogleCloudPlatform/generative-ai/blob/main/gemini/getting-started/intro_gemini_chat.ipynb


import httpx
import io
import PIL
import random
import re
import time
import threading
import traceback
from typing import List, Dict, Union

import cachetools.func
from google import genai
from google.genai.types import (
    Blob,
    Content,
    File,
    FileData,
    FunctionCall,
    GenerateContentConfig,
    GenerateContentResponse,
    HttpOptions,
    ModelContent,
    Part,
    SafetySetting,
    ThinkingConfig,
    Tool,
    UserContent,
)

import cfg
import my_db
import my_gemini_general
import my_gemini_live_text
import my_github
import my_log
import my_skills
import my_skills_general
import my_skills_storage
import utils


# не принимать запросы больше чем, это ограничение для телеграм бота, в этом модуле оно не используется
MAX_REQUEST = 40000 # 20000


# системная инструкция для чат бота
SYSTEM_ = my_skills_general.SYSTEM_

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
    system_instruction: str | List[str],
    max_output_tokens: int = 8000,
    temperature: float = 1,
    tools: list = None,
    THINKING_BUDGET: int = -1,
    timeout: int = my_gemini_general.TIMEOUT,
    json_output: bool = False,
    ):
    # google_search_tool = Tool(google_search=GoogleSearch())
    # toolcodeexecution = Tool(code_execution=ToolCodeExecution())

    if THINKING_BUDGET == -1:
        THINKING_BUDGET = None
    thinking_config = ThinkingConfig(
        thinking_budget=THINKING_BUDGET,
        # include_thoughts=True,
    )
    json = "application/json" if json_output else None
    if THINKING_BUDGET:
        gen_config = GenerateContentConfig(
            http_options=HttpOptions(timeout=timeout*1000),
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            system_instruction=system_instruction or None,
            safety_settings=SAFETY_SETTINGS,
            # tools = [google_search_tool, toolcodeexecution]
            # tools = [my_skills.calc, my_skills.search_google]
            tools = tools,
            thinking_config=thinking_config,
            response_mime_type=json,
            # media_resolution="MEDIA_RESOLUTION_MEDIUM", # "MEDIA_RESOLUTION_LOW" "MEDIA_RESOLUTION_HIGH"
        )
    else:
        gen_config = GenerateContentConfig(
            http_options=HttpOptions(timeout=timeout*1000),
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            system_instruction=system_instruction or None,
            safety_settings=SAFETY_SETTINGS,
            tools = tools,
            response_mime_type=json,
            # media_resolution="MEDIA_RESOLUTION_MEDIUM", # "MEDIA_RESOLUTION_LOW" "MEDIA_RESOLUTION_HIGH"
        )

    return gen_config


# @cachetools.func.ttl_cache(maxsize=10, ttl = 10 * 60)
@utils.memory_safe_ttl_cache(maxsize=100, ttl=300)
def img2txt(
    data_: bytes,
    prompt: str = "Что на картинке?",
    temp: float = 1,
    model: str = cfg.gemini25_flash_model,
    json_output: bool = False,
    chat_id: str = '',
    use_skills: str = True,
    system: str = '',
    timeout: int = my_gemini_general.TIMEOUT,
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
                timeout=timeout,
                use_skills=use_skills,
            )

            # хз почему он так отвечает иногда, это должно быть как то связано с функцией tb:get_intention
            # но как не понятно
            if res == 'ask_image':
                return ''

            return res
        except Exception as error:
            if 'cannot identify image file' in str(error):
                return ''
            traceback_error = traceback.format_exc()
            my_log.log_gemini(f'my_gemini3:img2txt1: {error}\n\n{traceback_error}')
        time.sleep(2)
    my_log.log_gemini('my_gemini3:img2txt2: 4 tries done and no result')
    return ''


def remove_old_pics(mem: List[Union['Content', 'UserContent']], turns_cutoff: int = 5):
    """
    Cleans a list of memory entries by selectively stripping 'image' parts
    based on specific heuristics and recency rules. This function modifies
    the input `mem` list directly (in-place).

    An 'image' entry is now identified more strictly:
    1. The entry has more than one 'part'.
    2. At least one of its 'parts' contains a 'Blob' object in its `inline_data`
       attribute AND its `text` attribute is None. This distinguishes image
       Blobs from other non-textual parts (e.g., function calls).

    Rules applied for stripping 'image' parts (i.e., parts identified as image Blobs):
    1. Remove image Blob parts from all entries matching the 'image' heuristic,
       *except* the absolute last one found in the entire memory list.
    2. If the absolute last 'image' entry (after rule 1 consideration) is located
       further back than `turns_cutoff` conversational turns (where one turn
       is a user message + a model response, so `turns_cutoff * 2` messages)
       from the end of the memory list, then its image Blob parts are also removed.

    Args:
        mem (List[Union[Content, UserContent]]): The raw list of memory entries.
                                                   Each entry is expected to be
                                                   a Content or UserContent object.
                                                   This list will be modified in place.
        turns_cutoff (int, optional): The number of conversational turns from the
                                      end of the list used as the cutoff point for
                                      keeping the last image. Defaults to 5.

    """
    if not mem:
        return

    def _is_image_entry_heuristic(entry: Union['Content', 'UserContent']) -> bool:
        """
        Helper function (nested) to determine if a memory entry contains an 'image'
        based on the stricter heuristic: more than one part AND at least one part
        where text is None AND inline_data is a Blob object.
        """
        if not hasattr(entry, 'parts') or not isinstance(entry.parts, list) or not entry.parts:
            return False

        has_multiple_parts = len(entry.parts) > 1

        # Check if there is at least one part that specifically represents an image Blob.
        has_image_blob_part = False
        for p in entry.parts:
            # An 'image part' must have inline_data as a Blob AND its text must be None.
            if hasattr(p, 'inline_data') and hasattr(p.inline_data, '__class__') and p.inline_data.__class__.__name__ == 'Blob' and \
               hasattr(p, 'text') and p.text is None:
                has_image_blob_part = True
                break # Found one, no need to check other parts

        return has_multiple_parts and has_image_blob_part

    def _strip_image_blob_parts_from_entry(entry: Union['Content', 'UserContent']) -> None:
        """
        Helper function (nested) to modify a memory entry in place by removing
        only parts that are identified as image Blobs (text is None AND inline_data is a Blob).
        Other parts (even if text is None, like function calls) are explicitly kept.
        """
        if hasattr(entry, 'parts') and isinstance(entry.parts, list) and entry.parts:
            # Keep only parts that are NOT identified as image Blobs.
            entry.parts = [
                p for p in entry.parts
                if not (hasattr(p, 'inline_data') and hasattr(p.inline_data, '__class__') and p.inline_data.__class__.__name__ == 'Blob' and
                        hasattr(p, 'text') and p.text is None)
            ]

    # 1. Identify all entries that match the 'image' heuristic.
    image_heuristic_indices: List[int] = []
    for i, entry in enumerate(mem):
        if _is_image_entry_heuristic(entry):
            image_heuristic_indices.append(i)

    # Determine the index of the absolute last entry matching the 'image' heuristic.
    last_image_index: int | None = image_heuristic_indices[-1] if image_heuristic_indices else None

    # 2. Apply Rule 1: Strip image Blob parts from all 'image' heuristic entries EXCEPT the last one.
    if last_image_index is not None:
        for idx in image_heuristic_indices:
            # If the current entry is NOT the last one found, strip its image Blob parts.
            if idx != last_image_index:
                current_entry = mem[idx] # Get the entry from the original list (modifies in-place)
                _strip_image_blob_parts_from_entry(current_entry)

    # 3. Apply Rule 2: Check the recency of the last 'image' entry and potentially strip it too.
    if last_image_index is not None:
        # Calculate how many messages away the last image entry is from the end of the list.
        # Example: if list length is 10 and last_image_index is 7,
        # then num_messages_from_end = 10 - 7 = 3 (meaning entries at indices 7, 8, 9 are at or after it).
        num_messages_from_end = len(mem) - last_image_index

        # The cutoff is `turns_cutoff` conversational turns, which translates to
        # `turns_cutoff * 2` individual messages (one user, one model per turn).
        # If the image is further back than this cutoff (strictly greater), strip its image Blob parts.
        if num_messages_from_end > turns_cutoff * 2:
            current_entry = mem[last_image_index] # Get the entry from the original list (modifies in-place)
            _strip_image_blob_parts_from_entry(current_entry)

    # Return the modified input list.
    return mem


def remove_all_pics(mem: List[Union['Content', 'UserContent']]) -> bool:
    """
    Удаляет все части, содержащие изображения (Blob), из всех записей в списке памяти.
    Функция модифицирует список `mem` напрямую (in-place).
    Возвращает True, если были удалены какие-либо изображения, иначе False.

    Идентификация "части изображения":
    Часть считается изображением, если ее атрибут `inline_data` является объектом 'Blob'
    И ее атрибут `text` равен None.

    Args:
        mem (List[Union[Content, UserContent]]): Список записей памяти,
                                                   который будет модифицирован.
    """
    if not mem:
        return False

    changed = False # Флаг, который покажет, были ли изменения
    for entry in mem:
        if hasattr(entry, 'parts') and isinstance(entry.parts, list):
            original_parts_len = len(entry.parts)

            # Собираем только те части, которые НЕ являются изображениями
            parts_to_keep = []
            for p in entry.parts:
                is_image_blob = (
                    hasattr(p, 'inline_data') and
                    hasattr(p.inline_data, '__class__') and
                    p.inline_data.__class__.__name__ == 'Blob' and
                    hasattr(p, 'text') and p.text is None
                )
                if not is_image_blob:
                    parts_to_keep.append(p)

            # Если количество частей изменилось, значит, мы что-то удалили
            if len(parts_to_keep) < original_parts_len:
                entry.parts = parts_to_keep # Обновляем список частей
                changed = True # Отмечаем, что были изменения
    return changed # Возвращаем флаг


def validate_mem(mem):
    '''
    Проверяется корректность памяти
    У каждой записи должна быть прописана роль, если её нет то сделать дамп памяти для анализа
    и обнулить память для надежности
    '''
    for entry in mem:
        if not hasattr(entry, 'role') or entry.role not in ['user', 'model']:
            my_log.log_gemini(f'my_gemini3:validate_mem: Invalid memory entry: {entry}\n\nFull memory dump:\n{mem}')
            mem.clear()
            break


def parse_content_response(response: GenerateContentResponse) -> tuple[list[dict], str]:
    """
    Парсит объект GenerateContentResponse для извлечения текстового содержимого
    и данных изображений. На случай если в ответе есть картинки.

    Args:
        response: Объект GenerateContentResponse.

    Returns:
        Кортеж, содержащий:
        - Список словарей, где каждый словарь представляет изображение с ключами:
          'data' (байты), 'mime_type' (строка) и 'filename' (строка).
        - Единая строка, содержащая все объединенные текстовые части из ответа.
          Если текст отсутствует, возвращается пустая строка.
    """
    try:
        if not isinstance(response, GenerateContentResponse):
            return [], ""
        images = []
        full_text_parts = []
        image_counter = 0

        if not response or not hasattr(response, 'candidates') or not response.candidates:
            return images, ""

        for candidate in response.candidates:
            if hasattr(candidate, 'content') and candidate.content and \
            hasattr(candidate.content, 'parts') and candidate.content.parts:
                for part in candidate.content.parts:
                    # Извлечение текстовых частей
                    if hasattr(part, 'text') and part.text is not None:
                        full_text_parts.append(part.text)

                    # Извлечение данных изображений
                    if hasattr(part, 'inline_data') and part.inline_data:
                        if hasattr(part.inline_data, 'mime_type') and \
                        part.inline_data.mime_type.startswith('image/'):

                            image_data = part.inline_data.data
                            mime_type = part.inline_data.mime_type

                            filename = None
                            if hasattr(part.inline_data, 'display_name') and \
                            part.inline_data.display_name:
                                filename = part.inline_data.display_name
                            else:
                                # Генерируем имя файла, если оно не указано
                                extension = mime_type.split('/')[-1]
                                filename = f"image_{image_counter}.{extension}"
                                image_counter += 1

                            images.append({
                                "data": image_data,
                                "mime_type": mime_type,
                                "filename": filename
                            })

        return images, "".join(full_text_parts)
    except Exception as e:
        traceback_error = traceback.format_exc()
        my_log.log_gemini(f'my_gemini3:parse_content_response: Error parsing response: {e}\n\n{traceback_error}')
        return [], ""


def clear_non_text_parts(mem: list) -> list:
    """
    Проходит по истории сообщений и отфильтровывает все нетекстовые parts.
    Если сообщение после фильтрации не содержит текстовых parts, то оно удаляется
    из истории. Оставшиеся текстовые parts объединяются в один.
    """
    new_mem = []
    for message in mem:
        # Пропускаем сообщения, у которых нет parts или они пустые
        if not hasattr(message, 'parts') or not message.parts:
            continue

        text_parts_content = []
        # Класс Part берем из первого элемента, так как мы знаем, что parts не пуст
        PartClass = type(message.parts[0])

        for part in message.parts:
            # Если в part'е есть текст и он не пустой, добавляем его
            if hasattr(part, 'text') and part.text:
                text_parts_content.append(part.text)

        # Если после фильтрации текстовых parts не осталось, пропускаем это сообщение
        if not text_parts_content:
            continue

        # Объединяем все найденные текстовые части
        combined_text = "\n".join(text_parts_content)

        # Заменяем старый список parts одним новым текстовым part'ом
        message.parts = [PartClass(text=combined_text)]
        new_mem.append(message)

    # Обновляем исходный список mem, чтобы изменения были "на месте"
    mem[:] = new_mem
    return mem


def _count_chars_in_slice(mem_slice: List[Union[Content, UserContent]]) -> int:
    """Counts the total characters of text parts in a slice of memory."""
    # Counts the total characters of text parts in a slice of memory.
    count = 0
    for message in mem_slice:
        if hasattr(message, 'parts') and message.parts:
            for part in message.parts:
                if hasattr(part, 'text') and part.text:
                    count += len(part.text)
    return count


def trim_mem(mem: list, max_chat_mem_chars: int, clear: bool = False) -> None:
    """
    Trims the chat history if its size exceeds max_chat_mem_chars,
    respecting logical turn boundaries (including function call sequences).
    """
    # Trims the chat history if its size exceeds max_chat_mem_chars,
    # respecting logical turn boundaries (including function call sequences).
    if clear:
        # This function should be safe as it only removes non-text parts
        mem[:] = clear_non_text_parts(mem)

    if not mem:
        return

    # 1. Identify the start index of every logical turn.
    # A turn starts with a user message that is not a function response.
    turn_start_indices = [
        i for i, entry in enumerate(mem)
        if entry.role == 'user' and not _has_function_response(entry)
    ]

    if not turn_start_indices:
        # History might be malformed or start with a model response. Clear it for safety.
        mem.clear()
        return

    # 2. Iterate backwards through the turns to see how many fit in the memory limit.
    total_chars = 0
    keep_from_index = -1

    for i in range(len(turn_start_indices) - 1, -1, -1):
        start_index = turn_start_indices[i]
        # The turn ends right before the start of the next turn, or at the end of the list.
        end_index = turn_start_indices[i + 1] if i + 1 < len(turn_start_indices) else len(mem)

        turn_slice = mem[start_index:end_index]
        turn_chars = _count_chars_in_slice(turn_slice)

        if total_chars + turn_chars > max_chat_mem_chars:
            # This turn doesn't fit. We need to keep turns from the next one onwards.
            keep_from_index = turn_start_indices[i + 1] if i + 1 < len(turn_start_indices) else -1 # -1 means nothing fits
            break

        total_chars += turn_chars

    # 3. Perform the trim if necessary.
    if keep_from_index != -1:
        mem[:] = mem[keep_from_index:]
    elif total_chars > max_chat_mem_chars:
        # This happens if even the very last turn is too large. We clear everything.
        mem.clear()


def trim_all():
    '''
    Проходит по всем юзерам и зачищает ими историю от нетекстовых вставок
    '''
    all_users = my_db.get_all_users_ids()
    for user in all_users:
        mem = my_db.blob_to_obj(my_db.get_user_property(user, 'dialog_gemini3')) or []
        if mem:
            mem = clear_non_text_parts(mem)
            my_db.set_user_property(user, 'dialog_gemini3', my_db.obj_to_blob(mem))


def chat(
    query: str,
    chat_id: str = '',
    temperature: float = 1,
    model: str = '',
    system: str = '',
    max_tokens: int = 8000,
    max_chat_lines: int = my_gemini_general.MAX_CHAT_LINES,
    max_chat_mem_chars: int = my_gemini_general.MAX_CHAT_MEM_CHARS,
    timeout: int = my_gemini_general.TIMEOUT,
    use_skills: bool = False,
    THINKING_BUDGET: int = -1,
    json_output: bool = False,
    do_not_update_history: bool = False,
    key__: str = '',
    telegram_user_name: str = '',
    empty_memory: bool = False
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
        THINKING_BUDGET: The maximum number of tokens to spend on thinking. -1 = AUTO
        json_output: A boolean flag indicating whether to return the response as a JSON object.
        do_not_update_history: A boolean flag indicating whether to update the conversation history.
        key__: The API key to use for the request.
        telegram_user_name: The user's Telegram username.
        empty_memory: A boolean flag indicating whether to clear the conversation history.

    Returns:
        A string containing the model's response, or an empty string if an error occurs or the response is empty.

    Raises:
        None: The function catches and logs exceptions internally, returning an empty string on failure.
    """
    try:
        # Set a deadline for the entire operation
        deadline = time.time() + timeout

        # лайв модель по другому работает но с той же памятью
        if model in (my_gemini_live_text.DEFAULT_MODEL, my_gemini_live_text.FALLBACK_MODEL):
            if chat_id:
                mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_gemini3')) or []
                # Удаляем старые картинки, остается только последняя если она не была дольше чем 5 запросов назад
                remove_old_pics(mem)
                trim_mem(mem, max_chat_mem_chars, clear = True)
                # если на границе памяти находится вызов функции а не запрос юзера
                # то надо подрезать. начинаться должно с запроса юзера
                if mem and mem[0].role == 'user' and hasattr(mem[0].parts[0], 'text') and not mem[0].parts[0].text:
                    mem = mem[2:]
                validate_mem(mem)
                mem = validate_and_sanitize_mem(mem)
            else:
                mem = []
            if mem:
                my_db.set_user_property(chat_id, 'dialog_gemini3', my_db.obj_to_blob(mem))
            my_gemini_live_text.SYSTEM_ = SYSTEM_
            return my_gemini_live_text.get_resp(
                query,
                chat_id=chat_id,
                system=system,
                model=model,
                temperature=temperature,
                n_try=3,
                max_chat_lines=max_chat_lines,
                timeout=timeout
            )

        if model == 'gemini-2.5-flash-lite':
            THINKING_BUDGET = -1
            use_skills = False

        if 'gemma-3' in model:
            if temperature:
                temperature = temperature/2

        # not support thinking
        if 'gemini-2.0-flash' in model or 'gemma-3-27b-it' in model:
            THINKING_BUDGET = -1

        if isinstance(query, str):
            query = query[:my_gemini_general.MAX_SUM_REQUEST]
        elif isinstance(query, list):
            query[0] = query[0][:my_gemini_general.MAX_SUM_REQUEST]

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


        # Удаляем старые картинки, остается только последняя если она не была дольше чем 5 запросов назад
        remove_old_pics(mem)
        trim_mem(mem, max_chat_mem_chars)
        # если на границе памяти находится вызов функции а не запрос юзера
        # то надо подрезать. начинаться должно с запроса юзера
        if mem and mem[0].role == 'user' and hasattr(mem[0].parts[0], 'text') and not mem[0].parts[0].text:
            mem = mem[2:]

        validate_mem(mem)

        resp = ''
        key = ''
        resp_full = None

        # current date time string
        now = utils.get_full_time()
        saved_file_name = my_db.get_user_property(chat_id, 'saved_file_name') or ''
        if saved_file_name:
            saved_file = my_db.get_user_property(chat_id, 'saved_file') or ''
        else:
            saved_file = ''
        saved_file_size = len(saved_file)
        system_ = [
            f'Current date and time: {now}\n',
            f'Use this telegram chat id (user id) for API function calls: {chat_id}',
            *SYSTEM_,
            system,
        ]
        if telegram_user_name:
            system_.insert(1, f'Telegram reported user name: {telegram_user_name}')

        # сохраняем маркер для проверки валидности chat_id в модуле my_skills*
        my_skills_storage.STORAGE_ALLOWED_IDS[chat_id] = chat_id

        if saved_file_name:
            system_.insert(1, f'Telegram user have saved file/files and assistant can query it: {saved_file_name} ({saved_file_size} chars)')
        # if 'flash-lite' in model:
        #     system_.insert(1, 'You can draw graphs and charts using the code_execution_tool')

        if 'gemma-3-27b-it' in model:
            system_ = None


        if empty_memory:
            mem = []


        for _ in range(3):
            # Calculate remaining time for this attempt
            remaining_time = deadline - time.time()
            if remaining_time <= 0:
                my_log.log_gemini(f'my_gemini3:chat: Overall timeout of {timeout}s exceeded before new attempt.')
                break

            response = None

            try:
                if key__:
                    key = key__
                else:
                    key = my_gemini_general.get_next_key()
                # Use the remaining time for the client and config timeout
                client = genai.Client(api_key=key, http_options={'timeout': int(remaining_time * 1000)})
                if use_skills:
                    if model == 'gemini-2.5-flash-lite': # not support tools except search and code builtin
                        code_execution_tool = Tool(code_execution={})
                        google_search_tool = Tool(google_search={})
                        SKILLS = [google_search_tool, code_execution_tool,]
                        # лайт не умеет в функции? не все его версии умеют?
                        # SKILLS = [
                        #     my_skills.calc,
                        #     my_skills.search_google_fast,
                        #     my_skills.search_google_deep,
                        #     my_skills.download_text_from_url,
                        #     my_skills_general.save_to_txt,
                        #     my_skills.query_user_file,
                        #     my_skills.query_user_logs,
                        # ]
                        # SKILLS = None
                    elif 'gemma-3-27b-it' in model:
                        SKILLS = None
                    else:
                        SKILLS = [
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
                            my_skills.search_and_send_images,
                            my_skills.help,
                        ]
                        # прошка и сама может стихи написать
                        if model != cfg.gemini_pro_model:
                            SKILLS.append(compose_creative_text)
                    mem = validate_and_sanitize_mem(mem)
                    chat = client.chats.create(
                        model=model,
                        config=get_config(
                            system_instruction=system_,
                            tools=SKILLS,
                            THINKING_BUDGET=THINKING_BUDGET,
                            json_output=json_output,
                            timeout=int(remaining_time) # Pass remaining time to config
                        ),
                        history=mem,
                    )
                else:
                    mem = validate_and_sanitize_mem(mem)
                    chat = client.chats.create(
                        model=model,
                        config=get_config(
                            system_instruction=system_,
                            THINKING_BUDGET=THINKING_BUDGET,
                            json_output=json_output,
                            timeout=int(remaining_time) # Pass remaining time to config
                        ),
                        history=mem,
                    )
                response = chat.send_message(query,)
            except Exception as error:

                if '429 RESOURCE_EXHAUSTED' in str(error):
                    my_log.log_gemini(f'my_gemini3:chat:1: [{chat_id}] {str(error)} {model} {key}')
                    return ''
                elif 'API key expired. Please renew the API key.' in str(error) or '429 Quota exceeded for quota metric' in str(error):
                    my_gemini_general.remove_key(key)
                    continue
                if 'API Key not found. Please pass a valid API key.' in str(error):
                    my_gemini_general.remove_key(key)
                    continue
                elif 'timeout' in str(error).lower():
                    my_log.log_gemini(f'my_gemini3:chat:2:timeout: {str(error)} {model} {key}')
                    return ''
                elif """503 UNAVAILABLE. {'error': {'code': 503, 'message': 'The model is overloaded. Please try again later.', 'status': 'UNAVAILABLE'}}""" in str(error):
                    my_log.log_gemini(f'my_gemini3:chat:3: {str(error)} {model} {key}')
                    return ''
                elif """400 INVALID_ARGUMENT. {'error': {'code': 400, 'message': 'Please ensure that function response turn comes immediately after a function call turn.'""" in str(error):
                    traceback_error = traceback.format_exc()
                    my_log.log_gemini(f'my_gemini3:chat:4: {str(error)} {model} {key}')
                    my_log.log_gemini(f'my_gemini3:chat:5: Invalid history state. mem dump: {mem}')
                    my_log.log_gemini(f'my_gemini3:chat:6: {traceback_error}')
                    new_mem = []
                    i = 0
                    while i < len(mem):
                        # Проверяем, нужно ли удалить текущий элемент И следующий за ним
                        # Условие: текущий элемент пустой И следующий элемент существует
                        is_empty_current = hasattr(mem[i], 'parts') and mem[i].parts and hasattr(mem[i].parts[0], 'text') and not mem[i].parts[0].text

                        if is_empty_current and i + 1 < len(mem):
                            # Если текущий пустой И есть следующий, пропускаем оба
                            i += 2
                        else:
                            # Иначе, добавляем текущий в новый список и идем к следующему
                            new_mem.append(mem[i])
                            i += 1

                    mem = new_mem # Переприсваиваем
                else:
                    raise error

            if response:
                try:
                    # Safely attempt to access the text attribute.
                    # This will raise a ValueError if no valid text part exists (e.g., blocked by safety filters).
                    resp = response.text or ''
                except ValueError:
                    # Handle the case where the response was blocked or is otherwise empty.
                    if response.candidates:
                        my_log.log_gemini(f'my_gemini3:chat:7: response has no valid text part. Finish reason: {response.candidates[0].finish_reason}')
                    resp = ''
            else:
                resp = ''


            resp_full = parse_content_response(response)

            # модель ответила пустой ответ, но есть картинки (и возможно какой то другой ответ, хотя скорее всего текста нет)
            if not resp and resp_full and resp_full[0]:
                resp = '...'
                if resp_full[1]:
                    resp = resp_full[1]
                break
            elif not resp:
                if "finish_reason=<FinishReason.STOP: 'STOP'>" in str(response):
                    return ''
                time.sleep(2)
            else:
                break

        if resp:
            resp = resp.strip()

            # если есть картинки то отправляем их через my_skills_storage.STORAGE
            if resp_full and resp_full[0] and chat_id:
                for image in resp_full[0]:
                    item = {
                        'type': 'image/png file', # image['mime_type'],
                        'filename': image['filename'],
                        'data': image['data'],
                    }
                    with my_skills_storage.STORAGE_LOCK:
                        if chat_id in my_skills_storage.STORAGE:
                            if item not in my_skills_storage.STORAGE[chat_id]:
                                my_skills_storage.STORAGE[chat_id].append(item)
                        else:
                            my_skills_storage.STORAGE[chat_id] = [item,]


            # плохие ответы
            ppp = [
                '```python\nprint(default_api.',
                '```json\n{\n  "tool_code":',
                '```python\nprint(telegram_bot_api.',
                '```\nprint(default_api.',
            ]
            if any(resp.startswith(p) for p in ppp):
                my_log.log_gemini(f'chat:bad resp: {resp}')
                return ''

            to_cut = '''```json
{"tool_code": "print(OCR(photo_id=1))"}
```'''
            if resp.startswith(to_cut):
                resp = resp[len(to_cut):].strip()

            # флеш (и не только) иногда такие тексты в которых очень много повторов выдает,
            # куча пробелов, и возможно другие тоже. укорачиваем
            result_ = re.sub(r" {1000,}", " " * 10, resp) # очень много пробелов в ответе
            result_ = utils.shorten_all_repeats(result_)
            if len(result_)+100 < len(resp): # удалось сильно уменьшить
                resp = result_
                try:
                    chat._curated_history[-1].parts[-1].text = resp
                except Exception as error4:
                    my_log.log_gemini(f'my_gemini3:chat:8: {error4}\nresult: {result}\nchat history: {str(chat_.history)}')


            history = chat.get_history()
            if history:
                history = history[-max_chat_lines*2:]
                if chat_id:
                    if not do_not_update_history:
                        my_db.set_user_property(chat_id, 'dialog_gemini3', my_db.obj_to_blob(history))
                        my_db.add_msg(chat_id, model)

        return resp.strip()

    except Exception as error:
        traceback_error = traceback.format_exc()
        if """500 INTERNAL. {'error': {'code': 500, 'message': 'An internal error has occurred. Please retry or report in https://developers.generativeai.google/guide/troubleshooting', 'status': 'INTERNAL'}}""" in str(error) \
           or """503 UNAVAILABLE. {'error': {'code': 503, 'message': 'The service is currently unavailable.', 'status': 'UNAVAILABLE'}}""" in str(error):
            my_log.log_gemini(f'my_gemini3:chat:unknown_error:9: {chat_id} {error} {model}')
        else:
            if 'API Key not found. Please pass a valid API key.' in str(error):
                # my_log.log_gemini(f'my_gemini3:chat:unknown_error:2: {error}\nKey: [{key}]')
                my_gemini_general.remove_key(key)
            elif 'User location is not supported for the API use.' in str(error):
                my_log.log_gemini(f'my_gemini3:chat:unknown_error:10: {error}')
            elif 'validation errors for GenerateContentConfig' in str(error):
                pass
            elif 'Request contains an invalid argument.' in str(error):
                if '<PIL.JpegImagePlugin.JpegImageFile image mode=RGB' in str(query):
                    pass
                else:
                    my_log.log_gemini(f'my_gemini3:chat:unknown_error:11: [{chat_id}]\n{query[:1500]}\n\n{error}')
            elif 'Server disconnected without sending a response' or 'Попытка установить соединение была безуспешной' in str(error):
                my_log.log_gemini(f'my_gemini3:chat:unknown_error:12: [{chat_id}] {error}')
            else:
                my_log.log_gemini(f'my_gemini3:chat:unknown_error:13: {error}\n\n{traceback_error}\n{model}\nQuery: {str(query)[:1000]}\nMem: {str(mem)[:1000]}')
        return ''
    finally:
        if chat_id in my_skills_storage.STORAGE_ALLOWED_IDS:
            del my_skills_storage.STORAGE_ALLOWED_IDS[chat_id]


def _has_function_call(entry: Content) -> bool:
    """
    Checks if a model's Content entry contains a function call.
    """
    # Checks if a model's Content entry contains a function call.
    if not isinstance(entry, Content) or entry.role != 'model' or not entry.parts:
        return False
    # A function call is stored in the parts list
    return any(isinstance(part, FunctionCall) for part in entry.parts)


def _has_function_response(entry: Content) -> bool:
    """
    Checks if a user's Content entry contains a function response.
    """
    # Check if entry is a Content object with role 'user' and has parts
    # Checks if a user's Content entry contains a function response.
    if not isinstance(entry, Content) or entry.role != 'user' or not entry.parts:
        return False
    # A function response is stored in the parts list
    return any(isinstance(part, Part) and part.function_response for part in entry.parts)


def validate_and_sanitize_mem(
    mem: List[Union[Content, UserContent]]
) -> List[Union[Content, UserContent]]:
    """
    Validates and sanitizes a Gemini conversation history to prevent API errors.
    This version correctly handles function responses wrapped in the 'user' role.
    """
    # Validates and sanitizes a Gemini conversation history to prevent API errors.
    # This version correctly handles function responses wrapped in the 'user' role.
    if not mem:
        return []

    # Find the first 'user' turn and discard anything before it.
    try:
        first_user_index = next(i for i, entry in enumerate(mem) if entry.role == 'user')
        processing_list = mem[first_user_index:]
    except StopIteration:
        return []

    sanitized_mem: List[Union[Content, UserContent]] = []
    i = 0
    while i < len(processing_list):
        current_entry = processing_list[i]
        current_role = current_entry.role

        last_sanitized_role = sanitized_mem[-1].role if sanitized_mem else None
        last_entry_had_call = sanitized_mem and _has_function_call(sanitized_mem[-1])

        if current_role == 'user':
            # A user turn can be a normal message or a function response.
            is_func_response = _has_function_response(current_entry)

            if is_func_response:
                # This is a function response. It's only valid after a model's function call.
                if last_sanitized_role == 'model' and last_entry_had_call:
                    sanitized_mem.append(current_entry)
            else:
                # This is a normal user message. Valid at the start or after a model response.
                if last_sanitized_role is None or last_sanitized_role == 'model':
                    sanitized_mem.append(current_entry)
                # If we see user -> user, the second one starts a new valid sequence.
                elif last_sanitized_role == 'user':
                    sanitized_mem[-1] = current_entry

        elif current_role == 'model':
            # A model turn is valid after a user message (normal or function response).
            if last_sanitized_role == 'user':
                sanitized_mem.append(current_entry)

        # We silently skip invalid turns (e.g., model -> model)
        i += 1

    # Final cleanup: ensure the history doesn't end on an incomplete turn.
    if sanitized_mem:
        last_entry = sanitized_mem[-1]
        # If it ends on a user turn that is NOT a function response, it's an incomplete turn.
        if last_entry.role == 'user' and not _has_function_response(last_entry):
            sanitized_mem.pop()
        # If it ends on a model turn that expects a tool response, it's incomplete.
        elif last_entry.role == 'model' and _has_function_call(last_entry):
            sanitized_mem.pop()

    return sanitized_mem


def count_chars(mem) -> int:
    '''считает количество символов в чате'''
    total = 0
    for x in mem:
        if x.parts:
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

    mem = mem[-my_gemini_general.MAX_CHAT_LINES*2:]
    while count_chars(mem) > my_gemini_general.MAX_CHAT_MEM_CHARS:
        mem = mem[2:]

    if chat_id:
        my_db.set_user_property(chat_id, 'dialog_gemini3', my_db.obj_to_blob(mem))
    return mem


def force(chat_id: str, text: str, model: str = ''):
    '''
    Updates the last bot answer with the given text, handling complex function call chains.
    '''
    try:
        lock = my_gemini_general.LOCKS.setdefault(chat_id, threading.Lock())
        with lock:
            mem: List[Union[Content, UserContent]] = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_gemini3')) or []

            if not mem:
                # Cannot force an answer in an empty history
                return

            # Find the start of the last logical turn
            last_turn_start_index = -1
            for i in range(len(mem) - 1, -1, -1):
                entry = mem[i]
                if entry.role == 'user' and not _has_function_response(entry):
                    last_turn_start_index = i
                    break

            if last_turn_start_index != -1:
                # The turn starts with a user query. We keep it.
                user_query_entry = mem[last_turn_start_index]
                # Cut the history back to the point right before the last user query
                mem[:] = mem[:last_turn_start_index]
                # Now, add back the user query and the new forced model response
                mem.append(user_query_entry)
                mem.append(ModelContent(text))
            else:
                # This case is unlikely with valid history, but as a fallback,
                # we'll just replace the very last entry if it's from the model.
                if mem[-1].role == 'model':
                    mem[-1] = ModelContent(text)
                # If the last entry is from the user, we can't 'force' a model response
                # without breaking the sequence, so we do nothing.

            my_db.set_user_property(chat_id, 'dialog_gemini3', my_db.obj_to_blob(mem))
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_gemini(f'my_gemini3:force: Failed to force text in chat {chat_id}: {error}\n\n{error_traceback}\n\n{text}')


def undo(chat_id: str, model: str = ''):
    """
    Undoes the last logical turn in the chat history for a given chat ID.

    A logical turn can be a simple user-model exchange (2 entries) or a complex
    multi-step function call sequence (user -> model(call) -> user(response) -> model(answer)).
    This function finds the last user message that was not a function response
    and removes it and everything that follows.

    Args:
        chat_id (str): The ID of the chat.
        model (str, optional): The model name (unused, for compatibility).
    """
    try:
        # Acquire lock to prevent race conditions
        lock = my_gemini_general.LOCKS.setdefault(chat_id, threading.Lock())
        with lock:
            mem: List[Union[Content, UserContent]] = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_gemini3')) or []

            if not mem:
                # Nothing to undo
                return

            # Find the index of the start of the last logical turn.
            # We iterate backwards to find the last user message that is NOT a function response.
            last_turn_start_index = -1
            for i in range(len(mem) - 1, -1, -1):
                entry = mem[i]
                # A turn starts with a user message that is not a function_response part
                if entry.role == 'user' and not _has_function_response(entry):
                    last_turn_start_index = i
                    break

            if last_turn_start_index != -1:
                # If we found the start, slice the memory up to that point
                mem[:] = mem[:last_turn_start_index]
            else:
                # If no such user message was found (e.g., history is malformed or very short),
                # it's safest to clear the entire history.
                mem.clear()

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


def chat_cli(
    chat_id: str = 'test',
    model: str = cfg.gemini25_flash_model,
    THINKING_BUDGET: int = -1,
    use_skills: bool = False
    ) -> None:
    while 1:
        q = input('>')
        if q == 'mem':
            print(get_mem_as_string(chat_id))
            continue
        if q == 'llama':
            print(get_mem_for_llama(chat_id))
            continue
        if q == 'jpg':
            r = img2txt(
                open(r'C:\Users\user\Downloads\samples for ai\картинки\фотография улицы.png', 'rb').read(),
                'что там',
                chat_id=chat_id,
            )
        elif q == 'upd':
            r = 'ok'
            update_mem('2+2', '4', chat_id)
        elif q == 'force':
            r = 'ok'
            force(chat_id, 'изменено')
        elif q == 'undo':
            r = 'ok'
            undo(chat_id)
        elif q == 'reset':
            r = 'ok'
            reset(chat_id)
        else:
            r = chat(
                q,
                chat_id,
                model = model,
                THINKING_BUDGET=THINKING_BUDGET,
                use_skills=use_skills,
                )
        print(r)


def convert_mem(chat_id: str):
    '''
    Конвертирует память из старой таблицы dialog_gemini в новую dialog_gemini3
    Берет из базы память в формате для лламы, реконструирует для dialog_gemini3 и сохраняет
    '''
    try:
        mem = my_gemini_general.get_mem_for_llama(chat_id, lines_amount=10)
        new_mem = []

        # проходим по памяти берем по 2 элемента - запрос и ответ
        if len(mem) > 1 and len(mem) % 2 == 0:
            for i in range(0, len(mem), 2):
                e_user = mem[i]
                e_model = mem[i+1]
                u = UserContent(e_user['content'])
                c = ModelContent(e_model['content'])
                new_mem.append(u)
                new_mem.append(c)

            if new_mem:
                my_db.set_user_property(chat_id, 'dialog_gemini3', my_db.obj_to_blob(new_mem))        
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_gemini(f'my_gemini3:convert_mem:Failed to convert mem: {error}\n\n{error_traceback}')


@cachetools.func.ttl_cache(maxsize=10, ttl = 10 * 60)
def translate(
    text: str,
    from_lang: str = '',
    to_lang: str = '',
    help: str = '',
    censored: bool = False,
    model: str = ''
    ) -> str:
    """
    Translates the given text from one language to another.

    Args:
        text (str): The text to be translated.
        from_lang (str, optional): The language of the input text. If not specified, the language will be automatically detected.
        to_lang (str, optional): The language to translate the text into. If not specified, the text will be translated into Russian.
        help (str, optional): Help text for tranlator.
        censored (bool, optional): If True, the text will be censored. Not implemented.
        model (str, optional): The model to use for translation.
    Returns:
        str: The translated text.
    """
    if from_lang == '':
        from_lang = 'autodetect'
    if to_lang == '':
        to_lang = 'ru'

    if help:
        query = f'''
Translate TEXT from language [{from_lang}] to language [{to_lang}],
this can help you to translate better: [{help}]

Using this JSON schema:
  translation = {{"lang_from": str, "lang_to": str, "translation": str}}
Return a `translation`

TEXT:

{text}
'''
    else:
        query = f'''
Translate TEXT from language [{from_lang}] to language [{to_lang}].

Using this JSON schema:
  translation = {{"lang_from": str, "lang_to": str, "translation": str}}
Return a `translation`

TEXT:

{text}
'''

    translated = chat(query, temperature=0.1, model=model, json_output = True, do_not_update_history = True)

    translated_dict = utils.string_to_dict(translated)
    if translated_dict:
        if isinstance(translated_dict, dict):
            try:
                l1 = translated_dict['translation']
            except KeyError as error:
                my_log.log_gemini(f'my_gemini3:translate: key error {str(translated_dict)}')
                return ''
        elif isinstance(translated_dict, str):
            return translated_dict
        elif isinstance(translated_dict, list):
            l1 = translated_dict[0]['translation']
        else:
            my_log.log_gemini(f'translate1: unknown type {type(translated_dict)}\n\n{str(translated_dict)}')
            return ''
        # иногда возвращает словарь в словаре вложенный
        if isinstance(l1, dict):
            l2 = l1['translation']
            return l2
        elif isinstance(l1, str):
            return l1
        elif isinstance(translated_dict, list):
            text = translated_dict[0]['translation']
        else:
            my_log.log_gemini(f'translate2: unknown type {type(l1)}\n\n{str(l1)}')
            return ''
    return ''


def detect_lang(text: str, chat_id_full: str) -> str:
    q = f'''Detect language of the text, anwser supershort in 1 word iso_code_639_1 like
text = The quick brown fox jumps over the lazy dog.
answer = (en)
text = "Я люблю программировать"
answer = (ru)

Text to be detected: {text[:100]}
'''
    result = chat(
        q,
        chat_id=chat_id_full,
        temperature=0,
        model=cfg.gemini25_flash_model,
        max_tokens=10,
        do_not_update_history=True,
        timeout=30,
    )
    result = result.replace('"', '').replace(' ', '').replace("'", '').replace('(', '').replace(')', '').strip().lower()
    return result


def rebuild_subtitles(text: str, lang: str, chat_id_full: str) -> str:
    '''Переписывает субтитры с помощью ИИ, делает легкочитаемым красивым текстом.
    Args:
        text (str): текст субтитров
        lang (str): язык субтитров (2 буквы)
        chat_id_full (str): id чата
    '''
    def split_text(text: str, chunk_size: int) -> list:
        '''Разбивает текст на чанки.

        Делит текст по строкам. Если строка больше chunk_size, 
        то делит ее на части по последнему пробелу перед превышением chunk_size.
        '''
        chunks = []
        current_chunk = ""
        for line in text.splitlines():
            if len(current_chunk) + len(line) + 1 <= chunk_size:
                current_chunk += line + "\n"
            else:
                chunks.append(current_chunk.strip())
                current_chunk = line + "\n"
        if current_chunk:
            chunks.append(current_chunk.strip())

        result = []
        for chunk in chunks:
            if len(chunk) <= chunk_size:
                result.append(chunk)
            else:
                words = chunk.split()
                current_chunk = ""
                for word in words:
                    if len(current_chunk) + len(word) + 1 <= chunk_size:
                        current_chunk += word + " "
                    else:
                        result.append(current_chunk.strip())
                        current_chunk = word + " "
                if current_chunk:
                    result.append(current_chunk.strip())
        return result


    if len(text) > 25000:
        chunks = split_text(text, 24000)
        result = ''
        for chunk in chunks:
            r = rebuild_subtitles(chunk, lang, chat_id_full)
            result += r
        return result

    query = f'Fix errors, make an easy to read text out of the subtitles, make a fine paragraphs and sentences, output language = [{lang}]:\n\n{text}'
    result = chat(
        query,
        chat_id=chat_id_full,
        temperature=0.1,
        model=cfg.gemini25_flash_model,
        do_not_update_history=True,
    )
    return result


def list_models(include_context: bool = False):
    '''
    Lists all available models.
    '''
    client = genai.Client(api_key=my_gemini_general.get_next_key(), http_options={'timeout': 20 * 1000})

    result = []
    for model in client._models.list():
        # pprint.pprint(model)
        # result += f'{model.name}: {model.display_name} | in {model.input_token_limit} out {model.output_token_limit}\n{model.description}\n\n'
        if not model.name.startswith(('models/chat', 'models/text', 'models/embedding', 'models/aqa')):
            if include_context:
                result += [f'{model.name} {int(model.input_token_limit/1024)}k/{int(model.output_token_limit/1024)}k',]
            else:
                result += [f'{model.name}',]
    # sort results
    result = sorted(result)

    return '\n'.join(result)


def test_new_key(key: str, chat_id_full: str) -> bool:
    """
    Test if a new key is valid.

    Args:
        key (str): The key to be tested.

    Returns:
        bool: True if the key is valid, False otherwise.
    """
    try:
        if key in my_gemini_general.REMOVED_KEYS or key in my_gemini_general.BADKEYS:
            return False

        result = chat(
            '1+1= answer very short',
            chat_id=chat_id_full,
            key__=key,
            timeout=30,
            do_not_update_history=True,
        )
        if result.strip():
            return True
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log2(f'my_gemini3:test_new_key: {error}\n\n{error_traceback}')

    return False


@cachetools.func.ttl_cache(maxsize=100, ttl=15*60)
def rewrite_text_for_tts(text: str, user_id: str) -> str:
    '''
    Rewrites the given text for text-to-speech (TTS).

    This function takes a text string and reformulates it to make it easier to read aloud
    by TTS systems. It removes elements that are difficult to pronounce without adding
    any new words or translating the text. The function tries to ensure that the output
    text retains the same meaning as the input.

    Args:
        text (str): The text to be rewritten for TTS.
        user_id (str): The user ID associated with the request.

    Returns:
        str: The rewritten text suitable for TTS or empty string.
    '''

    try:
        query = f'''Rewrite this TEXT for TTS voiceover, remove from it what is difficult to read aloud,
do not add your own words to the result, your text response should only contain the new text.
Translating the text to another language is not allowed.
Example text: 2-3 weeks, maximum 5.
Example answer: two to three weeks, five at the most.
TEXT to rewrite:

{text}
'''
        result = chat(
            query=query,
            chat_id=user_id,
            temperature=0.1,
            model=cfg.gemini_flash_light_model,
            do_not_update_history=True
        )

        if not result:
            result = chat(
                query=query,
                chat_id=user_id,
                temperature=0.1,
                model=cfg.gemini_flash_light_model_fallback,
                do_not_update_history=True
            )

        if not result:
            return ''

        return result

    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log2(f'my_gemini3:rewrite_text_for_tts: {error}\n\n{error_traceback}')
        return ''


def compose_creative_text(prompt: str, context: str, user_id: str) -> str:
    '''
    Composes creative content such as songs, poems, and rhymed verses.
    Only use it if user ask for generating song, poem, or rhymed text.
    The output will be the generated text *only*, without any additional commentary.

    Args:
        prompt: The user's full request for creative text generation, including any topic, style, length, or specific rhyming schemes.
        context: The context for the creative text generation, brefly summarizing the dialog before the prompt.
        user_id: The Telegram user ID.

    Returns:
        The generated song, poem, or rhymed text.
    '''
    try:
        user_id = my_skills_general.restore_id(user_id)

        my_log.log_gemini_skills(f'compose_creative_text: {user_id} {prompt}\n\n{context}')

        query = f'''{{"request_type": "creative_text_generation", "user_prompt": "{prompt}", "context": "{context}", "output_format_instruction": "The output must contain only the requested creative text (regular text, song, poem, rhymed verse) without any introductory phrases, conversational remarks, or concluding comments."}}'''

        result = my_github.ai(
            prompt=query,
            user_id=user_id,
            temperature=1,
            model=my_github.BIG_GPT_MODEL,
        )

        if result:
            my_log.log_gemini_skills(f'compose_creative_text: {user_id} {prompt}\n\n{result}')
            return result

    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_gemini_skills(f'compose_creative_text: {error}\n\n{error_traceback}\n\n{prompt}')

    my_log.log_gemini_skills(f'compose_creative_text: {user_id} {prompt}\n\nThe muse did not answer, come up with something yourself without the help of tools.')
    return 'The muse did not answer, come up with something yourself without the help of tools.'


# одноразовая функция, удалить?
def converts_all_mems():
    '''
    Конвертирует все записи из старой таблицы dialog_gemini в новую dialog_gemini3
    '''
    try:
        all_users = my_db.get_all_users_ids()
        my_log.log_gemini(f'my_gemini3:converts_all_mems: Converting {len(all_users)} mems')
        for chat_id in all_users:
            convert_mem(chat_id)
        my_log.log_gemini(f'my_gemini3:converts_all_mems: Done')
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_gemini(f'my_gemini3:converts_all_mems:Failed to convert all mems: {error}\n\n{error_traceback}')


def remove_pics_from_all_mems():
    '''
    Удаляет все картинки из всех диалогов в dialog_gemini3
    '''
    try:
        all_users = my_db.get_all_users_ids()
        my_log.log_gemini(f'my_gemini3:remove_pics_from_all_mems: Removing pics from {len(all_users)} users')
        for chat_id in all_users:
            mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_gemini3')) or []

            # Вызываем измененную функцию, которая теперь возвращает True, если были изменения
            has_changed = remove_all_pics(mem) 

            if has_changed:
                my_db.set_user_property(chat_id, 'dialog_gemini3', my_db.obj_to_blob(mem))
                my_log.log_gemini(f'my_gemini3:remove_pics_from_all_mems: Pics removed for user {chat_id}')
            else:
                pass
                # my_log.log_gemini(f'my_gemini3:remove_pics_from_all_mems: No pics found or removed for user {chat_id}')
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_gemini(f'my_gemini3:remove_pics_from_all_mems: Failed to remove pics from all mems: {error}\n\n{error_traceback}')


def gemini_to_openai_mem(
    mem_input: Union[List[Union[Content, UserContent]], str]
) -> List[Dict[str, str]]:
    """
    Converts Gemini-style memory to OpenAI-style memory.

    Accepts either a list of Gemini Content objects or a string (chat_id)
    to fetch the memory from the database ('dialog_gemini3').

    This function strips all non-text parts, ensures role compatibility,
    and returns a balanced list of user/assistant turns.

    Args:
        mem_input: A list of Gemini objects or a chat_id string.

    Returns:
        A list of dictionaries formatted for OpenAI.
    """
    mem: List[Union[Content, UserContent]]
    if isinstance(mem_input, str):
        # Input is a chat_id, fetch memory from the database
        mem = my_db.blob_to_obj(
            my_db.get_user_property(mem_input, 'dialog_gemini3')
        ) or []
    elif isinstance(mem_input, list):
        # Input is already a memory list
        mem = mem_input
    else:
        # Invalid input type
        return []

    openai_mem: List[Dict[str, str]] = []
    if not mem:
        return openai_mem

    for entry in mem:
        # Determine the role for the OpenAI format
        role: str
        if entry.role == 'user':
            role = 'user'
        elif entry.role == 'model':
            role = 'assistant'
        else:
            # Skip any other roles (e.g., 'tool')
            continue

        # Extract and combine all text parts from the entry
        if not hasattr(entry, 'parts') or not entry.parts:
            continue

        text_parts = [
            part.text for part in entry.parts if hasattr(part, 'text') and part.text
        ]
        if not text_parts:
            continue

        content = "\n".join(text_parts).strip()
        if content:
            openai_mem.append({'role': role, 'content': content})

    # Ensure the conversation is balanced (ends with an assistant response)
    if openai_mem and openai_mem[-1]['role'] == 'user':
        openai_mem.pop()

    return openai_mem


def openai_to_gemini_mem(
    mem_input: Union[List[Dict[str, str]], str]
) -> List[Union[Content, UserContent]]:
    """
    Converts OpenAI-style memory to Gemini-style memory.

    Accepts either a list of OpenAI-style dictionaries or a string (chat_id)
    to fetch the memory from the database ('dialog_openrouter').

    Args:
        mem_input: A list of dictionaries or a chat_id string.

    Returns:
        A list of Gemini Content or UserContent objects.
    """
    mem: List[Dict[str, str]]
    if isinstance(mem_input, str):
        # Input is a chat_id, fetch memory from the database
        mem = my_db.blob_to_obj(
            my_db.get_user_property(mem_input, 'dialog_openrouter')
        ) or []
    elif isinstance(mem_input, list):
        # Input is already a memory list
        mem = mem_input
    else:
        # Invalid input type
        return []

    gemini_mem: List[Union[Content, UserContent]] = []
    if not mem:
        return gemini_mem

    for entry in mem:
        role = entry.get('role')
        content = entry.get('content')

        # Validate entry structure and content
        if not isinstance(content, str) or not content.strip():
            continue

        # Create the appropriate Gemini object based on the role
        if role == 'user':
            gemini_mem.append(UserContent(content))
        elif role == 'assistant':
            gemini_mem.append(ModelContent(content))
        # Silently ignore other roles like 'system' or 'tool'

    # Ensure the conversation is balanced (ends with a model response)
    if gemini_mem and gemini_mem[-1].role == 'user':
        gemini_mem.pop()

    return gemini_mem


def _wait_for_file_active(client: genai.Client, file_obj: File, timeout_sec: int = 180) -> File | None:
    """
    Waits for a file to become ACTIVE, polling its state.
    The key used in the client must be the one that uploaded the file.
    """
    start_time = time.time()
    file_name = file_obj.name
    while True:
        try:
            # Re-fetch the file object to get the latest state
            file_obj = client.files.get(name=file_name)
        except Exception as e:
            my_log.log_gemini(f'my_gemini3:_wait_for_file_active: Failed to get file state for {file_name}: {e}')
            time.sleep(5)
            continue # Retry getting state

        if file_obj.state.name == 'ACTIVE':
            return file_obj
        if file_obj.state.name == 'FAILED':
            my_log.log_gemini(f"my_gemini3:_wait_for_file_active: File {file_name} processing failed.")
            return None
        if time.time() - start_time > timeout_sec:
            my_log.log_gemini(f"my_gemini3:_wait_for_file_active: File {file_name} did not become active in {timeout_sec} seconds.")
            return None
        time.sleep(3)


@utils.async_run
def _robust_delete_file(client: genai.Client, file_name: str, attempts: int = 5, delay_sec: int = 30):
    """
    Tries to delete a file multiple times with delays.
    The key used in the client must be the one that uploaded the file.
    """
    for attempt in range(attempts):
        try:
            client.files.delete(name=file_name)
            # my_log.log_gemini(f'my_gemini3:_robust_delete_file: Successfully deleted file {file_name} on attempt {attempt + 1}.')
            return
        except Exception as e:
            # my_log.log_gemini(f'my_gemini3:_robust_delete_file: Attempt {attempt + 1}/{attempts} failed to delete {file_name}: {e}')
            if attempt < attempts - 1:
                time.sleep(delay_sec)
    my_log.log_gemini(f'my_gemini3:_robust_delete_file: Failed to delete file {file_name} after {attempts} attempts.')


@cachetools.func.ttl_cache(maxsize=10, ttl = 10 * 60)
def video2txt(
    video_data: bytes|str,
    prompt: str = "Опиши это видео.",
    system: str = '',
    model: str = cfg.gemini25_flash_model,
    chat_id: str = '',
    timeout: int = my_gemini_general.TIMEOUT,
    max_tokens: int = 8000,
    temperature: float = 1,
) -> str:
    """
    Analyzes a video file or URL and generates a text description based on a user prompt.

    This function is designed to be robust. It handles different input types:
    - Raw bytes: For files under 20MB, it sends data inline. For larger files,
      it uploads to temporary storage before analysis.
    - String path: A local file path, which is read into bytes.
    - URL: A web URL (e.g., YouTube), which is passed directly to the model.

    The entire process respects an overall timeout and is wrapped in a retry loop.
    If an API key is invalid, expired, or has exhausted its quota, the function
    will automatically discard the key, clean up resources, and retry with a new key.

    Args:
        video_data (bytes | str): The video content, provided as raw bytes,
                                  a string path to a local file, or a URL.
        prompt (str, optional): The instruction for the model based on the video.
                                Defaults to "Опиши это видео.".
        system (str, optional): A system-level instruction to guide the model's behavior.
        model (str, optional): The specific Gemini model to use for the analysis.
                               Defaults to `cfg.gemini25_flash_model`.
        chat_id (str, optional): An identifier for the chat session for logging.
        timeout (int, optional): The total timeout in seconds for the entire operation.
                                 Defaults to `my_gemini_general.TIMEOUT`.
        max_tokens (int, optional): The maximum number of tokens for the response.
        temperature (float, optional): Controls the randomness of the output (0 to 2).

    Returns:
        str: The generated text description of the video. Returns an empty string
             if the analysis fails or times out.
    """
    # Determine input type
    is_url = False
    if isinstance(video_data, str):
        if video_data.startswith(('https://', 'http://')):
            is_url = True
        else:  # It's a file path, read it into bytes
            with open(video_data, 'rb') as f:
                video_data = f.read()

    deadline = time.time() + timeout  # Overall deadline

    # Main retry loop for API keys
    tries = 3
    for _ in range(tries):
        key = ''
        client = None
        uploaded_file = None
        temp_file_path = ''

        remaining_time = deadline - time.time()
        if remaining_time <= 0:
            my_log.log_gemini('my_gemini3:video2txt: Overall timeout exceeded before new attempt.')
            break

        try:
            key = my_gemini_general.get_next_key()
            client = genai.Client(api_key=key, http_options={'timeout': int(remaining_time * 1000)})
            contents = None

            if is_url:
                # Handle URL input
                video_part = Part(file_data=FileData(file_uri=video_data))
                contents = [video_part, Part(text=prompt)]
            else:
                # Handle bytes input (from file or direct)
                MAX_VIDEO_SIZE_INLINE = 20 * 1024 * 1024
                if len(video_data) > MAX_VIDEO_SIZE_INLINE:
                    # Large file: upload it
                    temp_file_path = utils.get_tmp_fname(ext='.mp4')
                    with open(temp_file_path, 'wb') as f:
                        f.write(video_data)

                    initial_file_obj = client.files.upload(file=temp_file_path)

                    remaining_wait_time = int(deadline - time.time())
                    if remaining_wait_time <= 0:
                        my_log.log_gemini('my_gemini3:video2txt: Timeout exceeded before file could be processed.')
                        continue

                    uploaded_file = _wait_for_file_active(client, initial_file_obj, timeout_sec=remaining_wait_time)
                    if not uploaded_file:
                        my_log.log_gemini(f'my_gemini3:video2txt: File processing failed or timed out for key {key}.')
                        continue

                    contents = [uploaded_file, prompt]
                else:
                    # Small file: send inline
                    video_part = Part(inline_data=Blob(data=video_data, mime_type='video/mp4'))
                    contents = Content(parts=[video_part, Part(text=prompt)])

            remaining_gen_time = deadline - time.time()
            if remaining_gen_time <= 0:
                my_log.log_gemini('my_gemini3:video2txt: Timeout exceeded before content generation.')
                break

            # Generate content
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=get_config(
                    system_instruction=system,
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                    timeout=int(remaining_gen_time),
                ),
            )

            resp = ''
            if response:
                try:
                    resp = response.text or ''
                except ValueError:
                    if response.candidates:
                        my_log.log_gemini(f'my_gemini3:video2txt: Response blocked. Finish reason: {response.candidates[0].finish_reason}')

            if resp:
                if chat_id and model:
                    my_db.add_msg(chat_id, model)
                return resp.strip()

        except Exception as error:
            traceback_error = traceback.format_exc()
            err_str = str(error)
            if 'API key' in err_str or 'Quota exceeded' in err_str or 'RESOURCE_EXHAUSTED' in err_str:
                my_log.log_gemini(f'my_gemini3:video2txt: Key-related error with key {key}. Removing and retrying.')
                my_gemini_general.remove_key(key)
                continue
            else:
                my_log.log_gemini(f'my_gemini3:video2txt: Non-key error: {error}\n{traceback_error}')
                break
        finally:
            if uploaded_file and client:
                _robust_delete_file(client, uploaded_file.name)
            if temp_file_path:
                utils.remove_file(temp_file_path)

    my_log.log_gemini('my_gemini3:video2txt: Failed to get response after all retries or timeout.')
    return ''


# @cachetools.func.ttl_cache(maxsize=10, ttl = 10 * 60)
@utils.memory_safe_ttl_cache(maxsize=100, ttl=300)
def doc2txt(
    doc_data: bytes | str,
    prompt: str = "",
    system: str = '',
    model: str = cfg.gemini25_flash_model,
    chat_id: str = '',
    timeout: int = my_gemini_general.TIMEOUT,
    max_tokens: int = 8000,
    temperature: float = 1,
    mime_type: str = 'application/pdf',
) -> str:
    """
    Analyzes a document and generates text based on a prompt.

    Handles different input types: raw bytes, local file path, or URL.
    For documents over 20MB, it uses the File API for uploading and
    cleans up the uploaded file afterward. Automatically retries with a new
    API key on key-related failures.

    Args:
        doc_data (bytes | str): The document content as raw bytes, a local
                                file path, or a URL.
        prompt (str, optional): The instruction for the model.
        system (str, optional): System-level instruction for the model.
        model (str, optional): The Gemini model to use.
        chat_id (str, optional): Chat session identifier for logging.
        timeout (int, optional): Overall timeout for the operation in seconds.
        max_tokens (int, optional): Maximum tokens for the response.
        temperature (float, optional): Controls output randomness (0 to 2).
        mime_type (str, optional): The MIME type of the document.
                                   Defaults to 'application/pdf'.

    Returns:
        str: The generated text description. Returns an empty string on
             failure or timeout.
    """

    PROMPT_OCR_ADVANCED = """
Your role is an AI-powered document processing and restoration expert. Your mission is to transcribe the provided document into clean, readable, and well-structured Markdown text. Your goal is not just to extract characters, but to restore the document's original intent and improve its readability.

Follow these instructions meticulously:

**Phase 1: Full Content Extraction**
1.  **Transcribe Everything:** Extract 100% of the textual content from all pages. This includes main body text, headers, footers, page numbers, table content, footnotes, and text within images or diagrams. Do not omit any information.

**Phase 2: Intelligent Correction and Refinement**
2.  **Correct Obvious OCR Errors:** Use your language understanding to identify and fix common OCR mistakes.
    -   Example: `rec0gnize` should become `recognize`.
    -   Example: `rn` might be `m` (e.g., `rnodern` -> `modern`).
    -   Example: `l` might be `i` or `1` and vice-versa.
    -   Correct typos and spelling errors that are clearly artifacts of the scanning process, but preserve the original wording and grammar.
3.  **Merge Broken Lines and Words (De-hyphenation):** Reconstruct the natural flow of text.
    -   Merge words that are broken by a hyphen at the end of a line (e.g., "contin-" on one line and "uation" on the next should become "continuation").
    -   Join lines that form a single sentence but were split due to the original document's layout. Create coherent paragraphs.

**Phase 3: Structural Reconstruction (Formatting)**
4.  **Recreate Document Structure using Markdown:** Do not just output a wall of text. Replicate the original hierarchy and formatting.
    -   **Headings:** Use Markdown headings (`#`, `##`, `###`) for titles and subtitles, matching the original's hierarchy.
    -   **Emphasis:** Preserve **bold** text using `**text**` and *italic* text using `*text*`.
    -   **Lists:** Format bulleted lists using (`-` or `*`) and numbered lists using (`1.`, `2.`).
    -   **Tables:** Recreate tables using Markdown table syntax. Ensure columns and rows are correctly aligned.
    -   **Paragraphs:** Maintain paragraph breaks as they appear in the original document. Add a blank line between paragraphs.
    -   **Quotes:** Use blockquote syntax (`>`) for quoted text.

**Phase 4: Final Output Rules (Crucial)**
5.  **No Interpretation or Summarization:** Your task is transcription and restoration, NOT analysis. DO NOT summarize, explain, or add your own thoughts.
6.  **No Extra Text:** The output must contain ONLY the restored document text in Markdown. DO NOT include any introductory phrases like "Here is the transcribed document:", conversational filler, or concluding remarks.
7.  **Preserve Original Language:** The output must be in the same language as the source document. DO NOT translate any part of it.

Your final output is a single block of clean, corrected, and well-formatted Markdown text.
"""

    if not prompt:
        prompt = PROMPT_OCR_ADVANCED

    deadline = time.time() + timeout  # Overall deadline

    # Handle different input types
    if isinstance(doc_data, str):
        if doc_data.startswith(('https://', 'http://')):
            try:
                # Download URL content, respecting a portion of the timeout
                with httpx.Client(timeout=timeout*0.8) as client:
                    response = client.get(doc_data)
                    response.raise_for_status()
                    doc_data = response.content
            except Exception as e:
                my_log.log_gemini(f'my_gemini3:doc2txt: Failed to download URL {doc_data}: {e}')
                return ''
        else:  # It's a file path
            with open(doc_data, 'rb') as f:
                doc_data = f.read()

    # Main retry loop for API keys
    tries = 3
    for _ in range(tries):
        key = ''
        client = None
        uploaded_file = None
        temp_file_path = ''

        remaining_time = deadline - time.time()
        if remaining_time <= 0:
            my_log.log_gemini('my_gemini3:doc2txt: Overall timeout exceeded.')
            break

        try:
            key = my_gemini_general.get_next_key()
            client = genai.Client(api_key=key, http_options={'timeout': int(remaining_time * 1000)})
            contents = None

            MAX_DOC_SIZE_INLINE = 20 * 1024 * 1024
            if len(doc_data) > MAX_DOC_SIZE_INLINE:
                # Upload large document via File API
                temp_file_path = utils.get_tmp_fname(ext='.pdf')
                with open(temp_file_path, 'wb') as f:
                    f.write(doc_data)

                # Use a specific config for mime_type
                upload_config = FileData(mime_type=mime_type)
                initial_file_obj = client.files.upload(file=temp_file_path, file_data=upload_config)

                wait_timeout = int(deadline - time.time())
                if wait_timeout <= 0: continue

                uploaded_file = _wait_for_file_active(client, initial_file_obj, timeout_sec=wait_timeout)
                if not uploaded_file:
                    my_log.log_gemini(f'my_gemini3:doc2txt: File processing failed or timed out for key {key}.')
                    continue

                contents = [uploaded_file, prompt]
            else:
                # Send smaller document inline
                doc_part = Part.from_bytes(data=doc_data, mime_type=mime_type)
                contents = [doc_part, Part(text=prompt)]

            gen_timeout = deadline - time.time()
            if gen_timeout <= 0: break

            # Generate content
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=get_config(
                    system_instruction=system,
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                    timeout=int(gen_timeout),
                ),
            )

            resp = response.text or ''
            if resp:
                if chat_id and model:
                    my_db.add_msg(chat_id, model)
                return resp.strip()

        except Exception as error:
            err_str = str(error)
            if 'API key' in err_str or 'Quota exceeded' in err_str or 'RESOURCE_EXHAUSTED' in err_str:
                my_log.log_gemini(f'my_gemini3:doc2txt: Key error with {key}. Retrying.')
                my_gemini_general.remove_key(key)
                continue # Retry with a new key
            else:
                traceback_error = traceback.format_exc()
                my_log.log_gemini(f'my_gemini3:doc2txt: Non-key error: {error}\n{traceback_error}')
                break # Break on other errors
        finally:
            if uploaded_file and client:
                _robust_delete_file(client, uploaded_file.name)
            if temp_file_path:
                utils.remove_file(temp_file_path)

    my_log.log_gemini('my_gemini3:doc2txt: Failed after all retries or timeout.')
    return ''


def get_reprompt_for_image(prompt: str, chat_id: str = '') -> tuple[str, str, str, bool, bool] | None:
    """
    Executes a pre-formatted prompt to get a detailed image generation prompt.

    It takes a fully-formed query string, sends it to the model, and parses the
    expected JSON response.

    Args:
        prompt: A complete, pre-formatted query string containing all instructions for the model.
        chat_id: The user's chat ID for logging and context.

    Returns:
        A tuple containing (positive_prompt, negative_prompt, moderation_sexual, moderation_hate)
        if successful, otherwise None.
    """
    result = chat(
        query=prompt,
        chat_id=chat_id,
        temperature=1.5,
        model=cfg.gemini25_flash_model,
        json_output=True,
        do_not_update_history=True,
        empty_memory=True
    )

    if not result:
        return None

    result_dict = utils.string_to_dict(result)
    if not result_dict:
        my_log.log_gemini(f'my_gemini3:get_reprompt: Failed to parse JSON response for prompt: "{prompt[:150]}..."')
        return None

    # Extract values based on the keys defined in the external prompt's JSON schema
    reprompt = result_dict.get('reprompt', '')
    negative_prompt = result_dict.get('negative_reprompt', '')
    moderation_sexual = result_dict.get('moderation_sexual', False)
    moderation_hate = result_dict.get('moderation_hate', False)
    preffered_aspect_ratio = result_dict.get('preffered_aspect_ratio', '1')

    # if moderation_sexual or moderation_hate:
    #     my_log.log_reprompt_moderation(
    #         f'MODERATION (my_gemini3) triggered: Sexual={moderation_sexual}, Hate={moderation_hate}. '
    #         f'Prompt: "{prompt}..."'
    #     )

    if moderation_sexual or moderation_hate:
        return 'MODERATION ' + reprompt, negative_prompt, preffered_aspect_ratio, moderation_sexual, moderation_hate

    # Return the values if the essential parts are present
    if reprompt and negative_prompt:
        return reprompt, negative_prompt, preffered_aspect_ratio, moderation_sexual, moderation_hate

    return None


@utils.memory_safe_ttl_cache(maxsize=100, ttl=300)
def sum_big_text(
    text:str,
    query: str,
    temperature: float = 1,
    role: str = '',
    model1: str = '',
    model2: str = '',
    chat_id: str = '',
) -> str:
    """
    Generates a response from an AI model based on a given text,
    query, and temperature.

    Args:
        text (str): The complete text to be used as input.
        query (str): The query to be used for generating the response.
        temperature (float, optional): The temperature parameter for controlling the randomness of the response. Defaults to 0.1.
        role (str, optional): System prompt. Defaults to ''.
        model (str, optional): The name of the model to be used for generating the response.
        model2 (str, optional): The name of the fallback model to be used for generating the response.
        chat_id (str, optional): The user's chat ID for logging and context.

    Returns:
        str: The generated response from the AI model.
    """
    if not model1:
        model1 = cfg.gemini25_flash_model
    if not model2:
        model2 = cfg.gemini25_flash_model_fallback
    query = f'''{query}\n\n{text[:my_gemini_general.MAX_SUM_REQUEST]}'''
    r = chat(query, temperature=temperature, model=model1, system=role, chat_id=chat_id, do_not_update_history=True, empty_memory=True)
    if not r:
        r = chat(query, temperature=temperature, model=model2, system=role, chat_id=chat_id, do_not_update_history=True, empty_memory=True)
    return r


def retranscribe(text: str, prompt: str = '', chat_id: str = '') -> str:
    '''исправить текст после транскрипции выполненной гуглом'''
    if prompt:
        query = f'{prompt}:\n\n{text}'
    else:
        query = f'Fix errors, make a fine text of the transcription, keep original language:\n\n{text}'
    result = chat(query, temperature=0.1, model=cfg.gemini25_flash_model, chat_id=chat_id, do_not_update_history=True, empty_memory=True)
    return result


def trim_user_history(chat_id: str, max_history_size: int) -> None:
    """
    Reads, trims, and saves memory for a user based on the number of logical turns.
    This function is standalone and does not affect the regular update flow.
    """
    #
    # Reads, trims, and saves memory for a user based on the number of logical turns.
    # A logical turn starts with a user message that is not a function response.
    #
    if max_history_size == 1000:
        return
    mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_gemini3')) or []
    if not mem:
        return

    if max_history_size <= 0:
        mem.clear()
    else:
        # Identify the start of each logical turn
        turn_start_indices = [
            i for i, entry in enumerate(mem)
            if entry.role == 'user' and not _has_function_response(entry)
        ]

        # If the number of turns exceeds the user's limit, trim the oldest ones
        if len(turn_start_indices) > max_history_size:
            keep_from_index = turn_start_indices[-max_history_size]
            mem = mem[keep_from_index:]  # Create the trimmed slice

    my_db.set_user_property(chat_id, 'dialog_gemini3', my_db.obj_to_blob(mem))


def find_bad_keys():
    '''
    Проверяет все ключи, если ключ не сработал то репортит
    '''
    
    keys = cfg.gemini_keys[:] + my_gemini_general.ALL_KEYS[:]

    # preload bad keys
    _ = my_gemini_general.get_next_key()

    for key in keys:
        if not test_new_key(key, ''):
            print(key)
        time.sleep(random.randint(1, 5))


if __name__ == "__main__":
    my_db.init(backup=False, vacuum=False)
    my_gemini_general.load_users_keys()

    # print(video2txt(r'C:\Users\user\Downloads\samples for ai\видео\без слов.webm', 'что за самолет'))
    # print(video2txt(r'C:\Users\user\Downloads\samples for ai\видео\видеоклип с песней.webm', 'сделай транскрипцию текста, исправь очевидные ошибки распознавания запиши красиво текст удобно для чтения с разбиением на абзацы'))

    # print(doc2txt(r'C:\Users\user\Downloads\samples for ai\20220816043638.pdf'))

    # mem2 = gemini_to_openai_mem('[123] [0]')
    # mem3 = openai_to_gemini_mem('[123] [0]')
    # from pprint import pprint
    # pprint(mem2)
    # pprint(mem3)

    # remove_pics_from_all_mems()

    # один раз запустить надо
    # converts_all_mems()
    # print(list_models(include_context=True))

    find_bad_keys()

    reset('test')
    chat_cli(model = 'gemini-2.5-flash')

    # chat_cli(model = 'gemini-2.5-flash', THINKING_BUDGET=10000, use_skills=True)
    # chat_cli(model = 'gemini-2.0-flash', THINKING_BUDGET=10000, use_skills=True)

    # with open(r'c:\Users\user\Downloads\samples for ai\myachev_Significant_Digits_-_znachaschie_tsifryi_106746.txt', 'r', encoding='utf-8') as f:
    #     t = f.read()
    # q = f'Составь оглавление книги из текста:\n\n\n{t}'
    # print(chat(q, 'test', model = 'gemini-2.5-flash-lite', system='отвечай всегда по-русски'))
    # print(len(q))
    # print(chat(q, 'test', model = 'gemini-2.5-flash-preview-05-20', system='отвечай всегда по-русски'))


    my_db.close()
