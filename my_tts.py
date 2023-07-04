#!/usr/bin/env python3


import io
import tempfile
import os
import asyncio

import edge_tts
import gtts
from vosk_tts.model import Model
from vosk_tts.synth import Synth


VOSK_MODEL = Model(model_name="vosk-model-tts-ru-0.1-natasha")
VOSK_SYNTH = Synth(VOSK_MODEL)


def tts_vosk(text: str) -> bytes:
    # Создаем временный файл для записи аудио
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f: 
        filename = f.name 

    VOSK_SYNTH.synth(text, filename)
    data = open(filename, "rb").read()
    os.remove(filename)
    return data


def tts_google(text: str, lang: str = 'ru') -> bytes:
    """
    Converts the given text to speech using the Google Text-to-Speech (gTTS) API.

    Parameters:
        text (str): The text to be converted to speech.
        lang (str, optional): The language of the text. Defaults to 'ru'.

    Returns:
        bytes: The audio file in the form of bytes.
    """
    mp3_fp = io.BytesIO()
    result = gtts.gTTS(text, lang=lang)
    result.write_to_fp(mp3_fp)
    mp3_fp.seek(0)
    return mp3_fp.read()


def tts(text: str, voice: str = 'ru', rate: str = '+0%', gender: str = 'female') -> bytes:
    """Генерирует аудио из текста с помощью edge-tts и возвращает байтовый поток

    Эта функция принимает:

    text: Строку с текстом для озвучивания

    voice: Необязательный параметр, указывает голос для синтеза речи. По умолчанию используется русский голос. Можно указать любой другой голос, доступный в edge-tts.

    rate: Необязательный параметр, указывает скорость речи. По умолчанию '+50%' - повышенная скорость. Можно указать любую скорость речи, поддерживаемую edge-tts.

    gender: Необязательный параметр, 'female' или 'male'

    Функция возвращает байтовый поток с сгенерированным аудио.
    """
    lang = voice

    if gender == 'google_female':
        return tts_google(text, lang)

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
    return data.getvalue()


def get_voice(language_code: str, gender: str = 'female'):
    """принимает двухбуквенное обозначение языка и возвращает голосовой движок для его озвучки
    gender = 'male' or 'female'"""
    assert gender in ('male', 'female')
    
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
 'en': {'female': 'en-ZA-LeahNeural', 'male': 'en-ZA-LukeNeural'},
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
    #print(type(tts('Привет, как дела!', 'ru')))
    
    print(type(tts_vosk('Привет, как дела!')))

    #print(get_voice('ru', 'male'))
