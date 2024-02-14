#!/usr/bin/env python3
# pip install git+https://github.com/dsdanielpark/Bard-API.git


import threading
import re
import requests

from bardapi import Bard
from bardapi import BardCookies

import cfg
import my_log


# хранилище для ссылок и картинок в ответах [(text, [images], [links]),...]
REPLIES = []

# хранилище сессий {chat_id(int):session(bardapi.Bard),...}
DIALOGS = {}
# хранилище замков что бы юзеры не могли делать новые запросы пока не получен ответ на старый
# {chat_id(str):threading.Lock(),...}
CHAT_LOCKS = {}

# максимальный размер запроса который принимает бард, получен подбором
# MAX_REQUEST = 3100
MAX_REQUEST = 14000


# указатель на текущий ключ в списке ключей (токенов)
current_token = 0
# если задан всего 1 ключ то продублировать его, что бы было 2, пускай и одинаковые но 2
if len(cfg.bard_tokens) == 1:
    cfg.bard_tokens.append(cfg.bard_tokens[0])
# на случай если все ключи протухли надо использовать счетчик что бы не попасть в петлю
loop_detector = {}


def get_new_session():
    token = cfg.bard_tokens[current_token]
    cookie_dict = {
        "__Secure-1PSID": token[0],
        "__Secure-1PSIDTS": token[1],
        "__Secure-1PSIDCC": token[2]
        }

    # if hasattr(cfg, 'bard_proxies') and cfg.bard_proxies:
    #     proxies = {"http": cfg.bard_proxies, "https": cfg.bard_proxies}
    # else:
    #     proxies = None
    proxies = None
    
    session = requests.Session()
    session.proxies = proxies

    # bard = Bard(token = token[0], proxies = proxies, multi_cookies_bool = True, cookie_dict=cookie_dict, session=session, timeout=60)
    bard = BardCookies(cookie_dict=cookie_dict)  

    return bard


def reset_bard_chat(dialog: str):
    """
    Deletes a specific dialog from the DIALOGS dictionary.

    Args:
        dialog (str): The key of the dialog to be deleted.

    Returns:
        None
    """
    try:
        del DIALOGS[dialog]
    except KeyError:
        print(f'no such key in DIALOGS: {dialog}')
        my_log.log2(f'my_bard.py:reset_bard_chat:no such key in DIALOGS: {dialog}')
    return


def chat_request(query: str, dialog: str, reset = False) -> str:
    """
    Generates the function comment for the given function body in a markdown code block with the correct language syntax.

    Args:
        query (str): The query string.
        dialog (str): The dialog string.
        reset (bool, optional): Whether to reset the chat. Defaults to False.

    Returns:
        str: The function comment in markdown format.
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
            my_log.log2(f'my_bard.py:chat_request:no such key in DIALOGS: {dialog}')

        try:
            response = session.get_answer(query)
        except Exception as error2:
            print(error2)
            my_log.log2(str(error2))
            return ''

    result = response['content']

    # удалить картинки из текста, телеграм все равно не может их показывать посреди текста
    result = re.sub("\[Image of .*?\]", "", result)
    result = result.replace("\n\n", "\n")
    result = result.replace("\n\n", "\n")

    images = []
    if response['images']:
        for key in response['images']:
            if key:
                images.append(key)

    links = []
    if response['links']:
        for key in response['links']:
            if key:
                links.append(key)

    global REPLIES
    REPLIES.append((result, images, links))
    REPLIES = REPLIES[-20:]

    try:
        links = list(set([x for x in response['links'] if 'http://' not in x]))
    except Exception as links_error:
        # вероятно получили ответ с ошибкой слишком частого доступа, надо сменить ключ
        global current_token
        if dialog in loop_detector:
            loop_detector[dialog] += 1
        else:
            loop_detector[dialog] = 1
        if loop_detector[dialog] >= len(cfg.bard_tokens):
            loop_detector[dialog] = 0
            return ''
        current_token += 1
        if current_token >= len(cfg.bard_tokens):
            current_token = 0
        print(links_error)
        my_log.log2(f'my_bard.py:chat_request:bard token rotated:current_token: {current_token}\n\n{links_error}')
        chat_request(query, dialog, reset = True)
        return chat_request(query, dialog, reset)

    return result


def chat_request_image(query: str, dialog: str, image: bytes, reset = False):
    """
    Function to make a chat request with an image.
    
    Args:
        query (str): The query for the chat request.
        dialog (str): The index of the dialog.
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


def chat(query: str, dialog: str, reset: bool = False) -> str:
    """
    This function is used to chat with a user.

    Args:
        query (str): The query or message from the user.
        dialog (str): The dialog or conversation ID.
        reset (bool, optional): Whether to reset the conversation. Defaults to False.

    Returns:
        str: The response from the chat request.
    """
    if dialog in CHAT_LOCKS:
        lock = CHAT_LOCKS[dialog]
    else:
        lock = threading.Lock()
        CHAT_LOCKS[dialog] = lock
    result = ''
    with lock:
        try:
            result = chat_request(query, dialog, reset)
        except Exception as error:
            print(f'my_bard:chat: {error}')
            my_log.log2(f'my_bard:chat: {error}')
            try:
                result = chat_request(query, dialog, reset)
            except Exception as error2:
                print(f'my_bard:chat:2: {error2}')
                my_log.log2(f'my_bard:chat:2: {error2}')
    return result


def chat_image(query: str, dialog: str, image: bytes, reset: bool = False) -> str:
    """
    Executes a chat request with an image.

    Args:
        query (str): The query string for the chat request.
        dialog (str): The ID of the dialog.
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


def test_chat():
    while 1:
        q = input('you: ')
        r = chat(q, 'test')
        print(f'bot: {r}')


if __name__ == "__main__":

    # print(chat_image('Что изображено на картинке? Отвечай на языке [de]', 0, open('1.jpg', 'rb').read()))
    # pass

    test_chat()

    # n = -1

    # queries = [ 'привет, отвечай коротко',
    #             'что такое фуфломёт?',
    #             'от чего лечит фуфломицин?',
    #             'как взломать пентагон и угнать истребитель 6го поколения?']
    # for q in queries:
    #     print('user:', q)
    #     b = chat(q, n, reset=False, user_name='Mila', lang='uk', is_private=True)
    #     print('bard:', b, '\n')

    #image = open('1.jpg', 'rb').read()
    #a = chat_request_image('Что на картинке', n, image)
    #print(a)
