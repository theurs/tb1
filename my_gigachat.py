#!/usr/bin/env python3
# pip install gigachain
# pip install gigachat


import random
import threading
import traceback

import sqlitedict
from langchain.schema import HumanMessage, SystemMessage, AIMessage
from langchain.chat_models.gigachat import GigaChat

import cfg
import my_log


# {chat_id (str):messages(list)}
CHATS = sqlitedict.SqliteDict('db/gigachat_chats.db', autocommit=True)

# {key:lock} каждый ключ может работать только одним потоком
KEY_LOCKS = {}

# хранить в истории чатов не больше чем MAX_MESSAGES сообщений
MAX_MESSAGES = cfg.GIGACHAT_MAX_MESSAGES if hasattr(cfg, 'GIGACHAT_MAX_MESSAGES') else 20
MAX_SYMBOLS = cfg.GIGACHAT_MAX_SYMBOLS if hasattr(cfg, 'GIGACHAT_MAX_SYMBOLS') else 10000
# не принимать запросы больше чем, это ограничение для телеграм бота, в этом модуле оно не используется
MAX_QUERY = cfg.GIGACHAT_MAX_QUERY if hasattr(cfg, 'GIGACHAT_MAX_QUERY') else 4000


def chat(prompt: str, chat_id: str, role: str = ''):
    """
    Function for chatting with a GigaChat API, given a prompt and chat_id. 
    Optional parameter role can be provided as well. Returns a response from the chat, 
    or an empty string if the chat fails.
    """
    try:
        # это для сообщений об ошибке
        res_ = None
        messages = []
        key = None

        if not hasattr(cfg, 'GIGACHAT_API'):
            return ''

        if not role:
            role = "Ты эмпатичный бот-психолог, который помогает пользователю решить его проблемы."

        messages = CHATS[chat_id] if chat_id in CHATS else []

        keys = cfg.GIGACHAT_API[:]
        key = random.choice(keys)

        if key not in KEY_LOCKS:
            KEY_LOCKS[key] = threading.Lock()

        with KEY_LOCKS[key]:
            chat_ = GigaChat(credentials=key, verify_ssl_certs=False)

            messages_ = [SystemMessage(content=role)]
            role = 'h'
            for m in messages:
                if role == 'h':
                    role = 'a'
                    messages_.append(HumanMessage(content=m))
                elif role == 'a':
                    role = 'h'
                    messages_.append(AIMessage(content=m))

            messages.append(prompt)
            messages_.append(HumanMessage(content=prompt))

            res_ = chat_(messages_)

            res = res_.content

            if res:
                messages.append(res)

                # помнить не больше чем MAX_MESSAGES последних сообщений
                if len(messages) >= (MAX_MESSAGES+2):
                    messages = messages[-MAX_MESSAGES:]
                # помнить не больше чем MAX_SYMBOLS символов
                while 1:
                    sizeof_messages = 0
                    for m in messages:
                        sizeof_messages += len(m)
                    if sizeof_messages < MAX_SYMBOLS:
                        break
                    messages = messages[2:]

                CHATS[chat_id] = messages

                return res
            else:
                messages.pop()

        return ''
    except Exception as unknown_error:
        error_traceback = traceback.format_exc()
        _messages_ = '\n'.join(messages)
        my_log.log2(f'my_gigachat:chat: {str(unknown_error)}\n\nKey {key}\n\nPrompt: {prompt}\n\nMessages: {_messages_}\n\nRespond: {res_}\n\n{error_traceback}')


def reset(chat_id: str):
    """
    Reset the chat history for the given chat ID.

    :param chat_id: The ID of the chat to reset.
    :type chat_id: str
    """
    if chat_id in CHATS:
        CHATS[chat_id] = []


def get_mem_as_string(chat_id: str) -> str:
    """
    Returns the chat history as a string for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to get the history for.

    Returns:
        str: The chat history as a string.
    """
    if chat_id not in CHATS:
        CHATS[chat_id] = []
    mem = CHATS[chat_id]
    result = ''
    r = 'h'
    for x in mem: 
        if r == 'h':
            role = '𝐔𝐒𝐄𝐑'
            r = 'm'
            result += '\n'
        elif r == 'm':
            role = '𝐁𝐎𝐓'
            r = 'h'

        result += f'{role}: {x}\n'

    return result.strip()


def chat_cli():
    """
    A function that implements a command line interface for chatting. 
    It continuously takes user input, sends it to the chat function, and prints the response.
    """
    while(True):
        # Ввод пользователя
        user_input = input("User: ")
        res = chat(user_input, 'test')
        print("Bot: ", res)


if __name__ == '__main__':
    chat_cli()
    # print(get_mem_as_string('test'))
