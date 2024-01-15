#!/usr/bin/env python3


import json
import os
import random
import traceback
from multiprocessing.pool import ThreadPool

import langdetect
import requests
import replicate
from duckduckgo_search import DDGS
from sqlitedict import SqliteDict

import bing_img
import cfg
import gpt_basic
import my_gemini
import my_log
import my_trans


NFSW_CONTENT = SqliteDict('db/nfsw_content_stable_diffusion.db', autocommit=True)


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
    prompt_translated = my_gemini.ai(f'This is a prompt for image generation. Rewrite it in english, in one long sentance, make it better:\n\n{prompt}', temperature=1)
    if not prompt_translated:
        return translate_prompt_to_en(prompt)
    return translate_prompt_to_en(prompt_translated)


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

    API_URL = [
                # "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0",
                # "https://api-inference.huggingface.co/models/dataautogpt3/OpenDalleV1.1",
                "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-2-1",
                "https://api-inference.huggingface.co/models/openskyml/dalle-3-xl",
                "https://api-inference.huggingface.co/models/prompthero/openjourney",
               ]

    api_key = random.choice(cfg.huggin_face_api)

    headers = {"Authorization": f"Bearer {api_key}"}

    # prompt = translate_prompt_to_en(prompt)
    prompt = rewrite_prompt_for_open_dalle(prompt)
    payload = json.dumps({"inputs": prompt})

    def request_img(prompt, url, h, p):
        try:
            response = requests.post(url, headers=h, json=p, timeout=180)
            result = []
            if response.content and ('error' not in str(response.content)[:300]):
                result.append(response.content)
            return result
        except Exception as error:
            my_log.log2(f'my_genimg:huggin_face_api: {error}\n\nPrompt: {prompt}')
            return []

    pool = ThreadPool(processes=6)
    async_result1 = pool.apply_async(request_img, (prompt, API_URL[1], headers, payload,))
    async_result2 = pool.apply_async(request_img, (prompt, API_URL[1], headers, payload,))
    # async_result3 = pool.apply_async(request_img, (prompt, API_URL[2], headers, payload,))
    # async_result4 = pool.apply_async(request_img, (prompt, API_URL[3], headers, payload,))
    # async_result5 = pool.apply_async(request_img, (prompt, API_URL[4], headers, payload,))
    result = async_result1.get() + async_result2.get() #+ async_result3.get() #+ async_result4.get() + async_result5.get()

    return result


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

    if not result:
        r = huggin_face_api(prompt)
        if r:
            result = r
            my_log.log2(f'my_genimg:gen_images: huggin_face_api')

    return result[:10]


if __name__ == '__main__':
    # print(ddg_search_images('сочная малина'))
    # print(gen_images('рисунок мальчика с чёрными волосами в костюме жирафа и девочки с рыжими волосами в костюме лисы, наклейки, логотип, минимализм, в новый год, наряжают ёлку'))
    # print(stable_duffision_api('гермиона гренджер на коленях перед священником'))
    # print(stable_duffision_api('a man standing in front of a painting, ssr card, avatar for website, archers, ram skull, janapese, jeremy, mall background, young man with short, marvel poster, wlop : :'))
    # print(stable_duffision_api("Hermione Granger looks up, mouth agape, in awe and wonder. The light of magic illuminates her face and sparkles dance in her eyes. A swirl of books and magical artifacts surrounds her, representing her vast knowledge and love of learning. The background is a grand library or a starry night sky, symbolizing her limitless potential and insatiable curiosity. The overall tone is one of amazement and discovery."))
    # print(stable_duffision_api("Гермиона Грейнджер смотрит вверх с разинутым ртом в благоговении и удивлении. Свет волшебства освещает ее лицо и сверкает танцем в глазах. Ее окружает водоворот книг и магических артефактов, символизирующий ее обширные знания и любовь к учебе. Фоном является огромная библиотека или звездное ночное небо, символизирующее ее безграничный потенциал и ненасытное любопытство. Общий тон – изумление и открытие."))
    open('1.jpg','wb').write(huggin_face_api('Гермиона Грейнджер смотрит вверх с разинутым ртом в благоговении и удивлении. Свет волшебства освещает ее лицо и сверкает танцем в глазах. Ее окружает водоворот книг и магических артефактов, символизирующий ее обширные знания и любовь к учебе. Фоном является огромная библиотека или звездное ночное небо, символизирующее ее безграничный потенциал и ненасытное любопытство. Общий тон – изумление и открытие.'))
