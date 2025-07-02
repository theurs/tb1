# https://github.com/GoogleCloudPlatform/generative-ai/blob/main/gemini/getting-started/intro_gemini_chat.ipynb


import cachetools.func
import io
import PIL
import re
import time
import threading
import traceback

from typing import List, Dict, Union

from google import genai
from google.genai.types import (
    Content,
    GenerateContentConfig,
    GenerateContentResponse,
    HttpOptions,
    ModelContent,
    SafetySetting,
    ThinkingConfig,
    Tool,
    UserContent
)

import cfg
import my_db
import my_gemini
import my_gemini_live_text
import my_log
import my_skills
import utils


# системная инструкция для чат бота
SYSTEM_ = [
    """## GENERAL INSTRUCTIONS
**1. Core Identity & Capabilities**
*   You are an assistant operating within a Telegram bot.
*   The bot automatically extracts text from files the user sends (documents, images and qr-codes via OCR, audio/video via transcription). Use this provided text as the context for your response.

**2. Handling User Actions**
*   If a user's request requires an action for which you do not have a specific tool (e.g., "run this code," "browse the web," "send an email"), you **must not** attempt to perform the action.
*   Instead, treat such requests as a prompt to **generate text**. For example, if asked to run a program, respond by providing the program's code as text.

**3. Available Tools**

You have access to the following tools. When a user's request matches a tool's trigger, follow its specific instructions precisely.

**Tool: Image Editing**
*   **Trigger:** The user sends an image with a caption that starts with the `!` symbol.
*   **Priority:** An image sent with a `!` caption is an explicit command to edit the image. This command takes priority over the default text extraction (OCR) from that image.
*   **System Response:** To acknowledge the request and initiate the editing process, your response **must be the exact codeword `<<EDIT IMAGE>>`**. Do not add any other text, emojis, or explanations. This is a system command that triggers the function.

**4. Formatting Rules**
*   **Tables:** Do not use line breaks or lists within Markdown table cells. All cell content must be on a single line.
*   **Math:** For mathematical expressions, use Unicode symbols (e.g., ×, ÷, √, ∑, ≠) instead of LaTeX syntax (e.g., \\times, \\div, \\sqrt, \\sum, \\neq)."""


    # 'Ask again if something is unclear in the request',
    # 'You (assistant) are currently working in a Telegram bot. The Telegram bot automatically extracts text from any type of files sent to you by the user, such as documents, images, audio and video recordings (transcribation), etc., so that you can fully work with any files.',
    # "If the user's request cannot be fulfilled using the available tools or direct actions, the assistant(you) must treat the request as a request to generate text (e.g., providing code as text), not a request to perform an action (e.g., executing code or interacting with external systems not directly supported by tools) (intention mismatch).",
    # "If user ask you to run a program treat it as a request to generate text and not a request to actually run a program or perform an action.",
    # "To edit image user can send image with caption starting ! symbol. Don`t answer 'Image was edit successfully', it`s a system message, not your answer, you should answer <<EDIT IMAGE>> if user want to edit image.",
    # "Do not use line breaks and lists inside markdown tables.",
    # "To mark a list item use symbol `•` instead of `*`.",
    # "Anwser to user codeword <<EDIT IMAGE>> to indicate you understood this query was a request to edit image, don't add any other text.",
]


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
    timeout: int = my_gemini.TIMEOUT,
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


def trim_mem(mem: list, max_chat_mem_chars: int, clear: bool = False):
    """
    Обрезает историю диалога, если её объём превышает max_chat_mem_chars.
    Реализовано через поиск индекса, с которого нужно сохранить историю, 
    и последующую обрезку списка.
    clear = True - удалить сначала все Parts в которых не текст а вызов функций итп
    """
    if clear:
        mem = clear_non_text_parts(mem)
            
    total_chars = 0
    # Индекс, с которого мы будем сохранять историю.
    # Если вся история помещается в лимит, он останется равен 0.
    keep_from_index = 0

    # Идём с конца списка парами (user, model), чтобы найти точку отсечения.
    # `(len(mem) & ~1)` округляет длину списка до ближайшего чётного снизу,
    # чтобы безопасно брать пары.
    start_iter = (len(mem) & ~1) - 2
    for i in range(start_iter, -1, -2):
        pair_chars = 0
        # Считаем символы в паре сообщений
        for message in mem[i:i+2]:
            if hasattr(message, 'parts') and message.parts:
                for part in message.parts:
                    if hasattr(part, 'text') and part.text:
                        pair_chars += len(part.text)

        # Если накопленный размер + размер текущей пары превышает лимит...
        if total_chars + pair_chars > max_chat_mem_chars:
            # ...то эта пара уже не влезает. Значит, сохранять нужно
            # всё, что было *после* неё. Индекс начала следующей пары — i + 2.
            keep_from_index = i + 2
            break  # Точку отсечения нашли, выходим из цикла.

        # Если пара помещается, добавляем её размер к общему и продолжаем.
        total_chars += pair_chars

    # Если был найден индекс для обрезки (он будет больше 0),
    # то модифицируем список "на месте", оставляя только нужную часть.
    if keep_from_index > 0:
        mem[:] = mem[keep_from_index:]


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
    max_chat_lines: int = my_gemini.MAX_CHAT_LINES,
    max_chat_mem_chars: int = my_gemini.MAX_CHAT_MEM_CHARS,
    timeout: int = my_gemini.TIMEOUT,
    use_skills: bool = False,
    THINKING_BUDGET: int = -1,
    json_output: bool = False,
    do_not_update_history: bool = False,
    key__: str = '',
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

    Returns:
        A string containing the model's response, or an empty string if an error occurs or the response is empty.

    Raises:
        None: The function catches and logs exceptions internally, returning an empty string on failure.
    """
    try:
        # # лайв модель по другому работает но с той же памятью
        # if model in (my_gemini_live_text.DEFAULT_MODEL, my_gemini_live_text.FALLBACK_MODEL):
        #     if chat_id:
        #         mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_gemini3')) or []
        #         # Удаляем старые картинки, остается только последняя если она не была дольше чем 5 запросов назад
        #         remove_old_pics(mem)
        #         trim_mem(mem, max_chat_mem_chars, clear = True)
        #         # если на границе памяти находится вызов функции а не запрос юзера
        #         # то надо подрезать. начинаться должно с запроса юзера
        #         if mem and mem[0].role == 'user' and hasattr(mem[0].parts[0], 'text') and not mem[0].parts[0].text:
        #             mem = mem[2:]
        #         validate_mem(mem)
        #     else:
        #         mem = []
        #     if mem:
        #         my_db.set_user_property(chat_id, 'dialog_gemini3', my_db.obj_to_blob(mem))
        #     my_gemini_live_text.SYSTEM_ = SYSTEM_
        #     return my_gemini_live_text.get_resp(
        #         query,
        #         chat_id=chat_id,
        #         system=system,
        #         model=model,
        #         temperature=temperature,
        #         n_try=3,
        #         max_chat_lines=max_chat_lines
        #     )


        # if 'flash-lite' in model:
        #     THINKING_BUDGET = -1
        #     use_skills = False

        if 'gemma-3' in model:
            if temperature:
                temperature = temperature/2

        # not support thinking
        if 'gemini-2.0-flash' in model or 'gemma-3-27b-it' in model:
            THINKING_BUDGET = -1

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
        if do_not_update_history:
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
        if saved_file_name:
            my_skills.STORAGE_ALLOWED_IDS[chat_id] = chat_id
            system_.insert(1, f'Telegram user have saved file/files and assistant can query it: {saved_file_name} ({saved_file_size} chars)')
        if 'flash-lite' in model:
            system_.insert(1, 'You can draw graphs and charts using the code_execution_tool')

        if 'gemma-3-27b-it' in model:
            system_ = None

        for _ in range(3):
            response = None

            try:
                if key__:
                    key = key__
                else:
                    key = my_gemini.get_next_key()
                client = genai.Client(api_key=key, http_options={'timeout': timeout * 1000})
                if use_skills:
                    if 'flash-lite' in model:
                        code_execution_tool = Tool(code_execution={})
                        google_search_tool = Tool(google_search={})
                        SKILLS = [google_search_tool, code_execution_tool,]
                    elif 'gemma-3-27b-it' in model:
                        SKILLS = None
                    else:
                        SKILLS = [
                            my_skills.calc,
                            my_skills.search_google_fast,
                            my_skills.search_google_deep,
                            my_skills.download_text_from_url,
                            my_skills.get_time_in_timezone,
                            my_skills.get_weather,
                            my_skills.get_currency_rates,
                            my_skills.tts,
                            my_skills.speech_to_text,
                            my_skills.edit_image,
                            my_skills.translate_text,
                            my_skills.translate_documents,
                            # my_skills.compose_creative_text, # its too slow
                            my_skills.text_to_image,
                            my_skills.text_to_qrcode,
                            my_skills.save_to_txt,
                            my_skills.save_to_excel,
                            my_skills.save_to_docx,
                            my_skills.save_to_pdf,
                            my_skills.save_diagram_to_image,
                            my_skills.save_chart_and_graphs_to_image,
                            my_skills.save_html_to_image,
                            my_skills.query_user_file,
                            my_skills.get_location_name,
                            my_skills.help,
                        ]
                    chat = client.chats.create(
                        model=model,
                        config=get_config(
                            system_instruction=system_,
                            tools=SKILLS,
                            THINKING_BUDGET=THINKING_BUDGET,
                            json_output=json_output,
                        ),
                        history=mem,
                    )
                else:
                    chat = client.chats.create(
                        model=model,
                        config=get_config(
                            system_instruction=system_,
                            THINKING_BUDGET=THINKING_BUDGET,
                            json_output=json_output,
                        ),
                        history=mem,
                    )
                response = chat.send_message(query,)
            except Exception as error:
                
                if '429 RESOURCE_EXHAUSTED' in str(error):
                    my_log.log_gemini(f'my_gemini3:chat:2: {str(error)} {model} {key}')
                    return ''
                elif 'API key expired. Please renew the API key.' in str(error) or '429 Quota exceeded for quota metric' in str(error):
                    my_gemini.remove_key(key)
                elif 'timeout' in str(error).lower():
                    my_log.log_gemini(f'my_gemini3:chat:timeout: {str(error)} {model} {key}')
                    return ''
                elif """503 UNAVAILABLE. {'error': {'code': 503, 'message': 'The model is overloaded. Please try again later.', 'status': 'UNAVAILABLE'}}""" in str(error):
                    my_log.log_gemini(f'my_gemini3:chat:3: {str(error)} {model} {key}')
                    return ''
                elif """400 INVALID_ARGUMENT. {'error': {'code': 400, 'message': 'Please ensure that function response turn comes immediately after a function call turn.'""" in str(error):
                    my_log.log_gemini(f'my_gemini3:chat:4: {str(error)} {model} {key}')
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

                    # my_log.log_gemini(f'my_gemini:chat2:2:3__: mem: {mem}\n\nnew_mem: {new_mem}')
                    mem = new_mem # Переприсваиваем

                else:
                    raise error

            if response:
                resp = response.text or ''
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

            # если есть картинки то отправляем их через my_skills.STORAGE
            if resp_full and resp_full[0] and chat_id:
                for image in resp_full[0]:
                    item = {
                        'type': 'image/png file', # image['mime_type'],
                        'filename': image['filename'],
                        'data': image['data'],
                    }
                    with my_skills.STORAGE_LOCK:
                        if chat_id in my_skills.STORAGE:
                            if item not in my_skills.STORAGE[chat_id]:
                                my_skills.STORAGE[chat_id].append(item)
                        else:
                            my_skills.STORAGE[chat_id] = [item,]


            # плохие ответы
            ppp = [
                '```python\nprint(default_api.',
                '```tool_code\nprint(default_api.',
                '```json\n{\n  "tool_code":',
                '```python\nprint(telegram_bot_api.',
                '```\nprint(default_api.',
            ]
            if any(resp.startswith(p) for p in ppp):
                my_log.log_gemini(f'chat:bad resp: {resp}')
                return ''


            # флеш (и не только) иногда такие тексты в которых очень много повторов выдает,
            # куча пробелов, и возможно другие тоже. укорачиваем
            result_ = re.sub(r" {1000,}", " " * 10, resp) # очень много пробелов в ответе
            result_ = utils.shorten_all_repeats(result_)
            if len(result_)+100 < len(resp): # удалось сильно уменьшить
                resp = result_
                try:
                    chat._curated_history[-1].parts[-1].text = resp
                except Exception as error4:
                    my_log.log_gemini(f'my_gemini3:chat4: {error4}\nresult: {result}\nchat history: {str(chat_.history)}')


            history = chat.get_history()
            if history:
                history = history[-max_chat_lines*2:]
                my_db.set_user_property(chat_id, 'dialog_gemini3', my_db.obj_to_blob(history))
                if chat_id:
                    if not do_not_update_history:
                        my_db.add_msg(chat_id, model)

        return resp.strip()

    except Exception as error:
        traceback_error = traceback.format_exc()
        if """500 INTERNAL. {'error': {'code': 500, 'message': 'An internal error has occurred. Please retry or report in https://developers.generativeai.google/guide/troubleshooting', 'status': 'INTERNAL'}}""" in str(error) \
           or """503 UNAVAILABLE. {'error': {'code': 503, 'message': 'The service is currently unavailable.', 'status': 'UNAVAILABLE'}}""" in str(error):
            my_log.log_gemini(f'my_gemini3:chat:unknown_error:1: {error} {model}')
        else:
            my_log.log_gemini(f'my_gemini3:chat:unknown_error:2: {error}\n\n{traceback_error}\n{model}\nQuery: {str(query)[:1000]}')
        return ''
    finally:
        if chat_id in my_skills.STORAGE_ALLOWED_IDS:
            del my_skills.STORAGE_ALLOWED_IDS[chat_id]


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
        mem = my_gemini.get_mem_for_llama(chat_id, lines_amount=10)
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
    client = genai.Client(api_key=my_gemini.get_next_key(), http_options={'timeout': 20 * 1000})

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
        if key in my_gemini.REMOVED_KEYS:
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


if __name__ == "__main__":
    my_db.init(backup=False)
    my_gemini.load_users_keys()

    # один раз запустить надо
    # converts_all_mems()
    # print(list_models(include_context=True))

    reset('test')

    # chat_cli(model = 'gemini-2.5-flash-lite-preview-06-17', THINKING_BUDGET=10000, use_skills=True)
    # chat_cli(model = 'gemini-2.5-flash', THINKING_BUDGET=10000, use_skills=True)
    chat_cli(model = 'gemini-2.0-flash', THINKING_BUDGET=10000, use_skills=True)

    # with open(r'c:\Users\user\Downloads\samples for ai\myachev_Significant_Digits_-_znachaschie_tsifryi_106746.txt', 'r', encoding='utf-8') as f:
    #     t = f.read()
    # q = f'Составь оглавление книги из текста:\n\n\n{t}'
    # print(chat(q, 'test', model = 'gemini-2.5-flash-lite-preview-06-17', system='отвечай всегда по-русски'))
    # print(len(q))
    # print(chat(q, 'test', model = 'gemini-2.5-flash-preview-05-20', system='отвечай всегда по-русски'))


    my_db.close()
