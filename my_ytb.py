#!/usr/bin/env python3
# pip install youtube_search


import os
import threading

from youtube_search import YoutubeSearch

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
        except ValueError:
            try:
                minutes, seconds = x['duration'].split(":")
                dur_seconds = int(minutes) * 60 + int(seconds)
            except ValueError:
                dur_seconds = int(x['duration'])

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


if __name__ == '__main__':

    results = search_youtube('линкин парк на русском', 10)

    d = download_youtube(results[0][2])
    print(results[0], len(d))