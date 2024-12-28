#!/usr/bin/env python3
# если не доступно в стране то можно попробовать добавить это в hosts
# 50.7.85.220 copilot.microsoft.com
# 50.7.85.220 sydney.bing.com
# 50.7.85.220 edgeservices.bing.com
# 50.7.85.220 www.bing.com

import random

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


def get_images_v2(prompt: str,
               u_cookie: str,
               proxy: str = None,
               timeout: int = 60,
               max_generate_time_sec: int = 60):

    results = []

    sync_gen = ImageGen(auth_cookie=u_cookie)
    try:
        results = sync_gen.get_images(prompt)
    except Exception as error:
        if 'Your prompt has been rejected' in str(error):
            BAD_IMAGES_PROMPT[prompt] = True
        my_log.log_bing_img(f'get_images_v2: {error} \n\n {u_cookie} \n\nPrompt: {prompt}')

    if results:
        results = [x for x in results if '.bing.net/th/id/' in x]
        my_log.log_bing_success(f'{u_cookie}\n{proxy}\n{prompt}\n{results}')

    return results


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

    # используем только первую куку (одну)
    cookies = [x for x in COOKIE.items()]
    random.shuffle(cookies)

    if not cookies:
        # my_log.log_bing_img(f'get_images: {query} no cookies')
        return []

    cookie = cookies[0][0]

    if hasattr(cfg, 'bing_proxy') and cfg.bing_proxy:
        try:
            return get_images_v2(query, cookie, cfg.bing_proxy)
        except Exception as error:
            if 'location' in str(error) or 'timeout' in str(error) or 'Out of generate time' in str(error):
                my_log.log_bing_img(f'get_images: {error} Cookie: {cookie} Proxy: {cfg.bing_proxy}')
                return []
            if str(error).startswith('error1'):
                BAD_IMAGES_PROMPT[query] = True
                return [str(error),]
            else:
                my_log.log_bing_img(f'get_images: {error}\n\nQuery: {query}\n\nCookie: {cookie}\n\nProxy: {cfg.bing_proxy}')
    else:
        try:
            return get_images_v2(query, cookie)
        except Exception as error:
            if 'location' in str(error) or 'timeout' in str(error) or 'Out of generate time' in str(error):
                my_log.log_bing_img(f'get_images: {error} Cookie: {cookie}')
                return []
            if str(error).startswith('error1'):
                BAD_IMAGES_PROMPT[query] = True
                return []
            else:
                my_log.log_bing_img(f'get_images: {error}\n\nQuery: {query}\n\nCookie: {cookie}')

    return []


if __name__ == '__main__':
    print(gen_images('вкусный торт с медом и орехами'))
