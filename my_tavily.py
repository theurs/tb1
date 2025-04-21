#!/usr/bin/env python3
# To install: pip install tavily-python


import cachetools.func
import traceback
from concurrent.futures import ThreadPoolExecutor

from tavily import TavilyClient

import cfg
import my_log
import utils


KEYS = []


def get_next_key() -> str:
    '''
    Round robin keys cfg.TAVILY_KEYS
    '''
    global KEYS
    if not KEYS:
        if hasattr(cfg, 'TAVILY_KEYS') and len(cfg.TAVILY_KEYS) > 0:
            KEYS = cfg.TAVILY_KEYS[:]

    if KEYS:
        return KEYS.pop(0)
    else:
        return None


@cachetools.func.ttl_cache(maxsize=20, ttl=15*60)
def search(query: str, max_results: int = 5, search_depth: str = 'basic') -> dict:
    '''
    Делает максимальный запрос в Tavily
    
    query - поисковый запрос
    max_results - максимальное количество результатов
    search_depth - глубина поиска ('basic', 'advanced')

    Возвращает ответ в виде словаря
    '''
    try:
        key = get_next_key()
        if not key:
            return ''
        client = TavilyClient(key)
        response = client.search(
            query=query,
            include_answer="advanced",
            include_images=True,
            include_image_descriptions=True,
            include_raw_content=True,
            max_results=max_results,
            search_depth=search_depth,
        )
        return response
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_tavily(f'search: {error}\n{traceback_error}')
        return {}


@cachetools.func.ttl_cache(maxsize=10, ttl=1*60)
def search_images(query: str) -> list:
    '''
    Retrieves a list of images from the Tavily search engine based on the given query.

    Args:
        query (str): The search query.

    Returns:
        list: A list of image as [(downloaded bytes, title),...]
    '''
    try:
        def download_image_wrapper(image):
            data = utils.download_image_as_bytes(image[0])
            title = image[1]
            return (data, title)

        response = search(query)

        if 'images' in response:
            images_with_data = [(x['url'], x['description']) for x in response['images']]
            # Downloading images.
            with ThreadPoolExecutor() as executor:
                result = list(executor.map(download_image_wrapper, images_with_data))
            result = [x for x in result if x[0]]
            return result
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_tavily(f'search_images: {error}\n{traceback_error}')

    return []


@cachetools.func.ttl_cache(maxsize=10, ttl=1*60)
def search_text(query: str) -> str:
    '''
    Делает максимальный запрос в Tavily
    
    query - поисковый запрос
    
    Возвращает ответ raw
    '''
    response = search(query)
    if response:
        return str(response)
    else:
        return ''


if __name__ == '__main__':
    print(search('Как прошло 30 часовое перемирие'))
