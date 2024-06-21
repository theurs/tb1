#!/usr/bin/env python3


import io
import json
import os
import random
import re
import subprocess
import threading
import time
import traceback
import zlib
from pydub import AudioSegment
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed

import speech_recognition as sr
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from pydub import AudioSegment
from pydub.silence import split_on_silence


import cfg
import my_gemini
import my_log
import my_ytb
import utils
from utils import async_run


YT_DLP = 'yt-dlp'
FFMPEG = 'ffmpeg'


MAX_THREADS = 16  # Максимальное количество одновременных потоков
download_worker_semaphore = threading.Semaphore(MAX_THREADS)  # Создаем семафор здесь


# не больше 8 потоков для распознавания речи гуглом
recognize_chunk_SEMAPHORE = threading.Semaphore(8)

# не выполнять больше чем в 1 поток, слишком сильно давит на память и процессор
stt_google_pydub_lock = threading.Lock()


def detect_repetitiveness(text: str) -> bool:
    '''True если в тексте много повторений, ответ от джемини содержит большое количество повторений
    такое бывает когда он сфейлился'''
    # в мелких маловероятно и в любом случае результат хз
    if len(text) < 500:
        return False
    text_encoded = text.encode()
    compressed_data = zlib.compress(text_encoded)
    ratio = len(text_encoded) / len(compressed_data)
    if ratio > 5:
        my_log.log_entropy_detector(f'{len(text_encoded)} {len(compressed_data)} {ratio}\n\n{text}')
    return ratio > 5


def detect_repetitiveness_with_tail(text: str) -> bool:
    '''True если в тексте много повторений, ответ от джемини содержит большое количество повторений
    такое бывает когда он сфейлился
    так же считает отдельно энтропия хвоста, второй половины сообщения, должна быть запредельно высокой
    '''
    # в мелких маловероятно и в любом случае результат хз
    if len(text) < 500:
        return False
    text_encoded = text.encode()
    compressed_data = zlib.compress(text_encoded)
    compressed_data2 = zlib.compress(text_encoded[-int(len(text_encoded)/2):])
    ratio = len(text_encoded) / len(compressed_data)
    ratio2 = len(text_encoded[-int(len(text_encoded)/2):]) / len(compressed_data2)
    if ratio > 5 and ratio2 > 100:
        my_log.log_entropy_detector(f'{len(text_encoded)} {len(compressed_data)} {ratio}\n\n{text}')
    return ratio > 5 and ratio2 > 100


def recognize_chunk(audio_chunk: AudioSegment,
                    return_dict: dict,
                    index: int,
                    language: str = "ru"):
    '''Распознавание речи с использованием Google Web Speech API
    Args:
        audio_chunk: pydub.audio_segment.AudioSegment
        return_dict: dict
        index: int
        language: str
    
    Returns:
        dict with index as key and text as value
    '''
    with recognize_chunk_SEMAPHORE:
        try:
            recognizer = sr.Recognizer()
            # Конвертируем аудио в WAV формат для совместимости с speech_recognition
            wav_io = io.BytesIO()
            audio_chunk.export(wav_io, format="wav")
            wav_io.seek(0)

            with sr.AudioFile(wav_io) as source:
                # Читаем аудио
                audio = recognizer.record(source)
                try:
                    # Распознаем речь используя Google Web Speech API
                    text = recognizer.recognize_google(audio, language=language)
                    return_dict[index] = text
                except sr.UnknownValueError as e:
                    return_dict[index] = ""
                except sr.RequestError as e:
                    return_dict[index] = ""
        except Exception as e:
            return_dict[index] = ""


def stt_google_pydub(audio_bytes: bytes|str,
                     sample_rate: int = 44100,
                     chunk_duration: int = 50,
                     language: str = "ru") -> str:
    '''Распознавание речи с использованием Google Web Speech API

    Args:
        audio_bytes (bytes): Сырые данные аудио в байтах или путь к аудиофайлу
        sample_rate (int, optional): Частота дискретизации аудио. Defaults to 44100.
        chunk_duration (int, optional): Длительность куска аудио в миллисекундах. Defaults to 50.
        language (str, optional): Язык распознавания речи. Defaults to "ru".

    Returns:
        str: Распознанный текст
    '''
    with stt_google_pydub_lock:
        try:
            if isinstance(audio_bytes, str):
                with open(audio_bytes, "rb") as f:
                    audio_bytes = f.read()

            # Создаем объект AudioSegment, пытаясь автоматически определить формат
            audio_segment = AudioSegment.from_file(io.BytesIO(audio_bytes))
            # Устанавливаем частоту дискретизации
            audio_segment = audio_segment.set_frame_rate(sample_rate)
            
            # Разбиваем аудио на части по паузам в речи
            chunks = split_on_silence(audio_segment, min_silence_len=500, silence_thresh=-40)

            # Объединяем маленькие кусочки, чтобы они были не длиннее chunk_duration
            combined_chunks = []
            current_chunk = AudioSegment.empty()
            for chunk in chunks:
                if len(current_chunk) + len(chunk) <= chunk_duration * 1000:
                    current_chunk += chunk
                else:
                    combined_chunks.append(current_chunk)
                    current_chunk = chunk

            if len(current_chunk) > 0:
                combined_chunks.append(current_chunk)

            threads = []
            results = {}

            for i, chunk in enumerate(combined_chunks):
                # Создаем и стартуем поток для распознавания
                thread = threading.Thread(target=recognize_chunk, args=(chunk, results, i, language))
                threads.append(thread)
                thread.start()

            # Ждем завершения всех потоков
            for thread in threads:
                thread.join()

            # Сортируем результаты по порядку индексов и объединяем их в строку
            ordered_results = [results[i] for i in sorted(results)]
            result = ' '.join(ordered_results)

            result2 = my_gemini.retranscribe(result)
            if not result2 or detect_repetitiveness(result2):
                return result
            else:
                return result2        
        except Exception as error:
            traceback_error = traceback.format_exc()
            my_log.log2(f"my_transcribe:stt_google_pydub: {error}\n{traceback_error}")
            return ''


def genai_clear():
    """Очистка файлов, загруженных через Gemini API.
    TODO: Проверить возможность удаления чужих файлов.
    TODO: Обработать потенциальный race condition при настройке API ключа.
    """

    try:
        keys = cfg.gemini_keys[:] + my_gemini.ALL_KEYS
        random.shuffle(keys)

        for key in keys:
            print(key)
            genai.configure(api_key=key) # здесь может быть рейс кондишн?
            files = genai.list_files()
            for f in files:
                print(f.name)
                try:
                    # genai.delete_file(f.name)
                    pass # можно ли удалять чужие файлы?
                except Exception as error:
                    my_log.log_gemini(f'stt:genai_clear: delete file {error}\n{key}\n{f.name}')

    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_gemini(f'Failed to convert audio data to text: {error}\n\n{traceback_error}')


def transcribe_genai(audio_file: str, prompt: str = '', language: str = 'ru') -> str:
    '''
    This function takes an audio file path and an optional prompt as input and returns the transcribed text.

    Parameters
    audio_file: The path to the audio file. This can be a local file path or a YouTube URL.
    prompt: An optional prompt to provide to the Gemini API. This can be used to guide the transcription process.
    language: The language of the audio file. This is used to select the appropriate language model for transcription.
    Returns
    The transcribed text.

    Raises
    Exception: If an error occurs during transcription.
    '''
    if my_ytb.valid_youtube_url(audio_file):
        audio_file_ = my_ytb.download_ogg(audio_file)
        result = transcribe_genai(audio_file_, prompt, language)
        utils.remove_file(audio_file_)
        return result

    try:
        keys = cfg.gemini_keys[:] + my_gemini.ALL_KEYS
        random.shuffle(keys)
        key = keys[0]

        your_file = None
        if not prompt:
            prompt = "Listen carefully to the following audio file. Provide a transcript. Fix errors, make a fine text without time stamps. This audio file is a cutted fragment with +5 extra seconds in both directions."

        for _ in range(3):
            try:
                genai.configure(api_key=key) # здесь может быть рейс кондишн?
                if your_file == None:
                    your_file = genai.upload_file(audio_file)
                    genai.configure(api_key=key) # здесь может быть рейс кондишн?
                model = genai.GenerativeModel('models/gemini-1.5-flash-latest')
                # tokens_count = model.count_tokens([your_file])
                # if tokens_count.total_tokens > 7800:
                #     response = ''
                #     break
                response = model.generate_content([prompt, your_file],
                                                  safety_settings={
                    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                    }
                )
                if response.text.strip():
                    break
            except Exception as error:
                my_log.log_gemini(f'my_transcribe.py:transcribe_genai: Failed to convert audio data to text: {error}')
                response = ''
                time.sleep(2)

        try:
            genai.configure(api_key=key) # здесь может быть рейс кондишн?
            if your_file:
                genai.delete_file(your_file.name)
        except Exception as error:
            my_log.log_gemini(f'my_transcribe.py:transcribe_genai: Failed to delete audio file: {error}\n{key}\n{your_file.name if your_file else ""}\n\n{str(your_file)}')

        if response and response.text.strip():
            if detect_repetitiveness(response.text.strip()):
                return stt_google_pydub_v2(audio_file, language = language)
            return response.text.strip()
        else:
            return stt_google_pydub_v2(audio_file, language = language)
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_gemini(f'my_transcribe.py:transcribe_genai: Failed to convert audio data to text: {error}\n\n{traceback_error}')
        return stt_google_pydub_v2(audio_file, language = language)


def download_worker(video_url: str, part: tuple, n: int, fname: str, language: str):
    with download_worker_semaphore:
        utils.remove_file(f'{fname}_{n}.ogg')
        proc = subprocess.run([YT_DLP, '-x', '-g', video_url], stdout=subprocess.PIPE)
        stream_url = proc.stdout.decode('utf-8', errors='replace').strip()

        proc = subprocess.run([FFMPEG, '-ss', str(part[0]), '-i', stream_url, '-t',
                        str(part[1]), f'{fname}_{n}.ogg'],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out_ = proc.stdout.decode('utf-8', errors='replace').strip()
        err_ = proc.stderr.decode('utf-8', errors='replace').strip()
        if 'error' in err_:
            my_log.log2(f'my_transcribe:download_worker: Error in FFMPEG: {err_}')
        if 'error' in out_:
            my_log.log2(f'my_transcribe:download_worker: Error in FFMPEG: {out_}')

        text = transcribe_genai(f'{fname}_{n}.ogg', language=language)

        if text:
            with open(f'{fname}_{n}.txt', 'w', encoding='utf-8') as f:
                f.write(text)

        utils.remove_file(f'{fname}_{n}.ogg')


def download_youtube_clip(video_url: str, language: str):
    """
    Скачивает видео с YouTube по частям, транскрибирует.
    Возвращает транскрипцию к видео. text, info(dict с информацией о видео)
    language - язык для транскрибации, используется только кусков которые джемини сфейлил.
               у джемини автоопределение языков а у резерва нет
    """

    part_size = 10 * 60 # размер куска несколько минут
    treshold = 5 # захватывать +- несколько секунд в каждом куске

    proc = subprocess.run([YT_DLP, '--skip-download', '-J', video_url], stdout=subprocess.PIPE)
    output = proc.stdout.decode('utf-8', errors='replace')
    info = json.loads(output)
    duration = info['duration']

    output_name = utils.get_tmp_fname()

    parts = []
    start = 0
    while start < duration:
        end = min(start + part_size, duration)
        if start == 0:
            parts.append((0, min(duration, end + treshold)))  # Первый фрагмент
        elif end == duration:
            parts.append((max(0, start - treshold), duration - start))  # Последний фрагмент
        else:
            parts.append((max(0, start - treshold), min(duration - start, part_size) + 2 * treshold))  # Остальные фрагменты
        start = end

    n = 0
    threads = []

    for part in parts:
        n += 1
        t = threading.Thread(target=download_worker, args=(video_url, part, n, output_name, language))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    result = ''
    for x in range(1, n + 1):
        # check if file exists
        if os.path.exists(f'{output_name}_{x}.txt'):
            with open(f'{output_name}_{x}.txt', 'r', encoding='utf-8') as f:
                result += f.read() + '\n\n'
            utils.remove_file(f'{output_name}_{x}.txt')

    return result, info


def gemini_tokens_count(text: str) -> int:
    genai.configure(api_key=cfg.gemini_keys[0])
    # print([(x.name, x.input_token_limit, x.output_token_limit, x.supported_generation_methods) for x in genai.list_models()])
    response = genai.count_message_tokens(prompt=text)
    return response['token_count']


########################################################################################
# не используется, альтернативный вариант, возможно что он быстрее
########################################################################################

def find_cut_positions(pauses, desired_chunk_size, audio_duration):
    """
    Находит оптимальные позиции для разрезания аудио на основе пауз и желаемой длины фрагмента,
    гарантируя, что размер фрагментов не превышает желаемого.

    Args:
        pauses (list): Список пауз в формате [(начало, конец, длительность), ...].
        desired_chunk_size (float): Желаемая длительность фрагмента в секундах.
        audio_duration (float): Общая длительность аудио в секундах.

    Returns:
        list: Список кортежей (позиция разреза, длительность фрагмента).
    """
    segments = []
    last_end = 0
    for start, end, duration in pauses:
        segments.append((last_end, round(start - last_end, 2)))
        last_end = end
    segments.append((last_end, audio_duration - last_end))  # Добавляем последний сегмент

    def split_segment(segments, index):
        start, duration = segments[index]
        if duration <= desired_chunk_size:
            return

        half_duration = duration / 2
        segments[index] = (start, half_duration)
        segments.insert(index + 1, (start + half_duration, half_duration))
        split_segment(segments, index)
        split_segment(segments, index + 1)

    i = 0
    while i < len(segments):
        split_segment(segments, i)
        i += 1

    merged_segments = []
    current_segment_start = 0
    current_segment_duration = 0
    for start, duration in segments:
        if current_segment_duration + duration <= desired_chunk_size:
            current_segment_duration += duration
        else:
            merged_segments.append((current_segment_start, current_segment_duration))
            current_segment_start = start
            current_segment_duration = duration
    merged_segments.append((current_segment_start, current_segment_duration))

    merged_segments = [(round(x[0], 2), round(x[1], 2)) for x in merged_segments]
    return merged_segments


def find_split_segments(audio_file: str, max_size: int = 50) -> list:
    """
    Находит моменты тишины в аудиофайле и возвращает список точек для разрезания на основе этих моментов и желаемой длины фрагмента.

    Args:
        audio_file (str): Путь к аудиофайлу (поддерживаются любые форматы, распознаваемые ffmpeg, и ссылки на YouTube).

    Returns:
        list: Список кортежей (позиция разреза, длительность фрагмента).
    """
    if '/youtu.be/' in audio_file or 'youtube.com/' in audio_file:
        proc = subprocess.run([YT_DLP, '--skip-download', '-J', audio_file], stdout=subprocess.PIPE)
        output = proc.stdout.decode('utf-8', errors='replace')
        info = json.loads(output)
        duration__ = info['duration']
        proc = subprocess.run([YT_DLP, '-x', '-g', audio_file], stdout=subprocess.PIPE)
        audio_file = proc.stdout.decode('utf-8', errors='replace').strip()
    else:
        result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', audio_file], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            r = float(result.stdout)
        except ValueError:
            r = 0
        duration__ = r

    proc = subprocess.run([FFMPEG, '-i', audio_file, '-af', 'silencedetect=noise=-30dB:d=0.5', '-f', 'null', '-'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output = proc.stdout.decode('utf-8', errors='replace').strip()
    error = proc.stderr.decode('utf-8', errors='replace').strip()

    pattern_start = re.compile(r'silence_start:\s+(\d+\.\d+)')
    pattern_end_duration = re.compile(r'silence_end:\s+(\d+\.\d+)\s+\|\s+silence_duration:\s+(\d+\.\d+)')
    
    silences = []
    current_start = None

    for line in error.splitlines():
        start_match = pattern_start.search(line)
        end_duration_match = pattern_end_duration.search(line)

        if start_match:
            current_start = float(start_match.group(1))
        elif end_duration_match and current_start is not None:
            end = float(end_duration_match.group(1))
            duration = float(end_duration_match.group(2))
            silences.append((current_start, end, duration))
            current_start = None
    # print(silences)
    # print()
    return find_cut_positions(silences, max_size, duration__)


def stt_google_pydub_v2(audio_file_path: str, lang: str = 'ru') -> str:
    """
    Распознает текст из аудио файла.

    Args:
        audio_file_path (str): Путь к  аудио файлу - 'mp3', 'mp4', 'aac', 'webm', 'ogg' или bytes (ogg)

    Returns:
        str: Распознанный текст.
    """
    # Создаем объект распознавания речи
    r = sr.Recognizer()

    # Загружаем аудио файл с помощью pydub
    if isinstance(audio_file_path, bytes):
        audio = AudioSegment.from_file(io.BytesIO(audio_file_path))
    else:
        audio = AudioSegment.from_file(audio_file_path)

    # Находим точки разрезания аудио на сегменты
    split_segments = find_split_segments(audio_file_path)

    # Распознаем текст для каждого сегмента в параллельных потоках
    recognized_text = [""] * len(split_segments)
    with ThreadPoolExecutor() as executor:
        futures = []
        for i, (start, duration) in enumerate(split_segments):
            # Извлекаем сегмент
            start_ = start*1000
            end = (start + duration)*1000
            segment = audio[start_:end]

            # Сохраняем сегмент в BytesIO
            wav_bytes = BytesIO()
            segment.export(wav_bytes, format="wav")
            wav_bytes.seek(0)

            # Распознаем текст асинхронно
            futures.append(executor.submit(recognize_segment, r, wav_bytes, lang, i))

        # Собираем результаты в правильном порядке
        for future in as_completed(futures):
            try:
                index = future.result()[0]
                text = future.result()[1]
                recognized_text[index] = text
            except Exception as e:
                print(f"Ошибка при распознавании сегмента: {e}")

    return " ".join(recognized_text).strip()


def recognize_segment(recognizer, wav_bytes, lang, index):
    """
    Распознает текст из сегмента аудио.

    Args:
        recognizer (speech_recognition.Recognizer): Объект распознавания речи.
        wav_bytes (io.BytesIO): Байтовое представление сегмента аудио в формате WAV.
        lang (str): Язык аудио.
        index (int): Индекс сегмента.

    Returns:
        tuple: Кортеж (index, text), где index - индекс сегмента, text - распознанный текст.
    """
    with sr.AudioFile(wav_bytes) as source:
        audio_data = recognizer.record(source)
    try:
        text = recognizer.recognize_google(audio_data, language=lang)
        return (index, text)
    except sr.UnknownValueError:
        print("Не удалось распознать речь в сегменте.")
        return (index, "")
    except sr.RequestError as e:
        print(f"Ошибка при распознавании речи: {e}")
        return (index, "")

########################################################################################
# не используется, альтернативный вариант, возможно что он быстрее
########################################################################################


@async_run
def shazam(url: str):
    '''не работает, не может джемини шазамить'''
    r = transcribe_genai('https://www.youtube.com/watch?v=O8u61dQut1E', 'Какая музыка играет, название?')
    print(my_ytb.get_title(url), url)
    print(r)


if __name__ == '__main__':
    pass
    urls = [
        'https://www.youtube.com/watch?v=rR19alK6QKM',
        'https://www.youtube.com/watch?v=MqTFEahfgOk&pp=ygUT0L_QtdGB0L3QuCDRhdC40YLRiw%3D%3D',
        'https://www.youtube.com/watch?v=fPO76Jlnz6c&pp=ygUT0L_QtdGB0L3QuCDRhdC40YLRiw%3D%3D',
        'https://www.youtube.com/watch?v=5Fix7P6aGXQ&pp=ygU10LAg0YLRiyDRgtCw0LrQvtC5INC60YDQsNGB0LjQstGL0Lkg0YEg0LHQvtGA0L7QtNC-0Lk%3D',
        'https://www.youtube.com/watch?v=xfT645b6l0s&pp=ygUX0L_QvtC60LjQvdGD0LvQsCDRh9Cw0YI%3D',
    ]
    for x in urls:
        shazam(x)
