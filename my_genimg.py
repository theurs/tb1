#!/usr/bin/env python3


import json
import os
import random
from multiprocessing.pool import ThreadPool

import requests
import replicate
from duckduckgo_search import DDGS

import cfg
import bing_img
import gpt_basic
import my_log


def replicate_images(prompt: str, amount: int = 1):
    """рисует 1 картинку с помощью replicate и возвращает сколько смог нарисовать"""
    os.environ["REPLICATE_API_TOKEN"] = cfg.replicate_token

    MODELS = [  "stability-ai/sdxl:39ed52f2a78e934b3ba6e2a89f5b1c712de7dfea535525255b1aa35c5565e08b",
                "ai-forever/kandinsky-2:601eea49d49003e6ea75a11527209c4f510a93e2112c969d548fbb45b9c4f19f",
                "stability-ai/stable-diffusion:27b93a2413e7f36cd83da926f3656280b2931564ff050bf9575f1fdf9bcd7478"]

    results = []

    # model = random.choice(MODELS)
    model = MODELS[1]

    for _ in range(amount):
        if len(results) > amount:
            break

        try:
            r = replicate.run(
                model,
                input={"prompt": prompt, "width": 1024, "height": 1024},
            )
            for x in r:
                results.append(x)
            if len(results) > amount:
                break
        except Exception as error_replicate_img:
            my_log.log2(f'my_genimg:replicate: {error_replicate_img}')

    return results


def bing(prompt: str, moderation_flag: bool = False, user_id: str = ''):
    """рисует 4 картинки с помощью далли и возвращает сколько смог нарисовать"""
    if moderation_flag:
        return []
    try:
        images = bing_img.gen_images(prompt, user_id)
        if type(images) == list:
            return images
    except Exception as error_bing_img:
        my_log.log2(f'my_genimg:bing: {error_bing_img}')
    return []


def openai(prompt: str):
    """рисует 4 картинки с помощью openai и возвращает сколько смог нарисовать"""
    try:
        return gpt_basic.image_gen(prompt, amount = 4)
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


def wizmodel_com(prompt: str):
    if not hasattr(cfg, 'WIZMODEL_API') or not cfg.WIZMODEL_API:
        return []

    url = "https://api.wizmodel.com/v1/predictions"
    
    if cfg.bing_proxy:
        proxy = {'http': random.choice(cfg.bing_proxy), 'https': random.choice(cfg.bing_proxy)}
    else:
        proxy = None

    payload = json.dumps({
        "input": {
            "prompt": prompt
            },
        "version": "7d229e3ed5d01c879622d0cd273572260b7e35103d6765af740f853b160d04b7"
        }
                         )

    api_key = random.choice(cfg.WIZMODEL_API[0])
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}'
        }

    try:
        response = requests.request("POST", url, headers=headers, data=payload, timeout = 200, proxies=proxy)
    except Exception as error:
        my_log.log2(f'my_genimg:wizmodel_com: {error}\n\nPrompt: {prompt}')
        return []

    return response.text


def gen_images(prompt: str, moderation_flag: bool = False, user_id: str = ''):
    """рисует одновременно всеми доступными способами"""
    #return bing(prompt) + chimera(prompt)

    # prompt_tr = gpt_basic.translate_image_prompt(prompt)

    pool = ThreadPool(processes=6)

    async_result1 = pool.apply_async(bing, (prompt, moderation_flag, user_id))
    # async_result2 = pool.apply_async(openai, (prompt_tr,))

    # async_result3 = pool.apply_async(replicate_images, (prompt_tr,))
    # async_result4 = pool.apply_async(replicate_images, (prompt_tr,))
    # async_result5 = pool.apply_async(replicate_images, (prompt_tr,))
    # async_result6 = pool.apply_async(replicate_images, (prompt_tr,))

    result = async_result1.get() #+ async_result2.get() + async_result3.get() + async_result4.get() + async_result5.get() + async_result6.get()

    # if len(result) < 10:
    #     result = result + ddg_search_images(prompt)
    return result[:10]


if __name__ == '__main__':
    # print(ddg_search_images('сочная малина'))
    # print(gen_images('рисунок мальчика с чёрными волосами в костюме жирафа и девочки с рыжими волосами в костюме лисы, наклейки, логотип, минимализм, в новый год, наряжают ёлку'))
    print(wizmodel_com('firewalled daemon'))
