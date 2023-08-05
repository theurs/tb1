#!/usr/bin/env python3
# pornhub_api yt_dlp
# pydantic==1.10.9??


import os
import random
import subprocess
import telebot
import tempfile
import threading
from pathlib import Path

from pornhub_api import PornhubApi
import yt_dlp  

import my_log


lock = threading.Lock()


def get_screenshots(query: str):
    api = PornhubApi()

    videos = api.search.search_videos(
        query,
        ordering="newest"
    )

    vids = []
    for vid in videos:
        if len(vids) > 3:
            break
        try:
            h, m, s = vid.duration.split(':')
        except:
            try:
                m, s = vid.duration.split(':')
                h = 0
            except Exception as error:
                print(f'my_p_hub:get_screenshots: {error}')
                my_log.log2(f'my_p_hub:get_screenshots: {error}')
                continue
        dur = int(s) + int(m) * 60 + int(h) * 3600
        if dur > 2*60 and dur < 30*60:
            vids.append((vid.url, dur))

    random.shuffle(vids)

    results = []
    threads = []

    for url, dur in vids:
        thread = threading.Thread(target=get_screenshot, args=(url, dur, results))
        thread.start()
        threads.append(thread)

    for thread in threads:
        thread.join()

    medias = [telebot.types.InputMediaPhoto(open(i, 'rb').read(), has_spoiler = True) for i in results]

    for x in results:
        try:
            os.remove(x)
        except FileNotFoundError:
            pass
        except Exception as error:
            print(f'my_p_hub:get_screenshots: {error}')
            my_log.log2(f'my_p_hub:get_screenshots: {error}')

    return medias


def get_screenshot(url: str, dur: int, results):
    filename = ''
    try:
        ydl = yt_dlp.YoutubeDL()
        info_dict = ydl.extract_info(url, download=False)
        direct_link = info_dict['url']

        random_seconds = random.randint(90, dur)
        time_string = f'00:{random_seconds // 60:02d}:{random_seconds % 60:02d}'
        
        temp_dir = tempfile.gettempdir()
        filename = f'{random.randint(100000000, 900000000)}.jpg'
        filename = Path(temp_dir, filename)

        try:
            os.remove(filename)
        except FileNotFoundError:
            pass
        subprocess.run(['ffmpeg', '-ss', time_string, '-i', direct_link, '-frames:v', '1', filename], 
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as error:
        print(f'my_p_hub:get_screenshot: {error}')
        my_log.log2(f'my_p_hub:get_screenshot: {error}')
    
    if filename:
        with lock:
            results.append(filename)


if __name__ == '__main__':
    print(get_screenshots('девушка в нижнем белье'))
    