#!/usr/bin/env python3


import os
import time
import threading

import cfg
import utils
import my_log
from Perplexity import Perplexity


perplexity = Perplexity()
lock = threading.Lock()


def ask(query: str, search_focus: str = 'internet') -> str:
    global perplexity

    query += ' (отвечай на русском языке)'
    
    assert search_focus in ["internet", "scholar", "news", "youtube", "reddit", "wikipedia"], "Invalid search focus"

    # пробуем 3 раза получить ответ
    for _ in range(3):
        try:
            with lock:
                answer = perplexity.search(query, search_focus)
        except Exception as error:
            answer = ''
            print(error)
            my_log.log2(f'my_perplexity.py:ask: {error}')
        if answer:
            text = answer.json_answer_text["answer"]
            links = []
            for web_result in answer.json_answer_text['web_results']:
                links.append([web_result['name'], web_result['url']])

            links2 = []
            for web_result in answer.json_answer_text['extra_web_results']:
                links2.append([web_result['name'], web_result['url']])

            # меняем маркдаун разметку на хтмл
            text = utils.bot_markdown_to_html(text)

            # меняем ссылки из текста
            n = 0
            for link in links:
                text = text.replace(f'[{n + 1}]', f'<a href = "{link[1]}" title = "{link[0]}">[{n + 1}]</a>')
                n += 1
            for link in links2:
                text += '\n\n' + f'<a href = "{link[1]}">{link[0]}</a>'
            return text
        else:
            with lock:
                # переподключение
                perplexity = Perplexity()
                time.sleep(1)

    return ''


if __name__ == '__main__':
    # os.environ['all_proxy'] = cfg.all_proxy

    print(ask('курс доллара'))
    while 1:
        query = input('> ')
        print(ask(query))
