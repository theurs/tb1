#!/usr/bin/env python3


import time
import threading
import traceback
import sqlite3

import my_log
from utils import async_run


LOCK = threading.Lock()

CON = None
CUR = None
COM_COUNTER = 0
DAEMON_RUN = True
DAEMON_TIME = 2


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


def init():
    '''init db'''
    global CON, CUR
    try:
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
        CUR.execute('CREATE INDEX IF NOT EXISTS idx_access_time ON msg_counter (access_time)')
        CUR.execute('CREATE INDEX IF NOT EXISTS idx_user_id ON msg_counter (user_id)')
        CUR.execute('CREATE INDEX IF NOT EXISTS idx_model_used ON msg_counter (model_used)')

        CUR.execute('''
            CREATE TABLE IF NOT EXISTS translations (
                original TEXT,
                lang TEXT,
                help TEXT,
                translation TEXT
            )
        ''')
        CUR.execute('CREATE INDEX IF NOT EXISTS idx_original ON translations (original)')
        CUR.execute('CREATE INDEX IF NOT EXISTS idx_lang ON translations (lang)')
        CUR.execute('CREATE INDEX IF NOT EXISTS idx_help ON translations (help)')
        CUR.execute('CREATE INDEX IF NOT EXISTS idx_translation ON translations (translation)')

        CUR.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id_num INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT,
                lang TEXT,
                first_meet REAL,

                image_generated_counter INTEGER,

                saved_file TEXT,

                blocked INTEGER,
                blocked_bing INTEGER,
                auto_leave_chat INTEGER,

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
                bot_name TEXT
            )
        ''')
        CUR.execute('CREATE INDEX IF NOT EXISTS idx_id ON users (id)')
        CUR.execute('CREATE INDEX IF NOT EXISTS idx_first_meet ON users (first_meet)')

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
            CON.close()
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
    '''Посчитать сколько юзеров не имеют ни одного сообщения раньше чем за days дней'''
    access_time = time.time() - days * 24 * 60 * 60
    with LOCK:
        try:
            CUR.execute('''
                SELECT COUNT(DISTINCT user_id)
                FROM msg_counter 
                WHERE access_time > ?
                AND NOT EXISTS (
                    SELECT 1
                    FROM msg_counter AS mc2
                    WHERE mc2.user_id = msg_counter.user_id
                    AND mc2.access_time <= ?
                )
            ''', (access_time, access_time))

            return CUR.fetchone()[0]
        except Exception as error:
            my_log.log2(f'my_db:count_new_user_in_days {error}')
            return 0


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


def get_user_lang(user_id: str) -> str:
    '''Get user language'''
    with LOCK:
        try:
            CUR.execute('''
                SELECT lang FROM users
                WHERE user_id = ?
            ''', (user_id)
            )
            result = CUR.fetchone()
            if result:
                return result[0]
            else:
                return None
        except Exception as error:
            my_log.log2(f'my_db:get_user_lang {error}')
            return None


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


def set_user_lang(user_id: str, lang: str):
    '''Set user language'''
    global COM_COUNTER
    with LOCK:
        try:
            # надо проверить есть ли в базе юзер, и если есть то обновить его язык а если нет то добавить нового
            CUR.execute('''
                SELECT 1 FROM users
                WHERE id = ?
            ''', (user_id,))
            if CUR.fetchone():
                CUR.execute('''
                    UPDATE users
                    SET lang = ?
                    WHERE id = ?
                ''', (lang, user_id))
            else:
                first_meet = get_first_meet(user_id) or time.time()
                CUR.execute('''
                    INSERT INTO users (id, lang, first_meet)
                    VALUES (?, ?, ?)
                ''', (user_id, lang, first_meet))
            COM_COUNTER += 1
        except Exception as error:
            my_log.log2(f'my_db:set_user_lang {error}')


if __name__ == '__main__':
    pass
    init()

    vacuum()


    # print(get_translation(text='test2', lang='ru', help=''))
    # update_translation(text='test2', lang='ru', help='', translation='тест2')
    # print(get_translation(text='test2', lang='ru', help=''))
    # print(get_translations_like(text='ес'))
    # print(get_translations_count())


    # print(get_total_msg_users_in_days(30))
    # print(count_new_user_in_days(30))

    # for x in range(10000000):
    #     uid = random.choice(('user1','user2', 'user3', 'user4', 'user5', 'user6', 'user7', 'user8', 'user9', 'user10'))
    #     model = random.choice(('model1','model2', 'model3', 'model4', 'model5', 'model6', 'model7', 'model8', 'model9', 'model10'))
    #     add_msg(uid, model)
    #     print(x, end='\r\r\r\r\r')

    # for x in range(10000000):
    #     a = count_msgs('user1', 'all', 10000)
    #     b = count_msgs('user1', 'model5', 10000)
    #     c = count_msgs_all()
    #     print(x, end='\r\r\r\r\r')

    # print(count_msgs('test', 'gpt4o', 1000000))

    close()
