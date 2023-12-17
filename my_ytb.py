#!/usr/bin/env python3
# pip install youtube_search
# pip install pytube


import concurrent.futures
import os
import random
import threading
import time

from pytube import YouTube
from youtube_search import YoutubeSearch

import gpt_basic
import my_log
import utils


BIG_LOCK = threading.Lock()


GENRES = ['rock', 'pop', 'folk', 'dance', 'rusrap', 'ruspop', 'world', 'electronic',
 'alternative', 'children', 'rnb', 'hip', 'jazz', 'postrock', 'latin',
 'classical', 'metal', 'reggae', 'tatar', 'blues', 'instrumental', 'rusrock',
 'dnb', 'türk', 'post', 'country', 'psychedelic', 'conjazz', 'indie',
 'posthardcore', 'local', 'avantgarde', 'punk', 'videogame', 'techno', 'house',
 'christmas', 'melodic', 'caucasian', 'reggaeton', 'soundtrack', 'singer', 'ska',
 'shanson', 'ambient', 'film', 'western', 'rap', 'beats', "hard'n'heavy",
 'progmetal', 'minimal', 'contemporary', 'new', 'soul', 'holiday', 'german',
 'tropical', 'fairytail', 'spiritual', 'urban', 'gospel', 'nujazz', 'folkmetal',
 'trance', 'miscellaneous', 'anime', 'hardcore', 'progressive', 'chanson',
 'numetal', 'vocal', 'estrada', 'russian', 'classicmetal', 'dubstep', 'club',
 'deep', 'southern', 'black', 'folkrock', 'fitness', 'french', 'disco', 
 'religious', 'hiphop', 'drum', 'extrememetal', 'türkçe', 'experimental', 'easy',
 'metalcore', 'modern', 'argentinetango', 'old', 'breaks', 'eurofolk', 
 'stonerrock', 'industrial', 'funk', 'jpop', 'middle', 'variété', 'other', 
 'adult', 'christian', 'gothic', 'international', 'muslim', 'relax', 'schlager',
 'caribbean', 'ukrrock', 'nu', 'breakbeat', 'comedy', 'chill', 'newage',
 'specialty', 'uzbek', 'k-pop', 'balkan', 'chinese', 'meditative', 'dub', 'power', 
 'death', 'grime', 'arabesk', 'romance', 'flamenco', 'leftfield', 'european',
 'tech', 'newwave', 'dancehall', 'mpb', 'piano', 'top', 'bigroom', 'opera',
 'celtic', 'tradjazz', 'acoustic', 'epicmetal', 'historisch', 'downbeat', 
 'downtempo', 'africa', 'audiobook', 'jewish', 'sängerportrait', 'deutschrock', 
 'eastern', 'action', 'future', 'electropop', 'folklore', 'bollywood', 
 'marschmusik', 'rnr', 'karaoke', 'indian', 'rancheras', 'электроника',
 'afrikaans', 'tango', 'rhythm', 'sound', 'deutschspr', 'trip', 'lovers',
 'choral', 'dancepop', 'podcasts', 'retro', 'smooth', 'mexican', 'brazilian',
 'mood', 'surf', 'author', 'gangsta', 'triphop', 'inspirational', 'idm',  
 'ethnic', 'bluegrass', 'broadway', 'animated', 'americana', 'karadeniz',  
 'rockabilly', 'colombian', 'self', 'synthrock', 'sertanejo', 'japanese',  
 'canzone', 'swing', 'lounge', 'sport', 'korean', 'ragga', 'traditional',
 'gitarre', 'frankreich', 'alternativepunk', 'emo', 'laiko', 'cantopop',  
 'glitch', 'documentary', 'rockalternative', 'thrash', 'hymn', 'oceania',  
 'rockother', 'popeurodance', 'dark', 'vi', 'grunge', 'hardstyle', 'samba',
 'garage', 'soft', 'art', 'folktronica', 'entehno', 'mediterranean', 'chamber',
 'cuban', 'taraftar', 'rockindie', 'gypsy', 'hardtechno', 'shoegazing',
 'skarock', 'bossa', 'salsa', 'latino', 'worldbeat', 'malaysian', 'baile',
 'ghazal', 'loungeelectronic', 'arabic', 'popelectronic', 'acid', 'kayokyoku',
 'neoklassik', 'tribal', 'tanzorchester', 'native', 'independent', 'cantautori', 
 'handsup', 'poprussian', 'punjabi', 'synthpop', 'rave', 'französisch',  
 'quebecois', 'speech', 'soulful', 'teen', 'jam', 'ram', 'horror', 'scenic',  
 'orchestral', 'neue', 'roots', 'slow', 'jungle', 'indipop', 'axé', 'fado',
 'showtunes', 'arena', 'irish', 'mandopop', 'forró', 'popdance', 'dirty',
 'regional']

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
    # tmpfname = utils.get_tmp_fname() + '.mp3'
    tmpfname = utils.get_tmp_fname()

    url = f'https://youtube.com/watch?v={id}'

    with BIG_LOCK:
        # os.system(f'yt-dlp -f "ba" -x --audio-format mp3 -o "{tmpfname}" "{url}"')
        os.system(f'yt-dlp -f "ba" -o "{tmpfname}" "{url}"')

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
сначала название песни потом тире потом альбом или группа, используй только реально существующие песни,
жанры только эти: {', '.join(random.sample(GENRES, 20))}.

Пример:
нимб - линкин парк"""
    songs = []
    for _ in range(3):
        songs = [x.strip() for x in gpt_basic.ai_instruct(prompt=PROMPT, temp=1).split('\n') if x]
        if songs:
            break
        time.sleep(3)
    if not songs:
        return []

    try:
        # Создаем пул потоков
        with concurrent.futures.ThreadPoolExecutor() as executor:
            # Запускаем поиск по каждой песне в параллельном потоке
            futures = [executor.submit(search_youtube, song, limit=5) for song in songs]
            # Получаем результаты поиска
            results = [future.result()[0] for future in futures]
        return results
    except:
        return []


def get_video_info(vid_id: str) -> str:
    url = f'https://youtube.com/watch?v={vid_id}'

    yt = YouTube(url,
                #  use_oauth=True,
                #  allow_oauth_cache=True
                 )

    title = yt.title
    autor = yt.author
    length = yt.length
    # metadata = yt.metadata
    publish_date = yt.publish_date
    # vid_info = yt.vid_info
    views = yt.views
    # captions = yt.captions
    description = yt.description
    result = f"""URL: {url}
Название: {title}
Автор: {autor}
Описание: {description}

Продолжительность: {length} (секунды)
Дата публикации: {publish_date}
Просмотры: {views}
"""
    return result


if __name__ == '__main__':

    # results = search_youtube('линкин парк на русском', 10)
    # results = get_random_songs(10)

    # d = download_youtube(results[0][2])
    # print(results[0], len(d))
    
    print(get_video_info('FAAM7wdtXmg'))