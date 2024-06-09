#!/usr/bin/env python3
# pip install fastapi pydub TTS pyinstaller sqlitedict uvicorn torch pydantic
# pyinstaller my_tts_server.py # не хочет работать
#
############################################################################################### 
# ffmpeg должен быть установлен в системе
# в папке tts_models/1.opus должен лежать файл 1.opus, там примерно 1 минута дефолтного голоса
# .opus - дефолтный кодек ютуба, скачать что-нибудь с ютуба можно командой yt-dlp -x URL
# порезать размер как то так ffmpeg -i 2.opus -t 00:01:00 -c copy 1.opus
# в папке ./db/ будет база с загруженными голосами users_voice.db
# 
# Как запустить питоновский скрипт в венде как службу но с правами какого то юзера. 
# Надо использовать nssm install <servicename>
# 
# python -m venv my_tts_server
# my_tts_server\Scripts\activate.bat
# pip install <название_пакета1> <название_пакета2> ...
# python.exe c:\...\my_tts_server\Scripts\python.exe my_tts_server.py
###############################################################################################


import base64
import os
import subprocess
import tempfile
import time
import threading
from typing import Optional

import torch
import uvicorn
from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from pydub import AudioSegment
from sqlitedict import SqliteDict
from TTS.api import TTS

import utils

if not os.path.exists('db'):
    os.mkdir('db')
# {user id as str: user voice wav file as bytes}
USERS = SqliteDict('db/users_voice.db', autocommit=True)


# можно запускать только 1 поток генерации голоса
LOCK = threading.Lock()


device = None
DEFAULT_SPEAKER = None
tts = None


def init():
    global device, DEFAULT_SPEAKER, tts
    if not device:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if not DEFAULT_SPEAKER:
        DEFAULT_SPEAKER = convert_to_wav('tts_models/1.opus', open('tts_models/1.opus', 'rb').read())
    if not tts:
        tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)


def get_tmp_fname() -> str:
    """
    Generate a temporary file name.

    Returns:
        str: The name of the temporary file.
    """
    with tempfile.NamedTemporaryFile(delete=True) as temp_file:
        return temp_file.name


def get_voice(text: str, language: str = "ru", speaker_wav: bytes = None) -> bytes:
    """
    Синтезирует речь из текста и возвращает аудио в формате Ogg Vorbis.

    Args:
        text (str): Текст для озвучивания.
        language (str, optional): Язык текста. По умолчанию "ru".
        speaker_wav (bytes, optional): WAV-данные голоса диктора.
                                        По умолчанию используется DEFAULT_SPEAKER.

    Returns:
        bytes: Аудиоданные в формате Ogg Vorbis.

    Raises:
        Любые исключения, возникающие в процессе синтеза или обработки аудио.
    """
    with LOCK:
        try:
            init()
            if not speaker_wav:
                speaker_wav = DEFAULT_SPEAKER
            speaker_file = get_tmp_fname() + ".wav"
            with open(speaker_file, "wb") as f:
                f.write(speaker_wav)

            output_file = get_tmp_fname() + ".wav"
            result_file = get_tmp_fname() + ".ogg"

            tts.tts_to_file(text, speaker_wav=speaker_file, language=language, file_path=output_file)

            with open(output_file, "rb") as f:
                result = f.read()

            AudioSegment.from_wav(output_file).export(result_file, format="ogg")
            with open(result_file, "rb") as f:
                result = f.read()

            return result
        finally:
            utils.remove_file(speaker_file)
            utils.remove_file(output_file)
            utils.remove_file(result_file)


def convert_to_wav(fname: str, data: str) -> bytes:
    '''Convert data bytes to wav file'''
    ext = fname.lower().split('.')[-1]
    if ext == 'wav':
        return data

    tmp_out = get_tmp_fname() + '.' + ext
    tmp_out_wav = get_tmp_fname() + '.' + ext + '.wav'
    with open(tmp_out, 'wb') as f:
        f.write(data)

    subprocess.run(['ffmpeg', '-i', tmp_out, '-map', '0:a', '-c:a', 'pcm_s16le', tmp_out_wav], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # subprocess.run(['ffmpeg', '-i', tmp_out, '-map', '0:a', '-c:a', 'pcm_s16le', tmp_out_wav])

    with open(tmp_out_wav, 'rb') as f:
        result = f.read()

    utils.remove_file(tmp_out)
    utils.remove_file(tmp_out_wav)

    return result


app = FastAPI()


class VoiceRequest(BaseModel):
    text: str
    language: Optional[str] = "ru"
    user_id:  Optional[str] = "unknown"


@app.post("/get-voice/")
async def get_voice_endpoint(request: VoiceRequest):
    try:
        init()
        if request.user_id == "unknown" or request.user_id not in USERS or not USERS[request.user_id]:
            speaker = DEFAULT_SPEAKER
        else:
            speaker = USERS[request.user_id]

        voice_bytes = get_voice(request.text, request.language, speaker)
        return {"voice": base64.b64encode(voice_bytes).decode('utf-8')}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/set-voice/")
async def set_voice_endpoint(user_id: str, fname: str, filedata: UploadFile = File(...)):
    """
    Сохраняет голос пользователя.

    Args:
        user_id (str): Идентификатор пользователя.
        fname (str): Имя файла с голосом пользователя.
        filedata (UploadFile, optional): Файл с голосом пользователя. По умолчанию File(...).

    Raises:
        HTTPException: Если произошла ошибка при обработке аудио.
    """
    try:
        if filedata:
            data = await filedata.read()
        voice_data = convert_to_wav(fname, data)
        USERS[user_id] = voice_data
        return {"message": "OK"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    while 1:
        try:
            uvicorn.run(app, host="0.0.0.0", port = 34671)
        except Exception as error:
            print(error)
            time.sleep(10)
