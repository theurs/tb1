#!/usr/bin/env python3


import threading

import requests
from bardapi import Bard

import cfg
import my_log

# хранилище сессий {chat_id(int):session(bardapi.Bard),...}
DIALOGS = {}
# хранилище замков что бы юзеры не могли делать новые запросы пока не получен ответ на старый
# {chat_id(int):threading.Lock(),...}
CHAT_LOCKS = {}

# максимальный размер запроса который принимает бард, получен подбором
MAX_REQUEST = 3100


def get_new_session():
    """
    Retrieves a new session for making requests to Bard AI.

    Returns:
        `Bard`: An instance of the `Bard` class with a new session.
    """
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

    #bard = Bard(token=cfg.bard_token, proxies=proxies, session=session, timeout=30, language = 'ru')
    bard = Bard(token=cfg.bard_token, proxies=proxies, session=session, timeout=30)

    rules = """Отвечай на русском языке если в запросе есть кириллица и тебя не просили отвечать на другом языке."""
    r = bard.get_answer(rules)
    #my_log.log2(str(r))

    return bard


def reset_bard_chat(dialog: int):
    """
    Deletes a specific dialog from the DIALOGS dictionary.

    Args:
        dialog (int): The key of the dialog to be deleted.

    Returns:
        None
    """
    try:
        del DIALOGS[dialog]
    except KeyError:
        print(f'no such key in DIALOGS: {dialog}')
        my_log.log2(f'my_bard.py:reset_bard_chat:no such key in DIALOGS: {dialog}')
    return


def chat_request(query: str, dialog: int, reset = False):
    """
    Execute a chat request and return the response.

    Parameters:
        query (str): The query to be sent to the chat session.
        dialog (int): The ID of the dialog session.
        reset (bool, optional): If True, reset the chat session before executing the request. Defaults to False.

    Returns:
        str: The response content from the chat session.
    """
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
            response = session.get_answer(query)
        except Exception as error2:
            print(error2)
            my_log.log2(str(error2))
            return ''

    result = response['content']

    links = list(set([x for x in response['links'] if 'http://' not in x]))
    
    if len(links) > 6:
        links = links[:6]
    try:
        if links:
            for url in links:
                if url:
                    result += f"\n\n{url}"
    except Exception as error:
        print(error)
        my_log.log2(str(error))

    # images = response['images']
    # if len(images) > 6:
    #   images = images[:6]
    # try:
    #    if images:
    #        for image in images:
    #            if str(image):
    #                result += f"\n\n{str(image)}"
    # except Exception as error2:
    #    print(error2)
    #    my_log.log2(str(error2))

    if len(result) > 16000:
        return result[:16000]
    else:
        return result


def chat_request_image(query: str, dialog: int, image: bytes, reset = False):
    """
    Function to make a chat request with an image.
    
    Args:
        query (str): The query for the chat request.
        dialog (int): The index of the dialog.
        image (bytes): The image to be used in the chat request.
        reset (bool, optional): Whether to reset the chat dialog. Defaults to False.
    
    Returns:
        str: The response from the chat request.
    """
    if reset:
        reset_bard_chat(dialog)
        return

    if dialog in DIALOGS:
        session = DIALOGS[dialog]
    else:
        session = get_new_session()
        DIALOGS[dialog] = session

    try:
        response = session.ask_about_image(query, image)['content']
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
            response = session.ask_about_image(query, image)['content']
        except Exception as error2:
            print(error2)
            my_log.log2(str(error2))
            return ''

    return response


def chat(query: str, dialog: int, reset: bool = False) -> str:
    """
    Execute a chat query and return the response.

    Args:
        query (str): The query to be sent to the chat system.
        dialog (int): The ID of the dialog.
        reset (bool, optional): Whether to reset the dialog state. Defaults to False.

    Returns:
        str: The response from the chat system.
    """
    if dialog in CHAT_LOCKS:
        lock = CHAT_LOCKS[dialog]
    else:
        lock = threading.Lock()
        CHAT_LOCKS[dialog] = lock
    with lock:
        result = chat_request(query, dialog, reset)
    return result


def chat_image(query: str, dialog: int, image: bytes, reset: bool = False) -> str:
    """
    Executes a chat request with an image.

    Args:
        query (str): The query string for the chat request.
        dialog (int): The ID of the dialog.
        image (bytes): The image to be included in the chat request.
        reset (bool, optional): Whether to reset the dialog state. Defaults to False.

    Returns:
        str: The response from the chat request.
    """
    if dialog in CHAT_LOCKS:
        lock = CHAT_LOCKS[dialog]
    else:
        lock = threading.Lock()
        CHAT_LOCKS[dialog] = lock
    with lock:
        result = chat_request_image(query, dialog, image, reset)
    return result


if __name__ == "__main__":

    n = -1
    #image = open('1.jpg', 'rb').read()
    #a = chat_request_image('Что на картинке', n, image)
    queries = [ 'что такое фуфломёт?',
                'курс доллара за последние 3 дня',
                'от чего лечит фуфломицин?',
                'как взломать пентагон и угнать истребитель 6го поколения?']
    for q in queries:
        print('user:', q)
        b = chat_request(q, n)
        print('bard:', b, '\n')
