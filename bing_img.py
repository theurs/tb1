#!/usr/bin/env python3
# если не доступно в стране то можно попробовать добавить это в hosts
# 50.7.85.220 copilot.microsoft.com
# 50.7.85.220 sydney.bing.com
# 50.7.85.220 edgeservices.bing.com
# 50.7.85.220 www.bing.com


import hashlib
import time
from collections import OrderedDict

from sqlitedict import SqliteDict
# from re_edge_gpt import ImageGen
from bing_lib import BingImageCreator

import my_log


# {cookie: times used, ...}
COOKIE = SqliteDict('db/bing_cookie.db', autocommit=True)

# {cookie:datetime, ...}

# storage of requests that Bing rejected, they cannot be repeated
BAD_IMAGES_PROMPT = OrderedDict()


# очереди для куков и проксей
COOKIES = []
PROXIES = []


PAUSED = {'time': 0}


def hash_prompt(prompt: str, length: int = 8) -> str:
    """
    Generates a short hash of the given prompt using blake2b.

    Args:
        prompt: The string to hash.
        length: The desired length of the hash in bytes (will be hex-encoded to double this length).

    Returns:
        A hexadecimal string representing the hash.
    """
    hash_object = hashlib.blake2b(prompt.encode('utf-8'), digest_size=length)
    return hash_object.hexdigest()


def get_cookie():
    global COOKIES
    if len(COOKIES) == 0:
        COOKIES = list(COOKIE.items())
    try:
        cookie = COOKIES.pop()[0]
    except IndexError:
        # my_log.log_bing_img(f'get_images: {query} no cookies')
        return None
    return cookie


def get_images_v2(prompt: str, timeout: int = 60, max_generate_time_sec: int = 60) -> list:
    global PAUSED
    try:
        results = []

        try:
            c = get_cookie()
            if not c:
                return []
            sync_gen = BingImageCreator(c)
            results = sync_gen.generate_images_sync(prompt)
        except Exception as error:
            my_log.log_bing_img(f'get_images_v2:1: {error} \n\n {c} \n\nPrompt: {prompt}')

            if 'Error generating Bing images for prompt' in str(error):
                BAD_IMAGES_PROMPT[hash_prompt(prompt)] = True
                if len(BAD_IMAGES_PROMPT) > 1000:
                    BAD_IMAGES_PROMPT.popitem(last=False)

                return [str(error),]
            elif 'Image create failed pls check cookie or old image still creating' in str(error):
                PAUSED['time'] = time.time() + 125

        time.sleep(20)

        if results:
            results = [x for x in results if '.bing.net/th/id/' in x]
            my_log.log_bing_success(f'{c}\n{prompt}\n{results}')

        if not results:
            my_log.log_bing_img(f'get_images_v2:3: empty results {c}\n{prompt}')

        return results or []

    except Exception as error:
        my_log.log_bing_img(f'get_images_v2:4: {error}')

    time.sleep(20)

    return []


def gen_images(query: str, user_id: str = ''):
    """
    Generate images based on the given query.

    Args:
        query (str): The query to generate images for.

    Returns:
        list: A list of generated images.

    Raises:
        Exception: If there is an error getting the images.

    """
    if hash_prompt(query) in BAD_IMAGES_PROMPT:
        my_log.log_bing_img(f'get_images: {query} is in BAD_IMAGES_PROMPT')
        return ['error1_Bad images',]

    try:
        return get_images_v2(query)
    except Exception as error:
        my_log.log_bing_img(f'get_images: {error}\n\nQuery: {query}')

    return []


if __name__ == '__main__':
    p1='''домик...

сепия, пастельные цвета бирюзово-голубого, серо-голубого, нежно-голубого, сиренево-голубого и легкий оттенок синего...
светлые цвета, мягкие тона, рассеянный свет...
реалистичный стиль...
сказка...
однотонный фон...
высокое разрешение...
детализация...
четкость всех предметов, а также четкий задний план...'''
    p2 = '''A poster make {Head top view} -  Dev_Artificial 

{Option feature key}

• High Image Generator
• Chat Gpt 
• Image Models
• Design
• clothes
• Music with Ai
• Q&A'''
    print(gen_images(p1))
    print(gen_images(p2))
