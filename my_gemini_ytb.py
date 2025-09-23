# To run this code you need to install the following dependencies:
# pip install google-genai

import time

from google import genai
from google.genai import types

import cfg
import my_db
import my_gemini_general
import my_log


PROMPT = """Перепиши текстом всё содержание видео целиком стараясь ничего не упустить, уложись до 1500 слов. Ответ напиши на языке """
MODEL = cfg.gemini25_flash_model
MODEL_FALLBACK = cfg.gemini25_flash_model_fallback
# MODEL = "gemini-2.0-flash"
# MODEL_FALLBACK = "gemini-2.0-flash-001"
TIMEOUT = 180

SAFETY_SETTINGS = [
    types.SafetySetting(
        category="HARM_CATEGORY_DANGEROUS_CONTENT",
        threshold="BLOCK_NONE",
    ),
    types.SafetySetting(
        category="HARM_CATEGORY_HARASSMENT",
        threshold="BLOCK_NONE",
    ),
    types.SafetySetting(
        category="HARM_CATEGORY_HATE_SPEECH",
        threshold="BLOCK_NONE",
    ),
    types.SafetySetting(
        category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
        threshold="BLOCK_NONE",
    ),
]


def get_text(url: str, lang: str, user_id: str) -> str:
    '''
    Get text from url YouTube video
    Args:
        url: str
        lang: str 'en', 'ru', etc
        user_id: str
    Returns:
        str: video as text
    '''
    result = ''
    model = MODEL
    start_time = time.time()
    for _ in range(3):
        if time.time() - start_time > TIMEOUT:
            break
        try:
            key = my_gemini_general.get_next_key()
            client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=TIMEOUT*1000))

            contents = [
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            file_data=types.FileData(
                                file_uri=url,
                                mime_type="video/*",
                            )
                        ),
                        types.Part.from_text(text=f'{PROMPT} **{lang}**.'),
                    ],
                ),
            ]
            tools = [
                types.Tool(url_context=types.UrlContext()),
            ]
            generate_content_config = types.GenerateContentConfig(
                thinking_config = types.ThinkingConfig(
                    thinking_budget=0,
                ),
                safety_settings=SAFETY_SETTINGS,
                tools=tools,
                response_mime_type="text/plain",
            )

            for chunk in client.models.generate_content_stream(model=model, contents=contents, config=generate_content_config):
                if chunk.text:
                    result += chunk.text

            if result:
                break

            if model == MODEL:
                model = MODEL_FALLBACK
            else:
                model = MODEL

        except Exception as e:
            my_log.log_gemini(f'my_gemini_ytb:get_text: {e}')
            result = ''
            if model == MODEL:
                model = MODEL_FALLBACK
            else:
                model = MODEL

    if result and user_id:
        my_db.add_msg(user_id, MODEL)
    if result:
        my_log.log_gemini(f'my_gemini_ytb:get_text: transcribed with {model} in {time.time() - start_time:.2f} seconds {url} {lang} {user_id}')

    return result


if __name__ == "__main__":
    my_db.init(backup=False)
    my_gemini_general.load_users_keys()

    print(get_text('https://www.youtube.com/shorts/CqnJNdrz5DY', 'ru', ''))
