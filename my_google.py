#!/usr/bin/env python3

import concurrent.futures
import urllib.parse
import traceback

from duckduckgo_search import DDGS
import googlesearch
import trafilatura

import cfg
import my_log
import my_gemini
import my_groq


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
    newconfig = trafilatura.settings.use_config()
    newconfig.set("DEFAULT", "EXTRACTION_TIMEOUT", "0")
    for url in urls:
        content = trafilatura.fetch_url(url)
        # text = trafilatura.extract(content, config=newconfig, include_links=True, deduplicate=True, \
        #                            include_comments = True)
        text = trafilatura.extract(content, config=newconfig, include_links = False, deduplicate=True)
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


def ddg_text(query: str) -> str:
    """
    Generate a list of URLs from DuckDuckGo search results based on the given query.

    Parameters:
        query (str): The search query.

    Returns:
        str: A URL from each search result.
    """
    with DDGS() as ddgs:
        for result in ddgs.text(query, safesearch='Off', timelimit='y', region = 'ru-ru'):
            yield result['href']


def download_in_parallel(urls, max_sum_request):
    text = ''
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        future_to_url = {executor.submit(download_text_v2, url, 40000): url for url in urls}
        for future in concurrent.futures.as_completed(future_to_url):
            try:
                result = future.result()
                text += result
                if len(text) > max_sum_request:
                    break
            except Exception as exc:
                my_log.log2(f'my_google:download_in_parallel: {exc}')
                print(f"Exception occurred while processing {future_to_url[future]}: {exc}")
    return text


def search_v3(query: str, lang: str = 'ru', max_search: int = 20) -> str:
    # добавляем в список выдачу самого гугла, и она же первая и главная
    urls = [f'https://www.google.com/search?q={urllib.parse.quote(query)}',]
    # добавляем еще несколько ссылок, возможно что внутри будут пустышки, джаваскрипт заглушки итп
    try:
        r = googlesearch.search(query, stop = max_search, lang=lang)
    except Exception as error:
        my_log.log2(f'my_google:search_google_v2: {error}')
        try:
            r = [x for x in ddg_text(query)]
        except Exception as error:
            my_log.log2(f'my_google:search_google_v2: {error}')
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

    # text = ''
    # for url in urls:
    #     # print(url)
    #     text += download_text_v2(url, 20000)
    #     if len(text) > my_gemini.MAX_SUM_REQUEST:
    #         break
    text = download_in_parallel(urls, my_gemini.MAX_SUM_REQUEST)

    q = f'''Answer in "{lang}" language to users search query using search results and your own knowledge.
User query: "{query}"

Search results:

{text[:my_gemini.MAX_SUM_REQUEST]}
'''
    # print(len(q))
    # print(f'{q[:1000]}...')
    return my_gemini.ai(q, model='gemini-1.5-pro-latest'), f'Data extracted from Google with query "{query}":\n\n' + text


def search_v4(query: str, lang: str = 'ru', max_search: int = 10) -> str:
    # добавляем в список выдачу самого гугла, и она же первая и главная
    urls = [f'https://www.google.com/search?q={urllib.parse.quote(query)}',]
    # добавляем еще несколько ссылок, возможно что внутри будут пустышки, джаваскрипт заглушки итп
    try:
        r = googlesearch.search(query, stop = max_search, lang=lang)
    except Exception as error:
        my_log.log2(f'my_google:search_google_v2: {error}')
        try:
            r = [x for x in ddg_text(query)]
        except Exception as error:
            my_log.log2(f'my_google:search_google_v2: {error}')
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

    # text = ''
    # for url in urls:
    #     # print(url)
    #     text += download_text([url,], 5000)
    #     if len(text) > 12000:
    #         break

    text = download_in_parallel(urls, my_groq.MAX_SUM_REQUEST)

    q = f'''Answer in "{lang}" language to users search query using search results and your own knowledge.
User query: "{query}"

Search results:

{text[:12000]}
'''
    return my_groq.ai(q, max_tokens_ = 4000), f'Data extracted from Google with query "{query}":\n\n' + text


if __name__ == "__main__":
    print(search_v3('курс доллара')[0], '\n\n')
