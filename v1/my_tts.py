#!/usr/bin/env python3


import io  # Библиотека для работы с байтовыми потоками
import edge_tts  # Библиотека для генерации речи 
import tempfile  # Библиотека для создания временных файлов
import subprocess  # Библиотека для вызова внешних процессов
import os  # Библиотека для работы с файловой системой


edge_tts_cmd = "/home/ubuntu/.local/bin/edge-tts"


def tts(text: str, voice: str = 'ru', rate: str = '+0%') -> bytes: 
    """Генерирует аудио из текста с помощью edge-tts и возвращает байтовый поток

    Эта функция принимает:

    text: Строку с текстом для озвучивания

    voice: Необязательный параметр, указывает голос для синтеза речи. По умолчанию используется русский голос. Можно указать любой другой голос, доступный в edge-tts.

    rate: Необязательный параметр, указывает скорость речи. По умолчанию '+50%' - повышенная скорость. Можно указать любую скорость речи, поддерживаемую edge-tts.

    Функция возвращает байтовый поток с сгенерированным аудио.
    """
    
    voice = get_voice(voice)
    
    # Удаляем символы переноса строки и перевода каретки 
    text = text.replace('\r','') 
    text = text.replace('\n',' ')  
    
    # Создаем временный файл для записи аудио
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f: 
        filename = f.name 
        
    # Запускаем edge-tts для генерации аудио
    command = [
        edge_tts_cmd,     # Исполняемый файл 
        "--rate="+rate, # Скорость речи
        "--text",       # Входной текст 
        text,
        "-v",           # Голос
        voice,
        "--write-media",# Записать аудио в файл
        filename        # Имя выходного файла
    ]
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # Читаем аудио из временного файла 
    with open(filename, "rb") as f: 
        data = io.BytesIO(f.read())
        
    # Удаляем временный файл
    os.remove(filename)
    
    # Возвращаем байтовый поток с аудио
    return data.getvalue()


def get_voice(language_code):
    """принимает двухбуквенное обозначение языка и возвращает голосовой движок для его озвучки"""
    voices = {
        'af': 'af-ZA-WillemNeural',
        'ar': 'ar-EG-SalmaNeural',
        'az': 'az-AZ-BanuNeural', 
        'bg': 'bg-BG-KalinaNeural',
        'bn': 'bn-BD-NabanitaNeural',
        'bs': 'bs-BA-GoranNeural', 
        'ca': 'ca-ES-JoanaNeural',
        'cs': 'cs-CZ-VlastaNeural',
        'cy': 'cy-GB-NiaNeural', 
        'da': 'da-DK-ChristelNeural',
        'de': 'de-DE-KatjaNeural',
        'el': 'el-GR-AthinaNeural',
        'en': 'en-US-AriaNeural',
        'es': 'es-ES-ElviraNeural',
        'et': 'et-EE-AnuNeural',
        'fa': 'fa-IR-DilaraNeural',
        'fi': 'fi-FI-NooraNeural', 
        'fil': 'fil-PH-BlessicaNeural',
        'fr': 'fr-FR-DeniseNeural',
        'ga': 'ga-IE-OrlaNeural',
        'gl': 'gl-ES-SabelaNeural',
        'gu': 'gu-IN-DhwaniNeural',
        'he': 'he-IL-HilaNeural',
        'hi': 'hi-IN-SwaraNeural',
        'hr': 'hr-HR-GabrijelaNeural',
        'hu': 'hu-HU-NoemiNeural',
        'id': 'id-ID-GadisNeural',
        'is': 'is-IS-GudrunNeural',
        'it': 'it-IT-ElsaNeural',
        'ja': 'ja-JP-NanamiNeural',
        'jv': 'jv-ID-SitiNeural',
        'ka': 'ka-GE-EkaNeural',
        'kk': 'kk-KZ-AigulNeural',
        'km': 'km-KH-SreymomNeural',
        'kn': 'kn-IN-SapnaNeural',
        'ko': 'ko-KR-SunHiNeural',
        'lo': 'lo-LA-KeomanyNeural',
        'lt': 'lt-LT-OnaNeural',
        'lv': 'lv-LV-EveritaNeural',
        'mk': 'mk-MK-MarijaNeural',
        'ml': 'ml-IN-SobhanaNeural',
        'mn': 'mn-MN-YesuiNeural',
        'mr': 'mr-IN-AarohiNeural',
        'ms': 'ms-MY-YasminNeural',
        'mt': 'mt-MT-GraceNeural',
        'my': 'my-MM-NilarNeural',
        'nb': 'nb-NO-PernilleNeural',
        'ne': 'ne-NP-HemkalaNeural',
        'nl': 'nl-NL-FennaNeural',
        'pl': 'pl-PL-ZofiaNeural',
        'ps': 'ps-AF-LatifaNeural',
        'pt': 'pt-BR-FranciscaNeural',
        'ro': 'ro-RO-AlinaNeural',
        'ru': 'ru-RU-SvetlanaNeural',
        'si': 'si-LK-ThiliniNeural',
        'sk': 'sk-SK-ViktoriaNeural',
        'sl': 'sl-SI-PetraNeural',
        'so': 'so-SO-UbaxNeural',
        'sq': 'sq-AL-AnilaNeural',
        'sr': 'sr-RS-SophieNeural',
        'su': 'su-ID-TutiNeural',
        'sv': 'sv-SE-SofieNeural',
        'sw': 'sw-TZ-RehemaNeural',
        'ta': 'ta-IN-PallaviNeural',
        'te': 'te-IN-ShrutiNeural',
        'th': 'th-TH-PremwadeeNeural',
        'tr': 'tr-TR-EmelNeural',
        'uk': 'uk-UA-PolinaNeural',
        'ur': 'ur-PK-UzmaNeural',
        'uz': 'uz-UZ-MadinaNeural',
        'vi': 'vi-VN-HoaiMyNeural',
        'zh': 'zh-CN-XiaoxiaoNeural',
        'zu': 'zu-ZA-ThandoNeural'
    }
    return voices[language_code]


if __name__ == "__main__":
    #with open('test.mp3', 'wb') as f:
    #    f.write(tts('Привет, как дела!', 'ru'))
    
    print(get_voice('ru'))
