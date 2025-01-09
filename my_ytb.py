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

import natsort.natsort

import my_log
import utils
import cfg


LOCK_TRANSCODE = threading.Lock()


def download_ogg(url: str) -> str:
    '''Downloads audio from a youtube URL, saves it to a temporary file in OGG format, and returns the path to the OGG file.'''
    tmp_file = utils.get_tmp_fname()
    subprocess.run(['yt-dlp', '-x', '--audio-format', 'vorbis', '-o', tmp_file, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return tmp_file + '.ogg'


@cachetools.func.ttl_cache(maxsize=10, ttl=10 * 60)
def valid_youtube_url(url: str) -> str:
    """
    Checks if the URL is a valid YouTube URL using yt-dlp, with proxy support.

    Supports various YouTube URL formats:
    - youtu.be/
    - youtube.com/watch?v=
    - m.youtube.com/watch?v=
    - youtube-nocookie.com/embed/

    Args:
        url: The URL string to check.

    Returns:
        The YouTube video ID if the URL is valid, otherwise an empty string.
    """
    try:
        url = url.strip()
        if not url.lower().startswith('http'):
            return ''

        # Check if a proxy is configured
        if hasattr(cfg, 'YTB_PROXY') and cfg.YTB_PROXY:
            # Use a random proxy from the list
            proxy = random.choice(cfg.YTB_PROXY)
            process = subprocess.run([
                'yt-dlp',
                '--print', '%(id)s',
                '--skip-download',  # Skip downloading the video
                '--proxy', proxy,
                url
            ], capture_output=True, text=True, check=True)
        else:
            # No proxy configured, use yt-dlp directly
            process = subprocess.run([
                'yt-dlp',
                '--print', '%(id)s',
                '--skip-download',  # Skip downloading the video
                url
            ], capture_output=True, text=True, check=True)

        # Extract the video ID from the output
        video_id = process.stdout.strip()

        # Check if the extracted ID is not empty
        if video_id:
            return video_id
        else:
            my_log.log2(f'my_ytb:valid_youtube_url1: Invalid YouTube URL: {url}')
            return ''

    except subprocess.CalledProcessError as error:
        error_traceback = traceback.format_exc()
        my_log.log2(f'my_ytb:valid_youtube_url2: {url} {error}\n\n{error_traceback}')
        return ''


# @cachetools.func.ttl_cache(maxsize=10, ttl=10 * 60)
# def valid_other_video_url(url: str) -> bool:
#     """
#     Checks if the URL is a valid video link that can be downloaded by yt-dlp.
#     Attempts to get the file size as a way to validate.
#     Uses a proxy if available in the configuration.
#     Limit of 8000 seconds

#     Args:
#         url: The URL string to check.

#     Returns:
#         True if it's a valid video link, otherwise False.
#     """
#     try:
#         if not url.lower().startswith('https://'):
#             return False

#         # Use yt-dlp to check the file size without downloading
#         if hasattr(cfg, 'YTB_PROXY') and cfg.YTB_PROXY:
#             proxy = random.choice(cfg.YTB_PROXY)
#             process = subprocess.run([
#                 'yt-dlp',
#                 '--print', 'filesize',
#                 '--skip-download',  # Skip downloading the video
#                 '--proxy', proxy,
#                 url
#             ], capture_output=True, text=True, check=True)
#         else:
#             process = subprocess.run([
#                 'yt-dlp',
#                 '--print', 'duration',
#                 '--skip-download',  # Skip downloading the video
#                 url
#             ], capture_output=True, text=True, check=True)

#         # If the output is not empty and can be converted to an integer, it's likely a valid video
#         duration = process.stdout.strip()
#         if duration and duration.isdigit():
#             duration = int(duration)
#             if duration < 8000:
#                 return True
#             else:
#                 return False
#         else:
#             # my_log.log2(f'my_ytb:valid_other_video_url1: Invalid video URL or no file size: {url}')
#             return False

#     except subprocess.CalledProcessError as error:
#         error_traceback = traceback.format_exc()
#         my_log.log2(f'my_ytb:valid_other_video_url2: {url} {error}\n\n{error_traceback}')
#         return False


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


@cachetools.func.ttl_cache(maxsize=10, ttl=10 * 60)
def get_title_and_poster(url: str) -> Tuple[str, str, str, int]:
    """
    Gets the title, thumbnail URL, description, and size of a YouTube video using yt-dlp.

    Args:
        url: The URL of the YouTube video.

    Returns:
        A tuple containing the title, thumbnail URL, description, and size (duration in seconds) of the video.
        If an error occurs, returns a tuple of four empty strings or 0 for size.
    """
    try:
        # Use yt-dlp to extract video information
        if hasattr(cfg, 'YTB_PROXY') and cfg.YTB_PROXY:
            proxy = random.choice(cfg.YTB_PROXY)
            process = subprocess.run([
                'yt-dlp',
                '--dump-json',
                '--proxy', proxy,
                url
            ], capture_output=True, text=True, check=True)
        else:
            process = subprocess.run([
                'yt-dlp',
                '--dump-json',
                url
            ], capture_output=True, text=True, check=True)

        # Parse the JSON output
        video_info = json.loads(process.stdout)

        # Extract the required information
        title = video_info.get('title', '')
        thumbnail_url = video_info.get('thumbnail', '')
        description = video_info.get('description', '')
        size = video_info.get('duration', 0)

        return title, thumbnail_url, description, size

    except (subprocess.CalledProcessError, json.JSONDecodeError) as error:
        my_log.log2(f'my_ytb:get_title_and_poster {url} {error}')
        return '', '', '', 0


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


def convert_to_mp3(input_file: str) -> str | None:
    """
    Converts an audio file to MP3 format using ffmpeg with the highest quality settings.

    Args:
        input_file: Path to the input audio file.

    Returns:
        Path to the converted MP3 file, or None if an error occurred.
    """
    with LOCK_TRANSCODE:
        try:
            output_file = utils.get_tmp_fname() + '.mp3'

            # LAME Bitrate Overview
            # lame option | Average kbit/s | Bitrate range kbit/s      | ffmpeg option
            # ----------- | --------------- | ----------------------- | -------------
            # -b 320      | 320             | 320 CBR (non VBR) example | -b:a 320k (NB this is 32KB/s, or its max)
            # -V 0        | 245             | 220-260                 | -q:a 0 (NB this is VBR from 220 to 260 KB/s)
            # -V 1        | 225             | 190-250                 | -q:a 1
            # -V 2        | 190             | 170-210                 | -q:a 2
            # -V 3        | 175             | 150-195                 | -q:a 3
            # -V 4        | 165             | 140-185                 | -q:a 4
            # -V 5        | 130             | 120-150                 | -q:a 5
            # -V 6        | 115             | 100-130                 | -q:a 6
            # -V 7        | 100             | 80-120                  | -q:a 7
            # -V 8        | 85              | 70-105                  | -q:a 8
            # -V 9        | 65              | 45-85                   | -q:a 9

            subprocess.run([
                'ffmpeg',
                '-i',
                input_file,
                '-vn',  # Disable video processing
                '-acodec',
                'libmp3lame',  # Use libmp3lame for MP3 encoding
                '-q:a',
                '2',  # Use -q:a for VBR (Variable Bit Rate)
                # 0 is the highest quality, 9 is the lowest
                '-loglevel',
                'error',
                output_file
            ], check=True)

            return output_file

        except subprocess.CalledProcessError as error:
            my_log.log2(f'convert_to_mp3: error: {error}\n\n{traceback.format_exc()}')
            return None


def download_audio(url: str) -> str | None:
    """
    Downloads audio file using yt-dlp to a temporary folder
    with audio quality 128k or lower. If small file them download best quality.

    Args:
        url: Link to the audio file.

    Returns:
        Path to the downloaded file in the temporary folder, or None if download failed.
    """
    output_template = utils.get_tmp_fname()

    try:
        duration = get_title_and_poster(url)[3]
        if duration < 10*60:
            quality = 'bestaudio'
        else:
            quality = 'bestaudio[abr<=128]/bestaudio'
        if hasattr(cfg, 'YTB_PROXY') and cfg.YTB_PROXY:
            proxy = random.choice(cfg.YTB_PROXY)
            subprocess.run([
                'yt-dlp',
                '-f', quality,
                '--proxy', proxy,
                '-o', output_template,
                url
            ], check=True)
        else:
            subprocess.run([
                'yt-dlp',
                '-f', quality,
                '-o', output_template,
                url
            ], check=True)
    except subprocess.CalledProcessError:
        return None

    r = output_template
    if quality == 'bestaudio':
        r2 = convert_to_mp3(r)
        if r2:
            utils.remove_file(r)
            return r2
        else:
            return None
    return r


def remove_folder_or_parent(path: str) -> None:
    """
    Removes a file or folder within the root temporary directory.
    If a file is given, its parent directory is removed.

    Args:
        path: Path to the file or folder to remove.
    """
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
