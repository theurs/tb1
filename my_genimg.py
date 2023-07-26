#!/usr/bin/env python3


from multiprocessing.pool import ThreadPool

import bingai
import gpt_basic
import my_log


def bing(prompt: str):
    """рисует 4 картинки с помощью далли и возвращает сколько смог нарисовать"""
    try:
        images = bingai.gen_imgs(prompt)
        if type(images) == list:
            return images
    except Exception as error_bing_img:
        print(f'my_genimg:bing: {error_bing_img}')
        my_log.log2(f'my_genimg:bing: {error_bing_img}')
    return []


def openai(prompt: str):
    """рисует 6 картинок с помощью openai и возвращает сколько смог нарисовать"""
    try:
        return gpt_basic.image_gen(prompt, amount = 6)
    except Exception as error_openai_img:
        print(f'my_genimg:openai: {error_openai_img}')
        my_log.log2(f'my_genimg:openai: {error_openai_img}')
    return []


def gen_images(prompt: str):
    """рисует одновременно и с помощью бинга и с сервисом от chimera"""
    #return bing(prompt) + chimera(prompt)

    pool = ThreadPool(processes=2)

    async_result1 = pool.apply_async(bing, (prompt,))
    async_result2 = pool.apply_async(openai, (prompt,))

    result = async_result1.get() + async_result2.get()

    return result[:10]


if __name__ == '__main__':
    print(gen_images('мотоцикл из золота под дождем'))
