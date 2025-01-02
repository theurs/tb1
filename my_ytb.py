#!/usr/bin/env python3
# pip install pytube


import natsort
import os
import subprocess
import shutil
import tempfile
from typing import List, Tuple

import natsort.natsort
import pytube

import my_log
import utils


def download_ogg(url: str) -> str:
    '''Downloads audio from a youtube URL, saves it to a temporary file in OGG format, and returns the path to the OGG file.'''
    tmp_file = utils.get_tmp_fname()
    # if yt_cookies.txt file exists, use it
    if os.path.exists('yt_cookies.txt'):
        subprocess.run(['yt-dlp', '--cookies', 'yt_cookies.txt', '-x', '--audio-format', 'vorbis', '-o', tmp_file, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.run(['yt-dlp', '-x', '--audio-format', 'vorbis', '-o', tmp_file, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return tmp_file + '.ogg'


def valid_youtube_url(url: str) -> str:
    '''Checks if the URL is a valid YouTube URL (all variants are supported). 
       Returns the video ID or an empty string if the URL is invalid.'''
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
    '''Gets the title of the YouTube video from the given URL.
       Returns the title or an empty string if an error occurs.'''
    try:
        yt = pytube.YouTube(url)
        return yt.title
    except Exception as error:
        return ''


def get_title_and_poster(url: str) -> Tuple[str, str, str, int]:
    """Gets the title, thumbnail URL, description and size of a YouTube video.

    Args:
        url: The URL of the YouTube video.

    Returns:
        A tuple containing the title, thumbnail URL, and description of the video. 
        If an error occurs, returns a tuple of three empty strings.
    """
    try:
        yt = pytube.YouTube(url)
        title = yt.title
        pic = yt.thumbnail_url
        description = yt.description
        size = yt.length

        return title or '', pic, description or '', size
    except Exception as error:
        my_log.log2(f'my_ytb:get_title_and_poster {url} {error}')
        return '', '', '', 0


def split_audio(input_file: str, max_size_mb: int) -> List[str]:
    """
    Splits audio file into parts no larger than the specified size using ffmpeg.

    Args:
        input_file: Path to the input audio file.
        max_size_mb: Maximum part size in megabytes.

    Returns:
        A list of paths to files in a temporary folder.
    """

    # Create a temporary folder
    tmp_dir = tempfile.mkdtemp()

    # Create a temporary folder if it doesn't exist
    if not os.path.exists(tmp_dir):
        os.makedirs(tmp_dir)

    output_prefix = os.path.join(tmp_dir, "part")

    bit_rate = 64000

    # Calculate the segment time in seconds
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
        'libvorbis',
        '-ab',
        '64k',
        '-reset_timestamps',
        '1',
        '-loglevel',
        'quiet',
        f'{output_prefix}%03d.ogg'
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
        if os.path.exists('yt_cookies.txt'):
            subprocess.run([
                'yt-dlp',
                '--cookies',
                'yt_cookies.txt',
                '-f', 'bestaudio[abr<=128]/bestaudio',
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
                # '--noplaylist',
                # '--quiet',
                url
            ], check=True)
    except  subprocess.CalledProcessError:
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

    # input = download_audio('https://www.youtube.com/watch?v=DYhs2rv7pT8')
    # print(input)

    # print(get_title_and_poster('https://www.youtube.com/watch?v=jfKfPfyJRdk'))

