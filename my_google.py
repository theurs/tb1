#!/usr/bin/env python3


import chardet
import datetime
import io
import requests
import urllib.parse

import googlesearch
import trafilatura
import magic
import PyPDF2

import gpt_basic
import my_log



max_request = 3500
#max_request = 1800

def search(q: str, max_req: int = max_request, max_search: int = 10, hist: str = '') -> str:
    """ищет в гугле ответ на вопрос q, отвечает с помощью GPT
    max_req - максимальный размер ответа гугла, сколько текста можно отправить гпт чату
    max_search - сколько ссылок можно прочитать пока не наберется достаточно текстов
    hist - история диалога, о чем говорили до этого
    """
    
    max_req = max_req - len(hist)
    
    # добавляем в список выдачу самого гугла, и она же первая и главная
    urls = [f'https://www.google.com/search?q={urllib.parse.quote(q)}',]
    # добавляем еще несколько ссылок, возможно что внутри будут пустышки, джаваскрипт заглушки итп
    r = googlesearch.search(q, stop = max_search)
    bad_results = ('https://g.co/','.pdf','.docx','.xlsx', '.doc', '.xls')
    for url in r:
        if any(s.lower() in url.lower() for s in bad_results):
            continue
        urls.append(url)

    result = ''
    newconfig = trafilatura.settings.use_config()
    newconfig.set("DEFAULT", "EXTRACTION_TIMEOUT", "0")

    for url in urls:
        content = trafilatura.fetch_url(url)
    
        if content:
            #text = trafilatura.extract(content, config=newconfig, include_links=True, deduplicate=True)
            text = trafilatura.extract(content, config=newconfig)
            if text:
                result += text
                if len(result) > max_req:
                    break

    #text = f'Выдели из текста важные факты и подробности, они понадобятся для дальнейших ответов.\n\n\n{result}'
    
    #text = f'Ответь на запрос юзера, используй результаты поиска в гугле по этому запросу, отвечай коротко и по делу если юзер не просил по другому.\nЗапрос: {q}\nРезультаты поиска в гугле по этому запросу:\n\n\n{result}'
    
    #text = f'Ответь на запрос юзера, используй результаты поиска в гугле по этому запросу, отвечай только на запрос юзера без мыслей в сторону и своих комментариев.\nЗапрос: {q}\nРезультаты поиска в гугле по этому запросу:\n\n\n{result}'
    #text = f'Ответь на запрос юзера, используй результаты поиска в гугле по этому запросу.\nЗапрос: {q}\nРезультаты поиска в гугле по этому запросу:\n\n\n{result}'
    
    text = f"""Ответь на запрос юзера, используй результаты поиска в Google по этому запросу,
игнорируй непонятные символы в результатах поиска, они не должны влиять на ответ,
в ответе должно быть только то что юзер искал, и не должно быть того что не искал,
постарайся понять смысл его запроса и что он хочет увидеть в ответ,
если на такие запросы нельзя отвечать то переведи всё в шутку.


О чем говорили до этого: {hist}


Запрос: {q}


Результаты поиска в гугле по этому запросу:


{result}"""
    my_log.log2(text[:max_req])
    return gpt_basic.ai(text[:max_req])



if __name__ == "__main__":
    print(search('курс доллара'), '\n\n')
    print(search('текст песни егора пикачу'), '\n\n')

    print(search('когда доллар рухнет?'), '\n\n')
    print(search('как убить соседа'), '\n\n')

    print(search('Главные герои книги незнайка на луне, подробно'), '\n\n')
    print(search('Главные герои книги три мушкетера, подробно'), '\n\n')
