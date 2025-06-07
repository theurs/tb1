#!/usr/bin/env python3

import cachetools.func
import io
import glob
import os
import re
import subprocess
import tempfile
import traceback

import edge_tts
import gtts
from langdetect import detect

import my_log
import my_gemini_tts
import my_openai_voice
import utils


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
    'en': {'male': 'en-US-AndrewMultilingualNeural', 'female': 'en-US-AvaMultilingualNeural'},
    'en2': {'male': 'en-US-BrianMultilingualNeural', 'female': 'en-US-EmmaMultilingualNeural'},
    'en3': {'male': 'en-AU-WilliamNeural', 'female': 'en-AU-NatashaNeural'},
    'en4': {'male': 'en-CA-LiamNeural', 'female': 'en-CA-ClaraNeural'},
    'en5': {'male': 'en-GB-RyanNeural', 'female': 'en-GB-LibbyNeural'},
    'en6': {'male': 'en-GB-ThomasNeural', 'female': 'en-GB-MaisieNeural'},
    'en7': {'male': None, 'female': 'en-GB-SoniaNeural'},
    'en8': {'male': 'en-HK-SamNeural', 'female': 'en-HK-YanNeural'},
    'en9': {'male': 'en-IE-ConnorNeural', 'female': 'en-IE-EmilyNeural'},
    'en10': {'male': 'en-IN-PrabhatNeural', 'female': 'en-IN-NeerjaExpressiveNeural'},
    'en11': {'male': None, 'female': 'en-IN-NeerjaNeural'},
    'en12': {'male': 'en-KE-ChilembaNeural', 'female': 'en-KE-AsiliaNeural'},
    'en13': {'male': 'en-NG-AbeoNeural', 'female': 'en-NG-EzinneNeural'},
    'en14': {'male': 'en-NZ-MitchellNeural', 'female': 'en-NZ-MollyNeural'},
    'en15': {'male': 'en-PH-JamesNeural', 'female': 'en-PH-RosaNeural'},
    'en16': {'male': 'en-SG-WayneNeural', 'female': 'en-SG-LunaNeural'},
    'en17': {'male': 'en-TZ-ElimuNeural', 'female': 'en-TZ-ImaniNeural'},
    'en18': {'male': 'en-US-AndrewNeural', 'female': 'en-US-AnaNeural'},
    'en19': {'male': 'en-US-BrianNeural', 'female': 'en-US-AriaNeural'},
    'en20': {'male': 'en-US-ChristopherNeural', 'female': 'en-US-AvaNeural'},
    'en21': {'male': 'en-US-EricNeural', 'female': 'en-US-EmmaNeural'},
    'en22': {'male': 'en-US-GuyNeural', 'female': 'en-US-JennyNeural'},
    'en23': {'male': 'en-US-RogerNeural', 'female': 'en-US-MichelleNeural'},
    'en24': {'male': 'en-US-SteffanNeural', 'female': None},
    'en25': {'male': 'en-ZA-LukeNeural', 'female': 'en-ZA-LeahNeural'},
    'es': {'male': 'es-AR-TomasNeural', 'female': 'es-AR-ElenaNeural'},
    'es2': {'male': 'es-BO-MarceloNeural', 'female': 'es-BO-SofiaNeural'},
    'es3': {'male': 'es-CL-LorenzoNeural', 'female': 'es-CL-CatalinaNeural'},
    'es4': {'male': 'es-CO-GonzaloNeural', 'female': 'es-CO-SalomeNeural'},
    'es5': {'male': 'es-CR-JuanNeural', 'female': 'es-CR-MariaNeural'},
    'es6': {'male': 'es-CU-ManuelNeural', 'female': 'es-CU-BelkysNeural'},
    'es7': {'male': 'es-DO-EmilioNeural', 'female': 'es-DO-RamonaNeural'},
    'es8': {'male': 'es-EC-LuisNeural', 'female': 'es-EC-AndreaNeural'},
    'es9': {'male': 'es-ES-AlvaroNeural', 'female': 'es-ES-ElviraNeural'},
    'es10': {'male': None, 'female': 'es-ES-XimenaNeural'},
    'es11': {'male': 'es-GQ-JavierNeural', 'female': 'es-GQ-TeresaNeural'},
    'es12': {'male': 'es-GT-AndresNeural', 'female': 'es-GT-MartaNeural'},
    'es13': {'male': 'es-HN-CarlosNeural', 'female': 'es-HN-KarlaNeural'},
    'es14': {'male': 'es-MX-JorgeNeural', 'female': 'es-MX-DaliaNeural'},
    'es15': {'male': 'es-NI-FedericoNeural', 'female': 'es-NI-YolandaNeural'},
    'es16': {'male': 'es-PA-RobertoNeural', 'female': 'es-PA-MargaritaNeural'},
    'es17': {'male': 'es-PE-AlexNeural', 'female': 'es-PE-CamilaNeural'},
    'es18': {'male': 'es-PR-VictorNeural', 'female': 'es-PR-KarinaNeural'},
    'es19': {'male': 'es-PY-MarioNeural', 'female': 'es-PY-TaniaNeural'},
    'es20': {'male': 'es-SV-RodrigoNeural', 'female': 'es-SV-LorenaNeural'},
    'es21': {'male': 'es-US-AlonsoNeural', 'female': 'es-US-PalomaNeural'},
    'es22': {'male': 'es-UY-MateoNeural', 'female': 'es-UY-ValentinaNeural'},
    'es23': {'male': 'es-VE-SebastianNeural', 'female': 'es-VE-PaolaNeural'},
    'et': {'male': 'et-EE-KertNeural', 'female': 'et-EE-AnuNeural'},
    'fa': {'male': 'fa-IR-FaridNeural', 'female': 'fa-IR-DilaraNeural'},
    'fi': {'male': 'fi-FI-HarriNeural', 'female': 'fi-FI-NooraNeural'},
    'fil': {'male': 'fil-PH-AngeloNeural', 'female': 'fil-PH-BlessicaNeural'},
    'fr': {'male': 'fr-FR-RemyMultilingualNeural', 'female': 'fr-FR-VivienneMultilingualNeural'},
    'fr2': {'male': 'fr-BE-GerardNeural', 'female': 'fr-BE-CharlineNeural'},
    'fr3': {'male': 'fr-CA-AntoineNeural', 'female': 'fr-CA-SylvieNeural'},
    'fr4': {'male': 'fr-CA-JeanNeural', 'female': None},
    'fr5': {'male': 'fr-CA-ThierryNeural', 'female': None},
    'fr6': {'male': 'fr-CH-FabriceNeural', 'female': 'fr-CH-ArianeNeural'},
    'fr7': {'male': 'fr-FR-HenriNeural', 'female': 'fr-FR-DeniseNeural'},
    'fr8': {'male': None, 'female': 'fr-FR-EloiseNeural'},
    'ga': {'male': 'ga-IE-ColmNeural', 'female': 'ga-IE-OrlaNeural'},
    'gl': {'male': 'gl-ES-RoiNeural', 'female': 'gl-ES-SabelaNeural'},
    'gu': {'male': 'gu-IN-NiranjanNeural', 'female': 'gu-IN-DhwaniNeural'},
    'he': {'male': 'he-IL-AvriNeural', 'female': 'he-IL-HilaNeural'},
    'hi': {'male': 'hi-IN-MadhurNeural', 'female': 'hi-IN-SwaraNeural'},
    'hr': {'male': 'hr-HR-SreckoNeural', 'female': 'hr-HR-GabrijelaNeural'},
    'hu': {'male': 'hu-HU-TamasNeural', 'female': 'hu-HU-NoemiNeural'},
    'id': {'male': 'id-ID-ArdiNeural', 'female': 'id-ID-GadisNeural'},
    'is': {'male': 'is-IS-GunnarNeural', 'female': 'is-IS-GudrunNeural'},
    'it1': {'male': 'it-IT-GiuseppeMultilingualNeural', 'female': None},
    'it2': {'male': 'it-IT-DiegoNeural', 'female': 'it-IT-ElsaNeural'},
    'it3': {'male': None, 'female': 'it-IT-IsabellaNeural'},
    'iu': {'male': 'iu-Cans-CA-TaqqiqNeural', 'female': 'iu-Cans-CA-SiqiniqNeural'},
    'iu2': {'male': 'iu-Latn-CA-TaqqiqNeural', 'female': 'iu-Latn-CA-SiqiniqNeural'},
    'ja': {'male': 'ja-JP-KeitaNeural', 'female': 'ja-JP-NanamiNeural'},
    'jv': {'male': 'jv-ID-DimasNeural', 'female': 'jv-ID-SitiNeural'},
    'ka': {'male': 'ka-GE-GiorgiNeural', 'female': 'ka-GE-EkaNeural'},
    'kk': {'male': 'kk-KZ-DauletNeural', 'female': 'kk-KZ-AigulNeural'},
    'km': {'male': 'km-KH-PisethNeural', 'female': 'km-KH-SreymomNeural'},
    'kn': {'male': 'kn-IN-GaganNeural', 'female': 'kn-IN-SapnaNeural'},
    'ko1': {'male': 'ko-KR-HyunsuMultilingualNeural', 'female': None},
    'ko2': {'male': 'ko-KR-InJoonNeural', 'female': 'ko-KR-SunHiNeural'},
    'lo': {'male': 'lo-LA-ChanthavongNeural', 'female': 'lo-LA-KeomanyNeural'},
    'lt': {'male': 'lt-LT-LeonasNeural', 'female': 'lt-LT-OnaNeural'},
    'lv': {'male': 'lv-LV-NilsNeural', 'female': 'lv-LV-EveritaNeural'},
    'mk': {'male': 'mk-MK-AleksandarNeural', 'female': 'mk-MK-MarijaNeural'},
    'ml': {'male': 'ml-IN-MidhunNeural', 'female': 'ml-IN-SobhanaNeural'},
    'mn': {'male': 'mn-MN-BataaNeural', 'female': 'mn-MN-YesuiNeural'},
    'mr': {'male': 'mr-IN-ManoharNeural', 'female': 'mr-IN-AarohiNeural'},
    'ms': {'male': 'ms-MY-OsmanNeural', 'female': 'ms-MY-YasminNeural'},
    'mt': {'male': 'mt-MT-JosephNeural', 'female': 'mt-MT-GraceNeural'},
    'my': {'male': 'my-MM-ThihaNeural', 'female': 'my-MM-NilarNeural'},
    'nb': {'male': 'nb-NO-FinnNeural', 'female': 'nb-NO-PernilleNeural'},
    'ne': {'male': 'ne-NP-SagarNeural', 'female': 'ne-NP-HemkalaNeural'},
    'nl': {'male': 'nl-BE-ArnaudNeural', 'female': 'nl-BE-DenaNeural'},
    'nl2': {'male': 'nl-NL-MaartenNeural', 'female': 'nl-NL-ColetteNeural'},
    'nl3': {'male': None, 'female': 'nl-NL-FennaNeural'},
    'pl': {'male': 'pl-PL-MarekNeural', 'female': 'pl-PL-ZofiaNeural'},
    'ps': {'male': 'ps-AF-GulNawazNeural', 'female': 'ps-AF-LatifaNeural'},
    'pt1': {'male': None, 'female': 'pt-BR-ThalitaMultilingualNeural'},
    'pt2': {'male': 'pt-BR-AntonioNeural', 'female': 'pt-BR-FranciscaNeural'},
    'pt3': {'male': 'pt-PT-DuarteNeural', 'female': 'pt-PT-RaquelNeural'},
    'ro': {'male': 'ro-RO-EmilNeural', 'female': 'ro-RO-AlinaNeural'},
    'ru': {'male': 'ru-RU-DmitryNeural', 'female': 'ru-RU-SvetlanaNeural'},
    'si': {'male': 'si-LK-SameeraNeural', 'female': 'si-LK-ThiliniNeural'},
    'sk': {'male': 'sk-SK-LukasNeural', 'female': 'sk-SK-ViktoriaNeural'},
    'sl': {'male': 'sl-SI-RokNeural', 'female': 'sl-SI-PetraNeural'},
    'so': {'male': 'so-SO-MuuseNeural', 'female': 'so-SO-UbaxNeural'},
    'sq': {'male': 'sq-AL-IlirNeural', 'female': 'sq-AL-AnilaNeural'},
    'sr': {'male': 'sr-RS-NicholasNeural', 'female': 'sr-RS-SophieNeural'},
    'su': {'male': 'su-ID-JajangNeural', 'female': 'su-ID-TutiNeural'},
    'sv': {'male': 'sv-SE-MattiasNeural', 'female': 'sv-SE-SofieNeural'},
    'sw': {'male': 'sw-KE-RafikiNeural', 'female': 'sw-KE-ZuriNeural'},
    'sw2': {'male': 'sw-TZ-DaudiNeural', 'female': 'sw-TZ-RehemaNeural'},
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
    'zh': {'male': 'zh-CN-YunjianNeural', 'female': 'zh-CN-XiaoxiaoNeural'},
    'zh2': {'male': 'zh-CN-YunxiNeural', 'female': 'zh-CN-XiaoyiNeural'},
    'zh3': {'male': 'zh-CN-YunxiaNeural', 'female': 'zh-CN-liaoning-XiaobeiNeural'},
    'zh4': {'male': 'zh-CN-YunyangNeural', 'female': 'zh-CN-shaanxi-XiaoniNeural'},
    'zh5': {'male': 'zh-HK-WanLungNeural', 'female': 'zh-HK-HiuGaaiNeural'},
    'zh6': {'male': None, 'female': 'zh-HK-HiuMaanNeural'},
    'zh7': {'male': 'zh-TW-YunJheNeural', 'female': 'zh-TW-HsiaoChenNeural'},
    'zh8': {'male': None, 'female': 'zh-TW-HsiaoYuNeural'},
    'zu': {'male': 'zu-ZA-ThembaNeural', 'female': 'zu-ZA-ThandoNeural'},
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
    lang = re.sub(r'\d', '', lang)
    mp3_fp = io.BytesIO()
    result = gtts.gTTS(text, lang=lang)
    result.write_to_fp(mp3_fp)
    mp3_fp.seek(0)
    data = mp3_fp.read()
    return data


def get_voice(language_code: str, gender: str = 'female'):
    """принимает двухбуквенное обозначение языка и возвращает голосовой движок для его озвучки
    gender = 'male' or 'female'"""

    if gender not in ('male', 'female'):
        gender = 'female'

    # белорусский язык это скорее всего ошибка автоопределителя, но в любом случае такой язык не поддерживается, меняем на украинский
    if language_code == 'be':
        language_code = 'uk'

    if language_code == 'ua':
        language_code = 'uk'
    return VOICES[language_code][gender] or ''


@cachetools.func.ttl_cache(maxsize=10, ttl=10 * 60)
def tts(text: str, voice: str = 'ru', rate: str = '+0%', gender: str = 'female') -> bytes | None:
    """
    Generates text-to-speech audio from the given input text using the specified voice, 
    speech rate, and gender.

    Args:
        text (str): The input text to convert to speech.
        voice (str, optional): The voice to use for the speech. Defaults to 'ru'.
        rate (str, optional): The speech rate. Defaults to '+0%'. (+-100%)
        gender (str, optional): The gender of the voice. Defaults to 'female'.

    Returns:
        bytes: The generated audio as a bytes object. Or None if an error occurs.
    """
    if '_' in voice:
        voice = voice.split('_')[0]

    lang = voice

    def change_speed(data: bytes, rate: str) -> bytes:
        '''Изменяет скорость речи'''
        new_data = change_audio_speed_and_format(data, rate)
        return new_data or data

    try:

        # если в начале текста есть <инструкция как надо произносить текст> то
        # вырезать ее из текста и сохранить в переменную prompt. искать в начале регэкспом
        # <инструкция как надо произносить текст> и вырезать ее.
        prompt = re.search(r'^<(.*?)>', text.strip(), re.DOTALL)
        instruction = ''
        if prompt:
            instruction = prompt.group(1)
            text = text[prompt.end():].strip()  # Обрезаем инструкцию и пробелы

        # remove 2 or more * from text with re, only paired like a markdown tag
        text = text.replace('***', '')
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
        text = re.sub(r'__([^_]+)__', r'\1', text)
        text = re.sub(r'~~([^~]+)~~', r'\1', text)

        result = ''

        if instruction:
            if gender == 'male':
                gender = 'openai_alloy'
            elif gender == 'female':
                gender = 'openai_coral'
            elif gender == 'google_female':
                gender = 'openai_nova'

        if gender == 'google_female':
            try:
                result = tts_google(text, lang)
            except Exception as e:
                if 'Language not supported' in str(e):
                    if str(e) not in ('he', 'uz'): # hebrew, uzbek are not supported by google
                        # my_log.log2(f'my_tts:1: tts_google: {e}')
                        pass
            if result:
                return change_speed(result, rate)
            else:
                gender = 'female'
        elif gender.startswith('openai_') and len(text) < 8 * 1024:
            try:
                result = my_openai_voice.openai_get_audio_bytes(text, voice = gender[7:], prompt=instruction)
                if result:
                    return change_speed(result, rate)
            except Exception as e:
                pass
        elif gender.startswith('gemini_') and len(text) < 30 * 1024:
            try:
                result = my_gemini_tts.generate_tts_wav_bytes(text, lang = lang, voice_name = gender[7:])
                if result:
                    return change_speed(result, rate)
            except Exception as e:
                pass

        voice = get_voice(voice, gender)
        # if not voice:
        #     voice = get_voice('de', gender)

        # Удаляем символы переноса строки и перевода каретки 
        text = text.replace('\r','')
        text = text.replace('\n\n','\n')
        # заменить ! на точку, с восклицательным знаком очень плохие переходы получаются
        if lang == 'ru':
            text = text.replace('!', '.')
            text = text.replace('«', '').replace('»', '')

        # Создаем временный файл для записи аудио
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as f: 
            filename = f.name 

        # Запускаем edge-tts для генерации аудио
        communicate = edge_tts.Communicate(text, voice)
        communicate.save_sync(filename)

        # Читаем аудио из временного файла 
        with open(filename, "rb") as f: 
            data = io.BytesIO(f.read())

        utils.remove_file(filename)
        # Возвращаем байтовый поток с аудио
        data = data.getvalue()

        if data:
            return change_speed(data, rate)
        else:
            result = tts_google(text, lang)
            if result:
                return change_speed(result, rate)
    except edge_tts.exceptions.NoAudioReceived:
        result = tts_google(text, lang)
        if result:
            return change_speed(result, rate)
        else:
            return None
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log2(f'my_tts:tts:2: {error}\n\n{error_traceback}')
        result = tts_google(text, lang)
        if result:
            return change_speed(result, rate)
        else:
            return None


def detect_lang_carefully(text: str) -> str:
    if len(text) < 30:
        return ''
    language = detect(text)
    return language


def change_audio_speed_and_format(input_audio: bytes | str, speed_factor_percent_str: str) -> bytes | None:
    """
    Changes the speed of the input audio (from bytes or a file path) using ffmpeg
    and encodes it to Opus format at 24 kbit/s.

    Args:
        input_audio (bytes | str): The input audio data as bytes, or a path to an audio file.
        speed_factor_percent_str (str): The speed change as a percentage string, relative to normal speed.
                                        Examples: "+0%", "0%" (normal speed),
                                        "+50%" (50% faster), "-25%" (25% slower).
                                        Allowed percentage values are between -100% and +100%.
                                        A value of -100% results in half speed (0.5x).
                                        A value of +100% results in double speed (2.0x).

    Returns:
        bytes | None: The processed audio as Opus bytes at 24 kbit/s, or None if an error occurs.
    """

    # Parse and validate speed_factor_percent_str
    if not isinstance(speed_factor_percent_str, str):
        my_log.log2(f"my_tts:change_audio_speed_and_format:invalid_sf_type: speed_factor must be a string. Got {type(speed_factor_percent_str)}")
        return None

    if not speed_factor_percent_str.endswith('%'):
        my_log.log2(f"my_tts:change_audio_speed_and_format:invalid_sf_format: speed_factor string must end with '%'. Got '{speed_factor_percent_str}'")
        return None

    try:
        percentage_str_val = speed_factor_percent_str.rstrip('%')
        percentage_value = float(percentage_str_val)
    except ValueError:
        my_log.log2(f"my_tts:change_audio_speed_and_format:invalid_sf_value: Could not parse percentage from speed_factor '{speed_factor_percent_str}'")
        return None

    # Validate input percentage range as per user's "+-0-100%"
    if not (-100.0 <= percentage_value <= 100.0):
        my_log.log2(f"my_tts:change_audio_speed_and_format:sf_out_of_range: Percentage value {percentage_value}% is out of the allowed range [-100%, +100%]. Input was '{speed_factor_percent_str}'.")
        return None

    # Convert percentage to atempo multiplier
    # Example: +50% -> 1.0 + (50/100) = 1.5
    # Example: -20% -> 1.0 + (-20/100) = 0.8
    # Example: -100% -> 1.0 + (-100/100) = 0.0
    atempo_multiplier = 1.0 + (percentage_value / 100.0)

    # Clamp atempo_multiplier to ffmpeg's supported range [0.5, 100.0]
    # For input percentages [-100%, +100%], atempo_multiplier is [0.0, 2.0].
    # So, we primarily need to ensure the lower bound of 0.5 for atempo.
    if atempo_multiplier < 0.5:
        atempo_multiplier = 0.5
    # The upper bound of 100.0 for atempo is well above our calculated max of 2.0,
    # so no explicit upper clamping is needed here if input percentage is constrained.
    # However, for robustness, if the constraint on percentage_value was different:
    # elif atempo_multiplier > 100.0:
    #     atempo_multiplier = 100.0


    audio_bytes_to_process: bytes | None = None

    if isinstance(input_audio, str):
        if os.path.exists(input_audio):
            try:
                with open(input_audio, "rb") as f:
                    audio_bytes_to_process = f.read()
            except Exception as e:
                error_traceback = traceback.format_exc()
                my_log.log2(f'my_tts:change_audio_speed_and_format:file_read_error: Error reading file {input_audio}: {e}\n\n{error_traceback}')
                return None
        else:
            my_log.log2(f'my_tts:change_audio_speed_and_format:file_not_found: File not found: {input_audio}')
            return None
    elif isinstance(input_audio, bytes):
        audio_bytes_to_process = input_audio
    else:
        my_log.log2(f'my_tts:change_audio_speed_and_format:invalid_input_type: Invalid input_audio type. Must be bytes or str path. Got {type(input_audio)}')
        return None

    if not audio_bytes_to_process:
        my_log.log2(f'my_tts:change_audio_speed_and_format:no_audio_data: No audio data to process after input handling.')
        return None


    ffmpeg_command = [
        'ffmpeg',
        '-hide_banner',         # Suppress printing banner
        '-loglevel', 'error',   # Only print errors
        '-i', '-',              # Input from stdin
        '-filter:a', f'atempo={atempo_multiplier}',
        '-ac', '2',             # Set audio channels to mono
        '-c:a', 'libopus',      # Specify opus codec
        '-b:a', '24k',          # Audio bitrate 24 kbit/s
        '-f', 'opus',           # Output format opus
        '-'                     # Output to stdout
    ]

    # my_log.log2(f"my_tts:change_audio_speed_and_format:ffmpeg_command: {' '.join(ffmpeg_command)}")

    stderr_data = None

    try:
        process = subprocess.Popen(
            ffmpeg_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout_data, stderr_data = process.communicate(input=audio_bytes_to_process)
        
        if process.returncode != 0:
            stderr_str = stderr_data.decode('utf-8', errors='ignore').strip()
            my_log.log2(f'my_tts:change_audio_speed_and_format:ffmpeg_error: FFmpeg failed with return code {process.returncode}.\nCommand: {" ".join(ffmpeg_command)}\nStderr:\n{stderr_str if stderr_str else "No stderr output."}')
            return None

        return stdout_data

    except FileNotFoundError:
        error_traceback = traceback.format_exc()
        my_log.log2(f"my_tts:change_audio_speed_and_format:ffmpeg_not_found: ffmpeg not found. Please ensure ffmpeg is installed and in your system's PATH.\n\n{error_traceback}")
        return None
    except Exception as e:
        error_traceback = traceback.format_exc()
        if stderr_data:
            stderr_str = stderr_data.decode('utf-8', errors='ignore').strip() if 'stderr_data' in locals() else "N/A"
            my_log.log2(f"my_tts:change_audio_speed_and_format:generic_error: An unexpected error occurred during ffmpeg processing: {e}\nCommand: {' '.join(ffmpeg_command)}\nStderr:\n{stderr_str}\n\n{error_traceback}")
        else:
            my_log.log2(f"my_tts:change_audio_speed_and_format:generic_error: An unexpected error occurred during ffmpeg processing: {e}\nCommand: {' '.join(ffmpeg_command)}\n\n{error_traceback}")
        return None


if __name__ == "__main__":
    pass

    # with open('C:/Users/user/Downloads/1.mp3', 'wb') as f:
    #     f.write(tts('привет как тебя зовут?', 'ru', '+0%', 'openai_nova'))

    # l = []
    # for k in VOICES:
    #     if k not in l:
    #         l.append(k)
    # print(l)
    # print(detect_lang_carefully('Однако здравствуйте, как ваше ничего сегодня? To continue effectively with.'))



    # with open(r"C:\Users\user\Downloads\кусок радио-т подкаста несколько голосов.opus", 'wb') as f2:
    #     data = change_audio_speed_and_format(r"C:\Users\user\Downloads\samples for ai\аудио\кусок радио-т подкаста несколько голосов.mp3", '-50%')
    #     if data:
    #         f2.write(data)
