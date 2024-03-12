#!/usr/bin/env python3


import threading
import re
import requests

from gemini import Gemini, GeminiImage

import cfg
import my_log


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
    cookies = {
        "__Secure-1PSIDCC": token[0],
        "__Secure-1PSID":   token[1],
        "__Secure-1PSIDTS": token[2],
        "NID":              token[3]
        }

    if hasattr(cfg, 'bard_proxies') and cfg.bard_proxies:
        proxies = {"http": cfg.bard_proxies, "https": cfg.bard_proxies}
    else:
        proxies = None
    bard = Gemini(cookies=cookies, proxies=proxies, timeout=90)

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


def chat_request(query: str, dialog: str, reset = False):
    """
    Function to handle chat requests.

    Args:
        query (str): The user's input query.
        dialog (str): The dialog identifier.
        reset (bool, optional): Whether to reset the dialog state. Defaults to False.

    Returns:
        tuple: A tuple containing the response text, web images, and generated images.
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
        response = session.generate_content(query)
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
            response = session.generate_content(query)
        except Exception as error2:
            print(error2)
            my_log.log2(str(error2))
            return '', [], []

    result = response.text
    web_images_ = response.web_images
    generated_images_ = response.generated_images
    web_images = []
    generated_images = []
    
    
    if web_images_:
        for web_image in web_images_:
            web_image_url = str(web_image.url)
            web_image_title = web_image.title
            web_image_alt = web_image.alt
            web_images.append((web_image_url, web_image_title, web_image_alt))
            result = result.replace(web_image_title, ' ')

    if generated_images_:
        token = cfg.bard_tokens[current_token]
        cookies = {
            "__Secure-1PSIDCC": token[0],
            "__Secure-1PSID":   token[1],
            "__Secure-1PSIDTS": token[2],
            "NID":              token[3]
        }
        bytes_images_dict = GeminiImage.fetch_images_dict_sync(generated_images_, cookies=cookies)

        for generated_image in bytes_images_dict.keys():
            generated_images.append(bytes_images_dict[generated_image])

        result = re.sub(r"\[Imagen of .*\]", "", result)

    return result, web_images, generated_images


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
        response = session.generate_content(query, image=image)
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
            response = session.generate_content('query', image=image)
        except Exception as error2:
            print(error2)
            my_log.log2(str(error2))
            return ''

    return response.text


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


def generate_images(prompt: str, dialog: str = 'image_gen'):
    text, web, gen = chat_request(prompt, dialog)
    return gen


def test_chat():
    while 1:
        q = input('you: ')
        r = chat(q, 'test')
        print(f'bot: {r}')


if __name__ == "__main__":

    # print(chat_image('Что изображено на картинке? Отвечай на языке [de]', 0, open('1.jpg', 'rb').read()))
    # pass

    test_chat()

    for i in generate_images('generate image of wild makeup'):
        with open(f'{hash(i)}.jpg', 'wb') as f:
            f.write(i)

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
