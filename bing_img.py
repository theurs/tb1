#!/usr/bin/env python3
# если не доступно в стране то можно попробовать добавить это в hosts
# 50.7.85.220 copilot.microsoft.com
# 50.7.85.220 sydney.bing.com
# 50.7.85.220 edgeservices.bing.com
# 50.7.85.220 www.bing.com

import time

from sqlitedict import SqliteDict
from re_edge_gpt import ImageGen

import cfg
import my_log


# {cookie: times used, ...}
COOKIE = SqliteDict('db/bing_cookie.db', autocommit=True)
# {cookie:datetime, ...}

# storage of requests that Bing rejected, they cannot be repeated
# BAD_IMAGES_PROMPT = SqliteDict('db/bad_images_prompt.db', autocommit=True)
BAD_IMAGES_PROMPT = {}


# очереди для куков и проксей
COOKIES = []
PROXIES = []


def get_cookie():
    global COOKIES
    if len(COOKIES) == 0:
        COOKIES = list(COOKIE.items())
    try:
        cookie = COOKIES.pop()[0]
    except IndexError:
        # my_log.log_bing_img(f'get_images: {query} no cookies')
        raise Exception('no cookies')
    return cookie


def get_proxy():
    global PROXIES
    if hasattr(cfg, 'bing_proxy') and cfg.bing_proxy:
        proxies = cfg.bing_proxy[:]
    else:
        proxies = []

    if len(PROXIES) == 0:
        PROXIES = proxies[:]

    try:
        proxy = PROXIES.pop()
    except IndexError:
        proxy = None

    return proxy


def get_images_v2(prompt: str, timeout: int = 60, max_generate_time_sec: int = 60) -> list:
    try:
        results = []
        proxy = get_proxy()

        try:
            c = get_cookie()
            sync_gen = ImageGen(auth_cookie=c, quiet=True, proxy=proxy)
            results = sync_gen.get_images(prompt)
        except Exception as error:
            my_log.log_bing_img(f'get_images_v2: {error} \n\n {c} \n\nPrompt: {prompt}')
            if 'Bad images' in str(error) or \
                'Your prompt is being reviewed by Bing. Try to change any sensitive words and try again.' in str(error) or \
                'Your prompt has been blocked by Bing. Try to change any bad words and try again' in str(error):
                BAD_IMAGES_PROMPT[prompt] = True
                return [str(error),]
            elif 'Image create failed pls check cookie or old image still creating' in str(error):
                time.sleep(60)
                try:
                    cc = get_cookie()
                    sync_gen = ImageGen(auth_cookie=cc, quiet=True, proxy=proxy)
                    results = sync_gen.get_images(prompt)
                except Exception as error2:
                    my_log.log_bing_img(f'get_images_v2: {error2} \n\n {cc} \n\nPrompt: {prompt}')
                    time.sleep(60)

        if results:
            results = [x for x in results if '.bing.net/th/id/' in x]
            my_log.log_bing_success(f'{c}\n{proxy}\n{prompt}\n{results}')

        return results

    except Exception as error:
        my_log.log_bing_img(f'get_images_v2: {error}')

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
    if query in BAD_IMAGES_PROMPT:
        my_log.log_bing_img(f'get_images: {query} is in BAD_IMAGES_PROMPT')
        return ['error1_Bad images',]

    try:
        return get_images_v2(query)
    except Exception as error:
        my_log.log_bing_img(f'get_images: {error}\n\nQuery: {query}')

    return []


if __name__ == '__main__':
    print(gen_images('вкусный торт с медом и орехами'))
