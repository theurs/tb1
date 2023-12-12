#!/usr/bin/env python3
# pip install youtube_search


import concurrent.futures
import os
import threading

from youtube_search import YoutubeSearch

import gpt_basic
import my_log
import utils


BIG_LOCK = threading.Lock()


def search_youtube(query: str, limit: int = 10):
    """
    Search YouTube for videos based on a given query.

    Parameters:
        query (str): The search query to use.
        limit (int, optional): The maximum number of search results to return. Defaults to 10.

    Returns:
        list: A list of tuples containing the title, duration, and ID of each video.
    """
    results = YoutubeSearch(query, max_results=limit).to_dict()

    r = []
    for x in results:
        try:
            hours, minutes, seconds = x['duration'].split(":")
            dur_seconds = int(hours) * 3600 + int(minutes) * 60 + int(seconds)
        except:
            try:
                minutes, seconds = x['duration'].split(":")
                dur_seconds = int(minutes) * 60 + int(seconds)
            except:
                try:
                    dur_seconds = int(x['duration'])
                except:
                    dur_seconds = 0

        if dur_seconds > 20*60:
            continue
        r.append((x['title'], x['duration'], x['id']))

    return r


def download_youtube(id: str) -> bytes:
    """
    Downloads a YouTube video given its ID and returns the video data as bytes.

    Parameters:
        id (str): The ID of the YouTube video.

    Returns:
        bytes: The video data as bytes.
    """
    tmpfname = utils.get_tmp_fname()
    url = f'https://youtube.com/watch?v={id}'

    with BIG_LOCK:
        os.system(f'yt-dlp -f bestaudio -o "{tmpfname}" "{url}"')

    data = b''
    with open(tmpfname, 'rb') as f:
        data = f.read()

    try:
        os.remove(tmpfname)
    except OSError:
        my_log.log2(f'ytb:download_youtube:Cannot remove tmp file {tmpfname}')

    return data


def get_random_songs(limit: int = 10):
    PROMPT = f"""Посоветует хорошую музыку. Дай список из {limit} песен,
без оформления списка просто одна песня на одной строке без цифр, для поиска на Ютубе в таком виде,
сначала название песни потом тире потом альбом или группа, используй только реально существующие песни.

Пример:
нимб - линкин парк"""
    songs = [x.strip() for x in gpt_basic.ai_instruct(prompt=PROMPT, temp=1).split('\n') if x]
    try:
        # Создаем пул потоков
        with concurrent.futures.ThreadPoolExecutor() as executor:
            # Запускаем поиск по каждой песне в параллельном потоке
            futures = [executor.submit(search_youtube, song, limit=1) for song in songs]
            # Получаем результаты поиска
            results = [future.result()[0] for future in futures]
        return results
    except:
        return []


if __name__ == '__main__':

    # results = search_youtube('линкин парк на русском', 10)
    results = get_random_songs(10)

    d = download_youtube(results[0][2])
    print(results[0], len(d))