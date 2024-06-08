#!/usr/bin/env python3


import asyncio
import io
import glob
import os
import tempfile

import edge_tts
import gtts

import edge_tts_makedict


#cache for TTS
TTS_CACHE = []
CACHE_SIZE = 20


VOICES = None


# cleanup
for filePath in [x for x in glob.glob('*.wav') + glob.glob('*.ogg') + glob.glob('*.mp4') + glob.glob('*.mp3') if 'temp_tts_file' in x]:
    try:
        os.remove(filePath)
    except:
        print("Error while deleting file : ", filePath)


def tts_google(text: str, lang: str = 'ru', rate: str = '+0%') -> bytes:
    """
    Converts the given text to speech using the Google Text-to-Speech (gTTS) API.

    Parameters:
        text (str): The text to be converted to speech.
        lang (str, optional): The language of the text. Defaults to 'ru'.

    Returns:
        bytes: The generated audio as a bytes object.
    """
    mp3_fp = io.BytesIO()
    result = gtts.gTTS(text, lang=lang)
    result.write_to_fp(mp3_fp)
    mp3_fp.seek(0)
    data = mp3_fp.read()
    global TTS_CACHE
    TTS_CACHE.append([text, data, lang, rate, 'google_female'])
    TTS_CACHE = TTS_CACHE[-CACHE_SIZE:]
    return data


def get_voice(language_code: str, gender: str = 'female'):
    """принимает двухбуквенное обозначение языка и возвращает голосовой движок для его озвучки
    gender = 'male' or 'female'"""
    global VOICES
    
    assert gender in ('male', 'female')

    # белорусский язык это скорее всего ошибка автоопределителя, но в любом случае такой язык не поддерживается, меняем на украинский
    if language_code == 'be':
        language_code = 'uk'

    if not VOICES:
        VOICES = edge_tts_makedict.get_voices()

    if language_code == 'ua':
        language_code = 'uk'
    return VOICES[language_code][gender]


def tts(text: str, voice: str = 'ru', rate: str = '+0%', gender: str = 'female') -> bytes:
    """
    Generates text-to-speech audio from the given input text using the specified voice, 
    speech rate, and gender.

    Args:
        text (str): The input text to convert to speech.
        voice (str, optional): The voice to use for the speech. Defaults to 'ru'.
        rate (str, optional): The speech rate. Defaults to '+0%'.
        gender (str, optional): The gender of the voice. Defaults to 'female'.

    Returns:
        bytes: The generated audio as a bytes object.
    """
    lang = voice

    global TTS_CACHE
    for text_, data, lang_, rate_, gender_ in TTS_CACHE:
        if text_ == text and lang_ == lang and rate_ == rate and gender_ == gender:
            return data

    if gender == 'google_female':
        return tts_google(text, lang)

    voice = get_voice(voice, gender)

    # Удаляем символы переноса строки и перевода каретки 
    text = text.replace('\r','') 
    text = text.replace('\n\n','\n')  

    # Создаем временный файл для записи аудио
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as f: 
        filename = f.name 

    # Запускаем edge-tts для генерации аудио
    com = edge_tts.Communicate(text, voice, rate=rate)
    # com = edge_tts.Communicate(text, voice)
    asyncio.run(com.save(filename))

    # Читаем аудио из временного файла 
    with open(filename, "rb") as f: 
        data = io.BytesIO(f.read())

    os.remove(filename)
    # Возвращаем байтовый поток с аудио
    data = data.getvalue()

    TTS_CACHE.append([text, data, lang, rate, gender])
    TTS_CACHE = TTS_CACHE[-CACHE_SIZE:]
    return data


if __name__ == "__main__":
    pass
