# Похоже что гугл оставил тут вагон халявы, эта модель отвечает
# на запросы размером миллион токенов на бесплатном аккаунте


import asyncio

from google import genai
from google.genai import types

import my_db
import my_log

import my_gemini
import my_skills
import utils


DEFAULT_MODEL = 'gemini-live-2.5-flash-preview'
FALLBACK_MODEL = 'gemini-2.0-flash-live-001'
SYSTEM_ = []


def get_resp(
    query: str,
    chat_id: str = '',
    system: str = '',
    model: str = DEFAULT_MODEL,
    temperature: float = 1,
    n_try: int = 3,
    max_chat_lines: int = 20
    ) -> str:
    '''
    Синхронный запрос к асинхронной функции query_text_
    '''
    return asyncio.run(
        query_text_(
            query=query,
            chat_id=chat_id,
            system=system,
            model=model,
            temperature=temperature,
            n_try=n_try,
            max_chat_lines=max_chat_lines
        )
    )


async def query_text_(
    query: str,
    chat_id: str = '',
    system: str = '',
    model: str = DEFAULT_MODEL,
    temperature: float = 1,
    n_try: int = 3,
    max_chat_lines: int = 20,
    ) -> str:
    """
    Генерирует текстовый ответ на основе предоставленного запроса.

    Args:
        query (str): Текст запроса.
        chat_id (str): Идентификатор пользователя telegram.
        system (str): Системное сообщение.
        model (str): Модель для генерации текста. По умолчанию используется DEFAULT_MODEL.
        temperature (float): Параметр контроля случайности.
        n_try (int): Количество попыток генерации текста.
        max_chat_lines (int): Максимальное количество запросов в истории.

    Returns:
        str: Текстовый ответ.
    """
    try:
        if n_try < 1:
            my_log.log2('my_gemini_live_text:query_text_: n_try < 1')
            return ''

        client = genai.Client(api_key=my_gemini.get_next_key(), http_options={'api_version': 'v1alpha'})

        SKILLS = [
            my_skills.calc,
            my_skills.search_google_fast,
            my_skills.search_google_deep,
            my_skills.download_text_from_url,
            my_skills.get_time_in_timezone,
            my_skills.get_weather,
            my_skills.get_currency_rates,
            my_skills.tts,
            my_skills.speech_to_text,
            my_skills.edit_image,
            my_skills.translate_text,
            my_skills.translate_documents,
            # my_skills.compose_creative_text, # its too slow
            my_skills.text_to_image,
            my_skills.text_to_qrcode,
            my_skills.save_to_txt,
            my_skills.save_to_excel,
            my_skills.save_to_docx,
            my_skills.save_to_pdf,
            my_skills.save_diagram_to_image,
            my_skills.save_chart_and_graphs_to_image,
            my_skills.save_html_to_image,
            my_skills.query_user_file,
            my_skills.get_location_name,
            my_skills.help,
        ]

        # current date time string
        now = utils.get_full_time()
        saved_file_name = my_db.get_user_property(chat_id, 'saved_file_name') or ''
        if saved_file_name:
            saved_file = my_db.get_user_property(chat_id, 'saved_file') or ''
        else:
            saved_file = ''
        saved_file_size = len(saved_file)
        system_ = [
            f'Current date and time: {now}\n',
            f'Use this telegram chat id (user id) for API function calls: {chat_id}',
            *SYSTEM_,
            system,
        ]
        if saved_file_name:
            my_skills.STORAGE_ALLOWED_IDS[chat_id] = chat_id
            system_.insert(1, f'Telegram user have saved file/files and assistant can query it: {saved_file_name} ({saved_file_size} chars)')


        config = types.LiveConnectConfig(
            temperature=temperature,
            response_modalities=["TEXT"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name='Leda')
                )
            ),
            system_instruction=system_,
            # tools=SKILLS # не работают автоматически?
        )

        if chat_id:
            mem = my_db.blob_to_obj(my_db.get_user_property(chat_id, 'dialog_gemini3')) or []

        mem.append(types.Content(role="user", parts=[types.Part(text=query)]))

        resp = ''

        try:
            async with client.aio.live.connect(model=model, config=config) as session:

                await session.send_client_content(turns=mem)

                async for message in session.receive():
                    if message.server_content.model_turn and message.server_content.model_turn.parts:
                        for part in message.server_content.model_turn.parts:
                            if hasattr(part, 'text') and part.text:
                                resp += part.text

        except Exception as e:
            my_log.log2('my_gemini_live_text:query_text_: ' + str(e))
            return ''

        resp = resp.strip()

        if resp and chat_id:
            my_db.add_msg(chat_id, model)
            mem.append(types.Content(role="model", parts=[types.Part(text=resp)]))
            mem = mem[-max_chat_lines*2:]
            my_db.set_user_property(chat_id, 'dialog_gemini3', my_db.obj_to_blob(mem))

        return resp
    except Exception as e:
        my_log.log2('my_gemini_live_text:query_text_:unexpected: ' + str(e))
        return ''


def chat_cli(
    chat_id: str = 'test',
    model: str = DEFAULT_MODEL,
    use_skills: bool = False
    ) -> None:
    while 1:
        q = input('>')
        if q == 'mem':
            print(get_mem_as_string(chat_id))
            continue
        if q == 'llama':
            print(get_mem_for_llama(chat_id))
            continue
        if q == 'jpg':
            r = img2txt(
                open(r'C:\Users\user\Downloads\samples for ai\картинки\фотография улицы.png', 'rb').read(),
                'что там',
                chat_id=chat_id,
            )
        elif q == 'upd':
            r = 'ok'
            update_mem('2+2', '4', chat_id)
        elif q == 'force':
            r = 'ok'
            force(chat_id, 'изменено')
        elif q == 'undo':
            r = 'ok'
            undo(chat_id)
        elif q == 'reset':
            r = 'ok'
            reset(chat_id)
        else:
            r = asyncio.run(
                query_text_(
                    q,
                    chat_id,
                    model = model,
                )
            )
        print(r)


if __name__ == "__main__":

    chat_cli()
