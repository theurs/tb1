#!/usr/bin/env python3


import cachetools.func
import json
import natsort
import os
import random
import subprocess
import shutil
import tempfile
import threading
import traceback
from typing import List, Tuple

import my_log
import utils
import cfg


download_audio = utils.download_audio
valid_youtube_url = utils.valid_youtube_url
convert_to_mp3 = utils.convert_to_mp3
get_title_and_poster = utils.get_title_and_poster
LOCK_TRANSCODE = utils.LOCK_TRANSCODE



def download_ogg(url: str) -> str:
    '''Downloads audio from a youtube URL, saves it to a temporary file in OGG format, and returns the path to the OGG file.'''
    tmp_file = utils.get_tmp_fname()
    subprocess.run(['yt-dlp', '-x', '--audio-format', 'vorbis', '-o', tmp_file, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return tmp_file + '.ogg'


@cachetools.func.ttl_cache(maxsize=10, ttl=10 * 60)
def get_title(url: str) -> str:
    """
    Gets the title of the YouTube video from the given URL using yt-dlp.
    Uses a proxy if available in the configuration.
    Logs errors using the my_log module.

    Args:
        url: The URL of the YouTube video.

    Returns:
        The title of the video or an empty string if an error occurs.
    """
    try:
        # Check if a proxy is configured
        if hasattr(cfg, 'YTB_PROXY') and cfg.YTB_PROXY:
            # Use a random proxy from the list
            proxy = random.choice(cfg.YTB_PROXY)
            process = subprocess.run([
                'yt-dlp',
                '--print', 'title',
                '--proxy', proxy,
                url
            ], capture_output=True, text=True, check=True)
        else:
            # No proxy configured, use yt-dlp directly
            process = subprocess.run([
                'yt-dlp',
                '--print', 'title',
                url
            ], capture_output=True, text=True, check=True)

        # Get the title from the output
        title = process.stdout.strip()
        return title
    except subprocess.CalledProcessError as error:
        # Log the error using my_log.log2()
        my_log.log2(f'my_ytb:get_title: {url} {error}')
        return ''


def split_audio(input_file: str, max_size_mb: int) -> List[str]:
    """
    Splits an audio file into parts no larger than the specified size using ffmpeg,
    saving them as MP3 files with variable bitrate (VBR).

    Args:
        input_file: Path to the input audio file.
        max_size_mb: Maximum part size in megabytes.

    Returns:
        A list of paths to the MP3 files in a temporary folder.
    """
    file_size = os.path.getsize(input_file)
    if file_size <= max_size_mb * 1024 * 1024:
        duration = utils.audio_duration(input_file)
        if duration < 10 * 60:
            return [input_file,]

    with LOCK_TRANSCODE:
        # Create a temporary folder
        tmp_dir = utils.get_tmp_fname()

        # Create a temporary folder if it doesn't exist
        if not os.path.exists(tmp_dir):
            os.makedirs(tmp_dir)

        output_prefix = os.path.join(tmp_dir, "part")

        segment_time = 5000

        subprocess.run([
            'ffmpeg',
            '-i',
            input_file,
            '-f',
            'segment',
            '-segment_time',
            str(segment_time),
            '-acodec',
            'libmp3lame',
            '-q:a',  # Сохраняем настройку VBR качества
            '8',
            '-maxrate', # Устанавливаем максимальный битрейт
            '80k',
            '-bufsize', # Рекомендуется устанавливать bufsize, обычно в 2 раза больше maxrate
            '168k',
            '-reset_timestamps',
            '1',
            '-loglevel',
            'quiet',
            f'{output_prefix}%03d.mp3'
        ], check=True)

        # Get the list of files in the temporary folder
        files = [os.path.join(tmp_dir, f) for f in os.listdir(tmp_dir) if os.path.isfile(os.path.join(tmp_dir, f))]

        return natsort.natsorted(files)


def remove_folder_or_parent(path: str) -> None:
    """
    Removes a file or folder within the root temporary directory.
    If a file is given, its parent directory is removed.

    Args:
        path: Path to the file or folder to remove.
    """

    if not path:
        return

    temp_dir = tempfile.gettempdir()
    normalized_path = os.path.normpath(path)
    normalized_temp_dir = os.path.normpath(temp_dir)

    if not normalized_path.startswith(normalized_temp_dir):
        my_log.log2(f'my_ytb:remove_folder_or_parent: Path is not within the temporary directory: {path}')
        return

    try:
        if os.path.isfile(normalized_path):
            parent_dir = os.path.dirname(normalized_path)
            if parent_dir == normalized_temp_dir:
                os.remove(normalized_path)
                # my_log.log2(f'my_ytb:remove_folder_or_parent: File removed from root temp dir: {path}')
            else:
                shutil.rmtree(parent_dir)
                # my_log.log2(f'my_ytb:remove_folder_or_parent: Parent directory removed: {parent_dir}')
            return
        elif os.path.isdir(normalized_path):
            shutil.rmtree(normalized_path)
            # my_log.log2(f'my_ytb:remove_folder_or_parent: Directory removed: {path}')
            return
        else:
            my_log.log2(f'my_ytb:remove_folder_or_parent: Path is not a file or directory: {path}')
    except Exception as error:
        my_log.log2(f'my_ytb:remove_folder_or_parent: Error removing path: {error}\n\n{path}')


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



    # files = split_audio("C:/Users/user/AppData/Local/Temp/tmp9ug1aie1/123.m4a", 20) 
    # print(files) # Выведет список файлов во временной папке

    # input = download_audio('https://www.youtube.com/shorts/qgI5Xhap3IY')
    # print(input)

    # print(get_title_and_poster('https://www.youtube.com/watch?v=5F24kWz1tKk'))

    # print(get_title('https://www.youtube.com/watch?v=5F24kWz1tKk'))

    # print(valid_youtube_url('https://www.youtube.com/watch?v=5F24kWz1tKk'))

    # print(download_audio('https://www.youtube.com/shorts/qgI5Xhap3IY'))
    # print(valid_other_video_url('https://vkvideo.ru/video-217672812_456239407'))
