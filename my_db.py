#!/usr/bin/env python3


import datetime
import gzip
import hashlib
import io
import lzma
import matplotlib
import pickle
import pprint
import time
import threading
import traceback
import shutil
import sqlite3
import sys
from typing import List, Tuple, Dict, Optional

matplotlib.use('Agg') #  Отключаем вывод графиков на экран
import matplotlib.pyplot as plt
from collections import OrderedDict
import matplotlib.dates as mdates

from cachetools import LRUCache

import my_log
import utils
from utils import async_run


LOCK = threading.Lock()

CON = None
CUR = None
COM_COUNTER = 0
DAEMON_RUN = True
DAEMON_TIME = 30


# Serialize and compress an object
def obj_to_blob(obj):
    if obj is None:
        return None
    else:
        try:
            return lzma.compress(pickle.dumps(obj))
        except Exception as error:
            my_log.log2(f'my_db:obj_to_blob {error}')
            return None


# De-serialize and decompress an object
def blob_to_obj(blob):
    if blob:
        try:
            return pickle.loads(lzma.decompress(blob))
        except Exception as error:
            my_log.log2(f'my_db:blob_to_obj {error}')
            return None
    else:
        return None


class SmartCache:
    def __init__(self, max_size = 1000, max_value_size = 1024*10): # 1000*10kb=10mb!
        self.cache = LRUCache(maxsize=max_size)
        self.max_value_size = max_value_size
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            value = self.cache.get(key)
        return value

    def set(self, key, value):
        value_size = sys.getsizeof(value)
        if value_size <= self.max_value_size:
            with self.lock:
                self.cache[key] = value
        else:
            self.delete(key)

    def delete(self, key):
        with self.lock:
            if key in self.cache:
                del self.cache[key]


# cache for users table
USERS_CACHE = SmartCache()


def backup_db():
    try:
        with open('db/main.db', 'rb') as f_in, gzip.open('db/main.db.gz', 'wb', compresslevel=1) as f_out:
            shutil.copyfileobj(f_in, f_out)
    except Exception as error:
        my_log.log2(f'my_db:compress_backup_db {error}')


@async_run
def sync_daemon():
    global COM_COUNTER
    while DAEMON_RUN:
        time.sleep(DAEMON_TIME)
        try:
            with LOCK:
                if COM_COUNTER > 0:
                    CON.commit()
                    COM_COUNTER = 0
        except Exception as error:
            my_log.log2(f'my_db:sync_daemon {error}')


def init(backup: bool = True):
    '''init db'''
    global CON, CUR
    day_seconds = 60 * 60 * 24
    week_seconds = day_seconds * 7
    month_seconds = day_seconds * 30
    year_seconds = day_seconds * 365
    try:
        if backup:
            backup_db()
        CON = sqlite3.connect('db/main.db', check_same_thread=False)
        CUR = CON.cursor()

        CUR.execute('''
            CREATE TABLE IF NOT EXISTS msg_counter (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                access_time REAL,
                model_used TEXT
            )
        ''')
        CUR.execute('''DELETE FROM msg_counter WHERE access_time < ?''', (time.time() - year_seconds,))
        CUR.execute('CREATE INDEX IF NOT EXISTS idx_access_time ON msg_counter (access_time)')
        CUR.execute('CREATE INDEX IF NOT EXISTS idx_user_id ON msg_counter (user_id)')
        CUR.execute('CREATE INDEX IF NOT EXISTS idx_model_used ON msg_counter (model_used)')

        CUR.execute('''
            CREATE TABLE IF NOT EXISTS translations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original TEXT,
                lang TEXT,
                help TEXT,
                translation TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        CUR.execute('CREATE INDEX IF NOT EXISTS idx_original ON translations (original)')
        CUR.execute('CREATE INDEX IF NOT EXISTS idx_lang ON translations (lang)')
        CUR.execute('CREATE INDEX IF NOT EXISTS idx_help ON translations (help)')
        CUR.execute('CREATE INDEX IF NOT EXISTS idx_translation ON translations (translation)')
        # CUR.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON translations (timestamp)')

        CUR.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id_num INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT,
                lang TEXT,
                first_meet REAL,
                last_time_access REAL,
                telegram_stars INTEGER,

                image_generated_counter INTEGER,

                saved_file TEXT,
                saved_file_name TEXT,

                blocked INTEGER,
                blocked_bing INTEGER,
                blocked_totally INTEGER,
                auto_leave_chat INTEGER,

                auto_translations INTEGER,
                tts_gender TEXT,
                suggest_enabled INTEGER,
                chat_enabled INTEGER,
                original_mode INTEGER,
                ocr_lang TEXT,
                superchat INTEGER,
                transcribe_only INTEGER,
                command_mode TEXT,
                voice_only_mode INTEGER,
                disabled_kbd INTEGER,

                chat_mode TEXT,
                role TEXT,
                temperature REAL,
                bot_name TEXT,
                persistant_memory TEXT,

                api_key_gemini TEXT,
                api_key_groq TEXT,
                api_key_deepl TEXT,
                api_key_huggingface TEXT,

                dialog_gemini BLOB,
                dialog_groq BLOB,
                dialog_openrouter BLOB,
                dialog_shadow BLOB,
                dialog_gpt4omini BLOB
            )
        ''')
        CUR.execute('CREATE INDEX IF NOT EXISTS idx_id ON users (id)')
        CUR.execute('CREATE INDEX IF NOT EXISTS idx_first_meet ON users (first_meet)')
        # удалить файлы старше 1 дня и диалоги старше 1 недели
        CUR.execute("""UPDATE users SET saved_file = NULL,
                    saved_file_name = NULL WHERE last_time_access < ?
                    """, (time.time() - day_seconds,))
        CUR.execute("""UPDATE users SET dialog_gemini = NULL,
                    dialog_groq = NULL,
                    dialog_openrouter = NULL,
                    dialog_shadow = NULL,
                    persistant_memory = NULL
                    WHERE last_time_access < ?
                    """, (time.time() - week_seconds,))

        CUR.execute('''
            CREATE TABLE IF NOT EXISTS sum (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date REAL,
                url TEXT,
                text TEXT
            )
        ''')

        CUR.execute('''
            CREATE TABLE IF NOT EXISTS im_suggests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date REAL,
                hash TEXT,
                prompt TEXT
            )
        ''')

        if backup:
            CON.commit()
            CUR.execute("VACUUM")
        CON.commit()
        sync_daemon()
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'my_db:init {error}\n\n{traceback_error}')


def close():
    global DAEMON_RUN
    DAEMON_RUN = False
    time.sleep(DAEMON_TIME + 2)
    with LOCK:
        try:
            CON.commit()
            # CON.close()
        except Exception as error:
            my_log.log2(f'my_db:close {error}')


@async_run
def add_msg(user_id: str, model_used: str, timestamp: float = None):
    '''add msg counter record to db'''
    global COM_COUNTER
    with LOCK:
        try:
            access_time = timestamp if timestamp else time.time()
            
            # Проверка наличия записи
            CUR.execute('''
                SELECT COUNT(*) FROM msg_counter
                WHERE user_id = ? AND access_time = ? AND model_used = ?
            ''', (user_id, access_time, model_used))
            
            if CUR.fetchone()[0] == 0:
                # Если записи нет, добавляем новую
                CUR.execute('''
                    INSERT INTO msg_counter (user_id, access_time, model_used)
                    VALUES (?, ?, ?)
                ''', (user_id, access_time, model_used))
                COM_COUNTER += 1

        except Exception as error:
            my_log.log2(f'my_db:add {error}')


def count_msgs(user_id: str, model: str, access_time: float):
    '''Count the number of messages sent by a user since a specified access time.

    access_time - seconds before now (60*60*24*30 - 30 days)

    print(count_msgs('user1', 'all', 60*60*24*30)) - print all messages sent by user1 in the last 30 days
    '''
    access_time = time.time() - access_time
    with LOCK:
        try:
            if model == 'all':
                CUR.execute('''
                    SELECT COUNT(*) FROM msg_counter
                    WHERE user_id = ? AND access_time > ?
                ''', (user_id, access_time))
            else:
                CUR.execute('''
                    SELECT COUNT(*) FROM msg_counter
                    WHERE user_id = ? AND model_used = ? AND access_time > ?
                ''', (user_id, model, access_time))
            return CUR.fetchone()[0]
        except Exception as error:
            my_log.log2(f'my_db:count {error}')
            return 0


def count_msgs_all():
    '''count all messages'''
    with LOCK:
        try:
            CUR.execute('''
                SELECT COUNT(*) FROM msg_counter
            ''')
            return CUR.fetchone()[0]
        except Exception as error:
            my_log.log2(f'my_db:count_all {error}')
            return 0


def get_model_usage(days: int):
    access_time = time.time() - days * 24 * 60 * 60
    with LOCK:
        try:
            CUR.execute('''
                SELECT model_used, COUNT(*) FROM msg_counter
                WHERE access_time > ?
                GROUP BY model_used
            ''', (access_time,))
            results = CUR.fetchall()
            model_usage = {}
            for row in results:
                model = row[0]
                usage_count = row[1]
                model_usage[model] = usage_count
            return model_usage
        except Exception as error:
            my_log.log2(f'my_db:get_model_usage {error}')
            return {}


def get_model_usage_for_days(num_days: int) -> List[Tuple[str, Dict[str, int]]]:
    """
    Retrieves model usage data for the past num_days, excluding the current day.
    Includes image generation counts.
    Data is sorted from oldest to newest.

    Args:
        num_days: The number of past days to retrieve data for.

    Returns:
        A list of tuples, where each tuple contains:
        - The date (YYYY-MM-DD)
        - A dictionary of model usage counts for that date, including image generation.
        Returns an empty list if there is an error or no data.
    """

    end_date = datetime.date.today() - datetime.timedelta(days=1)
    usage_data: List[Tuple[str, Dict[str, int]]] = []

    for i in range(num_days - 1, -1, -1):
        current_date = end_date - datetime.timedelta(days=i)
        date_str = current_date.strftime("%Y-%m-%d")
        start_timestamp = time.mktime(current_date.timetuple())
        end_timestamp = start_timestamp + 24 * 60 * 60

        model_usage: Dict[str, int] = {} # Initialize model_usage here

        with LOCK:
            try:
                # Existing model usage query (msg_counter table)
                CUR.execute('''
                    SELECT model_used, COUNT(*) FROM msg_counter
                    WHERE access_time >= ? AND access_time < ?
                    GROUP BY model_used
                ''', (start_timestamp, end_timestamp))
                results = CUR.fetchall()
                
                for row in results:
                    model = row[0]
                    usage_count = row[1]
                    model_usage[model] = usage_count

                usage_data.append((date_str, model_usage))

            except Exception as error:
                my_log.log2(f'my_db:get_model_usage_for_days {error}')
                return []

    return usage_data


def visualize_usage(usage_data: List[Tuple[str, Dict[str, int]]], mode: str = 'llm') -> Optional[bytes]:
    """
    Visualizes model usage data over time.

    Args:
        usage_data: A list of tuples, where each tuple contains:
            - The date (YYYY-MM-DD) as a string.
            - A dictionary of model usage counts for that date,
              where keys are model names (str) and values are counts (int).
        mode: The visualization mode ('llm' or 'img'). If 'llm', only non-image models are plotted. If 'img', only image models are plotted.

    Returns:
        A byte string containing the PNG image data of the generated plot,
        or None if the input data is empty.
    """

    if not usage_data:  # Check for empty input data
        my_log.log2('my_db:visualize_usage: No data to visualize.')
        return None

    dates: List[str] = [data[0] for data in usage_data]  # Extract dates
    models: List[str] = sorted(set(
        model for date, usage in usage_data for model in usage
    ))  # Extract unique model names
    model_counts: Dict[str, List[int]] = {model: [] for model in models}  # Initialize count lists for each model

    # Populate data lists
    for date, usage in usage_data:
        for model in models:
            model_counts[model].append(usage.get(model, 0))  # Get count or default to 0

    fig, ax = plt.subplots(figsize=(10, 6))  # Create figure and axis

    # Plot model usage 
    for model in models:
        if mode == 'llm':
            if model.startswith('img '):
                continue
        elif mode == 'img':
            if not model.startswith('img '):
                continue
        ax.plot(dates, model_counts[model], label=model, marker='o')

    ax.set_xlabel("Date")  # Set x-axis label
    ax.set_ylabel("Usage Count")  # Set y-axis label
    ax.set_title("Model Usage Over Time")  # Set plot title
    ax.grid(axis='y', linestyle='--')  # Add horizontal grid lines
    ax.tick_params(axis='x', rotation=45, labelsize=8)  # Rotate x-axis labels for better readability

    # Adjust x-axis ticks if too many dates
    if len(dates) > 10:
        step: int = len(dates) // 10  # Calculate step size for ticks
        ax.set_xticks(dates[::step])    # Set x-axis ticks

    ax.legend(fontsize='small')  # Display legend

    plt.tight_layout()  # Adjust layout for better spacing

    # Save plot to byte buffer
    buf = io.BytesIO()   # Create in-memory byte buffer
    plt.savefig(buf, format="png", dpi=150, bbox_inches='tight') # Save plot to buffer as PNG
    buf.seek(0)            # Reset buffer position
    image_bytes: bytes = buf.read() # Read image bytes from buffer
    buf.close()           # Close buffer
    return utils.compress_png_bytes(image_bytes) # Return compressed PNG image bytes


def get_total_msg_users() -> int:
    with LOCK:
        try:
            CUR.execute('''
                SELECT COUNT(DISTINCT user_id) FROM msg_counter
            ''')
            return CUR.fetchone()[0]
        except Exception as error:
            my_log.log2(f'my_db:get_total_msg_users {error}')
            return 0


def get_total_msg_users_in_days(days: int) -> int:
    access_time = time.time() - days * 24 * 60 * 60
    with LOCK:
        try:
            CUR.execute('''
                SELECT COUNT(DISTINCT user_id) FROM msg_counter
                WHERE access_time > ?
            ''', (access_time,))
            return CUR.fetchone()[0]
        except Exception as error:
            my_log.log2(f'my_db:get_total_msg_users_in_days {error}')
            return 0


def count_new_user_in_days(days: int) -> int:
    '''Посчитать сколько юзеров впервые написали боту раньше чем за days дней'''
    access_time = time.time() - days * 24 * 60 * 60
    with LOCK:
        try:
            CUR.execute('''
                SELECT COUNT(DISTINCT T1.user_id)
                FROM msg_counter AS T1
                INNER JOIN users AS T2 ON T1.user_id = T2.id
                WHERE T2.first_meet > ?
            ''', (access_time,))
            return CUR.fetchone()[0]
        except Exception as error:
            my_log.log2(f'my_db:count_new_user_in_days {error}')
            return 0


def get_new_users_for_last_days(days: int) -> OrderedDict:
    """
    Retrieves the number of new users for each of the past `days` from the database.

    Args:
        days: The number of past days to retrieve data for.

    Returns:
        An OrderedDict containing the number of new users for each day.
        The keys are date strings in "YYYY-MM-DD" format, and the values are the
        corresponding new user counts. The dates are ordered from oldest to newest.
    """

    result = OrderedDict()
    today = datetime.date.today()
    with LOCK:
        try:
            for i in range(days - 1, -1, -1):
                date_obj = today - datetime.timedelta(days=i)
                date_str = date_obj.strftime("%Y-%m-%d")
                start_timestamp = time.mktime(date_obj.timetuple())
                end_timestamp = start_timestamp + 24 * 60 * 60

                CUR.execute('''
                    SELECT COUNT(DISTINCT T1.user_id)
                    FROM msg_counter AS T1
                    INNER JOIN users AS T2 ON T1.user_id = T2.id
                    WHERE T2.first_meet >= ? AND T2.first_meet < ?
                ''', (start_timestamp, end_timestamp))
                new_users_count = CUR.fetchone()[0]
                result[date_str] = new_users_count

        except Exception as error:
            my_log.log2(f'my_db:get_new_users_for_last_days {error}')

    if result:  # Проверяем, не пустой ли словарь
        result.popitem() # Удаляем последний элемент

    return result


def get_users_for_last_days(days: int) -> OrderedDict:
    """
    Retrieves the number of active users for each of the past `days`, excluding today.

    Args:
        days: The number of past days to retrieve data for (excluding today).

    Returns:
        An OrderedDict containing the number of active users for each day. 
        The keys are date strings in "YYYY-MM-DD" format, and the values are the 
        corresponding user counts. The dates are ordered from oldest to newest.
        Returns an empty OrderedDict if days is less than or equal to zero.
    """

    result = OrderedDict()
    for i in range(days - 1, -1, -1):  # Итерация в обратном порядке
        date_obj = datetime.date.today() - datetime.timedelta(days=i)
        date_str = date_obj.strftime("%Y-%m-%d")
        try:
            start_timestamp = time.mktime(date_obj.timetuple())
            end_timestamp = start_timestamp + 24 * 60 * 60

            with LOCK:
                CUR.execute('''
                    SELECT COUNT(DISTINCT user_id) FROM msg_counter
                    WHERE access_time >= ? AND access_time < ?
                ''', (start_timestamp, end_timestamp))
                users_count = CUR.fetchone()[0]
        except Exception as error:
            my_log.log2(f'my_db:get_users_for_last_days {error}')
            users_count = 0

        result[date_str] = users_count

    if result:  # Проверяем, не пустой ли словарь
        result.popitem() # Удаляем последний элемент

    return result # Возвращаем OrderedDict


def draw_user_activity(days: int = 90) -> bytes:
    """
    Generates a chart of user activity with English labels and comments.

    Args:
        days: The number of days for which to generate the chart. Defaults to 90.

    Returns:
        Bytes of the chart image in PNG format.
    """

    data = get_users_for_last_days(days)
    new_users_data = get_new_users_for_last_days(days)

    dates = list(data.keys())
    x_dates = [datetime.datetime.strptime(d, "%Y-%m-%d").date() for d in dates]
    active_users = list(data.values())
    new_users = list(new_users_data.values())

    fig, ax1 = plt.subplots(figsize=(10, 6), facecolor='white')

    # Plot active users on the primary y-axis
    ax1.plot(x_dates, active_users, marker='o', color='#4C72B0', label='Active Users', alpha=0.7)
    ax1.set_xlabel("Date", fontsize=12)
    ax1.set_ylabel("Active Users", fontsize=12, color='#4C72B0')
    ax1.tick_params(axis='y', labelcolor='#4C72B0')

    # Create a secondary y-axis for new users
    ax2 = ax1.twinx()
    ax2.plot(x_dates, new_users, marker='x', linestyle='--', color='#C44E52', label='New Users', alpha=0.7)
    ax2.set_ylabel("New Users", fontsize=12, color='#C44E52')
    ax2.tick_params(axis='y', labelcolor='#C44E52')

    # Set chart title and grid
    ax1.set_title(f"User Activity for the Last {days} Days", fontsize=14)
    ax1.grid(axis='y', linestyle='--', alpha=0.3)  # Lighter grid lines
    ax2.grid(False) # Turn off grid for the secondary axis


    # Format x-axis dates
    ax1.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    fig.autofmt_xdate()

    # Combine legends for both axes
    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(handles1 + handles2, labels1 + labels2, loc="upper left")

    # Save the plot to a bytes buffer
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches='tight') # Increased DPI for better quality
    buf.seek(0)
    image_bytes = buf.read()
    buf.close()

    return utils.compress_png_bytes(image_bytes)


def get_translation(text: str, lang: str, help: str) -> str:
    '''Get translation from cache if any'''
    with LOCK:
        try:
            CUR.execute('''
                SELECT translation FROM translations
                WHERE original = ? AND lang = ? AND help = ?
            ''', (text, lang, help))
            result = CUR.fetchone()
            return result[0] if result else ''
        except Exception as error:
            my_log.log2(f'my_db:get_translation {error}')
            return ''


def update_translation(text: str, lang: str, help: str, translation: str):
    '''Update or insert translation in cache'''
    global COM_COUNTER
    with LOCK:
        try:
            CUR.execute('''
                SELECT 1 FROM translations
                WHERE original = ? AND lang = ? AND help = ?
            ''', (text, lang, help))
            if CUR.fetchone():
                CUR.execute('''
                    UPDATE translations
                    SET translation = ?
                    WHERE original = ? AND lang = ? AND help = ?
                ''', (translation, text, lang, help))
            else:
                CUR.execute('''
                    INSERT INTO translations (original, lang, help, translation)
                    VALUES (?, ?, ?, ?)
                ''', (text, lang, help, translation))
            COM_COUNTER += 1
        except Exception as error:
            my_log.log2(f'my_db:update_translation {error}')


def update_translations(values: list):
    '''Update many translations in cache
    values - list of tuples (text, lang, help, translation)
    '''
    global COM_COUNTER
    drop_all_translations()
    with LOCK:
        try:
            # Выполняем один запрос для вставки данных
            CUR.executemany('''
                INSERT INTO translations (original, lang, help, translation)
                VALUES (?, ?, ?, ?)
            ''', values)
            COM_COUNTER += len(values)
        except Exception as error:
            my_log.log2(f'my_db:update_translations {error}')


def get_translations_like(text: str) -> list:
    '''Get translations from cache that are similar to the given text'''
    with LOCK:
        try:
            CUR.execute('''
                SELECT original, lang, help, translation FROM translations
                WHERE translation LIKE ?
            ''', (f'%{text}%',))
            results = CUR.fetchall()
            return results or []
        except Exception as error:
            my_log.log2(f'my_db:get_translations_like {error}')
            return []


def get_translations_count() -> int:
    '''Get count of translations'''
    with LOCK:
        try:
            CUR.execute('''
                SELECT COUNT(*) FROM translations
            ''')
            result = CUR.fetchone()
            return result[0] if result else 0
        except Exception as error:
            my_log.log2(f'my_db:get_translations_count {error}')
            return 0


def drop_all_translations():
    '''Drop all translations from cache'''
    with LOCK:
        try:
            CUR.execute('''
                DELETE FROM translations
            ''')
        except Exception as error:
            my_log.log2(f'my_db:drop_all_translations {error}')


def vacuum():
    '''Vacuum database'''
    with LOCK:
        try:
            CUR.execute('''
                VACUUM
            ''')
            CON.commit()
        except Exception as error:
            my_log.log2(f'my_db:vacuum {error}')


def drop_long_translations():
    '''Drop long translations from cache'''
    with LOCK:
        try:
            CUR.execute('''
                DELETE FROM translations
                WHERE LENGTH(translation) > 200
            ''')
        except Exception as error:
            my_log.log2(f'my_db:drop_long_translations {error}')


def get_first_meet(user_id):
    '''Get first meet time of user'''
    try:
        pass
        # надо найти самое первое сообщение от юзера в таблице msg_counter
        CUR.execute('''
            SELECT MIN(access_time) FROM msg_counter
            WHERE user_id = ?
        ''', (user_id,))
        result = CUR.fetchone()
        if result and result[0]:
            return result[0]
        else:
            return None
    except Exception as error:
        my_log.log2(f'my_db:get_first_meet {error}')
        return None


def get_user_property(user_id: str, property: str):
    '''Get a value of property in user table
    Return None if user not found
    '''
    cache_key = hashlib.md5(f"{user_id}_{property}".encode()).hexdigest()
    if cache_key in USERS_CACHE.cache:
        return USERS_CACHE.get(cache_key)
    else:
        with LOCK:
            try:
                CUR.execute(f'''
                    SELECT {property} FROM users
                    WHERE id = ?
                ''', (user_id,))
                result = CUR.fetchone()
                if result:
                    USERS_CACHE.set(cache_key, result[0])
                    return result[0]
                else:
                    return None
            except Exception as error:
                my_log.log2(f'my_db:get_user_property {error}')
                return None


def get_user_all_bad_ids():
    '''get users ids if blocked = True'''
    with LOCK:
        try:
            CUR.execute('''
                SELECT id FROM users
                WHERE blocked = 1
            ''')
            result = CUR.fetchall()
            return [x[0] for x in result]
        except Exception as error:
            my_log.log2(f'my_db:get_user_all_bad_ids {error}')
            return []


def get_user_all_bad_bing_ids():
    '''get users ids if blocked_bing = True'''
    with LOCK:
        try:
            CUR.execute('''
                SELECT id FROM users
                WHERE blocked_bing = 1
            ''')
            result = CUR.fetchall()
            return [x[0] for x in result]
        except Exception as error:
            my_log.log2(f'my_db:get_user_all_bad_bing_ids {error}')
            return []


def get_user_all_bad_totally_ids():
    '''get users ids if blocked_totally = True'''
    with LOCK:
        try:
            CUR.execute('''
                SELECT id FROM users
                WHERE blocked_totally = 1
            ''')
            result = CUR.fetchall()
            return [x[0] for x in result]
        except Exception as error:
            my_log.log2(f'my_db:get_user_all_bad_totally_ids {error}')
            return []


def delete_user_property(user_id: str, property: str):
    '''Delete user`s property value'''
    global COM_COUNTER
    cache_key = hashlib.md5(f"{user_id}_{property}".encode()).hexdigest()
    if cache_key in USERS_CACHE.cache:
        USERS_CACHE.delete(cache_key)
    with LOCK:
        try:
            # Проверяем, существует ли пользователь
            CUR.execute('''
                SELECT 1 FROM users
                WHERE id = ?
            ''', (user_id,))
            if CUR.fetchone():
                # Проверяем, есть ли у property
                CUR.execute(f'''
                    SELECT 1 FROM users
                    WHERE id = ? AND {property} IS NOT NULL
                ''', (user_id,))
                if CUR.fetchone():
                    # Удаляем
                    CUR.execute(f'''
                        UPDATE users
                        SET {property} = NULL
                        WHERE id = ?
                    ''', (user_id,))
                    COM_COUNTER += 1
            else:
                my_log.log2(f'my_db:delete_property - User {user_id} not found')
        except Exception as error:
            my_log.log2(f'my_db:delete_property {error}')


def set_user_property(user_id: str, property: str, value):
    '''Set user`s property'''
    global COM_COUNTER
    cache_key = hashlib.md5(f"{user_id}_{property}".encode()).hexdigest()
    USERS_CACHE.set(cache_key, value)
    with LOCK:
        try:
            # Проверяем, есть ли пользователь в базе
            CUR.execute('''
                SELECT 1 FROM users
                WHERE id = ?
            ''', (user_id,))
            if CUR.fetchone():
                # Обновляем если пользователь уже существует
                CUR.execute(f'''
                    UPDATE users
                    SET {property} = ?
                    WHERE id = ?
                ''', (value, user_id))
            else:
                # Добавляем нового пользователя, если его нет
                first_meet = get_first_meet(user_id) or time.time()
                CUR.execute(f'''
                    INSERT INTO users (id, {property}, first_meet)
                    VALUES (?, ?, ?)
                ''', (user_id, value, first_meet))
            COM_COUNTER += 1
        except Exception as error:
            my_log.log2(f'my_db:set_user_property {error}')


def get_all_users_ids():
    '''Get all users ids'''
    with LOCK:
        try:
            CUR.execute('''
                SELECT id FROM users
            ''')
            results = CUR.fetchall()
            return [result[0] for result in results]
        except Exception as error:
            my_log.log2(f'my_db:get_all_users_ids {error}')
            return []


def set_sum_cache(url, text):
    '''Set sum cache'''
    global COM_COUNTER
    with LOCK:
        try:
            # проверяем есть ли в таблице sum такая запись
            CUR.execute('''
                SELECT 1 FROM sum
                WHERE url = ?
            ''', (url,))
            if CUR.fetchone():
                # если есть, то обновляем
                CUR.execute('''
                    UPDATE sum
                    SET text = ?,
                    date = ?
                    WHERE url = ?
                ''', (text, time.time(), url))
            else:
                # если нет, то добавляем
                CUR.execute('''
                    INSERT INTO sum (url, date, text)
                    VALUES (?, ?, ?)
                ''', (url, time.time(), text))
            # remove old records
            CUR.execute('''
                DELETE FROM sum
                WHERE date < ?
            ''', (time.time() - 60*60*24*30,))
            COM_COUNTER += 1
        except Exception as error:
            my_log.log2(f'my_db:set_sum_cache {error}')


def get_from_sum(url: str) -> str:
    '''Get from sum'''
    with LOCK:
        try:
            CUR.execute('''
                SELECT text FROM sum
                WHERE url = ?
            ''', (url,))
            result = CUR.fetchone()
            if result is None:
                return ''
            return result[0]
        except Exception as error:
            my_log.log2(f'my_db:get_from_sum {error}')
            return ''


def delete_from_sum(url_id: str):
    '''Remove from sum'''
    with LOCK:
        try:
            CUR.execute('''
                DELETE FROM sum
                WHERE url = ?
            ''', (url_id,))
        except Exception as error:
            my_log.log2(f'my_db:remove_from_sum {error}')


def set_im_suggests(hash, prompt):
    '''Set im_suggests'''
    global COM_COUNTER
    with LOCK:
        try:
            # проверяем есть ли в таблице im_suggests такая запись
            CUR.execute('''
                SELECT 1 FROM im_suggests
                WHERE hash = ?
            ''', (hash,))
            if CUR.fetchone():
                # если есть, то обновляем
                CUR.execute('''
                    UPDATE im_suggests
                    SET prompt = ?,
                    date = ?
                    WHERE hash = ?
                ''', (prompt, time.time(), hash))
            else:
                # если нет, то добавляем
                CUR.execute('''
                    INSERT INTO im_suggests (hash, date, prompt)
                    VALUES (?, ?, ?)
                ''', (hash, time.time(), prompt))
            # remove old records
            CUR.execute('''
                DELETE FROM im_suggests
                WHERE date < ?
            ''', (time.time() - 60*60*24*30,))
            COM_COUNTER += 1
        except Exception as error:
            my_log.log2(f'my_db:set_im_suggests {error}')


def get_from_im_suggests(hash: str) -> str:
    '''Get from im_suggests'''
    with LOCK:
        try:
            CUR.execute('''
                SELECT prompt FROM im_suggests
                WHERE hash = ?
            ''', (hash,))
            result = CUR.fetchone()
            if result is None:
                return ''
            return result[0]
        except Exception as error:
            my_log.log2(f'my_db:get_from_im_suggests {error}')
            return ''


def delete_from_im_suggests(hash: str):
    '''Remove from im_suggests'''
    with LOCK:
        try:
            CUR.execute('''
                DELETE FROM im_suggests
                WHERE hash = ?
            ''', (hash,))
        except Exception as error:
            my_log.log2(f'my_db:remove_from_im_suggests {error}')


if __name__ == '__main__':
    pass
    init(backup=False)


    usage_data = get_model_usage_for_days(90)  # Get data for the past 7 days
    with open('d:/downloads/1.png', 'wb') as f:
        f.write(visualize_usage(usage_data))


    # pprint.pprint(get_new_users_for_last_days(90))

    # with open('d:/downloads/1.png', 'wb') as f:
        # f.write(draw_user_activity(90))

    # a='xg'*100000
    # b = obj_to_blob(a)
    # print(len(b))
    # print(blob_to_obj(b))
    

    # set_sum_cache('test', 'test123')
    # print(get_from_sum('test'))
    # delete_from_sum('test')
    # delete_from_sum('test1')
    # print(get_from_sum('test'))



    # print(get_user_all_bad_ids())

    # import random
    # USERS_CACHE = SmartCache(10000)
    # time_start = time.time()
    # counter_last = 0
    # for x in range(10000000000000):
    #     USERS_CACHE.set(x, str(x) + 'value10'*100)

    #     for y in range(1, random.randint(1, 5)):
    #         a = USERS_CACHE.get(x)

    #     if time.time() - time_start > 1:
    #         print(x - counter_last, end='\r')
    #         counter_last = x
    #         time_start = time.time()


    # print(get_all_users_ids())

    # vacuum()

    # print(get_translation(text='test2', lang='ru', help=''))
    # update_translation(text='test2', lang='ru', help='', translation='тест2')
    # print(get_translation(text='test2', lang='ru', help=''))
    # print(get_translations_like(text='ес'))
    # print(get_translations_count())


    # print(get_total_msg_users_in_days(30))
    # print(count_new_user_in_days(30))


    # USERS_CACHE.set('key1', 'value10'*100)
    # # USERS_CACHE = {'key1': 'value10'*100, 'key2': 'value10'*200}
    # # USERS_CACHE = OrderedDict({'key1': 'value10'*100, 'key2': 'value10'*200})
    # time_start = time.time()
    # counter_last = 0
    # for x in range(10000000000):
    #     a = USERS_CACHE.get('key1')
    #     # a = USERS_CACHE['key1']
    #     if time.time() - time_start > 1:
    #         print(x - counter_last, end='\r')
    #         counter_last = x
    #         time_start = time.time()



    # print(count_msgs('test', 'gpt4o', 1000000))

    close()
