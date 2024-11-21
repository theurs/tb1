#!/usr/bin/env python3


import base64
import glob
import io
import json
import os
import random
import shutil
import time
import threading
import traceback
from multiprocessing.pool import ThreadPool
from io import BytesIO

import gradio_client
import PIL
import requests
from sqlitedict import SqliteDict
from PIL import Image

import bing_img
import cfg
import my_gemini
import my_glm
import my_groq
import my_log
import my_prodia
import my_runware_ai
import utils


DEBUG = cfg.DEBUG if hasattr(cfg, 'DEBUG') else False


# каждый юзер дает свои ключи и они используются совместно со всеми
# {full_chat_id as str: key as str}
# {'[9123456789] [0]': 'key1', ...}
USER_KEYS = SqliteDict('db/huggingface_user_keys.db', autocommit=True)
# list of all users keys
ALL_KEYS = []
USER_KEYS_LOCK = threading.Lock()


# {hash of image:model name, ...}
WHO_AUTOR = {}

# не давать генерировать картинки больше чем 1 за раз для 1 юзера
# {userid:lock}
LOCKS = {}


def load_users_keys():
    """
    Load users' keys into memory and update the list of all keys available.
    """
    with USER_KEYS_LOCK:
        global USER_KEYS, ALL_KEYS
        if hasattr(cfg, 'huggin_face_api') and cfg.huggin_face_api:
            ALL_KEYS = cfg.huggin_face_api
        for user in USER_KEYS:
            key = USER_KEYS[user]
            if key not in ALL_KEYS:
                ALL_KEYS.append(key)


def upscale(image_bytes: bytes) -> bytes:
    """
    Увеличивает размер изображения, если его ширина или высота меньше 1024 пикселей,
    с сохранением хорошего качества.

    Args:
        image_bytes: Байты изображения.

    Returns:
        Байты увеличенного изображения или исходные байты, если увеличение не требуется.
    """
    try:
        image = Image.open(BytesIO(image_bytes))
        width, height = image.size

        if width < 1024 or height < 1024:
            if width > height:
                new_width = 1024
                new_height = int(height * (1024 / width))
            else:
                new_height = 1024
                new_width = int(width * (1024 / height))

            # Используем качественный алгоритм ресайза (Lanczos)
            resized_image = image.resize((new_width, new_height), Image.LANCZOS)

            # Сохраняем изображение в байты
            output_buffer = BytesIO()
            resized_image.save(output_buffer, format=image.format)
            return output_buffer.getvalue()
        else:
            return image_bytes
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_huggin_face_api(f'my_genimg:upscale: {error}\n\n{error_traceback}')
        return image_bytes


def bing(prompt: str, moderation_flag: bool = False, user_id: str = ''):
    """рисует 4 картинки с помощью далли и возвращает сколько смог нарисовать"""
    if moderation_flag or prompt.strip() == '':
        return []
    try:
        images = bing_img.gen_images(prompt, user_id)
        if type(images) == list:
            return list(set(images))
    except Exception as error_bing_img:
        my_log.log_bing_img(f'my_genimg:bing: {error_bing_img}')
    return []


def remove_huggin_face_key(api_key: str):
    '''Remove an API key from the list of valid API keys'''
    try:
        global ALL_KEYS
        ALL_KEYS.remove(api_key)
        user = 'unknown'
        for user in USER_KEYS:
            if USER_KEYS[user] == api_key:
                del USER_KEYS[user]
                break
        my_log.log_keys(f'Invalid key {api_key} removed, user {user}')
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_huggin_face_api(f'Failed to remove key {api_key}: {error}\n\n{error_traceback}')


def huggin_face_api(prompt: str, negative_prompt: str = "") -> list:
    """
    Calls the Hugging Face API to generate text based on a given prompt.
    
    Args:
        prompt (str): The prompt to generate text from.
    
    Returns:
        bytes: The generated text as bytes.
    """
    if not hasattr(cfg, 'huggin_face_api'):
        return []

    if hasattr(cfg, 'huggin_face_models_urls') and cfg.huggin_face_models_urls:
        API_URL = cfg.huggin_face_models_urls
    else:
        if os.path.exists('huggin_face_models_urls.list'):
            with open('huggin_face_models_urls.list', 'r') as f:
                API_URL = f.read().splitlines()
            API_URL = [x.strip() for x in API_URL if x.strip() and not x.strip().startswith('#')]
        else:
            API_URL = [
            # 'playgroundai/playground-v2.5-1024px-aesthetic',
            "https://api-inference.huggingface.co/models/ehristoforu/dalle-3-xl-v2",
            # 'AP123/SDXL-Lightning',
            # "multimodalart/stable-cascade",
            "https://api-inference.huggingface.co/models/digiplay/Juggernaut_final",
            "https://api-inference.huggingface.co/models/RunDiffusion/Juggernaut-X-v10",
            "https://api-inference.huggingface.co/models/dataautogpt3/TempestV0.1",
            "https://api-inference.huggingface.co/models/UnfilteredAI/NSFW-gen-v2",

            # new test
            "https://api-inference.huggingface.co/models/Corcelio/mobius",
            "https://api-inference.huggingface.co/models/sd-community/sdxl-flash",
            "https://api-inference.huggingface.co/models/fluently/Fluently-XL-v4",
            "https://api-inference.huggingface.co/models/Corcelio/openvision",

            # "multimodalart/cosxl",
            # 'PixArt-alpha/PixArt-Sigma',
            # 'ByteDance/Hyper-SDXL-1Step-T2I',
        ]

    payload = json.dumps({"inputs": prompt, "negative_prompt": negative_prompt,})

    def request_img(prompt, url, p):
        if 'PixArt-Sigma' in url:
            try:
                return PixArtSigma(prompt, url, negative_prompt=negative_prompt)
            except:
                return []
        if 'Hyper-SDXL' in url:
            try:
                return Hyper_SDXL(prompt, url, negative_prompt=negative_prompt)
            except:
                return []
        if 'cosxl' in url:
            try:
                return cosxl(prompt, url, negative_prompt=negative_prompt)
            except:
                return []
        if 'stable-cascade' in url:
            try:
                return stable_cascade(prompt, url, negative_prompt=negative_prompt)
            except:
                return []
        if 'playgroundai/playground-v2.5-1024px-aesthetic' in url:
            try:
                return playground25(prompt, url, negative_prompt=negative_prompt)
            except Exception as error:
                my_log.log_huggin_face_api(f'my_genimg:playgroundai/playground-v2.5-1024px-aesthetic: {error}\nPrompt: {prompt}\nURL: {url}')
                return []
        if 'AP123/SDXL-Lightning' in url:
            try:
                return SDXL_Lightning(prompt, url, negative_prompt=negative_prompt)
            except Exception as error:
                my_log.log_huggin_face_api(f'my_genimg:AP123/SDXL-Lightning: {error}\nPrompt: {prompt}\nURL: {url}')
                return []
        if 'Stable-Diffusion-3' in url:
            try:
                return stable_diffusion_3_medium(prompt, url, negative_prompt=negative_prompt)
            except Exception as error:
                my_log.log_huggin_face_api(f'my_genimg:stable_diffusion_3_medium: {error}\nPrompt: {prompt}\nURL: {url}')
                return []
        if 'gokaygokay/Kolors' in url:
            try:
                return Kolors(prompt, url, negative_prompt=negative_prompt)
            except Exception as error:
                my_log.log_huggin_face_api(f'my_genimg:Kolors: {error}\nPrompt: {prompt}\nURL: {url}')
                return []
        if 'multimodalart/AuraFlow' in url:
            try:
                return AuraFlow(prompt, url, negative_prompt=negative_prompt)
            except Exception as error:
                my_log.log_huggin_face_api(f'my_genimg:AuraFlow: {error}\nPrompt: {prompt}\nURL: {url}')
                return []
        if 'FLUX.1-schnell' in url or 'FLUX.1-schnell' in url:
            try:
                return FLUX1(prompt, url, negative_prompt=negative_prompt)
            except Exception as error:
                my_log.log_huggin_face_api(f'my_genimg:FLUX1: {error}\nPrompt: {prompt}\nURL: {url}')
                return []

        n = 1
        result = []
        while n > 0:
            n -= 1

            if hasattr(cfg, 'bing_proxy'):
                proxy = {'http': random.choice(cfg.bing_proxy), 'https': random.choice(cfg.bing_proxy)}
            else:
                proxy = None
            api_key = random.choice(ALL_KEYS)
            headers = {"Authorization": f"Bearer {api_key}"}

            mult_words = [
                '2D', '3D', 'CGI', 'VFX', 'abstract', 'animate', 'animated', 'animatic',
                'animation', 'animation_studio', 'animator', 'anime', 'art', 'asset', 'assets', 'background',
                'blurry', 'bright colors', 'cartoon', 'cartoonish', 'cel', 'celanimation', 'cels', 'character',
                'character_design', 'characters', 'chibi', 'childish', 'claymation', 'comic', 'compositing', 'concept_art',
                'concept_design', 'design', 'digital', 'doujinshi', 'draw', 'drawing', 'dreamlike', 'ecchi',
                'editing', 'effects', 'fanart', 'fantasy', 'film', 'filmmaking', 'frame', 'frames',
                'genre', 'graphicnovel', 'graphics', 'hentai', 'illustrate', 'illustration', 'inbetween', 'kawaii',
                'keyframe', 'lighting', 'lineart', 'loli', 'loop', 'low-contrast', 'low-resolution', 'manga',
                'mecha', 'mocap', 'model', 'modeling', 'models', 'modern', 'motion', 'motion_capture',
                'movie', 'narrative', 'paint', 'painting', 'palette', 'pipeline', 'pixelated', 'post-production',
                'pre-production', 'production', 'program', 'puppet', 'puppets', 'render', 'rendering', 'rigging',
                'rotoscoping', 'scene', 'scenes', 'script', 'scripting', 'sequence', 'sequences', 'shading',
                'short', 'shota', 'simple', 'simplistic', 'sketch', 'software', 'stop_motion', 'stopmotion',
                'story', 'storyboard', 'storyboards', 'style', 'sunny', 'surreal', 'technique', 'texturing',
                'timeline', 'tool', 'tween', 'urban', 'vibrant', 'vibrant colors', 'visual', 'visual_development',
                ]

            try:
                if (any(word in negative_prompt for word in mult_words)
                    and any(word in url for word in ['m3lt', 'midsommarcartoon', 'FLUX.1-dev-LoRA-One-Click-Creative-Template', 'flux-ghibsky-illustration'])):
                    return []

                if (any(word in prompt for word in mult_words)
                    and any(word in url for word in ['flux_film_foto', 'Juggernaut_final', 'NSFW-gen-v2'])):
                    return []

                response = requests.post(url, headers=headers, json=p, timeout=120, proxies=proxy)
            except Exception as error:
                my_log.log_huggin_face_api(f'my_genimg:huggin_face_api: {error}\nPrompt: {prompt}\nAPI key: {api_key}\nProxy: {proxy}\nURL: {url}')
                continue

            if '"error":"Authorization header is correct, but the token seems invalid' in response.text:
                remove_huggin_face_key(api_key)
                api_key = random.choice(ALL_KEYS)
                continue
            resp_text = str(response.content)[:300]
            if 'read timeout=' in resp_text or "SOCKSHTTPSConnectionPool(host='api-inference.huggingface.co', port=443): Max retries exceeded with url" in resp_text: # и так долго ждали
                return []
            if response.content and '{"error"' not in resp_text and len(response.content) > 10000:
                # resize small images, upscale
                upscaled = upscale(response.content)
                result.append(upscaled)
                WHO_AUTOR[hash(upscaled)] = url.split('/')[-1]
                return result

            if 'is currently loading","estimated_time":' in str(resp_text) or \
                '"error":"Internal Server Error"' in str(resp_text) or \
                '"CUDA out of memory' in str(resp_text) or \
                '"error":"Service Unavailable"' in str(resp_text):
                if DEBUG:
                    my_log.log_huggin_face_api(f'my_genimg:huggin_face_api: {resp_text} | {proxy} | {url}')
            else: # unknown error
                my_log.log_huggin_face_api(f'my_genimg:huggin_face_api: {resp_text} | {proxy} | {url}')
            time.sleep(10)

        return result

    pool = ThreadPool(processes=len(API_URL))
    async_results = []
    for x in API_URL:
        async_results.append(pool.apply_async(request_img, (prompt, x, payload,)))

    result = []
    for x in async_results:
        result += x.get()

    result = list(set(result))

    return result


def huggin_face_api_one_image(
    url: str,
    positive_prompt: str,
    negative_prompt: str,
    retries: int = 5,
    delay: int = 10,
    timeout: int = 120,
    ) -> bytes:
    """
    Попытка сгенерировать изображения через Hugging Face API с заданными положительным и отрицательным промптами.
    Пытается несколько раз в случае неудачи, используя случайные ключи API.

    Args:
        url (str): URL API Hugging Face.
        positive_prompt (str): Положительный промпт.
        negative_prompt (str): Отрицательный промпт.
        retries (int): Количество попыток.
        delay (int): Задержка между попытками (в секундах).

    Returns:
        bytes: Изображение в байтах.
    """
    if not ALL_KEYS:
        # raise Exception("Нет доступных ключей для Hugging Face API")
        return []

    payload = json.dumps({
        "inputs": positive_prompt, 
        "negative_prompt": negative_prompt,
    })

    start_time = time.time()
    for attempt in range(retries):
        api_key = random.choice(ALL_KEYS)  # Выбираем случайный ключ
        headers = {"Authorization": f"Bearer {api_key}"}

        try:
            response = requests.post(url, headers=headers, data=payload, timeout=timeout)

            if response.status_code == 200 and len(response.content) > 100:
                # my_log.log_huggin_face_api(f"Успешно сгенерировано изображение на попытке {attempt + 1}")
                return response.content


            # Логируем ошибку статуса
            # my_log.log_huggin_face_api(f"huggin_face_api_one_image: Попытка {attempt + 1} не удалась: статус {response.status_code}, ответ: {response.text[:300]}")

        except Exception as e:
            error_traceback = traceback.format_exc()
            my_log.log_huggin_face_api(f"huggin_face_api_one_image: {str(e)}\nТрассировка: {error_traceback}")

        end_time = time.time()
        if end_time - start_time > timeout:
            return b''

        time.sleep(delay)  # Задержка перед новой попыткой

    # raise Exception("Не удалось получить изображение после нескольких попыток")
    return b''


def PixArtSigma(prompt: str, url: str = 'PixArt-alpha/PixArt-Sigma', negative_prompt: str = "") -> bytes:
    """
    url = "PixArt-alpha/PixArt-Sigma" only?
    """
    try:
        client = gradio_client.Client(url)
    except Exception as error:
        my_log.log_huggin_face_api(f'my_genimg:PixArt-alpha/PixArt-Sigma: {error}\n\nPrompt: {prompt}\nURL: {url}')
        return []
    result = None
    try:
        result = client.predict(
                prompt=prompt,
                negative_prompt=negative_prompt,
                style="(No style)",
                use_negative_prompt=bool(negative_prompt),
                num_imgs=1,
                seed=0,
                width=1024,
                height=1024,
                schedule="DPM-Solver",
                dpms_guidance_scale=4.5,
                sas_guidance_scale=3,
                dpms_inference_steps=14,
                sas_inference_steps=25,
                randomize_seed=True,
                api_name="/run"
        )
    except Exception as error:
        if 'No GPU is currently available for you after 60s' not in str(error) and 'You have exceeded your GPU quota' not in str(error):
            my_log.log_huggin_face_api(f'my_genimg:PixArt-alpha/PixArt-Sigma: {error}\n\nPrompt: {prompt}\nURL: {url}')
        # else:
        #     my_log.log_huggin_face_api(f'my_genimg:PixArt-alpha/PixArt-Sigma: {error}\n\nPrompt: {prompt}\nURL: {url}')
        return []

    fname = result[0][0]['image']
    base_path = os.path.dirname(fname)
    if fname:
        try:
            data = None
            with open(fname, 'rb') as f:
                data = f.read()
            try:
                utils.remove_file(fname)
                os.rmdir(base_path)
            except Exception as error:
                my_log.log_huggin_face_api(f'my_genimg:PixArt-alpha/PixArt-Sigma: {error}\n\nPrompt: {prompt}\nURL: {url}')
            if data:
                WHO_AUTOR[hash(data)] = url.split('/')[-1]
                return [data,]
        except Exception as error:
            my_log.log_huggin_face_api(f'my_genimg:PixArt-alpha/PixArt-Sigma: {error}\n\nPrompt: {prompt}\nURL: {url}')
    return []


def size_of_image(data: bytes):
    """
    Calculate the size of an image from the given byte data.

    Args:
        data (bytes): The byte data of the image.

    Returns:
        tuple: A tuple containing the width and height of the image.
    """
    img = PIL.Image.open(io.BytesIO(data))
    return img.size


def SDXL_Lightning(prompt: str, url: str = 'AP123/SDXL-Lightning', negative_prompt: str = "") -> bytes:
    """
    url = "AP123/SDXL-Lightning" only?
    """
    try:
        client = gradio_client.Client("AP123/SDXL-Lightning")
    except Exception as error:
        my_log.log_huggin_face_api(f'my_genimg:SDXL_Lightning: {error}\n\nPrompt: {prompt}\nURL: {url}')
        return []
    result = None
    try:
        result = client.predict(
            prompt,
            "8-Step",	# Literal['1-Step', '2-Step', '4-Step', '8-Step']  in 'Select inference steps' Dropdown component
            api_name="/generate_image"
        )
    except Exception as error:
        if 'No GPU is currently available for you after 60s' not in str(error) and 'You have exceeded your GPU quota' not in str(error):
            my_log.log_huggin_face_api(f'my_genimg:SDXL_Lightning: {error}\n\nPrompt: {prompt}\nURL: {url}')
        return []

    fname = result
    base_path = os.path.dirname(fname)
    if fname:
        try:
            data = None
            with open(fname, 'rb') as f:
                data = f.read()
            try:
                utils.remove_file(fname)
                os.rmdir(base_path)
            except Exception as error:
                my_log.log_huggin_face_api(f'my_genimg:SDXL_Lightning: {error}\n\nPrompt: {prompt}\nURL: {url}')
            imgsize = size_of_image(data)
            if data and imgsize == (1024, 1024):
                WHO_AUTOR[hash(data)] = url.split('/')[-1]
                return [data,]
        except Exception as error:
            my_log.log_huggin_face_api(f'my_genimg:SDXL_Lightning: {error}\n\nPrompt: {prompt}\nURL: {url}')
    return []


def playground25(prompt: str, url: str = "https://playgroundai-playground-v2-5.hf.space/", negative_prompt: str = "") -> bytes:
    """
    url = "playgroundai/playground-v2.5-1024px-aesthetic" only?
    """
    try:
        client = gradio_client.Client("https://playgroundai-playground-v2-5.hf.space/")
    except Exception as error:
        my_log.log_huggin_face_api(f'my_genimg:playground25: {error}\n\nPrompt: {prompt}\nURL: {url}')
        return []
    result = None
    try:
        result = client.predict(
            prompt,	# str  in 'Prompt' Textbox component
            negative_prompt,	# str  in 'Negative prompt' Textbox component
            bool(negative_prompt),	# bool  in 'Use negative prompt' Checkbox component
            random.randint(0, 2147483647),	    # float (numeric value between 0 and 2147483647) in 'Seed' Slider component
            1024,	# float (numeric value between 256 and 1536) in 'Width' Slider component
            1024,	# float (numeric value between 256 and 1536) in 'Height' Slider component
            3,	# float (numeric value between 0.1 and 20) in 'Guidance Scale' Slider component
            True,	# bool  in 'Randomize seed' Checkbox component
            api_name="/run"
        )
    except Exception as error:
        if 'No GPU is currently available for you after 60s' not in str(error) and 'You have exceeded your GPU quota' not in str(error):
            my_log.log_huggin_face_api(f'my_genimg:playground25: {error}\n\nPrompt: {prompt}\nURL: {url}')
        return []

    fname = result[0][0]['image']
    base_path = os.path.dirname(fname)
    if fname:
        try:
            data = None
            with open(fname, 'rb') as f:
                data = f.read()
            try:
                utils.remove_file(fname)
                os.rmdir(base_path)
            except Exception as error:
                my_log.log_huggin_face_api(f'my_genimg:playground25: {error}\n\nPrompt: {prompt}\nURL: {url}')
            if data:
                WHO_AUTOR[hash(data)] = url.split('/')[-1]
                return [data,]
        except Exception as error:
            my_log.log_huggin_face_api(f'my_genimg:playground25: {error}\n\nPrompt: {prompt}\nURL: {url}')
    return []


def stable_cascade(prompt: str, url: str = "multimodalart/stable-cascade", negative_prompt: str = "") -> bytes:
    """
    url = "multimodalart/stable-cascade" only?
    """
    try:
        client = gradio_client.Client(url)
    except Exception as error:
        my_log.log_huggin_face_api(f'my_genimg:stable_cascade: {error}\n\nPrompt: {prompt}\nURL: {url}')
        return []

    result = None
    try:
        result = client.predict(
            prompt,	# str  in 'Prompt' Textbox component
            negative_prompt,	# str  in 'Negative prompt' Textbox component
            0,	# float (numeric value between 0 and 2147483647) in 'Seed' Slider component
            1024,	# float (numeric value between 1024 and 1536) in 'Width' Slider component
            1024,	# float (numeric value between 1024 and 1536) in 'Height' Slider component
            10,	# float (numeric value between 10 and 30) in 'Prior Inference Steps' Slider component
            0,	# float (numeric value between 0 and 20) in 'Prior Guidance Scale' Slider component
            4,	# float (numeric value between 4 and 12) in 'Decoder Inference Steps' Slider component
            0,	# float (numeric value between 0 and 0) in 'Decoder Guidance Scale' Slider component
            1,	# float (numeric value between 1 and 2) in 'Number of Images' Slider component
            api_name="/run"
        )
    except Exception as error:
        if 'No GPU is currently available for you after 60s' not in str(error) and 'You have exceeded your GPU quota' not in str(error):
            my_log.log_huggin_face_api(f'my_genimg:stable_cascade: {error}\n\nPrompt: {prompt}\nURL: {url}')
        return []

    fname = result
    base_path = os.path.dirname(fname)
    if fname:
        try:
            data = None
            with open(fname, 'rb') as f:
                data = f.read()
            try:
                utils.remove_file(fname)
                os.rmdir(base_path)
            except Exception as error:
                my_log.log_huggin_face_api(f'my_genimg:stable_cascade: {error}\n\nPrompt: {prompt}\nURL: {url}')
            if data:
                WHO_AUTOR[hash(data)] = url.split('/')[-1]
                return [data,]
        except Exception as error:
            my_log.log_huggin_face_api(f'my_genimg:stable_cascade: {error}\n\nPrompt: {prompt}\nURL: {url}')
    return []


def glm(prompt: str, width: int = 1024, height: int = 1024, num: int = 1, negative_prompt: str = ""):
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
        if hasattr(cfg, 'GLM_IMAGES') and cfg.GLM_IMAGES:
            images = my_glm.txt2img(prompt, user_id='-')
            results = []
            if images:
                for image in images:
                    data = utils.download_image_as_bytes(image)
                    WHO_AUTOR[hash(data)] = 'bigmodel.cn cogView-3-plus'
                    results.append(data)
                return results

    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_huggin_face_api(f'glm: {error}\n\n{error_traceback}')

    return []


def prodia(prompt: str, width: int = 1024, height: int = 1024, num: int = 1, negative_prompt: str = ""):
    """
    Generates images based on a prompt using the PRODIA API.

    Args:
        prompt (str): The prompt for generating the images.
        width (int, optional): The width of the images. Defaults to 1024.
        height (int, optional): The height of the images. Defaults to 1024.
        num (int, optional): The number of images to generate. Defaults to 1.

    Returns:
        list: A list of generated images in bytes format.
    """
    try:
        image = my_prodia.gen_image(prompt, negative_prompt)
        results = []
        if image:
            data = image
            WHO_AUTOR[hash(data)] = 'prodia.com sdxl'
            results.append(data)
            return results

    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_huggin_face_api(f'my_genimg:prodia: {error}\n\n{error_traceback}')

    return []


def kandinski(prompt: str, width: int = 1024, height: int = 1024, num: int = 1, negative_prompt: str = ""):
    """
    Generates images based on a prompt using the KANDINSKI_API.

    Args:
        prompt (str): The prompt for generating the images.
        width (int, optional): The width of the images. Defaults to 1024.
        height (int, optional): The height of the images. Defaults to 1024.
        num (int, optional): The number of images to generate. Defaults to 1.

    Returns:
        list: A list of generated images in bytes format.
    """
    try:
        if not hasattr(cfg, 'KANDINSKI_API') or not cfg.KANDINSKI_API:
            return []
        keys = cfg.KANDINSKI_API[:]
        key = random.choice(keys)
        AUTH_HEADERS = {
            'X-Key': f'Key {key[0]}',
            'X-Secret': f'Secret {key[1]}',
        }
        params = {
            "type": "GENERATE",
            "numImages": num,
            "width": width,
            "height": height,
            "generateParams": {
            "query": f"{prompt}"
		    }
	    }
        def get_model():
            response = requests.get('https://api-key.fusionbrain.ai/key/api/v1/models', headers=AUTH_HEADERS)
            data = response.json()
            return data[0]['id']

        data = {
            'model_id': (None, get_model()),
            'params': (None, json.dumps(params), 'application/json')
        }
        response = requests.post('https://api-key.fusionbrain.ai/key/api/v1/text2image/run', headers=AUTH_HEADERS, files=data, timeout=120)
        data = response.json()
        try:
            uuid = data['uuid']
        except KeyError:
            return []

        def check_generation(request_id, attempts=10, delay=10):
            while attempts > 0:
                response = requests.get('https://api-key.fusionbrain.ai/key/api/v1/text2image/status/' + request_id, headers=AUTH_HEADERS)
                data = response.json()
                if  data['censored']:
                    return []
                if data['status'] == 'DONE':
                    return data['images']
                attempts -= 1
                time.sleep(delay)

        images = check_generation(uuid)
        if images:
            results = []
            for image in images:
                data = base64.b64decode(image)
                WHO_AUTOR[hash(data)] = 'fusionbrain.ai'
                results.append(data)
            return results
        else:
            return []

    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_huggin_face_api(f'my_genimg:kandinski: {error}\n\n{error_traceback}')

    return []


def get_ynd_iam_token(oauth_tokens):
  """
  Get Yandex IAM token using OAuth tokens.

  Parameters:
    oauth_tokens (list): List of OAuth tokens.

  Returns:
    str: Yandex IAM token if successful, None otherwise.
  """
  url = "https://iam.api.cloud.yandex.net/iam/v1/tokens"
  headers = {"Content-Type": "application/json"}
  for oauth_token in oauth_tokens:
    data = {"yandexPassportOauthToken": oauth_token}

    response = requests.post(url, headers=headers, json=data, timeout=10)

    if response.status_code == 200:
        return response.json()['iamToken']
    else:
        my_log.log2(f'my_genimg:get_ynd_iam_token: {response.status_code} {oauth_token}')
    return None


def yandex_cloud_generate_image_async(iam_token: str, prompt: str, seed=None, timeout: int = 60):
    """
    A function to asynchronously generate an image using the Yandex Cloud API.

    Parameters:
    - iam_token (str): The IAM token for authentication.
    - prompt (str): The text prompt for image generation.
    - seed (int, optional): The seed for random generation. Defaults to None.
    - timeout (int, optional): The timeout for the API request. Defaults to 120.

    Returns:
    - list: list of images as bytes.
    """
    try:
        url = "https://llm.api.cloud.yandex.net:443/foundationModels/v1/imageGenerationAsync"
        headers = {"Authorization": f"Bearer {iam_token}"}
        data = {
            "model_uri": "art://b1gcvk4tetlvtrjkktek/yandex-art/latest",
            "messages": [{"text": prompt, "weight": 1}],
            "generation_options": {"mime_type": "image/jpeg"}
        }

        if seed:
            data["generation_options"]["seed"] = seed
        else:
            data["generation_options"]["seed"] = random.randint(0, 2**64 - 1)

        response = requests.post(url, headers=headers, json=data, timeout=20)

        if response.status_code == 200:
            url = f" https://llm.api.cloud.yandex.net:443/operations/{response.json()['id']}"
            time.sleep(30)
            while timeout > 0:
                try:
                    response = requests.get(url, headers=headers, timeout=20)
                    if response.status_code == 200:
                        if hasattr(response, 'text'):
                            response = response.json()
                            if response['done']:
                                return response['response']['image']
                except Exception as error2:
                    error_traceback2 = traceback.format_exc()
                    if 'Read timed out.' in str(error2) or 'Read timed out.' in str(error_traceback2):
                        pass
                    else:
                        my_log.log_huggin_face_api(f'my_genimg:yandex_cloud_generate_image_async: {error2}\n\n{error_traceback2}')
                time.sleep(20)
                timeout -= 20
        else:
            print(f"Ошибка: {response.status_code}")
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_huggin_face_api(f'my_genimg:yandex_cloud_generate_image_async: {error}\n\n{error_traceback}')
    return []


def yandex_cloud(prompt: str = 'An australian cat', amount: int = 1):
    """
    Function to generate images using Yandex Cloud API. 
    Takes a prompt string and an amount of images to generate. 
    Returns a list of generated images as bytes.
    """
    try:
        if not hasattr(cfg, 'YND_OAUTH') or not cfg.YND_OAUTH:
            return []
        iam_tokens = cfg.YND_OAUTH[:]
        random.shuffle(iam_tokens)
        iam_token = get_ynd_iam_token(iam_tokens)
        results = []
        prompt = 'High detail, high quality. ' + prompt
        for _ in range(amount):
            result = yandex_cloud_generate_image_async(iam_token, prompt)
            if result:
                data = base64.b64decode(result)
                WHO_AUTOR[hash(data)] = 'shedevrum.ai (yandex cloud)'
                results.append(data)
        return results
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_huggin_face_api(f'my_genimg:yandex_cloud: {error}\n\nPrompt: {prompt}\nAmount: {amount}\n{error_traceback}')
        return []


def cosxl(prompt: str, url: str = "multimodalart/cosxl", negative_prompt: str = "") -> list:
    """
    url = "multimodalart/cosxl" only?
    """
    try:
        client = gradio_client.Client(url)
    except Exception as error:
        my_log.log_huggin_face_api(f'my_genimg:cosxl: {error}\n\nPrompt: {prompt}\nURL: {url}')
        return []

    result = None
    try:
        result = client.predict(prompt, "", 7, api_name="/run_normal")
    except Exception as error:
        if 'No GPU is currently available for you after 60s' not in str(error) and 'You have exceeded your GPU quota' not in str(error):
            my_log.log_huggin_face_api(f'my_genimg:cosxl: {error}\n\nPrompt: {prompt}\nURL: {url}')
        return []

    fname = result
    base_path = os.path.dirname(fname)
    if fname:
        try:
            data = None
            with open(fname, 'rb') as f:
                data = f.read()
            try:
                utils.remove_file(fname)
                os.rmdir(base_path)
            except Exception as error:
                my_log.log_huggin_face_api(f'my_genimg:cosxl: {error}\n\nPrompt: {prompt}\nURL: {url}')
            if data:
                WHO_AUTOR[hash(data)] = url.split('/')[-1]
                return [data,]
        except Exception as error:
            my_log.log_huggin_face_api(f'my_genimg:cosxl: {error}\n\nPrompt: {prompt}\nURL: {url}')
    return []


def Hyper_SDXL(prompt: str, url: str = "ByteDance/Hyper-SDXL-1Step-T2I", number: int = 1, negative_prompt: str = "") -> list:
    """
    url = "ByteDance/Hyper-SDXL-1Step-T2I" only?
    """
    try:
        client = gradio_client.Client(url)
    except Exception as error:
        my_log.log_huggin_face_api(f'my_genimg:Hyper_SDXL: {error}\n\nPrompt: {prompt}\nURL: {url}')
        return []

    result = None
    try:
        result = result = client.predict(
            num_images=number,
            height=1024,
            width=1024,
            prompt=prompt,
            seed=0,
            api_name="/process_image"
        )
    except Exception as error:
        if 'No GPU is currently available for you after 60s' not in str(error) and 'You have exceeded your GPU quota' not in str(error):
            my_log.log_huggin_face_api(f'my_genimg:Hyper_SDXL: {error}\n\nPrompt: {prompt}\nURL: {url}')
        return []

    images = []
    for fname in result:
        try:
            fname = fname['image']
        except:
            continue
        base_path = os.path.dirname(fname)
        if fname:
            try:
                data = None
                with open(fname, 'rb') as f:
                    data = f.read()
                try:
                    utils.remove_file(fname)
                    os.rmdir(base_path)
                except Exception as error:
                    my_log.log_huggin_face_api(f'my_genimg:Hyper_SDXL: {error}\n\nPrompt: {prompt}\nURL: {url}')
                if data:
                    WHO_AUTOR[hash(data)] = url.split('/')[-1]
                    images.append(data)
            except Exception as error:
                my_log.log_huggin_face_api(f'my_genimg:Hyper_SDXL: {error}\n\nPrompt: {prompt}\nURL: {url}')
    return images


def stable_diffusion_3_medium(prompt: str, url: str = "markmagic/Stable-Diffusion-3-FREE", number: int = 1, negative_prompt: str = "") -> list:
    """
    url = "markmagic/Stable-Diffusion-3-FREE" only?
    """
    try:
        client = gradio_client.Client(url)
    except Exception as error:
        my_log.log_huggin_face_api(f'my_genimg:stable_diffusion_3_medium: {error}\n\nPrompt: {prompt}\nURL: {url}')
        return []

    result = None
    try:
        result = result = client.predict(
            prompt=prompt,
            negative_prompt=negative_prompt,
            use_negative_prompt=bool(negative_prompt),
            seed=0,
            width=1024,
            height=1024,
            guidance_scale=7,
            randomize_seed=True,
            num_inference_steps=30,
            NUM_IMAGES_PER_PROMPT=number,
            api_name="/run"
        )
    except Exception as error:
        if 'No GPU is currently available for you after 60s' not in str(error) and 'You have exceeded your GPU quota' not in str(error):
            my_log.log_huggin_face_api(f'my_genimg:stable_diffusion_3_medium: {error}\n\nPrompt: {prompt}\nURL: {url}')
        return []

    images = []
    for fname in result:
        try:
            fname = fname['image']
        except:
            continue
        base_path = os.path.dirname(fname)
        if fname:
            try:
                data = None
                with open(fname, 'rb') as f:
                    data = f.read()
                try:
                    utils.remove_file(fname)
                    os.rmdir(base_path)
                except Exception as error:
                    my_log.log_huggin_face_api(f'my_genimg:stable_diffusion_3_medium: {error}\n\nPrompt: {prompt}\nURL: {url}')
                if data:
                    WHO_AUTOR[hash(data)] = url.split('/')[-1]
                    images.append(data)
            except Exception as error:
                my_log.log_huggin_face_api(f'my_genimg:stable_diffusion_3_medium: {error}\n\nPrompt: {prompt}\nURL: {url}')
    return images


def Kolors(prompt: str, url: str = "gokaygokay/Kolors", number: int = 1, negative_prompt: str = "") -> list:
    """
    url = "gokaygokay/Kolors" only?
    """
    try:
        client = gradio_client.Client(url)
    except Exception as error:
        my_log.log_huggin_face_api(f'my_genimg:Kolors: {error}\n\nPrompt: {prompt}\nURL: {url}')
        return []

    result = None
    try:
        result = client.predict(
		prompt=prompt,
		negative_prompt=negative_prompt,
        # use_negative_prompt=bool(negative_prompt),
		height=1024,
		width=1024,
		num_inference_steps=20,
		guidance_scale=5,
		num_images_per_prompt=number,
		use_random_seed=True,
		seed=0,
		api_name="/predict"
        )
    except Exception as error:
        if 'No GPU is currently available for you after 60s' not in str(error) and 'You have exceeded your GPU quota' not in str(error):
            my_log.log_huggin_face_api(f'my_genimg:Kolors: {error}\n\nPrompt: {prompt}\nURL: {url}')
        return []

    images = []
    for fname in result[0]:
        try:
            fname = fname['image']
        except:
            continue
        base_path = os.path.dirname(fname)
        if fname:
            try:
                data = None
                with open(fname, 'rb') as f:
                    data = f.read()
                try:
                    utils.remove_file(fname)
                    os.rmdir(base_path)
                except Exception as error:
                    my_log.log_huggin_face_api(f'my_genimg:Kolors: {error}\n\nPrompt: {prompt}\nURL: {url}')
                if data:
                    WHO_AUTOR[hash(data)] = url.split('/')[-1]
                    images.append(data)
            except Exception as error:
                my_log.log_huggin_face_api(f'my_genimg:Kolors: {error}\n\nPrompt: {prompt}\nURL: {url}')
    return images


def AuraFlow(prompt: str, url: str = "multimodalart/AuraFlow", number: int = 1, negative_prompt: str = "") -> list:
    """
    url = "multimodalart/AuraFlow" only?
    """
    try:
        client = gradio_client.Client(url)
    except Exception as error:
        my_log.log_huggin_face_api(f'my_genimg:AuraFlow: {error}\n\nPrompt: {prompt}\nURL: {url}')
        return []

    result = None
    try:
        result = client.predict(
            prompt=prompt,
            negative_prompt=negative_prompt,
            seed=0,
            randomize_seed=True,
            width=1024,
            height=1024,
            guidance_scale=5,
            num_inference_steps=28,
            api_name="/infer"
        )
    except Exception as error:
        if 'No GPU is currently available for you after 60s' not in str(error) and 'You have exceeded your GPU quota' not in str(error):
            my_log.log_huggin_face_api(f'my_genimg:AuraFlow: {error}\n\nPrompt: {prompt}\nURL: {url}')
        return []

    images = []
    for fname in result[0]:
        try:
            fname = fname['image']
        except:
            continue
        base_path = os.path.dirname(fname)
        if fname:
            try:
                data = None
                with open(fname, 'rb') as f:
                    data = f.read()
                try:
                    utils.remove_file(fname)
                    os.rmdir(base_path)
                except Exception as error:
                    my_log.log_huggin_face_api(f'my_genimg:AuraFlow: {error}\n\nPrompt: {prompt}\nURL: {url}')
                if data:
                    WHO_AUTOR[hash(data)] = url.split('/')[-1]
                    images.append(data)
            except Exception as error:
                my_log.log_huggin_face_api(f'my_genimg:AuraFlow: {error}\n\nPrompt: {prompt}\nURL: {url}')
    return images


def FLUX1(prompt: str, url: str = "black-forest-labs/FLUX.1-schnell", number: int = 1, negative_prompt: str = "") -> list:
    """
    url = "black-forest-labs/FLUX.1-schnell" or "ChristianHappy/FLUX.1-schnell" only?
    """
    try:
        client = gradio_client.Client(url)
    except Exception as error:
        my_log.log_huggin_face_api(f'my_genimg:FLUX1: {error}\n\nPrompt: {prompt}\nURL: {url}')
        return []

    result = None
    try:
        result = client.predict(
            prompt=prompt,
            # negative_prompt=negative_prompt,
            seed=0,
            randomize_seed=True,
            width=1024,
            height=1024,
            num_inference_steps=4,
            api_name="/infer"
        )
    except Exception as error:
        if 'No GPU is currently available for you after 60s' not in str(error) and 'You have exceeded your GPU quota' not in str(error):
            my_log.log_huggin_face_api(f'my_genimg:FLUX1: {error}\n\nPrompt: {prompt}\nURL: {url}')
        return []

    images = []
    try:
        fname = result[0]
        base_path = os.path.dirname(fname)
    except:
        fname = ''
    if fname:
        try:
            data = None
            with open(fname, 'rb') as f:
                data = f.read()
            try:
                utils.remove_file(fname)
                os.rmdir(base_path)
            except Exception as error:
                my_log.log_huggin_face_api(f'my_genimg:FLUX1: {error}\n\nPrompt: {prompt}\nURL: {url}')
            if data:
                WHO_AUTOR[hash(data)] = url.split('/')[-1]
                images.append(data)
        except Exception as error:
            my_log.log_huggin_face_api(f'my_genimg:FLUX1: {error}\n\nPrompt: {prompt}\nURL: {url}')
    return images


def runware(prompt: str, number: int = 2, negative_prompt: str = "", cache: bool = False, big: bool = False) -> list:
    """
        runware.ai
    """
    try:
        h = 1024
        w = 1024
        if big:
            h = 2048
            w = 2048
        images = my_runware_ai.generate_images(prompt,
                                               number_results=number,
                                               negative_prompt=negative_prompt,
                                               use_cache=cache,
                                               height=h,
                                               width=w,
                                               )

        results = []
        images = [x for x in utils.download_image_as_bytes(images)]
        for data in images:
            if data:
                WHO_AUTOR[hash(data)] = 'runware.ai'
                results.append(data)
        return results
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_huggin_face_api(f'my_genimg:runware: {error}\n\nPrompt: {prompt}\n\n{error_traceback}')
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
    try:
        conversation_history = conversation_history.replace('𝐔𝐒𝐄𝐑:', 'user:')
        conversation_history = conversation_history.replace('𝐁𝐎𝐓:', 'bot:')

        prompt = prompt.strip()
        if prompt.startswith('!!!'):
            prompt = prompt[3:]
            dont_translate = True
        else:
            dont_translate = False

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
  reprompt = {{"was_translated": str, "lang_from": str, "reprompt": str, "negative_reprompt": str, "moderation_sexual": bool}}
Return a `reprompt`
'''

        negative = ''
        reprompt = ''
        r = ''

        if not r:
            r = my_gemini.get_reprompt_for_image(query, chat_id)
        if r:
            reprompt, negative, moderation_sex = r
            if moderation_sex:
                return 'MODERATION', None
        if not reprompt:
            r = my_groq.get_reprompt_for_image(query, chat_id)
            if r:
                reprompt, negative, moderation_sex = r
                if moderation_sex:
                    return 'MODERATION', None

    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_huggin_face_api(f'my_genimg:get_reprompt: {error}\n\nPrompt: {prompt}\n\n{error_traceback}')
    if dont_translate:
        my_log.log_reprompts(f'get_reprompt:\n\n{prompt}\n\n{prompt}\n\nNegative: {negative}')
    else:
        my_log.log_reprompts(f'get_reprompt:\n\n{prompt}\n\n{reprompt}\n\nNegative: {negative}')

    if dont_translate:
        return prompt, negative

    return reprompt, negative


def gen_images_bing_only(prompt: str, user_id: str = '', conversation_history: str ='') -> list:
    if prompt.strip() == '':
        return []

    reprompt, _ = get_reprompt(prompt, conversation_history)
    if reprompt == 'MODERATION':
        return []

    if reprompt:
        result = bing(reprompt, user_id=user_id)
        return result
    return []


def gen_images(prompt: str, moderation_flag: bool = False,
               user_id: str = '',
               conversation_history: str = '',
               use_bing: bool = True) -> list:
    """рисует одновременно всеми доступными способами"""

    if not user_id:
        user_id = 'test'

    if user_id in LOCKS:
        lock = LOCKS[user_id]
    else:
        lock = threading.Lock()
        LOCKS[user_id] = lock

    with lock:
        if prompt.strip() == '':
            return []

        negative = ''

        reprompt = ''
        if use_bing:
            reprompt, negative = get_reprompt(prompt, conversation_history, user_id)
            if reprompt == 'MODERATION':
                return []

        if reprompt:
            prompt = reprompt
        else:
            return []

        pool = ThreadPool(processes=9)

        async_result1 = pool.apply_async(bing, (prompt, moderation_flag, user_id))

        async_result2 = pool.apply_async(kandinski, (prompt, 1024, 1024, 1, negative))
        async_result3 = pool.apply_async(kandinski, (prompt, 1024, 1024, 1, negative))

        async_result4 = pool.apply_async(huggin_face_api, (prompt, negative))

        async_result5 = pool.apply_async(yandex_cloud, (prompt,))
        async_result6 = pool.apply_async(yandex_cloud, (prompt,))

        async_result7 = pool.apply_async(runware, (prompt, 2, negative))

        async_result8 = pool.apply_async(prodia, (prompt, negative))

        async_result9 = pool.apply_async(glm, (prompt, negative))

        result = (async_result1.get() or []) + \
                 (async_result2.get() or []) + \
                 (async_result3.get() or []) + \
                 (async_result4.get() or []) + \
                 (async_result5.get() or []) + \
                 (async_result6.get() or []) + \
                 (async_result7.get() or []) + \
                 (async_result8.get() or []) + \
                 (async_result9.get() or [])


        # пытаемся почистить /tmp от временных файлов которые создает stable-cascade?
        # может удалить то что рисуют параллельные запросы и второй бот?
        try:
            for f in glob.glob('/tmp/*'):
                if len(f) == 45:
                    try:
                        os.rmdir(f)
                    except Exception as unknown:
                        if 'Directory not empty' not in str(unknown) and "No such file or directory: '/tmp/gradio'" not in str(unknown):
                            my_log.log2(f'my_genimg:rmdir:gen_images: {unknown}\n\n{f}')
            shutil.rmtree('/tmp/gradio')
        except Exception as unknown:
            error_traceback = traceback.format_exc()
            if 'Directory not empty' not in str(unknown) and "No such file or directory: '/tmp/gradio'" not in str(unknown):
                my_log.log2(f'my_genimg:rmdir:gen_images: {unknown}\n\n{error_traceback}')

        return result


def test_hkey(key: str):
    '''test huggingface key'''
    API_URL = [
        "https://api-inference.huggingface.co/models/ehristoforu/dalle-3-xl-v2",
        "https://api-inference.huggingface.co/models/digiplay/Juggernaut_final",
        "https://api-inference.huggingface.co/models/RunDiffusion/Juggernaut-X-v10",
        "https://api-inference.huggingface.co/models/dataautogpt3/TempestV0.1",
        "https://api-inference.huggingface.co/models/UnfilteredAI/NSFW-gen-v2",
    ]

    payload = json.dumps({"inputs": 'golden apple', "negative_prompt": 'big',})

    n = 1
    while n > 0:
        n -= 1

        if hasattr(cfg, 'bing_proxy'):
            proxy = {'http': random.choice(cfg.bing_proxy), 'https': random.choice(cfg.bing_proxy)}
        else:
            proxy = None
        api_key = key
        headers = {"Authorization": f"Bearer {api_key}"}

        try:
            response = requests.post(API_URL[0], headers=headers, json=payload, timeout=10, proxies=proxy)
        except Exception as error:
            # print(error)
            my_log.log_keys(f'hf key test error: {api_key}\n\n{str(error)}')
            continue

        try:
            resp_text = response.text
        except:
            return True
        # print(resp_text)
        if 'Authorization header is correct, but the token seems invalid' in resp_text:
            my_log.log_keys(f'hf key test error: {resp_text}\n{api_key}\n\n{str(response)}')
            return False

    return True


def guess_hf_url(url: str) -> str:
    if url.startswith('http'):
        return url
    else:
        if '/' in url:
            url = 'https://api-inference.huggingface.co/models/' + url
        else:
            try:
                if os.path.exists('huggin_face_models_urls.list'):
                    with open('huggin_face_models_urls.list', 'r') as f:
                        API_URL = f.read().splitlines()
                    API_URL = [x.strip() for x in API_URL if x.strip() and not x.strip().startswith('#')]
                    for x in API_URL:
                        if url in x:
                            url = x
                            break
                    if not url.startswith('http'):
                        return ''
            except:
                return ''
    return url


def gen_one_image(prompt: str,
               user_id: str = '',
               url: str = '',
               ) -> bytes:
    """рисует указанной в урле моделькой хаггинг фейса"""

    url = guess_hf_url(url)
    if not url or not url.startswith('https://api-inference.huggingface.co/models/'):
        return None

    if not user_id:
        user_id = 'test'

    if prompt.strip() == '':
        return None

    negative = ''

    reprompt = ''

    reprompt, negative = get_reprompt(prompt, '', user_id)
    if reprompt == 'MODERATION':
        return None

    if reprompt:
        prompt = reprompt
    else:
        return None

    result = huggin_face_api_one_image(
        url,
        prompt,
        negative
        )

    return result


if __name__ == '__main__':
    load_users_keys()
    my_groq.load_users_keys()

    print(get_reprompt('Потрясающая блондинка с длинными распущенными волосами сидит на деревянной лестнице. На ней минимум одежды, ее тело полностью видно с акцентом на вульву, демонстрируя ее гладкую, безупречную кожу и естественную красоту. Освещение мягкое и естественное, подчеркивающее ее изгибы и текстуру кожи. Высокая детализация, разрешение 8K, фотореалистичная фотография, отмеченная наградами.'))

