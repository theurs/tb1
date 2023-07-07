#!/usr/bin/env python3


import concurrent.futures

import bingai
import cfg
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


def gen_images(prompt: str):
    """рисует одновременно и с помощью бинга и с сервисом от chimera"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future1 = executor.submit(bing, prompt)
        future2 = executor.submit(chimera, prompt)
        # Дождитесь завершения обоих функций
        result1 = future1.result()
        print('1')
        result2 = future2.result()
        print('2')
    return result1 + result2    


if __name__ == '__main__':
    print(gen_images('мотоцикл из золота под дождем'))
