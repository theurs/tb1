#!/usr/bin/env python3


import io
import json
import os
import random
import subprocess
import threading
import time
import traceback
import zlib

import speech_recognition as sr
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from pydub import AudioSegment
from pydub.silence import split_on_silence


import cfg
import my_gemini
import my_log
import utils


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
    compressed_data = zlib.compress(text.encode())
    ratio = len(text.encode()) / len(compressed_data)
    my_log.log_entropy_detector(f'{len(text)} {len(compressed_data)} {ratio}\n\n{text}')
    # return len(compressed_data), len(text.encode()), len(text.encode()) / len(compressed_data)
    return ratio > 4


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
                return stt_google_pydub(audio_file, language = language)
            return response.text.strip()
        else:
            return stt_google_pydub(audio_file, language = language)
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_gemini(f'my_transcribe.py:transcribe_genai: Failed to convert audio data to text: {error}\n\n{traceback_error}')
        return stt_google_pydub(audio_file, language = language)


def download_worker(video_url: str, part: tuple, n: int, fname: str, language: str):
    with download_worker_semaphore:
        try:
            os.unlink(f'{fname}_{n}.ogg')
        except:
            pass
        proc = subprocess.run([YT_DLP, '-x', '-g', video_url], stdout=subprocess.PIPE)
        stream_url = proc.stdout.decode('utf-8').strip()

        proc = subprocess.run([FFMPEG, '-ss', str(part[0]), '-i', stream_url, '-t',
                        str(part[1]), f'{fname}_{n}.ogg'],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out_ = proc.stdout.decode('utf-8').strip()
        err_ = proc.stderr.decode('utf-8').strip()
        if 'error' in err_:
            my_log.log2(f'my_transcribe:download_worker: Error in FFMPEG: {err_}')
        if 'error' in out_:
            my_log.log2(f'my_transcribe:download_worker: Error in FFMPEG: {out_}')

        text = transcribe_genai(f'{fname}_{n}.ogg', language=language)

        if text:
            with open(f'{fname}_{n}.txt', 'w', encoding='utf-8') as f:
                f.write(text)

        try:
            os.unlink(f'{fname}_{n}.ogg')
        except:
            my_log.log2(f'download_worker: Failed to delete audio file: {fname}_{n}.ogg')


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
    output = proc.stdout.decode('utf-8')
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
            try:
                os.unlink(f'{output_name}_{x}.txt')
            except:
                my_log.log2(f'my_transcribe:download_youtube_clip: Failed to delete {output_name}_{x}.txt')

    return result, info


def gemini_tokens_count(text: str) -> int:
    genai.configure(api_key=cfg.gemini_keys[0])
    # print([(x.name, x.input_token_limit, x.output_token_limit, x.supported_generation_methods) for x in genai.list_models()])
    response = genai.count_message_tokens(prompt=text)
    return response['token_count']


if __name__ == '__main__':
    pass

    # t = 'Это пример текста с определенными повторяющимися элементами, элементами элементами'
    # print(detect_repetitiveness(t))
    # t = 'Это пример текста с определенными повторяющимися элементами, элементами элементами' + ' элементами'*10
    # print(detect_repetitiveness(t))
    # t = 'Это пример текста с определенными повторяющимися элементами, элементами элементами' + ' элементами'*100
    # print(detect_repetitiveness(t))
    # t = 'Это пример текста с определенными повторяющимися элементами, элементами элементами' + ' элементами'*1000
    # print(detect_repetitiveness(t))

    # download_youtube_clip('https://www.youtube.com/watch?v=hEBQNq5FiFQ')
    # download_youtube_clip('https://www.youtube.com/shorts/e2OaVTW_tlA')
    # download_youtube_clip('https://www.youtube.com/watch?v=MowRjPRK0I4')

    # print(transcribe_genai(files[0]))

    # genai_clear()

    # start_time = time.time()
    # t = download_youtube_clip('https://www.youtube.com/watch?v=hHiQpGgISj8')
    # with open('test.txt', 'w', encoding='utf-8') as f:
    #     f.write(t[0])
    #     f.write('\n\n')
    #     f.write(str(t[1]))
    # print(time.time() - start_time)
