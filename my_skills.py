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
import random
import requests
import subprocess
import traceback

import matplotlib.pyplot as plt
import pandas as pd
import swisseph as swe
from kerykeion import AstrologicalSubject, NatalAspects, KerykeionChartSVG
from kerykeion.charts.charts_utils import convert_latitude_coordinate_to_string, convert_longitude_coordinate_to_string
from kerykeion.utilities import get_houses_list
from datetime import datetime
from simpleeval import simple_eval
from typing import Callable, List, Optional, Tuple, Union

# it will import word random and broke code
# from random import *
#from random import betavariate, choice, choices, expovariate, gammavariate, gauss, getrandbits, getstate, lognormvariate, normalvariate, paretovariate, randbytes, randint, randrange, sample, seed, setstate, shuffle, triangular, uniform, vonmisesvariate, weibullvariate

import cfg
import my_cohere
import my_db
import my_google
import my_gemini
import my_gemini_general
import my_gemini_google
import my_groq
import my_log
import my_md_tables_to_png
import my_mistral
import my_skills_storage
import my_skills_general
import my_sum
import utils


MAX_REQUEST = 25000


help = my_skills_general.help
text_to_image = my_skills_general.text_to_image
text_to_qrcode = my_skills_general.text_to_qrcode
tts = my_skills_general.tts
speech_to_text = my_skills_general.speech_to_text
translate_text = my_skills_general.translate_text
translate_documents = my_skills_general.translate_documents
edit_image = my_skills_general.edit_image
get_weather = my_skills_general.get_weather


def save_natal_chart_to_image(name: str, date: str, time: str, place: str, nation: str, language: str, chat_id: str) -> str:
    """Generates a natal chart in PNG format based on the provided astrological subject data and sends it to the user.

    This function uses the Kerykeion library to create an astrological natal chart.

    Args:
        name (str): The name of the astrological subject (e.g., "Alexandra Ivanova").
        date (str): The birth date in 'YYYY-MM-DD' format (e.g., "1994-10-17").
        time (str): The birth time in 'HH:MM' format (e.g., "06:42").
        place (str): The city of birth. It is important that the city name is specified in English,
                     as the library expects English city names (e.g., "St. Petersburg" instead of "Санкт-Петербург").
        nation (str): The two-letter country code (e.g., "RU" for Russia, "US" for USA).
        language (str): The two-letter language code (e.g., "ru" for Russian, "en" for English).
        chat_id (str): The Telegram user chat ID where the file should be sent.

    Returns:
        str: 'OK' if the file was successfully prepared for sending, or a detailed 'FAIL' message otherwise.
    """

    def get_textual_astrological_report(subject: AstrologicalSubject) -> str:
        """
        Генерирует текстовый отчет по натальной карте, используя объекты Kerykeion.
        
        Args:
            subject: Объект AstrologicalSubject.
            
        Returns:
            Отформатированная строка с астрологической информацией.
        """
        try:
            PLANET_NAMES = [
                "Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Uranus",
                "Neptune", "Pluto", "Mean_Node", "Chiron", "Ascendant", "Medium_Coeli",
                "Mean_Lilith", "Mean_South_Node"
            ]

            # --- 1. Основная информация ---
            dt_local = datetime.fromisoformat(subject.iso_formatted_local_datetime)
            tz_offset_str = dt_local.strftime('%z')
            formatted_tz = f"[{tz_offset_str[:-2]}:{tz_offset_str[-2:]}]"
            datetime_str = f"{dt_local.strftime('%Y-%m-%d %H:%M')} {formatted_tz}"

            lat_str = convert_latitude_coordinate_to_string(subject.lat, "Север", "Юг")
            lng_str = convert_longitude_coordinate_to_string(subject.lng, "Восток", "Запад")

            info_lines = [
                f"{subject.name}",
                f"Дата и время: {datetime_str}",
                f"Место: {subject.city}, {subject.nation}",
                f"Широта: {lat_str}",
                f"Долгота: {lng_str}",
                f"Система домов: {subject.houses_system_name}",
                f"Зодиак: {subject.zodiac_type}"
            ]

            # --- 2. Лунная фаза ---
            lunar_phase_info = [
                f"Лунная фаза (день): {subject.lunar_phase['moon_phase']}",
                f"Лунная фаза (название): {subject.lunar_phase['moon_phase_name']}",
            ]

            # --- 3. Положения планет ---
            planets_lines = []
            for planet_name in PLANET_NAMES:
                if hasattr(subject, planet_name):
                    planet = getattr(subject, planet_name)
                    retrograde_str = " (R)" if planet.retrograde else ""
                    
                    _sign_index, deg, minute, second, _frac = swe.split_deg(planet.abs_pos, swe.SPLIT_DEG_ZODIACAL)
                    position_str = f"{deg}°{minute}'{int(second)}\""
                    
                    planets_lines.append(
                        f"{planet.name}: {position_str} в знаке {planet.sign}{retrograde_str}"
                    )

            # --- 4. Положения домов (куспиды) ---
            houses_lines = []
            house_list = get_houses_list(subject)
            for house in house_list:
                _sign_index, deg, minute, second, _frac = swe.split_deg(house.abs_pos, swe.SPLIT_DEG_ZODIACAL)
                position_str = f"{deg}°{minute}'{int(second)}\""

                houses_lines.append(
                    f"Дом {house.name.title()}: {position_str} в знаке {house.sign}"
                )

            # --- 5. Аспекты ---
            aspect_calculator = NatalAspects(subject)
            aspects_lines = []
            sorted_aspects = sorted(aspect_calculator.relevant_aspects, key=lambda x: (x.p1, x.p2))
            for aspect in sorted_aspects:
                # ИСПРАВЛЕНО ЗДЕСЬ: Используем aspect.diff вместо aspect['orb']
                aspects_lines.append(
                    f"{aspect.p1} - {aspect.p2}: {aspect.aspect} (орб: {aspect.diff:.2f}°)"
                )

            # --- 6. Стихии ---
            elements_count = {'fire': 0, 'earth': 0, 'air': 0, 'water': 0}
            planets_for_elements = PLANET_NAMES[:10]

            for planet_name in planets_for_elements:
                if hasattr(subject, planet_name):
                    planet = getattr(subject, planet_name)
                    elements_count[planet.element] += 1

            total_points = len(planets_for_elements)
            if total_points > 0:
                elements_lines = [
                    f"Огонь: {elements_count['fire']/total_points:.0%}",
                    f"Земля: {elements_count['earth']/total_points:.0%}",
                    f"Воздух: {elements_count['air']/total_points:.0%}",
                    f"Вода: {elements_count['water']/total_points:.0%}",
                ]
            else:
                elements_lines = ["Нет планет для расчета стихий."]

            # --- Сборка отчета ---
            report_parts = {
                "--- ОСНОВНАЯ ИНФОРМАЦИЯ ---": info_lines,
                "--- ЛУННАЯ ФАЗА ---": lunar_phase_info,
                "--- ПЛАНЕТЫ ---": planets_lines,
                "--- ДОМА (КУСПИДЫ) ---": houses_lines,
                "--- СТИХИИ ---": elements_lines,
                "--- АСПЕКТЫ ---": aspects_lines,
            }

            output_str = ""
            for title, lines in report_parts.items():
                output_str += title + "\n"
                output_str += "\n".join(lines)
                output_str += "\n\n"

            return output_str.strip()
        except Exception as error:
            traceback_str = traceback.format_exc()
            my_log.log2(f'tb:gemini_natal_chart: {error}\n\n{traceback_str}')
            return f"FAIL: An error occurred while generating the report. Error: {error}"

    try:
        # Log the request
        my_log.log_gemini_skills_html(f'Generating natal chart for "{name}, {date} {time}, {place}, {nation}" for chat_id: {chat_id}')

        # Restore and validate chat_id
        chat_id = my_skills_general.restore_id(chat_id)
        if chat_id == '[unknown]':
            return "FAIL, unknown chat id"

        # Parse date and time strings into integers
        try:
            year, month, day = map(int, date.split('-'))
            hour, minute = map(int, time.split(':'))
        except ValueError as e:
            return f"FAIL: Invalid date or time format. Use 'YYYY-MM-DD' and 'HH:MM'. Error: {e}"

        # Create an AstrologicalSubject instance
        subject = AstrologicalSubject(
            name=name,
            year=year,
            month=month,
            day=day,
            hour=hour,
            minute=minute,
            city=place,
            nation=nation
        )

        # Generate the chart in SVG format
        # тут надо язык а не нацию
        chart = KerykeionChartSVG(subject, chart_language=language.upper())
        svg_string = chart.makeTemplate()

        # Define filename
        filename = f"natal_chart_{name.replace(' ', '_')}_{date}.png"
        filename = utils.safe_fname(filename) # Ensure filename is safe

        # Convert the SVG string to PNG bytes
        try:
            # Assuming a default viewport size is suitable for natal charts, or can be made configurable
            png_bytes = my_md_tables_to_png.html_to_image_bytes_playwright(svg_string, width=1920, height=1080)
        except Exception as e:
            msg = f'FAIL: Error converting SVG to PNG: {str(e)}'
            my_log.log_gemini_skills_html(msg)
            return msg

        if png_bytes and isinstance(png_bytes, bytes):
            item = {
                'type': 'image/png file',
                'filename': filename,
                'data': png_bytes,
            }
            with my_skills_storage.STORAGE_LOCK:
                if chat_id in my_skills_storage.STORAGE:
                    if item not in my_skills_storage.STORAGE[chat_id]:
                        my_skills_storage.STORAGE[chat_id].append(item)
                else:
                    my_skills_storage.STORAGE[chat_id] = [item,]
            return f"OK. Информация для трактовки изображения карты (ассистент должен рассказать юзеру что на карте используя эти данные): {get_textual_astrological_report(subject)}"
        else:
            return "FAIL: Image bytes were not generated."

    except Exception as e:
        traceback_error = traceback.format_exc()
        my_log.log_gemini_skills_html(f'save_natal_chart_to_image: Unexpected error: {e}\n\n{traceback_error}\n\n{name}, {date}, {time}, {place}, {nation}, {chat_id}')
        return f"FAIL: An unexpected error occurred: {e}"


def query_user_file(query: str, user_id: str) -> str:
    '''
    Query saved user file (do not ask for full text, just answer the question)

    Args:
        query: str - user query
        user_id: str - user id

    Returns:
        str
    '''
    user_id = my_skills_general.restore_id(user_id)
    if user_id not in my_skills_storage.STORAGE_ALLOWED_IDS or my_skills_storage.STORAGE_ALLOWED_IDS[user_id] != user_id:
        my_log.log_gemini_skills_query_file(f'/query_last_file "{query}" "{user_id}" - Unauthorized access detected.')
        return 'Unauthorized access detected.'

    my_log.log_gemini_skills_query_file(f'/query_last_file "{query}" "{user_id}"')

    saved_file_name = my_db.get_user_property(user_id, 'saved_file_name') or ''
    if saved_file_name:
        saved_file = my_db.get_user_property(user_id, 'saved_file')
    else:
        saved_file = ''

    q = f'''Answer the user`s query using saved text and your own mind, answer plain text with fancy markdown formatting, do not use code block for answer.

User query: {query}

URL/file: {saved_file_name}

Saved text: {saved_file}
'''

    temperature = my_db.get_user_property(user_id, 'temperature') or 1
    role = my_db.get_user_property(user_id, 'role') or ''

    result = my_gemini.ai(q[:my_gemini_general.MAX_SUM_REQUEST], temperature=temperature, tokens_limit=8000, model = cfg.gemini25_flash_model, system=role)
    if not result:
        result = my_gemini.ai(q[:my_gemini_general.MAX_SUM_REQUEST], temperature=temperature, tokens_limit=8000, model = cfg.gemini_flash_model, system=role)
    if not result:
        result = my_cohere.ai(q[:my_cohere.MAX_SUM_REQUEST], system=role)
    if not result:
        result = my_mistral.ai(q[:my_mistral.MAX_SUM_REQUEST], system=role)
    if not result:
        result = my_groq.ai(q[:my_groq.MAX_SUM_REQUEST], temperature=temperature, max_tokens_ = 4000, system=role)

    if result:
        my_log.log_gemini_skills_query_file(result)
        return result
    else:
        return 'No result was given.'


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

        chat_id = my_skills_general.restore_id(chat_id)
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
            with my_skills_storage.STORAGE_LOCK:
                if chat_id in my_skills_storage.STORAGE:
                    if item not in my_skills_storage.STORAGE[chat_id]:
                        my_skills_storage.STORAGE[chat_id].append(item)
                else:
                    my_skills_storage.STORAGE[chat_id] = [item,]
            return "OK"
    except Exception as e:
        traceback_error = traceback.format_exc()
        my_log.log_gemini_skills_html(f'save_html_to_image: Unexpected error: {e}\n\n{traceback_error}\n\n{html}\n\n{filename} {viewport_width}x{viewport_height}\n\n{chat_id}')
        return f"FAIL: An unexpected error occurred: {e}"

    return 'FAILED'


##### charts ###############################################

def save_chart_and_graphs_to_image(user_id: str) -> str:
    '''
    Send a charts to telegram user. Any visual plots.
    Args:
        user_id: str - telegram user id
    Returns:
        str:
    '''
    user_id = my_skills_general.restore_id(user_id)
    my_log.log_gemini_skills_save_docs(f'/save_chart_and_graphs_to_image {user_id}')
    # return "The function itself does not return an edited image. It returns a string containing instructions for the assistant. Use save_html_to_image for drawing charts in html, when drawing with html keep in mind it should be look like a real chart with axis and legend end etc."
    return "The function itself does not return an edited image. It returns a string containing instructions for the assistant. When generating an graphs and charts message for the user, your output must be exclusively the /calc command in the format /calc [query], with absolutely no preceding or additional explanatory text, because this exact message is directly processed by the drawing system for delivery to the user. For example: /calc 'draw x=y^2'. Do NOT respond with text like 'Here is your query: /calc draw x=y^2 ' as this will fail."


# не используется но возможно потребуются когда groq перестанет работать
def save_chart_and_graphs_to_image_(prompt: str, filename: str, user_id: str) -> str:
    '''
    Send a charts to telegram user. Any visual plots.
    Args:
        prompt: str - prompt text to generate chart and graphs
        filename: str - filename
        user_id: str - telegram user id
    Returns:
        str: 'OK' message or error message
    '''
    user_id = my_skills_general.restore_id(user_id)
    my_log.log_gemini_skills_save_docs(f'/save_chart_and_graphs_to_image {user_id} {filename} {prompt}')
    # return "The function itself does not return an edited image. It returns a string containing instructions for the assistant. Use use save_html_to_image for drawing charts in html, when drawing with html keep in mind it should be look like a real chart with axis and legend end etc."

    try:
        if not filename.endswith('.png'):
            filename += '.png'

        text, images = my_groq.get_groq_response_with_image(prompt, user_id)

        if text and images:
            for image in images:
                item = {
                    'type': 'image/png file',
                    'filename': filename,
                    'data': image,
                }
                with my_skills_storage.STORAGE_LOCK:
                    if user_id in my_skills_storage.STORAGE:
                        if item not in my_skills_storage.STORAGE[user_id]:
                            my_skills_storage.STORAGE[user_id].append(item)
                    else:
                        my_skills_storage.STORAGE[user_id] = [item,]
            my_log.log_gemini_skills_save_docs(f'/save_chart_and_graphs_to_image {user_id} {filename} {prompt}\n\n{text}')
            return text
    except Exception as e:
        traceback_error = traceback.format_exc()
        my_log.log_gemini_skills_save_docs(f'save_chart_and_graphs_to_image: Unexpected error: {e}\n\n{traceback_error}\n\n{prompt}\n\n{user_id}')
        return f"FAIL: An unexpected error occurred: {e}"

    my_log.log_gemini_skills_save_docs(f'/save_chart_and_graphs_to_image {user_id} {filename} {prompt}\n\nFAILED')
    return 'FAILED'


# не используется но возможно потребуются когда groq перестанет работать
def save_pandas_chart_to_image_(filename: str, data: dict, chart_type: str, chat_id: str, plot_params: Optional[dict] = None) -> str:
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

        chat_id = my_skills_general.restore_id(chat_id)
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
            with my_skills_storage.STORAGE_LOCK:
                if chat_id in my_skills_storage.STORAGE:
                    if item not in my_skills_storage.STORAGE[chat_id]:
                        my_skills_storage.STORAGE[chat_id].append(item)
                else:
                    my_skills_storage.STORAGE[chat_id] = [item,]
            return "OK"
        else:
            # This case indicates that no image data was generated.
            my_log.log_gemini_skills_save_docs(f'save_pandas_chart_to_image: No image data could be generated for chat {chat_id}\n\nData: {data}\nChart Type: {chart_type}')
            return "FAIL: No image data could be generated."

    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_gemini_skills_save_docs(f'save_pandas_chart_to_image: Unexpected error: {error}\n\n{traceback_error}\n\nData: {data}\nChart Type: {chart_type}\nChat ID: {chat_id}')
        return f"FAIL: An unexpected error occurred: {error}"

##### charts ###############################################


def init():
    """
    Iterate over my_skills_storage.STORAGE dict and remove expired entries
    Assuming value is a tuple (data1, data2, ..., timestamp)
    where timestamp is the last element.
    """
    with my_skills_storage.STORAGE_LOCK:
        my_skills_storage.STORAGE.clear()


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
    This tool should not be used instead of other functions, such as text translation.

    Args:
        query: The search query string.
        lang: The language to use for the search - 'ru', 'en', etc.
        user_id: The user ID to send the search results to.

    Returns:
        A string containing the search results.
        In case of an error, returns a string 'ERROR' with the error description.
    """
    try:
        user_id = my_skills_general.restore_id(user_id)
        query = my_skills_general.decode_string(query)
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
    This tool can also find direct links to images.

    Args:
        query: The search query string.
        lang: The language to use for the search - 'ru', 'en', etc.
        user_id: The chat ID to send the search results to.

    Returns:
        A string containing the search results.
        In case of an error, returns a string 'ERROR' with the error description.
    """
    try:
        user_id = my_skills_general.restore_id(user_id)
        query = my_skills_general.decode_string(query)
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
        user_id = my_skills_general.restore_id(user_id)

        my_log.log_gemini_skills_calc(f'New calc: {user_id} Strict: {strict} {expression}')

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
                'bin': bin,
                'oct': oct,
                'hex': hex,
                'bool': bool,
                'chr': chr,
                'ord': ord,
                'len': len,
                'range': range,
                'list': list,
                'dict': dict,
                'set': set,
                'frozenset': frozenset,
                'tuple': tuple,                
            }

            result = str(simple_eval(expression, functions=allowed_functions))

            my_log.log_gemini_skills_calc(f'Internal calc result: {result}')

            return result
    except Exception as error:
        my_log.log_gemini_skills_calc(f'Calc strict error: {expression}\n{error}')

    #first try groq
    r = my_groq.calc(expression, user_id=user_id)
    if r:
        my_log.log_gemini_skills_calc(f'Groq calc result: {r}')
        return r

    # try gemini calc
    r1, r0 = my_gemini_google.calc(expression, user_id)
    result = f'{r0}\n\n{r1}'.strip()

    if result:
        my_log.log_gemini_skills_calc(f'Google calc result: {result}')
        return result
    else:
        my_log.log_gemini_skills_calc(f'Calc error: Failed to calculate {expression}')
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
    body = my_skills_general.decode_string(body)
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


if __name__ == '__main__':
    pass
    init()
    my_db.init(backup=False)
    my_groq.load_users_keys()

    # test_calc()
    r = calc(
        'bin(48)',
        strict=True,
        user_id='test'
    )
    print(r)

    # print(my_skills_general.restore_id('-1234567890'))

    # print(sys.get_int_max_str_digits())
    # print(sys.set_int_max_str_digits())

    # text='''ls -l'''
    # print(run_script('test.sh', text))

    my_db.close()
