#!/usr/bin/env python3
# pip install pytube


import subprocess

import pytube

import utils


def download_ogg(url: str) -> str:
    '''download audio from youtube url, save to temp file in ogg format, return path to ogg file'''
    tmp_file = utils.get_tmp_fname()
    subprocess.run(['yt-dlp', '-x', '--audio-format', 'vorbis', '-o', tmp_file, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # subprocess.run(['yt-dlp', '-x', '--audio-format', 'vorbis', '-o', tmp_file, url])
    return tmp_file + '.ogg'


def valid_youtube_url(url: str) -> str:
    '''check if url is valid youtube url, all variants are supported
       returns video id or empty string'''
    if url.startswith('https://') and len(url.split()) == 1 and ('youtu.be/' in url or 'youtube.com/' in url):
        try:
            id_ = pytube.extract.video_id(url)
            if '-nocookie' in url:
                id_ = pytube.extract.video_id(url.replace('-nocookie', ''))
        except Exception as error:
            return ''
        return id_
    return ''


def get_title(url: str) -> str:
    try:
        yt = pytube.YouTube(url)
        return yt.title
    except Exception as error:
        return ''


if __name__ == '__main__':
    pass
    # print(download_ogg('https://www.youtube.com/watch?v=dQw4w9WgXcQ'))

    # # Примеры использования:
    # urls = [
    #     "fjkghjkdf реезЖ.",
    #     "https://www.youtube.com/watch?v=dQw4w9WgXcQ ыдгаыврапварп",
    #     "fgkgdfkhgdfkg https://www.youtube.com/watch?v=dQw4w9WgXcQ dhgjkdfhgjkdfhg",
    #     "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    #     "http://youtube.com/watch?v=dQw4w9WgXcQ",
    #     "https://youtu.be/dQw4w9WgXcQ",
    #     "https://youtube-nocookie.com/embed/dQw4w9WgXcQ",
    #     "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
    #     "https://invalid.com/watch?v=dQw4w9WgXcQ"
    # ]

    # for url in urls:
    #     video_id = valid_youtube_url(url)
    #     print(f"{url} -> {video_id}")
    