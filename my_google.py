#!/usr/bin/env python3

import concurrent.futures
import urllib.parse
import traceback

import googlesearch

import cfg
import my_log
import my_gemini
import my_ddg
import my_groq
import my_sum
import utils


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
        text = my_sum.summ_url(url, download_only = True)
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


def search_v3(query: str, lang: str = 'ru', max_search: int = 15):
    # добавляем в список выдачу самого гугла, и она же первая и главная
    urls = [f'https://www.google.com/search?q={urllib.parse.quote(query)}',]
    # добавляем еще несколько ссылок, возможно что внутри будут пустышки, джаваскрипт заглушки итп
    try:
        r = googlesearch.search(query, stop = max_search, lang=lang)
        # raise Exception('not implemented')
    except Exception as error:
        my_log.log2(f'my_google:search_google_v3: {error}')
        try:
            r = my_ddg.get_links(query, max_search)
        except Exception as error:
            my_log.log2(f'my_google:search_google_v3: {error}')
            return ''

    bad_results = ('https://g.co/','.pdf','.docx','.xlsx', '.doc', '.xls')

    try:
        for url in r:
            if any(s.lower() in url.lower() for s in bad_results):
                continue
            urls.append(url)
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log2(f'my_google:search_v3: {error}\n\n{error_traceback}')

    text = download_in_parallel(urls, my_gemini.MAX_SUM_REQUEST)

    q = f'''Answer to the user's search query.
Guess what they were looking for and compose a good answer using search results and your own knowledge.

The structure of the answer should be similar to the following: 

Show a block with the user`s intention briefly.
Show a block with a short and clear answer that satisfies most users.
Show a block with a full answer and links, links should be formatted for easy reading.
Answer in "{lang}" language.

User`s query: "{query}"
Current date: {utils.get_full_time()}

Search results:

{text[:my_gemini.MAX_SUM_REQUEST]}
'''
    r = ''
    r =  my_gemini.ai(q[:my_gemini.MAX_SUM_REQUEST], model='gemini-1.5-flash-latest')
    if r:
        r += '\n\n--\n[Gemini Pro Flash]'
    if not r:
        r = my_gemini.ai(q[:32000], model='gemini-1.5-flash-latest')
        if r:
            r += '\n\n--\n[Gemini Pro Flash]'
        if not r:
            r = my_groq.ai(q[:32000], max_tokens_ = 4000, model_ = 'mixtral-8x7b-32768')
            if r:
                r += '\n\n--\n[Mixtral-8x7b-32768]'
            if not r:
                r = my_groq.ai(q[:12000], max_tokens_ = 4000)
                if r:
                    r += '\n\n--\n[Llama 3 70b]'

    return r, f'Data extracted from Google with query "{query}":\n\n' + text


if __name__ == "__main__":
    lines = [
        # 'курс доллара',
        'что значит 42',
        # 'можно ли на huggingface делать nsfw',
        ]
    for x in lines:
        print(search_v3(x)[0], '\n\n')
        # print(search_v3(x)[0], '\n\n')
