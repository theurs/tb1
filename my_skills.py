#!/usr/bin/env python3
# pip install -U simpleeval


import cachetools.func
import datetime
import decimal
import io
import math
import mpmath
import numbers
import numpy
import numpy as np
import os
import pytz
import random
import re
import requests
import subprocess
import time
import threading
import traceback

import matplotlib.pyplot as plt
import pandas as pd
from simpleeval import simple_eval
from typing import Callable, List, Optional, Tuple, Union

# it will import word random and broke code
# from random import *
#from random import betavariate, choice, choices, expovariate, gammavariate, gauss, getrandbits, getstate, lognormvariate, normalvariate, paretovariate, randbytes, randint, randrange, sample, seed, setstate, shuffle, triangular, uniform, vonmisesvariate, weibullvariate

from geopy.geocoders import Nominatim

import cfg
import my_db
import my_google
import my_gemini_google
import my_github
import my_groq
import my_log
import my_md_tables_to_png
import my_mermaid
import my_pandoc
import my_plantweb
# import my_tts
import my_sum
import utils


MAX_REQUEST = 25000


# {id:[{type,filename,data},{}],}
STORAGE = {}
STORAGE_LOCK = threading.Lock()


def text_to_image(prompt: str) -> str:
    '''
    Generate and send image message from text to user.
    Use it only if asked by user to generate image from text.
    Avoid using text_to_image for precise mathematical expressions, structured diagrams,
    or data-driven charts; instead, use save_diagram_to_image or save_pandas_chart_to_image
    for those specific tasks. Use save_html_to_image for drawing mostly textual content.

    Args:
        prompt: str - text to generate image from

    '''
    my_log.log_gemini_skills(f'/img "{prompt}"')
    return "The function itself does not return an image. It returns a string containing instructions for the assistant. The assistant must send a new message, starting with the /img command, followed by a space, and then the prompt provided, up to 100 words. This specific message format will be automatically recognized by an external system as a request to generate and send an image to the user."


def tts(text: str, lang: str, rate: str) -> str:
    '''
    Generate and send audio message from text to user.
    Use it only if asked by user to generate audio from text.
    Args:
        text: str - text to say (up to 8000 symbols)
        lang: str - language code, default is 'ru'
        rate: str - speed rate, +-100%, default is '+0%'
    '''
    my_log.log_gemini_skills(f'/tts "{text}" "{lang}" "{rate}"')
    return "The function itself does not return an audio message. It returns a string containing instructions for the assistant. The assistant must send a new message, starting with the /tts command, followed by a space, and then the lang provided 'en' ru' 'auto', followed by a space, and then the speed provided, followed by a space, and then the prompt provided. This specific message format will be automatically recognized by an external system as a request to generate and send an audio message to the user."


def speech_to_text(user_id: str) -> str:
    '''
    Transcribe audio message from telegram user.

    Args:
        user_id: str - telegram user id
    '''
    user_id = restore_id(user_id)
    my_log.log_gemini_skills(f'/stt {user_id}')
    return "The function itself does not return an transcribed text. It returns a string containing instructions for the assistant. Any audio-video files send by user to telegram bot will be transcribed automatically and assistant can work with this text."


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
    my_log.log_gemini_skills(f'/edit_image {user_id}')
    return "The function itself does not return an edited image. It returns a string containing instructions for the assistant. Any images send by user to telegram bot with caption starting ! symbol will be edited automatically using external service."


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


def save_html_to_image(filename: str, html: str, viewport_width: int, viewport_height: int, chat_id: str) -> str:
    """Save (render) HTML code to image file and send it to the user.
    This function renders the HTML content in a headless browser environment,
    supporting full HTML5, CSS3, and JavaScript execution. This means you
    can use JavaScript to create dynamic content, draw on <canvas> elements,
    manipulate the DOM, and generate any visual output that a web browser can display.

    Args:
        filename: str - The desired file name for the image file (e.g., 'sales_chart').
        html: str - The HTML code to be saved as an image file. The page must be fully
                    formed according to the HTML standard with CSS and JavaScript included.
                    You can embed JavaScript directly within <script> tags to create complex
                    visualizations, animations, or interactive elements that will be rendered
                    into the final image.
        viewport_width: int - The width of the viewport in pixels.
        viewport_height: int - The height of the viewport in pixels.

        chat_id: str - The Telegram user chat ID where the file should be sent.

    Returns:
        str: 'OK' or 'FAILED'
    """
    try:
        my_log.log_gemini_skills_html(f'"{filename} {viewport_width}x{viewport_height}"\n\n"{html}"')

        chat_id = restore_id(chat_id)
        if chat_id == '[unknown]':
            return "FAIL, unknown chat id"

        # Ensure filename has .png extension and is safe
        if not filename.lower().endswith('.png'):
            filename += '.png'
        filename = utils.safe_fname(filename)

        # save html to png file
        try:
            png_bytes = my_md_tables_to_png.html_to_image_bytes_playwright(html, width=viewport_width, height=viewport_height)
        except Exception as e:
            msg = f'FAILED: {str(e)}'
            my_log.log_gemini_skills_html(msg)
            return msg

        if png_bytes and isinstance(png_bytes, bytes):
            item = {
                'type': 'image/png file',
                'filename': filename,
                'data': png_bytes,
            }
            with STORAGE_LOCK:
                if chat_id in STORAGE:
                    if item not in STORAGE[chat_id]:
                        STORAGE[chat_id].append(item)
                else:
                    STORAGE[chat_id] = [item,]
            return "OK"
    except Exception as e:
        traceback_error = traceback.format_exc()
        my_log.log_gemini_skills_html(f'save_html_to_image: Unexpected error: {e}\n\n{traceback_error}\n\n{html}\n\n{filename} {viewport_width}x{viewport_height}\n\n{chat_id}')
        return f"FAIL: An unexpected error occurred: {e}"

    return 'FAILED'        


def save_pandas_chart_to_image(filename: str, data: dict, chart_type: str, chat_id: str, plot_params: Optional[dict] = None) -> str:
    '''
    Send a chart generated from Pandas data as an image file to the user.
    Args:
        filename: str - The desired file name for the image file (e.g., 'sales_chart').
        data: dict - A dictionary where keys are column names and values are lists of data.
                     Example: {'Date': ['2023-01-01', '2023-01-02'], 'Sales': [100, 150]}
        chart_type: str - The type of chart to generate (e.g., 'line', 'bar', 'pie', 'scatter').
        chat_id: str - The Telegram user chat ID where the file should be sent.
        plot_params: Optional[dict] - Optional dictionary of additional plotting parameters for Matplotlib/Pandas.
                                      Example: {'x': 'Date', 'y': 'Sales', 'title': 'Daily Sales', 'xlabel': 'Date', 'ylabel': 'Amount'}.
                                      For 'pie' charts:
                                      - You must specify 'y' to indicate the column containing the values for slices.
                                      - You can optionally specify 'labels_column' to use a column's values as slice labels. If provided, the data will be grouped by this column and values summed for slices.
                                      - Example: {'y': 'Share (%)', 'labels_column': 'Category', 'title': 'Monthly Expenses'}.
                                      - The 'labels' parameter should NOT be used directly in plot_params for 'pie' charts, as labels are derived from the 'labels_column' or default index.
    Returns:
        str: 'OK' if the file was successfully prepared for sending, or a detailed 'FAIL' message otherwise.
    '''
    try:
        my_log.log_gemini_skills_save_docs(f'save_pandas_chart_to_image {chat_id}\n\n{filename}\n{chart_type}\n{data}')

        chat_id = restore_id(chat_id)
        if chat_id == '[unknown]':
            return "FAIL, unknown chat id"

        # Ensure filename has .png extension and is safe
        if not filename.lower().endswith('.png'):
            filename += '.png'
        filename = utils.safe_fname(filename)

        png_bytes = None
        try:
            # 1. Convert data to Pandas DataFrame
            df = pd.DataFrame(data)

            # 2. Create the plot using Pandas .plot() method (which uses Matplotlib)
            # This part needs careful handling based on chart_type and plot_params
            fig, ax = plt.subplots() # Create a new figure and a set of subplots

            # Apply default plot_params if not provided
            if plot_params is None:
                plot_params = {}

            # Basic mapping from chart_type to Pandas plot method
            if chart_type == 'line':
                df.plot(kind='line', ax=ax, **plot_params)
            elif chart_type == 'bar':
                df.plot(kind='bar', ax=ax, **plot_params)
            elif chart_type == 'pie':
                # Pie charts typically need a single column for values and optionally 'y' for labels
                # Example: plot_params={'y': 'ColumnName', 'labels_column': 'CategoryColumnName'}
                if 'y' in plot_params and plot_params['y'] in df.columns:
                    # Exclude 'autopct' and 'labels_column' from plot_params, as they are handled explicitly
                    pie_plot_params_for_kwargs = {k:v for k,v in plot_params.items() if k not in ['y', 'autopct', 'labels_column']}

                    labels_for_pie = None
                    if 'labels_column' in plot_params and plot_params['labels_column'] in df.columns:
                        labels_for_pie = df[plot_params['labels_column']]

                    df.plot(
                        kind='pie',
                        y=plot_params['y'],
                        ax=ax,
                        autopct=plot_params.get('autopct', '%1.1f%%'),
                        startangle=90,
                        labels=labels_for_pie, # <--- ЭТА СТРОКА ДОБАВЛЕНА/ИЗМЕНЕНА
                        **pie_plot_params_for_kwargs
                    )
                else:
                    my_log.log_gemini_skills_save_docs(f'save_pandas_chart_to_image: Pie chart requires "y" in plot_params and existing column.')
                    return "FAIL: Pie chart requires a 'y' parameter in plot_params pointing to a valid column."
            elif chart_type == 'scatter':
                # Scatter plots require 'x' and 'y' in plot_params
                if 'x' in plot_params and 'y' in plot_params and plot_params['x'] in df.columns and plot_params['y'] in df.columns:
                    df.plot(kind='scatter', x=plot_params['x'], y=plot_params['y'], ax=ax, **{k:v for k,v in plot_params.items() if k not in ['x', 'y']})
                else:
                    my_log.log_gemini_skills_save_docs(f'save_pandas_chart_to_image: Scatter plot requires "x" and "y" in plot_params.')
                    return "FAIL: Scatter plot requires 'x' and 'y' parameters in plot_params."
            else:
                my_log.log_gemini_skills_save_docs(f'save_pandas_chart_to_image: Unsupported chart type: {chart_type}')
                return f"FAIL: Unsupported chart type: {chart_type}. Supported types: line, bar, pie, scatter."

            # Add title and labels if present in plot_params
            if 'title' in plot_params:
                ax.set_title(plot_params['title'])
            if 'xlabel' in plot_params:
                ax.set_xlabel(plot_params['xlabel'])
            if 'ylabel' in plot_params:
                ax.set_ylabel(plot_params['ylabel'])

            # Adjust layout to prevent labels/titles from overlapping
            plt.tight_layout()

            # Save the plot to a BytesIO object in image format
            buffer = io.BytesIO()
            plt.savefig(buffer, format='png', bbox_inches='tight') # bbox_inches='tight' crops whitespace
            buffer.seek(0) # Rewind the buffer to the beginning
            png_bytes = buffer.getvalue()

            plt.close(fig) # Close the figure to free up memory

        except Exception as chart_error:
            my_log.log_gemini_skills_save_docs(f'save_pandas_chart_to_image: Error generating chart: {chart_error}\n\n{traceback.format_exc()}')
            return f"FAIL: Error generating chart: {chart_error}"

        # If bytes were successfully generated, prepare the item for storage
        if png_bytes and isinstance(png_bytes, bytes):
            item = {
                'type': 'image/png file',
                'filename': filename,
                'data': png_bytes,
            }
            with STORAGE_LOCK:
                if chat_id in STORAGE:
                    if item not in STORAGE[chat_id]:
                        STORAGE[chat_id].append(item)
                else:
                    STORAGE[chat_id] = [item,]
            return "OK"
        else:
            # This case indicates that no image data was generated.
            my_log.log_gemini_skills_save_docs(f'save_pandas_chart_to_image: No image data could be generated for chat {chat_id}\n\nData: {data}\nChart Type: {chart_type}')
            return "FAIL: No image data could be generated."

    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_gemini_skills_save_docs(f'save_pandas_chart_to_image: Unexpected error: {error}\n\n{traceback_error}\n\nData: {data}\nChart Type: {chart_type}\nChat ID: {chat_id}')
        return f"FAIL: An unexpected error occurred: {error}"


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
            with STORAGE_LOCK:
                if chat_id in STORAGE:
                    if item not in STORAGE[chat_id]:
                        STORAGE[chat_id].append(item)
                else:
                    STORAGE[chat_id] = [item,]

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


def save_to_docx(filename: str, text: str, chat_id: str) -> str:
    '''
    Send DOCX file to user, converted from markdown text(~~ for strikethrough).
    Args:
        filename: str - The desired file name for the DOCX file (e.g., 'document').
        text: str - The markdown formatted text to convert to DOCX.
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
            with STORAGE_LOCK:
                if chat_id in STORAGE:
                    if item not in STORAGE[chat_id]:
                        STORAGE[chat_id].append(item)
                else:
                    STORAGE[chat_id] = [item,]
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
    Send excel file to user. This updated function supports multiple sheets within a single Excel file.
    Args:
        filename: str - The desired file name for the Excel file (e.g., 'report').
        data: dict - A dictionary where keys are sheet names (str) and values are dictionaries
                     that can be converted to pandas DataFrames. Each inner dictionary represents
                     the data for a single sheet.
                     Example:
                     {
                         'Sheet1': {'Name':['John', 'Anna'], 'Age':[28,24]},
                         'Sheet2': {'Product':['Laptop', 'Mouse'], 'Price':[1200, 25]}
                     }
                     If 'data' is an empty dictionary, a single empty sheet named "Sheet1" will be created.
        chat_id: str - The Telegram user chat ID where the file should be sent.
    Returns:
        str: 'OK' if the file was successfully prepared for sending, or a detailed 'FAIL' message otherwise.
    '''
    try:
        my_log.log_gemini_skills_save_docs(f'save_to_excel {chat_id}\n\n {data}')

        chat_id = restore_id(chat_id)
        if chat_id == '[unknown]':
            return "FAIL, unknown chat id"

        # Ensure filename has .xlsx extension and is safe
        if not filename.lower().endswith('.xlsx'):
            filename += '.xlsx'
        filename = utils.safe_fname(filename)

        excel_buffer = io.BytesIO()

        # Use pandas.ExcelWriter to write multiple sheets to the same Excel file
        with pd.ExcelWriter(excel_buffer, engine='xlsxwriter') as writer:
            # If the provided data dictionary is empty, create a single empty sheet
            if not data:
                pd.DataFrame({}).to_excel(writer, sheet_name="Sheet1", index=False)
            else:
                # Iterate through each sheet's data provided in the 'data' dictionary
                for sheet_name, sheet_data in data.items():
                    # Validate that sheet_data is a dictionary, as expected for DataFrame creation
                    if not isinstance(sheet_data, dict):
                        # Log error for invalid data structure (assuming my_log exists)
                        my_log.log_gemini_skills_save_docs(f'save_to_excel: Invalid sheet data type for sheet "{sheet_name}". Expected dict, got {type(sheet_data)}')
                        return f"FAIL: Invalid data for sheet '{sheet_name}'. Expected a dictionary for sheet content."

                    try:
                        # Convert the sheet's data dictionary into a pandas DataFrame
                        df = pd.DataFrame(sheet_data)
                        # Write the DataFrame to the Excel writer as a new sheet
                        df.to_excel(writer, sheet_name=sheet_name, index=False)
                    except Exception as sheet_write_error:
                        # Log error for specific sheet write failure (assuming my_log and traceback exist)
                        my_log.log_gemini_skills_save_docs(f'save_to_excel: Error writing sheet "{sheet_name}": {sheet_write_error}\n\n{traceback.format_exc()}')
                        return f"FAIL: Error writing data to sheet '{sheet_name}': {sheet_write_error}"

        # After all sheets are written, get the bytes from the buffer
        excel_bytes = excel_buffer.getvalue()

        # If bytes were successfully generated, prepare the item for storage
        if excel_bytes:
            item = {
                'type': 'excel file',
                'filename': filename,
                'data': excel_bytes,
            }
            with STORAGE_LOCK:
                if chat_id in STORAGE:
                    if item not in STORAGE[chat_id]:
                        STORAGE[chat_id].append(item)
                else:
                    STORAGE[chat_id] = [item,]
            return "OK"
        else:
            # This case indicates that no Excel data was generated, even after attempting to write.
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
            with STORAGE_LOCK:
                if chat_id in STORAGE:
                    if item not in STORAGE[chat_id]: # Avoid duplicate entries if necessary
                        STORAGE[chat_id].append(item)
                else:
                    STORAGE[chat_id] = [item,]
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


def init():
    """
    Iterate over STORAGE dict and remove expired entries
    Assuming value is a tuple (data1, data2, ..., timestamp)
    where timestamp is the last element.
    """
    with STORAGE_LOCK:
        STORAGE.clear()


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
def get_currency_rates(date: str = '') -> str:
    '''Return json all currencies rates from https://openexchangerates.org
    date in YYYY-MM-DD format, if absent than latest'''
    try:
        if hasattr(cfg, 'OPENEXCHANGER_KEY') and cfg.OPENEXCHANGER_KEY:
            # https://openexchangerates.org/api/latest.json?app_id=APIKEY
            my_log.log_gemini_skills(f'Currency: {date or "latest"}')
            if date:
                url = f'https://openexchangerates.org/api/historical/{date}.json?app_id={cfg.OPENEXCHANGER_KEY}'
            else:
                url = f'https://openexchangerates.org/api/latest.json?app_id={cfg.OPENEXCHANGER_KEY}'
            responses = requests.get(url, timeout = 20)
            my_log.log_gemini_skills(f'Currency: {responses.text[:300]}')
            return responses.text
        else:
            my_log.log_gemini_skills(f'Currency: ERROR NO API KEY')
            return 'Error: no API key provided'
    except Exception as error:
        backtrace_error = traceback.format_exc()
        my_log.log_gemini_skills(f'get_currency_rates:Error: {error}\n\n{backtrace_error}')
        return f'ERROR {error}'


@cachetools.func.ttl_cache(maxsize=10, ttl=60 * 60)
def search_google_fast(query: str, lang: str, user_id: str) -> str:
    """
    Fast searches Google for the given query and returns the search results.
    You are able to mix this functions with other functions and your own ability to get best results for your needs.

    Args:
        query: The search query string.
        lang: The language to use for the search - 'ru', 'en', etc.
        user_id: The user ID to send the search results to.

    Returns:
        A string containing the search results.
        In case of an error, returns a string 'ERROR' with the error description.
    """
    try:
        user_id = restore_id(user_id)
        query = decode_string(query)
        my_log.log_gemini_skills_search(f'Fast Google search: [{lang}] {user_id} {query}')

        r = my_google.search_v3(
            query.lower(),
            lang = lang,
            download_only=True,
            chat_id=user_id,
            fast_search=True
        )
        my_log.log_gemini_skills_search(f'Fast Google search: {r[:2000]}')
        return r
    except Exception as error:
        my_log.log_gemini_skills_search(f'search_google_fast:Error: {error}')
        return f'ERROR {error}'


@cachetools.func.ttl_cache(maxsize=10, ttl=60 * 60)
def search_google_deep(query: str, lang: str, user_id: str) -> str:
    """
    Deep searches Google for the given query and returns the search results.
    You are able to mix this functions with other functions and your own ability to get best results for your needs.

    Args:
        query: The search query string.
        lang: The language to use for the search - 'ru', 'en', etc.
        user_id: The chat ID to send the search results to.

    Returns:
        A string containing the search results.
        In case of an error, returns a string 'ERROR' with the error description.
    """
    try:
        user_id = restore_id(user_id)
        query = decode_string(query)
        my_log.log_gemini_skills_search(f'Deep Google search: [{lang}] {user_id} {query}')

        r = my_google.search_v3(
            query.lower(),
            lang = lang,
            chat_id=user_id,
            download_only=True
        )
        my_log.log_gemini_skills_search(f'Deep Google search: {r[:2000]}')
        return r
    except Exception as error:
        my_log.log_gemini_skills_search(f'search_google_deep:Error: {error}')
        return f'ERROR {error}'


@cachetools.func.ttl_cache(maxsize=10, ttl=60 * 60)
def download_text_from_url(url: str) -> str:
    '''Download text from url if user asked to.
    Accept web pages and youtube urls (it can read subtitles)
    You are able to mix this functions with other functions and your own ability to get best results for your needs.
    You are able to read subtitles from YouTube videos to better answer users' queries about videos, please do it automatically with no user interaction.
    '''
    language = 'ru'
    my_log.log_gemini_skills(f'Download URL: {url} {language}')
    try:
        result = my_sum.summ_url(url, download_only = True, lang = language)
        return result[:MAX_REQUEST]
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_gemini_skills(f'download_text_from_url:Error: {error}\n\n{traceback_error}')
        return f'ERROR {error}'


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


@cachetools.func.ttl_cache(maxsize=10, ttl = 60*60)
def calc(expression: str, strict: bool, user_id: str) -> str:
    '''Calculate expression with python. The expression can be strict or a free-form task;
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
        A string containing the result of the calculation.
    '''

    try:
        user_id = restore_id(user_id)

        my_log.log_gemini_skills(f'New calc: {user_id} Strict: {strict} {expression}')

        if strict:

            # decimal, math, mpmath, numbers, numpy, random, datetime
            allowed_functions = {
                'math': math,
                'decimal': decimal,
                'mpmath': mpmath,
                'numbers': numbers,
                'numpy': numpy,
                'np': np,
                'random': random,
                'datetime': datetime,
                # 'my_factorial': my_factorial,
                'abs': abs,
                'max': max,
                'min': min,
                'round': round,
                'sum': sum,
                'pow': pow,
                'complex': complex,
                'divmod': divmod,
                'float': float,
                'int': int,
            }

            result = str(simple_eval(expression, functions=allowed_functions))

            my_log.log_gemini_skills(f'Internal calc result: {result}')

            return result
    except Exception as error:
        my_log.log_gemini_skills(f'Calc strict error: {expression}\n{error}')

    #first try groq
    r = my_groq.calc(expression, user_id=user_id)
    if r:
        my_log.log_gemini_skills(f'Groq calc result: {r}')
        return r

    # try gemini calc
    r1, r0 = my_gemini_google.calc(expression, user_id)
    result = f'{r0}\n\n{r1}'.strip()

    if result:
        my_log.log_gemini_skills(f'Google calc result: {result}')
        return result
    else:
        my_log.log_gemini_skills(f'Calc error: Failed to calculate {expression}')
        return f'Error: failed to calculate {expression}'


calc_tool = calc


def test_calc(func: Callable = calc) -> None:
    """
    Тестирует функцию calc (которая теперь не принимает chat_id и возвращает строку)
    с набором предопределенных тестовых случаев.
    """

    test_cases: List[Tuple[str, Union[str, None]]] = [
        # Валидные выражения.
        # ('3.96140812E+28+3.96140812E+28', '7.92281624e+28'),
        # ("2 + 2", "4"),
        # ("10 * 5", "50"),
        # ("100 / 4", "25.0"),
        # ("2 ** 3", "8"),
        # ("1 + 2 * 3", "7"),
        # ("(1 + 2) * 3", "9"),
        # ("2 ++ 2", "4"), # 2 + (+2) = 4
        # ("sqrt(16)", "4.0"),
        # ("math.sqrt(16)", "4.0"),
        # ("math.sin(0)", "0.0"),
        # ("math.factorial(5)", "120"),
        # # Пример с Decimal (если ваша функция calc поддерживает его)
        # ("decimal.Decimal('1.23') + decimal.Decimal('4.56')", "5.79"),
        # ('math.factorial(10)', '3628800'),
        # ('math.factorial(1600)', ''),
        ('round((80 / 270) * 100, 2)', '29.63'),
        #date example
        # ("datetime.datetime.now()", ""),
        # # Примеры, где мы не можем предсказать *точный* вывод, но все равно можем проверить:
        # ("random.randint(1, 10)", None),  # Мы не знаем точное число
        # ("x + y + z", None),  # Предполагая, что функция обрабатывает неопределенные переменные
        # ("a*2+b-c", None),
        # # Недопустимые выражения (ожидаем ошибки).
        # ("x = 5\ny = 10\nx + y", ""),
        # ("invalid_function(5)", ""),
        # ("2 + abc", ""),
        # ("print('hello')", ""),
        # ("os.system('ls -l')", ""),  # Если функция блокирует os.system
        # ("1 / 0", ""),
        # ("math.unknown_function()", ""),
        # ("", ""),  # Пустое выражение тоже должно быть ошибкой.
        # ('89479**78346587', ''),
    ]

    for expression, expected_result in test_cases:
        result = func(expression)

        print(f"Запрос: {expression}")
        print(f"Ответ: {result}")

        if expected_result == "":  # Случай ошибки
            if result == "" or result.startswith('Error'):
                print(f"Результат: OK (Ожидалась ошибка) {result}")
            else:
                print(f"Результат: FAIL (Ожидалась ошибка, получено: {result})")
        elif expected_result is None:  # Непредсказуемый результат
            if result != "":
                print("Результат: OK (Результат получен)")
            else:
                print("Результат: FAIL (Результат не получен)")
        else:  # У нас есть конкретный ожидаемый результат
            if result == expected_result:
                print("Результат: OK")
            else:
                print(f"Результат: FAIL (Ожидалось: {expected_result}, Получено: {result})")
        print("-" * 20)

    print("Тесты завершены.")


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


def run_script(filename: str, body: str) -> str:
    """
    Saves and runs a script in the shell, returning its output. This script has full access to files and network, there are no sandboxes.
    Allowed file extensions are ".py" for Python and ".sh" for Bash. Do not add any shebang to the body.
    The function will execute the code using: subprocess.check_output(f'./run_script_{filename}', shell=True, timeout=300)

    Args:
        filename: The name of the file to be created.
        body: The content of the script to be executed.

    Returns:
        The output of the executed script.

    Instructions:
        1. Pass the filename with the extension (.py or .sh) to the 'filename' argument.
        2. Pass the script content without the shebang (#!... ) to the 'body' argument.
        3. If 'filename' ends with .py, the 'body' will be executed as a Python script.
        4. If 'filename' ends with .sh, the 'body' will be executed as a Bash script.
        5. The function will save the script to disk, make it executable, run it, and return the output.
        6. If an error occurs during script execution, the function will return the error message.
        7. After executing the script, it will be deleted from the disk.

    Example:
        filename = 'script.py'
        body = '''
import os
print(os.getcwd())
'''
        result = run_script(filename, body)
        print(result)

    Or:

        filename = 'script.sh'
        body = '''
echo "Hello, world!"
ls -l
'''
        result = run_script(filename, body)
        print(result)

    Important:
    - Ensure the script content in `body` is properly formatted and does not contain syntax errors.
    - Be cautious when running scripts with network access, as they have full access to the network.
    - If the script generates files, make sure to handle them appropriately (e.g., delete them after use).
    - Double quotes inside the script body are NOT escaped anymore.
    - Use triple quotes (''') to pass multiline strings with quotes to avoid manual escaping.
    """
    body = decode_string(body)
    filename = 'run_script_' + filename
    ext = utils.get_file_ext(filename)
    if ext.startswith('.'):
        ext = ext[1:]

    if ext == 'py':
        if not body.split()[0].startswith('#!/'):
            body = '#!/usr/bin/env python3\n\n' + body
        # Do not escape double quotes
    elif ext == 'sh':
        if not body.split()[0].startswith('#!/'):
            body = '#!/bin/bash\n\n' + body
    # Remove extra escaping that was added previously
    # body = body.replace('\\\\', '\\')

    my_log.log_gemini_skills(f'run_script {filename}\n\n{body}')

    try:
        with open(filename, 'w') as f:
            f.write(body)
        os.chmod(filename, 0o777)
        try:
            output = subprocess.check_output(f'./{filename}', shell=True, timeout=300, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as error:
            if not error.output:
                output = str(error).encode('utf-8', errors='replace')
            else:
                output = error.output
        utils.remove_file(filename)
        result = output.decode('utf-8', errors='replace')
        my_log.log_gemini_skills(f'run_script: {result}')
        return result
    except Exception as error:
        utils.remove_file(filename)
        traceback_error = traceback.format_exc()
        my_log.log_gemini_skills(f'run_script: {error}\n{traceback_error}\n\n{filename}\n{body}')
        return f'{error}\n\n{traceback_error}'


def help(user_id: str) -> str:
    '''
    Return help info about you (assistant and telegram bot) skills and abilities.
    Use it if user ask what he can do here or what you can do for him.
    '''
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
        /bing - будет рисовать только с помощью Bing image creator
        /flux - будет рисовать только с помощью Flux
        /gem - будет рисовать только с помощью Gemini
/tts <text to say> - сделать запрос к внешним сервисам на голосовое сообщение

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


@cachetools.func.ttl_cache(maxsize=10, ttl = 2*60)
def compose_creative_text(prompt: str, context: str, user_id: str) -> str:
    '''
    Composes creative content such as songs, poems, and rhymed verses.
    This tool is specifically designed for tasks where the user explicitly requests rhyming,
    specific poetic forms (e.g., couplets, quatrains), or lyrical structures for songs,
    as the model itself may not always produce high-quality rhyming or poetic depth.
    The output will be the generated text *only*, without any additional commentary.

    Args:
        prompt: The user's full request for creative text generation, including any topic, style, length, or specific rhyming schemes.
        context: Any additional conversational context or extracted details that might help the generation, such as previous turns of conversation or specific constraints not directly in the main prompt. If no additional context is available or relevant, provide an empty string.
        user_id: The Telegram user ID.

    Returns:
        The generated song, poem, or rhymed text.
    '''
    try:
        user_id = restore_id(user_id)

        my_log.log_gemini_skills(f'compose_creative_text: {user_id} {prompt}\n\n{context}')

        query = f'''{{"request_type": "creative_text_generation", "user_prompt": "{prompt}", "context": "{context}", "output_format_instruction": "The output must contain only the requested creative text (song, poem, rhymed verse) without any introductory phrases, conversational remarks, or concluding comments."}}'''

        result = my_github.ai(query, model=my_github.GROK_MODEL, timeout=60, user_id=user_id)

        if result:
            my_log.log_gemini_skills(f'compose_creative_text: {user_id} {prompt} {context}\n\n{result}')
            return result

    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_gemini_skills(f'compose_creative_text: {error}\n\n{error_traceback}\n\n{prompt}\n\n{context}')

    my_log.log_gemini_skills(f'compose_creative_text: {user_id} {prompt}\n\n{context}\n\nThe muse did not answer, come up with something yourself without the help of tools.')
    return 'The muse did not answer, come up with something yourself without the help of tools.'


if __name__ == '__main__':
    pass
    init()
    my_db.init(backup=False)
    my_groq.load_users_keys()
    # moscow_time = get_time_in_timezone("Europe/Moscow")
    # print(f"Time in Moscow: {moscow_time}")

    # test_calc()
    r = calc(
        'Generate lists of numbers for plotting the graph of the sin(x) function in the range from -5 to 5 with a step of 0.1.',
        strict=False,
        user_id='test'
    )
    print(r)

    # print(restore_id('-1234567890'))

    # print(sys.get_int_max_str_digits())
    # print(sys.set_int_max_str_digits())

    # text='''ls -l'''
    # print(run_script('test.sh', text))

    my_db.close()
