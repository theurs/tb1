# https://github.com/google-gemini/cookbook/blob/main/quickstarts/Get_started_TTS.ipynb

import io
import json
import os
import time
import unicodedata

from google import genai
from google.genai.types import (
    HttpOptions,
)
from pydub import AudioSegment

import my_gemini
import my_log
import utils


# --- Список известных голосов (может меняться, проверяйте документацию Gemini) ---
POSSIBLE_VOICES = [
    'Achernar', 'Achird', 'Algenib', 'Algieba', 'Alnilam', 'Aoede', 'Autonoe',
    'Callirrhoe', 'Charon', 'Despina', 'Enceladus', 'Erinome', 'Fenrir',
    'Gacrux', 'Iapetus', 'Kore', 'Laomedeia', 'Leda', 'Orus', 'Puck',
    'Pulcherrima', 'Rasalgethi', 'Sadachbia', 'Sadaltager', 'Schedar',
    'Sulafat', 'Umbriel', 'Vindemiatrix', 'Zephyr', 'Zubenelgenubi',
]

# --- Список известных моделей TTS (может меняться, проверяйте документацию Gemini) ---
POSSIBLE_MODELS_TTS = [
    "gemini-2.5-flash-preview-tts",
    "gemini-2.5-pro-preview-tts"
]


def visual_len(text: str) -> int:
    """
    Вычисляет 'визуальную' длину строки, считая базовые символы
    с последующими комбинирующими Unicode знаками (например, ударениями)
    как один логический символ.

    Args:
        text (str): Входная строка.

    Returns:
        int: Визуальная длина строки.
    """
    length = 0
    for char in text:
        # Проверяем, является ли символ НЕ комбинирующим знаком.
        # Комбинирующие знаки (например, ударения) имеют категорию,
        # начинающуюся с 'M' (Mark: Mn, Me, Mc).
        if unicodedata.category(char)[0] != 'M':
            length += 1
    return length


def generate_tts_wav_bytes(
    text_to_speak: str,
    voice_name: str = "Zephyr",
    model_id: str = "gemini-2.5-flash-preview-tts",
    lang: str = '',
    raw: bool = False,
) -> bytes | None:
    """
    Генерирует аудио из текста с использованием указанного голоса и модели,
    получает сырые PCM (WAV) байты от Gemini API и возвращает WAV байты или сырые байты.
    Для длинных текстов использует tts_chunked_text для автоматического разбиения и параллелизации.
    
    Args:
        text_to_speak: Текст, который нужно преобразовать в аудио.
        voice_name: Имя голоса, который нужно использовать (по умолчанию "Zephyr").
        model_id: Идентификатор модели, которая будет использоваться (по умолчанию "gemini-2.5-flash-preview-tts").
        lang: Язык текста. По умолчанию ''.
        raw: Флаг, указывающий, нужно ли возвращать сырые байты (по умолчанию False).
    """
    text_to_speak = text_to_speak.strip()
    if not text_to_speak:
        return None

    # # что то он перестал нормально работать, пока что будет только мелкие озвучивать
    # if len(text_to_speak) > 2000:
    #     return None

    # Если текст слишком длинный, разбиваем на чанки и используем параллельную обработку
    if visual_len(text_to_speak) > 1500:
        chunks = utils.split_text(text_to_speak, 1500)
        return tts_chunked_text(chunks=chunks, voice_name=voice_name, model=model_id, lang=lang)

    response = None

    # Цикл для повторных попыток вызова API
    for _ in range(3):
        key = my_gemini.get_next_key()
        if not key:
            my_log.log_gemini("my_gemini_tts:generate_tts_wav_bytes:1: API ключ Gemini не найден")
            return None

        client = genai.Client(api_key=key, http_options=HttpOptions(timeout=180*1000))

        if voice_name not in POSSIBLE_VOICES:
            my_log.log_gemini(f"my_gemini_tts:generate_tts_wav_bytes:2: Предупреждение: Указанный голос '{voice_name}' отсутствует в списке известных голосов. По умолчанию используется 'Zephyr'")
            voice_name = "Zephyr"
        if model_id not in POSSIBLE_MODELS_TTS:
            my_log.log_gemini(f"my_gemini_tts:generate_tts_wav_bytes:3: Предупреждение: Указанная модель '{model_id}' отсутствует в списке известных моделей. По умолчанию используется 'gemini-2.5-flash-preview-tts'")
            model_id = "gemini-2.5-flash-preview-tts"

        try:
            response = client.models.generate_content(
                model=model_id,
                contents=text_to_speak,
                config={
                    "response_modalities": ['Audio'],
                    "speech_config": {
                        "voice_config": {
                            "prebuilt_voice_config": {
                                "voice_name": voice_name
                            }
                        }
                    }
                },
            )
            break # Успешный вызов, выходим из цикла повторных попыток
        except Exception as e:
            if 'timeout' in str(e).lower():
                my_log.log_gemini(f"my_gemini_tts:generate_tts_wav_bytes:4: Timeout {e}")
                return None
            my_log.log_gemini(f"my_gemini_tts:generate_tts_wav_bytes:5: Ошибка при вызове API Gemini TTS: {e}")
            time.sleep(3) # Небольшая задержка перед следующей попыткой

    if response is None: # Если все попытки не увенчались успехом
        return None

    # Извлечение сырых PCM байтов и MIME-типа
    try:
        if not response.candidates:
            my_log.log_gemini("my_gemini_tts:generate_tts_wav_bytes:5: Ошибка API: В ответе нет кандидатов.")
            return None
        candidate = response.candidates[0]
        if not candidate.content or not candidate.content.parts:
            my_log.log_gemini("my_gemini_tts:generate_tts_wav_bytes:6: Ошибка API: В кандидате ответа отсутствует 'content' или 'parts'.")
            return None

        audio_part = candidate.content.parts[0]

        if not audio_part.inline_data:
            my_log.log_gemini("my_gemini_tts:generate_tts_wav_bytes:7: Ошибка API: В части ответа отсутствует 'inline_data'.")
            return None
        if not hasattr(audio_part.inline_data, 'data') or not hasattr(audio_part.inline_data, 'mime_type'):
            my_log.log_gemini("my_gemini_tts:generate_tts_wav_bytes:8: Ошибка API: Объект 'inline_data' не содержит 'data' или 'mime_type'.")
            return None

        pcm_audio_bytes = audio_part.inline_data.data

    except Exception as e:
        my_log.log_gemini(f"my_gemini_tts:generate_tts_wav_bytes:9: Ошибка при разборе ответа API: {e}")
        my_log.log_gemini(f"my_gemini_tts:generate_tts_wav_bytes:10: Полный ответ API для отладки: {response}")
        return None

    # Добираемся до mime_type
    if response.candidates and response.candidates[0].content.parts and \
       response.candidates[0].content.parts[0].inline_data:
        actual_mime_type = response.candidates[0].content.parts[0].inline_data.mime_type
        if actual_mime_type != "audio/L16;codec=pcm;rate=24000":
            my_log.log_gemini(f"my_gemini_tts:generate_tts_wav_bytes:11: Ошибка API: Ожидался mime_type 'audio/L16;codec=pcm;rate=24000', получен '{actual_mime_type}'.")

    if pcm_audio_bytes:
        if raw:
            return pcm_audio_bytes
        # save as .wave bytes using pydub mime_type='audio/L16;codec=pcm;rate=24000'
        audio_segment = AudioSegment(
            data=pcm_audio_bytes,
            sample_width=2,    # Assuming 16-bit PCM
            frame_rate=24000,  # Assuming a sample rate of 24kHz
            channels=1         # Assuming mono audio
        )
        wav_io = io.BytesIO()
        audio_segment.export(wav_io, format="wav")
        wav_bytes = wav_io.getvalue()
        return wav_bytes
    else:
        return None


# Вспомогательная функция, которая будет выполнять синтез для одного чанка
# Она будет декорирована для параллельного выполнения
@utils.async_run_with_limit(max_threads=1)
def _process_single_chunk(
    chunk_index: int,
    chunk_text: str,
    voice_name: str,
    model: str,
    lang: str,
    results_list: list # Передаем список для записи результатов
):
    """
    Обрабатывает один текстовый фрагмент, генерирует аудио и сохраняет его в общий список.
    """
    # Добавляем инструкцию для чтеца только к первому фрагменту (или каждому, если это необходимо по контексту)
    # Здесь добавляем к каждому, т.к. каждый чанк обрабатывается независимо.
    # Если инструкция должна быть только для первого, то это должна быть отдельная логика.
    # Для целей параллелизации добавляем к каждому фрагменту.
    # text_with_instruction = f'читай фрагмент книги на языке [{lang}] ровным спокойным голосом профессионального чтеца\n\n{chunk_text}'
    text_with_instruction = chunk_text

    if not chunk_text.strip():
        # my_log.log_gemini(f"my_gemini_tts:_process_single_chunk:0: Пустой текст для фрагмента {chunk_index}. Фрагмент будет пропущен.")
        return

    wav_bytes = generate_tts_wav_bytes(
        text_to_speak=text_with_instruction,
        voice_name=voice_name,
        model_id=model,
        lang=lang,
        raw = True,
    )

    if not wav_bytes:
        my_log.log_gemini(f"my_gemini_tts:_process_single_chunk:1: Не удалось сгенерировать аудио для фрагмента {chunk_index}, повторная попытка...")
        time.sleep(5) # Ждем перед повторной попыткой
        wav_bytes = generate_tts_wav_bytes(
            text_to_speak=text_with_instruction,
            voice_name=voice_name,
            model_id=model,
            lang=lang,
            raw = True,
        )
        if not wav_bytes:
            my_log.log_gemini(f"my_gemini_tts:_process_single_chunk:2: Повторная попытка для фрагмента {chunk_index} также не удалась. Фрагмент будет пропущен.")
            # return None # Возвращаем None, если совсем не получилось.
            # Вместо возврата, сохраняем None в списке, чтобы сохранить порядок
            results_list[chunk_index] = None
            return

    # Сохраняем результат по его индексу в общем списке
    results_list[chunk_index] = wav_bytes


def tts_chunked_text(
    chunks: list[str],
    voice_name: str = "Iapetus",
    lang: str = 'ru',
    model: str = 'gemini-2.5-flash-preview-tts'
    ) -> bytes | None:
    '''
    Синтезирует речь для каждого чанка текста параллельно и склеивает в 1 большой Wav файл.

    Args:
        chunks: Список текстовых чанков для синтеза.
        voice_name: Имя голоса Gemini для синтеза. По умолчанию "Iapetus".
        lang: Язык текста. По умолчанию 'ru'.
        model: Модель TTS. По умолчанию "gemini-2.5-flash-preview-tts".
    '''
    # Инициализируем список для хранения результатов с размером, равным количеству чанков.
    # Это позволяет каждому потоку записывать результат по своему индексу без конфликтов.
    results = [None] * len(chunks)
    threads = []

    for i, chunk in enumerate(chunks):
        # Запускаем _process_single_chunk в отдельном потоке, используя декоратор
        # Декоратор _process_single_chunk возвращает объект потока.
        thread = _process_single_chunk(i, chunk, voice_name, model, lang, results)
        threads.append(thread)

    # Ожидаем завершения всех потоков
    for thread in threads:
        if thread: # Убеждаемся, что поток был создан (декоратор может вернуть None или другой объект)
            thread.join()

    sound_result = AudioSegment.empty()

    # Собираем аудио из результатов, сохраняя порядок
    for i, wav_bytes in enumerate(results):
        if wav_bytes:
            try:
                sound = AudioSegment.from_raw(
                    io.BytesIO(wav_bytes),
                    frame_rate=24000,
                    channels=1,
                    sample_width=2,
                    format="s16le",
                )
                sound_result += sound
            except Exception as e:
                my_log.log_gemini(f"my_gemini_tts:tts_chunked_text:1: Ошибка при обработке аудиофрагмента {i}: {e}. Фрагмент будет пропущен.")
        else:
            my_log.log_gemini(f"my_gemini_tts:tts_chunked_text:2: Фрагмент {i} не был сгенерирован или не содержит аудиоданных.")
            # Можно добавить короткий фрагмент тишины вместо пропущенного куска
            # sound_result += AudioSegment.silent(duration=500) # 0.5 секунды тишины

    if not sound_result:
        my_log.log_gemini("my_gemini_tts:tts_chunked_text:3: Все фрагменты были пропущены или не удалось сгенерировать аудио.")
        return None

    wav_io = io.BytesIO()
    sound_result.export(wav_io, format="wav")
    wav_bytes = wav_io.getvalue()
    return wav_bytes


# def tts_chunked_text_to_files(chunks: list[str], output_dir: str, voice_name: str = "Iapetus") -> None:
#     '''
#     Синтезирует речь для каждого чанка текста и сохраняет результаты в отдельные
#     wav-файлы в указанной папке. Пропускает генерацию, если файл уже существует
#     и имеет ненулевой размер.

#     Args:
#         chunks: Список текстовых чанков для синтеза.
#         output_dir: Путь к папке, куда будут сохраняться файлы (например, "c:/output/audio/").
#         voice_name: Имя голоса Gemini для синтеза. По умолчанию "Iapetus".
#     '''

#     for i, chunk in enumerate(chunks):
#         # Файлы будут названы 0001.wav, 0002.wav и т.д.
#         file_name = os.path.join(output_dir, f"{i+1:04d}.wav")

#         if os.path.exists(file_name) and os.path.getsize(file_name) > 0:
#             # my_log.log_gemini(f"Файл для чанка {i+1} уже существует и не пуст '{file_name}', пропуск генерации.")
#             continue # Пропустить текущий чанк, если файл уже есть и имеет ненулевой размер

#         # my_log.log_gemini(f"Обработка чанка {i+1} и сохранение в {file_name}")

#         wav_bytes = generate_tts_wav_bytes(text_to_speak=f'читай фрагмент книги на русском языке ровным спокойным голосом профессионального чтеца\n\n{chunk}', voice_name=voice_name)

#         if wav_bytes:
#             try:
#                 with open(file_name, "wb") as f:
#                     f.write(wav_bytes)
#                 # my_log.log_gemini(f"Чанк {i+1} успешно сохранен: {file_name}")
#             except IOError as e:
#                 my_log.log_gemini(f"Ошибка при записи файла '{file_name}': {e}")
#         else:
#             my_log.log_gemini(f"Не удалось сгенерировать аудио для чанка {i+1}: '{chunk[:50]}...'")


def replace_plus_with_unicode_accents(text: str) -> str:
    """
    Заменяет знак '+' перед ударной гласной на юникодный знак ударения.
    Поддерживает русские и английские гласные.

    Args:
        text (str): Исходный текст с ударениями, обозначенными знаком '+'
                    перед ударной гласной (например, "прив+ет").

    Returns:
        str: Текст, где '+' и следующая за ней гласная заменены на
             соответствующую юникодную букву под ударением.
    """
    # Карта соответствия гласных с ударением
    ACCENT_MAP = {
        # Русские строчные
        'а': 'а́', 'е': 'е́', 'и': 'и́', 'о': 'о́', 'у': 'у́',
        'ы': 'ы́', 'э': 'э́', 'ю': 'ю́', 'я': 'я́',
        # Русские заглавные
        'А': 'А́', 'Е': 'Е́', 'И': 'И́', 'О': 'О́', 'У': 'У́',
        'Ы': 'Ы́', 'Э': 'Э́', 'Ю': 'Ю́', 'Я': 'Я́',
        # Английские строчные (для общих случаев или заимствований)
        'a': 'á', 'e': 'é', 'i': 'í', 'o': 'ó', 'u': 'ú', 'y': 'ý',
        # Английские заглавные
        'A': 'Á', 'E': 'É', 'I': 'Í', 'O': 'Ó', 'U': 'Ú', 'Y': 'Ý',
    }

    result_chars = []
    i = 0
    while i < len(text):
        if text[i] == '+':
            # Проверяем, есть ли следующий символ и является ли он гласной из нашей карты
            if i + 1 < len(text) and text[i+1] in ACCENT_MAP:
                # Если да, добавляем ударную гласную и пропускаем '+' и саму гласную
                result_chars.append(ACCENT_MAP[text[i+1]])
                i += 2
            else:
                # Если '+' не перед ударной гласной, оставляем как есть
                result_chars.append(text[i])
                i += 1
        else:
            # Если это не '+', просто добавляем символ
            result_chars.append(text[i])
            i += 1
    return "".join(result_chars)


def process_chunks_for_tts(json_file_path: str, base_output_dir: str, book_name: str) -> None:
    """
    Reads text chunks from a JSON file, synthesizes speech for each chunk
    using a placeholder TTS function, and saves the audio as WAV files.
    Skips chunks for which a non-empty WAV file already exists.

    Args:
        json_file_path: Path to the JSON file containing the list of text chunks.
        base_output_dir: The base directory for saving audio files (e.g., "downloads").
        book_name: The name of the book, used to create a subdirectory
                   within the base output directory (e.g., "книгаХХХ").
    """
    # Construct the full output directory path
    output_dir = os.path.join(base_output_dir, book_name)

    # Create the output directory if it doesn't exist
    try:
        os.makedirs(output_dir, exist_ok=True)
        print(f"Output directory ensured: '{output_dir}'")
    except OSError as e:
        print(f"Error creating output directory '{output_dir}': {e}")
        return

    # Load chunks from the JSON file
    chunks = []
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            chunks = json.load(f)
        chunks = [x for x in chunks if 'РАЗД+ЕЛ' not in x and 'КН+ИГИ' not in x and len(x)>30]
        print(f"Successfully loaded {len(chunks)} chunks from '{json_file_path}'.")
    except FileNotFoundError:
        print(f"Error: JSON file not found at '{json_file_path}'.")
        return
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from '{json_file_path}'.")
        return
    except Exception as e:
        print(f"An error occurred while reading JSON: {e}")
        return

    # Initialize statistics counters
    total_chunks = len(chunks)
    processed_count = 0
    skipped_count = 0
    failed_count = 0

    print("\n--- Starting TTS processing ---")
    print(f"Total chunks to process: {total_chunks}")

    # Process each chunk
    for i, chunk in enumerate(chunks):
        # Construct the desired output filename
        file_name = os.path.join(output_dir, f"{i+1:04d}.wav")

        # Check if the file already exists and is not empty
        if os.path.exists(file_name) and os.path.getsize(file_name) > 0:
            print(f"Chunk {i+1}/{total_chunks}: File already exists and is not empty, skipping generation: '{file_name}'")
            skipped_count += 1
            continue # Skip to the next chunk

        print(f"Chunk {i+1}/{total_chunks}: Processing and saving to '{file_name}'")

        # --- Call the placeholder TTS generation function ---
        # Replace this with your actual call to a TTS API that returns WAV bytes.
        # The available `tts` tool *sends* audio, it does not return bytes
        # to be saved locally, so it cannot be used directly here.
        wav_bytes = generate_tts_wav_bytes(
            text_to_speak=f'читай фрагмент книги на русском языке ровным спокойным голосом профессионального чтеца\n\n{replace_plus_with_unicode_accents(chunk)}',
            voice_name="Iapetus" # Use the specified voice
        )
        # ----------------------------------------------------

        if wav_bytes:
            try:
                # Save the generated WAV bytes to the file
                with open(file_name, "wb") as f:
                    f.write(wav_bytes)
                print(f"Chunk {i+1}/{total_chunks} successfully saved: {file_name}")
                processed_count += 1
            except IOError as e:
                print(f"Error writing file '{file_name}': {e}")
                failed_count += 1
        else:
            print(f"Failed to generate audio for chunk {i+1}/{total_chunks}. Placeholder returned None.")
            failed_count += 1

    # Print summary statistics
    print("\n--- TTS Processing Summary ---")
    print(f"Total chunks considered: {total_chunks}")
    print(f"Chunks processed and saved: {processed_count}")
    print(f"Chunks skipped (file existed): {skipped_count}")
    print(f"Chunks failed to process: {failed_count}")
    print("----------------------------")


if __name__ == "__main__":
    # Инициализация для запуска примера
    my_gemini.my_db.init(backup=False)
    my_gemini.load_users_keys()

    json_input_path = r"C:\Users\user\Downloads\samples for ai\myachev_Significant_Digits_processed_by_sections_accents.json"
    base_download_directory = r"C:\Users\user\Downloads"
    book_subdirectory_name = "книга Значимые Цифры" # Example book name

    process_chunks_for_tts(json_input_path, base_download_directory, book_subdirectory_name)