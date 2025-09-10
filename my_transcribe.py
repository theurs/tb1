#!/usr/bin/env python3

import cachetools.func
import io
import json
import os
import random
import re
import requests
import subprocess
import threading
import time
import traceback
import zlib
from pydub import AudioSegment
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

import speech_recognition as sr
from google import genai

from pydub import AudioSegment
from pydub.silence import split_on_silence


import cfg
import my_gemini3
import my_gemini_general
import my_groq
import my_log
import my_ytb
import utils
from utils import async_run


YT_DLP = 'yt-dlp'
FFMPEG = 'ffmpeg'


MAX_THREADS = 4  # Максимальное количество одновременных потоков
MAX_THREADS_V2 = 2  # Максимальное количество одновременных потоков
download_worker_semaphore = threading.Semaphore(MAX_THREADS)  # Создаем семафор здесь
download_worker_semaphore_v2 = threading.Semaphore(MAX_THREADS_V2)  # Создаем семафор здесь


# не больше 4 потоков для распознавания речи гуглом
recognize_chunk_SEMAPHORE = threading.Semaphore(4)

# не выполнять больше чем в 1 поток, слишком сильно давит на память и процессор
stt_google_pydub_lock = threading.Lock()


def detect_repetitiveness(text: str) -> bool:
    '''True если в тексте много повторений, ответ от джемини содержит большое количество повторений
    такое бывает когда он сфейлился'''
    # в мелких маловероятно и в любом случае результат хз
    if len(text) < 2000:
        return False
    text_encoded = text.encode()
    compressed_data = zlib.compress(text_encoded)
    ratio = len(text_encoded) / len(compressed_data)
    if ratio > 6:
        my_log.log_entropy_detector(f'{len(text_encoded)} {len(compressed_data)} {ratio}\n\n{text}')
    return ratio > 6


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
    if ratio > 6 and ratio2 > 100:
        my_log.log_entropy_detector(f'{len(text_encoded)} {len(compressed_data)} {ratio}\n\n{text}')
    return ratio > 6 and ratio2 > 100


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

            result2 = my_gemini3.retranscribe(result)
            if not result2 or detect_repetitiveness(result2):
                return result
            else:
                return result2        
        except Exception as error:
            traceback_error = traceback.format_exc()
            my_log.log2(f"my_transcribe:stt_google_pydub: {error}\n{traceback_error}")
            return ''


def genai_clear(key: str = '') -> None:
    """
    Cleans up all files uploaded to the Gemini project associated with an API key.

    This function instantiates a client with a given or fetched API key,
    retrieves a list of all files, and attempts to delete each one.
    It uses an object-oriented client to avoid race conditions.

    Args:
        key (str, optional): The specific API key for cleanup. If not provided,
                             a key is fetched from the general pool.
    """
    try:
        # Get the API key
        api_key = key or my_gemini_general.get_next_key()
        if not api_key:
            my_log.log_gemini('my_transcribe:genai_clear: No API key available for cleanup.')
            return

        # Instantiate the client to avoid race conditions
        client = genai.Client(api_key=api_key)

        # List and delete files. Converting to list() is safer.
        files_to_delete = list(client.files.list())
        for f in files_to_delete:
            try:
                # You can only delete your own files, scoped by the API key.
                client.files.delete(name=f.name)
            except Exception as error:
                my_log.log_gemini(f'my_transcribe:genai_clear: Failed to delete file {f.name}. Error: {error}')

    except Exception as error:
        # Catches broader errors like invalid API key on client creation
        traceback_error = traceback.format_exc()
        my_log.log_gemini(f'my_transcribe:genai_clear: A critical error occurred during cleanup: {error}\n{traceback_error}')


@utils.async_run
def _robust_delete_file(client: genai.Client, file_name: str, attempts: int = 5, delay_sec: int = 30):
    """
    Tries to delete a file multiple times with delays in a separate thread.
    The key used in the client must be the one that uploaded the file.
    """
    for attempt in range(attempts):
        try:
            client.files.delete(name=file_name)
            # my_log.log_gemini(f'my_transcribe:_robust_delete_file: Successfully deleted file {file_name} on attempt {attempt + 1}.')
            return
        except Exception as e:
            # my_log.log_gemini(f'my_transcribe:_robust_delete_file: Attempt {attempt + 1}/{attempts} failed to delete {file_name}: {e}')
            if attempt < attempts - 1:
                time.sleep(delay_sec)
    my_log.log_gemini(f'my_transcribe:_robust_delete_file: Failed to delete file {file_name} after {attempts} attempts.')


def transcribe_genai(
    audio_file: str,
    prompt: str = '',
    language: str = 'ru',
    temperature: float = 0.2,
    max_tokens: int = 8000,
    timeout: int = 240
    ) -> str:
    """
    Transcribes an audio file using the Gemini API with a robust two-level retry mechanism.

    It handles key failures by retrying with a new key and re-uploading the file.
    It handles temporary service errors (e.g., 503 Overload) by retrying the transcription
    request without re-uploading. File deletion is handled robustly in the background.

    Args:
        audio_file: Path to the audio file or a YouTube URL.
        prompt: Optional prompt to guide the transcription model.
        language: The language of the audio, used for the fallback STT method.
        temperature: Controls the randomness of the output.
        max_tokens: The maximum number of tokens to generate.
        timeout: The overall timeout in seconds for the entire operation.

    Returns:
        The transcribed text, or an empty string on failure.
    """
    if my_ytb.valid_youtube_url(audio_file):
        audio_file_ = my_ytb.download_ogg(audio_file)
        if not audio_file_:
            my_log.log_gemini(f'my_transcribe.py:transcribe_genai: Failed to download YouTube audio from {audio_file}')
            return ''
        result = transcribe_genai(audio_file_, prompt, language, temperature, max_tokens, timeout)
        utils.remove_file(audio_file_)
        return result

    final_response_text = ''
    deadline = time.monotonic() + timeout

    if not prompt:
        prompt = "Listen carefully to the following audio file. Provide a transcript. Fix errors, make a fine text with good looking paragraphs, without time stamps and diarization (speaker separation)."

    config = genai.types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_tokens,
        safety_settings=my_gemini3.SAFETY_SETTINGS,
    )

    # Outer loop: Handles API key failures. A new key means a new upload.
    for _ in range(3):
        remaining_time = deadline - time.monotonic()
        if remaining_time <= 0:
            my_log.log_gemini('my_transcribe.py:transcribe_genai: Overall timeout exceeded before key attempt.')
            break

        key = ''
        client = None
        uploaded_file = None

        try:
            key = my_gemini_general.get_next_key()
            client = genai.Client(api_key=key, http_options={'timeout': int(remaining_time * 1000)})

            uploaded_file = client.files.upload(file=audio_file)

            # Inner loop: Handles temporary errors like 503 without changing the key or re-uploading.
            for _ in range(3):
                if time.monotonic() > deadline: break
                try:
                    response = client.models.generate_content(
                        model=cfg.gemini25_flash_model,
                        contents=[prompt, uploaded_file],
                        config=config
                    )
                    if response and response.text and response.text.strip():
                        final_response_text = response.text.strip()
                        # Success, break both loops
                        return final_response_text
                except Exception as inner_error:
                    err_str = str(inner_error)
                    if '503 UNAVAILABLE' in err_str:
                        my_log.log_gemini(f'my_transcribe.py:transcribe_genai: Model overloaded (503). Retrying transcription... Error: {err_str}')
                        time.sleep(2)
                        continue # Retry inner loop
                    else:
                        # Re-raise other errors to be caught by the outer loop's handler
                        raise inner_error

            if final_response_text: break

        except Exception as outer_error:
            err_str = str(outer_error)
            if 'API key' in err_str or 'Quota exceeded' in err_str or 'timeout' in err_str.lower():
                my_log.log_gemini(f'my_transcribe.py:transcribe_genai: Key/API error. Getting new key. Error: {err_str}')
                if 'API key' in err_str or 'Quota exceeded' in err_str:
                    my_gemini_general.remove_key(key)
                # Continue outer loop to get a new key
            else:
                traceback_error = traceback.format_exc()
                my_log.log_gemini(f'my_transcribe.py:transcribe_genai: Unrecoverable error: {outer_error}\n{traceback_error}')
                break # Break outer loop on unhandled errors
        finally:
            # Cleanup is now non-blocking and robust
            if uploaded_file and client:
                _robust_delete_file(client, uploaded_file.name)

    # Fallback after all attempts
    if final_response_text and not detect_repetitiveness(final_response_text):
        return final_response_text
    else:
        my_log.log_gemini('my_transcribe.py:transcribe_genai: Gemini failed or produced repetitive text, falling back to stt_google_pydub_v2.')
        return stt_google_pydub_v2(audio_file, lang=language)


def transcribe_groq(audio_file: str, prompt: str = '', language: str = 'ru') -> str:
    '''
    This function takes an audio file path and an optional prompt as input and returns the transcribed text.

    Parameters
    audio_file: The path to the audio file. This can be a local file path or a YouTube URL.
    prompt: An optional prompt to provide to the Grow API. This can be used to guide the transcription process.
    language: The language of the audio file. This is used to select the appropriate language model for transcription.
    Returns
    The transcribed text.

    Raises
    Exception: If an error occurs during transcription.
    '''
    if my_ytb.valid_youtube_url(audio_file):
        audio_file_ = my_ytb.download_ogg(audio_file)
        result = transcribe_groq(audio_file_, prompt, language)
        utils.remove_file(audio_file_)
        return result

    try:
        # if not prompt:
        #     prompt = "Listen carefully to the following audio file. Provide a transcript. Fix errors, make a fine text."

        with open(audio_file, 'rb') as f:
            data = f.read()

        for _ in range(3):
            text = my_groq.stt(data, lang=language, prompt=prompt).strip()
            if text:
                return text
            time.sleep(2)

        if not text:
            # return stt_google_pydub_v2(audio_file, lang = language)
            return transcribe_genai(audio_file, prompt, language)
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_gemini(f'my_transcribe.py:transcribe_roq: Failed to convert audio data to text: {error}\n\n{traceback_error}')
        return transcribe_genai(audio_file, prompt, language)


def download_worker(video_url: str, part: tuple, n: int, fname: str, language: str):
    with download_worker_semaphore:
        utils.remove_file(f'{fname}_{n}.ogg')
        if hasattr(cfg, 'YTB_PROXY') and cfg.YTB_PROXY:
            proc = subprocess.run([YT_DLP, '-x', '--proxy', random.choice(cfg.YTB_PROXY), '-g', video_url], stdout=subprocess.PIPE)
        else:
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

        text = my_groq.stt(f'{fname}_{n}.ogg', language=language)
        if not text:
            text = transcribe_genai(f'{fname}_{n}.ogg', language=language)

        if text:
            with open(f'{fname}_{n}.txt', 'w', encoding='utf-8') as f:
                f.write(text)

        utils.remove_file(f'{fname}_{n}.ogg')


def download_worker_v2(video_url: str, part: tuple, n: int, fname: str, language: str):
    with download_worker_semaphore_v2:
        utils.remove_file(f'{fname}_{n}.ogg')

        if hasattr(cfg, 'YTB_PROXY') and cfg.YTB_PROXY:
            proc = subprocess.run([YT_DLP, '-x', '--proxy', random.choice(cfg.YTB_PROXY), '-g', video_url], stdout=subprocess.PIPE)
        else:
            proc = subprocess.run([YT_DLP, '-x', '-g', video_url], stdout=subprocess.PIPE)
        stream_url = proc.stdout.decode('utf-8', errors='replace').strip()

        proc = subprocess.run([FFMPEG, '-ss', str(part[0]), '-i', stream_url, '-t',
                        str(part[1]), f'{fname}_{n}.ogg'],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out_ = proc.stdout.decode('utf-8', errors='replace').strip()
        err_ = proc.stderr.decode('utf-8', errors='replace').strip()
        if 'error' in err_:
            my_log.log2(f'my_transcribe:download_worker_v2: Error in FFMPEG: {err_}')
        if 'error' in out_:
            my_log.log2(f'my_transcribe:download_worker_v2: Error in FFMPEG: {out_}')

        text = transcribe_groq(f'{fname}_{n}.ogg', language=language)

        if text:
            with open(f'{fname}_{n}.txt', 'w', encoding='utf-8') as f:
                f.write(text)

        utils.remove_file(f'{fname}_{n}.ogg')


@cachetools.func.ttl_cache(maxsize=10, ttl=10 * 60)
def get_url_video_duration(url: str, proxy: bool = True) -> int:
    '''return duration of video, get with yt-dlp'''
    if hasattr(cfg, 'YTB_PROXY') and cfg.YTB_PROXY and proxy:
        proc = subprocess.run([YT_DLP, '--proxy', random.choice(cfg.YTB_PROXY), '--skip-download', '-J', url], stdout=subprocess.PIPE)
    else:
        proc = subprocess.run([YT_DLP, '--skip-download', '-J', url], stdout=subprocess.PIPE)
    output = proc.stdout.decode('utf-8', errors='replace')
    info = json.loads(output)
    try:
        duration = info['duration']
    except:
        duration = 0
    if duration == 0 and proxy:
        return get_url_video_duration(url, proxy = False)
    return duration


def download_youtube_clip(video_url: str, language: str):
    """
    Скачивает видео с YouTube по частям, транскрибирует.
    Возвращает транскрипцию к видео. text, info(dict с информацией о видео)
    language - язык для транскрибации, используется только для кусков которые джемини сфейлил.
               у джемини автоопределение языков а у резерва нет
    """

    part_size = 10 * 60 # размер куска несколько минут
    treshold = 5 # захватывать +- несколько секунд в каждом куске

    duration = get_url_video_duration(video_url)

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


def download_youtube_clip_v2(video_url: str, language: str):
    """
    Скачивает видео с YouTube по частям, транскрибирует.
    Возвращает транскрипцию к видео. text, info(dict с информацией о видео)
    language - язык для транскрибации, используется только для кусков которые groq.
               у groq автоопределение языков а у резерва нет
    """

    part_size = 10 * 60 # размер куска несколько минут
    treshold = 5 # захватывать +- несколько секунд в каждом куске

    if hasattr(cfg, 'YTB_PROXY') and cfg.YTB_PROXY:
        proc = subprocess.run([YT_DLP, '--proxy', random.choice(cfg.YTB_PROXY), '--skip-download', '-J', video_url], stdout=subprocess.PIPE)
    else:
        proc = subprocess.run([YT_DLP, '--skip-download', '-J', video_url], stdout=subprocess.PIPE)
    output = proc.stdout.decode('utf-8', errors='replace')
    info = json.loads(output)
    try:
        duration = info['duration']
    except:
        duration = 0
    if not duration or duration == 0 or duration > 4*60*60:
        return '', info
    my_log.log2(f'my_transcribe:download_youtube_clip_v2: {video_url} Duration: {duration}')

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
        t = threading.Thread(target=download_worker_v2, args=(video_url, part, n, output_name, language))
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
        if hasattr(cfg, 'YTB_PROXY') and cfg.YTB_PROXY:
            proc = subprocess.run([YT_DLP, '--proxy', random.choice(cfg.YTB_PROXY), '--skip-download', '-J', audio_file], stdout=subprocess.PIPE)
        else:
            proc = subprocess.run([YT_DLP, '--skip-download', '-J', audio_file], stdout=subprocess.PIPE)
        output = proc.stdout.decode('utf-8', errors='replace')
        info = json.loads(output)
        duration__ = info['duration']
        if hasattr(cfg, 'YTB_PROXY') and cfg.YTB_PROXY:
            proc = subprocess.run([YT_DLP, '-x', '--proxy', random.choice(cfg.YTB_PROXY), '-g', audio_file], stdout=subprocess.PIPE)
        else:
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


@cachetools.func.ttl_cache(maxsize=10, ttl=1 * 60)
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
        # print("Не удалось распознать речь в сегменте.")
        return (index, "")
    except sr.RequestError as e:
        print(f"Ошибка при распознавании речи: {e}")
        return (index, "")


def split_audio_file(audio_file_path: str, max_split_size: int = 18 * 1024 * 1024) -> List[str]:
    """
    Splits an audio file into multiple parts of a specified maximum size using ffmpeg.

    Args:
        audio_file_path: The path to the input audio file.
        max_split_size: The maximum size of each split in bytes.

    Returns:
        A list of paths to the generated audio files.
    """

    # Get the file size and duration of the audio file using ffprobe
    file_size_command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=size",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        audio_file_path,
    ]
    file_size_output = subprocess.check_output(file_size_command).decode("utf-8").strip()
    total_file_size = float(file_size_output)

    duration_command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        audio_file_path,
    ]
    duration_output = subprocess.check_output(duration_command).decode("utf-8").strip()
    total_duration = float(duration_output)

    # Calculate the number of splits needed
    num_splits = int(total_file_size / max_split_size) + 1

    # Calculate the duration of each split
    split_duration = total_duration / num_splits

    # Split the audio file using ffmpeg
    split_files = []
    for i in range(num_splits):
        start_time = i * split_duration
        output_file = os.path.splitext(audio_file_path)[0] + f"_{i}" + os.path.splitext(audio_file_path)[1]

        split_command = [
            "ffmpeg",
            "-i",
            audio_file_path,
            "-ss",
            str(start_time),
            "-t",
            str(split_duration),
            "-c",
            "copy",
            output_file,
        ]

        subprocess.run(split_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        split_files.append(output_file)

    return split_files


def download_audio_file(url: str, max_size: int = 150*1024*1024, chunk_size: int = 1 * 1024 * 1024) -> str:
    """
    Downloads a file from the given URL in chunks.

    Args:
        url: The URL of the file to download.
        max_size: The maximum allowed size of the file in bytes.
        chunk_size: The size of each chunk to download in bytes.

    Returns:
        The path to the downloaded file if the download was successful.
        If the download was aborted due to exceeding the maximum size or an error occurred, returns an empty string.
    """
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()

        temp_filename =  utils.get_tmp_fname() + url[-4:]

        downloaded_size = 0
        with open(temp_filename, 'wb') as temp_file:
            for chunk in response.iter_content(chunk_size=chunk_size):
                downloaded_size += len(chunk)
                if downloaded_size > max_size:
                    temp_file.close()
                    os.remove(temp_filename)
                    return ""
                temp_file.write(chunk)
        temp_file.close()
        return temp_filename
    except Exception as error:
        my_log.log2(f'my_transcribe:download_audio_file: {error}')
        os.remove(temp_filename)
        return ""


def transcribe_audio_file_web(url: str) -> str:
    '''
    Транскрибирует аудио файл, скачивает, режет на куски и отдает из в groq-whisper (google backup)
    '''
    source_file = download_audio_file(url)
    if not source_file:
        return ''
    segments = split_audio_file(source_file)
    text = ''
    for segment in segments:
        text += transcribe_groq(segment) + '\n\n'

    for segment in segments:
        utils.remove_file(segment)

    utils.remove_file(source_file)

    return text


if __name__ == '__main__':
    pass
    my_groq.load_users_keys()
    my_gemini_general.load_users_keys()

    # urls = [
    #     'https://www.youtube.com/shorts/4cFxuSQ4yro',
    #     # 'https://www.youtube.com/watch?v=rR19alK6QKM',
    #     # 'https://www.youtube.com/watch?v=fPO76Jlnz6c&pp=ygUT0L_QtdGB0L3QuCDRhdC40YLRiw%3D%3D',
    #     # 'https://www.youtube.com/watch?v=5Fix7P6aGXQ&pp=ygU10LAg0YLRiyDRgtCw0LrQvtC5INC60YDQsNGB0LjQstGL0Lkg0YEg0LHQvtGA0L7QtNC-0Lk%3D',
    #     # 'https://www.youtube.com/watch?v=xfT645b6l0s&pp=ygUX0L_QvtC60LjQvdGD0LvQsCDRh9Cw0YI%3D',
    # ]
    # for x in urls:
    #     r = download_youtube_clip_v2(x, 'ru')
    #     print(r[0])

    # print(transcribe_genai('d:\\downloads\\1.ogg', prompt='_'))
    # genai_clear()

    # f = download_audio_file('https://cdn.radio-t.com/rt_podcast942.mp3')
    # print(f)
    # f = split_audio_file('C:/Users/user/AppData/Local/Temp/tmpeuzzy252.mp3')
    # print(f)

    # r = transcribe_audio_file_web('https://cdn.radio-t.com/rt_podcast942.mp3')
    # print(r)

