#!/usr/bin/env python3


import asyncio
import io
import glob
import os
import re
import subprocess
import tempfile
import threading
import wave

import edge_tts
import gtts
from transliterate import translit
from lingua_franca.format import pronounce_number
import lingua_franca
import torch #silero
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

        subprocess.run(['sox'] + result_files + [tmp_wav_file])
        subprocess.run(['ffmpeg', '-i', tmp_wav_file, '-c:a', 'libvorbis', tmp_fname])

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
        MODEL, _ = torch.hub.load(repo_or_dir='snakers4/silero-models',
                                        model='silero_tts',
                                        language='ru',
                                        speaker='v3_1_ru')
        MODEL.to('cpu')

    sample_rate = 48000
    speaker = voice # aidar, baya, kseniya, xenia, eugene, random

    # замена английских букв и цифр на русские буквы и слова
    text = unroll_text(text)

    audio_path = MODEL.save_wav(text=text,
                                speaker=speaker,
                                put_accent=True,
                                put_yo=True,
                                sample_rate=sample_rate
                                )

    data = open(audio_path, 'rb').read()
    os.remove(audio_path)

    return data


def is_abr(word):
    if len(word) < 2:
        return False
    for i in range(len(word) - 1):
        if word[i].isupper() and word[i + 1].isupper():
            return True
    return False


def split_on_uppercase(s, keep_contiguous=True):
    """

    Args:
        s (str): string
        keep_contiguous (bool): flag to indicate we want to 
                                keep contiguous uppercase chars together

    Returns:

    """
    string_length = len(s)
    is_lower_around = (lambda: s[i-1].islower() or 
                       string_length > (i + 1) and s[i + 1].islower())

    start = 0
    parts = []
    for i in range(1, string_length):
        if s[i].isupper() and (not keep_contiguous or is_lower_around()):
            parts.append(s[start: i])
            start = i
    parts.append(s[start:])

    return parts


def word_to_tts(text: str) -> str:
    """Заменяет в тексте абревиатуры на слоги для чтения с помощью TTS."""
    syllables = {'A': 'a', 'Б': 'бэ', 'В': 'вэ',
                 'Г': 'гэ', 'Д': 'дэ', 'Е': 'е',
                 'Ё': 'ё', 'Ж': 'жэ', 'З': 'зэ',
                 'И': 'и', 'Й': 'й', 'К': 'ка',
                 'Л': 'эл', 'М': 'эм', 'Н': 'эн',
                 'О': 'о', 'П': 'пэ', 'Р': 'эр',
                 'С': 'эс', 'Т': 'тэ', 'У': 'у',
                 'Ф': 'эф', 'Х': 'хэ', 'Ц': 'цэ', 'Ч': 'чэ',
                 'Ш': 'шэ', 'Щ': 'щэ', 'Ъ': 'твёрдый знак',
                 'Ы': 'ы', 'Ь': 'мягкий знак',
                 'Э': 'э', 'Ю': 'ю', 'Я': 'я',
                 'Q':'кью'}
    
    text = text.replace('\r', '')
    text = text.replace('\n', '⁂ ')
    
    result = ''
    # заменяем в тексте все буквы в словах состоящих только из больших букв с помощь словаря
    for word in text.split():                               # бьем текст на слова
        for subword in split_on_uppercase(word):            # и на части слов 
            if is_abr(subword):                             # если слово - абревиатура то 
                for letter in subword:                      # проходим по каждой букве
                    try:
                        result += syllables[letter] + ' '   # и пытаемся заменить на слог
                    except KeyError:
                        result += letter + ' '              # если не получилось то оставляем как есть
            else:
                result += subword                           # если не абревиатура то оставляем как есть
            result += ' '

    result = result.strip()
    result = result.replace('⁂', '\n')
    return result


def load_language(lang:str):
    lingua_franca.load_language(lang)


def convert_one_num_float(match_obj):
    if match_obj.group() is not None:
        text = str(match_obj.group())
        return pronounce_number(float(match_obj.group()))


def convert_diapazon(match_obj):
    if match_obj.group() is not None:
        text = str(match_obj.group())
        text = text.replace("-"," тире ")
        return all_num_to_text(text)


def all_num_to_text(text:str) -> str:
    text = re.sub(r'[\d]*[.][\d]+-[\d]*[.][\d]+', convert_diapazon, text)
    text = re.sub(r'-[\d]*[.][\d]+', convert_one_num_float, text)
    text = re.sub(r'[\d]*[.][\d]+', convert_one_num_float, text)
    text = re.sub(r'[\d]-[\d]+', convert_diapazon, text)
    text = re.sub(r'-[\d]+', convert_one_num_float, text)
    text = re.sub(r'[\d]+', convert_one_num_float, text)
    text = text.replace("%", " процентов")
    return text


def unroll_text(text: str, lang: str = 'ru') -> str:
    """Заменяет в тексте не русские символы на русские и цифры на слова для TTS который сам так не умеет"""
    load_language(lang)
    result = translit(text, 'ru')
    result = all_num_to_text(result)
    result = word_to_tts(result)
    return result
   

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
    
    #print(get_voice('ru', 'male'))
    
    text = """1. Что такое "Нормализация"? АБВГД

Есть такое понятие как логическая избыточность. Это когда, например, в таблице пользователей есть столбец номер телефона. То есть у пользователя Х может быть только один номер телефона для связи. Но зачастую это неудобно: ведь номеров у человека может быть несколько.

В такой ситуации разумно вынести номер телефона в отдельную таблицу и организовать связь "Один-ко-многим" (у одного пользователя может быть несколько телефонных номеров)

То есть мы разбиваем таблицу на части или делаем декомпозицию, приводя таким образом таблицу к нормальной форме

Нормализация как раз и подразумевает собой процесс приведения базы данных к нормальным формам с целью избавления от логической избыточности, а декомпозиция - это одна из вариаций нормализации.

Нормальных форм существует аж 8: с 1NF и до 6NF а также Бойса-Кодда и Доменно-ключевая формы.
2. Есть ли преимущество у NoSQL над SQL?

Иногда можно добиться большего быстродействия у первого языка. Если кратко - преимущество есть в скорости выполнения запросов. Это связано с отсутствием связей и конкретной схемы в NoSQL.

Так MongoDB может выигрывать у PostrgeSQL в запросах, которые подразумевают много связей и за которыми постгрес полезет в другие таблицы, которые, вдобавок, могут оказаться очень большими.
"""
    print(unroll_text(text))
    #print(word_to_tts(text))
    open('1.ogg', 'wb').write(tts_silero(text))
