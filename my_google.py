#!/usr/bin/env python3

import cachetools.func
import urllib.parse
import traceback

import googlesearch

import my_log
import my_gemini
import my_ddg
import my_groq
import my_sum
import utils


@cachetools.func.ttl_cache(maxsize=10, ttl=10 * 60)
def search_v3(query: str, lang: str = 'ru', max_search: int = 6, download_only = False):
    # добавляем в список выдачу самого гугла, и она же первая и главная
    urls = [f'https://www.google.com/search?q={urllib.parse.quote(query)}',]
    # добавляем еще несколько ссылок, возможно что внутри будут пустышки, джаваскрипт заглушки итп
    try:
        # r = googlesearch.search(query, stop = max_search, lang=lang)
        r = my_ddg.get_links(query, max_search)
        # raise Exception('not implemented')
    except Exception as error:
        my_log.log2(f'my_google:search_google_v3: {error}')
        try:
            # r = my_ddg.get_links(query, max_search)
            r = googlesearch.search(query, stop = max_search, lang=lang)
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

    # text = my_sum.download_in_parallel(urls, my_gemini.MAX_SUM_REQUEST)
    text = my_sum.download_text(urls, my_gemini.MAX_SUM_REQUEST)

    if download_only:
        return text

    q = f'''Answer to the user's search query.
Guess what they were looking for and compose a good answer using search results and your own knowledge.

The structure of the answer should be similar to the following: 

Show a block with the user`s intention briefly.
Show a block with a short and clear answer that satisfies most users.
Show a block with a full answer and links, links should be formatted for easy reading, markdown in links is mandatory.
Answer in "{lang}" language.

User`s query: "{query}"
Current date: {utils.get_full_time()}

Search results:

{text[:my_gemini.MAX_SUM_REQUEST]}
'''
    r = ''
    r =  my_gemini.ai(q[:my_gemini.MAX_SUM_REQUEST], model='gemini-1.5-flash-exp-0827', temperature=1)
    if r:
        r += '\n\n--\n[Gemini Flash]'
    # if not r:
    #     r = my_gemini.ai(q[:32000], model='gemini-1.5-flash-exp-0827', temperature=1)
    #     if r:
    #         r += '\n\n--\n[Gemini Flash]'
    if not r:
        r = my_groq.ai(q[:my_groq.MAX_SUM_REQUEST], max_tokens_ = 4000, model_= 'llama-3.1-70b-versatile')
        if r:
            r += '\n\n--\n[Llama 3.1 70b]'
    if not r:
        r = my_groq.ai(q[:32000], max_tokens_ = 4000, model_ = 'mixtral-8x7b-32768')
        if r:
            r += '\n\n--\n[Mixtral-8x7b-32768]'

    return r, f'Data extracted from Google with query "{query}":\n\n' + text


if __name__ == "__main__":
    pass
    # lines = [
    #     # 'курс доллара',
    #     'что значит 42',
    #     'что значит 42',
    #     ]
    # for x in lines:
    #     print(search_v3(x)[0], '\n\n')
