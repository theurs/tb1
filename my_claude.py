#!/usr/bin/env python3
# pip install claude-api


import random
import threading

import claude_api

import cfg
import my_log
import my_dic


# максимальный размер запроса 190к (символов или токенов или чего?)
# тут считаем что символов но как на самом деле хз
# MAX_QUERY = 190000
MAX_QUERY = 90000

# хранилище сессий {chat_id(str):session(str),...}
DIALOGS = my_dic.PersistentDict('db/claude_dialogs.pkl')

# хранилище замков что бы юзеры не могли делать новые запросы пока не получен ответ на старый
# {chat_id(str):threading.Lock(),...}
CHAT_LOCKS = {}

# подключениe клауду {chat_id(str):claude_api.Client(cookie),...}
APIS = {}


def get_api(chat_id: str):
    """возвращает объект api. создает новый если не было раньше или был удален"""
    if chat_id not in APIS:
        random.shuffle(cfg.claudeai_keys)
        api = claude_api.Client(cfg.claudeai_keys[0])
        APIS[chat_id] = api
    else:
        api = APIS[chat_id]
    return api


def get_new_session(chat_id: str):
    """
    Retrieves a new session for making HTTP requests.

    Args:


    Returns:
        session (str): An session id
    """
    api = get_api(chat_id)

    session = api.create_new_chat()['uuid']

    return session


def reset_claude_chat(dialog: str):
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
        # my_log.log2(f'my_claude.py:reset_claude_chat:no such key in DIALOGS: {dialog}')
        pass
    return


def chat_request(query: str, dialog: str, reset = False, attachment = None) -> str:
    """
    Generates a response to a chat request.

    Args:
        query (str): The user's query.
        dialog (str): The dialog number.
        reset (bool, optional): Whether to reset the dialog. Defaults to False.
        attachment (str, optional): The attachment, path to file. Defaults to None.
    Returns:
        str: The generated response.
    """
    if reset:
        reset_claude_chat(dialog)
        return

    if dialog in DIALOGS:
        session = DIALOGS[dialog]
    else:
        session = get_new_session(dialog)
        DIALOGS[dialog] = session

    resp = ''

    try:
        api = get_api(dialog)
        resp = api.send_message(query, session, attachment)
    except Exception as error:
        print(f'my_claude:chat_request: {error}')
        my_log.log2(f'my_claude:chat_request: {error}')

        try:
            del APIS[dialog]
            session = get_new_session(dialog)
            DIALOGS[dialog] = session
            api = get_api(dialog)
            resp = api.send_message(query, session, attachment)
        except Exception as error2:
            print(f'my_claude:chat_request:error2: {error2}')
            my_log.log2(f'my_claude:chat_request:error2: {error2}')

    return resp


def chat(query: str, dialog: str, reset: bool = False, attachment = None) -> str:
    """
    Executes a chat request with the given query and dialog ID.

    Args:
        query (str): The query to be sent to the chat API.
        dialog (str): The ID of the dialog to send the request to.
        reset (bool, optional): Whether to reset the conversation. Defaults to False.
        attachment (str, optional): The attachment, path to file. Defaults to None.

    Returns:
        str: The response from the chat API.
    """
    if dialog in CHAT_LOCKS:
        lock = CHAT_LOCKS[dialog]
    else:
        lock = threading.Lock()
        CHAT_LOCKS[dialog] = lock
    with lock:
        result = chat_request(query, dialog, reset, attachment)
    return result


if __name__ == '__main__':

    # prompt = open('1.txt', 'r', encoding='utf-8').read()[:99000]
    # print(chat(prompt, '0'))

    # print(chat('о чем это', 'test', False, 'C:/Users/user/Downloads/Writing Book Description.pdf'))
    # print(chat('переведи первый абзац на русский', 'test'))
    #print(chat('дальше', 'test'))

    while True:
        prompt = input("> ")
        if prompt.strip() == 'забудь':
            reset_claude_chat('01')
            continue
        response = chat(prompt, '01')
        print('bot:', response)
