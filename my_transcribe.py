#!/usr/bin/env python3


import json
import os
import random
import subprocess
import threading
import time
import traceback

import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

import cfg
import my_gemini
import my_log
import utils


YT_DLP = 'yt-dlp'
FFMPEG = 'ffmpeg'


MAX_THREADS = 8  # Максимальное количество одновременных потоков
download_worker_semaphore = threading.Semaphore(MAX_THREADS)  # Создаем семафор здесь


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


def transcribe_genai(audio_file: str) -> str:
    try:
        keys = cfg.gemini_keys[:] + my_gemini.ALL_KEYS
        random.shuffle(keys)
        key = keys[0]

        your_file = None
        prompt = "Listen carefully to the following audio file. Provide a transcript. Fix errors, make a fine text without time stamps. This audio file is a cutted fragment with +5 extra seconds in both directions."

        for _ in range(3):
            try:
                genai.configure(api_key=key) # здесь может быть рейс кондишн?
                if your_file == None:
                    print(7, audio_file)
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
                my_log.log_gemini(f'Failed to convert audio data to text: {error}')
                response = ''
                time.sleep(2)

        try:
            genai.configure(api_key=key) # здесь может быть рейс кондишн?
            genai.delete_file(your_file.name)
        except Exception as error:
            my_log.log_gemini(f'Failed to delete audio file: {error}\n{key}\n{your_file.name}\n\n{str(your_file)}')

        return response.text.strip() if response else ''
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_gemini(f'Failed to convert audio data to text: {error}\n\n{traceback_error}')


def download_worker(video_url: str, part: tuple, n: int, fname: str):
    print('1')
    with download_worker_semaphore:
        try:
            os.unlink(f'{fname}_{n}.ogg')
        except:
            pass
        print('2')
        proc = subprocess.run([YT_DLP, '-x', '-g', video_url], stdout=subprocess.PIPE)
        stream_url = proc.stdout.decode('utf-8').strip()
        print('3', stream_url)
        # subprocess.run([FFMPEG, '-ss', str(part[0]), '-i', stream_url, '-t',
        #                 str(part[1]), f'{fname}_{n}.ogg'],
        #             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        subprocess.run([FFMPEG, '-ss', str(part[0]), '-i', stream_url, '-t',
                        str(part[1]), f'{fname}_{n}.ogg'])


        print('4', fname, n)
        text = transcribe_genai(f'{fname}_{n}.ogg')
        print('5')
        if text:
            with open(f'{fname}_{n}.txt', 'w', encoding='utf-8') as f:
                f.write(text)
        print('6')
        try:
            os.unlink(f'{fname}_{n}.ogg')
        except:
            my_log.log2(f'download_worker: Failed to delete audio file: {fname}_{n}.ogg')


def download_youtube_clip(video_url: str):
    """
    Скачивает видео с YouTube по частям, транскрибирует.
    Возвращает транскрипцию к видео. text, info(dict с информацией о видео)
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
        t = threading.Thread(target=download_worker, args=(video_url, part, n, output_name))
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
                my_log.log2(f'download_youtube_clip: Failed to delete {output_name}_{x}.txt')

    return result, info


if __name__ == '__main__':
    pass
    # download_youtube_clip('https://www.youtube.com/watch?v=hEBQNq5FiFQ')
    # download_youtube_clip('https://www.youtube.com/shorts/e2OaVTW_tlA')
    # download_youtube_clip('https://www.youtube.com/watch?v=MowRjPRK0I4')

    # print(transcribe_genai(files[0]))

    # genai_clear()

    start_time = time.time()
    t = download_youtube_clip('https://m.youtube.com/watch?v=3YxaaGgTQYM')
    with open('test.txt', 'w', encoding='utf-8') as f:
        f.write(t[0])
        f.write('\n\n')
        f.write(str(t[1]))
    print(time.time() - start_time)
