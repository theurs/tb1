#!/usr/bin/env python3


import json
import natsort
import os
import random
import subprocess
import shutil
import tempfile
import threading
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
        my_log.log2(f'my_ytb:valid_youtube_url2: {url} {error}')
        return ''


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
    with LOCK_TRANSCODE:
        # Create a temporary folder
        tmp_dir = tempfile.mkdtemp()

        # Create a temporary folder if it doesn't exist
        if not os.path.exists(tmp_dir):
            os.makedirs(tmp_dir)

        output_prefix = os.path.join(tmp_dir, "part")

        # Calculate the segment time in seconds based on the average bitrate
        # We'll use an average bitrate of 64kbps for the calculation
        bit_rate = 64000
        segment_time = int(max_size_mb * 8 * 1000 * 1000 / bit_rate)

        subprocess.run([
            'ffmpeg',
            '-i',
            input_file,
            '-f',
            'segment',
            '-segment_time',
            str(segment_time),
            '-acodec',
            'libmp3lame',  # Use libmp3lame for MP3 encoding
            '-q:a',  # Use -q:a for VBR
            '6',  # VBR quality level (0-9, 0 being the highest quality)
            '-reset_timestamps',
            '1',
            '-loglevel',
            'quiet',
            f'{output_prefix}%03d.mp3'  # Save as MP3 files
        ], check=True)

        # Get the list of files in the temporary folder
        files = [os.path.join(tmp_dir, f) for f in os.listdir(tmp_dir) if os.path.isfile(os.path.join(tmp_dir, f))]

        return natsort.natsorted(files)


def download_audio(url: str) -> str | None:
    """
    Downloads audio file using yt-dlp to a temporary folder
    with audio quality 128k or lower.

    Args:
        url: Link to the audio file.

    Returns:
        Path to the downloaded file in the temporary folder, or None if download failed.
    """
    tmp_dir = tempfile.mkdtemp()
    # Create a temporary folder if it doesn't exist
    if not os.path.exists(tmp_dir):
        os.makedirs(tmp_dir)
    output_template = os.path.join(tmp_dir, r"123.%(ext)s")

    try:
        if hasattr(cfg, 'YTB_PROXY') and cfg.YTB_PROXY:
            proxy = random.choice(cfg.YTB_PROXY)
            subprocess.run([
                'yt-dlp',
                '-f', 'bestaudio[abr<=128]/bestaudio',
                '--proxy', proxy,
                '-o', output_template,
                # '--noplaylist',
                # '--quiet',
                url
            ], check=True)
        else:
            subprocess.run([
                'yt-dlp',
                '-f', 'bestaudio[abr<=128]/bestaudio',
                '-o', output_template,
                url
            ], check=True)
    except subprocess.CalledProcessError:
        return None

    # Find the downloaded file in the folder
    files = [f for f in os.listdir(tmp_dir) if os.path.isfile(os.path.join(tmp_dir, f))]
    if files:
        return os.path.join(tmp_dir, files[0])
    else:
        return None  # File not found


def remove_folder_or_parent(path: str) -> None:
    """
    Removes a folder with all its contents or the parent folder of a file.

    Args:
        path: Path to the folder or file.
    """
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
    except Exception as error:
        my_log.log2(f'my_ytb:remove_folder_or_parent: {error}\n\n{path}')
    try:
        if os.path.isfile(path):
            shutil.rmtree(os.path.dirname(path))
    except Exception as error2:
        my_log.log2(f'my_ytb:remove_folder_or_parent: {error2}\n\n{path}')


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

