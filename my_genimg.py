#!/usr/bin/env python3


import base64
import json
import os
import random
import sys
import time
import traceback
from multiprocessing.pool import ThreadPool

import gradio_client
import langdetect
import requests
from duckduckgo_search import DDGS
from sqlitedict import SqliteDict

import bing_img
import cfg
import gpt_basic
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
        my_log.log2(f'my_genimg:stable_diffusion_api: {str(unknown)}\n\n{error_traceback}')
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
            "https://api-inference.huggingface.co/models/stablediffusionapi/juggernaut-xl-v8",
            'playgroundai/playground-v2.5-1024px-aesthetic',
            "https://api-inference.huggingface.co/models/ehristoforu/dalle-3-xl",
            "https://api-inference.huggingface.co/models/ehristoforu/dalle-3-xl",
            'playgroundai/playground-v2.5-1024px-aesthetic',
            "multimodalart/stable-cascade",
        ]

    prompt_ = prompt
    prompt = rewrite_prompt_for_open_dalle(prompt)
    if prompt_ != prompt:
        my_log.log_reprompts(f'{prompt_}\n\n{prompt}')

    payload = json.dumps({"inputs": prompt})

    def request_img(prompt, url, p):
        if 'stable-cascade' in url:
            return stable_cascade(prompt, url)
        if 'playgroundai/playground-v2.5-1024px-aesthetic' in url:
            return playground25(prompt, url)

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
            if response.content and '{"error"' not in resp_text:
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


def playground25(prompt: str, url: str) -> bytes:
    """
    url = "playgroundai/playground-v2.5-1024px-aesthetic" only?
    """
    client = gradio_client.Client("https://playgroundai-playground-v2-5.hf.space/--replicas/9kuov/")
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
            my_log.log2(f'my_genimg:stable_cascade: {error}\n\nPrompt: {prompt}\nURL: {url}')
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
                my_log.log2(f'my_genimg:stable_cascade: {error}\n\nPrompt: {prompt}\nURL: {url}')
            if data:
                WHO_AUTOR[hash(data)] = url.split('/')[-1]
                return [data,]
        except Exception as error:
            my_log.log2(f'my_genimg:stable_cascade: {error}\n\nPrompt: {prompt}\nURL: {url}')
    return []


def stable_cascade(prompt: str, url: str) -> bytes:
    """
    url = "multimodalart/stable-cascade" only?
    """
    client = gradio_client.Client(url)
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
            my_log.log2(f'my_genimg:stable_cascade: {error}\n\nPrompt: {prompt}\nURL: {url}')
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
                my_log.log2(f'my_genimg:stable_cascade: {error}\n\nPrompt: {prompt}\nURL: {url}')
            if data:
                WHO_AUTOR[hash(data)] = url.split('/')[-1]
                return [data,]
        except Exception as error:
            my_log.log2(f'my_genimg:stable_cascade: {error}\n\nPrompt: {prompt}\nURL: {url}')
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
        uuid = data['uuid']

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
        my_log.log2(f'my_genimg:kandinski: {error}\n\n{error_traceback}')


def gen_images(prompt: str, moderation_flag: bool = False, user_id: str = ''):
    """рисует одновременно всеми доступными способами"""
    #return bing(prompt) + chimera(prompt)

    # prompt_tr = gpt_basic.translate_image_prompt(prompt)

    pool = ThreadPool(processes=6)

    async_result1 = pool.apply_async(bing, (prompt, moderation_flag, user_id))

    async_result2 = pool.apply_async(huggin_face_api, (prompt,))
    
    async_result3 = pool.apply_async(kandinski, (prompt,))
    
    async_result4 = pool.apply_async(kandinski, (prompt,))

    result = async_result1.get() + async_result2.get() + async_result3.get() + async_result4.get()

    return result[:10]


if __name__ == '__main__':

    print(huggin_face_api('An austronaut is sitting on a moon.'))

    # if len(sys.argv) > 1:
    #     t = ' '.join(sys.argv[1:])
    # else:
    #     t = my_gemini.ai('Write a prompt for drawing a beautiful picture, make one sentence.', temperature=1)

    # n=0

    # r = str(random.randint(1000000000,9000000000))
    # starttime=time.time()
    # print(t)
    # for x in huggin_face_api(t):
    #     n+=1
    #     open(f'{n} - {r}.jpg','wb').write(x)
    # endtime=time.time()
    # print(round(endtime - starttime, 2))
