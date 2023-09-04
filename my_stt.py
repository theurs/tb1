#!/usr/bin/env python3


import os
import subprocess
import sys
import threading
import tempfile
from pathlib import Path
import speech_recognition as sr

import cfg
import gpt_basic
import my_log
import my_whisper


# сработает если бот запущен питоном из этого venv
vosk_cmd = Path(Path(sys.executable).parent, 'vosk-transcriber')

# запрещаем запускать больше чем 1 процесс распознавания голоса в одно время (только для vosk)
vosk_lock = threading.Lock()


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
    #subprocess.run(['ffmpeg', '-i', audio_file, '-t', '00:00:50', tmp_wav_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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

    text = google_recognizer.recognize_google(audio, language=language)

    os.remove(audio_file2)

    # хак для голосовых команд обращенных к гуглу и бингу
    # воск их записывает по-русски а гугл по-английски
    lower_text = text.lower()
    if lower_text.startswith('google'):
        text = 'гугл ' + text[6:]
    if lower_text.startswith('bing'):
        text = 'бинг ' + text[4:]
    return text


def stt(input_file: str, lang: str = 'ru') -> str:
    """
    This function takes an input file path as a parameter and returns the transcribed text from the audio file.
    
    Args:
        input_file (str): The path of the input audio file.
    
    Returns:
        str: The transcribed text from the audio file.
    """
    with tempfile.NamedTemporaryFile() as temp_file:
        output_file = temp_file.name

    text = ''

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

    if not text:
        try:
            # затем opanai
            assert audio_duration(input_file) < 600, 'Too big for free speech recognition'
            # auto detect language?
            text = gpt_basic.stt(input_file)
        except Exception as error:
            print(error, text)
            my_log.log2(f'{error}\n\n{text}')

    if not text:
        if cfg.stt == 'whisper':
            my_whisper.get_text(input_file)
        elif cfg.stt == 'vosk':
            with vosk_lock:
                subprocess.run([vosk_cmd, "--server", "--input", input_file, "--output", output_file], 
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                with open(output_file, "r") as f:
                    text = f.read()
            os.remove(output_file)

    if text:
        cleared = gpt_basic.clear_after_stt(text)
        return cleared
    return text


if __name__ == "__main__":
    os.environ['all_proxy'] = cfg.all_proxy
    #print(vosk_cmd)
    text = stt('1.opus')
    print(text)
