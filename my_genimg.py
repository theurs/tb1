#!/usr/bin/env python3


from multiprocessing.pool import ThreadPool

import bingai
import cfg
import my_cattoGPT
import my_chimera


def bing(prompt: str):
    """рисует 4 картинки с помощью далли и возвращает сколько смог нарисовать"""
    try:
        images = bingai.gen_imgs(prompt)
        if type(images) == list:
            return images
    except Exception as error_bing_img:
        print(error_bing_img)

    return []


def chimera(prompt: str):
    """рисует 4 картинки с помощью кандинского и возвращает сколько смог нарисовать"""
    if cfg.key_chimeraGPT:
        try:
            return my_chimera.image_gen(prompt, amount = 4)
        except Exception as error_chimera_img:
            print(error_chimera_img)
            #my_log.log2(error_chimera_img)

    return []


def catto(prompt: str):
    """рисует 4 картинки с помощью кандинского и возвращает сколько смог нарисовать"""
    if cfg.key_cattoGPT:
        try:
            return my_cattoGPT.image_gen(prompt, amount = 4)
        except Exception as error_catto_img:
            print(error_catto_img)
            #my_log.log2(error_catto_img)

    return []


def gen_images(prompt: str):
    """рисует одновременно и с помощью бинга и с сервисом от chimera"""
    #return bing(prompt) + chimera(prompt)

    pool = ThreadPool(processes=4)

    async_result1 = pool.apply_async(bing, (prompt,))
    async_result2 = pool.apply_async(chimera, (prompt,))
    async_result3 = pool.apply_async(catto, (prompt,))

    result = async_result1.get() + async_result2.get() + async_result3.get()
    
    return result[:10]


if __name__ == '__main__':
    print(gen_images('мотоцикл из золота под дождем'))
