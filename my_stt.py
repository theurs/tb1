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
from pathlib import Path

import audiofile
import google.generativeai as genai
import speech_recognition as sr

import my_gemini
import cfg
import my_log
import utils


# locks for chat_ids
LOCKS = {}

# [(crc32, text recognized),...]
STT_CACHE = []
CACHE_SIZE = 100


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


def audio_duration(audio_file: str) -> int:
    """
    Get the duration of an audio file.

    Args:
        audio_file (str): The path to the audio file.

    Returns:
        int: The duration of the audio file in seconds.
    """
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', audio_file], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return float(result.stdout)


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
    audio_file2 = convert_to_wave_with_ffmpeg(audio_file)
    google_recognizer = sr.Recognizer()

    with sr.AudioFile(audio_file2) as source:
        audio = google_recognizer.record(source)  # read the entire audio file

    try:
        os.unlink(audio_file2)
    except Exception as unknown_error:
        my_log.log2(f'my_stt:stt_google:{unknown_error}')

    text = google_recognizer.recognize_google(audio, language=language)

    # хак для голосовых команд обращенных к гуглу и бингу
    # воск их записывает по-русски а гугл по-английски
    lower_text = text.lower()
    if lower_text.startswith('google'):
        text = 'гугл ' + text[6:]
    if lower_text.startswith('bing'):
        text = 'бинг ' + text[4:]
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

        if not text:
            # быстро и хорошо распознает но до 1 минуты всего
            # и часто глотает последнее слово
            try: # пробуем через гугл
                text = stt_google(input_file, lang)
            except AssertionError:
                pass
            except sr.UnknownValueError as unknown_value_error:
                print(unknown_value_error)
                my_log.log2(str(unknown_value_error))
            except sr.RequestError as request_error:
                print(request_error)
                my_log.log2(str(request_error))
            except Exception as unknown_error:
                print(unknown_error)
                my_log.log2(str(unknown_error))

        try: # gemini
            # может выдать до 8000 токенов (12000 русских букв) более чем достаточно для голосовух
            text = stt_genai(input_file)
        except Exception as error:
            my_log.log2(f'my_stt:stt:genai:{error}')

        #затем через локальный (моя реализация) whisper
        if not text:
            try:
                text = stt_my_whisper_api(input_file, lang)
            except Exception as error:
                error_traceback = traceback.format_exc()
                my_log.log2(f'my_stt:stt:{error}\n\n{error_traceback}')

        if text:
            # text_ = my_gemini.repair_text_after_speech_to_text(text)
            text_ = text
            STT_CACHE.append([data, text_])
            STT_CACHE = STT_CACHE[-CACHE_SIZE:]
            return text_

    return ''


def audio_to_wav(audio_bytes: bytes, file_info: str) -> bytes:
    """
    Конвертирует аудиоданные из формата AMR в WAV.

    Args:
        audio_bytes: Байты аудиоданных в формате AMR.
        file_info: Строка, имя файла из которого можно получить его расширение

    Returns:
        Байты аудиоданных в формате WAV.
    """
    ext = Path(file_info).suffix
    
    temp_input = utils.get_tmp_fname()+ext
    temp_output = utils.get_tmp_fname()+'.wav'

    with open(temp_input, 'wb') as f:
        f.write(audio_bytes)

    audiofile.convert_to_wav(temp_input, temp_output)

    with open(temp_output, 'rb') as f:
        wav_bytes = f.read()

    try:
        os.remove(temp_input)
    except Exception as error:
        my_log.log2(f'my_stt:audio_to_wav:remove input {temp_input} {error}')
        pass
    try:
        os.remove(temp_output)
    except Exception as error:
        my_log.log2(f'my_stt:audio_to_wav:remove output {temp_output} {error}')

    return wav_bytes


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
        prompt = "Listen carefully to the following audio file. Provide a transcript. Fix errors, make a fine text."

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
                response = model.generate_content([prompt, your_file])
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
    # print(stt_genai('1.opus'))
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
