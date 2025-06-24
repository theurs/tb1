# Похоже что гугл оставил тут вагон халявы, эта модель отвечает
# на запросы размером миллион токенов на бесплатном аккаунте


import asyncio

from google import genai
from google.genai import types

import cfg
import my_db
import my_log


DEFAULT_MODEL = 'gemini-live-2.5-flash-preview'
FALLBACK_MODEL = "gemini-2.0-flash-live-001"


async def query_text_(
    query: str,
    user_id: str = '',
    system: str = '',
    model: str = DEFAULT_MODEL,
    temperature: float = 1,
    n_try: int = 3,
    ) -> str:
    """
    Генерирует текстовый ответ на основе предоставленного запроса.

    Args:
        query (str): Текст запроса.
        user_id (str): Идентификатор пользователя telegram.
        system (str): Системное сообщение.
        model (str): Модель для генерации текста. По умолчанию используется DEFAULT_MODEL.
        temperature (float): Параметр контроля случайности.
        n_try (int): Количество попыток генерации текста.

    Returns:
        str: Текстовый ответ.
    """
    if n_try < 1:
        my_log.log2('my_gemini_live_text:query_text_: n_try < 1')
        return ''

    client = genai.Client(api_key=cfg.gemini_keys[0], http_options={'api_version': 'v1alpha'})

    config = types.LiveConnectConfig(
        temperature=temperature,
        response_modalities=["TEXT"],
        system_instruction=system,
    )

    resp = ''

    try:
        async with client.aio.live.connect(model=model, config=config) as session:

            await session.send_client_content(
                turns=types.Content(
                    role="user",
                    parts=[
                        types.Part(text=query),
                    ]
                )
            )

            async for message in session.receive():
                if message.server_content.model_turn and message.server_content.model_turn.parts:
                    for part in message.server_content.model_turn.parts:
                        if hasattr(part, 'text') and part.text:
                            resp += part.text
                            # print(part.text, end='')
    except Exception as e:
        my_log.log2('my_gemini_live_text:query_text_: ' + str(e))
        return ''

    resp = resp.strip()

    if resp and user_id:
        my_db.add_msg(user_id, model)

    return resp


if __name__ == "__main__":

    with open('C:/Users/user/Downloads/samples for ai/myachev_Significant_Digits_-_znachaschie_tsifryi_106746.txt', 'r', encoding='utf-8') as f:
        sample_text = f.read()
        print(len(sample_text))  

    query = "Перескажи содержание 49 главы книги\n\nКнига:\n\n" + sample_text

    response = asyncio.run(query_text_(sample_text))
    print(response)
