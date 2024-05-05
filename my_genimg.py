#!/usr/bin/env python3


import base64
import glob
import io
import json
import os
import random
import shutil
import sys
import time
import traceback
from multiprocessing.pool import ThreadPool

import cv2
import gradio_client
import langdetect
import numpy as np
import PIL
import requests
from duckduckgo_search import DDGS
from sqlitedict import SqliteDict

import bing_img
import cfg
import my_gemini
import my_log
import my_trans


DEBUG = cfg.DEBUG if hasattr(cfg, 'DEBUG') else False


NFSW_CONTENT = SqliteDict('db/nfsw_content_stable_diffusion.db', autocommit=True)


# {hash of image:model name, ...}
WHO_AUTOR = {}


# запоминаем промпты для хаггинг фейса, они не должны повторятся
# {prompt:True/False, ...}
huggingface_prompts = SqliteDict('db/kandinski_prompts.db', autocommit=True)


# не давать генерировать картинки больше чем 1 за раз для 1 юзера
# {userid:lock}
LOCKS = {}


def bing(prompt: str, moderation_flag: bool = False, user_id: str = ''):
    """рисует 4 картинки с помощью далли и возвращает сколько смог нарисовать"""
    if moderation_flag:
        return []
    try:
        images = bing_img.gen_images(prompt, user_id)
        if type(images) == list:
            return images
    except Exception as error_bing_img:
        my_log.log_bing_img(f'my_genimg:bing: {error_bing_img}')
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


def translate_prompt_to_en(prompt: str) -> str:
    """
    Translates a given prompt to English if it is not already in English.

    Args:
        prompt (str): The input prompt to be translated.

    Returns:
        str: The translated prompt in English.
    """
    detected_lang = langdetect.detect(prompt)
    if detected_lang != 'en':
        prompt_translated = my_gemini.translate(prompt, to_lang='en', help='This is a prompt for image generation. Users can write it in their own language, but only English is supported.')
        if not prompt_translated:
            prompt_translated = my_trans.translate_text2(prompt, 'en')
        if prompt_translated:
            prompt = prompt_translated
    return prompt


def rewrite_prompt_for_open_dalle(prompt: str) -> str:
    """
    Generate a new prompt for OpenDalle image generation by rewriting the given prompt.
    
    Args:
        prompt (str): The original prompt for image generation.
        
    Returns:
        str: The rewritten prompt in English.
    """
    # small text detect fails :(

    force = False
    if hash(prompt) in huggingface_prompts:
        force = True
    else:
        huggingface_prompts[hash(prompt)] = True

    detected_lang = langdetect.detect(prompt)
    if detected_lang != 'en' or force:
        prompt_translated = my_gemini.ai(f'This is a prompt for image generation. Rewrite it in english, in one long sentance, make it better:\n\n{prompt}', temperature=1)
        if not prompt_translated:
            return translate_prompt_to_en(prompt)
        return translate_prompt_to_en(prompt_translated)
    else:
        return prompt


def stable_duffision_api(prompt: str):
    """
    Requests an image from the Stable Diffusion API using the provided prompt.

    Args:
        prompt (str): The prompt for generating the image.

    Returns:
        list[str]: A list containing the URL of the generated image if successful, otherwise an empty list.
    """
    try:
        if hasattr(cfg, 'STABLE_DIFFUSION_API') and cfg.STABLE_DIFFUSION_API:
            if prompt in NFSW_CONTENT:
                return []
            url = "https://stablediffusionapi.com/api/v3/text2img"

            prompt = translate_prompt_to_en(prompt)

            api_keys = cfg.STABLE_DIFFUSION_API[:]
            random.shuffle(api_keys)
            for api_key in api_keys:
                payload = json.dumps({
                    "key": api_key,
                    "prompt": prompt,
                    "negative_prompt": None,
                    "width": "1024",
                    "height": "1024",
                    "samples": "1",
                    "num_inference_steps": "20",
                    "seed": None,
                    "guidance_scale": 7.5,
                    "safety_checker": "yes",
                    "multi_lingual": "no",
                    "panorama": "no",
                    "self_attention": "no",
                    "upscale": "no",
                    "embeddings_model": None,
                    "webhook": None,
                    "track_id": None
                })
                headers = {
                'Content-Type': 'application/json'
                }
                response = requests.request("POST", url, headers=headers, data=payload, timeout=60)
                response_json = json.loads(response.text)

                # Get the fields from the JSON response
                status = response_json["status"]
                if status == "success":
                    # generation_time = response_json["generationTime"]
                    # request_id = response_json["id"]
                    image_url = response_json["output"][0]
                    # proxy_link = response_json["proxy_links"][0]
                    nsfw_content_detected = response_json["nsfw_content_detected"]
                    if nsfw_content_detected:
                        NFSW_CONTENT[prompt] = nsfw_content_detected
                        return []
                    # meta = response_json["meta"]

                    # Extract the meta fields
                    # image_height = meta["H"]
                    # image_width = meta["W"]
                    # enable_attention_slicing = meta["enable_attention_slicing"]
                    # file_prefix = meta["file_prefix"]
                    # guidance_scale = meta["guidance_scale"]
                    # instant_response = meta["instant_response"]
                    # model_name = meta["model"]
                    # num_samples = meta["n_samples"]
                    # negative_prompt = meta["negative_prompt"]
                    # output_directory = meta["outdir"]
                    # prompt = meta["prompt"]
                    # model_revision = meta["revision"]
                    # safety_checker = meta["safetychecker"]
                    # seed = meta["seed"]
                    # steps = meta["steps"]
                    # temperature = meta["temp"]
                    # vae_model = meta["vae"]
                    return [image_url,]
                else:
                    try:
                        my_log.log_stable_diffusion_api(f'{response_json}\n\nStatus: {status}\nMessage: {response_json["message"]}\nPrompt: {prompt}\nAPI key: {api_key}')
                    except:
                        my_log.log_stable_diffusion_api(f'{response_json}\n\nPrompt: {prompt}\nAPI key: {api_key}')
    except Exception as unknown:
        error_traceback = traceback.format_exc()
        my_log.log_huggin_face_api(f'my_genimg:stable_diffusion_api: {str(unknown)}\n\n{error_traceback}')
    return []


def huggin_face_api(prompt: str) -> bytes:
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
        API_URL = [
            'playgroundai/playground-v2.5-1024px-aesthetic',
            "https://api-inference.huggingface.co/models/ehristoforu/dalle-3-xl-v2",
            'AP123/SDXL-Lightning',
            "multimodalart/stable-cascade",
            "https://api-inference.huggingface.co/models/digiplay/Juggernaut_final",
            "https://api-inference.huggingface.co/models/RunDiffusion/Juggernaut-X-v10",
            "https://api-inference.huggingface.co/models/dataautogpt3/TempestV0.1",
            "https://api-inference.huggingface.co/models/UnfilteredAI/NSFW-gen-v2",
            
            # "https://api-inference.huggingface.co/models/cagliostrolab/animagine-xl-3.0",
            # "https://api-inference.huggingface.co/models/Linaqruf/animagine-xl",
            # "https://api-inference.huggingface.co/models/KBlueLeaf/Kohaku-XL-Epsilon",
            ### "multimodalart/cosxl",
        ]

    prompt_ = prompt
    prompt = rewrite_prompt_for_open_dalle(prompt)
    if prompt_ != prompt:
        my_log.log_reprompts(f'{prompt_}\n\n{prompt}')

    payload = json.dumps({"inputs": prompt})

    def request_img(prompt, url, p):
        if 'cosxl' in url:
            try:
                return cosxl(prompt, url)
            except:
                return []
        if 'stable-cascade' in url:
            try:
                return stable_cascade(prompt, url)
            except:
                return []
        if 'playgroundai/playground-v2.5-1024px-aesthetic' in url:
            try:
                return playground25(prompt, url)
            except Exception as error:
                my_log.log_huggin_face_api(f'my_genimg:playgroundai/playground-v2.5-1024px-aesthetic: {error}\nPrompt: {prompt}\nURL: {url}')
                return []
        if 'AP123/SDXL-Lightning' in url:
            try:
                return SDXL_Lightning(prompt, url)
            except Exception as error:
                my_log.log_huggin_face_api(f'my_genimg:AP123/SDXL-Lightning: {error}\nPrompt: {prompt}\nURL: {url}')
                return []

        n = 1
        result = []
        while n > 0:
            n -= 1

            if hasattr(cfg, 'bing_proxy'):
                proxy = {'http': random.choice(cfg.bing_proxy), 'https': random.choice(cfg.bing_proxy)}
            else:
                proxy = None
            api_key = random.choice(cfg.huggin_face_api)
            headers = {"Authorization": f"Bearer {api_key}"}

            try:
                response = requests.post(url, headers=headers, json=p, timeout=120, proxies=proxy)
            except Exception as error:
                my_log.log_huggin_face_api(f'my_genimg:huggin_face_api: {error}\nPrompt: {prompt}\nAPI key: {api_key}\nProxy: {proxy}\nURL: {url}')
                continue

            resp_text = str(response.content)[:300]
            # if isinstance(resp_text, str):
            #     print(resp_text[:300])
            if 'read timeout=' in resp_text or "SOCKSHTTPSConnectionPool(host='api-inference.huggingface.co', port=443): Max retries exceeded with url" in resp_text: # и так долго ждали
                return []
            if response.content and '{"error"' not in resp_text and len(response.content) > 10000:
                result.append(response.content)
                WHO_AUTOR[hash(response.content)] = url.split('/')[-1]
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


def SDXL_Lightning(prompt: str, url: str) -> bytes:
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
                os.remove(fname)
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


def playground25(prompt: str, url: str) -> bytes:
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
            "",	# str  in 'Negative prompt' Textbox component
            False,	# bool  in 'Use negative prompt' Checkbox component
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
                os.remove(fname)
                os.rmdir(base_path)
            except Exception as error:
                my_log.log_huggin_face_api(f'my_genimg:playground25: {error}\n\nPrompt: {prompt}\nURL: {url}')
            if data:
                WHO_AUTOR[hash(data)] = url.split('/')[-1]
                return [data,]
        except Exception as error:
            my_log.log_huggin_face_api(f'my_genimg:playground25: {error}\n\nPrompt: {prompt}\nURL: {url}')
    return []


def stable_cascade(prompt: str, url: str) -> bytes:
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
            "",	# str  in 'Negative prompt' Textbox component
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
                os.remove(fname)
                os.rmdir(base_path)
            except Exception as error:
                my_log.log_huggin_face_api(f'my_genimg:stable_cascade: {error}\n\nPrompt: {prompt}\nURL: {url}')
            if data:
                WHO_AUTOR[hash(data)] = url.split('/')[-1]
                return [data,]
        except Exception as error:
            my_log.log_huggin_face_api(f'my_genimg:stable_cascade: {error}\n\nPrompt: {prompt}\nURL: {url}')
    return []


def kandinski(prompt: str, width: int = 1024, height: int = 1024, num: int = 1):
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
        response = requests.post('https://api-key.fusionbrain.ai/key/api/v1/text2image/run', headers=AUTH_HEADERS, files=data)
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


def is_blurry(image_bytes: bytes, threshold: int = 100):
    """
    Check if the given image is blurry by calculating the Laplacian variance and comparing it with the given threshold.

    Parameters:
    - image_bytes: bytes, the bytes of the image to be checked for blurriness
    - threshold: int, the threshold value for the Laplacian variance (default is 100)

    Returns:
    - bool, True if the image is blurry, False otherwise
    """
    nparr = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if image is None:
        return False
    gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    laplacian_var = cv2.Laplacian(gray_image, cv2.CV_64F).var()
    return laplacian_var < threshold


def stability_ai(prompt: str = 'An australian cat', amount: int = 1):
    """
    Generate stable image using stability.ai API.

    Args:
        prompt (str): The prompt for generating the stable image.
        amount (int): The number of stable images to generate.

    Returns:
        List: A list of stable images generated.
    """
    if amount > 1:
        result = []
        for i in range(amount):
            result.append(stability_ai(prompt, 1))
        return result

    try:
        if hasattr(cfg, 'STABILITY_API') and cfg.STABILITY_API:

            keys = cfg.STABILITY_API[:]
            random.shuffle(keys)
            key = keys[0]

            response = requests.post(
                f"https://api.stability.ai/v2beta/stable-image/generate/core",
                headers={
                    "authorization": f"Bearer {key}",
                    "accept": "image/*"
                },
                files={
                    "none": ''
                },
                data={
                    "prompt": prompt,
                    "output_format": "webp",
                },
                timeout=90,
            )

            if response.status_code == 200 and not is_blurry(response.content):
                WHO_AUTOR[hash(response.content)] = 'stability.ai'
                return [response.content, ]
            else:
                if 'Expecting value: line 1 column 1 (char 0)' not in response.json():
                    raise Exception(str(response.json()))
                else:
                    return []
    except Exception as error:
        if 'Expecting value: line 1 column 1 (char 0)' not in str(error):
            error_traceback = traceback.format_exc()
            my_log.log_huggin_face_api(f'my_genimg:stability_ai: {error}\n\n{error_traceback}')

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


def cosxl(prompt: str, url: str) -> bytes:
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
                os.remove(fname)
                os.rmdir(base_path)
            except Exception as error:
                my_log.log_huggin_face_api(f'my_genimg:cosxl: {error}\n\nPrompt: {prompt}\nURL: {url}')
            if data:
                WHO_AUTOR[hash(data)] = url.split('/')[-1]
                return [data,]
        except Exception as error:
            my_log.log_huggin_face_api(f'my_genimg:cosxl: {error}\n\nPrompt: {prompt}\nURL: {url}')
    return []


def get_reprompt(prompt: str, conversation_history: str) -> str:
    """
    Function to get a reprompt for image generation based on user's prompt and conversation history.
    Parameters:
    - prompt: a string containing the user's prompt
    - conversation_history: a string containing the conversation history
    Returns:
    - a string representing the reprompt for image generation
    """
    conversation_history = conversation_history.replace('𝐔𝐒𝐄𝐑:', 'user:')
    conversation_history = conversation_history.replace('𝐁𝐎𝐓:', 'bot:')
    query = f"""
User want to create image with text to image generator.
Repromt user's prompt for image generation.
Generate a good detailed prompt in english language, image generator accept only english so translate if needed.
If the query mentions celebrity names, try to replace them with movie character names, for example, Emma Watson -> Hermione Granger, Schwarzenegger -> Terminator.
Answer as a professional image prompt engineer, answer completely grammatically correct and future rich, add details if it was short.

User's prompt: {prompt}

Dialog history: {conversation_history}
"""

#     query = f"""
# User want to create image with text to image generator.
# Repromt user's prompt for image generation.
# Generate a good detailed prompt in english language, image generator accept only english so translate if needed.
# Answer as a professional image prompt engineer, completely grammatically correct and future rich, add details if it was short.

# User's prompt: {prompt}

# Dialog history for help you understand context: {conversation_history}
# """

    reprompt = my_gemini.ai(query, temperature=1.2)
    my_log.log_reprompts(f'{prompt}\n\n{reprompt}')

    query2 = f"""
Does this text look like a user request to generate an image? Yes or No, answer supershort.

Text: {reprompt}
"""
    if 'yes' in my_gemini.ai(query2, temperature=0.1).lower():
        return reprompt
    else:
        return prompt


def gen_images(prompt: str, moderation_flag: bool = False, user_id: str = '', conversation_history: str = ''):
    """рисует одновременно всеми доступными способами"""

    if prompt.strip() == '':
        return []

    reprompt = get_reprompt(prompt, conversation_history)
    prompt = reprompt

    pool = ThreadPool(processes=6)

    async_result1 = pool.apply_async(bing, (prompt, moderation_flag, user_id))
    
    async_result2 = pool.apply_async(kandinski, (prompt,))
    async_result3 = pool.apply_async(kandinski, (prompt,))

    async_result4 = pool.apply_async(huggin_face_api, (prompt,))

    async_result5 = pool.apply_async(yandex_cloud, (prompt,))
    async_result6 = pool.apply_async(yandex_cloud, (prompt,))


    result = (async_result1.get() or []) + \
            (async_result2.get() or []) + \
            (async_result3.get() or []) + \
            (async_result4.get() or []) + \
            (async_result5.get() or []) + \
            (async_result6.get() or [])

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


if __name__ == '__main__':
    imgs = kandinski('собака кусака')
    open('kandinski1.jpg', 'wb').write(imgs[0])
