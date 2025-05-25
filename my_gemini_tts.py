# https://github.com/google-gemini/cookbook/blob/main/quickstarts/Get_started_TTS.ipynb


import io
import os

from google import genai
from pydub import AudioSegment

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


def generate_tts_wav_bytes(
    text_to_speak: str,
    voice_name: str = "Zephyr",
    model_id: str = "gemini-2.5-flash-preview-tts",
    lang: str = '',
) -> bytes | None:
    """
    Генерирует аудио из текста с использованием указанного голоса и модели,
    получает сырые PCM (WAV) байты от Gemini API и возвращает байты.

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
        Байты аудио в формате Wav или None в случае ошибки.
    """

    text_to_speak = text_to_speak.strip()
    if not text_to_speak:
        return None

    response = None

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

    except Exception as e:
        my_log.log_gemini(f"Ошибка при разборе ответа API: {e}")
        my_log.log_gemini(f"Полный ответ API для отладки: {response}")
        return None

    if pcm_audio_bytes:
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


if __name__ == "__main__":
    output_dir = r"c:\Users\user\Downloads"

    text_for_tts_1 = "Привет, мир! Это тестовое сообщение для синтеза речи."
    audio_data = generate_tts_wav_bytes(
        text_to_speak=text_for_tts_1,
        voice_name="Zephyr", # Явно указываем голос
    )

    if audio_data:
        output_ogg_filename = os.path.join(output_dir, "gemini_tts_output.wav")
        with open('c:/Users/user/Downloads/1.wav', "wb") as f:
            f.write(audio_data)
