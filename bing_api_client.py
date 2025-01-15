#!/usr/bin/env python3


import importlib
import json
import os
import requests
import traceback
from typing import List, Dict, Any

import cfg
import my_log


CFG_FILE_TIMESTAMP = 0


def get_base_url() -> str:
    '''
    Returns the base URL for the image generation API.
    Auto reload cfg.py if it has changed
    '''
    try:
        global CFG_FILE_TIMESTAMP

        if os.path.exists('cfg.py') and os.path.getmtime('cfg.py') != CFG_FILE_TIMESTAMP:
            CFG_FILE_TIMESTAMP = os.path.getmtime('cfg.py')
            module = importlib.import_module('cfg')
            importlib.reload(module)

        BASE_URL = cfg.BING_SECONDARY_URL if hasattr(cfg, 'BING_SECONDARY_URL') and cfg.BING_SECONDARY_URL else ''

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
    data: Dict[str, str] = {"prompt": prompt}

    try:
        # Send the POST request
        response: requests.Response = requests.post(url, headers=headers, json=data, timeout=90)
        
        # Raise an exception for bad status codes
        response.raise_for_status()
        
        # Parse the JSON response
        json_response: Dict[str, Any] = response.json()
        
        # Extract the list of URLs
        image_urls: List[str] = json_response.get("urls", [])
        
        return image_urls

    except Exception as error:
        if '404 Client Error: NOT FOUND for url:' not in str(error):
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
