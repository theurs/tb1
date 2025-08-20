#!/usr/bin/env python3
#pip install -U duckduckgo_search


import io
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image

from duckduckgo_search import DDGS

import cfg
import my_gemini3
import my_log
import utils


def chat_new_connection():
    '''Connect with proxy and return object'''
    if hasattr(cfg, 'DDG_PROXY'):
        return DDGS(proxy=random.choice(cfg.DDG_PROXY), timeout=30)
    else:
        return DDGS(timeout=30)


def get_links(query: str, max_results: int = 5) -> list:
    """
    Retrieves a list of links from the DuckDuckGo search engine based on the given query.

    Args:
        query (str): The search query.
        max_results (int, optional): The maximum number of results to return. Defaults to 5.

    Returns:
        list: A list of links found in the search results.

    Raises:
        Exception: If an error occurs during the search.

    Note:
        The `safesearch` parameter is set to 'off' to include potentially unsafe content in the search results.

    """
    try:
        results = chat_new_connection().text(query, max_results = max_results, safesearch='off')
        return [x['href'] for x in results]
    except Exception as error:
        my_log.log2(f'my_ddg:get_links: {error}')
        return []


def is_valid_image(data: bytes) -> bool:
    """
    Checks if the given bytes represent a valid image.

    Args:
        data: The image data as bytes.

    Returns:
        True if the data represents a valid image, False otherwise.
    """
    try:
        Image.open(io.BytesIO(data)).verify()
        return True
    except Exception:
        return False


def download_image_wrapper(image):
    data = utils.download_image_as_bytes(image[0])
    title = image[1]
    # detect if image is correct else data=None
    if not is_valid_image(data):
        data = None
    return (data, title)


def check_image_against_query(image) -> bool:
    """
    Check if an image is relevant to a given query by asking a superhot AI assistant.

    Args:
        image (tuple): A tuple containing the image data and the search query.

    Returns:
        bool: True if the image is relevant to the query, False otherwise.
    """
    query = f'''This image was found in google with the following query: {image[1]}

Decided if it is relevant to the query.
Answer supershot, your answer should be "yes" or "no" or "other".
'''
    result = my_gemini3.img2txt(image[0], query)
    return True if 'yes' in result.lower() else False


def get_images(query: str, max_results: int = 16) -> list:
    """
    Retrieves a list of images from the DuckDuckGo search engine based on the given query.

    Args:
        query (str): The search query.
        max_results (int, optional): The maximum number of results to return. Defaults to 16.

    Returns:
        list: A list of image as [(downloaded bytes, title),...]

    Raises:
        Exception: If an error occurs during the search.

    Note:
        The `safesearch` parameter is set to 'off' to include potentially unsafe content in the search results.

    """
    results = chat_new_connection().images(
        keywords=query,
        region="wt-wt",
        safesearch="off",
        # size='Large',
        size='Wallpaper',
        color=None,
        type_image=None,
        layout=None,
        license_image=None,
        max_results=max_results,
    )

    images_with_data = [(x['image'], x['title']) for x in results]

    # Downloading images.
    with ThreadPoolExecutor() as executor:
        result = list(executor.map(download_image_wrapper, images_with_data))

    # Filter only images that were successfully downloaded.
    images_to_check = [(img_data, query) for img_data, _ in result if img_data]

    # Now we use ThreadPoolExecutor to check images against the query in parallel.
    relevant_images = []
    with ThreadPoolExecutor() as executor:
        # Submit all check_image_against_query tasks to the executor.
        future_to_image = {executor.submit(check_image_against_query, image): image for image in images_to_check}

        # Iterate over completed tasks.
        for future in as_completed(future_to_image):
            image = future_to_image[future]
            try:
                is_relevant = future.result()  # Getting the result from check_image_against_query.
                if is_relevant:
                    relevant_images.append(image)  # If relevant add to the results list.
            except Exception as exc:
                print(f'Image relevance check generated an exception: {exc}')

    # Sort by data size.
    sorted_images = sorted(relevant_images, key=lambda x: len(x[0]), reverse=True)

    # restore lost titles
    restored_images = []
    for i in result:
        data = i[0]
        title = i[1]
        for j in sorted_images[:10]:
            data2 = j[0]
            if data == data2:
                restored_images.append((data, title))

    return restored_images


def reset(*args, **kwargs):
    """
    Заглушка.
    Эта функция принимает любое количество позиционных и именованных аргументов
    и ничего не делает.
    """
    pass


if __name__ == '__main__':
    pass

    # l = get_links('новейший авианосец')
    # print(l)

    p = get_images('новейший авианосец')
    print(p)
