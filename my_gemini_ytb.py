# To run this code you need to install the following dependencies:
# pip install google-genai

import time

from google import genai
from google.genai import types

import my_db
import my_gemini
import my_log


PROMPT = """Перепиши текстом всё содержание видео целиком стараясь ничего не упустить, уложись до 1500 слов. Ответ напиши на языке """
MODEL = "gemini-2.0-flash"
TIMEOUT = 180


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
    start_time = time.time()
    for _ in range(3):
        if time.time() - start_time > TIMEOUT:
            break
        try:
            key = my_gemini.get_next_key()
            client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=TIMEOUT*1000))

            model = MODEL
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
                tools=tools,
                response_mime_type="text/plain",
            )

            resp = client.models.generate_content(
                model=model,
                contents=contents,
                config=generate_content_config,
            )
            if resp and resp.text:
                result = resp.text
                break

        except Exception as e:
            my_log.log_gemini(f'my_gemini_ytb:get_text: {e}')

    if result and user_id:
        my_db.add_msg(user_id, MODEL)

    return result


if __name__ == "__main__":
    my_db.init(backup=False)
    my_gemini.load_users_keys()

    get_text('https://www.youtube.com/shorts/CqnJNdrz5DY', 'ru', '')
