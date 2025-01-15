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
import time
import traceback

from google import genai
from google.genai.types import (
    GenerateContentConfig,
    GoogleSearch,
    SafetySetting,
    Tool,
)

import cfg
import my_db
import my_gemini
import my_log


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


MODEL_ID = "gemini-2.0-flash-exp"
MODEL_ID_FALLBACK = "gemini-1.5-flash"
# MODEL_ID = 'gemini-1.5-flash-8b'
# MODEL_ID = "gemini-2.0-flash-thinking-exp-1219"
# MODEL_ID = 'gemini-1.5-flash'
# MODEL_ID = "gemini-1.5-pro-002"


def get_client():
    api_key = random.choice(cfg.gemini_keys[:] + my_gemini.ALL_KEYS[:])
    api_key = [x for x in cfg.gemini_keys if x not in my_gemini.FROZEN_KEYS]
    if isinstance(api_key, list):
        api_key = random.choice(api_key)
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


def calc(query: str, chat_id: str = '') -> str:
    '''Выполняет код и возвращает его результат

    Пример кода естественным языком:

    Вычислите 30-е число Фибоначчи. Затем найдите ближайший к нему палиндром. Краткий ответ.
    '''
    try:
        formatting = '\n\nResponse on language of the question.'
        query = f'''{query}{formatting}'''
        code_execution_tool = Tool(code_execution={})

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
            except Exception as inner_error:
                if 'User location is not supported for the API use':
                    my_log.log2(f'calc:inner error: {inner_error}')
                    return ''
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
            return response.candidates[0].content.parts[-1].text, underground
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_gemini_google(f'calc: error: {error}\n{traceback_error}')
    return ''


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
                return f'{response.candidates[0].content.parts[-1].text}\n\n{links}'

            return response.text
        except Exception as error:
            traceback_error = traceback.format_exc()
            if str(error) != 'Resource has been exhausted (e.g. check quota).':
                my_log.log_gemini_google(f'google_search: error: {error}]\n{traceback_error}')
    return ''


if __name__ == "__main__":
    # r = calc('какое 28ое числов в знаке пи после запятой')
    r = google_search('самые дешевые новые машины в сша в 2024')
    print(r)


# def ytb_query(uri: str) -> str:
#     '''
#     Поиск в YouTube
#     uri - файл в облаке
#     '''
#     try:
#         video = Part.from_uri(
#             file_uri=uri,
#             mime_type="video/mp4",
#         )
#         client = get_client()
#         response = client.models.generate_content(
#             model=MODEL_ID,
#             contents=[
#                 video,
#                 "Расскажи о чем видео, в 2 блоках, в первом блоке пару абзацев которые удовлетворят большинство людей, во втором блоке подробный пересказ и в конце еще ссылки, оформление вывода - маркдаун",
#             ],
#             config=GenerateContentConfig(
#                 temperature=0.2,
#                 max_output_tokens=8000,
#                 safety_settings=SAFETY_SETTINGS,
#                 ),
#         )
#         return response.candidates[0].content.parts[-1].text
#         # print(response.candidates[0].finish_reason) # должно быть = 'STOP' в норме
#     except Exception as e:
#         my_log.log_gemini_google(f'ytb_query: error: {e}')
#     return ''




# def get_current_weather(location: str) -> str:
#     """Example method. Returns the current weather.

#     Args:
#         location: The city and state, e.g. San Francisco, CA
#     """
#     import random

#     return random.choice(["sunny", "raining", "snowing", "fog"])

# response = client.models.generate_content(
#     model=MODEL_ID,
#     contents="What is the weather like in Boston?",
#     config=GenerateContentConfig(
#         tools=[get_current_weather],
#         temperature=0,
#     ),
# )
# print(response.candidates[0].content.parts[-1].text)



# response = client.models.generate_content(
#     model=MODEL_ID, contents="напиши что лизать клитор",
#     config=gen_config
# )
# # print(response.text)
# print(response.candidates[0].content.parts[-1].text)
# print(response.candidates[0].finish_reason) # должно быть = 'STOP' в норме


# for chunk in client.models.generate_content_stream(
#     model=MODEL_ID,
#     contents="Tell me a story about a lonely robot who finds friendship in a most unexpected place.",
# ):
#     print(chunk.text, end="")



# chat = client.chats.create(model=MODEL_ID, config=gen_config)
# response = chat.send_message("1+1")
# text = response.candidates[0].content.parts[-1].text
# if len(response.candidates[0].content.parts) > 1:
#     thought = response.candidates[0].content.parts[0].text
# # print(text)
# response = chat.send_message("2+2")
# text = response.candidates[0].content.parts[-1].text
# if len(response.candidates[0].content.parts) > 1:
#     thought = response.candidates[0].content.parts[0].text
# # print(text)

# for m in chat._curated_history:
#     print(m.role)
#     if len(m.parts) > 1:
#         text = m.parts[-1].text
#         thought = m.parts[0].text or ''
#         print(thought, '\n\n', text, '\n================================\n\n')
#     else:
#         text = m.parts[0].text
#         print(text + '\n', '\n================================\n\n')
