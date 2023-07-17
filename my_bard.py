#!/usr/bin/env python3


import requests
import threading
from pprint import pprint

from bardapi import Bard

import cfg
import my_log


DIALOGS = {}
CHAT_LOCKS = {}


MAX_REQUEST = 3100


def get_new_session():
    if cfg.all_proxy:
        proxies = {
            'http': cfg.all_proxy,
            'https': cfg.all_proxy
                }
    else:
        proxies = None

    session = requests.Session()

    session.cookies.set("__Secure-1PSID", cfg.bard_token)

    session.headers = {
        "Host": "bard.google.com",
        "X-Same-Domain": "1",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Origin": "https://bard.google.com",
        "Referer": "https://bard.google.com/",
        }

    bard = Bard(token=cfg.bard_token, proxies=proxies, session=session, timeout=30)

    return bard


def reset_bard_chat(dialog: int):
        try:
            del DIALOGS[dialog]
        except KeyError:
            print(f'no such key in DIALOGS: {dialog}')
            my_log.log2(f'my_bard.py:reset_bard_chat:no such key in DIALOGS: {dialog}')
        return


def chat_request(query: str, dialog: int, reset = False):
    """возвращает ответ"""

    if reset:
        reset_bard_chat(dialog)
        return

    if dialog in DIALOGS:
        session = DIALOGS[dialog]
    else:
        session = get_new_session()
        DIALOGS[dialog] = session

    try:
        response = session.get_answer(query)['content']
    except Exception as error:
        print(error)
        my_log.log2(str(error))

        try:
            del DIALOGS[dialog]
            session = get_new_session()
            DIALOGS[dialog] = session
        except KeyError:
            print(f'no such key in DIALOGS: {dialog}')
            my_log.log2(f'my_bard.py:chat:no such key in DIALOGS: {dialog}')

        try:
            response = session.get_answer(line)['content']
        except Exception as error2:
            print(error2)
            my_log.log2(str(error2))
            return ''

    return response


def chat_request2(query: str, dialog: int, reset = False):
    """возвращает ответ"""

    if reset:
        reset_bard_chat(dialog)
        return

    if dialog in DIALOGS:
        session = DIALOGS[dialog]
    else:
        session = get_new_session()
        DIALOGS[dialog] = session

    try:
        response = session.get_answer(query)
    except Exception as error:
        print(error)
        my_log.log2(str(error))

        try:
            del DIALOGS[dialog]
            session = get_new_session()
            DIALOGS[dialog] = session
        except KeyError:
            print(f'no such key in DIALOGS: {dialog}')
            my_log.log2(f'my_bard.py:chat:no such key in DIALOGS: {dialog}')

        try:
            response = session.get_answer(line)
        except Exception as error2:
            print(error2)
            my_log.log2(str(error2))
            return ''

    return (response['content'], response['links'], response['images'], response['code'])


def chat(query: str, dialog: int, reset: bool = False) -> str:
    """возвращает ответ"""
    if dialog in CHAT_LOCKS:
        lock = CHAT_LOCKS[dialog]
    else:
        lock = threading.Lock()
        CHAT_LOCKS[dialog] = lock
    with lock:
        result = chat_request(query, dialog, reset)
    return result


if __name__ == "__main__":

    n = -1

    a = chat_request2('Сайты про лошадей', n)
    print(a[0], '\n\n')
    print(a[1], '\n\n')
    print(a[2], '\n\n')
    print(a[2], '\n\n')