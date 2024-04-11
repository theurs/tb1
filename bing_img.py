#!/usr/bin/env python3


import random
import time
import threading

import re
import requests
from sqlitedict import SqliteDict
from fake_useragent import UserAgent
from bingart import BingArt

import cfg
import my_log


# {cookie str: threading.Lock()}
COOKIE_LOCKS = {}


# limit user to 3 concurrent requests
# {id: threading.Semaphore(3)}
USER_LOCKS = {}


# do not use 1 same key at the same time for different requests
LOCKS = {}

# LOCK_STORAGE = threading.Lock()

# {cookie: times used, ...}
COOKIE = SqliteDict('db/bing_cookie.db', autocommit=True)
# {cookie:datetime, ...}

# storage of requests that Bing rejected, they cannot be repeated
BAD_IMAGES_PROMPT = SqliteDict('db/bad_images_prompt.db', autocommit=True)

ua = UserAgent(browsers=["edge"])
BING_URL = "https://www.bing.com"

# {proxy: (timestamp, external_ip)}
PROXY_ADDR_CACHE = SqliteDict('db/proxy_addr_cache.db', autocommit=True)
PROXY_ADDR_CACHE_MAX_TIME = 60*60*24


def get_external_ip(proxy):
    """
    Retrieves the external IP address using a proxy.

    Parameters:
    - proxy (str): The proxy to be used for the request.

    Returns:
    - str: The external IP address.
    """
    if proxy in PROXY_ADDR_CACHE:
        if time.time() - PROXY_ADDR_CACHE[proxy][0] < PROXY_ADDR_CACHE_MAX_TIME:
            return PROXY_ADDR_CACHE[proxy][1]
        else:
            del PROXY_ADDR_CACHE[proxy]
    session = requests.Session()
    session.proxies.update({'http': proxy, 'https': proxy})
    response = session.get('https://ifconfig.me')
    external_ip = response.text.strip() or '127.0.0.1'
    if external_ip != '127.0.0.1':
        PROXY_ADDR_CACHE[proxy] = (time.time(), external_ip)
    return external_ip


def get_images(prompt: str,
               u_cookie: str,
               proxy: str = None,
               timeout: int = 60,
               max_generate_time_sec: int = 60):
    """
    Retrieves a list of normal image links from Bing search based on a given prompt.
    
    Args:
        prompt (str): The search prompt to use for retrieving images.
        u_cookie (str): The user cookie for authentication.
        proxy (str, optional): The proxy server to use for the request. Defaults to None.
        timeout (int, optional): The timeout duration for the request in milliseconds. Defaults to 200.
        max_generate_time_sec (int, optional): The maximum time in seconds to wait for image generation. Defaults to 60.
        
    Raises:
        Exception: If the prompt is being reviewed by Bing.
        Exception: If the prompt has been blocked by Bing.
        Exception: If the language of the prompt is unsupported.
        Exception: If the request for image creation fails.
        TimeoutError: If the request times out while waiting for image generation.
        Exception: If no images are found in the search results.
        Exception: If any of the retrieved image links are in the list of bad images.
        
    Returns:
        list: A list of normal image links (URLs) from Bing search.
    """

    # FORWARDED_IP = get_external_ip(proxy)
    # FORWARDED_IP = f"1.0.0.{random.randint(0, 255)}"
    FORWARDED_IP = f"13.{random.randint(104, 107)}.{random.randint(0, 255)}.{random.randint(0, 255)}"
    HEADERS = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "max-age=0",
        "content-type": "application/x-www-form-urlencoded",
        "referrer": "https://www.bing.com/images/create/",
        "origin": "https://www.bing.com",
        "user-agent": ua.random,
        "x-forwarded-for": FORWARDED_IP,
    }

    url_encoded_prompt = requests.utils.quote(prompt)

    payload = f"q={url_encoded_prompt}&qs=ds"

    url = f"{BING_URL}/images/create?q={url_encoded_prompt}&rt=4&FORM=GUH2CR"

    session = requests.Session()
    if proxy:
        session.proxies.update({'http': proxy, 'https': proxy})
    session.headers = HEADERS
    session.cookies.set("_U", u_cookie)
    session.headers["user-agent"] = ua.random
    response = session.post(
        url,
        allow_redirects=False,
        data=payload,
        timeout=timeout,
    )
    # check for content waring message
    if "this prompt is being reviewed" in response.text.lower():
        raise Exception("error1_being_reviewed_prompt")
    if "this prompt has been blocked" in response.text.lower():
        raise Exception('error1_blocked_prompt')
    if "we're working hard to offer image creator in more languages" in response.text.lower():
        raise Exception('error1_unsupported_lang')
    if response.status_code != 302:
        url = f"{BING_URL}/images/create?q={url_encoded_prompt}&rt=3&FORM=GUH2CR"
        response = session.post(url, allow_redirects=False, timeout=timeout)
        if response.status_code != 302:
            Exception ('Image create failed pls check cookie or old image still creating')

    redirect_url = response.headers["Location"].replace("&nfy=1", "")
    request_id = redirect_url.split("id=")[-1]
    session.get(f"{BING_URL}{redirect_url}")

    polling_url = f"{BING_URL}/images/create/async/results/{request_id}?q={url_encoded_prompt}"

    start_wait = time.time()
    time_sec = 0
    while True:
        if int(time.time() - start_wait) > timeout:
            raise Exception('error2_timeout')
        response = session.get(polling_url)
        if response.status_code != 200:
            raise Exception('error2_noresults')
        if not response.text or response.text.find("errorMessage") != -1:
            time.sleep(1)
            time_sec = time_sec + 1
            if time_sec >= max_generate_time_sec:
                raise TimeoutError("Out of generate time")
            continue
        else:
            break
    # Use regex to search for src=""
    image_links = re.findall(r'src="([^"]+)"', response.text)
    # Remove size limit
    normal_image_links = [link.split("?w=")[0] for link in image_links]
    # Remove duplicates
    normal_image_links = list(set(normal_image_links))

    # Bad images
    bad_images = [
        "https://r.bing.com/rp/in-2zU3AJUdkgFe7ZKv19yPBHVs.png",
        "https://r.bing.com/rp/TX9QuO3WzcCJz1uaaSwQAz39Kb0.jpg",
    ]
    for img in normal_image_links:
        if img in bad_images:
            raise Exception("error1_Bad images")
    # No images
    if not normal_image_links:
        raise Exception('error_no_images')

    normal_image_links = [x for x in normal_image_links if not x.startswith('https://r.bing.com/')]
    time.sleep(5)
    my_log.log_bing_success(f'{u_cookie} {proxy} {prompt} {normal_image_links}')
    return normal_image_links


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
                if 'Your prompt has been rejected' in str(error):
                    BAD_IMAGES_PROMPT[prompt] = True
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
        if query in BAD_IMAGES_PROMPT:
            my_log.log_bing_img(f'get_images: {query} is in BAD_IMAGES_PROMPT')
            return ['error1_Bad images',]

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
                                BAD_IMAGES_PROMPT[query] = True
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
                            BAD_IMAGES_PROMPT[query] = True
                            return []
                        else:
                            my_log.log_bing_img(f'get_images: {error}\n\nQuery: {query}\n\nCookie: {cookie}')

        return []


if __name__ == '__main__':
    print(gen_images('вкусный торт с медом и орехами'))
