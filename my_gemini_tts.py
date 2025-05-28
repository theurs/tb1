# https://github.com/google-gemini/cookbook/blob/main/quickstarts/Get_started_TTS.ipynb

import io
import os
import time

from google import genai
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

    # что то он перестал нормально работать, пока что будет только мелкие озвучивать
    if len(text_to_speak) > 2000:
        return None

    # Если текст слишком длинный, разбиваем на чанки и используем параллельную обработку
    if len(text_to_speak) > 2500:
        chunks = utils.split_text(text_to_speak, 2500)
        return tts_chunked_text(chunks=chunks, voice_name=voice_name, model=model_id, lang=lang)

    response = None

    # Цикл для повторных попыток вызова API
    for _ in range(3):
        key = my_gemini.get_next_key()
        if not key:
            my_log.log_gemini("my_gemini_tts:generate_tts_wav_bytes:1: API ключ Gemini не найден")
            return None

        client = genai.Client(api_key=key)

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
            my_log.log_gemini(f"my_gemini_tts:generate_tts_wav_bytes:4: Ошибка при вызове API Gemini TTS: {e}")
            time.sleep(1) # Небольшая задержка перед следующей попыткой

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
@utils.async_run_with_limit(max_threads=5) # Ограничиваем до 5 одновременных потоков
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


if __name__ == "__main__":
    # Инициализация для запуска примера
    my_gemini.my_db.init(backup=False)
    my_gemini.load_users_keys()

    output_dir = r"c:\Users\user\Downloads"

    with open(r'C:\Users\user\Downloads\samples for ai\большая книга только первая глава.txt', 'r', encoding='utf-8') as f:
        text = f.read()

    # Вызываем generate_tts_wav_bytes, которая сама решит, вызывать ли tts_chunked_text
    data = generate_tts_wav_bytes(text_to_speak=text, voice_name="Leda")

    if data:
        output_ogg_filename = os.path.join(output_dir, "gemini_tts_output_parallel.wav")
        with open(output_ogg_filename, "wb") as f:
            f.write(data)
        print(f"Аудио сохранено в {output_ogg_filename}")
    else:
        print("Не удалось сгенерировать аудио.")
