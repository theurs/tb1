#!/usr/bin/env python3


import base64
import hashlib
import os
import random
import requests
import subprocess
import tempfile
import time
import threading
import traceback

import speech_recognition as sr

import cfg
import gpt_basic
import my_log
import my_gemini


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
    with tempfile.NamedTemporaryFile() as temp_file:
        tmp_wav_file = temp_file.name + '.wav'
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
        
        data = hashlib.sha256(open(input_file, 'rb').read()).hexdigest()
        global STT_CACHE
        for x in STT_CACHE:
            if x[0] == data:
                text = x[1]
                return text

        try: # сначала пробуем через гугл
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

        #затем через локальный (моя реализация) whisper
        if not text:
            try:
                text = stt_my_whisper_api(input_file, lang)
            except Exception as error:
                error_traceback = traceback.format_exc()
                my_log.log2(f'my_stt:stt:{error}\n\n{error_traceback}')

        if not text:
            try:
                # затем opanai
                assert audio_duration(input_file) < 600, 'Too big for free speech recognition'
                # auto detect language?
                text = gpt_basic.stt(input_file)
            except Exception as error:
                my_log.log2(f'{error}\n\n{text}')

        if text:
            text_ = my_gemini.repair_text_after_speech_to_text(text)
            STT_CACHE.append([data, text_])
            STT_CACHE = STT_CACHE[-CACHE_SIZE:]
            return text_

    return ''


if __name__ == "__main__":
    text = stt('1.opus')
    print(text)
