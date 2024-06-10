#!/usr/bin/env python3


import threading
import sqlite3


LOCK = threading.Lock()

CON = None
CUR = None


def init():
    global CON, CUR
    with LOCK:
        CON = sqlite3.connect('db/msg_counter.db')
        CUR = conn.cursor()

        CUR.execute('''
            CREATE TABLE IF NOT EXISTS records (
                user_id TEXT PRIMARY KEY,
                access_time REAL,
                model_used TEXT
            )
        ''')
        CON.commit()



def add_record(user_id: str, ):
    '''add record to db'''
    with LOCK:
        pass





def get_record(user_id: str, ):
    '''get record from db'''
    with LOCK:
    pass


if __name__ == '__main__':
    pass