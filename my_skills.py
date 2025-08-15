#!/usr/bin/env python3
# pip install -U simpleeval


import cachetools.func
import datetime
import decimal
import io
import hashlib
import math
import mpmath
import numbers
import numpy
import numpy as np
import os
import random
import requests
import subprocess
import time
import traceback
import tempfile

import matplotlib.pyplot as plt
import pandas as pd
import swisseph as swe
from kerykeion import AstrologicalSubject, NatalAspects, KerykeionChartSVG
from kerykeion.charts.charts_utils import convert_latitude_coordinate_to_string, convert_longitude_coordinate_to_string
from kerykeion.utilities import get_houses_list
from datetime import datetime
from PIL import Image
from playwright.sync_api import sync_playwright
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
import my_tarot
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


# def send_tarot_cards(chat_id: str, num_cards: int) -> str:
#     """Sends one or three random tarot cards to the user.

#     This function retrieves unique tarot cards (including their binary image data)
#     from the `my_tarot` module and prepares them for sending to the specified Telegram user.
#     If >1 cards are requested, they are combined into a single collage
#     image, arranged from left to right, without gaps, before sending.

#     Args:
#         chat_id (str): The Telegram user chat ID where the card(s) should be sent.
#                        The ID will be restored and validated internally.
#         num_cards (int): The number of cards to send. Valid values are 1 or 3.

#     Returns:
#         str: 'OK' followed by a confirmation message if the card(s) were
#              successfully prepared for sending. Returns 'FAIL' followed by an
#              error description if an issue occurred, such as an invalid
#              `num_cards` value, an unknown chat ID, or an error during card
#              retrieval or storage.
#     """
#     try:
#         # Log the request for auditing/debugging purposes.
#         my_log.log_gemini_skills(f'Sending {num_cards} tarot card(s) for chat_id: {chat_id}')

#         # Restore and validate the chat_id.
#         restored_chat_id: str = my_skills_general.restore_id(chat_id)
#         if restored_chat_id == '[unknown]':
#             return "FAIL: Unknown chat ID."

#         final_item_data: bytes
#         final_item_filename: str
#         card_names_for_message: List[str] = []

#         # Determine how many cards to retrieve based on num_cards.
#         if num_cards == 1:
#             # Retrieve a single random card.
#             card_data, card_name = my_tarot.get_single_tarot_card_data()
#             final_item_data = card_data
#             final_item_filename = card_name.replace('.webp', '')
#             card_names_for_message.append(card_name)

#         elif num_cards == 3:
#             # Retrieve three unique cards.
#             three_cards_data: List[Tuple[bytes, str]] = my_tarot.get_three_unique_tarot_card_data()

#             if len(three_cards_data) != 3:
#                 return "FAIL: Could not retrieve three unique tarot cards."

#             images: List[Image.Image] = []
#             total_width: int = 0
#             max_height: int = 0

#             # Open each image and prepare for collage
#             for card_bytes, card_name in three_cards_data:
#                 image: Image.Image = Image.open(io.BytesIO(card_bytes))
#                 images.append(image)
#                 total_width += image.width
#                 max_height = max(max_height, image.height)
#                 card_names_for_message.append(card_name)

#             # Create a new blank image with transparent background
#             collage_image = Image.new('RGBA', (total_width, max_height))

#             # Paste images onto the collage
#             x_offset: int = 0
#             for img in images:
#                 collage_image.paste(img, (x_offset, 0))
#                 x_offset += img.width

#             # Save the collage to bytes
#             byte_arr = io.BytesIO()
#             collage_image.save(byte_arr, format='PNG')
#             final_item_data = byte_arr.getvalue()
#             final_item_filename = f"{', '.join(name.replace('.webp', '') for name in card_names_for_message)}"

#         else:
#             # Handle invalid num_cards input.
#             return "FAIL: Invalid number of cards specified. Please choose 1 or 3."

#         # Check if final item data was generated.
#         if not final_item_data:
#             return "FAIL: No tarot card image data was generated."

#         # Acquire a lock before modifying the shared storage to prevent race conditions.
#         with my_skills_storage.STORAGE_LOCK:
#             # Ensure the chat_id exists in storage, if not, initialize it.
#             if restored_chat_id not in my_skills_storage.STORAGE:
#                 my_skills_storage.STORAGE[restored_chat_id] = []

#             # Define the item structure for storing the image data.
#             item = {
#                 'type': 'image/png file',
#                 'filename': final_item_filename,
#                 'data': final_item_data,
#             }
#             # Append the prepared item to the user's storage.
#             my_skills_storage.STORAGE[restored_chat_id].append(item)

#         # Return a success message.
#         msg_cards = ", ".join(card_name.replace('.png', '') for card_name in card_names_for_message)
#         return f"OK. {num_cards} tarot card(s) prepared for sending. Assistant, as a professional tarologist, must write to the user what such a spread means, the cards chosen are: " + msg_cards

#     except Exception as e:
#         # Capture full traceback for detailed logging in case of an unexpected error.
#         traceback_error: str = traceback.format_exc()
#         my_log.log_gemini_skills(
#             f'send_tarot_cards: Unexpected error: {e}\n\n{traceback_error}\n\nchat_id: {chat_id}, num_cards: {num_cards}'
#         )
#         # Return a failure message with the encountered error.
#         return f"FAIL: An unexpected error occurred while preparing tarot cards: {e}"


def send_tarot_cards(chat_id: str, num_cards: int) -> str:
    """Sends random tarot cards to the user.

    This function retrieves the specified number of unique tarot cards and
    send images to the specified Telegram user.

    Args:
        chat_id (str): The Telegram user chat ID where the card(s) should be sent.
                       The ID will be restored and validated internally.
        num_cards (int): The number of cards to send (must be between 1 and 10 inclusive).

    Returns:
        str: 'OK' followed by a confirmation message if the card(s) were
             successfully prepared for sending. Returns 'FAIL' followed by an
             error description if an issue occurred.
    """
    try:
        # Log the request for auditing/debugging purposes.
        my_log.log_gemini_skills(f'Sending {num_cards} tarot card(s) for chat_id: {chat_id}')

        # Restore and validate the chat_id.
        restored_chat_id: str = my_skills_general.restore_id(chat_id)
        if restored_chat_id == '[unknown]':
            return "FAIL: Unknown chat ID."

        # Validate card count range (1-10 is standard for tarot spreads)
        if num_cards < 1 or num_cards > 10:
            return "FAIL: Number of cards must be between 1 and 10 inclusive. Traditional tarot spreads rarely exceed 10 cards for readability."

        # Collect unique cards
        cards_data = []
        while len(cards_data) < num_cards:
            card = my_tarot.get_single_tarot_card_data()
            if card not in cards_data:
                cards_data.append(card)

        # Split cards into groups of 3 for storage
        storage_items = []
        group_messages = []

        for i in range(0, len(cards_data), 3):
            chunk = cards_data[i:i+3]
            chunk_size = len(chunk)
            chunk_card_names = [name for _, name in chunk]
            chunk_filenames = [name.replace('.webp', '') for name in chunk_card_names]

            # Process single-card group
            if chunk_size == 1:
                card_data, card_name = chunk[0]
                item_data = card_data
                item_filename = chunk_filenames[0]
                group_msg = f"Group {i//3 + 1}: {chunk_filenames[0]}"

            # Process multi-card group (2-3 cards)
            else:
                images = []
                total_width = 0
                max_height = 0

                for card_bytes, card_name in chunk:
                    image = Image.open(io.BytesIO(card_bytes))
                    images.append(image)
                    total_width += image.width
                    max_height = max(max_height, image.height)

                # Create horizontal collage
                collage_image = Image.new('RGBA', (total_width, max_height))
                x_offset = 0
                for img in images:
                    collage_image.paste(img, (x_offset, 0))
                    x_offset += img.width

                # Convert to PNG bytes
                byte_arr = io.BytesIO()
                collage_image.save(byte_arr, format='PNG')
                item_data = byte_arr.getvalue()
                item_filename = ', '.join(chunk_filenames)
                group_msg = ', '.join(chunk_filenames)

            storage_items.append({
                'type': 'image/png file',
                'filename': item_filename,
                'data': item_data,
            })
            group_messages.append(group_msg)

        # Store all groups in user-specific storage
        with my_skills_storage.STORAGE_LOCK:
            if restored_chat_id not in my_skills_storage.STORAGE:
                my_skills_storage.STORAGE[restored_chat_id] = []
            my_skills_storage.STORAGE[restored_chat_id].extend(storage_items)

        # Generate response message
        msg_cards = "; ".join(group_messages)
        return (
            f"Assistant, as a professional tarologist, must write to the user what such a spread means, "
            f"the cards chosen are: {msg_cards}"
        )

    except Exception as e:
        # Error handling with full traceback
        traceback_error: str = traceback.format_exc()
        my_log.log_gemini_skills(
            f'send_tarot_cards: Unexpected error: {e}\n\n{traceback_error}\n\nchat_id: {chat_id}, num_cards: {num_cards}'
        )
        return f"FAIL: An unexpected error occurred while preparing tarot cards: {e}"


def save_natal_chart_to_image(name: str, date: str, time: str, place: str, nation: str, language: str, chat_id: str) -> str:
    """Generates a natal chart in PNG format based on the provided astrological data.

    This function uses the Kerykeion library to create a natal chart.
    Assistant should guess nation and language and ask for other parameters.

    Args:
        name (str): The name of the astrological subject (e.g., "Alexandra Ivanova").
        date (str): The birth date in 'YYYY-MM-DD' format (e.g., "1994-10-17").
        time (str): The birth time in 'HH:MM' format (e.g., "06:42").
        place (str): The city of birth, specified in English (e.g., "St. Petersburg").
        nation (str): The two-letter country code (e.g., "RU" for Russia, "US" for USA).
        language (str): The two-letter language code (e.g., "ru" for Russian, "en" for English).
        chat_id (str): The Telegram user chat ID where the file should be sent.

    Returns:
        str: 'OK' on success, or a 'FAIL' message.
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
        my_log.log_gemini_skills(f'Generating natal chart for "{name}, {date} {time}, {place}, {nation}, {language}" for chat_id: {chat_id}')

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
            my_log.log_gemini_skills(msg)
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
            return f"OK. Информация для трактовки изображения карты (ассистент, как профессиональный астролог с большим опытом, должен рассказать юзеру что на карте используя эти данные): {get_textual_astrological_report(subject)}"
        else:
            return "FAIL: Image bytes were not generated."

    except Exception as e:
        traceback_error = traceback.format_exc()
        my_log.log_gemini_skills(f'save_natal_chart_to_image: Unexpected error: {e}\n\n{traceback_error}\n\n{name}, {date}, {time}, {place}, {nation}, {chat_id}')
        return f"FAIL: An unexpected error occurred: {e}"


def query_user_file(query: str, user_id: str) -> str:
    '''
    Query saved user file (do not ask for full text, do not ask about images, it will only answer about saved text)

    Args:
        query: str - user query
        user_id: str - user id

    Returns:
        str
    '''
    user_id = my_skills_general.restore_id(user_id)
    if user_id not in my_skills_storage.STORAGE_ALLOWED_IDS or my_skills_storage.STORAGE_ALLOWED_IDS[user_id] != user_id:
        my_log.log_gemini_skills_query_file(f'/query_user_file "{query}" "{user_id}" - Unauthorized access detected.')
        return 'Unauthorized access detected. Did you send the correct user id?'

    my_log.log_gemini_skills_query_file(f'/query_user_file "{query}" "{user_id}"')

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


def query_user_logs(query: str, user_id: str) -> str:
    '''
    Query saved user logs (do not ask for full text, just answer the question).
    Log is the big history of user queries and assistant answers.

    Args:
        query: str - user query
        user_id: str - user id

    Returns:
        str
    '''
    user_id = my_skills_general.restore_id(user_id)

    if user_id not in my_skills_storage.STORAGE_ALLOWED_IDS or my_skills_storage.STORAGE_ALLOWED_IDS[user_id] != user_id:
        my_log.log_gemini_skills_query_file(f'/query_user_log "{query}" "{user_id}" - Unauthorized access detected.')
        return 'Unauthorized access detected. Did you send the correct user id?'

    my_log.log_gemini_skills_query_logs(f'/query_user_log "{query}" "{user_id}"')

    logs = my_log.get_user_logs(user_id)

    q = f'''Answer the user`s query using saved text(chat log) and your own mind, answer plain text with fancy markdown formatting, do not use code block for answer.

User query: {query}

Saved text: {logs}
'''

    temperature = my_db.get_user_property(user_id, 'temperature') or 1
    role = my_db.get_user_property(user_id, 'role') or ''

    result = my_gemini.ai(q[-my_gemini_general.MAX_SUM_REQUEST:], temperature=temperature, tokens_limit=8000, model = cfg.gemini25_flash_model, system=role)
    if not result:
        result = my_gemini.ai(q[-my_gemini_general.MAX_SUM_REQUEST:], temperature=temperature, tokens_limit=8000, model = cfg.gemini_flash_model, system=role)
    if not result:
        result = my_cohere.ai(q[-my_cohere.MAX_SUM_REQUEST:], system=role)
    if not result:
        result = my_mistral.ai(q[-my_mistral.MAX_SUM_REQUEST:], system=role)
    if not result:
        result = my_groq.ai(q[-my_groq.MAX_SUM_REQUEST:], temperature=temperature, max_tokens_ = 4000, system=role)

    if result:
        my_log.log_gemini_skills_query_logs(result)
        return result
    else:
        return 'No result was given.'


@cachetools.func.ttl_cache(maxsize=5, ttl=10*60)
def render_html_to_mp4_bytes(
    html: str,
    viewport_width: int,
    viewport_height: int,
    fps: int = 15,
    quality: int = 65,
    duration_seconds: float = 60.0,
    cut_external_assets: bool = False,
) -> bytes | None:
    """
    Render HTML to mp4 bytes.

    Args:
        html (str): HTML text to render.
        viewport_width (int): Width of viewport.
        viewport_height (int): Height of viewport.
        fps (int, optional): Frames per second. Defaults to 15.
        quality (int, optional): Quality of output video. Defaults to 65.
        duration_seconds (float, optional): Duration of output video in seconds. Defaults to 60.0.
        cut_external_assets (bool, optional): Cut external assets such as images, styles and scripts. Defaults to False.

    Returns:
        bytes | None: Bytes of rendered mp4 video or None if error occurred.
    """
    try:
        class _HashStopper:
            def __init__(self, stable_frames: int = 10):
                self.prev = None
                self.stable = 0
                self.need = stable_frames
            def push(self, b: bytes) -> bool:
                h = hashlib.md5(b).hexdigest()
                if self.prev is None:
                    self.prev = h
                    return False
                if h == self.prev:
                    self.stable += 1
                else:
                    self.stable = 0
                self.prev = h
                return self.stable >= self.need

        frames: List[np.ndarray] = []
        frame_times: List[float] = []
        stopper = _HashStopper(10)

        start = time.time()
        base_interval = max(1.0 / max(1, min(fps, 30)), 0.02)
        interval = base_interval
        last_t = start

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=['--disable-dev-shm-usage', '--disable-extensions']
            )
            page = browser.new_page(viewport={'width': viewport_width, 'height': viewport_height})

            if cut_external_assets:
                page.route('/**/*', lambda route: route.abort() if route.request.resource_type in ('image', 'font') else route.continue_())

            page.set_content(html, wait_until='domcontentloaded')
            page.evaluate("""
(() => {
  try {
    const all = document.querySelectorAll('*');
    for (const el of all) {
      const cs = getComputedStyle(el);
      const hasAnim = (cs.animationName && cs.animationName !== 'none') || (cs.transitionDuration && cs.transitionDuration !== '0s');
      if (hasAnim) {
        el.style.animationPlayState = 'paused';
      }
    }
  } catch(e) {}
  window.__ready_to_start = false;
  if (typeof window.__start !== 'function') {
    window.__start = () => {
      const all = document.querySelectorAll('*');
      for (const el of all) {
        const cs = getComputedStyle(el);
        const hasAnim = (cs.animationName && cs.animationName !== 'none');
        if (hasAnim) {
          el.style.animation = 'none';
          el.offsetHeight;
          el.style.animation = '';
          el.style.animationPlayState = 'running';
        }
      }
      window.__recording = true;
    };
  }
})();
""")
            page.evaluate("""
() => new Promise(async (resolve) => {
  try { if (document.fonts && document.fonts.ready) await document.fonts.ready; } catch(e) {}
  requestAnimationFrame(() => requestAnimationFrame(() => {
    window.__ready_to_start = true;
    resolve();
  }));
})
""")
            page.wait_for_function("() => window.__ready_to_start === true", timeout=5000)
            page.evaluate("() => { window.__start && window.__start(); }")

            first_shot = page.screenshot(full_page=False, type='jpeg', quality=int(max(1, min(100, quality))))
            im0 = Image.open(io.BytesIO(first_shot)).convert('RGB')
            arr0 = np.array(im0, copy=False)
            frames.append(arr0)
            frame_times.append(0.0)
            last_t = time.time()

            while True:
                now = time.time()
                if now - start >= duration_seconds:
                    break
                if now - last_t < interval:
                    time.sleep(0.005)
                    continue

                t0 = time.time()
                try:
                    shot = page.screenshot(full_page=False, type='jpeg', quality=int(max(1, min(100, quality))))
                except Exception:
                    time.sleep(0.02)
                    try:
                        shot = page.screenshot(full_page=False, type='jpeg', quality=int(max(1, min(100, quality))))
                    except Exception:
                        break

                im = Image.open(io.BytesIO(shot)).convert('RGB')
                arr = np.array(im, copy=False)
                frames.append(arr)

                dt = time.time() - t0
                frame_times.append(dt)
                last_t = now

                if len(frame_times) >= 5:
                    avg = sum(frame_times[-5:]) / 5.0
                    interval = max(base_interval, avg * 1.5)

                if len(frames) > 12 and stopper.push(shot):
                    break

            browser.close()

        if not frames:
            return None

        total = max(time.time() - start, 1e-6)
        real_fps = max(1, min(30, int(round(len(frames) / total)) or fps))

        fd, tmp_path = tempfile.mkstemp(suffix='.mp4')
        os.close(fd)

        workdir = tempfile.mkdtemp(prefix="html2anim_")
        raw_list_path = os.path.join(workdir, "frames.txt")

        try:
            h = viewport_height
            w = viewport_width
            delays = [1.0 / real_fps] * len(frames)
            with open(raw_list_path, "w", encoding="utf-8") as f:
                for i, fr in enumerate(frames):
                    img_path = os.path.join(workdir, f"frame_{i:06d}.jpg")
                    if fr.shape[1] != w or fr.shape[0] != h:
                        _img = Image.fromarray(fr).resize((w, h), Image.Resampling.BILINEAR)
                        _img.save(img_path, "JPEG", quality=max(1, min(100, quality)))
                    else:
                        _img = Image.fromarray(fr)
                        _img.save(img_path, "JPEG", quality=max(1, min(100, quality)))
                    f.write(f"file '{img_path}'\n")
                    f.write(f"duration {delays[i]:.6f}\n")
                f.write(f"file '{img_path}'\n")

            cmd = [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel", "error",
                "-f", "concat",
                "-safe", "0",
                "-r", str(real_fps),
                "-i", raw_list_path,
                "-vf", f"scale={w}:{h}:flags=bicubic",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                tmp_path
            ]

            try:
                subprocess.run(cmd, check=True)
            except subprocess.CalledProcessError:
                pass
            if not (os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0):
                utils.remove_file(tmp_path)
                utils.remove_dir(workdir)
                return None

            with open(tmp_path, 'rb') as f:
                mp4_bytes = f.read()

            utils.remove_file(tmp_path)
            utils.remove_dir(workdir)
            return mp4_bytes if mp4_bytes else None

        except Exception:
            try:
                utils.remove_dir(workdir)
            except Exception:
                pass
            try:
                utils.remove_file(tmp_path)
            except Exception:
                pass
            raise

    except Exception as e:
        tb = traceback.format_exc()
        my_log.log_gemini_skills_html(
            f'render_html_to_mp4_bytes: Unexpected error: {e}\n\n{tb}\n\n{html[:2000]}'
        )
        return None


def save_html_to_animation(
    filename: str,
    chat_id: str,
    html: str,
    viewport_width: int,
    viewport_height: int,
) -> str:
    """
    Save (render) HTML code to mp4 video file and send it to the user.

    Important:
    - Do NOT use infinite animations. Avoid `animation-iteration-count: infinite` and endless JS loops.
    - All motion must complete within a finite time (target <= 60 seconds).
    - If looping is needed, repeat a fixed number of cycles (e.g., 3), not infinite.

    Authoring rules for HTML:
    - Page must become visually ready without user input.
    - Keep animations bounded in time. Example (CSS):
        animation-iteration-count: 3;  /* not infinite */
    - For JS-driven motion, stop explicitly (setTimeout/Promise) before 60s.
    - Minimize heavy external assets; inline when possible.

    Args:
        filename (str): Desired video filename ('.mp4' will be appended if missing).
        chat_id (str): Telegram chat ID of the user requesting the video.
        html (str): Fully-formed HTML producing a finite animation (<60s).
        viewport_width (int): Viewport width in pixels (max 1920).
        viewport_height (int): Viewport height in pixels (max 1080).

    Returns:
        str: 'OK' or 'FAILED'
    """

    my_log.log_gemini_skills_html(
        f'"{chat_id} {filename} {viewport_width}x{viewport_height}"\n\n"{html}"'
    )

    chat_id = my_skills_general.restore_id(chat_id)
    if chat_id == '[unknown]':
        return "FAIL, unknown chat id"

    if not filename.lower().endswith('.mp4'):
        filename += '.mp4'
    filename = utils.safe_fname(filename)

    mp4_bytes = render_html_to_mp4_bytes(
        html=html,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
        fps=15,
        quality=65,
        duration_seconds=60.0,
        cut_external_assets=False,
    )

    if not mp4_bytes:
        return "FAILED"

    item = {
        'type': 'video/mp4 file',
        'filename': filename,
        'data': mp4_bytes,
    }
    try:
        with my_skills_storage.STORAGE_LOCK:
            if chat_id in my_skills_storage.STORAGE:
                if item not in my_skills_storage.STORAGE[chat_id]:
                    my_skills_storage.STORAGE[chat_id].append(item)
            else:
                my_skills_storage.STORAGE[chat_id] = [item]
        return "OK"
    except Exception as e:
        tb = traceback.format_exc()
        my_log.log_gemini_skills_html(
            f'save_html_to_animation: storage error: {e}\n\n{tb}'
        )
        return "FAILED"


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
        str: Help mеssage
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
    """
    Return JSON with all currency rates from https://openexchangerates.org.

    Args:
        date (str): Date in YYYY-MM-DD format, if absent then latest.

    Returns:
        str: JSON string containing currency rates.
    """
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


LIMIT_ANSWER_LEN = 60000
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
        return r[:LIMIT_ANSWER_LEN]
    except Exception as error:
        my_log.log_gemini_skills_search(f'search_google_deep:Error: {error}')
        return f'ERROR {error}'


@cachetools.func.ttl_cache(maxsize=10, ttl=60 * 60)
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
