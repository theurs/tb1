#!/usr/bin/env python3


import html
import json
import sys

import my_log
from Perplexity import Perplexity
import utils


def ask(query: str, search_focus: str = 'internet') -> str:
    """
    This function takes a query string and a search focus as input parameters and returns a string.
    
    Args:
        query (str): The query string to be searched.
        search_focus (str, optional): The focus of the search. Default is 'internet'.
        
    Returns:
        str: The result of the search as a string.
    """
    query += ' (отвечай на русском языке)'

    assert search_focus in ["internet", "scholar", "news", "youtube", "reddit", "wikipedia"], "Invalid search focus"

    try:
        perplexity = Perplexity()
        answer = perplexity.search(query, search_focus=search_focus)
        result = ''
        for i in answer:
            pass
        d = json.loads(i['text'])
        result = d['answer']
    except Exception as error:
        print(error)
        my_log.log2(f'my_perplexity.py:ask: {error}')

    try:
        result += '\n\n'
        n = 1
        links = []
        for x in d['web_results']:
            # result += f'[{n}] <a href="{x["url"]}">{html.escape(x["name"])}</a>\n\n'
            links.append(f'<a href="{x["url"]}">[{n}]</a>')
            n += 1
        result = utils.bot_markdown_to_html(result)
        # заменяем ссылки
        for x in range(1, 11):
            if f'[{x}]' in result:
                result = result.replace(f'[{x}]', links[x-1])

    except Exception as error:
            print(error)
            my_log.log2(f'my_perplexity.py:ask: {error}')

    perplexity.close()

    return result


if __name__ == '__main__':
    """Usage ./bingai.py 'list 10 japanese dishes"""
    t = sys.argv[1]
    print(ask(t))  
