#!/usr/bin/env python3


import asyncio
import io
import glob
import os
import tempfile

import edge_tts
import gtts
import yandex_speech

import gpt_basic


#cache for TTS
TTS_CACHE = []
CACHE_SIZE = 20


# cleanup
for filePath in [x for x in glob.glob('*.wav') + glob.glob('*.ogg') + glob.glob('*.mp4') + glob.glob('*.mp3') if 'temp_tts_file' in x]:
    try:
        os.remove(filePath)
    except:
        print("Error while deleting file : ", filePath)


def tts_google(text: str, lang: str = 'ru') -> bytes:
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
    TTS_CACHE.append([text, data])
    TTS_CACHE = TTS_CACHE[-CACHE_SIZE:]
    return data


def tts_openai(text: str, voice: str = 'alloy') -> bytes:
    """
    Generate text to speech audio using OpenAI's TTS API.

    Args:
        text (str): The text to be converted to speech.
        voice (str, optional): The voice to be used for the speech. Defaults to 'alloy'.

    Returns:
        bytes: The audio data in bytes format.

    """
    if 'alloy' in voice:
        voice = 'alloy'
    elif 'echo' in voice:
        voice = 'echo'
    elif 'fable' in voice:
        voice = 'fable'
    elif 'onyx' in voice:
        voice = 'onyx'
    elif 'nova' in voice:
        voice = 'nova'
    elif 'shimmer' in voice:
        voice = 'shimmer'
    else:
        voice = 'alloy'
    data = gpt_basic.tts(text, voice)
    global TTS_CACHE
    TTS_CACHE.append([text, data])
    TTS_CACHE = TTS_CACHE[-CACHE_SIZE:]
    return data


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
    for text_, data in TTS_CACHE:
        if text_ == text:
            return data

    if gender == 'google_female':
        return tts_google(text, lang)
    if 'openai' in gender:
        return tts_openai(text, gender)
    if 'ynd' in gender:
        return tts_yandex(text, voice, rate, gender)

    voice = get_voice(voice, gender)

    # Удаляем символы переноса строки и перевода каретки 
    text = text.replace('\r','') 
    text = text.replace('\n\n','\n')  

    # Создаем временный файл для записи аудио
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f: 
        filename = f.name 

    # Запускаем edge-tts для генерации аудио
    com = edge_tts.Communicate(text, voice, rate=rate)
    asyncio.run(com.save(filename))

    # Читаем аудио из временного файла 
    with open(filename, "rb") as f: 
        data = io.BytesIO(f.read())

    os.remove(filename)
    # Возвращаем байтовый поток с аудио
    data = data.getvalue()

    TTS_CACHE.append([text, data])
    TTS_CACHE = TTS_CACHE[-CACHE_SIZE:]
    return data


def tts_yandex(text: str, voice: str = 'ru', rate: str = '+0%', gender: str = 'female') -> bytes:
    """
    Generate text-to-speech (TTS) audio using the Yandex API.
    
    Parameters:
        text (str): The text to convert to speech.
        voice (str, optional): The voice to use for the speech. Defaults to 'ru'.
        rate (str, optional): The rate of the speech. Defaults to '+0%'.
        gender (str, optional): The gender of the voice. Defaults to 'female'.
        
    Returns:
        bytes: The generated audio data in binary format.
    """
    # female - "jane", "oksana", "alyss", "omazh"
    # male - "zahar", "ermil"
    KEY = '60589d42-0e42-b742-8942-thekeyisalie'
    FORMAT = 'mp3'
    lang = f'{voice}-{voice.upper()}'
    # convert rate to decimal
    rate_decimal = 1.0 + (float(rate.strip('%')) / 100)
    
    if 'female' in gender:
        voice = 'oksana'
    elif 'male' in gender:
        voice = 'zahar'

    tts = yandex_speech.TTS(voice, FORMAT, KEY, lang, speed=rate_decimal)
    tts.generate(text)
    
    data = b''
    for d in tts._data:
        data += d

    global TTS_CACHE
    TTS_CACHE.append([text, data])
    TTS_CACHE = TTS_CACHE[-CACHE_SIZE:]
    return data


def get_voice(language_code: str, gender: str = 'female'):
    """принимает двухбуквенное обозначение языка и возвращает голосовой движок для его озвучки
    gender = 'male' or 'female'"""
    assert gender in ('male', 'female')

    # белорусский язык это скорее всего ошибка автоопределителя, но в любом случае такой язык не поддерживается, меняем на украинский
    if language_code == 'be':
        language_code = 'uk'

    voices = {
 'af': {'female': 'af-ZA-AdriNeural', 'male': 'af-ZA-WillemNeural'},
 'am': {'female': 'am-ET-MekdesNeural', 'male': 'am-ET-AmehaNeural'},
 'ar': {'female': 'ar-YE-MaryamNeural', 'male': 'ar-YE-SalehNeural'},
 'az': {'female': 'az-AZ-BanuNeural', 'male': 'az-AZ-BabekNeural'},
 'bg': {'female': 'bg-BG-KalinaNeural', 'male': 'bg-BG-BorislavNeural'},
 'bn': {'female': 'bn-IN-TanishaaNeural', 'male': 'bn-IN-BashkarNeural'},
 'bs': {'female': 'bs-BA-VesnaNeural', 'male': 'bs-BA-GoranNeural'},
 'ca': {'female': 'ca-ES-JoanaNeural', 'male': 'ca-ES-EnricNeural'},
 'cs': {'female': 'cs-CZ-VlastaNeural', 'male': 'cs-CZ-AntoninNeural'},
 'cy': {'female': 'cy-GB-NiaNeural', 'male': 'cy-GB-AledNeural'},
 'da': {'female': 'da-DK-ChristelNeural', 'male': 'da-DK-JeppeNeural'},
 'de': {'female': 'de-DE-KatjaNeural', 'male': 'de-DE-KillianNeural'},
 'el': {'female': 'el-GR-AthinaNeural', 'male': 'el-GR-NestorasNeural'},
 'en': {'female': 'en-US-AriaNeural', 'male': 'en-US-ChristopherNeural'},
 'es': {'female': 'es-VE-PaolaNeural', 'male': 'es-VE-SebastianNeural'},
 'et': {'female': 'et-EE-AnuNeural', 'male': 'et-EE-KertNeural'},
 'fa': {'female': 'fa-IR-DilaraNeural', 'male': 'fa-IR-FaridNeural'},
 'fi': {'female': 'fil-PH-BlessicaNeural', 'male': 'fil-PH-AngeloNeural'},
 'fr': {'female': 'fr-FR-EloiseNeural', 'male': 'fr-FR-HenriNeural'},
 'ga': {'female': 'ga-IE-OrlaNeural', 'male': 'ga-IE-ColmNeural'},
 'gl': {'female': 'gl-ES-SabelaNeural', 'male': 'gl-ES-RoiNeural'},
 'gu': {'female': 'gu-IN-DhwaniNeural', 'male': 'gu-IN-NiranjanNeural'},
 'he': {'female': 'he-IL-HilaNeural', 'male': 'he-IL-AvriNeural'},
 'hi': {'female': 'hi-IN-SwaraNeural', 'male': 'hi-IN-MadhurNeural'},
 'hr': {'female': 'hr-HR-GabrijelaNeural', 'male': 'hr-HR-SreckoNeural'},
 'hu': {'female': 'hu-HU-NoemiNeural', 'male': 'hu-HU-TamasNeural'},
 'id': {'female': 'id-ID-GadisNeural', 'male': 'id-ID-ArdiNeural'},
 'is': {'female': 'is-IS-GudrunNeural', 'male': 'is-IS-GunnarNeural'},
 'it': {'female': 'it-IT-IsabellaNeural', 'male': 'it-IT-DiegoNeural'},
 'ja': {'female': 'ja-JP-NanamiNeural', 'male': 'ja-JP-KeitaNeural'},
 'jv': {'female': 'jv-ID-SitiNeural', 'male': 'jv-ID-DimasNeural'},
 'ka': {'female': 'ka-GE-EkaNeural', 'male': 'ka-GE-GiorgiNeural'},
 'kk': {'female': 'kk-KZ-AigulNeural', 'male': 'kk-KZ-DauletNeural'},
 'km': {'female': 'km-KH-SreymomNeural', 'male': 'km-KH-PisethNeural'},
 'kn': {'female': 'kn-IN-SapnaNeural', 'male': 'kn-IN-GaganNeural'},
 'ko': {'female': 'ko-KR-SunHiNeural', 'male': 'ko-KR-InJoonNeural'},
 'lo': {'female': 'lo-LA-KeomanyNeural', 'male': 'lo-LA-ChanthavongNeural'},
 'lt': {'female': 'lt-LT-OnaNeural', 'male': 'lt-LT-LeonasNeural'},
 'lv': {'female': 'lv-LV-EveritaNeural', 'male': 'lv-LV-NilsNeural'},
 'mk': {'female': 'mk-MK-MarijaNeural', 'male': 'mk-MK-AleksandarNeural'},
 'ml': {'female': 'ml-IN-SobhanaNeural', 'male': 'ml-IN-MidhunNeural'},
 'mn': {'female': 'mn-MN-YesuiNeural', 'male': 'mn-MN-BataaNeural'},
 'mr': {'female': 'mr-IN-AarohiNeural', 'male': 'mr-IN-ManoharNeural'},
 'ms': {'female': 'ms-MY-YasminNeural', 'male': 'ms-MY-OsmanNeural'},
 'mt': {'female': 'mt-MT-GraceNeural', 'male': 'mt-MT-JosephNeural'},
 'my': {'female': 'my-MM-NilarNeural', 'male': 'my-MM-ThihaNeural'},
 'nb': {'female': 'nb-NO-PernilleNeural', 'male': 'nb-NO-FinnNeural'},
 'ne': {'female': 'ne-NP-HemkalaNeural', 'male': 'ne-NP-SagarNeural'},
 'nl': {'female': 'nl-NL-FennaNeural', 'male': 'nl-NL-MaartenNeural'},
 'pl': {'female': 'pl-PL-ZofiaNeural', 'male': 'pl-PL-MarekNeural'},
 'ps': {'female': 'ps-AF-LatifaNeural', 'male': 'ps-AF-GulNawazNeural'},
 'pt': {'female': 'pt-PT-RaquelNeural', 'male': 'pt-PT-DuarteNeural'},
 'ro': {'female': 'ro-RO-AlinaNeural', 'male': 'ro-RO-EmilNeural'},
 'ru': {'female': 'ru-RU-SvetlanaNeural', 'male': 'ru-RU-DmitryNeural'},
 'si': {'female': 'si-LK-ThiliniNeural', 'male': 'si-LK-SameeraNeural'},
 'sk': {'female': 'sk-SK-ViktoriaNeural', 'male': 'sk-SK-LukasNeural'},
 'sl': {'female': 'sl-SI-PetraNeural', 'male': 'sl-SI-RokNeural'},
 'so': {'female': 'so-SO-UbaxNeural', 'male': 'so-SO-MuuseNeural'},
 'sq': {'female': 'sq-AL-AnilaNeural', 'male': 'sq-AL-IlirNeural'},
 'sr': {'female': 'sr-RS-SophieNeural', 'male': 'sr-RS-NicholasNeural'},
 'su': {'female': 'su-ID-TutiNeural', 'male': 'su-ID-JajangNeural'},
 'sv': {'female': 'sv-SE-SofieNeural', 'male': 'sv-SE-MattiasNeural'},
 'sw': {'female': 'sw-TZ-RehemaNeural', 'male': 'sw-TZ-DaudiNeural'},
 'ta': {'female': 'ta-SG-VenbaNeural', 'male': 'ta-SG-AnbuNeural'},
 'te': {'female': 'te-IN-ShrutiNeural', 'male': 'te-IN-MohanNeural'},
 'th': {'female': 'th-TH-PremwadeeNeural', 'male': 'th-TH-NiwatNeural'},
 'tr': {'female': 'tr-TR-EmelNeural', 'male': 'tr-TR-AhmetNeural'},
 'uk': {'female': 'uk-UA-PolinaNeural', 'male': 'uk-UA-OstapNeural'},
 'ur': {'female': 'ur-PK-UzmaNeural', 'male': 'ur-PK-AsadNeural'},
 'uz': {'female': 'uz-UZ-MadinaNeural', 'male': 'uz-UZ-SardorNeural'},
 'vi': {'female': 'vi-VN-HoaiMyNeural', 'male': 'vi-VN-NamMinhNeural'},
 'zh': {'female': 'zh-TW-HsiaoYuNeural', 'male': 'zh-TW-YunJheNeural'},
 'zu': {'female': 'zu-ZA-ThandoNeural', 'male': 'zu-ZA-ThembaNeural'}}

    return voices[language_code][gender]


if __name__ == "__main__":
    r = tts_yandex('hello 1+1=2', voice='zh', rate='+0%', gender='male')
    open('1.mp3', 'wb').write(r)
    