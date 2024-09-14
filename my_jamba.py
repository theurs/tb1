#!/usr/bin/env python3
#pip install -U "ai21>=2.13.0"

import json
import random
import sys
import time
import traceback

from ai21 import AI21Client
from ai21.models.chat import UserMessage, AssistantMessage, SystemMessage

import cfg
import my_log


SESSIONS = {}
CHATS = {}
MAX_LINES = 20
MAX_BYTES = 80000
MAX_REQUEST = 20000


def get_session(user_id: str, timeout: int, force: bool = False):
    if user_id not in SESSIONS or force:
        SESSIONS[user_id] = AI21Client(api_key=random.choice(cfg.JAMBA_KEYS), timeout_sec=timeout)
    return SESSIONS[user_id]


def update_mem(query: str, resp: str, chat_id: str):
    mem = []
    if chat_id in CHATS:
        mem = CHATS[chat_id]
    if len(mem) > 0 and isinstance(mem[-1], UserMessage):
        mem = mem[:-1]
    mem += [UserMessage(content=query), AssistantMessage(content=resp),]
    mem = mem[-MAX_LINES*2:]

    while sys.getsizeof(mem) > MAX_BYTES:
        mem = mem[2:]

    CHATS[chat_id] = mem    


def chat(
    prompt: str,
    user_id: str = 'test',
    system: str = '',
    model = 'jamba-1.5-mini',
    temperature: float = 1,
    max_tokens: int = 4000,
    timeout: int = 120,
) -> str:
    if not hasattr(cfg, 'JAMBA_KEYS'):
        return ''

    if not model:
        model = 'jamba-1.5-mini'

    mem = []
    if user_id in CHATS:
        mem = CHATS[user_id]
    if system:
        mem = [SystemMessage(content=system),] + mem
    mem += [UserMessage(content=prompt),]

    for _ in range(3):
        try:
            client = get_session(user_id, timeout)

            response = client.chat.completions.create(
                model=model,
                messages=mem,
                temperature=temperature,
                max_tokens=max_tokens,
                # response_format=
            )
            r = response.model_dump_json()
            data = json.loads(r)
            answer = data['choices'][0]['message']['content']
            if answer:
                update_mem(prompt, answer, user_id)
                return answer
            time.sleep(2)
            client = get_session(user_id, timeout, True)
        except Exception as error:
            error_traceback = traceback.format_exc()
            my_log.log_jamba(f'{error}\n\n{prompt}\n{system}\n{user_id} {model} {temperature} {max_tokens} {timeout}\n\n{error_traceback}')
            client = get_session(user_id, timeout, True)
    return ''


def get_mem_as_string(chat_id: str) -> str:
    """
    Returns the chat history as a string for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to get the history for.

    Returns:
        str: The chat history as a string.
    """
    try:
        mem = []
        if chat_id in CHATS:
            mem = CHATS[chat_id]
        result = ''
        for x in mem:
            if isinstance(x, UserMessage):
                role = '𝐔𝐒𝐄𝐑'
            elif isinstance(x, AssistantMessage):
                role = '𝐁𝐎𝐓'
            elif isinstance(x, SystemMessage):
                role = '𝐒𝐘𝐒𝐓𝐄𝐌'
            else:
                continue
            text = x.content
            if text.startswith('[Info to help you answer'):
                end = text.find(']') + 1
                text = text[end:].strip()
            result += f'{role}: {text}\n'
            if role == '𝐁𝐎𝐓':
                result += '\n'
        return result
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_jamba(f'my_openrouter:get_mem_as_string: {error}\n\n{error_traceback}')
        return ''


def undo(chat_id: str):
    """
    Undo the last two lines of chat history for a given chat ID.

    Args:
        chat_id (str): The ID of the chat.

    Raises:
        Exception: If there is an error while undoing the chat history.

    Returns:
        None
    """
    try:
        mem = []
        if chat_id in CHATS:
            mem = CHATS[chat_id]
            mem = mem[:-2]
            if mem:
                CHATS[chat_id] = mem
            else:
                del CHATS[chat_id]
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_jamba(f'Failed to undo chat {chat_id}: {error}\n\n{error_traceback}')


def reset(chat_id: str):
    """
    Resets the chat history for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to reset.

    Returns:
        None
    """
    if chat_id in CHATS:
        del CHATS[chat_id]


def chat_cli(model: str = ''):
    # s = 'отвечай всегда по-русски'
    s = ''
    while 1:
        q = input('>')
        if q == 'mem':
            print(get_mem_as_string('test'))
            continue
        r = chat(q, model = model, system=s)
        print(r)


if __name__ == '__main__':
    pass
    chat_cli()
