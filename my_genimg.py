#!/usr/bin/env python3


import random
from multiprocessing.pool import ThreadPool

from duckduckgo_search import DDGS

import bingai
import gpt_basic
import my_log


def bing(prompt: str, moderation_flag: bool = False):
    """рисует 4 картинки с помощью далли и возвращает сколько смог нарисовать"""
    if moderation_flag:
        return []
    try:
        images = bingai.gen_imgs(prompt)
        if type(images) == list:
            return images
    except Exception as error_bing_img:
        print(f'my_genimg:bing: {error_bing_img}')
        my_log.log2(f'my_genimg:bing: {error_bing_img}')
    return []


def openai(prompt: str):
    """рисует 5 картинок с помощью openai и возвращает сколько смог нарисовать"""
    try:
        return gpt_basic.image_gen(prompt, amount = 5)
    except Exception as error_openai_img:
        print(f'my_genimg:openai: {error_openai_img}')
        my_log.log2(f'my_genimg:openai: {error_openai_img}')
    return []


def ddg_search_images(prompt: str, max_results: int = 10):
    """ищет картинки в поисковике"""
    result = []
    try:
        images = DDGS().images(prompt, size='Large', safesearch='on', license_image='Share')
        for image in images:
            result.append(image['image'])
            if len(result) > 20:
                break
    except Exception as error_ddg_img:
        print(f'my_genimg:ddg: {error_ddg_img}')
        my_log.log2(f'my_genimg:ddg: {error_ddg_img}')
    random.shuffle(result)
    return result[:max_results]


def gen_images(prompt: str, moderation_flag: bool = False):
    """рисует одновременно и с помощью бинга и с сервисом от chimera"""
    #return bing(prompt) + chimera(prompt)

    pool = ThreadPool(processes=2)

    async_result1 = pool.apply_async(bing, (prompt, moderation_flag))
    async_result2 = pool.apply_async(openai, (prompt,))
    async_result3 = pool.apply_async(openai, (prompt,))

    result = async_result1.get() + async_result2.get() + async_result3.get()

    # if len(result) < 10:
    #     result = result + ddg_search_images(prompt)
    return result[:10]


if __name__ == '__main__':
    print(ddg_search_images('сочная малина'))
