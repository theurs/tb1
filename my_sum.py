#!/usr/bin/env python3
#pip install lxml[html_clean]
# pip install webvtt-py

import cachetools.func
import concurrent.futures
import io
import glob
import os
import random
import re
import subprocess
import traceback
from urllib.parse import urlparse
from youtube_transcript_api import YouTubeTranscriptApi

import chardet
# import magic
import PyPDF2
import requests
import trafilatura
import webvtt

import cfg
import my_cohere
import my_gemini
import my_db
import my_log
import my_groq
import my_playwright
import my_stt
import my_transcribe
import utils


def extract_vk_video_id(url: str) -> str:
    """
    Извлекает идентификатор видео (video-ID_OWNER_ID) из URL VK и создает новый URL.

    Args:
        url (str): Входящий URL VK.

    Returns:
        str: Новый URL в формате https://vkvideo.ru/video-ID_OWNER_ID
             или пустая строка, если идентификатор не найден.
    """
    try:
        parsed_url = urlparse(url)
        # Проверяем части пути URL
        path_segments = parsed_url.path.split('/')

        video_segment = None
        for segment in path_segments:
            if segment.startswith('video-'):
                video_segment = segment
                break # Нашли нужный сегмент, можно выйти из цикла

        if video_segment:
            # Собираем новый URL с базовым доменом vkvideo.ru
            new_url = f"https://vkvideo.ru/{video_segment}"
            return new_url
        else:
            # Идентификатор не найден в пути
            return ""

    except Exception as e:
        # Обработка ошибок парсинга или других
        print(f"Ошибка при обработке URL {url}: {e}")
        return ""


@cachetools.func.ttl_cache(maxsize=10, ttl=10 * 60)
def get_subs_from_vk(url: str, proxy: bool = False) -> str:
    '''
    Downloads subtitles from vk video url using yt-dlp, extracts text, and returns it.

    Args:
        url (str): The URL of the video.
        proxy (bool): Whether to use a proxy (requires utils.get_ytb_proxy implemented).

    Returns:
        str: The text of the subtitles, or an empty string if no subtitles are found or an error occurs.
    '''

    # rebuild url, find section like video-220754053_456243093 from https://vkvideo.ru/playlist/-220754053_3/video-220754053_456243093?isLinkedPlaylist=1
    url = extract_vk_video_id(url)

    result = ''
    tmpname = None
    subtitle_path = None
    cleaned_text = '' # Variable to hold the final cleaned text

    try:
        # Use utils to get a temporary file base name
        tmpname = utils.get_tmp_fname()

        # yt-dlp command to download Russian VTT subtitles.
        # We download VTT or SRT, find the file, then parse.
        # Using -o "basename" causes yt-dlp to name the file "basename.<lang>.<ext>"
        cmd = [
            'yt-dlp',
            '--skip-download',
            '--write-subs',
            '--sub-langs', 'ru',
            '-o', f'{tmpname}', # yt-dlp will add .ru.vtt or .ru.srt etc.
            f'{url}'
        ]

        if proxy:
            # Assuming utils.get_ytb_proxy() returns the full proxy argument string like '--proxy http://...'
            proxy_arg = utils.get_ytb_proxy(url)
            if proxy_arg:
                 # Insert the proxy argument before the URL for clean separation
                 # Find where the URL is in the list and insert before it
                 try:
                     url_index = cmd.index(f'{url}')
                     cmd.insert(url_index, proxy_arg)
                 except ValueError:
                      # Should not happen if url is in cmd, but good practice
                      my_log.log2(f"get_subs_from_vk: URL {url} not found in initial command list.")

        # my_log.log2(f"get_subs_from_vk: Running command: {' '.join(cmd)}") # Дебаг команды

        # Execute the command
        # Using stderr=subprocess.PIPE to capture errors without printing directly
        # Added timeout to prevent hanging
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            stdout, stderr = process.communicate(timeout=60) # 1 minute timeout
        except subprocess.TimeoutExpired:
             process.kill()
             stdout, stderr = process.communicate()
             raise subprocess.TimeoutExpired(process.args, 300) # Re-raise with info

        stdout_str = stdout.decode('utf-8', errors='replace')
        stderr_str = stderr.decode('utf-8', errors='replace')

        # my_log.log2(f"get_subs_from_vk: stdout:\n{stdout_str}") # Можно раскомментировать для дебага
        # my_log.log2(f"get_subs_from_vk: stderr:\n{stderr_str}") # Можно раскомментировать для дебага

        # Check command return code and stderr/stdout for signs of no subtitles
        # yt-dlp might return 0 even if no subs, but will print "No subtitles available"
        if process.returncode != 0:
             # Log specific error if yt-dlp failed
             my_log.log2(f"get_subs_from_vk: yt-dlp exited with error code {process.returncode} for {url}. Stderr: {stderr_str}")
             result = '' # Error occurred
             return result # Exit try block early
        elif "No subtitles available" in stdout_str or "No subtitles available" in stderr_str:
             my_log.log2(f"get_subs_from_vk: yt-dlp reported no subtitles for {url}.")
             result = '' # No subtitles found
             return result # Exit try block early

        # Look for the downloaded file(s) created by yt-dlp.
        # It will follow the pattern tmpname.<lang>.<ext> (e.g., /tmp/tmpXYZ.ru.vtt)
        # Search for both .vtt and .srt as VK might provide either.
        subtitle_files = glob.glob(f"{tmpname}.*.vtt")
        if not subtitle_files:
             # If VTT not found, check for SRT
             subtitle_files = glob.glob(f"{tmpname}.*.srt")

        if not subtitle_files:
            # No subtitle files found matching the expected patterns
            # my_log.log2(f"get_subs_from_vk: No subtitle files found matching {tmpname}.*.vtt or {tmpname}.*.srt for {url}.")
            result = ''
            return result # Exit try block early

        # Assume the first found file is the correct one (usually there's only one for a language)
        subtitle_path = subtitle_files[0]
        # my_log.log2(f"get_subs_from_vk: Found subtitle file: {subtitle_path}") # Дебаг

        # Read the subtitle file content
        # Attempt reading with utf-8. Subtitles from web are usually utf-8.
        try:
            with open(subtitle_path, 'r', encoding='utf-8') as f:
                raw_subs_text = f.read()
        except Exception as file_read_error:
             my_log.log2(f"get_subs_from_vk: Error reading subtitle file {subtitle_path}: {file_read_error}")
             result = ''
             return result # Exit try block early

        # Process the raw subtitle text (either VTT or SRT)
        if subtitle_path.endswith('.vtt'):
            # my_log.log2("get_subs_from_vk: Parsing VTT subtitles.") # Дебаг
            # Use webvtt library for parsing VTT and extracting text
            try:
                cleaned_text = clear_text_subs_from_dzen_video(raw_subs_text)
            except Exception as parse_error:
                 my_log.log2(f"get_subs_from_vk: Error parsing VTT subtitles from {subtitle_path}: {parse_error}")
                 cleaned_text = '' # Ensure empty on parse error

        elif subtitle_path.endswith('.srt'):
             # my_log.log2("get_subs_from_vk: Parsing SRT subtitles.") # Дебаг
             # Custom parsing logic for SRT format to extract text blocks
             try:
                lines = raw_subs_text.strip().split('\n')
                text_blocks = []
                current_block_lines = []
                i = 0
                while i < len(lines):
                     line = lines[i].strip()
                     if not line: # Blank line separates blocks
                         if current_block_lines:
                             # Join lines within a block with a space (as they represent a single utterance)
                             block_text = ' '.join(current_block_lines).strip()
                             if block_text: # Add to blocks if not empty
                                 text_blocks.append(block_text)
                             current_block_lines = [] # Reset for next block
                         i += 1
                         continue

                     # Skip lines that look like SRT cue numbers or timecodes
                     if re.match(r'^\d+$', line): # e.g., '1', '2', ...
                          i += 1
                          continue
                     if '-->' in line: # e.g., '00:00:01,000 --> 00:00:03,000'
                          i += 1
                          continue

                     # If it's not a blank line, number, or timecode, it's part of the text block
                     current_block_lines.append(line)
                     i += 1

                # Handle the last block if the file doesn't end with a blank line
                if current_block_lines:
                    block_text = ' '.join(current_block_lines).strip()
                    if block_text:
                        text_blocks.append(block_text)

                # Now remove consecutive duplicate text blocks
                cleaned_blocks = []
                prev_block = None
                for block in text_blocks:
                     if block != prev_block:
                          cleaned_blocks.append(block)
                          prev_block = block

                # Join cleaned blocks with newline
                cleaned_text = '\n'.join(cleaned_blocks).strip()
             except Exception as parse_error:
                  my_log.log2(f"get_subs_from_vk: Error parsing SRT subtitles from {subtitle_path}: {parse_error}")
                  cleaned_text = '' # Ensure empty on parse error

        else:
             # This case should theoretically not be reached due to glob filtering
             my_log.log2(f"get_subs_from_vk: Found file with unexpected extension {subtitle_path} for {url}. Expected .vtt or .srt.")
             cleaned_text = '' # Unexpected file type

        # The final result is the cleaned text
        result = cleaned_text

        # my_log.log2(f"get_subs_from_vk: Successfully extracted and cleaned subtitles for {url}.") # Дебаг

    except subprocess.TimeoutExpired:
         my_log.log2(f"get_subs_from_vk: yt-dlp command timed out after 60 seconds for {url}")
         result = '' # Ensure empty string on timeout
    except FileNotFoundError:
         # This might happen if the 'yt-dlp' executable is not found in the system's PATH
         my_log.log2(f"get_subs_from_vk: yt-dlp command not found. Please ensure yt-dlp is installed and accessible in the system's PATH.")
         result = '' # Ensure empty string if command not found
    except Exception as error:
        # Catch any other unexpected errors during the process (e.g., issues with glob, utils, file operations not specifically handled)
        traceback_error = traceback.format_exc()
        my_log.log2(f'get_subs_from_vk: An unexpected error occurred processing {url}\n\n{error}\n\n{traceback_error}')
        result = '' # Ensure empty string on any error

    finally:
        # Clean up temporary file(s) created by yt-dlp starting with tmpname
        # glob might return the original tmpname if no files were created, handle that.
        if tmpname:
            # Find all files that start with the tmpname base
            files_to_remove = glob.glob(f"{tmpname}*")
            for f in files_to_remove:
                try:
                    if os.path.exists(f): # Check if the file actually exists before trying to remove
                        utils.remove_file(f) # Assuming utils.remove_file is safe and handles errors
                except Exception as cleanup_error:
                     # Log cleanup errors but don't re-raise as the main task is done or failed
                     my_log.log2(f"get_subs_from_vk: Error cleaning up file {f}: {cleanup_error}")

    return result


@cachetools.func.ttl_cache(maxsize=10, ttl=10 * 60)
def get_subs_from_rutube(url: str, proxy: bool = True) -> str:
    '''Downloads subtitles from rutube(any yt-dlp capable urls actually) video url, converts them to text and returns the text. 
    Returns None if no subtitles found.'''
    cache = my_db.get_from_sum(url+'.sub')
    if cache:
        return cache

    duration = my_transcribe.get_url_video_duration(url)
    my_log.log2(f'get_subs_from_rutube1: {url} Duration: {duration}')
    if duration == 0 or duration > 3*60*60:
        my_log.log2(f'get_subs_from_rutube2: too long video {url} {duration}')
        return ''

    tmpname = utils.get_tmp_fname()
    result = ''
    try:

        if proxy:
            cmd = f'yt-dlp -x -S "+size,+br" {utils.get_ytb_proxy(url)} "{url}" -o {tmpname}'
        else:
            cmd = f'yt-dlp -x -S "+size,+br" "{url}" -o {tmpname}'

        try:
            output = subprocess.check_output(cmd, shell=True, timeout=3000, stderr = subprocess.STDOUT)
        except subprocess.CalledProcessError as error:
            if not error.output:
                output = str(error).encode('utf-8', errors='replace')
            else:
                output = error.output

        output = output.decode('utf-8', errors='replace')

        search = tmpname+'*'
        new_tmp_fname = glob.glob(search)[0]
        if not os.path.isfile(new_tmp_fname):
            return ''
        result = my_stt.stt(new_tmp_fname)
        utils.remove_file(new_tmp_fname)
        result = result.strip()
        if result:
            my_db.set_sum_cache(url+'.sub', result)
        return result
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'get_subs_from_rutube3: {error} {url} {tmpname}\n\n{traceback_error}')
    finally:
        utils.remove_file(tmpname)
        if proxy and not result:
            result = get_subs_from_rutube(url, proxy = False)
        return result


@cachetools.func.ttl_cache(maxsize=10, ttl=10 * 60)
def get_subs_from_dzen_video(url: str, proxy: bool = True) -> str:
    '''Downloads subtitles from dzen video url, converts them to text and returns the text. 
    Returns None if no subtitles found.'''
    list_of_subs = []
    if proxy:
        cmd = f'yt-dlp -q --skip-download --list-subs  {utils.get_ytb_proxy()}  "{url}"'
    else:
        cmd = f'yt-dlp -q --skip-download --list-subs  "{url}"'
    try:
        output = subprocess.check_output(cmd, shell=True, timeout=300, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as error:
        if not error.output:
            output = str(error).encode('utf-8', errors='replace')
        else:
            output = error.output

    output = output.decode('utf-8', errors='replace')

    if output.startswith('ERROR'):
        if proxy:
            return get_subs_from_dzen_video(url, proxy = False)
        else:
            return ''

    for line in output.splitlines():
        line = line.strip()
        if line and not line.startswith('Language'):
            list_of_subs.append((line.split(' ', 1)[0], line.split(' ', 1)[1]))

    list_of_subs = [x for x in list_of_subs if 'WARNING' not in x[0]]

    if list_of_subs:
        tmpname = utils.get_tmp_fname()
        if proxy:
            cmd = f'yt-dlp -q --skip-download --write-subs --sub-lang "{list_of_subs[0][0]}"  {utils.get_ytb_proxy()}  "{url}" -o "{tmpname}"'
        else:
            cmd = f'yt-dlp -q --skip-download --write-subs --sub-lang "{list_of_subs[0][0]}"  "{url}" -o "{tmpname}"'
        subprocess.call(cmd, shell=True)
        ext = f'.{list_of_subs[0][0]}.{list_of_subs[0][1].split(",")[0]}'
        ext = ext.replace(' ', '')
        # check if file exists
        if not os.path.isfile(tmpname + ext):
            return get_subs_from_rutube(url)
        with open(tmpname + ext, 'r', encoding='utf-8') as f:
            text = f.read()
        utils.remove_file(tmpname + ext)
        return clear_text_subs_from_dzen_video(text)
    else:
        if proxy:
            return get_subs_from_dzen_video(url, proxy = False)
        else:
            return get_subs_from_rutube(url)


def clear_text_subs_from_dzen_video(text: str) -> str:
    """Removes time codes, empty lines and duplicate lines from dzen video subtitles.

    Args:
        text: The input string containing the subtitles in WebVTT format.

    Returns:
        A string containing the cleaned subtitles text.
    """
    # Parse the WebVTT subtitles using the webvtt library.
    captions = webvtt.from_buffer(io.StringIO(text))

    # Extract the text from each caption and join them with newline characters.
    t = ''.join(caption.text.strip() + '\n' for caption in captions)

    # Split the text into lines and remove leading/trailing whitespace from each line.
    lines = [x.strip() for x in t.strip().split('\n')]

    # Initialize an empty string to store the result and a variable to store the previous line.
    result = ''
    prev = ''

    # Iterate over the lines and remove consecutive duplicate lines.
    for line in lines:
        if line != prev:  # Only add the line if it's not the same as the previous one
            result += line + '\n'
            prev = line

    return result.strip()

    # lines = text.splitlines()[1:]
    # result = []
    # for i in range(len(lines)):
    #     if "-->" not in lines[i] and lines[i] != '':
    #         result.append(lines[i])
    # return '\n'.join(result).strip()


@cachetools.func.ttl_cache(maxsize=10, ttl=10 * 60)
def get_text_from_youtube(url: str, transcribe: bool = True, language: str = '') -> str:
    """Вытаскивает текст из субтитров на ютубе

    Args:
        url (str): ссылка на ютуб видео
        transcribe (bool, optional): если True то создаем субтитры с помощью джемини если их нет.

    Returns:
        str: первые субтитры из списка какие есть в видео
    """
    try:
        top_langs = (
            'ru', 'en', 'uk', 'es', 'pt', 'fr', 'ar', 'id', 'it', 'de', 'ja', 'ko', 'pl', 'th', 'tr', 'nl', 'hi', 'vi', 'sv', 'ro',
            'aa', 'ab', 'af', 'ak', 'am', 'an', 'as', 'av', 'ae', 'ay', 'az', 'ba', 'bm', 'be', 'bn', 'bi', 'bo', 'bs', 'br', 'bg',
            'ca', 'cs', 'ch', 'ce', 'cu', 'cv', 'kw', 'co', 'cr', 'cy', 'da', 'dv', 'dz', 'el', 'eo', 'et', 'eu', 'ee', 'fo', 'fa',
            'fj', 'fi', 'fy', 'ff', 'gd', 'ga', 'gl', 'gv', 'gn', 'gu', 'ht', 'ha', 'he', 'hz', 'ho', 'hr', 'hu', 'hy', 'ig', 'io',
            'ii', 'iu', 'ie', 'ia', 'ik', 'is', 'jv', 'kl', 'kn', 'ks', 'ka', 'kr', 'kk', 'km', 'ki', 'rw', 'ky', 'kv', 'kg', 'kj',
            'ku', 'lo', 'la', 'lv', 'li', 'ln', 'lt', 'lb', 'lu', 'lg', 'mh', 'ml', 'mr', 'mk', 'mg', 'mt', 'mn', 'mi', 'ms', 'my',
            'na', 'nv', 'nr', 'nd', 'ng', 'ne', 'nn', 'nb', 'no', 'ny', 'oc', 'oj', 'or', 'om', 'os', 'pa', 'pi', 'ps', 'qu', 'rm',
            'rn', 'sg', 'sa', 'si', 'sk', 'sl', 'se', 'sm', 'sn', 'sd', 'so', 'st', 'sq', 'sc', 'sr', 'ss', 'su', 'sw', 'ty', 'ta',
            'tt', 'te', 'tg', 'tl', 'ti', 'to', 'tn', 'ts', 'tk', 'tw', 'ug', 'ur', 'uz', 've', 'vo', 'wa', 'wo', 'xh', 'yi', 'yo',
            'za', 'zh', 'zu', 'bh'
        )
        if language:
            top_langs = [x for x in top_langs if x != language]
            top_langs.insert(0, language)

        if '//dzen.ru/video/watch/' in url or ('vk.com' in url and '/video-' in url):
            return get_subs_from_dzen_video(url)
        if '//rutube.ru/video/' in url:
            return get_subs_from_rutube(url)
        if 'pornhub.com/view_video.php?viewkey=' in url:
            return get_subs_from_rutube(url)
        if 'tiktok.com' in url and 'video' in url:
            return get_subs_from_rutube(url)
        if 'vk.com' in url and '/video-' in url or 'vkvideo.ru' in url:
            return get_subs_from_vk(url)
        if '//my.mail.ru/v/' in url and '/video/' in url:
            return get_subs_from_rutube(url)
        if 'https://vimeo.com/' in url:
            return get_subs_from_dzen_video(url)

        try:
            video_id = re.search(r"(?:v=|\/)([a-zA-Z0-9_-]{11})(?:\?|&|\/|$)", url).group(1)
        except:
            return ''

        for _ in range(4):
            try:
                t = ''
                try:
                    proxy = ''
                    if hasattr(cfg, 'YTB_PROXY') and cfg.YTB_PROXY:
                        proxy = random.choice(cfg.YTB_PROXY)
                        proxies = {
                            'http': proxy,
                            'https': proxy
                        }
                        t = YouTubeTranscriptApi.get_transcript(video_id, languages=top_langs, proxies = proxies)
                    else:
                        t = YouTubeTranscriptApi.get_transcript(video_id, languages=top_langs)
                except Exception as download_error:
                    my_log.log2(f'get_text_from_youtube:1: {download_error}\n\nProxy: {proxy}\nURL: {url}')
                if t:
                    break
            except Exception as error:
                if 'If you are sure that the described cause is not responsible for this error and that a transcript should be retrievable, please create an issue at' not in str(error):
                    my_log.log2(f'get_text_from_youtube:2: {error}')
                # my_log.log2(f'get_text_from_youtube:3: {error}')
                # print(error)
                t = ''

        text = '\n'.join([x['text'] for x in t])

        text = text.strip()

        if not text and transcribe: # нет субтитров?
            text, info = my_transcribe.download_youtube_clip_v2(url, language=language)

        return text
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'get_text_from_youtube::4: {url} {transcribe} {language}\n\n{error}\n\n{traceback_error}')
        return ''


def check_ytb_subs_exists(url: str) -> bool:
    '''проверяет наличие субтитров на ютубе, если это не ютуб или есть субтитры
    то возвращает True, иначе False
    '''
    if '/youtu.be/' in url or 'youtube.com/' in url or '//dzen.ru/video/watch/' in url or \
                '//rutube.ru/video/' in url or 'pornhub.com/view_video.php?viewkey=' in url or \
                ('tiktok.com' in url and 'video' in url) or \
                ('https://vimeo.com/' in url) or \
                ('vk.com' in url and '/video-' in url) or \
                ('//my.mail.ru/v/' in url and '/video/' in url):
        return len(get_text_from_youtube(url, transcribe=False)) > 0
    return False
    

def summ_text_worker(text: str, subj: str = 'text', lang: str = 'ru', query: str = '', role: str = '') -> str:
    """параллельный воркер для summ_text
       subj == 'text' or 'pdf'  - обычный текст о котором ничего не известно
       subj == 'chat_log'       - журнал чата
       subj == 'youtube_video'  - субтитры к видео на ютубе
    """

    # если запустили из pool.map и передали параметры как список
    if isinstance(text, tuple):
        text, subj, _ = text[0], text[1], text[2]

    if type(text) != str or len(text) < 100:
        return ''

    result = ''

    if subj == 'youtube_video':
        if len(text) > 2000:
            qq = f'''Summarize this YouTube video based on the subtitles.

Start the output immediately with the brief summary.
Output:
Output language: [{lang}]
Highlight the key points.
Do not use any code blocks in the output text.
Do not use tools.

Brief summary (2 sentences).
Format it as quotes with > symbol.
First block only text of the block, do not include words like Brief summary (2 sentences).

Detailed summary (50-1000[hard limit] words).
Format it as text, no quotes with > symbol.
Second block only text of the block, do not include words like Detailed summary (50-1000 words).

Subtitles:
'''
        else:
            qq = f'''Summarize this YouTube video based on the subtitles.

Start the output immediately with the brief summary.
Output:
Output language: [{lang}]
Highlight the key points.
Do not use any code blocks in the output text.
Do not use tools.

The brief summary only (up to 5 sentences).
First block only text of the block, do not include words like Brief summary (up to 5 sentences).

Subtitles:
'''
    else:
        if len(text) > 2000:
            qq = f'''Summarize this text.

Start the output immediately with the brief summary.
Output:
Output language: [{lang}]
Highlight the key points.
Do not use any code blocks in the output text.
Do not use tools.

Brief summary (2 sentences).
Format it as quotes with > symbol.
First block only text of the block, do not include words like Brief summary (2 sentences).

Detailed summary (50-1000[hard limit] words). Include short human-readable links if applicable.
Format it as text, no quotes with > symbol.
Second block only text of the block, do not include words like Detailed summary (50-1000 words).

Text:
'''
        else:
            qq = f'''Summarize this text.

Start the output immediately with the brief summary.
Output:
Output language: [{lang}]
Highlight the key points.
Do not use any code blocks in the output text.
Do not use tools.

The brief summary only (up to 5 sentences). Include short human-readable links if applicable.
First block only text of the block, do not include words like Brief summary (up to 5 sentences).

Text:
'''

    if not result:
        try:
            if query:
                qq = query
            r = my_gemini.sum_big_text(text[:my_gemini.MAX_SUM_REQUEST], qq, role=role)
            if r:
                result = f'{r}\n\n--\nGemini Flash [{len(text[:my_gemini.MAX_SUM_REQUEST])}]'
        except Exception as error:
            print(f'my_sum:summ_text_worker:gemini: {error}')
            my_log.log2(f'my_sum:summ_text_worker:gemini: {error}')

    if not result:
        try:
            if query:
                qq = query
            r = my_cohere.sum_big_text(text[:my_cohere.MAX_SUM_REQUEST], qq, role=role)
            if r:
                result = f'{r}\n\n--\nCommand R+ [{len(text[:my_cohere.MAX_SUM_REQUEST])}]'
        except Exception as error:
            print(f'my_sum:summ_text_worker:cohere: {error}')
            my_log.log2(f'my_sum:summ_text_worker:cohere: {error}')

    if not result:
        try:
            if query:
                qq = query
            r = my_groq.sum_big_text(text[:my_groq.MAX_SUM_REQUEST], qq, role=role)
            if r != '':
                result = f'{r}\n\n--\nLlama 3.2 90b [Groq] [{len(text[:my_groq.MAX_SUM_REQUEST])}]'
        except Exception as error:
            print(f'my_sum:summ_text_worker:llama: {error}')
            my_log.log2(f'my_sum:summ_text_worker:llama: {error}')

    return result


def summ_text(text: str, subj: str = 'text', lang: str = 'ru', query: str = '', role: str = '') -> str:
    """сумморизирует текст с помощью бинга или гптчата или клод-100к, возвращает краткое содержание, только первые 30(60)(99)т символов
    subj - смотрите summ_text_worker()
    """
    return summ_text_worker(text, subj, lang, query, role)


def download_text(urls: list, max_req: int = cfg.max_request, no_links = False) -> str:
    """
    Downloads text from a list of URLs and returns the concatenated result.
    
    Args:
        urls (list): A list of URLs from which to download text.
        max_req (int, optional): The maximum length of the result string. Defaults to cfg.max_request.
        no_links(bool, optional): Include links in the result. Defaults to False.
        
    Returns:
        str: The concatenated text downloaded from the URLs.
    """
    #max_req += 5000 # 5000 дополнительно под длинные ссылки с запасом
    result = ''
    for url in urls:
        text = summ_url(url, download_only = True).strip()
        if text:
            if len(text) < 300:
                if 'java' in text.lower() or 'browser' in text.lower() or 'джава' in text.lower() or 'браузер' in text.lower() or not text:
                    my_log.log_playwright(f'trying download text with playwright {url}\n\n{text}')
                    text = my_playwright.gettext(url, 30) or text
            if no_links:
                result += f'\n\n{text}\n\n'
            else:
                result += f'\n\n|||{url}|||\n\n{text}\n\n'
            if len(result) > max_req:
                break
    return result


def download_text_v2(url: str, max_req: int = cfg.max_request, no_links = False) -> str:
    return download_text([url,], max_req, no_links)


def download_in_parallel(urls, max_sum_request):
    text = ''
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        future_to_url = {executor.submit(download_text_v2, url, 30000): url for url in urls}
        for future in concurrent.futures.as_completed(future_to_url):
            try:
                result = future.result()
                text += result
                if len(text) > max_sum_request:
                    break
            except Exception as exc:
                error_traceback = traceback.format_exc()
                my_log.log2(f'my_google:download_in_parallel: {exc}\n\n{error_traceback}')
    return text


def get_urls_from_text(text):
    try:
        urls = re.findall(r'https?://\S+', text)
        return urls
    except:
        return []


@cachetools.func.ttl_cache(maxsize=10, ttl=10 * 60)
def summ_url(
    url:str,
    download_only: bool = False,
    lang: str = 'ru',
    deep: bool = False,
    role: str = ''
):
    """скачивает веб страницу, просит гптчат или бинг сделать краткое изложение текста, возвращает текст
    если в ссылке ютуб то скачивает субтитры к видео вместо текста
    может просто скачать текст без саммаризации, для другой обработки"""
    youtube = False
    pdf = False
    if '/youtu.be/' in url or 'youtube.com/' in url or '//dzen.ru/video/watch/' in url or \
       '//rutube.ru/video/' in url or 'pornhub.com/view_video.php?viewkey=' in url or \
       ('tiktok.com' in url and 'video' in url) or \
       ('vk.com' in url and '/video-' in url) or \
       ('vkvideo.ru' in url and '/video-' in url) or \
       ('https://vimeo.com/' in url) or \
       ('//my.mail.ru/v/' in url and '/video/' in url):
        text = get_text_from_youtube(url, language=lang)
        youtube = True
    elif url.lower().startswith('http') and url.lower().endswith(('.mp3', '.ogg', '.aac', '.m4a', '.flac')):
        text = my_transcribe.transcribe_audio_file_web(url)
    else:
        # Получаем содержимое страницы

        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}

        try:
            if url.lower().strip().startswith(('file://', 'localhost', '127.0.0.1', 'http://localhost', 'https://localhost', 'http://127.0.0.1', 'https://127.0.0.1')):
                if download_only:
                    return ''
                else:
                    return '', ''
            response = requests.get(url, stream=True, headers=headers, timeout=20, verify=False)
            content = b''
            # Ограничиваем размер
            for chunk in response.iter_content(chunk_size=1024):
                content += chunk
                if len(content) > 1 * 1024 * 1024: # 1 MB
                    break
        except Exception as e:
            my_log.log2(f'my_sum.summ_url:download: {e}')
            if download_only:
                return ''
            else:
                return '', ''

        if utils.mime_from_buffer(content) == 'application/pdf':
            pdf = True
            file_bytes = io.BytesIO(content)
            pdf_reader = PyPDF2.PdfReader(file_bytes)
            text = ''
            for page in pdf_reader.pages:
                text += page.extract_text()
        else:
            # Определяем кодировку текста
            encoding = chardet.detect(content[:2000])['encoding']
            # Декодируем содержимое страницы
            try:
                content = content.decode(encoding)
            except:
                try:
                    content = content.decode('utf-8')
                except:
                    if download_only:
                        return ''
                    else:
                        return '', ''

            text = trafilatura.extract(content,
                                       deduplicate=True,
                                       include_comments=True,
                                       include_links=True,
                                       include_images=True,
                                       include_formatting=True,
                                       include_tables=True,
                                    #    output_format='markdown'
                                       )

            # качаем браузером по умолчанию, если он не справился то откатываемся к обычным реквестам
            text = my_playwright.gettext(url, 30) or text

            # if not text:
            #     text = ''
            # if len(text) < 500:
            #     if 'java' in text.lower() or 'browser' in text.lower() or 'джава' in text.lower() or 'браузер' in text.lower() or not text:
            #         my_log.log_playwright(f'trying download text with playwright (2) {url}\n\n{text}')
            #         text = my_playwright.gettext(url, 30) or text


    if download_only:
        if youtube:
            r = f'URL: {url}\nСубтитры из видео на ютубе (полное содержание, отметки времени были удалены):\n\n{text}'
        else:
            r = f'URL: {url}\nРаспознанное содержание веб страницы:\n\n{text}'
        return r
    else:
        if youtube:
            r = summ_text(text, 'youtube_video', lang, role=role)
        elif pdf:
            r = summ_text(text, 'pdf', lang, role=role)
        else:
            if deep:
                text += '\n\n==============\nDownloaded links from the text for better analysis\n==============\n\n' + download_in_parallel(get_urls_from_text(text), my_gemini.MAX_SUM_REQUEST)
                r = summ_text(text, 'text', lang, role=role)
            else:
                r = summ_text(text, 'text', lang, role=role)
        return r, text


def is_valid_url(url: str) -> bool:
    """Функция is_valid_url() принимает строку url и возвращает True, если эта строка является веб-ссылкой,
    и False в противном случае."""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False


if __name__ == "__main__":
    pass
    # my_groq.load_users_keys()
    # r = get_subs_from_dzen_video('https://www.youtube.com/watch?v=lyGvQn_clQM')
    # r = get_text_from_youtube('https://www.youtube.com/watch?v=qnvNkXs7NpY', transcribe=False)
    # r = get_subs_from_rutube('https://vimeo.com/216790976')
    r = get_subs_from_dzen_video('https://vimeo.com/33830000')

    # r = get_subs_from_vk('https://vkvideo.ru/video-9695053_456241024')
    # r = get_subs_from_vk('https://vkvideo.ru/playlist/-220754053_3/video-220754053_456243093?isLinkedPlaylist=1')

    print(r)
