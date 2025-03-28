#!/usr/bin/env python3

import cachetools.func
import datetime
import hashlib
import lzma
import os
import pickle
import time
import threading
import traceback
import sqlite3
import sys
from typing import List, Tuple
from pprint import pprint

import zstandard
from collections import OrderedDict
from cachetools import LRUCache

import my_log
from utils import async_run, remove_file


LOCK = threading.Lock()

CON = None
CUR = None
DAEMON_RUN = True
DAEMON_TIME = 30

LAST_BACKUP_TIMESTAMP = time.time()
ONLINE_BACKUP_INTERVAL = 24 * 60 * 60  # 24 hours


def obj_to_blob(obj) -> bytes:
    """
    Serializes and compresses an object.

    Args:
        obj: The object to serialize and compress.

    Returns:
        bytes: The compressed serialized version of the object or None in case of an error.
    """
    if obj is None:
        return None
    else:
        try:
            # Serialize the object using pickle and compress it using lzma
            return lzma.compress(pickle.dumps(obj))
        except Exception as error:
            # Log the error and return None
            my_log.log2(f'my_db:obj_to_blob {error}')
            return None


def blob_to_obj(blob) -> object:
    """
    Deserializes and decompresses an object from its compressed serialized version.

    Args:
        blob (bytes): The compressed serialized version of the object.

    Returns:
        object: The original object or None in case of an error.
    """
    if blob:
        try:
            # Decompress the compressed serialized version of the object using lzma and deserialize it using pickle
            return pickle.loads(lzma.decompress(blob))
        except Exception as error:
            # Log the error and return None
            my_log.log2(f'my_db:blob_to_obj {error}')
            return None
    else:
        return None


class SmartCache:
    def __init__(self, max_size = 10000, max_value_size = 1024*10): # 1000*10kb=10mb!
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


def unpack_db(from_file: str, to_file: str):
    '''
    Unpack db copy (zstd compressed) with chunk reading and writing.
    '''
    try:
        with open(from_file, 'rb') as f_in:
            with open(to_file, 'wb') as f_out:
                zstd_decompressor = zstandard.ZstdDecompressor()
                decompressor = zstd_decompressor.stream_reader(f_in)
                chunk_size = 1024 * 1024 * 10 # 10 MB chunks

                while True:
                    chunk = decompressor.read(chunk_size)
                    if not chunk:
                        break
                    f_out.write(chunk)
        my_log.log2(f'my_db:unpack_db restored from {from_file} to {to_file}')
    except Exception as error:
        my_log.log2(f'my_db:unpack_db {error}')


def check_db():
    '''
    If not exists db/main.db check if there are files main.db.zst or main.db.zst.1 and restore
    '''
    if not os.path.exists('db/main.db'):
        if os.path.exists('db/main.db.zst'):
            unpack_db('db/main.db.zst', 'db/main.db')
        elif os.path.exists('db/main.db.zst.1'):
            unpack_db('db/main.db.zst.1', 'db/main.db')


def backup_db():
    try:
        # if exists db/main.db.zst move to db/main.db.zst.1 and copy
        if os.path.exists('db/main.db.zst'):
            if os.path.exists('db/main.db.zst.1'):
                remove_file('db/main.db.zst.1')
            os.rename('db/main.db.zst', 'db/main.db.zst.1')

        with open('db/main.db', 'rb') as f_in:
            with open('db/main.db.zst', 'wb') as f_out:
                # Use zstandard for compression
                zstd_compressor = zstandard.ZstdCompressor(threads=-1, level=3)
                compressor = zstd_compressor.stream_writer(f_out)
                chunk_size = 1024 * 1024 * 10 # 10 MB chunks

                while True:
                    chunk = f_in.read(chunk_size)
                    if not chunk:
                        break
                    compressor.write(chunk)
                # Завершение сжатия
                compressor.flush(zstandard.FLUSH_FRAME)  # Используем FLUSH_FRAME для корректного завершения
    except Exception as error:
        my_log.log2(f'my_db:compress_backup_db {error}')


def online_backup(target_file: str = ''):
    '''
    Создает бекап базы, каждые ONLINE_BACKUP_INTERVAL секунд
    вызывать надо из sync_daemon после комита внутри замка
    '''
    global LAST_BACKUP_TIMESTAMP

    if LAST_BACKUP_TIMESTAMP + ONLINE_BACKUP_INTERVAL < time.time():
        LAST_BACKUP_TIMESTAMP = time.time()

        if not target_file:
            target_file = f'db/main_backup.db'

        with sqlite3.Connection(target_file) as target:
            CON.backup(target)


@async_run
def sync_daemon():
    while DAEMON_RUN:
        time.sleep(DAEMON_TIME)
        try:
            with LOCK:
                CON.commit()
                online_backup()
        except Exception as error:
            traceback_error = traceback.format_exc()
            my_log.log2(f'my_db:sync_daemon {error}\n\n{traceback_error}')


def init(backup: bool = True, vacuum: bool = False):
    '''init db'''
    global CON, CUR
    day_seconds = 60 * 60 * 24
    week_seconds = day_seconds * 7
    month_seconds = day_seconds * 30
    year_seconds = day_seconds * 365
    keep_files_seconds = 1 * week_seconds
    keep_messages_seconds = 2 * week_seconds # 1 * month_seconds
    keep_global_messages_seconds = 10 * year_seconds

    check_db()

    try:
        if backup:
            backup_db()
        CON = sqlite3.connect('db/main.db', check_same_thread=False)
        CUR = CON.cursor()

        # переделать поле saved_file на blob
        alter_saved_file_column()

        CUR.execute('''
            CREATE TABLE IF NOT EXISTS msg_counter (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                access_time REAL,
                model_used TEXT
            )
        ''')
        CUR.execute('''DELETE FROM msg_counter WHERE access_time < ?''', (time.time() - keep_global_messages_seconds,))
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

        user_columns = """
            id_num INTEGER PRIMARY KEY AUTOINCREMENT,
            id TEXT,
            lang TEXT,
            first_meet REAL,
            last_time_access REAL,
            telegram_stars INTEGER,
            last_donate_time REAL,

            image_generated_counter INTEGER,

            saved_file BLOB,
            saved_file_name TEXT,

            blocked INTEGER,
            blocked_bing INTEGER,
            blocked_totally INTEGER,

            auto_leave_chat INTEGER,
            auto_translations INTEGER,
            tts_gender TEXT,
            speech_to_text_engine TEXT,
            chat_enabled INTEGER,
            superchat INTEGER,
            transcribe_only INTEGER,
            command_mode TEXT,
            voice_only_mode INTEGER,
            disabled_kbd INTEGER,
            chat_mode TEXT,
            chat_mode_prev TEXT,
            role TEXT,
            memos BLOB,
            temperature REAL,
            bot_name TEXT,
            openrouter_timeout INTEGER,
            action_style TEXT,
            send_message INTEGER,

            persistant_memory TEXT,

            base_api_url TEXT,
            openrouter_in_price REAL,
            openrouter_out_price REAL,
            openrouter_currency TEXT,

            api_key_gemini TEXT,
            api_key_groq TEXT,
            api_key_huggingface TEXT,

            dialog_gemini BLOB,
            dialog_gemini_thinking BLOB,
            dialog_groq BLOB,
            dialog_openrouter BLOB,
            dialog_glm BLOB
        """

        # Проверяем существование таблицы
        CUR.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
        table_exists = CUR.fetchone() is not None

        if not table_exists:
            CUR.execute(f'''
                CREATE TABLE IF NOT EXISTS users (
                    {user_columns}
                )
            ''')
            CUR.execute('CREATE INDEX IF NOT EXISTS idx_id ON users (id)')
            CUR.execute('CREATE INDEX IF NOT EXISTS idx_first_meet ON users (first_meet)')
        else:
            # Таблица существует, проверяем наличие полей и добавляем их при необходимости
            columns = [col.strip() for col in user_columns.strip().split(',')]
            for column_def in columns:
                column_name = column_def.split()[0]
                try:
                    CUR.execute(f"ALTER TABLE users ADD COLUMN {column_def}")
                    my_log.log2(f'my_db:init: added column to users: {column_def}')
                except sqlite3.OperationalError as op_error:
                    if 'duplicate column name' not in str(op_error):
                        my_log.log2(f'my_db:init: error adding column {column_name} to users: {op_error}')
                except Exception as error:
                    my_log.log2(f'my_db:init: error adding column {column_name} to users: {error}')


        # удалить файлы старше xx дня и диалоги старше yyy недели
        CUR.execute("""UPDATE users SET saved_file = NULL,
                    saved_file_name = NULL WHERE last_time_access < ?
                    """, (time.time() - keep_files_seconds,))
        CUR.execute("""UPDATE users SET dialog_gemini = NULL,
                    dialog_groq = NULL,
                    dialog_openrouter = NULL,
                    persistant_memory = NULL
                    WHERE last_time_access < ?
                    """, (time.time() - keep_messages_seconds,))

        CUR.execute('''
            CREATE TABLE IF NOT EXISTS sum (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date REAL,
                url TEXT,
                text TEXT
            )
        ''')


        if vacuum:
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


def alter_saved_file_column():
    '''
    Checks if the 'saved_file' column in the 'users' table exists and is of type TEXT.
    If it is, the column is dropped and recreated as BLOB.
    '''
    with LOCK:
        try:
            # Check if the table 'users' exists
            CUR.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
            table_exists = CUR.fetchone() is not None

            if not table_exists:
                my_log.log2('my_db:alter_saved_file_column: Table users does not exist.')
                return

            # Check the column type using PRAGMA table_info
            CUR.execute("PRAGMA table_info(users)")
            columns_info = CUR.fetchall()
            saved_file_column_info = None
            for column in columns_info:
                if column[1] == 'saved_file':
                    saved_file_column_info = column
                    break

            if saved_file_column_info:
                column_type = saved_file_column_info[2].upper()
                if column_type != 'BLOB':
                    my_log.log2(f'my_db:alter_saved_file_column: saved_file column type is {column_type}')

                if column_type == 'TEXT':
                    # Drop the existing TEXT column
                    my_log.log2('my_db:alter_saved_file_column: Dropping saved_file TEXT column...')
                    CUR.execute("ALTER TABLE users DROP COLUMN saved_file")
                    my_log.log2('my_db:alter_saved_file_column: saved_file TEXT column dropped.')

                    # Add the new BLOB column
                    my_log.log2('my_db:alter_saved_file_column: Adding saved_file BLOB column...')
                    CUR.execute("ALTER TABLE users ADD COLUMN saved_file BLOB")
                    my_log.log2('my_db:alter_saved_file_column: saved_file BLOB column added.')

                    CON.commit()  # Commit the changes
                else:
                    # my_log.log2(f'my_db:alter_saved_file_column: Column type of saved_file is already {column_type}, no action taken.')
                    pass

            else:
                my_log.log2('my_db:alter_saved_file_column: Column saved_file not found, no action taken.')

        except sqlite3.Error as error:
            my_log.log2(f'my_db:alter_saved_file_column {error}')
            CON.rollback()


@async_run
def add_msg(user_id: str, model_used: str, timestamp: float = None):
    '''add msg counter record to db'''
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


@cachetools.func.ttl_cache(maxsize=100, ttl=15*60)
def count_msgs_total_user(user_id: str) -> int:
    '''Count the number of all messages sent by a user.
    '''
    with LOCK:
        try:
            CUR.execute('''
                SELECT COUNT(*) FROM msg_counter
                WHERE user_id = ?
            ''', (user_id,))
            return CUR.fetchone()[0]
        except Exception as error:
            my_log.log2(f'my_db:count {error}')
            return 0


@cachetools.func.ttl_cache(maxsize=100, ttl=15*60)
def count_msgs_last_24h(user_id: str) -> int:
    """
    Counts the number of messages sent by a user in the last 24 hours.

    Args:
        user_id: The ID of the user.

    Returns:
        The number of messages sent by the user in the last 24 hours.
    """
    with LOCK:  # Assuming you have a lock defined for database access
        try:
            # Calculate the timestamp 24 hours ago
            time_24h_ago = time.time() - 24 * 60 * 60

            # Execute the SQL query to count messages
            CUR.execute('''
                SELECT COUNT(*) FROM msg_counter
                WHERE user_id = ? AND access_time >= ?
            ''', (user_id, time_24h_ago))

            # Fetch and return the result
            result = CUR.fetchone()[0]
            return result

        except sqlite3.Error as error:
            # Handle any database errors
            my_log.log2(f'my_db:count_msgs_last_24h {error}\nUser ID: {user_id}')
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


def get_total_msg_user(user_id) -> int:
    with LOCK:
        try:
            CUR.execute('''
                SELECT COUNT(id) FROM msg_counter WHERE user_id = ?
            ''', (user_id,))
            return CUR.fetchone()[0]
        except Exception as error:
            my_log.log2(f'my_db:get_total_msg_user {error}')
            return 0


def get_pics_msg_user(user_id) -> int:
    with LOCK:
        try:
            CUR.execute('''
                SELECT COUNT(id) FROM msg_counter WHERE user_id = ? AND model_used LIKE 'img %'
            ''', (user_id,))
            return CUR.fetchone()[0]
        except Exception as error:
            my_log.log2(f'my_db:get_total_msg_user {error}')
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
        except Exception as error:
            my_log.log2(f'my_db:update_translation {error}\n\n{text}\n\n{lang}\n\n{help}\n\n{translation}')


def update_translations(values: list):
    '''Update many translations in cache
    values - list of tuples (text, lang, help, translation)
    '''
    drop_all_translations()
    with LOCK:
        try:
            # Выполняем один запрос для вставки данных
            CUR.executemany('''
                INSERT INTO translations (original, lang, help, translation)
                VALUES (?, ?, ?, ?)
            ''', values)
        except Exception as error:
            my_log.log2(f'my_db:update_translations {error}\n\n{values}')


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


def get_unique_originals() -> List[Tuple[str, str]]:
    """
    Retrieves a list of unique original texts and their corresponding help texts
    from the translations table.

    Returns:
        A list of tuples, where each tuple contains the unique original text
        and its associated help text.
    """
    with LOCK:
        try:
            CUR.execute('''
                SELECT DISTINCT original, help
                FROM translations
            ''')
            results: List[Tuple[str, str]] = CUR.fetchall()
            return results
        except Exception as error:
            my_log.log2(f'my_db:get_unique_originals {error}')
            return []


def vacuum(lock_db: bool = True):
    '''Vacuum database'''
    if lock_db:
        with LOCK:
            try:
                CUR.execute('''
                    VACUUM
                ''')
                CON.commit()
            except Exception as error:
                my_log.log2(f'my_db:vacuum {error}')
    else:
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
        # тут лок нельзя ставить, функцию вызывают из другого лока
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
        # saved_file сжимаем и распаковываем
        if property == 'saved_file':
            return blob_to_obj(USERS_CACHE.get(cache_key))
        else:
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
                    # saved_file сжимаем и распаковываем
                    if property == 'saved_file':
                        r = blob_to_obj(result[0])
                        USERS_CACHE.set(cache_key, result[0])
                        return r
                    else:
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
            else:
                my_log.log2(f'my_db:delete_property - User {user_id} not found')
        except Exception as error:
            my_log.log2(f'my_db:delete_property {error}')


def set_user_property(user_id: str, property: str, value):
    '''Set user`s property'''

    # limit file save size
    if property == 'saved_file':
        value = value[:300000]
        value = obj_to_blob(value)

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


def find_users_with_many_messages() -> List[str]:
    """
    Finds users in the database who have more than 1000 messages.

    Returns:
        A list of user IDs (as strings) that match the criteria. 
        Returns an empty list if no users match or an error occurs.
    """
    with LOCK:
        try:
            CUR.execute("""
                SELECT id
                FROM users
                WHERE id IN (SELECT user_id FROM msg_counter GROUP BY user_id HAVING COUNT(*) > 1000)
                  AND id NOT LIKE '%-10%'  -- Exclude users with '-10' in their ID
            """)
            results = CUR.fetchall()
            return [user_id[0] for user_id in results]  
        except Exception as error:
            my_log.log2(f'my_db:find_users_with_many_messages {error}')
            return []


def fix_tts_model_used():
    '''Исправить записи в базе с неправильным model_used'''
    with LOCK:
        try:
            CUR.execute("UPDATE msg_counter SET model_used = REPLACE(model_used, 'TTS ', 'STT ') WHERE model_used LIKE 'TTS %'")
            CON.commit()
        except Exception as error:
            my_log.log2(f'my_db:fix_tts_model_used {error}')


def get_top_users_by_size(top_n: int = 100) -> List[Tuple[str, int]]:
    """
    Get the top N users by the total size of their texts and blobs.

    Args:
        top_n (int): The number of top users to retrieve.

    Returns:
        List[Tuple[str, int]]: A list of tuples containing user IDs and their total sizes.
    """
    with LOCK:
        try:
            # Извлекаем данные о пользователях
            CUR.execute('''
                SELECT id, saved_file, dialog_gemini, dialog_gemini_thinking, dialog_groq,
                       dialog_openrouter, dialog_glm, persistant_memory
                FROM users
            ''')
            users_data = CUR.fetchall()

            # Подсчитываем размеры текстов и блобов для каждого пользователя
            user_sizes = []
            for user in users_data:
                user_id = user[0]
                total_size = 0

                # Подсчитываем размеры текстов
                for text in user[1:]:
                    if text:
                        total_size += len(text)

                # Подсчитываем размеры блобов
                for blob in user[2:]:
                    if blob:
                        total_size += len(blob)

                user_sizes.append((user_id, total_size))

            # Сортируем пользователей по суммарному размеру
            user_sizes.sort(key=lambda x: x[1], reverse=True)

            # Возвращаем топ-N пользователей
            return user_sizes[:top_n]

        except Exception as error:
            my_log.log2(f'my_db:get_top_users_by_size {error}')
            return []


def get_user_data_sizes(user_id: str) -> dict:
    """
    Get the sizes of text and blob fields for a specific user.

    Args:
        user_id (str): The ID of the user.

    Returns:
        dict: A dictionary containing the sizes of text and blob fields.
    """
    with LOCK:
        try:
            # Извлекаем данные о пользователе
            CUR.execute('''
                SELECT id, saved_file, dialog_gemini, dialog_gemini_thinking, dialog_groq,
                       dialog_openrouter, dialog_glm, persistant_memory
                FROM users
                WHERE id = ?
            ''', (user_id,))
            user_data = CUR.fetchone()

            if not user_data:
                return {}

            # Подсчитываем размеры текстовых и блоб полей
            data_sizes = {
                'saved_file': len(user_data[1]) if user_data[1] else 0,
                'dialog_gemini': len(user_data[2]) if user_data[2] else 0,
                'dialog_gemini_thinking': len(user_data[3]) if user_data[3] else 0,
                'dialog_groq': len(user_data[4]) if user_data[4] else 0,
                'dialog_openrouter': len(user_data[5]) if user_data[5] else 0,
                'dialog_glm': len(user_data[6]) if user_data[6] else 0,
                'persistant_memory': len(user_data[7]) if user_data[7] else 0
            }

            return data_sizes

        except Exception as error:
            my_log.log2(f'my_db:get_user_data_sizes {error}')
            return {}


def drop_all_user_files_and_big_dialogs(max_dialog_size: int = 500000, delete_data: bool = False) -> str:
    '''
    Deletes user uploaded files and large Gemini dialogs.
    Dialogs with gemini can grow significantly due to images,
    sometimes they need to be deleted forcibly, but only
    if their size is larger than the specified limit in compressed form.
    User uploaded files can also be safely deleted,
    there is no need to store them for a long time.
    After deletion, a vacuum operation should be performed to reduce the database size.

    Args:
        max_dialog_size: The maximum size of a dialog in bytes before it is considered for deletion.
        delete_data: If True, performs actual deletion. If False, only displays statistics.

    Returns:
        str: A message indicating the result of the operation.
    '''
    with LOCK:
        try:
            if delete_data:
                total_deleted_size = 0

                # Delete saved files
                CUR.execute('''
                    UPDATE users
                    SET saved_file = NULL,
                    saved_file_name = NULL
                ''')

                # delete users with id starting with 'translate_doc_'
                CUR.execute('''
                    DELETE FROM users
                    WHERE id LIKE 'translate_doc_%'
                ''')

                # Delete large Gemini dialogs individually
                CUR.execute('''
                    SELECT id, LENGTH(dialog_gemini)
                    FROM users
                    WHERE LENGTH(dialog_gemini) > ?
                ''', (max_dialog_size,))
                results = CUR.fetchall()
                for user_id, size in results:
                    if size is not None:
                        total_deleted_size += size
                    CUR.execute('''
                        UPDATE users
                        SET dialog_gemini = NULL
                        WHERE id = ?
                    ''', (user_id,))

                CUR.execute('''
                    SELECT id, LENGTH(dialog_gemini_thinking)
                    FROM users
                    WHERE LENGTH(dialog_gemini_thinking) > ?
                ''', (max_dialog_size,))
                results = CUR.fetchall()
                for user_id, size in results:
                    if size is not None:
                        total_deleted_size += size
                    CUR.execute('''
                        UPDATE users
                        SET dialog_gemini_thinking = NULL
                        WHERE id = ?
                    ''', (user_id,))

                CON.commit()
                msg = f'my_db:drop_all_user_files_and_big_dialogs: User files and large dialogs have been deleted. Total deleted size: {total_deleted_size} bytes'
                my_log.log2(msg)

                # Clear the cache
                try:
                    USERS_CACHE.cache.cache_clear()
                except Exception as clear_cache_error:
                    my_log.log2(f'my_db:drop_all_user_files_and_big_dialogs {clear_cache_error}')

                # Execute VACUUM to reduce the database size (outside the LOCK)
                vacuum(lock_db = False)

                return msg

            else:
                # Print information about what would be deleted
                print("Information about data that would be deleted:")
                total_would_be_deleted_size = 0

                # Check for large dialog_gemini
                CUR.execute('''
                    SELECT id, LENGTH(dialog_gemini)
                    FROM users
                    WHERE LENGTH(dialog_gemini) > ?
                ''', (max_dialog_size,))
                results = CUR.fetchall()
                for user_id, size in results:
                    print(f"  User {user_id}: Delete dialog_gemini (size: {size} bytes)")
                    if size is not None:
                        total_would_be_deleted_size += size

                # Check for large dialog_gemini_thinking
                CUR.execute('''
                    SELECT id, LENGTH(dialog_gemini_thinking)
                    FROM users
                    WHERE LENGTH(dialog_gemini_thinking) > ?
                ''', (max_dialog_size,))
                results = CUR.fetchall()
                for user_id, size in results:
                    print(f"  User {user_id}: Delete dialog_gemini_thinking (size: {size} bytes)")
                    if size is not None:
                        total_would_be_deleted_size += size

                # Check for saved files
                CUR.execute('''
                    SELECT id
                    FROM users
                    WHERE saved_file IS NOT NULL OR saved_file_name IS NOT NULL
                ''')
                results = CUR.fetchall()
                for user_id in results:
                    print(f"  User {user_id}: Delete saved_file and saved_file_name")

                # Estimate the size of saved_files - difficult to get the exact size without reading the files
                print(f"  Estimated total size of deleted data (excluding saved files): {total_would_be_deleted_size} bytes")
                msg = f'my_db:drop_all_user_files_and_big_dialogs: User files and large dialogs would have been deleted (but were not). Estimated total size: {total_would_be_deleted_size} bytes (excluding saved files)'
                my_log.log2(msg)

                return msg

        except Exception as error:
            my_log.log2(f'my_db:drop_all_user_files_and_big_dialogs {error}')
            if delete_data:
                CON.rollback()
                return f'my_db:drop_all_user_files_and_big_dialogs: Error deleting data: {error}'


@cachetools.func.ttl_cache(maxsize=100, ttl=30*60)
def count_imaged_per24h(chat_id_full: str) -> int:
    """
    Counts the number of images generated by a user in the last 24 hours.

    Args:
        chat_id_full: The full ID of the user (chat).

    Returns:
        The number of images generated by the user in the last 24 hours.
    """
    with LOCK:
        try:
            # Calculate the timestamp 24 hours ago
            time_24h_ago = time.time() - 24 * 60 * 60

            # Execute the SQL query to count images
            CUR.execute('''
                SELECT COUNT(*) FROM msg_counter
                WHERE user_id = ? AND access_time >= ? AND (model_used LIKE 'img %' OR model_used LIKE 'IMG %')
            ''', (chat_id_full, time_24h_ago))

            # Fetch and return the result
            result = CUR.fetchone()[0]
            return result

        except sqlite3.Error as error:
            # Handle any database errors
            my_log.log2(f'my_db:count_imaged_per24h {error}\nUser ID: {chat_id_full}')
            return 0


if __name__ == '__main__':
    pass
    init(backup=False)

    online_backup()

    # print(find_users_with_many_messages())
    # fix_tts_model_used()

    # # Пример использования функции
    # top_users = get_top_users_by_size(100)
    # for user_id, total_size in top_users:
    #     print(f'User ID: {user_id}, Total Size: {total_size} bytes')

    # # Пример использования функции
    # user_id = 'xxx'

    # user_data_sizes = get_user_data_sizes(user_id)
    # for field, size in user_data_sizes.items():
    #     print(f'Field: {field}, Size: {size} bytes')

    # dialog = get_user_property(user_id, 'dialog_gemini')
    # decompressed_dialog = blob_to_obj(dialog)
    # pprint(decompressed_dialog)

    # c = count_imaged_per24h('[xxx] [0]')
    # print(c)

    close()
