import cachetools.func
import datetime
import io
import pytz
import re
import requests
import traceback

import pandas as pd
from geopy.geocoders import Nominatim

import cfg
import my_qrcode_generate
import my_log
import my_mermaid
import my_pandoc
import my_plantweb
import my_skills_storage
import my_svg
import utils


def restore_id(chat_id: str) -> str:
    '''
    Restore user id from string (they often miss brackets and add some crap)

    Args:
        chat_id: str
    Returns:
        chat_id in format '[number1] [number2]'
    '''
    def is_integer(s):
        try:
            int(s)
            return True
        except ValueError:
            return False

    pattern = r'^\[-?\d+\] \[\d+\]$'
    if re.fullmatch(pattern, chat_id):
        return chat_id

    # remove all symbols except numbers, minus and brackets
    chat_id = re.sub(r'[^0-9\-]', ' ', chat_id)
    chat_id = re.sub(r'\s+', ' ', chat_id).strip()

    # chat_id может приехать в виде одного числа - надо проверять и переделывать, добавлять скобки и число
    if is_integer(chat_id):
        chat_id = f"[{chat_id}] [0]"
    # если нет второго числа до добавить '[0]'
    if chat_id.count('[') == 1:
        chat_id = f"{chat_id} [0]"

    chat_id = chat_id.strip()
    if not chat_id:
        chat_id = '[unknown]'
    return chat_id


def decode_string(s: str) -> str:
    if isinstance(s, str) and s.count('\\') > 2:
        try:
            s = s.replace('\\\\', '\\')
            s = str(bytes(s, "utf-8").decode("unicode_escape").encode("latin1").decode("utf-8"))
            return s
        except Exception as error:
            my_log.log_gemini_skills(f'Error: {error}')
            return s
    else:
        return s


def save_diagram_to_image(filename: str, text: str, engine: str, chat_id: str) -> str:
    '''
    Send a diagram as an image file to the user, rendered from various text formats.
    Args:
        filename: str - The desired file name for the image file (e.g., 'diagram').
        text: str - The diagram definition text in Mermaid, PlantUML, Graphviz (DOT), or Ditaa format.
                     **Important considerations for 'text' parameter:**
                     - The input must strictly adhere to the syntax of the specified 'engine'.
                     - For PlantUML, syntax like `class` or `activity` is expected.
                     - For Graphviz, DOT language syntax is required.
                     - For Ditaa, ASCII art syntax with specific tags is used.
                     - `skinparam` or similar engine-specific options within the text
                       directly control the visual style and rendering of the diagram.
        engine: str - The diagram rendering engine to use: 'mermaid', 'plantuml', 'graphviz', or 'ditaa'.
        chat_id: str - The Telegram user chat ID where the file should be sent.
    Returns:
        str: 'OK' if the file was successfully prepared for sending, or a detailed 'FAIL' message otherwise.
    '''

    try:
        my_log.log_gemini_skills_save_docs(f'save_diagram_to_image {chat_id}\n\n{filename}\n{text}\nEngine: {engine}')

        chat_id = restore_id(chat_id)
        if chat_id == '[unknown]':
            return "FAIL, unknown chat id"

        # Ensure filename has .png extension and is safe
        if not filename.lower().endswith('.png'):
            filename += '.png'
        filename = utils.safe_fname(filename)

        # Validate the 'engine' parameter to prevent unsupported values from reaching text_to_image
        supported_engines = {'plantuml', 'graphviz', 'ditaa', 'mermaid'}
        if engine not in supported_engines:
            return f"FAIL: Unsupported diagram engine '{engine}'. Supported engines are: {', '.join(supported_engines)}."

        # Convert the diagram text to image bytes using the text_to_image function
        try:
            if engine == 'mermaid':
                png_output = my_mermaid.generate_mermaid_png_bytes(text)
            else:
                png_output = my_plantweb.text_to_png(text, engine=engine, format='png')
        except Exception as rendering_error:
            my_log.log_gemini_skills_save_docs(f'save_diagram_to_image: Error rendering diagram: {rendering_error}\n\n{traceback.format_exc()}')
            return f"FAIL: Error during diagram rendering: {rendering_error}"

        # Check the type of png_output to determine success or failure
        if isinstance(png_output, bytes):
            # If bytes were successfully generated, prepare the item for storage
            item = {
                'type': 'image/png file',
                'filename': filename,
                'data': png_output,
            }
            with my_skills_storage.STORAGE_LOCK:
                if chat_id in my_skills_storage.STORAGE:
                    if item not in my_skills_storage.STORAGE[chat_id]:
                        my_skills_storage.STORAGE[chat_id].append(item)
                else:
                    my_skills_storage.STORAGE[chat_id] = [item,]

            return "OK"

        elif isinstance(png_output, str):
            # If a string is returned, it indicates an error message from text_to_image
            my_log.log_gemini_skills_save_docs(f'save_diagram_to_image: No image data could be generated for chat {chat_id} - {png_output}\n\nText length: {len(text)}')
            return f"FAIL: No image data could be generated: {png_output}"
        else:
            # Unexpected return type
            my_log.log_gemini_skills_save_docs(f'save_diagram_to_image: Unexpected return type from text_to_image for chat {chat_id}\n\nText length: {len(text)}')
            return "FAIL: An unexpected error occurred during image generation."

    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_gemini_skills_save_docs(f'save_diagram_to_image: Unexpected error: {error}\n\n{traceback_error}\n\nText length: {len(text)}\n\n{chat_id}')
        return f"FAIL: An unexpected error occurred: {error}"


def save_to_txt(filename: str, text: str, chat_id: str) -> str:
    '''
    Send a plain text file to the user, you can use it to send markdown etc as a plaintext too.
    Args:
        filename: str - The desired file name for the text file (e.g., 'notes').
        text: str - The plain text content to save.
        chat_id: str - The Telegram user chat ID where the file should be sent.
    Returns:
        str: 'OK' if the file was successfully prepared for sending, or a detailed 'FAIL' message otherwise.
    '''
    try:
        my_log.log_gemini_skills_save_docs(f'save_to_txt {chat_id}\n\n{filename}\n{text}')

        chat_id = restore_id(chat_id)
        if chat_id == '[unknown]':
            return "FAIL, unknown chat id"

        # Ensure filename has .txt extension and is safe
        if '.' not in filename:
            filename += '.txt'
        filename = utils.safe_fname(filename)

        # Encode the text to bytes
        text_bytes = text.encode('utf-8')

        # If bytes were successfully generated, prepare the item for storage
        if text_bytes:
            item = {
                'type': 'text file',
                'filename': filename,
                'data': text_bytes,
            }
            with my_skills_storage.STORAGE_LOCK:
                if chat_id in my_skills_storage.STORAGE:
                    if item not in my_skills_storage.STORAGE[chat_id]:
                        my_skills_storage.STORAGE[chat_id].append(item)
                else:
                    my_skills_storage.STORAGE[chat_id] = [item,]
            return "OK"
        else:
            my_log.log_gemini_skills_save_docs(f'save_to_txt: No text data could be generated for chat {chat_id}\n\nText length: {len(text)}')
            return "FAIL: No text data could be generated."

    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_gemini_skills_save_docs(f'save_to_txt: Unexpected error: {error}\n\n{traceback_error}\n\nText length: {len(text)}\n\n{chat_id}')
        return f"FAIL: An unexpected error occurred: {error}"


def save_to_docx(filename: str, text: str, chat_id: str) -> str:
    r'''
    Send DOCX file to user, converted from markdown text(~~ for strikethrough).

    Args:
        filename: str - The desired file name for the DOCX file (e.g., 'document').
        text: str - The markdown formatted text to convert to DOCX.
                    To include mathematical equations, use LaTeX syntax enclosed in dollar signs:
                    - For inline formulas, use $...$ (e.g., `$a^2 + b^2 = c^2$`).
                    - For display formulas on a new line, use $$...$$ 
                      (e.g., `$$x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}$$`).
        chat_id: str - The Telegram user chat ID where the file should be sent.

    Returns:
        str: 'OK' if the file was successfully prepared for sending, or a detailed 'FAIL' message otherwise.
    '''
    try:
        my_log.log_gemini_skills_save_docs(f'save_to_docx {chat_id}\n\n{filename}\n{text}')

        chat_id = restore_id(chat_id)
        if chat_id == '[unknown]':
            return "FAIL, unknown chat id"

        # Ensure filename has .docx extension and is safe
        if not filename.lower().endswith('.docx'):
            filename += '.docx'
        filename = utils.safe_fname(filename)

        # Convert the markdown text to DOCX bytes using the provided function
        docx_bytes = my_pandoc.convert_markdown_to_document(text, 'docx')
        if isinstance(docx_bytes, str):
            # If a string is returned, it indicates an error message from convert_markdown_to_document
            my_log.log_gemini_skills_save_docs(f'save_to_docx: No DOCX data could be generated for chat {chat_id} - {docx_bytes}')
            return f"FAIL: No DOCX data could be generated: {docx_bytes}"

        # If bytes were successfully generated, prepare the item for storage
        if docx_bytes:
            item = {
                'type': 'docx file',
                'filename': filename,
                'data': docx_bytes,
            }
            with my_skills_storage.STORAGE_LOCK:
                if chat_id in my_skills_storage.STORAGE:
                    if item not in my_skills_storage.STORAGE[chat_id]:
                        my_skills_storage.STORAGE[chat_id].append(item)
                else:
                    my_skills_storage.STORAGE[chat_id] = [item,]
            return "OK"
        else:
            # This case indicates that no DOCX data was generated.
            my_log.log_gemini_skills_save_docs(f'save_to_docx: No DOCX data could be generated for chat {chat_id}\n\nText length: {len(text)}')
            return "FAIL: No DOCX data could be generated."

    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_gemini_skills_save_docs(f'save_to_docx: Unexpected error: {error}\n\n{traceback_error}\n\nText length: {len(text)}\n\n{chat_id}')
        return f"FAIL: An unexpected error occurred: {error}"


def save_to_excel(filename: str, data: dict, chat_id: str) -> str:
    '''
    Send excel file to user. Supports multiple sheets, auto-adjusting column widths, and formulas.

    Args:
        filename (str): The desired file name for the Excel file (e.g., 'report').

        data (dict): A ordered dictionary where keys are sheet names (str) and values are dictionaries
                     defining the content of each sheet, KEEP THE ORDER OF SHEETS IN THE DICTIONARY.

                     To specify formulas, each sheet's dictionary should contain two keys:
                     - 'data': A dictionary that can be converted to a pandas DataFrame.
                     - 'formulas': A list of dictionaries, where each item specifies a formula.
                       - 'cell' (str): The cell to place the formula in (e.g., 'C2').
                       - 'formula' (str): The Excel formula string (e.g., '=A2*B2').

                     Example with formulas:
                     {
                         'Sales': {
                             'data': {
                                 'Product': ['Laptop', 'Mouse'],
                                 'Quantity': [10, 50],
                                 'Price': [1200, 25],
                                 'Total': [0, 0]  # Placeholder for formula results
                             },
                             'formulas': [
                                 {'cell': 'D2', 'formula': '=B2*C2'},
                                 {'cell': 'D3', 'formula': '=B3*C3'},
                                 {'cell': 'B5', 'formula': "='Total Quantity:'"},
                                 {'cell': 'C5', 'formula': '=SUM(B2:B3)'}
                             ]
                         },
                         'Sheet2': { # Example of a sheet without formulas (old format)
                            'Product':['Keyboard', 'Monitor'], 'Price':[50, 300]
                         }
                     }

        chat_id (str): The Telegram user chat ID where the file should be sent.

    Returns:
        str: 'OK' if the file was successfully prepared, or a 'FAIL' message otherwise.
    '''
    try:
        my_log.log_gemini_skills_save_docs(f'save_to_excel {chat_id}\n\n {data}')

        chat_id = restore_id(chat_id)
        if chat_id == '[unknown]':
            return "FAIL, unknown chat id"

        if not filename.lower().endswith('.xlsx'):
            filename += '.xlsx'
        filename = utils.safe_fname(filename)

        excel_buffer = io.BytesIO()

        with pd.ExcelWriter(excel_buffer, engine='xlsxwriter') as writer:
            if not data:
                pd.DataFrame({}).to_excel(writer, sheet_name="Sheet1", index=False)
            else:
                for sheet_name, sheet_content in data.items():
                    # --- Определяем данные и формулы ---
                    # Проверяем, используется ли новый формат с ключами 'data' и 'formulas'
                    if isinstance(sheet_content, dict) and 'data' in sheet_content:
                        sheet_data_dict = sheet_content['data']
                        formulas_to_apply = sheet_content.get('formulas', [])
                    else:
                        # Обратная совместимость: если формат старый, формул нет
                        sheet_data_dict = sheet_content
                        formulas_to_apply = []

                    if not isinstance(sheet_data_dict, dict):
                        return f"FAIL: Invalid data for sheet '{sheet_name}'. Expected a dictionary for sheet content."

                    try:
                        # 1. Заливаем основные данные через pandas
                        df = pd.DataFrame(sheet_data_dict)
                        df.to_excel(writer, sheet_name=sheet_name, index=False)

                        # 2. Настраиваем ширину столбцов
                        worksheet = writer.sheets[sheet_name]
                        for idx, col in enumerate(df):
                            series = df[col]
                            max_len = max(
                                series.astype(str).map(len).max(),
                                len(str(series.name))
                            ) + 1
                            worksheet.set_column(idx, idx, max_len)

                        # 3. Вставляем формулы, если они есть
                        if formulas_to_apply:
                            for item in formulas_to_apply:
                                if isinstance(item, dict) and 'cell' in item and 'formula' in item:
                                    worksheet.write_formula(item['cell'], item['formula'])
                                else:
                                    # Можно логировать ошибку, если формат формулы неверный
                                    my_log.log_gemini_skills_save_docs(f'save_to_excel: Invalid formula item for sheet "{sheet_name}": {item}')

                    except Exception as sheet_write_error:
                        my_log.log_gemini_skills_save_docs(f'save_to_excel: Error writing sheet "{sheet_name}": {sheet_write_error}\n\n{traceback.format_exc()}')
                        return f"FAIL: Error writing data to sheet '{sheet_name}': {sheet_write_error}"

        excel_bytes = excel_buffer.getvalue()

        if excel_bytes:
            item = {'type': 'excel file', 'filename': filename, 'data': excel_bytes}
            with my_skills_storage.STORAGE_LOCK:
                if chat_id in my_skills_storage.STORAGE:
                    if item not in my_skills_storage.STORAGE[chat_id]:
                        my_skills_storage.STORAGE[chat_id].append(item)
                else:
                    my_skills_storage.STORAGE[chat_id] = [item,]
            return "OK"
        else:
            my_log.log_gemini_skills_save_docs(f'save_to_excel: No Excel data could be generated for chat {chat_id}\n\n{data}')
            return "FAIL: No Excel data could be generated."

    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_gemini_skills_save_docs(f'save_to_excel: Unexpected error: {error}\n\n{traceback_error}\n\n{data}\n\n{chat_id}')
        return f"FAIL: An unexpected error occurred: {error}"


def save_to_pdf(filename: str, text: str, chat_id: str) -> str:
    """
    Send PDF file to user, converted from markdown text(~~ for strikethrough).

    Args:
        filename: str - The desired file name for the PDF file (e.g., 'document').
        text: str - The markdown formatted text to convert to PDF.
        chat_id: str - The Telegram user chat ID where the file should be sent.

    Returns:
        str: 'OK' if the file was successfully sent, or a detailed 'FAIL' message otherwise.
    """
    try:
        # Log the function call for debugging/monitoring purposes
        my_log.log_gemini_skills_save_docs(f'save_to_pdf {chat_id}\n\n{filename}\n{text}')

        # Restore the actual chat ID
        chat_id = restore_id(chat_id)
        if chat_id == '[unknown]':
            return "FAIL, unknown chat id"

        # Ensure filename has .pdf extension and is safe for file system operations
        if not filename.lower().endswith('.pdf'):
            filename += '.pdf'
        filename = utils.safe_fname(filename)

        # Convert the markdown text to PDF bytes using the underlying utility
        pdf_bytes = None

        data = my_pandoc.convert_markdown_to_document(text, 'pdf')
        if isinstance(data, str):
            my_log.log_gemini_skills_save_docs(f'save_to_pdf: Error converting text to PDF: {data}')
            return data

        pdf_bytes = io.BytesIO(data).getvalue()

        # If PDF bytes were successfully generated, prepare the item for storage
        if pdf_bytes:
            item = {
                'type': 'pdf file', # Define the type for the stored item
                'filename': filename,
                'data': pdf_bytes,
            }
            # Use a global storage mechanism with a lock to ensure thread safety
            with my_skills_storage.STORAGE_LOCK:
                if chat_id in my_skills_storage.STORAGE:
                    if item not in my_skills_storage.STORAGE[chat_id]: # Avoid duplicate entries if necessary
                        my_skills_storage.STORAGE[chat_id].append(item)
                else:
                    my_skills_storage.STORAGE[chat_id] = [item,]
            return "OK"
        else:
            # This case indicates that no PDF data was generated, even after attempting conversion.
            my_log.log_gemini_skills_save_docs(f'save_to_pdf: No PDF data could be generated for chat {chat_id}\n\nText length: {len(text)}')
            return "FAIL: No PDF data could be generated."

    except Exception as error:
        # Catch any unexpected errors that occur during the function's execution
        traceback_error = traceback.format_exc()
        my_log.log_gemini_skills_save_docs(f'save_to_pdf: Unexpected error: {error}\n\n{traceback_error}\n\nText length: {len(text)}\n\n{chat_id}')
        return f"FAIL: An unexpected error occurred: {error}"


@cachetools.func.ttl_cache(maxsize=10, ttl=60*60)
def get_weather(location: str) -> str:
    '''Get weather data from OpenMeteo API 7 days forth and back
    Example: get_weather("Vladivostok")
    Return json string
    '''
    try:
        location = decode_string(location)
        my_log.log_gemini_skills(f'Weather: {location}')
        lat, lon = get_coords(location)
        if not any([lat, lon]):
            return 'error getting data'
        my_log.log_gemini_skills(f'Weather: {lat} {lon}')
        # Make sure all required weather variables are listed here
        # The order of variables in hourly or daily is important to assign them correctly below
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,rain,showers,snowfall,weather_code,cloud_cover,pressure_msl,surface_pressure,wind_speed_10m,wind_direction_10m,wind_gusts_10m&daily=weather_code,temperature_2m_max,temperature_2m_min,apparent_temperature_max,apparent_temperature_min,sunrise,sunset,daylight_duration,sunshine_duration,uv_index_max,uv_index_clear_sky_max,precipitation_sum,rain_sum,showers_sum,snowfall_sum,precipitation_hours,precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max,wind_direction_10m_dominant,shortwave_radiation_sum,et0_fao_evapotranspiration&past_days=7"
        responses = requests.get(url, timeout = 20)
        my_log.log_gemini_skills(f'Weather: {responses.text[:100]}')
        return responses.text
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_gemini_skills(f'get_weather:Error: {error}\n\n{traceback_error}')
        return f'ERROR {error}'


@cachetools.func.ttl_cache(maxsize=10, ttl=60*60)
def get_coords(loc: str):
    '''Get coordinates from Nominatim API
    Example: get_coords("Vladivostok")
    Return tuple (latitude, longitude)
    '''
    geolocator = Nominatim(user_agent="kun4sun_bot")
    location = geolocator.geocode(loc)
    if location:
        return round(location.latitude, 2), round(location.longitude, 2)
    else:
        return None, None


@cachetools.func.ttl_cache(maxsize=10, ttl=60*60)
def get_location_name(latitude: str, longitude: str, language: str) -> str:
    """
    Retrieves the human-readable name of a location based on its coordinates.

    Args:
        latitude (str): The latitude of the location as a string.
        longitude (str): The longitude of the location as a string.
        language (str): The language code for the returned location name (e.g., 'en', 'ru').

    Returns:
        str: A string representing the location's name, 'Not found' if no location
            is found for the given coordinates, or an error message if an exception occurs.
    """
    try:
        geolocator = Nominatim(user_agent="kun4sun_bot")
        location = geolocator.reverse(
            latitude + "," + longitude,
            language=language,
            addressdetails=True,
            namedetails=True
        )
    except Exception as e:
        my_log.log_gemini_skills(f'get_location_name:Error: {e}')
        return f'Error: {e}'

    if location:
        return str(location)
    else:
        return 'Not found'


def get_time_in_timezone(timezone_str: str) -> str:
    """
    Returns the current time in the specified timezone.

    Args:
        timezone_str: A string representing the timezone (e.g., "Europe/Moscow", "America/New_York").

    Returns:
        A string with the current time in "YYYY-MM-DD HH:MM:SS" format, or an error message if the timezone is invalid.
    """
    try:
        timezone = pytz.timezone(timezone_str)
        now = datetime.datetime.now(timezone)
        time_str = now.strftime("%Y-%m-%d %H:%M:%S")
        my_log.log_gemini_skills(f'get_time_in_timezone: timezone_str={timezone_str} time={time_str}')
        return now.strftime("%Y-%m-%d %H:%M:%S")
    except Exception as error:
        my_log.log_gemini_skills(f'get_time_in_timezone: Invalid timezone {timezone_str}\n{error}')
        return f"Error: Invalid timezone '{timezone_str}'"


def tts(user_id: str) -> str:
    '''
    Generate and send audio message from text to user.
    Use it only if asked by user to generate audio from text.
    To change voice user can use `/config` command
    Args:
        text: str - text to say (up to 8000 symbols)
        lang: str - language code, default is 'ru'
        rate: str - speed rate, +-100%, default is '+0%'
    '''
    user_id = restore_id(user_id)
    my_log.log_gemini_skills(f'/tts {user_id}')
    return "When generating an audio message for the user, your output must be exclusively the /tts command in the format /tts [lang ru en etc] [speed +-100%] [text], with absolutely no preceding or additional explanatory text, because this exact message is directly processed by the external audio generation system for delivery to the user. For example: /tts en +50% Hello, how are you? Do NOT respond with text like 'Here is your audio: /tts en +50% Hello, how are you?' as this will fail. User can change voices with `/config` command."


def speech_to_text(user_id: str) -> str:
    '''
    Transcribe audio message from telegram user.

    Args:
        user_id: str - telegram user id
    '''
    user_id = restore_id(user_id)
    my_log.log_gemini_skills(f'/stt {user_id}')
    return "The function itself does not return an transcribed text. It returns a string containing instructions for the assistant. Any audio-video files send by user to telegram bot will be transcribed automatically and assistant can work with this text."


def translate_text(user_id: str) -> str:
    '''
    Translate text to another language.

    Args:
        user_id: str - telegram user id
    '''
    user_id = restore_id(user_id)
    my_log.log_gemini_skills(f'/translate_text {user_id}')
    return "The function itself does not return an translated text. It returns a string containing instructions for the assistant. There are no tools for text translation, assistant have to translate all text by itself, as if he is a professional translator, using synonyms and context for better translation."


def translate_documents(user_id: str) -> str:
    '''
    Translate documents to another language.

    Args:
        user_id: str - telegram user id
    '''
    user_id = restore_id(user_id)
    my_log.log_gemini_skills(f'/translate_documents {user_id}')
    return "The function itself does not return an translated text. It returns a string containing instructions for the assistant. If user send document to telegram bot with caption like `!tr lang` it will translated automatically. Any documents send by user to telegram bot will by converted to markdown text for assistant."


def edit_image(user_id: str) -> str:
    '''
    Edit images.

    Args:
        user_id: str - telegram user id
    '''
    user_id = restore_id(user_id)
    my_log.log_gemini_skills_img(f'/edit_image {user_id}')
    return "The function itself does not return an edited image. It returns a string containing instructions for the assistant. Answer to user codeword <<EDIT IMAGE>> to indicate you understood this query was a request to edit image, dont add any other text."


def text_to_image(prompt: str) -> str:
    '''
    Generate and send image message from text to user.
    Use it only if asked by user to generate image from text.
    Avoid using text_to_image for precise mathematical expressions, structured diagrams,
    or data-driven charts; instead, use save_diagram_to_image or save_chart_and_graphs_to_image
    for those specific tasks. Use save_html_to_image for drawing mostly textual content.

    Args:
        prompt: str - text to generate image from

    '''
    my_log.log_gemini_skills_img(f'/img "{prompt}"')
    return (
        "The function itself does not return an image. It returns a string containing "
        "instructions for the assistant. The assistant must send a new message, starting "
        "with the /img command, followed by a space, and then the prompt provided, up to "
        "100 words. This specific message format will be automatically recognized by an "
        "external system as a request to generate and send an image to the user. "
        "You can also use the commands /flux <prompt> and /gem <1-4> <prompt> and /bing <prompt> for image generation. "
        "Flux draws one picture using the flux-dev model, gem draws several pictures using the Gemini model, "
        "bing draws 1-4 pictures using the DALL·E 3 model. /img draws 4 pictures with Bing + 2 with Gemini, "
        "and if none could be drawn, it tries to draw one with Flux. Gemini is the only one that "
        "can properly draw text and celebrities, Flux is the most uninhibited and accurate. Bing is the best but most restricted."
    )


def text_to_qrcode(text: str, logo_url: str, user_id: str) -> str:
    '''
    Send qrcode message to telegram user.

    Args:
        text: str - text to generate qrcode from
        logo_url: str - url to logo image, use 'DEFAULT' or empty string for default logo, any image including svg is supported.
        user_id: str - user id
    Returns:
        str: 'OK' or error message
    '''
    try:
        my_log.log_gemini_skills_img(f'/qrcode "{text}" "{logo_url}" "{user_id}"')

        user_id = restore_id(user_id)

        if logo_url != 'DEFAULT' and logo_url:
            logo_data = utils.download_image_as_bytes(logo_url)
            if logo_url.lower().endswith('.svg'):
                logo_data = my_svg.convert_svg_to_png_bytes(logo_data)
            if not logo_data:
                return "Failed to download logo image."
        elif logo_url == 'DEFAULT':
            logo_data = './pics/photo_2023-07-10_01-36-39.jpg'
        else:
            logo_data = ''

        png_bytes = my_qrcode_generate.generate_qr_with_logo_bytes(text, logo_data)
        if isinstance(png_bytes, str):
            return png_bytes

        if isinstance(png_bytes, bytes) and len(png_bytes) > 0:
            item = {
                'type': 'image/png file',
                'filename': 'https://t.me/kun4sun_bot',
                'data': png_bytes,
            }
            with my_skills_storage.STORAGE_LOCK:
                if user_id in my_skills_storage.STORAGE:
                    if item not in my_skills_storage.STORAGE[user_id]:
                        my_skills_storage.STORAGE[user_id].append(item)
                else:
                    my_skills_storage.STORAGE[user_id] = [item,]
            return "OK"

    except Exception as e:
        my_log.log_gemini_skills_img(f'my_skills.py:text_to_qrcode - Failed to generate qrcode: {e}')

    return "Failed to generate qrcode."


def help(user_id: str) -> str:
    '''
    Return help info about you (assistant and telegram bot) skills and abilities.
    Use it if user ask what he can do here or what you can do for him.
    '''
    user_id = restore_id(user_id)

    my_log.log_gemini_skills(f'help {user_id}')

    bot_name = f'@{cfg._BOT_NAME}' if hasattr(cfg, '_BOT_NAME') and cfg._BOT_NAME else '@kun4sun_bot'

    help_msg = f'''Эту информацию не следует выдавать юзеру без его явного запроса, особенно всю сразу, люди не любят читать длинные тесты.

Ты(ассистент) общаешься в телеграм чате с юзером, с точки зрения юзера ты телеграм бот по имени ЧатБот {bot_name}.
В разных локализациях имя ЧатБот и описание в телеграме может быть другим (используется автоперевод на все языки).

По команде /start юзер видит следующее сообщение:

----------------
Здравствуйте, я чат-бот с искусственным интеллектом. Я здесь, чтобы помочь вам во всем, что вам нужно.

✨ Доступ ко всем текстовым ИИ
🎨 Рисование и редактирование изображений
🗣 Распознавание голоса и создание субтитров
🖼 Ответы на вопросы об изображениях
🌐 Поиск в Интернете с использованием ИИ
🔊 Генерация речи
📝 Перевод документов
📚 Суммирование длинных текстов и видео
🎧 Загрузка аудио с YouTube

Спрашивайте меня о чем угодно. Отправляйте мне свой текст/изображение/аудио/документы с вопросами.
Создавайте изображения с помощью команды /img.

Измените язык с помощью команды /lang.
Удалите клавиатуру с помощью /remove_keyboard.
----------------

У этого телеграм бота (то есть у тебя, у ассистента) есть команды набираемые в чате начинающиеся с /:

/reset - Стереть текущий диалог и начать разговор заново
/help - Справка
/config - Меню настроек, там можно изменить параметры,
    выбрать llm модель gemini|mistral|llama|ChatGPT|Cohere|Deepseek|Openrouter,
    выбрать голос озвучки TTS - Microsoft Edge|Google|Gemini|OpenAI,
    включить только голосовой режим что бы твои ответы доходили до юзера только голосом с помощью TTS (🗣️),
    вкл/выкл кнопки под твоими ответами, кнопки там обычно такие:
        ➡️ (Right Arrow): Prompts the bot to continue the conversation or generate the next response.
        ♻️ (Circular Arrows): Clears the bot's memory and starts a new conversation.
        🙈 (Hands Covering Eyes): Hides or deletes the current message or response.
        📢 (Megaphone): Plays the text aloud using Text-to-Speech (TTS).
        📸 (Camera): Displays Google Images search results based on your request.
        🎤 (Microphone): Selects the voice AI engine for speech recognition. If Whisper (or another engine) doesn't understand your voice well, you can choose a different one.
    изменить тип уведомлений об активности - стандартный для телеграма и альтернативный (🔔),
    вкл/выкл режим при котором все голосовые сообщения только транскрибируются без дальнейшей обработки (📝),
    вкл/выкл отображение ответов, твои сообщения будут выглядеть как просто сообщения а не ответы на сообщения юзера (↩️),
    вкл/выкл автоматические ответы в публичном чате - это нужно для того что бы бот воспринимал комнату в чате как приватный разговор и отвечал на все запросы в чате а не только те которые начинаются с его имени (🤖),
    можно выбрать движок для распознавания голоса если дефолтный плохо понимает речь юзера - whisper|gemini|google|AssemblyAI|Deepgram,
/lang - Меняет язык локализации, автоопределение по умолчанию
/memo - Запомнить пожелание
/style - Стиль ответов, роль
/undo - Стереть только последний запрос
/force - Изменить последний ответ бота
/name - Меняет кодовое слово для обращения к боту (только русские и английские буквы и цифры после букв, не больше 10 всего) это нужно только в публичных чатах что бы бот понимал что обращаются к нему
/sum - пересказать содержание ссылки, кратко
/sum2 - То же что и /sum но не берет ответы из кеша, повторяет запрос заново
/calc - Численное решение математических задач
/transcribe - Сделать субтитры из аудио
/ytb - Скачать аудио с ютуба
/temperature - Уровень креатива llm от 0 до 2
/mem - Показывает содержимое своей памяти, диалога
/save - Сохранить диалог в формате msoffice и маркдаун. если отправить боту такой маркдаун с подписью load то бот загрузит диалог из него
/purge - Удалить мои логи
/openrouter - Выбрать модель от openrouter.ai особая команда для настройки openrouter.ai
/id - показывает телеграм id чата/привата то есть юзера
/remove_keyboard - удалить клавиатуру под сообщениями
/keys - вставить свои API ключи в бота (бот может использовать API ключи юзера)
/stars - donate telegram stars. после триального периода бот работает если юзер принес свои ключи или дал звезды телеграма (криптовалюта такая в телеграме)
/report - сообщить о проблеме с ботом
/trans <text to translate> - сделать запрос к внешним сервисам на перевод текста
/google <search query> - сделать запрос к внешним сервисам на поиск в гугле (используются разные движки, google тут просто синоним поиска)

Команды которые может использовать и юзер и сам ассистент по своему желанию:
/img <image description prompt> - сделать запрос к внешним сервисам на рисование картинок
    эта команда генерирует несколько изображений сразу всеми доступными методами но можно и конкретизировать запрос
        /bing <prompt> - будет рисовать только с помощью Bing image creator
        /flux <prompt> - будет рисовать только с помощью Flux
        /gem <1-4> <prompt> - будет рисовать только с помощью Gemini
/tts <text to say> - сделать запрос к внешним сервисам на голосовое сообщение. Юзер может поменять голос в настройках `/command`

Если юзер отправляет боту картинку с подписью то подпись анализируется и либо это воспринимается на запрос на редактирование картинки либо как на ответ по картинке, то есть бот может редактировать картинки, для форсирования этой функции надо в начале подписи использовать восклицательный знак.

Если юзер отправляет в телеграм бота картинки, голосовые сообщения, аудио и видеозаписи, любые документы и файлы то бот переделывает всё это в текст что бы ты (ассистент) мог с ними работать как с текстом.

В боте есть функция перевода документов, чот бы перевести документ юзеру надо отправить документ с подписью !tr <lang> например !lang ru для перевода на русский

Если юзер отправит ссылку или текстовый файл в личном сообщении, бот попытается извлечь и предоставить краткое содержание контента.
После загрузки файла или ссылки можно будет задавать вопросы о файле, используя команду /ask или знак вопроса в начале строки
Результаты поиска в гугле тоже сохранятся как файл.

Если юзер отправит картинку без подписи(инструкции что делать с картинкой) то ему будет предложено меню с кнопками
    Дать описание того что на картинке
    Извлечь весь текст с картинки используя llm
    Извлечь текст и зачитать его вслух
    Извлечь текст и написать художественный перевод
    Извлечь текст не используя llm с помощью ocr
    Сделать промпт для генерации такого же изображения
    Решить задачи с картинки
    Прочитать куаркод
    Повторить предыдущий запрос набранный юзером (если юзер отправил картинку без подписи и потом написал что с ней делать то это будет запомнено)

У бота есть ограничения на размер передаваемых файлов, ему можно отправить до 20мб а он может отправить юзеру до 50мб.
Для транскрибации более крупных аудио и видеофайлов есть команда /transcribe с отдельным загрузчиком файлов.

Бот может работать в группах, там его надо активировать командой /enable@<bot_name> а для этого сначала вставить
свои API ключи в приватной беседе командой /keys.
В группе есть 2 режима работы, как один из участников чата - к боту надо обращаться по имени, или как
симуляции привата, бот будет отвечать на все сообщения отправленные юзером в группу.
Второй режим нужен что бы в телеграме иметь опыт использования похожий на оригинальный сайт чатгпт,
юзеру надо создать свою группу, включить в ней темы (threads) и в каждой теме включить через настройки
/config режим автоответов, и тогда это всё будет выглядеть и работать как оригинальный сайт чатгпт с вкладками-темами
в каждой из которых будут свои отдельные беседы и настройки бота.

Группа поддержки в телеграме: https://t.me/kun4_sun_bot_support
Веб сайт с открытым исходным кодом для желающих запустить свою версию бота: https://github.com/theurs/tb1
'''

    return help_msg


if __name__ == '__main__':
    pass
