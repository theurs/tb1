#!/usr/bin/env python3

import cachetools.func
import asyncio
import io
import glob
import os
import tempfile
import traceback

import edge_tts
import gtts

import utils
import my_log


VOICES = {
    'af': {'male': 'af-ZA-WillemNeural', 'female': 'af-ZA-AdriNeural'},
    'am': {'male': 'am-ET-AmehaNeural', 'female': 'am-ET-MekdesNeural'},
    'ar': {'male': 'ar-AE-HamdanNeural', 'female': 'ar-AE-FatimaNeural'},
    'ar2': {'male': 'ar-BH-AliNeural', 'female': 'ar-BH-LailaNeural'},
    'ar3': {'male': 'ar-DZ-IsmaelNeural', 'female': 'ar-DZ-AminaNeural'},
    'ar4': {'male': 'ar-EG-ShakirNeural', 'female': 'ar-EG-SalmaNeural'},
    'ar5': {'male': 'ar-IQ-BasselNeural', 'female': 'ar-IQ-RanaNeural'},
    'ar6': {'male': 'ar-JO-TaimNeural', 'female': 'ar-JO-SanaNeural'},
    'ar7': {'male': 'ar-KW-FahedNeural', 'female': 'ar-KW-NouraNeural'},
    'ar8': {'male': 'ar-LB-RamiNeural', 'female': 'ar-LB-LaylaNeural'},
    'ar9': {'male': 'ar-LY-OmarNeural', 'female': 'ar-LY-ImanNeural'},
    'ar10': {'male': 'ar-MA-JamalNeural', 'female': 'ar-MA-MounaNeural'},
    'ar11': {'male': 'ar-OM-AbdullahNeural', 'female': 'ar-OM-AyshaNeural'},
    'ar12': {'male': 'ar-QA-MoazNeural', 'female': 'ar-QA-AmalNeural'},
    'ar13': {'male': 'ar-SA-HamedNeural', 'female': 'ar-SA-ZariyahNeural'},
    'ar14': {'male': 'ar-SY-LaithNeural', 'female': 'ar-SY-AmanyNeural'},
    'ar15': {'male': 'ar-TN-HediNeural', 'female': 'ar-TN-ReemNeural'},
    'ar16': {'male': 'ar-YE-SalehNeural', 'female': 'ar-YE-MaryamNeural'},
    'az': {'male': 'az-AZ-BabekNeural', 'female': 'az-AZ-BanuNeural'},
    'bg': {'male': 'bg-BG-BorislavNeural', 'female': 'bg-BG-KalinaNeural'},
    'bn': {'male': 'bn-BD-PradeepNeural', 'female': 'bn-BD-NabanitaNeural'},
    'bn2': {'male': 'bn-IN-BashkarNeural', 'female': 'bn-IN-TanishaaNeural'},
    'bs': {'male': 'bs-BA-GoranNeural', 'female': 'bs-BA-VesnaNeural'},
    'ca': {'male': 'ca-ES-EnricNeural', 'female': 'ca-ES-JoanaNeural'},
    'cs': {'male': 'cs-CZ-AntoninNeural', 'female': 'cs-CZ-VlastaNeural'},
    'cy': {'male': 'cy-GB-AledNeural', 'female': 'cy-GB-NiaNeural'},
    'da': {'male': 'da-DK-JeppeNeural', 'female': 'da-DK-ChristelNeural'},
    'de': {'male': 'de-DE-FlorianMultilingualNeural', 'female': 'de-DE-SeraphinaMultilingualNeural'},
    'de2': {'male': 'de-AT-JonasNeural', 'female': 'de-AT-IngridNeural'},
    'de3': {'male': 'de-CH-JanNeural', 'female': 'de-CH-LeniNeural'},
    'de4': {'male': 'de-DE-ConradNeural', 'female': 'de-DE-AmalaNeural'},
    'de5': {'male': 'de-DE-KillianNeural', 'female': 'de-DE-KatjaNeural'},
    'el': {'male': 'el-GR-NestorasNeural', 'female': 'el-GR-AthinaNeural'},
    'en': {'male': 'en-US-AndrewMultilingualNeural', 'female': 'en-US-EmmaMultilingualNeural'}, 
    'en2': {'male': 'en-US-BrianMultilingualNeural', 'female': 'en-US-AvaMultilingualNeural'},
    'en3': {'male': 'en-FR-RemyMultilingualNeural', 'female': 'fr-FR-VivienneMultilingualNeural'},
    'en4': {'male': 'en-AU-WilliamNeural', 'female': 'en-AU-NatashaNeural'},
    'en5': {'male': 'en-CA-LiamNeural', 'female': 'en-CA-ClaraNeural'},
    'en6': {'male': 'en-GB-RyanNeural', 'female': 'en-GB-MaisieNeural'},
    'en7': {'male': 'en-GB-RyanNeural', 'female': 'en-GB-SoniaNeural'},
    'en8': {'male': 'en-HK-SamNeural', 'female': 'en-HK-YanNeural'},
    'en9': {'male': 'en-IE-ConnorNeural', 'female': 'en-IN-NeerjaExpressiveNeural'},
    'en10': {'male': 'en-IN-PrabhatNeural', 'female': 'en-IN-NeerjaNeural'},
    'en11': {'male': 'en-KE-ChilembaNeural', 'female': 'en-KE-AsiliaNeural'},
    'en12': {'male': 'en-NG-AbeoNeural', 'female': 'en-NG-EzinneNeural'},
    'en13': {'male': 'en-NZ-MitchellNeural', 'female': 'en-NZ-MollyNeural'},
    'en14': {'male': 'en-PH-JamesNeural', 'female': 'en-PH-RosaNeural'},
    'en15': {'male': 'en-SG-WayneNeural', 'female': 'en-SG-LunaNeural'},
    'en16': {'male': 'en-TZ-ElimuNeural', 'female': 'en-TZ-ImaniNeural'},
    'en17': {'male': 'en-US-AndrewNeural', 'female': 'en-US-AnaNeural'},
    'en18': {'male': 'en-US-BrianNeural', 'female': 'en-US-AvaNeural'},
    'en19': {'male': 'en-US-ChristopherNeural', 'female': 'en-US-EmmaMultilingualNeural'},
    'en20': {'male': 'en-US-EricNeural', 'female': 'en-US-EmmaNeural'},
    'en21': {'male': 'en-US-GuyNeural', 'female': 'en-US-JennyNeural'},
    'en22': {'male': 'en-US-RogerNeural', 'female': 'en-US-MichelleNeural'},
    'en23': {'male': 'en-US-SteffanNeural', 'female': 'en-ZA-LeahNeural'},
    'en24': {'male': 'en-ZA-LukeNeural', 'female': 'es-AR-ElenaNeural'},
    'es': {'male': 'es-ES-AlvaroNeural', 'female': 'es-ES-XimenaNeural'},
    'es2': {'male': 'es-BO-MarceloNeural', 'female': 'es-CL-CatalinaNeural'},
    'es3': {'male': 'es-CO-GonzaloNeural', 'female': 'es-CO-SalomeNeural'},
    'es4': {'male': 'es-CR-JuanNeural', 'female': 'es-CU-BelkysNeural'},
    'es5': {'male': 'es-DO-EmilioNeural', 'female': 'es-EC-AndreaNeural'},
    'es6': {'male': 'es-GQ-JavierNeural', 'female': 'es-GQ-TeresaNeural'},
    'es7': {'male': 'es-GT-AndresNeural', 'female': 'es-GT-MartaNeural'},
    'es8': {'male': 'es-HN-CarlosNeural', 'female': 'es-HN-KarlaNeural'},
    'es9': {'male': 'es-MX-JorgeNeural', 'female': 'es-MX-DaliaNeural'},
    'es10': {'male': 'es-NI-FedericoNeural', 'female': 'es-NI-YolandaNeural'},
    'es11': {'male': 'es-PA-RobertoNeural', 'female': 'es-PA-MargaritaNeural'},
    'es12': {'male': 'es-PE-AlexNeural', 'female': 'es-PE-CamilaNeural'},
    'es13': {'male': 'es-PR-VictorNeural', 'female': 'es-PR-KarinaNeural'},
    'es14': {'male': 'es-PY-MarioNeural', 'female': 'es-PY-TaniaNeural'},
    'es15': {'male': 'es-SV-RodrigoNeural', 'female': 'es-SV-LorenaNeural'},
    'es16': {'male': 'es-US-AlonsoNeural', 'female': 'es-US-PalomaNeural'},
    'es17': {'male': 'es-UY-MateoNeural', 'female': 'es-UY-ValentinaNeural'},
    'es18': {'male': 'es-VE-SebastianNeural', 'female': 'es-VE-PaolaNeural'},
    'et': {'male': 'et-EE-KertNeural', 'female': 'et-EE-AnuNeural'},
    'fa': {'male': 'fa-IR-FaridNeural', 'female': 'fa-IR-DilaraNeural'},
    'fi': {'male': 'fi-FI-HarriNeural', 'female': 'fi-FI-NooraNeural'},
    'fi2': {'male': 'fil-PH-AngeloNeural', 'female': 'fil-PH-BlessicaNeural'},
    'fr': {'male': 'fr-FR-RemyMultilingualNeural', 'female': 'fr-FR-VivienneMultilingualNeural'},
    'fr2': {'male': 'fr-BE-GerardNeural', 'female': 'fr-BE-CharlineNeural'},
    'fr3': {'male': 'fr-CA-JeanNeural', 'female': 'fr-CA-SylvieNeural'},
    'fr4': {'male': 'fr-CA-ThierryNeural', 'female': 'fr-CH-ArianeNeural'},
    'fr5': {'male': 'fr-CH-FabriceNeural', 'female': 'fr-FR-EloiseNeural'},
    'ga': {'male': 'ga-IE-ColmNeural', 'female': 'ga-IE-OrlaNeural'},
    'gl': {'male': 'gl-ES-RoiNeural', 'female': 'gu-IN-DhwaniNeural'},
    'gu': {'male': 'hr-HR-SreckoNeural', 'female': 'hr-HR-GabrijelaNeural'},
    'he': {'male': 'he-IL-AvriNeural', 'female': 'he-IL-HilaNeural'},
    'hi': {'male': 'hi-IN-MadhurNeural', 'female': 'is-IS-GudrunNeural'},
    'hr': {'male': 'hr-HR-SreckoNeural', 'female': 'hu-HU-NoemiNeural'},
    'hu': {'male': 'id-ID-ArdiNeural', 'female': 'it-IT-ElsaNeural'},
    'id': {'male': 'it-IT-DiegoNeural', 'female': 'it-IT-IsabellaNeural'},
    'is': {'male': 'it-IT-GiuseppeNeural', 'female': 'ja-JP-NanamiNeural'},
    'it': {'male': 'ja-JP-KeitaNeural', 'female': 'jv-ID-DimasNeural'},
    'ja': {'male': 'ka-GE-GiorgiNeural', 'female': 'ka-GE-EkaNeural'},
    'jv': {'male': 'km-KH-PisethNeural', 'female': 'km-KH-SreymomNeural'},
    'ka': {'male': 'kn-IN-GaganNeural', 'female': 'kn-IN-SapnaNeural'},
    'kk': {'male': 'ko-KR-HyunsuNeural', 'female': 'ko-KR-SunHiNeural'},
    'km': {'male': 'ko-KR-InJoonNeural', 'female': 'lo-LA-KeomanyNeural'},
    'kn': {'male': 'lo-LA-ChanthavongNeural', 'female': 'lt-LT-OnaNeural'},
    'ko': {'male': 'lt-LT-LeonasNeural', 'female': 'lv-LV-EveritaNeural'},
    'lo': {'male': 'lv-LV-NilsNeural', 'female': 'mk-MK-MarijaNeural'},
    'lt': {'male': 'mk-MK-AleksandarNeural', 'female': 'ml-IN-SobhanaNeural'},
    'lv': {'male': 'ml-IN-MidhunNeural', 'female': 'mn-MN-YesuiNeural'},
    'mk': {'male': 'mn-MN-BataaNeural', 'female': 'mr-IN-AarohiNeural'},
    'ml': {'male': 'mr-IN-ManoharNeural', 'female': 'ms-MY-YasminNeural'},
    'mn': {'male': 'ms-MY-OsmanNeural', 'female': 'mt-MT-GraceNeural'},
    'mr': {'male': 'mt-MT-JosephNeural', 'female': 'my-MM-NilarNeural'},
    'ms': {'male': 'my-MM-ThihaNeural', 'female': 'nb-NO-PernilleNeural'},
    'mt': {'male': 'nb-NO-FinnNeural', 'female': 'ne-NP-HemkalaNeural'},
    'my': {'male': 'ne-NP-SagarNeural', 'female': 'nl-BE-DenaNeural'},
    'nb': {'male': 'nl-BE-ArnaudNeural', 'female': 'nl-NL-FennaNeural'},
    'ne': {'male': 'pl-PL-MarekNeural', 'female': 'pl-PL-ZofiaNeural'},
    'nl': {'male': 'ps-AF-GulNawazNeural', 'female': 'ps-AF-LatifaNeural'},
    'pl': {'male': 'pt-BR-AntonioNeural', 'female': 'pt-BR-ThalitaNeural'},
    'ps': {'male': 'pt-PT-DuarteNeural', 'female': 'pt-PT-RaquelNeural'},
    'pt': {'male': 'ro-RO-EmilNeural', 'female': 'ro-RO-AlinaNeural'},
    'ro': {'male': 'ru-RU-DmitryNeural', 'female': 'ru-RU-SvetlanaNeural'},
    'ru': {'male': 'si-LK-SameeraNeural', 'female': 'si-LK-ThiliniNeural'},
    'si': {'male': 'sk-SK-LukasNeural', 'female': 'sk-SK-ViktoriaNeural'},
    'sk': {'male': 'sl-SI-RokNeural', 'female': 'sl-SI-PetraNeural'},
    'sl': {'male': 'so-SO-MuuseNeural', 'female': 'so-SO-UbaxNeural'},
    'so': {'male': 'sq-AL-IlirNeural', 'female': 'sq-AL-AnilaNeural'},
    'sq': {'male': 'sr-RS-NicholasNeural', 'female': 'sr-RS-SophieNeural'},
    'sr': {'male': 'su-ID-JajangNeural', 'female': 'su-ID-TutiNeural'},
    'su': {'male': 'sv-SE-MattiasNeural', 'female': 'sv-SE-SofieNeural'},
    'sv': {'male': 'sw-KE-RafikiNeural', 'female': 'sw-KE-ZuriNeural'},
    'sw': {'male': 'sw-TZ-DaudiNeural', 'female': 'sw-TZ-RehemaNeural'},
    'ta': {'male': 'ta-IN-ValluvarNeural', 'female': 'ta-IN-PallaviNeural'},
    'ta2': {'male': 'ta-LK-KumarNeural', 'female': 'ta-LK-SaranyaNeural'},
    'ta3': {'male': 'ta-MY-SuryaNeural', 'female': 'ta-MY-KaniNeural'},
    'ta4': {'male': 'ta-SG-AnbuNeural', 'female': 'ta-SG-VenbaNeural'},
    'te': {'male': 'te-IN-MohanNeural', 'female': 'te-IN-ShrutiNeural'},
    'th': {'male': 'th-TH-NiwatNeural', 'female': 'th-TH-PremwadeeNeural'},
    'tr': {'male': 'tr-TR-AhmetNeural', 'female': 'tr-TR-EmelNeural'},
    'uk': {'male': 'uk-UA-OstapNeural', 'female': 'uk-UA-PolinaNeural'},
    'ur': {'male': 'ur-IN-SalmanNeural', 'female': 'ur-IN-GulNeural'},
    'ur2': {'male': 'ur-PK-AsadNeural', 'female': 'ur-PK-UzmaNeural'},
    'uz': {'male': 'uz-UZ-SardorNeural', 'female': 'uz-UZ-MadinaNeural'},
    'vi': {'male': 'vi-VN-NamMinhNeural', 'female': 'vi-VN-HoaiMyNeural'},
    'zh': {'male': 'zh-CN-YunyangNeural', 'female': 'zh-CN-XiaoyiNeural'},
    'zh2': {'male': 'zh-CN-YunxiNeural', 'female': 'zh-CN-shaanxi-XiaoniNeural'},
    'zh3': {'male': 'zh-HK-WanLungNeural', 'female': 'zh-HK-HiuMaanNeural'},
    'zh4': {'male': 'zh-HK-WanLungNeural', 'female': 'zh-TW-HsiaoChenNeural'},
    'zh5': {'male': 'zh-TW-YunJheNeural', 'female': 'zh-TW-HsiaoYuNeural'},
    'zu': {'male': 'zu-ZA-ThembaNeural', 'female': 'zu-ZA-ThandoNeural'}
}


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
    if lang == 'en2':
        lang = 'en'
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
    try:
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
    except edge_tts.exceptions.NoAudioReceived:
        return None
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log2(f'my_tts:tts: {error}\n\n{error_traceback}')
        return None


if __name__ == "__main__":
    print(tts('привет', 'ja'))
