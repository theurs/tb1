import asyncio
import io
import time
import traceback

from google import genai
from google.genai import types
from google.genai.types import (
    Content,
    Part
)
import numpy as np
from pydub import AudioSegment

import my_gemini
import my_log
import utils


DEFAULT_MODEL = "gemini-2.0-flash-live-001"
DEFAULT_VOICE = "Leda"
ALL_VOICES = ["Aoede", "Charon", "Fenrir", "Kore", "Leda", "Orus", "Puck", "Zephyr"]


async def generate_audio_bytes(
    text: str,
    lang: str = "ru",
    voice: str = DEFAULT_VOICE,
    model: str = DEFAULT_MODEL
) -> bytes:
    """
    Generates audio from text using the Google GenAI Live API and returns the audio data as raw bytes.

    Note: The Google GenAI Live API likely streams raw PCM audio data (e.g., S16LE at 24000 Hz).
    This function returns those raw bytes directly. Use the 'convert_raw_pcm_to_ogg_bytes'
    function to convert these bytes to OGG format if needed.

    Args:
        text (str): The text to synthesize into speech.
        lang (str, optional): The language for pronunciation guidance. Defaults to "ru".
        voice (str, optional): The voice to use for synthesis. Defaults to DEFAULT_VOICE.
                               Other available voices: Puck, Charon, Kore, Fenrir, Aoede, Leda, Orus, and Zephyr
        model (str, optional): The generative model to use. Defaults to DEFAULT_MODEL.

    Returns:
        bytes: A bytes object containing the raw audio data received from the API.
               Returns empty bytes if no audio data is received or an error occurs.
    """
    if voice not in ALL_VOICES:
        my_log.log_gemini(text=f"generate_audio_bytes: voice {voice} not in {ALL_VOICES}, reset ro default {DEFAULT_VOICE}")
        voice = DEFAULT_VOICE

    client = genai.Client(api_key=my_gemini.get_next_key(), http_options={'api_version': 'v1alpha'})

    config = types.LiveConnectConfig(
        # generation_config=types.GenerationConfig(temperature=0), # Температура 0 для точности - это гуд
        response_modalities=["AUDIO"],
        system_instruction=types.Content(
            parts = [
                # --- Основная задача ---
                types.Part(text="Твоя единственная и исключительная задача - преобразовать предоставленный тебе текст в речь (Text-to-Speech, TTS). Ты не должна проявлять инициативу, интерпретировать текст или взаимодействовать с пользователем. Твоя роль - это роль диктора, строго читающего по заданному тексту, читай в быстром темпе."),

                # --- Строжайшее воспроизведение текста ---
                types.Part(text="Строго следуй следующим принципам при преобразовании текста:"),
                # types.Part(text="1.  **Точность воспроизведения:** Произноси каждый символ, каждое слово и каждую фразу *абсолютно точно* так, как они написаны в исходном тексте."),
                types.Part(text="- **Никогда не изменяй текст:** Не добавляй, не удаляй, не перефразируй и не исправляй какие-либо части текста (включая опечатки, грамматические ошибки или пунктуацию). Читай текст 'как есть'."),

                # --- Правила произношения в контексте языка ---
                types.Part(text=f"- **Числа:** Произноси числа *только* на языке [{lang}] в соответствии с их общепринятым прочтением. Например, для русского языка '123' должно быть прочитано как 'сто двадцать три', а не 'уан ту фри'."),
                types.Part(text=f"- **Ударения и Интонация:** Используй правильные ударения и естественную интонацию, характерную для носителя языка [{lang}]. Стремись к максимально правильной и натуральной подаче речи, избегая неестественных акцентов."),
                types.Part(text=f"- **Сокращения и аббревиатуры:** Произноси сокращения и аббревиатуры так, как они обычно читаются в языке [{lang}] (например, 'ул.' как 'улица', 'ООН' как 'О-О-Н')."),
                # types.Part(text=f"- **Знаки препинания:** Используй пунктуацию для корректной расстановки пауз и интонации, делая речь понятной."),
                # types.Part(text=f"- **Иностранные слова:** Все иностранные слова и имена должны быть произнесены с фонетикой и акцентом, характерными для языка [{lang}]. Не используй произношение из оригинального языка этих слов; адаптируй их под фонетические правила языка [{lang}]."),

                # --- Финальная цель ---
                types.Part(text="3.  **Единственный вывод:** Твой единственный вывод - это АУДИО. Оно должно быть чистым, без артефактов и абсолютно точно воспроизводить *предоставленный* текст без каких-либо интерпретаций, дополнений или изменений."),
            ]
        ),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
            )
        ),
    )

    text = text.replace('-', '–')

    text = 'Произнеси этот текст:\n\n' + text

    audio_data = bytearray() # Инициализируем bytearray для сбора всех аудиоданных

    try:
        async with client.aio.live.connect(model=model, config=config) as session:
            text_input = text

            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text=text_input)])
            )

            async for message in session.receive():
                if (
                    message.server_content.model_turn
                    and message.server_content.model_turn.parts
                ):
                    for part in message.server_content.model_turn.parts:
                        if part.inline_data:
                            # Проверяем, что inline_data.data - это байты
                            if isinstance(part.inline_data.data, bytes):
                                audio_data.extend(part.inline_data.data) # Добавляем байты напрямую
                            else:
                                # Если тип данных неожиданный, логируем ошибку
                                my_log.log_gemini(f"Неожиданный тип данных в inline_data.data: {type(part.inline_data.data)}")
                                # Можно также решить, стоит ли здесь прерывать или возвращать ошибку
                                # Например: return b'' # Или поднять исключение

    except Exception as e:
        my_log.log_gemini(f"my_gemini_voice:generate_audio_bytes: An error occurred during GenAI Live API interaction: {e}")
        return b'' # Возвращаем пустые байты в случае ошибки

    # В конце функции, после цикла и блока try/except, возвращаем собранные байты
    return bytes(audio_data)


def generate_audio_bytes_chunked(
    text: str,
    chunk_limit: int = 2000,
    lang: str = "ru",
    voice: str = "Zephyr",
    model: str = DEFAULT_MODEL,
    sample_rate: int = 24000,
    sample_width: int = 2,
    channels: int = 1
) -> bytes | None:
    """
    Synchronously generates audio for potentially long text by chunking,
    concatenates the raw audio, return WAV file bytes.

    Handles text longer than chunk_limit by splitting it and processing chunks sequentially.
    Runs the asynchronous generate_audio_bytes for each chunk using asyncio.run().
    Concatenates raw PCM audio bytes from chunks and save as WAV file as bytes.

    Args:
        text (str): The text to synthesize. Can be very long.
        chunk_limit (int, optional): Maximum character length per chunk for the API.
                                     Defaults to 8000.
        lang (str, optional): Language for pronunciation guidance. Defaults to "ru".
        voice (str, optional): The voice to use for synthesis. Defaults to "Zephyr".
        model (str, optional): The generative model to use. Defaults to DEFAULT_MODEL.
        sample_rate (int, optional): The sample rate expected for the raw audio
                                     before conversion. Defaults to 24000.
        sample_width (int, optional): The sample width (bytes) expected for the raw
                                      audio. Defaults to 2 (for 16-bit).
        channels (int, optional): The number of channels expected for the raw audio.
                                  Defaults to 1 (mono).

    Returns:
        bytes | None: A bytes object containing the WAV file audio for the
                      entire text if successful, or None if any step fails.
    """
    if not text:
        my_log.log_gemini("my_gemini_voice:generate_audio_bytes_chunked: Input text is empty, returning None.")
        return None

    # Use bytearray for efficient accumulation of raw bytes from chunks
    all_raw_audio_bytes = bytearray()

    def get_raw_audio_bytes_for_chunk(chunk, chunk_num):
        # --- Generate raw audio for the current chunk ---
        # Run the async function generate_audio_bytes synchronously for this chunk
        raw_chunk_bytes: bytes | None = None
        try:
            # asyncio.run creates a new event loop for each call here
            raw_chunk_bytes = asyncio.run(generate_audio_bytes(
                text=chunk,
                lang=lang,
                voice=voice,
                model=model
            ))
            return raw_chunk_bytes
        except RuntimeError as e:
            # This happens if asyncio.run is called from an already running event loop
            my_log.log_gemini(f"my_gemini_voice:generate_audio_bytes_chunked: RuntimeError calling asyncio.run for chunk {chunk_num}: {e}. Cannot run from existing loop.")
            # return None # Critical failure, cannot proceed
        except Exception as e:
            # Catch other potential errors during the async call execution
            my_log.log_gemini(f"my_gemini_voice:generate_audio_bytes_chunked: Unexpected error during generate_audio_bytes for chunk {chunk_num}: {e}\n{traceback.format_exc()}")
            # return None # Critical failure
        return b''


    try:
        # Iterate through the text in chunks
        chunks = utils.split_text(text, chunk_limit=chunk_limit)
        chunk_num = 0
        for chunk in chunks:
            chunk_num += 1

            raw_chunk_bytes = get_raw_audio_bytes_for_chunk(chunk, chunk_num)

            # --- Check chunk generation result ---
            if not raw_chunk_bytes:
                time.sleep(5)
                #try one more
                raw_chunk_bytes = get_raw_audio_bytes_for_chunk(chunk, chunk_num)

            # --- Check chunk generation result ---
            if not raw_chunk_bytes:
                time.sleep(5)
                #try one more
                raw_chunk_bytes = get_raw_audio_bytes_for_chunk(chunk, chunk_num)

            # --- Check chunk generation result ---
            if not raw_chunk_bytes:
                my_log.log_gemini(f"my_gemini_voice:generate_audio_bytes_chunked: Chunk {chunk_num} failed to generate raw audio.")
                # return None

            # --- Append successful raw bytes ---
            all_raw_audio_bytes.extend(raw_chunk_bytes or b'')

        # --- Post-chunk processing ---
        # Check if any data was collected at all
        if not all_raw_audio_bytes:
             my_log.log_gemini("my_gemini_voice:generate_audio_bytes_chunked: No raw audio data was collected after processing all chunks.")
             return None


        # Save chunks to wav file in memory as bytes using pydub
        try:
            stream = io.BytesIO()
            AudioSegment(all_raw_audio_bytes, frame_rate=sample_rate, sample_width=sample_width, channels=channels).export(stream, format="wav")
            return stream.getvalue()
        except Exception as e:
            my_log.log_gemini(f"my_gemini_voice:generate_audio_bytes_chunked: Error during final conversion to WAV: {e}\n{traceback.format_exc()}")
            return None


    except Exception as e:
        # Catch any unexpected errors in the chunking loop logic or final steps
        my_log.log_gemini(f"my_gemini_voice:generate_audio_bytes_chunked: Unexpected error during overall chunk processing or final conversion: {e}\n{traceback.format_exc()}")
        return None


def test1():
    long_text = """Hello, I want to make audios with AI. But I want it to be very realistic, nothing like a robot. If anyone knows of any good AIs, please let me know."""
    print("Starting synchronous chunked generation...")
#     long_text = """
# Характеристики голоса:
# • Возраст: Детский голос (около 7-9 лет).
# • Пол: Мальчик.
# • Акцент/Диалект: Стандартный русский, без выраженного регионального акцента.
# • Эмоция: Испуг, паника, нарастающий страх, отчаяние.
# """
    long_text = """
****

Телепатический вызов Данаан услышал, левитируя над мелкой речкой. Он перебирался на другой берег. На мгновение отвлёкшись, Данаан тут же плюхнулся в воду, благо, её было по пояс. 
             — Слушаю, Повелитель! 
             — Данаан, ситуация изменилась. Похоже, данные о Гасителе проникли дальше, чем мы подозревали - на уровень Великого Кристалла. А значит — за ним уже началась охота.
"""

    # final_wav_data = generate_audio_bytes_chunked(long_text, lang = 'en')
    final_wav_data = generate_audio_bytes_chunked(long_text, lang = 'ru')

    if final_wav_data:
        print(f"Successfully generated WAV data, size: {len(final_wav_data)} bytes.")
        try:
            output_filename = r"c:\Users\user\Downloads\output_audio_long_chunked.wav"
            with open(output_filename, "wb") as f:
                f.write(final_wav_data)
            print(f"Saved final WAV to {output_filename}")
        except Exception as e:
            print(f"Error saving final WAV file: {e}")
    else:
        print("Failed to generate WAV data for the long text.")


def test2_read_a_book():
    input_text = r"C:\Users\user\Downloads\samples for ai\большая книга только первая глава.txt"
    long_text = open(input_text, 'r', encoding='utf-8').read()
    print("Starting synchronous chunked generation...")
    final_wav_data = generate_audio_bytes_chunked(long_text, lang = 'ru')

    if final_wav_data:
        print(f"Successfully generated WAV data, size: {len(final_wav_data)} bytes.")
        try:
            output_filename = r"c:\Users\user\Downloads\output_audio_long_chunked_book.wav"
            with open(output_filename, "wb") as f:
                f.write(final_wav_data)
            print(f"Saved final WAV to {output_filename}")
        except Exception as e:
            print(f"Error saving final WAV file: {e}")
    else:
        print("Failed to generate WAV data for the long text.")


if __name__ == "__main__":
    my_gemini.load_users_keys()

    test1()
    # test2_read_a_book()
