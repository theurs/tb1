#!/usr/bin/env python3


import asyncio
import io
import glob
import os
import subprocess
import tempfile
import threading
from transliterate import translit
import sys
from urllib.parse import urlparse

import edge_tts
import gtts
import torch #silero

import cfg
import gpt_basic
import utils


# cleanup
for filePath in [x for x in glob.glob('*.wav') + glob.glob('*.ogg') if 'temp_tts_file' in x]:
    try:
        os.remove(filePath)
    except:
        print("Error while deleting file : ", filePath)


lock = threading.Lock()
# отложенная инициализация, только при вызове функции
DEVICE, MODEL = None, None


def tts_silero(text: str, voice: str = 'xenia') -> bytes:
    with lock:
        tmp_fname = 'temp_tts_file.ogg'
        tmp_wav_file = 'temp_tts_file.wav'
        try:
            os.remove(tmp_fname)
        except OSError:
            pass
        try:
            os.remove(tmp_wav_file)
        except OSError:
            pass

        result_files = []
        n = 1
        base_n = 'temp_tts_file-'
        
        for chunk in utils.split_text(text, 800):
            data = tts_silero_chunk(chunk, voice=voice)
            new_chunkfile = f'{base_n}{n}.wav'
            with open(new_chunkfile, 'wb') as f:
                f.write(data)
            result_files.append(new_chunkfile)
            n += 1

        subprocess.run(['sox'] + result_files + [tmp_wav_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(['ffmpeg', '-i', tmp_wav_file, '-c:a', 'libvorbis', tmp_fname], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        data = open(tmp_fname, 'rb').read()

        for i in result_files:
            os.remove(i)
        os.remove(tmp_fname)
        os.remove(tmp_wav_file)

        return data


def tts_silero_chunk(text: str, voice: str = 'xenia') -> bytes:
    """
    Generate an audio file (WAV) from the given text using the Silero TTS model.

    Args:
        text (str): The input text to convert into speech.
        voice (str, optional): The voice to use for the speech. Defaults to 'xenia'.
                               Available voices: aidar, baya, kseniya, xenia, eugene, random.

    Returns:
        bytes: The audio data in bytes format.
    """

    global DEVICE, MODEL
    if not DEVICE:
        DEVICE = torch.device('cpu')
        local_file = 'tts_model/v3_1_ru.pt'
        # MODEL, _ = torch.hub.load(repo_or_dir='snakers4/silero-models',
        #                                 model='silero_tts',
        #                                 language='ru',
        #                                 speaker='v3_1_ru')
        # MODEL.to('cpu')
        MODEL = torch.package.PackageImporter(local_file).load_pickle("tts_models", "model")

    sample_rate = 48000
    speaker = voice # aidar, baya, kseniya, xenia, eugene, random

    # замена английских букв и цифр на русские буквы и слова
    text = tts_text_with_gpt(text)
    #print(text, '\n')
    

    audio_path = MODEL.save_wav(text=text,
                                speaker=speaker,
                                put_accent=True,
                                put_yo=True,
                                sample_rate=sample_rate
                                )

    data = open(audio_path, 'rb').read()
    os.remove(audio_path)

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

    gender: Необязательный параметр, 'female' или 'male' или другой голосовой движок

    Функция возвращает байтовый поток с сгенерированным аудио.
    """
    lang = voice

    if gender == 'google_female':
        return tts_google(text, lang)
    elif gender == 'silero_xenia':
        return tts_silero(text, 'xenia')
    elif gender == 'silero_aidar':
        return tts_silero(text, 'aidar')

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


def replace_numbers(text: str) -> str:
    number_words = {
        '0': 'ноль', '1': 'один', '2': 'два', '3': 'три',
        '4': 'четыре', '5': 'пять', '6': 'шесть', '7': 'семь',
        '8': 'восемь', '9': 'девять'}

    result = ''
    for char in text:
        if char.isdigit():
            result += ' ' + number_words[char] + ' '
        else:
            result += char

    return result.strip()


def tts_text_with_gpt(text: str) -> str:
    result = ''
    for chunk in utils.split_text(text, 2500):
        prompt = f"""Исправь текст,
смайлики и необычные символы надо записать русскими словами,
все цифры надо заменить на полные русские слова,
иностранные слова надо транслитерировать на русский с учётом звучания,
иностранные абревиатуры и сокращения транслитерировать на русский и разворачивать в полные слова,
русские сокращения надо развернуть в полные слова,
веб ссылки надо заменить на русские слова описывающие домен,
после ссылки надо добавлять запятую для создания паузы,
номера телефонов, время и любую другую информацию с цифрами надо записывать полными русскими словами,
в твоём ответе должен быть только исправленный текст.


Текст:


{text}
"""
        chunk_result = gpt_basic.ai(prompt)
        #chunk_result = translit(chunk_result, 'ru')
        #chunk_result = replace_numbers(chunk_result)
        result += chunk_result
    return result


if __name__ == "__main__":
    #print(type(tts('Привет, как дела!', 'ru')))

    #print(get_voice('ru', 'male'))

    #sys.exit()
    
    os.environ['all_proxy'] = cfg.all_proxy
    
    text = """
Определяйте свою категорию:
- Безработные
- Мамы в декрете с детьми до 3 лет
- Неработающие мамы в декрете с детьми до 7 лет
- Граждане старше 50 лет
- др. категории граждан (https://trud.dvfu.ru/?utm_source=tg+svodka25&utm_medium=post&utm_campaign=promo#rules)

Отправляйте заявку, (https://trud.dvfu.ru/?utm_source=tg+svodka25&utm_medium=post&utm_campaign=promo) подтверждайте вашу категорию, учитесь дистанционно и получите удостоверение повышения квалификации до конца лета!

Срок обучения: 1-2 месяца 
Количество мест ограничено. 

По вопросам: 
📲 8(924)731-88-85 с 10 до 18:00
🌐https://trud.dvfu.ru/ (https://trud.dvfu.ru/?utm_source=tg+svodka25&utm_medium=post&utm_campaign=promo)
"""

    print(tts_text_with_gpt(text))
    print('\n\n')

    #open('1.ogg', 'wb').write(tts_silero(text))
