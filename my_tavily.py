#!/usr/bin/env python3
# To install: pip install tavily-python
# pip install ftfy


import cachetools.func
import random
import traceback
from concurrent.futures import ThreadPoolExecutor

from tavily import TavilyClient
from ftfy import fix_text

import cfg
import my_db
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
            random.shuffle(KEYS)

    if KEYS:
        return KEYS.pop(0)
    else:
        return None


@cachetools.func.ttl_cache(maxsize=20, ttl=15*60)
def search(
    query: str,
    max_results: int = 10,
    search_depth: str = 'basic',
    fast: bool = False,
    user_id: str = '',
    ) -> dict:
    '''
    Делает максимальный запрос в Tavily

    query - поисковый запрос (не больше 400 символов??)
    max_results - максимальное количество результатов
    search_depth - глубина поиска ('basic', 'advanced')
    fast - быстрый поиск

    Возвращает ответ в виде словаря (или строку с ответом если быстрый режим)
    '''
    try:
        if not user_id:
            user_id = 'noname'

        key = get_next_key()
        query = query.strip()
        if not key or not query or len(query) < 2 or len(query) > 400:
            return ''
        client = TavilyClient(key)
        if fast:
            response = client.search(
                query=query,
                include_answer="advanced",
                include_images=False,
                include_image_descriptions=False,
                include_raw_content=False,
                max_results=max_results,
                search_depth=search_depth,
            )
            if 'answer' in response:
                response['answer'] = fix_text(response['answer'])
                if user_id:
                    my_db.add_msg(user_id, 'tavily')
                return response['answer']
        else:
            response = client.search(
                query=query,
                include_answer="advanced",
                include_images=True,
                include_image_descriptions=True,
                include_raw_content=True,
                max_results=max_results,
                search_depth=search_depth,
            )


        # --- Начало блока удаления дубликатов ---
        unique_results = []
        seen_urls = set()

        # Проходим по результатам после исправления кодировки
        for result in response['results']:
            # Проверяем наличие url и его тип
            if isinstance(result, dict) and 'url' in result and isinstance(result['url'], str):
                url = result['url']
                # Если url еще не встречался
                if url not in seen_urls:
                    unique_results.append(result) # Добавляем результат в новый список
                    seen_urls.add(url) # Отмечаем url как встреченный
            else:
                # Если результат не имеет url или url некорректен, просто добавляем его
                # или обрабатываем как ошибку, в зависимости от нужды.
                # Пока просто добавим, чтобы не потерять.
                # print(f"Warning: Result without valid 'url': {result}") # Можно добавить лог
                unique_results.append(result) # Можно пропустить, если url обязателен

        # Заменяем старый список результатов на новый, уникальный
        response['results'] = unique_results
        # --- Конец блока удаления дубликатов ---


        # Список ключей, в которых надо проверить и исправить кодировку
        # Добавляем 'answer' из верхнего уровня и поля внутри 'results'
        keys_to_check = ['title', 'content', 'raw_content']

        # Применяем функцию к полю 'answer' на верхнем уровне
        if 'answer' in response and isinstance(response['answer'], str):
            response['answer'] = fix_text(response['answer'])

        # Перебираем все результаты поиска в списке 'results'
        for result in response.get('results', []):
            # Перебираем нужные поля в каждом словаре результата
            for key in keys_to_check:
                if key in result and isinstance(result[key], str):
                    result[key] = fix_text(result[key])

        if user_id:
            my_db.add_msg(user_id, 'tavily')

        return response
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_tavily(f'search: {error}\n{traceback_error}')
        return {}


@cachetools.func.ttl_cache(maxsize=10, ttl=1*60)
def search_images(query: str, user_id: str = '') -> list:
    '''
    Retrieves a list of images from the Tavily search engine based on the given query.

    Args:
        query (str): The search query.
        user_id (str, optional): The user ID.

    Returns:
        list: A list of image as [(downloaded bytes, title),...]
    '''
    try:
        def download_image_wrapper(image):
            data = utils.download_image_as_bytes(image[0])
            title = image[1]
            return (data, title)

        response = search(query, user_id=user_id)

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
def search_text(query: str, user_id: str = '') -> str:
    '''
    Делает максимальный запрос в Tavily

    query - поисковый запрос
    user_id - id пользователя

    Возвращает ответ raw (джейсон в виде строки)
    '''
    response = search(query, user_id = user_id)
    if response:
        return str(response)
    else:
        return ''


@cachetools.func.ttl_cache(maxsize=10, ttl=1*60)
def search_text_fast(query: str, lang: str = '', user_id: str = '') -> str:
    '''
    Делает быстрый запрос в Tavily

    query - поисковый запрос (не больше 400 символов)
    lang - язык
    user_id - id пользователя

    Возвращает ответ строку
    '''
    if lang:
        query = f'Отвечай на языке *{lang}*\n\n{query}'
    if len(query) > 400:
        return ''
    response = search(query, max_results=5, search_depth='basic', fast = True, user_id = user_id)

    if response:
        return response
    else:
        return ''


if __name__ == '__main__':
    my_db.init(backup=False)

    print(search_text_fast('how can i create a python project', lang = 'ru'))

    my_db.close()
