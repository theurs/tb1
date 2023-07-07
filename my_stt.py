#!/usr/bin/env python3


import subprocess
import tempfile
import os
import sys
import threading
from pathlib import Path
import speech_recognition as sr

import gpt_basic


# сработает если бот запущен питоном из этого venv
vosk_cmd = Path(Path(sys.executable).parent, 'vosk-transcriber')

# запрещаем запускать больше чем 1 процесс распознавания голоса в одно время (только для vosk)
lock = threading.Lock()


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
    assert audio_duration(audio_file) < 50, 'Too big for free speech recognition'
    audio_file2 = convert_to_wave_with_ffmpeg(audio_file)
    google_recognizer = sr.Recognizer()

    with sr.AudioFile(audio_file2) as source:
        audio = google_recognizer.record(source)  # read the entire audio file
    #try:
    text = google_recognizer.recognize_google(audio, language=language)
    #except sr.UnknownValueError:
    #    text = "Google Speech Recognition could not understand audio"
    #except sr.RequestError as error:
    #    text = f"Could not request results from Google Speech Recognition service; {error}"

    #os.remove(audio_file)
    os.remove(audio_file2)

    # хак для голосовых команд обращенных к гуглу и бингу
    # воск их записывает по-русски а гугл по-английски
    lower_text = text.lower()
    if lower_text.startswith('google'):
        text = 'гугл ' + text[6:]
    if lower_text.startswith('bing'):
        text = 'бинг ' + text[4:]
    return text


def stt(input_file: str) -> str:
    with tempfile.NamedTemporaryFile() as temp_file:
        output_file = temp_file.name
    
    text = ''
    
    try:
        text = stt_google(input_file)
    except AssertionError:
        pass
    except sr.UnknownValueError:
        pass
    except sr.RequestError:
        pass
    except Exception as unknown_error:
        print(unknown_error)

    if not text:
        with lock:
            subprocess.run([vosk_cmd, "--server", "--input", input_file, "--output", output_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with open(output_file, "r") as f:
                text = f.read()
        # Удаление временного файла
        os.remove(output_file)

    cleared = gpt_basic.clear_after_stt(text)
    return cleared


if __name__ == "__main__":
    #print(vosk_cmd)
    text = stt('1.webm')
    print(text)
