#!/usr/bin/env python3

import cachetools.func
import asyncio
import io
import glob
import os
import tempfile

import edge_tts
import gtts

import utils


VOICES = {'af': {'female': 'af-ZA-AdriNeural', 'male': 'af-ZA-WillemNeural'}, 'am': {'male': 'am-ET-AmehaNeural', 'female': 'am-ET-MekdesNeural'}, 'ar': {'female': 'ar-YE-MaryamNeural', 'male': 'ar-YE-SalehNeural'}, 'az': {'male': 'az-AZ-BabekNeural', 'female': 'az-AZ-BanuNeural'}, 'bg': {'male': 'bg-BG-BorislavNeural', 'female': 'bg-BG-KalinaNeural'}, 'bn': {'female': 'bn-IN-TanishaaNeural', 'male': 'bn-IN-BashkarNeural'}, 'bs': {'male': 'bs-BA-GoranNeural', 'female': 'bs-BA-VesnaNeural'}, 'ca': {'male': 'ca-ES-EnricNeural', 'female': 'ca-ES-JoanaNeural'}, 'cs': {'male': 'cs-CZ-AntoninNeural', 'female': 'cs-CZ-VlastaNeural'}, 'cy': {'male': 'cy-GB-AledNeural', 'female': 'cy-GB-NiaNeural'}, 'da': {'female': 'da-DK-ChristelNeural', 'male': 'da-DK-JeppeNeural'}, 'de': {'female': 'de-DE-SeraphinaMultilingualNeural', 'male': 'de-DE-KillianNeural'}, 'el': {'female': 'el-GR-AthinaNeural', 'male': 'el-GR-NestorasNeural'}, 'en': {'female': 'en-ZA-LeahNeural', 'male': 'en-ZA-LukeNeural'}, 'es': {'female': 'es-VE-PaolaNeural', 'male': 'es-VE-SebastianNeural'}, 'et': {'female': 'et-EE-AnuNeural', 'male': 'et-EE-KertNeural'}, 'fa': {'female': 'fa-IR-DilaraNeural', 'male': 'fa-IR-FaridNeural'}, 'fi': {'male': 'fil-PH-AngeloNeural', 'female': 'fil-PH-BlessicaNeural'}, 'fr': {'female': 'fr-FR-VivienneMultilingualNeural', 'male': 'fr-FR-RemyMultilingualNeural'}, 'ga': {'male': 'ga-IE-ColmNeural', 'female': 'ga-IE-OrlaNeural'}, 'gl': {'male': 'gl-ES-RoiNeural', 'female': 'gl-ES-SabelaNeural'}, 'gu': {'female': 'gu-IN-DhwaniNeural', 'male': 'gu-IN-NiranjanNeural'}, 'he': {'male': 'he-IL-AvriNeural', 'female': 'he-IL-HilaNeural'}, 'hi': {'male': 'hi-IN-MadhurNeural', 'female': 'hi-IN-SwaraNeural'}, 'hr': {'female': 'hr-HR-GabrijelaNeural', 'male': 'hr-HR-SreckoNeural'}, 'hu': {'female': 'hu-HU-NoemiNeural', 'male': 'hu-HU-TamasNeural'}, 'id': {'male': 'id-ID-ArdiNeural', 'female': 'id-ID-GadisNeural'}, 'is': {'female': 'is-IS-GudrunNeural', 'male': 'is-IS-GunnarNeural'}, 'it': {'male': 'it-IT-GiuseppeNeural', 'female': 'it-IT-IsabellaNeural'}, 'ja': {'male': 'ja-JP-KeitaNeural', 'female': 'ja-JP-NanamiNeural'}, 'jv': {'male': 'jv-ID-DimasNeural', 'female': 'jv-ID-SitiNeural'}, 'ka': {'female': 'ka-GE-EkaNeural', 'male': 'ka-GE-GiorgiNeural'}, 'kk': {'female': 'kk-KZ-AigulNeural', 'male': 'kk-KZ-DauletNeural'}, 'km': {'male': 'km-KH-PisethNeural', 'female': 'km-KH-SreymomNeural'}, 'kn': {'male': 'kn-IN-GaganNeural', 'female': 'kn-IN-SapnaNeural'}, 'ko': {'male': 'ko-KR-InJoonNeural', 'female': 'ko-KR-SunHiNeural'}, 'lo': {'male': 'lo-LA-ChanthavongNeural', 'female': 'lo-LA-KeomanyNeural'}, 'lt': {'male': 'lt-LT-LeonasNeural', 'female': 'lt-LT-OnaNeural'}, 'lv': {'female': 'lv-LV-EveritaNeural', 'male': 'lv-LV-NilsNeural'}, 'mk': {'male': 'mk-MK-AleksandarNeural', 'female': 'mk-MK-MarijaNeural'}, 'ml': {'male': 'ml-IN-MidhunNeural', 'female': 'ml-IN-SobhanaNeural'}, 'mn': {'male': 'mn-MN-BataaNeural', 'female': 'mn-MN-YesuiNeural'}, 'mr': {'female': 'mr-IN-AarohiNeural', 'male': 'mr-IN-ManoharNeural'}, 'ms': {'male': 'ms-MY-OsmanNeural', 'female': 'ms-MY-YasminNeural'}, 'mt': {'female': 'mt-MT-GraceNeural', 'male': 'mt-MT-JosephNeural'}, 'my': {'female': 'my-MM-NilarNeural', 'male': 'my-MM-ThihaNeural'}, 'nb': {'male': 'nb-NO-FinnNeural', 'female': 'nb-NO-PernilleNeural'}, 'ne': {'female': 'ne-NP-HemkalaNeural', 'male': 'ne-NP-SagarNeural'}, 'nl': {'male': 'nl-NL-MaartenNeural', 'female': 'nl-NL-FennaNeural'}, 'pl': {'male': 'pl-PL-MarekNeural', 'female': 'pl-PL-ZofiaNeural'}, 'ps': {'male': 'ps-AF-GulNawazNeural', 'female': 'ps-AF-LatifaNeural'}, 'pt': {'male': 'pt-PT-DuarteNeural', 'female': 'pt-PT-RaquelNeural'}, 'ro': {'female': 'ro-RO-AlinaNeural', 'male': 'ro-RO-EmilNeural'}, 'ru': {'male': 'ru-RU-DmitryNeural', 'female': 'ru-RU-SvetlanaNeural'}, 'si': {'male': 'si-LK-SameeraNeural', 'female': 'si-LK-ThiliniNeural'}, 'sk': {'male': 'sk-SK-LukasNeural', 'female': 'sk-SK-ViktoriaNeural'}, 'sl': {'female': 'sl-SI-PetraNeural', 'male': 'sl-SI-RokNeural'}, 'so': {'male': 'so-SO-MuuseNeural', 'female': 'so-SO-UbaxNeural'}, 'sq': {'female': 'sq-AL-AnilaNeural', 'male': 'sq-AL-IlirNeural'}, 'sr': {'male': 'sr-RS-NicholasNeural', 'female': 'sr-RS-SophieNeural'}, 'su': {'male': 'su-ID-JajangNeural', 'female': 'su-ID-TutiNeural'}, 'sv': {'male': 'sv-SE-MattiasNeural', 'female': 'sv-SE-SofieNeural'}, 'sw': {'male': 'sw-TZ-DaudiNeural', 'female': 'sw-TZ-RehemaNeural'}, 'ta': {'female': 'ta-SG-VenbaNeural', 'male': 'ta-SG-AnbuNeural'}, 'te': {'male': 'te-IN-MohanNeural', 'female': 'te-IN-ShrutiNeural'}, 'th': {'male': 'th-TH-NiwatNeural', 'female': 'th-TH-PremwadeeNeural'}, 'tr': {'male': 'tr-TR-AhmetNeural', 'female': 'tr-TR-EmelNeural'}, 'uk': {'male': 'uk-UA-OstapNeural', 'female': 'uk-UA-PolinaNeural'}, 'ur': {'female': 'ur-PK-UzmaNeural', 'male': 'ur-PK-AsadNeural'}, 'uz': {'female': 'uz-UZ-MadinaNeural', 'male': 'uz-UZ-SardorNeural'}, 'vi': {'female': 'vi-VN-HoaiMyNeural', 'male': 'vi-VN-NamMinhNeural'}, 'zh': {'female': 'zh-TW-HsiaoYuNeural', 'male': 'zh-TW-YunJheNeural'}, 'zu': {'female': 'zu-ZA-ThandoNeural', 'male': 'zu-ZA-ThembaNeural'}}


# cleanup
for filePath in [x for x in glob.glob('*.wav') + glob.glob('*.ogg') + glob.glob('*.mp4') + glob.glob('*.mp3') if 'temp_tts_file' in x]:
    try:
        utils.remove_file(filePath)
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
    return data


def get_voice(language_code: str, gender: str = 'female'):
    """принимает двухбуквенное обозначение языка и возвращает голосовой движок для его озвучки
    gender = 'male' or 'female'"""
    
    assert gender in ('male', 'female')

    # белорусский язык это скорее всего ошибка автоопределителя, но в любом случае такой язык не поддерживается, меняем на украинский
    if language_code == 'be':
        language_code = 'uk'

    if language_code == 'ua':
        language_code = 'uk'
    return VOICES[language_code][gender]


@cachetools.func.ttl_cache(maxsize=10, ttl=10 * 60)
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

    utils.remove_file(filename)
    # Возвращаем байтовый поток с аудио
    data = data.getvalue()

    return data


if __name__ == "__main__":
    print(VOICES['ru'])
