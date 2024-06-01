#!/usr/bin/env python3
# pip install -U google-generativeai

import base64
import hashlib
import os
import random
import requests
import subprocess
import time
import threading
import traceback

import google.generativeai as genai
import speech_recognition as sr
from google.generativeai.types import HarmCategory, HarmBlockThreshold

import my_gemini
import cfg
import my_log
import utils


# locks for chat_ids
LOCKS = {}

# [(crc32, text recognized),...]
STT_CACHE = []
CACHE_SIZE = 100


def audio_duration(audio_file: str) -> int:
    """
    Get the duration of an audio file.

    Args:
        audio_file (str): The path to the audio file.

    Returns:
        int: The duration of the audio file in seconds.
    """
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', audio_file], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        r = float(result.stdout)
    except ValueError:
        r = 0
    return r


def convert_to_wave_with_ffmpeg(audio_file: str) -> str:
    """
    Converts an audio file to a wave format using FFmpeg.

    Args:
        audio_file (str): The path to the audio file to be converted.

    Returns:
        str: The path to the converted wave file.
    """
    tmp_wav_file = utils.get_tmp_fname() + '.wav'
    subprocess.run(['ffmpeg', '-i', audio_file, tmp_wav_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return tmp_wav_file


def convert_to_ogg_with_ffmpeg(audio_file: str) -> str:
    """
    Converts an audio file to a ogg format using FFmpeg.

    Args:
        audio_file (str): The path to the audio file to be converted.

    Returns:
        str: The path to the converted wave file.
    """
    tmp_wav_file = utils.get_tmp_fname() + '.ogg'
    subprocess.run(['ffmpeg', '-i', audio_file, '-map', '0:a', '-c:a','libvorbis', tmp_wav_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return tmp_wav_file


def stt_google(audio_file: str, language: str = 'ru') -> str:
    """
    Speech-to-text using Google's speech recognition API.
    
    Args:
        audio_file (str): The path to the audio file to be transcribed.
        language (str, optional): The language of the audio file. Defaults to 'ru'.
    
    Returns:
        str: The transcribed text from the audio file.
    """
    assert audio_duration(audio_file) < 55, 'Too big for free speech recognition'

    google_recognizer = sr.Recognizer()

    with sr.AudioFile(audio_file) as source:
        audio = google_recognizer.record(source)  # read the entire audio file

    text = google_recognizer.recognize_google(audio, language=language)

    return text


def stt_my_whisper_api(audio_file: str, language: str = 'ru') -> str:
    """
    Speech-to-text using MyWhisper API.
    
    Args:
        audio_file (str): The path to the audio file to be transcribed.
        language (str, optional): The language of the audio file. Defaults to 'ru'.
    
    Returns:
        str: The transcribed text from the audio file.
    """
    if not(hasattr(cfg, 'MY_WHISPER_API') and cfg.MY_WHISPER_API):
        return ''

    # assert audio_duration(audio_file) < 1200, 'Too big'

    servers = cfg.MY_WHISPER_API[:]
    random.shuffle(servers)

    for server in servers:
        addr = server[0]
        port = server[1]
        with open(audio_file, 'rb') as af:
            audio_bytes = af.read()

        audio_bytes_base64 = base64.b64encode(audio_bytes).decode('UTF-8')

        data = {"data": audio_bytes_base64, "lang": language}

        # Проверить доступность сервера
        response = requests.head(f"http://{addr}:{port}/stt", timeout=3)
        if response.status_code != 405:
            continue
        t1 = time.time()
        response = requests.post(
            f"http://{addr}:{port}/stt",
            json=data,
            headers={"Content-Type": "application/json"},
            timeout=600,
        )
        print(time.time() - t1)
        if response.status_code == 200:
            r = base64.b64decode(response.content.decode("UTF-8")).decode('UTF-8')
            return r

    return ''


def stt(input_file: str, lang: str = 'ru', chat_id: str = '_') -> str:
    """
    Generate the function comment for the given function body in a markdown code block with the correct language syntax.

    Args:
        input_file (str): The path to the input file.
        lang (str, optional): The language for speech recognition. Defaults to 'ru'.
        chat_id (str, optional): The ID of the chat. Defaults to '_'.

    Returns:
        str: The recognized speech as text.
    """
    if chat_id not in LOCKS:
        LOCKS[chat_id] = threading.Lock()
    with LOCKS[chat_id]:
        text = ''
        with open(input_file, 'rb') as f:
            data_from_file = f.read()
        data = hashlib.sha256(data_from_file).hexdigest()
        global STT_CACHE
        for x in STT_CACHE:
            if x[0] == data:
                text = x[1]
                return text

        dur = audio_duration(input_file)
        if dur < 55:
            input_file2 = convert_to_wave_with_ffmpeg(input_file)
        else:
            input_file2 = convert_to_ogg_with_ffmpeg(input_file)

        try:
            if not text and dur < 55:
                # быстро и хорошо распознает но до 1 минуты всего
                # и часто глотает последнее слово
                try: # пробуем через гугл
                    text = stt_google(input_file2, lang)
                except AssertionError:
                    pass
                except sr.UnknownValueError as unknown_value_error:
                    my_log.log2(str(unknown_value_error))
                except sr.RequestError as request_error:
                    my_log.log2(str(request_error))
                except Exception as unknown_error:
                    my_log.log2(str(unknown_error))

            if not text and dur < 55: # google failed, delete wav and create ogg
                try:
                    os.unlink(input_file2)
                except Exception as error:
                    my_log.log2(f'my_stt:stt:os.unlink:{error}')
                input_file2 = convert_to_ogg_with_ffmpeg(input_file)

            if not text:
                try: # gemini
                    # может выдать до 8000 токенов (12000 русских букв) более чем достаточно для голосовух
                    text = stt_genai(input_file2)
                except Exception as error:
                    my_log.log2(f'my_stt:stt:genai:{error}')

            #затем через локальный (моя реализация) whisper
            if not text:
                try:
                    text = stt_my_whisper_api(input_file2, lang)
                except Exception as error:
                    error_traceback = traceback.format_exc()
                    my_log.log2(f'my_stt:stt:{error}\n\n{error_traceback}')

        finally:
            try:
                os.unlink(input_file2)
            except Exception as error:
                my_log.log2(f'my_stt:stt:os.unlink:{error}')

        if text:
            # text_ = my_gemini.repair_text_after_speech_to_text(text)
            text_ = text
            STT_CACHE.append([data, text_])
            STT_CACHE = STT_CACHE[-CACHE_SIZE:]
            return text_

    return ''


def genai_clear():
    """Очистка файлов, загруженных через Gemini API.
    TODO: Проверить возможность удаления чужих файлов.
    TODO: Обработать потенциальный race condition при настройке API ключа.
    """

    try:
        keys = cfg.gemini_keys[:] + my_gemini.ALL_KEYS
        random.shuffle(keys)

        for key in keys:
            print(key)
            genai.configure(api_key=key) # здесь может быть рейс кондишн?
            files = genai.list_files()
            for f in files:
                print(f.name)
                try:
                    # genai.delete_file(f.name)
                    pass # можно ли удалять чужие файлы?
                except Exception as error:
                    my_log.log_gemini(f'stt:genai_clear: delete file {error}\n{key}\n{f.name}')

    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_gemini(f'Failed to convert audio data to text: {error}\n\n{traceback_error}')


def stt_genai(audio_file: str) -> str:
    """
    Converts the given audio file to text using the Gemini API.

    Args:
        audio_file (str): The path to the audio file to be converted.

    Returns:
        str: The converted text.
    """
    try:
        keys = cfg.gemini_keys[:] + my_gemini.ALL_KEYS
        random.shuffle(keys)
        key = keys[0]

        your_file = None
        prompt = "Listen carefully to the following audio file. Provide a transcript. Fix errors, make a fine text without time stamps."

        for _ in range(3):
            try:
                genai.configure(api_key=key) # здесь может быть рейс кондишн?
                if your_file == None:
                    your_file = genai.upload_file(audio_file)
                    genai.configure(api_key=key) # здесь может быть рейс кондишн?
                model = genai.GenerativeModel('models/gemini-1.5-flash-latest')
                # tokens_count = model.count_tokens([your_file])
                # if tokens_count.total_tokens > 7800:
                #     response = ''
                #     break
                response = model.generate_content([prompt, your_file],
                                                  safety_settings={
                    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                    }
                )
                if response.text.strip():
                    break
            except Exception as error:
                my_log.log_gemini(f'Failed to convert audio data to text: {error}')
                response = ''
                time.sleep(2)

        try:
            genai.configure(api_key=key) # здесь может быть рейс кондишн?
            genai.delete_file(your_file.name)
        except Exception as error:
            my_log.log_gemini(f'Failed to delete audio file: {error}\n{key}\n{your_file.name}\n\n{str(your_file)}')

        return response.text.strip() if response else ''
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_gemini(f'Failed to convert audio data to text: {error}\n\n{traceback_error}')


if __name__ == "__main__":

    # print(stt('1.mp3'))
    # print(stt('1.webm'))
    # print(stt('1.aac'))
    # print(stt('1.amr'))
    # print(stt('1.flac'))
    # print(stt('1.mp4'))

    # print(detect_audio_codec_with_ffprobe('1.ogg'))
    # print(detect_audio_codec_with_ffprobe('1.webm'))
    # print(detect_audio_codec_with_ffprobe('1.mp4'))

    # print(convert_to_wave_with_ffmpeg('1.ogg'))

    # genai.configure(api_key=cfg.gemini_keys[0])
    # for x in genai.list_models():
    #     print(x)

    # print(stt_genai('1.pdf'))
    # print(stt_genai('1.wav'))
    # genai_clear()

    pass
    # text = stt('3.ogg')
    # print(text)

    # # Читаем байты из .amr файла
    # with open('1.amr', 'rb') as f:
    #     amr_data = f.read()
    # # Конвертируем в WAV
    # wav_data = amr_to_wav(amr_data)
    # # Сохраняем WAV данные в файл (опционально)
    # with open('audio.wav', 'wb') as f:
    #     f.write(wav_data)
