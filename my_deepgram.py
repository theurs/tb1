# pip install deepgram-sdk deepgram_captions
# ??pip install python-dotenv??


import random
import time
import traceback
from datetime import timedelta


from deepgram import (
    DeepgramClient,
    PrerecordedOptions,
    SpeakOptions,
    FileSource,
)
from deepgram_captions import DeepgramConverter, srt, webvtt

import cfg
import my_log
import utils


def stt(buffer_data: bytes, lang: str = 'ru', prompt: str = '') -> str:
    '''
    Convert audio data to text using Deepgram API.
    buffer_data: bytes or str - audio data or path to audio file
    lang : str - language code not used
    prompt : str - not used
    '''
    try:
        if not hasattr(cfg, 'DEEPGRAM_KEYS') or not cfg.DEEPGRAM_KEYS:
            return ''

        api_key = random.choice(cfg.DEEPGRAM_KEYS)
        deepgram = DeepgramClient(api_key=api_key)

        if isinstance(buffer_data, str):
            with open(buffer_data, "rb") as file:
                buffer_data = file.read()

        payload: FileSource = {
            "buffer": buffer_data,
        }

        options = PrerecordedOptions(
            model="nova-2",
            smart_format=True,
            detect_language=True,
        )

        response = deepgram.listen.rest.v("1").transcribe_file(payload, options)

        transcript = response["results"]["channels"][0]["alternatives"][0]["transcript"]

        return transcript
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_deepgram(f'Failed to convert audio data to text: {error}\n\n{traceback_error}')

    return ''


def tts(text: str, lang: str = 'ru', voice: str = 'aura-zeus-en') -> bytes:
    '''
    Convert text to audio data using Deepgram API.
    text: str - text to convert
    lang: str - language code
    voice: str - voice name
        Male:   aura-orion-en,   aura-arcas-en, aura-perseus-en, aura-angus-en,  aura-orpheus-en, aura-helios-en, aura-zeus-en
        Female: aura-asteria-en, aura-luna-en,  aura-stella-en,  aura-athena-en, aura-hera-en
    '''
    try:
        if not hasattr(cfg, 'DEEPGRAM_KEYS') or not cfg.DEEPGRAM_KEYS:
            return b''

        if voice not in (
            'aura-orion-en', 'aura-arcas-en', 'aura-perseus-en', 'aura-angus-en', 'aura-orpheus-en', 'aura-helios-en', 'aura-zeus-en', 
            'aura-asteria-en', 'aura-luna-en', 'aura-stella-en', 'aura-athena-en', 'aura-hera-en'
        ) or not text.strip():
            return b''

        api_key = random.choice(cfg.DEEPGRAM_KEYS)
        deepgram = DeepgramClient(api_key=api_key)

        options = SpeakOptions(
            model = voice,
        )

        tmpfname = utils.get_tmp_fname()

        SPEAK_TEXT = {"text": text}

        response = deepgram.speak.rest.v("1").save(tmpfname, SPEAK_TEXT, options)

        data = b''
        try:
            with open(tmpfname, "rb") as file:
                data = file.read()
        except Exception as error:
            pass
        utils.remove_file(tmpfname)

        # print(response.to_json(indent=4))
        return data

    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_deepgram(f'Failed to convert text to audio data: {error}\n\n{traceback_error}')

    return b''


def transcribe(buffer_data: bytes, lang: str = 'ru', prompt: str = ''):
    '''
    Транскрибирует аудиозапись и возвращает субтитры в 2 форматах srt и vtt и текст.
    '''
    try:
        if not hasattr(cfg, 'DEEPGRAM_KEYS') or not cfg.DEEPGRAM_KEYS:
            return ''

        api_key = random.choice(cfg.DEEPGRAM_KEYS)
        deepgram = DeepgramClient(api_key=api_key)

        if isinstance(buffer_data, str):
            with open(buffer_data, "rb") as file:
                buffer_data = file.read()

        payload: FileSource = {
            "buffer": buffer_data,
        }

        options = PrerecordedOptions(
            model="nova-2",
            smart_format=True,
            detect_language=True,
            # diarize=True  # Добавляем diarize=True для определения говорящих
        )
        time_start = time.time()
        # human readable time format
        print("Start time is: " + time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time_start)))
        response = deepgram.listen.rest.v("1").transcribe_file(payload, options)
        time_end = time.time()
        time_delta = time_end - time_start
        # human readable time format
        print('End time is: ' + time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time_end)))
        print(f'Time elapsed: {timedelta(seconds=time_delta)}')

        t = DeepgramConverter(response)
        captions_srt = srt(t)
        captions_vtt = webvtt(t)
        transcript = response["results"]["channels"][0]["alternatives"][0]["transcript"]        

        return captions_srt, captions_vtt, transcript
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_deepgram(f'Failed to convert audio data to text: {error}\n\n{traceback_error}')

    return ''


def save_caps(cap_srt: str, cap_vtt: str, text: str, fname: str):
    '''
    Сохраняет в указанный файл (добавляет разные расширения) субтитры в форматах srt и vtt и текст.
    '''
    with open(fname + '.srt', 'w', encoding='utf-8') as f:
        f.write(cap_srt)
    with open(fname + '.vtt', 'w', encoding='utf-8') as f:
        f.write(cap_vtt)
    with open(fname + '.txt', 'w', encoding='utf-8') as f:
        f.write(text)


if __name__ == "__main__":
    pass
    # print(stt('C:/Users/user/Downloads/1.ogg'))
    # print(stt('C:/Users/user/Downloads/2.m4a'))

    # text_to_say = 'In 2021, Microsoft and OpenAI introduced the AI-powered assistant for programmers, GitHub Copilot.'
    # data = tts(text_to_say)
    # with open('C:/Users/user/Downloads/output.mp3', 'wb') as f:
    #     f.write(data)

    cap_crt, cap_vtt, text = transcribe('C:/Users/user/Downloads/3.m4a')
    save_caps(cap_crt, cap_vtt, text, 'C:/Users/user/Downloads/3')