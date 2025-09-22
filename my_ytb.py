#!/usr/bin/env python3


import cachetools.func
import json
import natsort
import os
import random
import subprocess
import shutil
import tempfile
from typing import List, Tuple

import my_log
import utils
import cfg


download_audio = utils.download_audio
valid_youtube_url = utils.valid_youtube_url
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

        # Расчет segment_time на основе max_size_mb и битрейта 24 кбит/с
        target_bitrate_bps = 32 * 1000  # 24(up to 32) kbps в бит/с
        max_size_bits = max_size_mb * 1024 * 1024 * 8 # max_size_mb в битах
        calculated_segment_time_seconds = max_size_bits / target_bitrate_bps

        # ffmpeg предпочитает целые числа или числа с плавающей точкой
        segment_time = calculated_segment_time_seconds 

        subprocess.run([
            'ffmpeg',
            '-i',
            input_file,
            '-f',
            'segment',
            '-segment_time',
            str(segment_time),
            '-acodec',
            'libopus',  # Изменено на libopus
            '-b:a',     # Устанавливаем постоянный битрейт
            '24k',      # 24 кбит/с
            '-reset_timestamps',
            '1',
            '-loglevel',
            'quiet',
            f'{output_prefix}%03d.opus' # Изменено расширение файла на .opus
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


@cachetools.func.ttl_cache(maxsize=10, ttl=10 * 60)
def get_title_and_poster(url: str) -> Tuple[str, str, str, int]:
    """
    Gets the title, thumbnail URL, description, and duration of a video using yt-dlp.
    Retries with different proxies if available.
    """
    try:
        command = ['yt-dlp', '--dump-json', url]
        process = utils.run_ytbdlp_with_retries(command)

        video_info = json.loads(process.stdout)
        title = video_info.get('title', '')
        thumbnail_url = video_info.get('thumbnail', '')
        description = video_info.get('description', '')
        duration = video_info.get('duration', 0)
        return title, thumbnail_url, description, duration
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError) as error:
        my_log.log2(f'my_ytb:get_title_and_poster: Failed for {url}. Error: {error}')
        return '', '', '', 0


def process_audio_filters(input_file: str, speed: str, volume: str) -> str:
    """
    Applies speed and volume filters to an audio file using ffmpeg.

    Args:
        input_file: Path to the input audio file.
        speed: Speed multiplier ('1.0', '1.5', '2.0').
        volume: Volume multiplier ('1.0', '2.0', '4.0').

    Returns:
        Path to the processed audio file, or the original path if no changes were needed.
    """
    speed_f = float(speed)
    volume_f = float(volume)

    # Skip processing if no changes are needed
    if speed_f == 1.0 and volume_f == 1.0:
        return input_file

    with LOCK_TRANSCODE:
        output_file = utils.get_tmp_fname(ext='.opus')

        # Build the audio filter chain for ffmpeg
        afilters = []
        if speed_f != 1.0:
            # FFmpeg's atempo filter is limited to the range [0.5, 100.0].
            # To achieve speeds > 2.0, we chain multiple atempo filters.
            temp_speed = speed_f
            while temp_speed > 2.0:
                afilters.append("atempo=2.0")
                temp_speed /= 2.0
            if temp_speed > 0.5:  # Add the remaining speed factor
                afilters.append(f"atempo={temp_speed}")

        if volume_f != 1.0:
            afilters.append(f"volume={volume_f}")

        if not afilters:
            return input_file

        af_chain = ",".join(afilters)

        try:
            subprocess.run([
                'ffmpeg',
                '-i', input_file,
                '-af', af_chain,
                '-c:a', 'libopus',
                '-b:a', '32k',
                '-loglevel', 'quiet',
                output_file
            ], check=True)

            # Clean up the original file if it's a temporary one
            if input_file.startswith(tempfile.gettempdir()):
                utils.remove_file(input_file)

            return output_file
        except subprocess.CalledProcessError as e:
            my_log.log2(f'my_ytb:process_audio_filters: ffmpeg error: {e}')
            return input_file  # Return original on failure


def download_audio(url: str, quality: str = 'voice', lang: str = 'en', limit_duration: int = 4 * 60 * 60) -> str | None:
    """
    Downloads the best audio track matching the user's language using yt-dlp.
    Falls back to the best overall audio if the specified language is not found.
    """
    if '.yandex.ru' in url or 'drive.google.com' in url:
        return utils.download_yandex_disk_audio(url)

    try:
        # Step 1: Get video metadata as JSON
        info_command = ['yt-dlp', '--dump-json', url]
        info_process = utils.run_ytbdlp_with_retries(info_command)
        video_info = json.loads(info_process.stdout)

        duration = video_info.get('duration', 0)
        if not duration or duration > limit_duration:
            my_log.log2(f"my_ytb:download_audio: Video duration ({duration}s) out of limits for {url}.")
            return None

        # Step 2: Select the best audio format
        formats = video_info.get('formats', [])
        audio_formats = [f for f in formats if f.get('vcodec') == 'none' and f.get('acodec') != 'none']

        # Find formats matching the user's language
        lang_formats = [f for f in audio_formats if f.get('language') == lang]

        best_format = None
        # A robust key function to get bitrate, falling back from 'abr' to 'tbr' and then to 0.
        get_bitrate = lambda f: (f.get('abr') or f.get('tbr') or 0)

        if lang_formats:
            # If language-specific tracks exist, find the one with the highest bitrate
            best_format = max(lang_formats, key=get_bitrate)
            # my_log.log2(f"my_ytb:download_audio: Found best audio for lang '{lang}': format_id {best_format.get('format_id')}")
        elif audio_formats:
            # Fallback: no tracks in user's language, get the overall best audio
            best_format = max(audio_formats, key=get_bitrate)
            my_log.log2(f"my_ytb:download_audio: No audio for lang '{lang}'. Falling back to best overall: format_id {best_format.get('format_id')}")

        if best_format:
            format_id = best_format.get('format_id')
        else:
            # Last resort fallback to the old method if no audio-only streams are found
            format_id = 'bestaudio[abr<=64]/bestaudio' if quality == 'voice' else 'bestaudio/best'
            my_log.log2(f"my_ytb:download_audio: No specific audio streams found. Using default selector: '{format_id}'")

        # Step 3: Download using the selected format_id
        output_template = f"{utils.get_tmp_fname()}.%(ext)s"
        download_command = [
            'yt-dlp',
            '-f', format_id,
            '-o', output_template,
            '--extract-audio',
            url
        ]

        utils.run_ytbdlp_with_retries(download_command)

        # Find the actual downloaded file since extension is dynamic
        base_name = os.path.splitext(output_template)[0]
        temp_dir = os.path.dirname(base_name)
        for f in os.listdir(temp_dir):
            if f.startswith(os.path.basename(base_name)):
                return os.path.join(temp_dir, f)

        my_log.log2(f"my_ytb:download_audio: File not found after successful download for {url}.")
        return None

    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError) as e:
        my_log.log2(f"my_ytb:download_audio: All download attempts failed for URL '{url}'. Error: {e}")
        return None
    except Exception as e:
        my_log.log2(f"my_ytb:download_audio: An unexpected error occurred for URL '{url}': {e}")
        return None


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

    # print(split_audio(r'C:\Users\user\Downloads\Музыка\Music for Work — Programming, Hacking, Coding — Chillstep & Future Garage Mix [sfrF7zjOK1E].m4a', 45))

    print(download_yandex_disk_audio('https://disk.yandex.ru/d/M72KCnoXfI7E-Q'))
