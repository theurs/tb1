#!/usr/bin/env python3


import html
import random

import cfg
import my_log
import utils
from Perplexity import Perplexity


def get_proxy():
    try:
        if cfg.perplexity_proxies:
            p = random.choice(cfg.perplexity_proxies)
            proxies = {
                'http': p,
                'https': p
            }
        else:
            proxies = None
    except Exception as error:
        print(f'my_perplexity.py:get_proxy: {error}')
        my_log.log2(f'my_perplexity.py:get_proxy: {error}')
        proxies = None
    return proxies


def ask(query: str, search_focus: str = 'internet') -> str:
    query += ' (отвечай на русском языке)'

    assert search_focus in ["internet", "scholar", "news", "youtube", "reddit", "wikipedia"], "Invalid search focus"

    # пробуем 3 раза получить ответ
    for _ in range(3):
        try:
            perplexity = Perplexity(get_proxy())
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
                text = text.replace(f'[{n + 1}]', f'<a href = "{link[1]}" title = "{html.escape(link[0])}">[{n + 1}]</a>')
                n += 1
            for link in links2:
                text += '\n\n' + f'<a href = "{link[1]}">{html.escape(link[0])}</a>'
            return text

    return ''


if __name__ == '__main__':

    print(ask('1+1'))
    while 1:
        query = input('> ')
        print(ask(query))
