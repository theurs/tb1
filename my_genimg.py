#!/usr/bin/env python3


import base64
import json
import os
import random
import re
import time
import threading
import traceback
from multiprocessing.pool import ThreadPool

import requests

import bing_api_client
import cfg
import my_cerebras
import my_db
import my_gemini3
import my_gemini_general
import my_gemini_genimg
import my_groq
import my_log
import my_mistral
import my_openrouter_free
import my_pollinations
import utils
from my_nebius import txt2img as flux_nebius


# {hash of image:model name, ...}
WHO_AUTOR = {}


# попробовать заблокировать параллельные вызовы бинга
BING_LOCK = threading.Lock()
# 0 - main, 1 - second instance
# если есть второй инстанс с бингом то переключаться между ними циклично
BING_SWITCH = 0


def openrouter_gen(prompt: str, user_id: str) -> list[bytes]:
    """
    Wrapper for my_openrouter_free.txt2img to align with ThreadPool usage.

    Args:
        prompt: The text prompt for the image.
        user_id: The user's ID for logging.

    Returns:
        A list containing the image bytes, or an empty list on failure.
    """
    # Attempt to fetch the image data using the OpenRouter API
    data: bytes | None = my_openrouter_free.txt2img(prompt, user_id=user_id)
    if data:
        # If successful, register the author and return data in a list
        WHO_AUTOR[utils.fast_hash(data)] = my_openrouter_free.GEMINI25_FLASH_IMAGE
        return [data]
    # Return an empty list if fetching failed
    return []


def pollinations_gen(prompt: str, width: int = 1024, height: int = 1024, model: str = "fluxxx") -> list[bytes]:
    """
    Wrapper for my_pollinations.fetch_image_bytes to align with ThreadPool usage.

    Args:
        prompt: The text prompt for the image.
        width: Image width.
        height: Image height.

    Returns:
        A list containing the image bytes, or an empty list on failure.
    """
    # Attempt to fetch the image data
    data: bytes | None = my_pollinations.fetch_image_bytes(prompt, width, height, model)
    if data:
        # If successful, register the author and return data in a list
        WHO_AUTOR[utils.fast_hash(data)] = 'pollinations.ai flux'
        return [data]
    # Return an empty list if fetching failed
    return []


def gemini_flash(prompt: str, width: int = 1024, height: int = 1024, num: int = 1, negative_prompt: str = "", user_id: str = ''):
    """
    Generates images based on a prompt using the bigmodel.cn API.

    Args:
        prompt (str): The prompt for generating the images.
        width (int, optional): The width of the images. Defaults to 1024.
        height (int, optional): The height of the images. Defaults to 1024.
        num (int, optional): The number of images to generate. Defaults to 1.

    Returns:
        list: A list of generated images in bytes format.
    """
    try:
        if num > 1:
            results = []
            for _ in range(num):
                images = gemini_flash(prompt, width, height, 1, negative_prompt)
                if not images:
                    return []
                image = images[0]
                results.append(image)
            return results

        data = my_gemini_genimg.generate_image(prompt, user_id=user_id)
        results = []
        if data:
            WHO_AUTOR[utils.fast_hash(data)] = my_gemini_genimg.MODEL
            results.append(data)
            return results

    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_reprompt_moderation(f'gemini 2.0 flash exp: {error}\n\n{error_traceback}')

    return []


def bing(
    prompt: str,
    moderation_flag: bool = False,
    user_id: str = '',
    model: str = 'dalle'
):
    """
    Рисует бингом, не больше 1 потока и 20 секунд пауза между запросами
    Ограничение на размер промпта 950, хз почему


    1 кука, пауза между запросами на рисование 20 секунд

    Одновременно используй только 1 аккаунт.
    Когда с ним проблемы, то переключайся на другой и меняй IP.
    Куки обновляй с той же страны, что и прокси, например США.

    У меня так работает.
    Два прокси США, которые меняются с каждым переключением аккаунта.
    Раз в месяц я их меняю на новые.

    """
    global BING_SWITCH

    # prompt = prompt.strip()[:950] # нельзя больше 950?
    prompt = prompt.strip()

    if moderation_flag or prompt.strip() == '':
        return []

    try:
        with BING_LOCK:
            images = []
            if os.path.exists('cfg_bing.py'):
                images = bing_api_client.gen_images(prompt, model=model)

                if images:
                    my_log.log_bing_success('BING SUCCESS ' + prompt + '\n\n' + '\n'.join(images))
                else:
                    my_log.log_bing_img('BING FAILED ' + prompt)

            if any([x for x in images if not x.startswith('https://')]):
                return images

        if type(images) == list:
            return list(set(images))
    except Exception as error_bing_img:
        my_log.log_bing_img(f'my_genimg:bing: {error_bing_img}')
    return []


class FusionBrainAPI:

    def __init__(self, url, api_key, secret_key):
        self.URL = url
        self.AUTH_HEADERS = {
            'X-Key': f'Key {api_key}',
            'X-Secret': f'Secret {secret_key}',
        }

    def get_pipeline(self):
        response = requests.get(self.URL + 'key/api/v1/pipelines', headers=self.AUTH_HEADERS)
        data = response.json()
        return data[0]['id']

    def generate(self, prompt, pipeline, images=1, width=1024, height=1024, negative_prompt=""):
        params = {
            "type": "GENERATE",
            "numImages": images,
            "width": width,
            "height": height,
            "generateParams": {
                "query": f"{prompt}"
            }
        }
        if negative_prompt:
            params["negativePromptDecoder"] = negative_prompt
        # Add style here if needed, e.g., params["style"] = "ANIME"
        data = {
            'pipeline_id': (None, pipeline),
            'params': (None, json.dumps(params), 'application/json'),
            'number_of_files': (None, str(images))
        }
        response = requests.post(self.URL + 'key/api/v1/pipeline/run', headers=self.AUTH_HEADERS, files=data)
        data = response.json()
        return data.get('uuid', '')

    def check_generation(self, request_id, attempts=10, delay=10):
        while attempts > 0:
            response = requests.get(self.URL + 'key/api/v1/pipeline/status/' + request_id, headers=self.AUTH_HEADERS)
            data = response.json()
            if data['status'] == 'DONE':
                return base64.b64decode(data['result']['files'][0])

            attempts -= 1
            time.sleep(delay)

        return None


def kandinski(prompt: str, width: int = 1024, height: int = 1024, num: int = 1, negative_prompt: str = ""):
    """
    Generates images based on a prompt using the Fusion Brain Kandinsky API (aligned with provided docs).

    Args:
        prompt (str): The prompt for generating the images.
        width (int, optional): The width of the images. Defaults to 1024. Recommended multiple of 64.
        height (int, optional): The height of the images. Defaults to 1024. Recommended multiple of 64.
        num (int, optional): The number of images to generate. NOTE: API docs state only 1 is supported. Defaults to 1.
        negative_prompt (str, optional): Negative prompt to guide the generation away from certain elements. Defaults to "".

    Returns:
        list: A list of generated images in bytes format, or an empty list on failure/censorship.
    """
    if num != 1:
        print(f"Warning: Kandinsky API documentation states only num=1 is supported. Forcing num=1.")
        num = 1 # Enforce API limitation

    # игнорируем негативный промпт потому что бот его не так как надо делает
    negative_prompt = ''

    try:
        if not hasattr(cfg, 'KANDINSKI_API') or not cfg.KANDINSKI_API:
            # my_log.log_reprompt_moderation('my_genimg:kandinski:1: KANDINSKI_API not configured in cfg.')
            return []

        keys = cfg.KANDINSKI_API[:]
        if not keys:
             my_log.log_reprompt_moderation('my_genimg:kandinski:2: No API keys found in cfg.KANDINSKI_API.')
             return []

        key_pair = random.choice(keys)
        api_key = key_pair[0]
        secret_key = key_pair[1]


        api = FusionBrainAPI('https://api-key.fusionbrain.ai/', api_key, secret_key)
        pipeline_id = api.get_pipeline()
        uuid = api.generate(
            prompt,
            pipeline_id,
            width=width,
            height=height,
            negative_prompt=negative_prompt
            )
        if not uuid:
            return []
        data = api.check_generation(uuid)
        if not data:
            return []

        results = []
        WHO_AUTOR[utils.fast_hash(data)] = 'fusionbrain.ai'
        results.append(data)
        return results

    except Exception as error:
        # Catch-all for unexpected errors
        error_traceback = traceback.format_exc()
        my_log.log_reprompt_moderation(f'my_genimg:kandinski:3: Unhandled exception: {error}\n\n{error_traceback}')
        return []


def get_reprompt(prompt: str, conversation_history: str = '', chat_id: str = '') -> tuple[str, str] | None:
    """
    Function to get a reprompt for image generation based on user's prompt and conversation history.
    Parameters:
    - prompt: a string containing the user's prompt
    - conversation_history: a string containing the conversation history
    Returns:
    - a string representing the reprompt for image generation
    """


    # # cerebras быстрый и хорошие модели, но склонен затупить и висеть до таймаута
    # r1, r2 = my_cerebras.get_reprompt(prompt, conversation_history, chat_id)
    # if r1 or r2:
    #     return r1,r2


    try:
        conversation_history = conversation_history.replace('𝐔𝐒𝐄𝐑:', 'user:')
        conversation_history = conversation_history.replace('𝐁𝐎𝐓:', 'bot:')

        prompt = prompt.strip()
        dont_translate = prompt.startswith('!')
        prompt = re.sub(r'^!+', '', prompt).strip()

        query = f'''
User want to create image with text to image generator.
Repromt user's PROMPT for image generation.
Generate a good detailed prompt in english language, image generator accept only english so translate if needed.
Answer as a professional image prompt engineer, answer completely grammatically correct and future rich, add details if it was short.
A negative prompt in image generation lets you specify what you DON'T want to see in the picture. It helps exclude unwanted objects, styles, colors, or other characteristics, giving you more control over the result and speeding up the generation process.

Example:

Prompt: "Cat in a wizard hat"

Negative prompt: "sad, angry, blurry, cartoon"

Result: The AI will generate an image of a cat in a wizard hat that looks realistic, rather joyful or neutral, not sad or angry, and the image will be sharp, not blurry.

Start your prompt with word Generate.


User's PROMPT: {prompt}

Dialog history: {conversation_history}

Using this JSON schema:
  reprompt = {{"was_translated": str, "lang_from": str, "reprompt": str, "negative_reprompt": str, "moderation_sexual": bool, "moderation_hate": bool}}
Return a `reprompt`
'''

        negative = ''
        reprompt = ''
        r = ''

        if not r:
            r = my_gemini3.get_reprompt_for_image(query, chat_id)
        if r:
            reprompt, negative, moderation_sex, moderation_hate = r
            if moderation_sex or moderation_hate:
                return 'MODERATION', None
        if not reprompt:
            r = my_mistral.get_reprompt_for_image(query, chat_id)
            if r:
                reprompt, negative, moderation_sex, moderation_hate = r
                if moderation_sex or moderation_hate:
                    return 'MODERATION', None

    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_reprompt_moderation(f'my_genimg:get_reprompt: {error}\n\nPrompt: {prompt}\n\n{error_traceback}')
    if dont_translate:
        my_log.log_reprompt_moderations(f'get_reprompt:\n\n{prompt}\n\n{prompt}\n\nNegative: {negative}')
    else:
        my_log.log_reprompt_moderations(f'get_reprompt:\n\n{prompt}\n\n{reprompt}\n\nNegative: {negative}')

    if dont_translate:
        return prompt, negative

    return reprompt, negative


def gen_images_bing_only(
    prompt: str,
    user_id: str = '',
    conversation_history: str ='',
    iterations: int = 1,
    model: str = 'dalle'
) -> list:
    if iterations == 0:
        iterations = 1

    if prompt.strip() == '':
        return []

    # переводим на английский и модерируем
    reprompt, _ = get_reprompt(prompt, conversation_history)

    if reprompt == 'MODERATION':
        # если сработала модерация но юзер в белом списке то ок
        if hasattr(cfg, 'ALLOW_PASS_NSFW_FILTER') and utils.extract_user_id(user_id) in cfg.ALLOW_PASS_NSFW_FILTER:
            reprompt = prompt
        # если сработала модерация то возвращаем ошибку
        else:
            return ['moderation',]

    # если промпт начинается с ! то не переводим
    if prompt.startswith('!'):
        reprompt = re.sub(r'^!+', '', prompt).strip()
    # # если модель гпт то тоже не переводим
    # if model == 'gpt':
    #     reprompt = prompt.strip()

    if reprompt.strip():
        result = []
        for _ in range(iterations):
            r = bing(reprompt, user_id=user_id, model=model)
            if r:
                result += r
            else:
                # если не получилось рисовать то выходим на случай когда промпт плохой, но белому списку доверяем
                if hasattr(cfg, 'ALLOW_PASS_NSFW_FILTER') and utils.extract_user_id(user_id) in cfg.ALLOW_PASS_NSFW_FILTER:
                    continue
                else:
                    break

        return result

    return []


def flux_nebius_gen1(prompt: str, negative_prompt: str, model: str = None):
    '''
    Generate images with Flux Nebius model. Flux dev
    '''
    try:
        image = flux_nebius(prompt, negative_prompt, model)
        if image:
            results = []
            WHO_AUTOR[utils.fast_hash(image)] = 'nebius.ai black-forest-labs/flux-dev'
            results.append(image)
            return results
        else:
            return []
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_reprompt_moderation(f'flux_nebius_gen1: {error}\n{traceback_error}')
        return []


def gen_images(
    prompt: str,
    moderation_flag: bool = False,
    user_id: str = '',
    conversation_history: str = '',
    use_bing: bool = True
) -> list:
    """рисует одновременно всеми доступными способами"""
    if not user_id:
        user_id = 'test'

    if prompt.strip() == '':
        return []

    negative = ''
    original_prompt = prompt

    reprompt, negative = get_reprompt(prompt, conversation_history, user_id)
    if reprompt == 'MODERATION':
        return ['moderation',]

    if reprompt:
        prompt = reprompt
    else:
        return []

    bing_prompt = original_prompt if original_prompt.startswith('!') else prompt
    bing_prompt = re.sub(r'^!+', '', bing_prompt).strip()

    pool = ThreadPool(processes=10)

    async_result_openrouter1 = pool.apply_async(openrouter_gen, (prompt, user_id))
    async_result2 = pool.apply_async(kandinski, (prompt, 1024, 1024, 1, negative))
    async_result3 = pool.apply_async(kandinski, (prompt, 1024, 1024, 1, negative))
    async_result10 = pool.apply_async(gemini_flash, (prompt, 1024, 1024, 1, negative, user_id))
    async_result_pollinations = pool.apply_async(pollinations_gen, (prompt,))

    if use_bing:
        async_result1 = pool.apply_async(bing, (bing_prompt, moderation_flag, user_id))

        result = (async_result_openrouter1.get() or []) + \
                 (async_result1.get() or []) + \
                 (async_result2.get() or []) + \
                 (async_result3.get() or []) + \
                 (async_result10.get() or []) + \
                 (async_result_pollinations.get() or [])
    else:
        result = (async_result_openrouter1.get() or []) + \
                 (async_result2.get() or []) + \
                 (async_result3.get() or []) + \
                 (async_result10.get() or []) + \
                 (async_result_pollinations.get() or [])

    return result


if __name__ == '__main__':
    my_db.init(backup=False)
    my_groq.load_users_keys()
    my_gemini_general.load_users_keys()
    my_mistral.load_users_keys()

    # print(get_reprompt('Потрясающая блондинка с длинными распущенными волосами сидит на деревянной лестнице. На ней минимум одежды, ее тело полностью видно с акцентом на вульву, демонстрируя ее гладкую, безупречную кожу и естественную красоту. Освещение мягкое и естественное, подчеркивающее ее изгибы и текстуру кожи. Высокая детализация, разрешение 8K, фотореалистичная фотография, отмеченная наградами.'))
    # print(get_reprompt('картину где бабушка сидит во рту с огурцами рядом сидит ее внучка пишет математику, а сверху бог летает'))

    # print(gen_images('golden apple', use_bing=False))

    # r = gemini_flash('golden apple', num = 2)
    # print(r)


    # r = kandinski('рука ладонью вверх все пальцы отчетливо видно', 1024, 1024, 1, negative_prompt = 'ugly')
    # with open(r'C:\Users\user\Downloads\1.jpg', 'wb') as f:
    #     f.write(r[0])

    my_db.close()