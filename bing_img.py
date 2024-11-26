#!/usr/bin/env python3


import random
import threading

from sqlitedict import SqliteDict
from my_bingart import BingArt

import cfg
import my_log


# {cookie str: threading.Lock()}
COOKIE_LOCKS = {}


# limit user to 3 concurrent requests
# {id: threading.Semaphore(3)}
USER_LOCKS = {}


# do not use 1 same key at the same time for different requests
LOCKS = {}


# {cookie: times used, ...}
COOKIE = SqliteDict('db/bing_cookie.db', autocommit=True)
# {cookie:datetime, ...}

# storage of requests that Bing rejected, they cannot be repeated
# BAD_IMAGES_PROMPT = SqliteDict('db/bad_images_prompt.db', autocommit=True)
# BAD_IMAGES_PROMPT = {}


def get_images_v2(prompt: str,
               u_cookie: str,
               proxy: str = None,
               timeout: int = 60,
               max_generate_time_sec: int = 60):

    results = []
    cookies = [x for x in COOKIE.items()]
    if cookies:
        c = random.choice(cookies)[0]
        if c not in COOKIE_LOCKS:
            COOKIE_LOCKS[c] = threading.Lock()

        with COOKIE_LOCKS[c]:
            bing_art = BingArt(auth_cookie_U=c)
            try:
                results = bing_art.generate_images(prompt)
            except Exception as error:
                # if 'Your prompt has been rejected' in str(error):
                #     BAD_IMAGES_PROMPT[prompt] = True
                my_log.log_bing_img(f'get_images_v2: {error} \n\n {c} \n\nPrompt: {prompt}')
            finally:
                bing_art.close_session()

    if results:
        results = [image['url'] for image in results['images']]
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
    
    if user_id not in USER_LOCKS:
        USER_LOCKS[user_id] = threading.Semaphore(3)

    with USER_LOCKS[user_id]:
        # print(user_id, USER_LOCKS[user_id]._value)
    # with BIG_LOCK:
        # if query in BAD_IMAGES_PROMPT:
        #     my_log.log_bing_img(f'get_images: {query} is in BAD_IMAGES_PROMPT')
        #     return ['error1_Bad images',]

        # сортируем куки по количеству обращений к ним
        cookies = [x for x in COOKIE.items()]
        cookies = sorted(cookies, key=lambda x: x[1])
        cookies = [x[0] for x in cookies]

        for cookie in cookies:
            if cookie not in LOCKS:
                LOCKS[cookie] = threading.Lock()
            with LOCKS[cookie]:
                # сразу обновляем счетчик чтоб этот ключ ушел вниз списка
                COOKIE[cookie] += 1
                if hasattr(cfg, 'bing_proxy') and cfg.bing_proxy:
                    proxies = cfg.bing_proxy[:]
                    random.shuffle(proxies)
                    for proxy in proxies:
                        try:
                            # return get_images(query, cookie, proxy)
                            return get_images_v2(query, cookie, proxy)
                        except Exception as error:
                            if 'location' in str(error) or 'timeout' in str(error) or 'Out of generate time' in str(error):
                                my_log.log_bing_img(f'get_images: {error} Cookie: {cookie} Proxy: {proxy}')
                                return []
                            if str(error).startswith('error1'):
                                # BAD_IMAGES_PROMPT[query] = True
                                return [str(error),]
                            else:
                                my_log.log_bing_img(f'get_images: {error}\n\nQuery: {query}\n\nCookie: {cookie}\n\nProxy: {proxy}')
                else:
                    try:
                        # return get_images(query, cookie)
                        return get_images_v2(query, cookie)
                    except Exception as error:
                        if 'location' in str(error) or 'timeout' in str(error) or 'Out of generate time' in str(error):
                            my_log.log_bing_img(f'get_images: {error} Cookie: {cookie}')
                            return []
                        if str(error).startswith('error1'):
                            # BAD_IMAGES_PROMPT[query] = True
                            return []
                        else:
                            my_log.log_bing_img(f'get_images: {error}\n\nQuery: {query}\n\nCookie: {cookie}')

        return []


if __name__ == '__main__':
    print(gen_images('вкусный торт с медом и орехами'))
