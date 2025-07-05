#!/usr/bin/env python3

import cachetools.func
import urllib.parse
import traceback

import googlesearch

import my_log
import my_cohere
import my_gemini
import my_gemini_general
import my_gemini_google
import my_ddg
import my_groq
import my_db
import my_sum
import my_tavily
import utils


@cachetools.func.ttl_cache(maxsize=10, ttl=120 * 60)
def search_v3(query: str,
              lang: str = 'ru',
              max_search: int = 10,
              download_only = False,
              chat_id: str = '',
              role: str = '',
              fast_search: bool = False,
    ):

    query = query.strip()
    text = ''

    if fast_search:
        # пробуем спросить в гроке, он быстрый
        response = my_groq.search(query, lang, system = role, user_id = chat_id)
        if response:
            if download_only:
                return response
            else:
                return response, response
        else:
            # пробуем спросить в гугле, он быстрый
            google_response = my_gemini_google.google_search(query, chat_id, role=role, lang=lang)
            if google_response:
                if download_only:
                    return google_response
                else:
                    return google_response, google_response

    if not query.startswith('!'):
        # пробуем спросить в tavily
        if lang:
            q = f'Отвечай на языке *{lang}*\n\n{query}'
        response = my_tavily.search(q, max_results=5, user_id=chat_id)

        if response:
            if download_only:
                response['answer'] = ''
                return str(response)
            else:
                # return response['answer'], str(response)
                text = str(response)

    if not text:
        if not query.startswith('!'):
            # сначала пробуем спросить в гроке
            response = my_groq.search(query, lang, system = role, user_id = chat_id)
            if response:
                if download_only:
                    return response
                else:
                    return response, response


        if not query.startswith('!'):
            # сначала пробуем спросить в гугле
            google_response = my_gemini_google.google_search(query, chat_id, role=role, lang=lang)
            if google_response:
                if download_only:
                    return google_response
                else:
                    return google_response, google_response

        query = query.lstrip('!')

        ## Если гугол не ответил или был маркер ! в запросе то ищем самостоятельно
        # добавляем в список выдачу самого гугла, и она же первая и главная
        urls = [f'https://www.google.com/search?q={urllib.parse.quote(query)}',]
        # добавляем еще несколько ссылок, возможно что внутри будут пустышки, джаваскрипт заглушки итп

        # но сначала пробуем сервис тавили
        text = my_tavily.search_text(query, user_id = chat_id)

    if not text:
        try:
            r = my_ddg.get_links(query, max_search)
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

        text = my_sum.download_text(urls, my_gemini_general.MAX_SUM_REQUEST)

    if download_only:
        return text

    q = f'''Answer to the user's search query.
Guess what they were looking for and compose a good answer using search results and your own knowledge.

Start the output immediately with the Brief answer.
Output:
Output language: [{lang}]
Highlight the key points.
Do not use any code blocks in the output text.
Do not use tools, tool_code.

Brief answer (50-1000[hard limit] words). Include short human-readable links if applicable.
Only text, do not include words like Brief answer (50-1000 words). Fine readable.

Links:
markdown formatted links if any, otherwise no links.

User`s query: "{query}"
Current date: {utils.get_full_time()}

Search results:

{text[:my_gemini_general.MAX_SUM_REQUEST]}
'''
    r = ''

    if not r:
        r =  my_gemini.sum_big_text(q[:my_gemini_general.MAX_SUM_REQUEST], query, role=role)
        if r:
            r += '\n\n--\n[Gemini Flash]'

    if not r:
        r = my_cohere.ai(q[:my_cohere.MAX_SUM_REQUEST], system=role)
        if r:
            r += '\n\n--\n[Command A]'

    if not r:
        r = my_groq.ai(q[:my_groq.MAX_SUM_REQUEST], max_tokens_ = 4000, system=role)
        if r:
            r += '\n\n--\n[Llama 3.2 90b]'
    if not r:
        r = my_groq.ai(q[:32000], max_tokens_ = 4000, model_ = 'mixtral-8x7b-32768', system=role)
        if r:
            r += '\n\n--\n[Mixtral-8x7b-32768]'

    return r, f'Data extracted from Google with query "{query}":\n\n' + text


if __name__ == "__main__":
    pass
    my_db.init(backup=False)
    # lines = [
    #     # 'курс доллара',
    #     'что значит 42',
    #     'что значит 42',
    #     ]
    # for x in lines:
    #     print(search_v3(x)[0], '\n\n')
    my_db.close()
