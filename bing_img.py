#!/usr/bin/env python3


import time
import threading
import socket

import random
import re

import requests

import cfg
import my_log
import my_dic


# не использовать 1 и тот же ключ одновременно для разных запросов
LOCKS = {}


# {0: cookie0, 1: cookie1, ...}
COOKIE = my_dic.PersistentDict('db/bing_cookie.pkl')

# хранилище запросов которые бинг отбраковал, их нельзя повторять
BAD_IMAGES_PROMPT = my_dic.PersistentDict('db/bad_images_prompt.pkl')


take_ip_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
take_ip_socket.connect(("8.8.8.8", 80))
FORWARDED_IP: str = take_ip_socket.getsockname()[0]
take_ip_socket.close()

BING_URL = "https://www.bing.com"
HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.77",
    "accept-language": "en,zh-TW;q=0.9,zh;q=0.8,en-GB;q=0.7,en-US;q=0.6",
    "cache-control": "max-age=0",
    "content-type": "application/x-www-form-urlencoded",
    "referrer": "https://www.bing.com/images/create/",
    "origin": "https://www.bing.com",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/119.0.0.0 "
                  "Safari/537.36 "
                  "Edg/119.0.0.0",
    "x-forwarded-for": FORWARDED_IP,
}


def get_images(prompt: str,
               u_cookie: str,
               proxy: str = None,
               timeout: int = 200,
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

    url_encoded_prompt = requests.utils.quote(prompt)

    payload = f"q={url_encoded_prompt}&qs=ds"

    url = f"{BING_URL}/images/create?q={url_encoded_prompt}&rt=4&FORM=GUH2CR"

    session = requests.Session()
    if proxy:
        session.proxies.update({'http': proxy, 'https': proxy})
    session.headers = HEADERS
    session.cookies.set("_U", u_cookie)

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
    return normal_image_links


def gen_images(query: str):
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
        my_log.log2(f'get_images: {query} is in BAD_IMAGES_PROMPT')
        return []
    cookies = []
    for x in COOKIE.items():
        cookie = x[1].strip()
        cookies.append(cookie)
        random.shuffle(cookies)
        for cookie in cookies:
            if cookie not in LOCKS:
                LOCKS[cookie] = threading.Lock()
            with LOCKS[cookie]:
                if cfg.bing_proxy:
                    for proxy in cfg.bing_proxy:
                        try:
                            return get_images(query, cookie, proxy)
                        except Exception as error:
                            my_log.log2(f'get_images: {error}\n\nQuery: {query}\n\nCookie: {cookie}\n\nProxy: {proxy}')
                            if str(error).startswith('error1'):
                                BAD_IMAGES_PROMPT[query] = True
                                return []
                else:
                    try:
                        return get_images(query, cookie)
                    except Exception as error:
                        my_log.log2(f'get_images: {error}')
    return []


if __name__ == '__main__':
    print(gen_images('fuck sex babe'))
