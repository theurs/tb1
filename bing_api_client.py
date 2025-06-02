#!/usr/bin/env python3


import requests
import threading
import traceback
from typing import List, Dict, Any

import my_log


# round robin BING_URLS
CURRENT_BING_APIS = []

CFG_LOCK = threading.Lock()


def get_base_url() -> str:
    '''
    Returns the base URL for the image generation API.
    Auto reload cfg.py if it has changed
    '''
    try:
        global CFG_FILE_TIMESTAMP, CURRENT_BING_APIS

        BASE_URL = ''
        ALL = []

        with CFG_LOCK:
            with open('cfg_bing.py', 'r') as f:
                ALL = f.read().split('\n')
                ALL = [x.strip() for x in ALL if not x.startswith('#') and x.strip()]

        if ALL:
            if not CURRENT_BING_APIS:
                CURRENT_BING_APIS = ALL[:]
            BASE_URL = CURRENT_BING_APIS.pop(0)

        return BASE_URL

    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_bing_api(f'bing_api_client:get_base_url: {error}\n\n{traceback_error}')
        return ''


def send_image_generation_request(prompt: str) -> List[str]:
    """
    Sends a POST request to the image generation API with the given prompt.

    :param prompt: The prompt for image generation.
    :return: A list of image URLs returned by the API.
    :raises requests.RequestException: If there's an error with the request.
    :raises json.JSONDecodeError: If the response is not a valid JSON.
    """
    url: str = get_base_url()

    if not url:
        return []

    headers: Dict[str, str] = {"Content-Type": "application/json"}
    data: Dict[str, str] = {"prompt": prompt[:900]}

    try:
        # Send the POST request
        response: requests.Response = requests.post(url, headers=headers, json=data, timeout=120)

        # Raise an exception for bad status codes
        response.raise_for_status()

        # Parse the JSON response
        json_response: Dict[str, Any] = response.json()

        # Extract the list of URLs
        image_urls: List[str] = json_response.get("urls", [])

        return image_urls

    except Exception as error:
        if '404 Client Error: NOT FOUND for url:' not in str(error):
            if 'timeout' in str(error).lower():
                my_log.log_bing_api(f'bing_api_client:send_image_generation_request1: {str(error)[:150]}')
            else:
                traceback_error = traceback.format_exc()
                my_log.log_bing_api(f'bing_api_client:send_image_generation_request3: {error}\n\n{traceback_error}')

    return []


def gen_images(prompt: str) -> List[str]:
    return send_image_generation_request(prompt)


if __name__ == "__main__":
    # Example prompt in Russian
    prompt: str = "Нарисуй закат на море с яркими оранжевыми и розовыми оттенками на небе а на переднем плане пусть будет одинокая лодка покачивающаяся на волнах"

    try:
        # Send the request and get the URLs
        urls: List[str] = gen_images(prompt)

        # Print the URLs
        for url in urls:
            print(url)

    except Exception as e:
        print(f"An error occurred: {e}")


'''
curl -X POST   -H "Content-Type: application/json"   -d '{
    "prompt": "a beautiful landscape"
  }'   http://172.28.1.10:58796/bing
'''
