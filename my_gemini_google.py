#!/usr/bin/env python3
# pip install -U google-genai
# https://github.com/GoogleCloudPlatform/generative-ai/blob/main/gemini/getting-started/intro_gemini_2_0_flash.ipynb
# 
# если недоступно в этой стране то можно попробовать добавить эот в hosts файл
# 50.7.85.220 gemini.google.com
# 50.7.85.220 aistudio.google.com
# 50.7.85.220 generativelanguage.googleapis.com
# 50.7.85.220 alkalimakersuite-pa.clients6.google.com
# 50.7.85.220 notebooklm.google
# 50.7.85.220 notebooklm.google.com

# 50.7.85.220 labs.google
# 50.7.85.220 o.pki.goog


import random
import re
import time
import traceback
from typing import Tuple

from google import genai
from google.genai.types import (
    GenerateContentConfig,
    GoogleSearch,
    SafetySetting,
    Tool,
)

import cfg
import my_db
import my_gemini_general
import my_gemini3
import my_log
import my_skills_storage
import utils


SAFETY_SETTINGS = [
    SafetySetting(
        category="HARM_CATEGORY_DANGEROUS_CONTENT",
        threshold="BLOCK_NONE",
    ),
    SafetySetting(
        category="HARM_CATEGORY_HARASSMENT",
        threshold="BLOCK_NONE",
    ),
    SafetySetting(
        category="HARM_CATEGORY_HATE_SPEECH",
        threshold="BLOCK_NONE",
    ),
    SafetySetting(
        category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
        threshold="BLOCK_NONE",
    ),
]


MODEL_ID = cfg.gemini25_flash_model # 'gemini-2.5-flash-preview-05-20' # "gemini-2.0-flash-exp"
MODEL_ID_FALLBACK = cfg.gemini25_flash_model_fallback # "gemini-1.5-flash"


def get_client():
    api_key = random.choice(cfg.gemini_keys[:] + my_gemini_general.ALL_KEYS[:])
    return genai.Client(api_key=api_key)


def get_config(system_instruction: str = "", max_output_tokens: int = 8000, temperature: float = 1):
    gen_config = GenerateContentConfig(
        temperature=temperature,
        # top_p=0.95,
        # top_k=20,
        # candidate_count=1,
        # seed=5,
        max_output_tokens=max_output_tokens,
        system_instruction=system_instruction,
        safety_settings=SAFETY_SETTINGS,
        # stop_sequences=["STOP!"],
        # presence_penalty=0.0,
        # frequency_penalty=0.0,
        )

    return gen_config


def calc(query: str, chat_id: str = '') -> Tuple[str, str]:
    """
    Executes code based on a natural language query and returns the result.

    Args:
        query: The natural language query.
        chat_id: The ID of the chat (optional).

    Returns:
        A tuple containing:
            - The text response from the model.
            - A string containing the executed code and its output (for debugging).

    Example natural language code query:
    Calculate the 30th Fibonacci number. Then find the closest palindrome to it. Short answer.
    """
    try:
        time.sleep(1)
        formatting = '\n\nResponse on language of the question. You can draw graphs ant charts using code_execution_tool.'
        query = f'''{query}{formatting}'''
        code_execution_tool = Tool(code_execution={})
        resp_full = None

        for _ in range(4):
            client = get_client()

            try:
                response = client.models.generate_content(
                    model=MODEL_ID,
                    contents=query,
                    config=GenerateContentConfig(
                        tools=[code_execution_tool],
                        temperature=0,
                        max_output_tokens=8000,
                        safety_settings=SAFETY_SETTINGS,
                    ),
                )
                resp_full = my_gemini3.parse_content_response(response)

            except Exception as inner_error:
                if 'User location is not supported for the API use':
                    my_log.log2(f'calc:inner error: {inner_error}')
                    return '', ''
                if 'Resource has been exhausted (e.g. check quota)' in str(inner_error):
                    continue

            underground = ''
            if response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.executable_code:
                        language = part.executable_code.language.lower()
                        code = part.executable_code.code
                        underground += f'```{language}\n{code}```\n'

                    if part.code_execution_result and part.code_execution_result.output:
                        underground += f'```{part.code_execution_result.output}```\n'

            if chat_id:
                my_db.add_msg(chat_id, MODEL_ID)

            # если есть картинки то отправляем их через my_skills_storage.STORAGE
            if resp_full and resp_full[0] and chat_id:
                for image in resp_full[0]:
                    item = {
                        'type': 'image/png file', # image['mime_type'],
                        'filename': image['filename'],
                        'data': image['data'],
                    }
                    with my_skills_storage.STORAGE_LOCK:
                        if chat_id in my_skills_storage.STORAGE:
                            if item not in my_skills_storage.STORAGE[chat_id]:
                                my_skills_storage.STORAGE[chat_id].append(item)
                        else:
                            my_skills_storage.STORAGE[chat_id] = [item,]

            if response and response.candidates and response.candidates[0].content.parts and response.candidates[0].content.parts[-1].text:
                return response.candidates[0].content.parts[-1].text, underground
            else:
                return '', ''
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_gemini_google(f'calc: error: {error}\n{traceback_error}')

    return '', ''


def google_search(query: str, chat_id: str = '', role: str = '', lang: str = 'en') -> str:
    '''
    Поиск в Google
    '''
    if not role:
        role = None

    formatting = f"\n\nAnswer in the user's language: [{lang}]."
    query = f'''{query}{formatting}'''

    google_search_tool = Tool(google_search=GoogleSearch())

    for _ in range(3):
        try:
            client = get_client()
            retry_counter = 0 # retry on overload error

            try:
                response = client.models.generate_content(
                    model=MODEL_ID,
                    contents=query,
                    config=GenerateContentConfig(
                        system_instruction = role,
                        tools=[google_search_tool],
                        temperature=0.2,
                        max_output_tokens=8000,
                        safety_settings=SAFETY_SETTINGS,
                        ),
                )
            except Exception as inner_error:
                if "Quota exceeded for quota metric 'Generate Content API requests per minute' and limit" in str(inner_error):
                    my_log.log_gemini_google(f'google_search:inner error: {inner_error}')
                    continue
                if '429 RESOURCE_EXHAUSTED.' in str(inner_error):
                    continue
                if 'Resource has been exhausted (e.g. check quota)' in str(inner_error):
                    continue
                if 'User location is not supported for the API use' in str(inner_error):
                    my_log.log2(f'google_search:inner error1: {inner_error}')
                    return ''
                if 'The model is overloaded. Please try again later.' in str(inner_error):
                    my_log.log2(f'google_search:inner:1: error2: {inner_error}')
                    time.sleep(5)
                    retry_counter += 1
                    if retry_counter > 5:
                        return ''
                    continue
                my_log.log2(f'google_search:inner:2: error2: {inner_error}')
                response = client.models.generate_content(
                    model=MODEL_ID_FALLBACK,
                    contents=query,
                    config=GenerateContentConfig(
                        system_instruction = role,
                        tools=[google_search_tool],
                        temperature=0.2,
                        max_output_tokens=8000,
                        safety_settings=SAFETY_SETTINGS,
                        ),
                )

            if chat_id:
                my_db.add_msg(chat_id, MODEL_ID)
            links = []
            # import pprint
            # pprint.pprint(response)
            if response.candidates[0].grounding_metadata.grounding_chunks:
                for part in response.candidates[0].grounding_metadata.grounding_chunks:
                    title = part.web.title
                    url = part.web.uri
                    link = f'[{title}]({url})'
                    links.append(link)

            if links:
                links = '\n'.join(links)
                result = f'{response.candidates[0].content.parts[-1].text}\n\n{links}'
            else:
                result = response.text

            if not result:
                continue
            # флеш (и не только) иногда такие тексты в которых очень много повторов выдает,
            # куча пробелов, и возможно другие тоже. укорачиваем
            result = re.sub(r" {1000,}", " " * 10, result) # очень много пробелов в ответе
            result = utils.shorten_all_repeats(result)

            return result
        except Exception as error:
            traceback_error = traceback.format_exc()
            if str(error) != 'Resource has been exhausted (e.g. check quota).':
                my_log.log_gemini_google(f'google_search: error: {error}]\n{traceback_error}')
    return ''


if __name__ == "__main__":
    # r = calc('какое 28ое числов в знаке пи после запятой')
    # r = google_search('самые дешевые новые машины в сша в 2024')

    r = calc('нарисуй график функции x=y^4')
    print(r)

