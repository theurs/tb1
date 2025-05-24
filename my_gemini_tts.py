# https://github.com/google-gemini/cookbook/blob/main/quickstarts/Get_started_TTS.ipynb


import io
import os

from google import genai
from pydub import AudioSegment
from pydub.exceptions import CouldntEncodeError, CouldntDecodeError

import my_gemini
import my_log


# --- Список известных голосов (может меняться, проверяйте документацию Gemini) ---
POSSIBLE_VOICES = [
    'Achernar', 'Achird', 'Algenib', 'Algieba', 'Alnilam', 'Aoede', 'Autonoe',
    'Callirrhoe', 'Charon', 'Despina', 'Enceladus', 'Erinome', 'Fenrir',
    'Gacrux', 'Iapetus', 'Kore', 'Laomedeia', 'Leda', 'Orus', 'Puck',
    'Pulcherrima', 'Rasalgethi', 'Sadachbia', 'Sadaltager', 'Schedar',
    'Sulafat', 'Umbriel', 'Vindemiatrix', 'Zephyr', 'Zubenelgenubi',
]

# --- Список известных моделей TTS (может меняться, проверяйте документацию Gemini) ---
# Модели, которые могут работать с client.models.generate_content для TTS.
# Актуальность следует проверять в документации Google GenAI.
POSSIBLE_MODELS_TTS = [
    "gemini-2.5-flash-preview-tts",
    "gemini-2.5-pro-preview-tts"
]


def generate_tts_ogg_bytes(
    text_to_speak: str,
    voice_name: str = "Zephyr",
    model_id: str = "gemini-2.5-flash-preview-tts",
    lang: str = '',
) -> bytes | None:
    """
    Генерирует аудио из текста с использованием указанного голоса и модели,
    получает сырые PCM (WAV) байты от Gemini API и конвертирует их в OGG Vorbis байты.

    Args:
        text_to_speak: Текст для синтеза речи.
        voice_name: Имя предустановленного голоса Gemini.
            По умолчанию: "Sadaltager".
            Полный список доступных голосов см. в константе POSSIBLE_VOICES
            или актуальной документации Gemini.
        model_id: Идентификатор модели Gemini для TTS.
            По умолчанию: "gemini-1.5-flash-preview-tts".
            Список возможных моделей см. в константе POSSIBLE_MODELS_TTS
            или актуальной документации Gemini.
        lang: Язык текста. Не используется?

    Returns:
        Байты аудио в формате OGG Vorbis или None в случае ошибки.
    """

    text_to_speak = text_to_speak.strip()
    if not text_to_speak:
        return None

    for _ in range(3):
        key = my_gemini.get_next_key()
        if not key:
            my_log.log_gemini("my_gemini_tts: my_gemini_tts: API ключ Gemini не найден")
            return None

        client = genai.Client(api_key=key)

        if voice_name not in POSSIBLE_VOICES:
            my_log.log_gemini(f"my_gemini_tts: Предупреждение: Указанный голос '{voice_name}' отсутствует в списке известных голосов. По умолчанию используется 'Zephyr'")
            voice_name = "Zephyr"
        if model_id not in POSSIBLE_MODELS_TTS:
            my_log.log_gemini(f"my_gemini_tts: Предупреждение: Указанная модель '{model_id}' отсутствует в списке известных моделей. По умолчанию используется 'gemini-2.5-flash-preview-tts'")
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
            break
        except Exception as e:
            my_log.log_gemini(f"my_gemini_tts: Ошибка при вызове API Gemini TTS: {e}")
            return None

    # Извлечение сырых PCM байтов и MIME-типа
    try:
        if not response.candidates:
            my_log.log_gemini("my_gemini_tts: Ошибка API: В ответе нет кандидатов.")
            return None
        candidate = response.candidates[0]
        if not candidate.content or not candidate.content.parts:
            my_log.log_gemini("my_gemini_tts: Ошибка API: В кандидате ответа отсутствует 'content' или 'parts'.")
            return None

        audio_part = candidate.content.parts[0]

        if not audio_part.inline_data:
            my_log.log_gemini("my_gemini_tts: Ошибка API: В части ответа отсутствует 'inline_data'.")
            return None
        if not hasattr(audio_part.inline_data, 'data') or not hasattr(audio_part.inline_data, 'mime_type'):
            my_log.log_gemini("my_gemini_tts: Ошибка API: Объект 'inline_data' не содержит 'data' или 'mime_type'.")
            return None

        pcm_audio_bytes = audio_part.inline_data.data
        mime_type = audio_part.inline_data.mime_type

    except (AttributeError, IndexError) as e:
        my_log.log_gemini(f"Ошибка при разборе ответа API: {e}")
        my_log.log_gemini(f"Полный ответ API для отладки: {response}")
        return None

    # Проверка MIME-типа (API Gemini TTS должен возвращать audio/L16 PCM)
    # и извлечение параметров для pydub
    if 'audio/L16' in mime_type and 'codec=pcm' in mime_type and 'rate=' in mime_type:
        try:
            rate_str = mime_type.split('rate=')[1].split(';')[0]
            frame_rate = int(rate_str)
        except (IndexError, ValueError):
            my_log.log_gemini(
                f"Не удалось извлечь частоту дискретизации из MIME типа: {mime_type}. "
                f"Используем значение по умолчанию 24000 Гц."
            )
            frame_rate = 24000

        num_channels = 1  # TTS обычно моно
        sample_width_bytes = 2  # L16 -> 16 бит = 2 байта

        # Конвертация PCM в OGG с использованием pydub
        try:
            audio_segment = AudioSegment.from_raw(
                io.BytesIO(pcm_audio_bytes),
                sample_width=sample_width_bytes,
                frame_rate=frame_rate,
                channels=num_channels
            )

            ogg_stream = io.BytesIO()
            # Исходный PCM (24kHz, 16bit, mono) = 384 kbps.
            audio_segment.export(ogg_stream, format="ogg", codec="libopus", bitrate="64k")
            ogg_bytes = ogg_stream.getvalue()
            return ogg_bytes

        except CouldntDecodeError as e:
            my_log.log_gemini("my_gemini_tts: Ошибка pydub: Не удалось декодировать сырые PCM данные. Проверьте параметры. {e}")
            return None
        except CouldntEncodeError as e:
            my_log.log_gemini("my_gemini_tts: Ошибка pydub: Не удалось закодировать в OGG. Убедитесь, что ffmpeg/libav установлен и доступен в PATH. {e}")
            return None
        except Exception as e:
            my_log.log_gemini(f"Непредвиденная ошибка при конвертации аудио с pydub: {e}")
            return None
    else:
        my_log.log_gemini(f"my_gemini_tts: Получен неподдерживаемый MIME тип для конвертации в OGG: {mime_type}. Ожидался 'audio/L16;codec=pcm;rate=...'. Байты не будут конвертированы.")
        return None


if __name__ == "__main__":
    output_dir = r"c:\Users\user\Downloads"

    text_for_tts_1 = "Привет, мир! Это тестовое сообщение для синтеза речи."
    ogg_audio_data_1 = generate_tts_ogg_bytes(
        text_to_speak=text_for_tts_1,
        voice_name="Zephyr", # Явно указываем голос
    )

    if ogg_audio_data_1:
        output_ogg_filename_1 = os.path.join(output_dir, "gemini_tts_output_1.ogg")
        with open(output_ogg_filename_1, "wb") as f:
            f.write(ogg_audio_data_1)

    text_for_tts_2 = """— Хочешь посидеть у меня на коленях и попросить что-нибудь на Рождество? — Нет, спасибо. Не хочу потом по венерологам бегать."""
    # Используем значения по умолчанию для голоса и модели
    ogg_audio_data_2 = generate_tts_ogg_bytes(text_to_speak=text_for_tts_2)

    if ogg_audio_data_2:
        output_ogg_filename_2 = os.path.join(output_dir, "gemini_tts_output_2_default_voice_model.ogg")
        with open(output_ogg_filename_2, "wb") as f:
            f.write(ogg_audio_data_2)
