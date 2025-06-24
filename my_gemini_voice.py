import asyncio
import json
import os
import io
import time
import traceback

from google import genai
from google.genai import types
from google.genai.types import (
    Content,
    Part
)
from pydub import AudioSegment

import my_gemini
import my_log
import utils


# DEFAULT_MODEL = "gemini-2.0-flash-live-001"
DEFAULT_MODEL = 'gemini-live-2.5-flash-preview'
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
    text = text.replace("--", "—").replace('-', '—')

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


async def generate_audio_bytes_chunked(
    text: str,
    chunk_limit: int = 2000,
    lang: str = "ru",
    voice: str = "Zephyr",
    model: str = "gemini-2.0-flash-live-001",
    sample_rate: int = 24000,
    sample_width: int = 2,
    channels: int = 1,
    max_concurrent_tasks: int = 3
) -> bytes | None:
    """
    Asynchronously generates audio for potentially long text by chunking,
    concatenates the raw audio, and returns WAV file bytes.
    Handles text longer than chunk_limit by splitting it and processing chunks concurrently
    while limiting the number of parallel tasks using asyncio.Semaphore.
    Runs the asynchronous generate_audio_bytes for each chunk with retry logic.
    Concatenates raw PCM audio bytes from chunks and saves as WAV file as bytes.

    Args:
        text (str): The text to synthesize. Can be very long.
        chunk_limit (int, optional): Maximum character length per chunk for the API.
                                     Defaults to 2000.
        lang (str, optional): Language for pronunciation guidance. Defaults to "ru".
        voice (str, optional): The voice to use for synthesis. Defaults to "Zephyr".
        model (str, optional): The generative model to use. Defaults to "gemini-2.0-flash-live-001".
        sample_rate (int, optional): The sample rate expected for the raw audio
                                     before conversion. Defaults to 24000.
        sample_width (int, optional): The sample width (bytes) expected for the raw
                                      audio. Defaults to 2 (for 16-bit).
        channels (int, optional): The number of channels expected for the raw audio.
                                  Defaults to 1 (mono).
        max_concurrent_tasks (int, optional): The maximum number of concurrent
                                              generate_audio_bytes calls. Defaults to 3.

    Returns:
        bytes | None: A bytes object containing the WAV file audio for the
                      entire text if successful, or None if any step fails.
    """

    if not text:
        print("Input text is empty, returning None.")
        return None

    # Использование семафора для ограничения количества одновременно выполняемых асинхронных операций
    semaphore = asyncio.Semaphore(max_concurrent_tasks)
    all_raw_audio_bytes = bytearray()

    chunks = utils.split_text(text, chunk_limit=chunk_limit)

    async def generate_chunk_audio(chunk: str, chunk_num: int) -> bytes:
        """
        Вспомогательная корутина для генерации аудио для одного чанка с использованием семафора
        и логики повторных попыток.
        """
        async with semaphore: # Захватываем семафор, чтобы ограничить параллелизм
            raw_chunk_bytes = b''
            # Логика повторных попыток: 1 изначальная + 2 повтора = 3 попытки всего
            for attempt in range(3):
                try:
                    # `generate_audio_bytes` - это асинхронная функция, которая должна быть доступна
                    raw_chunk_bytes = await generate_audio_bytes(
                        text=chunk,
                        lang=lang,
                        voice=voice,
                        model=model
                    )
                    if raw_chunk_bytes:
                        return raw_chunk_bytes # Успешно получено аудио, возвращаем его
                    
                    # Если raw_chunk_bytes пуст, это означает, что генерация не удалась или ничего не вернула
                    print(f"Chunk {chunk_num}, attempt {attempt+1}: No audio data received. Retrying in 5 seconds...")
                except Exception as e:
                    # Перехватываем любые исключения во время вызова API
                    print(f"Chunk {chunk_num}, attempt {attempt+1}: Error during generation: {e}. Retrying in 5 seconds...")
                
                if attempt < 2: # Задержка только если это не последняя попытка
                    await asyncio.sleep(5)
            
            # Если мы дошли до сюда, все попытки для этого чанка провалились
            print(f"Chunk {chunk_num} failed to generate raw audio after all attempts.")
            return b''

    # Создаем список задач (корутин) для каждого чанка
    tasks = [generate_chunk_audio(chunk, i + 1) for i, chunk in enumerate(chunks)]

    # Запускаем все задачи конкурентно, соблюдая ограничение семафора
    # `return_exceptions=True` позволяет всем задачам завершиться, даже если некоторые из них выдают исключения,
    # и исключения возвращаются как объекты в списке результатов.
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Обрабатываем результаты и конкатенируем аудио
    for i, res in enumerate(results):
        if isinstance(res, Exception):
            # Это может произойти, если generate_chunk_audio не обработает внутреннее исключение
            print(f"Critical error processing chunk {i+1}: {res}")
        elif res: # Если res является байтами (и не пустыми байтами от неудачных попыток)
            all_raw_audio_bytes.extend(res)

    if not all_raw_audio_bytes:
        print("No raw audio data was collected after processing all chunks.")
        return None

    # Постобработка: сохранение чанков в WAV-файл в памяти как байты с использованием pydub
    try:
        stream = io.BytesIO()
        # Убедитесь, что AudioSegment правильно импортирован/доступен (например, `from pydub import AudioSegment`)
        AudioSegment(all_raw_audio_bytes, frame_rate=sample_rate, sample_width=sample_width, channels=channels).export(stream, format="wav")
        return stream.getvalue()
    except Exception as e:
        print(f"Error during final conversion to WAV: {e}")
        return None


def generate_audio_bytes_chunked_sync(
    text: str,
    chunk_limit: int = 2000,
    lang: str = "ru",
    voice: str = "Puck",
    model: str = "gemini-2.0-flash-live-001",
    sample_rate: int = 24000,
    sample_width: int = 2,
    channels: int = 1,
    max_concurrent_tasks: int = 3
) -> bytes | None:
    """
    Синхронная обертка для асинхронной функции generate_audio_bytes_chunked.
    Позволяет вызывать асинхронную функцию из синхронного контекста.

    Args:
        text (str): Текст для синтеза.
        chunk_limit (int, optional): Максимальная длина чанка. По умолчанию 2000.
        lang (str, optional): Язык для произношения. По умолчанию "ru".
        voice (str, optional): Голос для синтеза. По умолчанию "Puck".
        model (str, optional): Генеративная модель. По умолчанию "gemini-2.0-flash-live-001".
        sample_rate (int, optional): Частота дискретизации аудио. По умолчанию 24000.
        sample_width (int, optional): Ширина сэмпла (байты). По умолчанию 2.
        channels (int, optional): Количество каналов. По умолчанию 1.
        max_concurrent_tasks (int, optional): Максимальное количество параллельных задач. По умолчанию 3.

    Returns:
        bytes | None: Байтовый объект, содержащий WAV-файл аудио, или None в случае ошибки.
    """
    try:
        # Используем asyncio.run() для выполнения асинхронной функции
        # в новом цикле событий. Это блокирует текущий поток до завершения
        # асинхронной операции.
        return asyncio.run(
            generate_audio_bytes_chunked(
                text=text,
                chunk_limit=chunk_limit,
                lang=lang,
                voice=voice,
                model=model,
                sample_rate=sample_rate,
                sample_width=sample_width,
                channels=channels,
                max_concurrent_tasks=max_concurrent_tasks
            )
        )
    except RuntimeError as e:
        # Это исключение может возникнуть, если asyncio.run() вызывается из уже
        # запущенного цикла событий (например, если обертка вызывается внутри другой
        # асинхронной функции без proper `await`).
        print(f"RuntimeError in generate_audio_bytes_chunked_sync: {e}")
        print("This might happen if called from an already running asyncio event loop.")
        return None
    except Exception as e:
        print(f"An unexpected error occurred in generate_audio_bytes_chunked_sync: {e}")
        # print(traceback.format_exc()) # Для отладки
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
         - Слушаю, Повелитель! 
         - Данаан, ситуация изменилась. Похоже, данные о Гасителе проникли дальше, чем мы подозревали - на уровень Великого Кристалла. А значит - за ним уже началась охота. 
         - Кто? 
         - Мало ли во Вселенной тех, кому нужна власть. Но наша разведка донесла, что наиболее вероятная кандидатура "охотника" - Феррис. Он же Феликс Антуан Полоз. Он же Кощей Бессмертный. Он же Игрок и Наблюдатель. Пиф  уже сброшен тебе. Будь осторожен, Данаан... 
Связь прервалась. 
          Тем временем с борта космической станции Вейдера стартовали ещё несколько разведчиков, но уже пилотируемых, а группа SG-1 вышла к селению.
"""

    # final_wav_data = generate_audio_bytes_chunked(long_text, lang = 'en')
    final_wav_data = generate_audio_bytes_chunked_sync(long_text, lang = 'ru')

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
    final_wav_data = generate_audio_bytes_chunked_sync(long_text, lang = 'ru')

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


def test2_read_a_book_():
    """
    Reads a JSON file containing text chunks, converts each chunk to audio using TTS,
    and saves the audio as WAV files in a structured directory.
    It skips chunks that have already been processed and saved.
    Assumes `generate_audio_bytes_chunked_sync` function is available in the scope.
    """
    # Configuration
    json_input_path = r"C:\Users\user\Downloads\samples for ai\myachev_Significant_Digits_processed_by_sections.json"

    # Extract a meaningful name for the output directory from the JSON filename
    # E.g., 'myachev_Significant_Digits_processed_by_sections' from the full path
    base_filename_without_ext = os.path.splitext(os.path.basename(json_input_path))[0]

    output_base_dir = r"C:\Users\user\Downloads"
    output_book_dir = os.path.join(output_base_dir, f"book_{base_filename_without_ext}")

    # Create the output directory if it doesn't exist
    try:
        os.makedirs(output_book_dir, exist_ok=True)
        print(f"Каталог для сохранения аудио: '{output_book_dir}' (создан/проверен).")
    except OSError as e:
        print(f"Ошибка при создании каталога '{output_book_dir}': {e}")
        return

    all_tts_chunks = []
    try:
        with open(json_input_path, 'r', encoding='utf-8') as f:
            all_tts_chunks = json.load(f)
        print(f"Загружено {len(all_tts_chunks)} частей из файла '{json_input_path}'.")
    except FileNotFoundError:
        print(f"Ошибка: Файл JSON не найден по пути '{json_input_path}'.")
        return
    except json.JSONDecodeError:
        print(f"Ошибка: Не удалось декодировать JSON из файла '{json_input_path}'. Проверьте формат файла.")
        return
    except Exception as e:
        print(f"Произошла непредвиденная ошибка при чтении файла JSON: {e}")
        return

    processed_count = 0
    skipped_count = 0
    failed_count = 0
    section_markers_count = 0
    total_chunks = len(all_tts_chunks)

    print("\nНачинаю генерацию TTS для частей...")
    for i, chunk_text in enumerate(all_tts_chunks):
        # Format filename with leading zeros for proper sorting
        chunk_filename = f"chunk_{i:04d}.wav"
        output_filepath = os.path.join(output_book_dir, chunk_filename)

        # Check for special section markers from the first script
        if chunk_text.startswith("<<<РАЗДЕЛ_") and chunk_text.endswith("_КНИГИ>>>"):
            print(f"[{i+1}/{total_chunks}] Обнаружен маркер раздела: '{chunk_text}'. Пропускаю генерацию аудио для маркера.")
            section_markers_count += 1
            # You might consider creating an empty WAV or a short silence for these markers
            # For now, we just skip audio generation for the marker text itself.
            continue

        # Check if the file already exists and is not zero size
        if os.path.exists(output_filepath) and os.path.getsize(output_filepath) > 0:
            print(f"[{i+1}/{total_chunks}] Пропускаю '{chunk_filename}' - файл уже существует и не пуст.")
            skipped_count += 1
            continue
        # If the file exists but is zero size, it will not be skipped and will be re-processed.
        # If the file does not exist, it will also not be skipped and will be processed.

        print(f"[{i+1}/{total_chunks}] Обрабатываю часть (длина: {len(chunk_text)} символов): '{chunk_text[:70]}...'")

        # Call the external TTS function.
        # `generate_audio_bytes_chunked_sync` is assumed to be available in the global scope.
        try:
            final_wav_data = generate_audio_bytes_chunked_sync(chunk_text, lang='ru')

            if final_wav_data:
                try:
                    with open(output_filepath, "wb") as f:
                        f.write(final_wav_data)
                    print(f"  Сохранено в '{output_filepath}'")
                    processed_count += 1
                except Exception as e:
                    print(f"  Ошибка при сохранении WAV файла '{output_filepath}': {e}")
                    failed_count += 1
            else:
                print(f"  Не удалось сгенерировать данные WAV для части {i+1}.")
                failed_count += 1
        except Exception as e:
            print(f"  Произошла ошибка во время генерации TTS для части {i+1}: {e}")
            failed_count += 1

    print("\n--- Сводка по процессу TTS ---")
    print(f"Всего частей в файле JSON: {total_chunks}")
    print(f"Успешно обработано и сохранено: {processed_count}")
    print(f"Пропущено (файлы уже существуют): {skipped_count}")
    print(f"Пропущено (маркеры разделов): {section_markers_count}")
    print(f"Не удалось обработать: {failed_count}")


if __name__ == "__main__":
    my_gemini.load_users_keys()

    test1()
    # test2_read_a_book_()
