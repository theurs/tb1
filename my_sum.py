#!/usr/bin/env python3
#pip install lxml[html_clean]

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

import cfg
import my_db
import my_log
import my_gemini
import my_groq
import my_stt
import my_transcribe
import utils


@cachetools.func.ttl_cache(maxsize=10, ttl=10 * 60)
def get_subs_from_rutube(url: str) -> str:
    '''Downloads subtitles from rutube(any yt-dlp capable urls actually) video url, converts them to text and returns the text. 
    Returns None if no subtitles found.'''
    cache = my_db.get_from_sum(url+'.sub')
    if cache:
        return cache

    duration = my_transcribe.get_url_video_duration(url)
    my_log.log2(f'my_sum:get_subs_from_rutube: {url} Duration: {duration}')
    if duration == 0 or duration > 1*60*60:
        my_log.log2(f'my_sum:get_subs_from_rutube: too long video {url} {duration}')
        return ''

    tmpname = utils.get_tmp_fname()
    result = ''
    try:
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
        my_log.log2(f'get_subs_from_rutube: {error} {url} {tmpname}')
    finally:
        utils.remove_file(tmpname)
        return result


@cachetools.func.ttl_cache(maxsize=10, ttl=10 * 60)
def get_subs_from_dzen_video(url: str) -> str:
    '''Downloads subtitles from dzen video url, converts them to text and returns the text. 
    Returns None if no subtitles found.'''
    list_of_subs = []
    cmd = f'yt-dlp -q --skip-download --list-subs "{url}"'
    try:
        output = subprocess.check_output(cmd, shell=True, timeout=300, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as error:
        if not error.output:
            output = str(error).encode('utf-8', errors='replace')
        else:
            output = error.output

    output = output.decode('utf-8', errors='replace')

    for line in output.splitlines():
        line = line.strip()
        if line and not line.startswith('Language'):
            list_of_subs.append((line.split(' ', 1)[0], line.split(' ', 1)[1]))

    if list_of_subs:
        tmpname = utils.get_tmp_fname()
        cmd = f'yt-dlp -q --skip-download --write-subs --sub-lang "{list_of_subs[0][0]}" "{url}" -o "{tmpname}"'
        subprocess.call(cmd, shell=True)
        ext = f'.{list_of_subs[0][0]}.{list_of_subs[0][1].split(",")[0]}'
        # check if file exists
        if not os.path.isfile(tmpname + ext):
            return get_subs_from_rutube(url)
        with open(tmpname + ext, 'r', encoding='utf-8') as f:
            text = f.read()
        utils.remove_file(tmpname + ext)
        return clear_text_subs_from_dzen_video(text)
    else:
        return get_subs_from_rutube(url)


def clear_text_subs_from_dzen_video(text: str) -> str:
    """Removes time codes and empty lines from subtitles text, returns clear text."""
    lines = text.splitlines()[1:]
    result = []
    for i in range(len(lines)):
        if "-->" not in lines[i] and lines[i] != '':
            result.append(lines[i])
    return '\n'.join(result).strip()


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
        top_langs = ('ru', 'en', 'uk', 'es', 'pt', 'fr', 'ar', 'id', 'it', 'de', 'ja', 'ko', 'pl', 'th', 'tr', 'nl', 'hi', 'vi', 'sv', 'ro')
        if language:
            top_langs = [x for x in top_langs if x != language]
            top_langs.insert(0, language)

        if '//dzen.ru/video/watch/' in url:
            return get_subs_from_dzen_video(url)
        if '//rutube.ru/video/' in url:
            return get_subs_from_rutube(url)
        if 'pornhub.com/view_video.php?viewkey=' in url:
            return get_subs_from_rutube(url)
        if 'tiktok.com' in url and 'video' in url:
            return get_subs_from_rutube(url)
        if 'vk.com' in url and '/video-' in url:
            return get_subs_from_rutube(url)
        if '//my.mail.ru/v/' in url and '/video/' in url:
            return get_subs_from_rutube(url)

        try:
            video_id = re.search(r"(?:v=|\/)([a-zA-Z0-9_-]{11})(?:\?|&|\/|$)", url).group(1)
        except:
            return ''

        for _ in range(4):
            try:
                t = ''
                try:
                    proxy = ''
                    if hasattr(cfg, 'YT_SUBS_PROXY'):
                        proxy = random.choice(cfg.YT_SUBS_PROXY)
                        t = YouTubeTranscriptApi.get_transcript(video_id, languages=top_langs, proxies = {'https': proxy})
                    else:
                        t = YouTubeTranscriptApi.get_transcript(video_id, languages=top_langs)
                except Exception as download_error:
                    my_log.log2(f'get_text_from_youtube: {download_error}\n\nProxy: {proxy}')
                if t:
                    break
            except Exception as error:
                if 'If you are sure that the described cause is not responsible for this error and that a transcript should be retrievable, please create an issue at' not in str(error):
                    my_log.log2(f'get_text_from_youtube: {error}')
                # my_log.log2(f'get_text_from_youtube: {error}')
                # print(error)
                t = ''

        text = '\n'.join([x['text'] for x in t])

        text = text.strip()

        if not text and transcribe: # нет субтитров?
            text, info = my_transcribe.download_youtube_clip_v2(url, language=language)

        return text
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'get_text_from_youtube: {url} {transcribe} {language}\n\n{error}\n\n{traceback_error}')
        return ''


def check_ytb_subs_exists(url: str) -> bool:
    '''проверяет наличие субтитров на ютубе, если это не ютуб или есть субтитры
    то возвращает True, иначе False
    '''
    if '/youtu.be/' in url or 'youtube.com/' in url or '//dzen.ru/video/watch/' in url:
        return len(get_text_from_youtube(url, transcribe=False)) > 0
    return False
    

def summ_text_worker(text: str, subj: str = 'text', lang: str = 'ru', query: str = '') -> str:
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
            qq = f'''Summarize the content of this YouTube video.

Answer in [{lang}] language.

The structure of the answer should be similar to the following:
Show a block with the brief summary of the video in 2 sentences, which satisfies most people.
Show a block with a detail summary of the content of the video in your own words, 50-2000 words.

Extracted subtitles:
'''
        else:
            qq = f'''Summarize the content of this YouTube video.

Answer in [{lang}] language.

The structure of the answer should be similar to the following:
Show a block with the brief summary of the video in 5 sentences, which satisfies most people.

Extracted subtitles:
'''
    else:
        if len(text) > 2000:
            qq = f'''Summarize the content of this text.

Answer in [{lang}] language.

The structure of the answer should be similar to the following:
Show a block with the brief summary of the text in 2 sentences, which satisfies most people.
Show a block with a detail summary of the content of the text in your own words, 50-2000 words.
Markdown for links is mandatory.

Text:
'''
        else:
            qq = f'''Summarize the content of this text.

Answer in [{lang}] language.

The structure of the answer should be similar to the following:
Show a block with the brief summary of the text in 5 sentences, which satisfies most people.
Markdown for links is mandatory.

Text:
'''

    if not result:
        try:
            if query:
                qq = query
            r = my_gemini.sum_big_text(text[:my_gemini.MAX_SUM_REQUEST], qq).strip()
            if r != '':
                result = f'{r}\n\n--\nGemini Flash [{len(text[:my_gemini.MAX_SUM_REQUEST])}]'
        except Exception as error:
            print(f'my_sum:summ_text_worker:gpt: {error}')
            my_log.log2(f'my_sum:summ_text_worker:gpt: {error}')

    if not result:
        try:
            if query:
                qq = query
            r = my_groq.sum_big_text(text[:my_groq.MAX_SUM_REQUEST], qq).strip()
            if r != '':
                result = f'{r}\n\n--Llama 3.1 70b [Groq] [{len(text[:my_groq.MAX_SUM_REQUEST])}]'
        except Exception as error:
            print(f'my_sum:summ_text_worker:gpt: {error}')
            my_log.log2(f'my_sum:summ_text_worker:gpt: {error}')

    return result


def summ_text(text: str, subj: str = 'text', lang: str = 'ru', query: str = '') -> str:
    """сумморизирует текст с помощью бинга или гптчата или клод-100к, возвращает краткое содержание, только первые 30(60)(99)т символов
    subj - смотрите summ_text_worker()
    """
    return summ_text_worker(text, subj, lang, query)


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
        text = summ_url(url, download_only = True)
        if text:
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
def summ_url(url:str, download_only: bool = False, lang: str = 'ru', deep: bool = False):
    """скачивает веб страницу, просит гптчат или бинг сделать краткое изложение текста, возвращает текст
    если в ссылке ютуб то скачивает субтитры к видео вместо текста
    может просто скачать текст без саммаризации, для другой обработки"""
    youtube = False
    pdf = False
    if '/youtu.be/' in url or 'youtube.com/' in url or '//dzen.ru/video/watch/' in url or \
       '//rutube.ru/video/' in url or 'pornhub.com/view_video.php?viewkey=' in url or \
       ('tiktok.com' in url and 'video' in url) or \
       ('vk.com' in url and '/video-' in url) or \
       ('//my.mail.ru/v/' in url and '/video/' in url):
        text = get_text_from_youtube(url, language=lang)
        youtube = True
    else:
        # Получаем содержимое страницы

        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}

        try:
            response = requests.get(url, stream=True, headers=headers, timeout=20)
            content = b''
            # Ограничиваем размер
            for chunk in response.iter_content(chunk_size=1024):
                content += chunk
                if len(content) > 1 * 1024 * 1024: # 1 MB
                    break
        except:
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
                                       )
            # if not text:
            #     text = content

    if download_only:
        if youtube:
            r = f'URL: {url}\nСубтитры из видео на ютубе (полное содержание, отметки времени были удалены):\n\n{text}'
        else:
            r = f'URL: {url}\nРаспознанное содержание веб страницы:\n\n{text}'
        return r
    else:
        if youtube:
            r = summ_text(text, 'youtube_video', lang)
        elif pdf:
            r = summ_text(text, 'pdf', lang)
        else:
            if deep:
                text += '\n\n==============\nDownloaded links from the text for better analysis\n==============\n\n' + download_in_parallel(get_urls_from_text(text), my_gemini.MAX_SUM_REQUEST)
                r = summ_text(text, 'text', lang)
            else:
                r = summ_text(text, 'text', lang)
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
