#!/usr/bin/env python3
#pip install -U duckduckgo_search[lxml]

import time

from duckduckgo_search import DDGS

import my_log


def get_links(query: str, max_results: int = 5) -> list:
    """
    Retrieves a list of links from the DuckDuckGo search engine based on the given query.

    Args:
        query (str): The search query.
        max_results (int, optional): The maximum number of results to return. Defaults to 5.

    Returns:
        list: A list of links found in the search results.

    Raises:
        Exception: If an error occurs during the search.

    Note:
        The `safesearch` parameter is set to 'off' to include potentially unsafe content in the search results.

    """
    try:
        results = DDGS().text(query, max_results = max_results, safesearch='off')
        return [x['href'] for x in results]
    except Exception as error:
        my_log.log2(f'my_ddg:get_links: {error}')
        return []


def ai(query: str, model: str = 'claude-3-haiku') -> str:
    """
    Generates a response from an AI model based on a given query and model.

    Args:
        query (str): The input query for the AI model.
        model (str, optional): The model to use for generating the response. Defaults to 'claude-3-haiku'.

    Returns:
        str: The generated response from the AI model. If an error occurs during the chat, an empty string is returned.

    Raises:
        None

    Note:
        The `model` parameter can be either "gpt-3.5" or "claude-3-haiku". If an invalid model is provided,
        the default model 'claude-3-haiku' will be used.
    """
    # model = "gpt-3.5" or "claude-3-haiku"
    # start_time = time.time()
    try:
        results = DDGS(timeout=120).chat(query, model=model)
    except Exception as error:
        my_log.log2(f'my_ddg:ai: {error}')
        return ''
    # end_time = time.time()
    # print(f'Elapsed time: {end_time - start_time:.2f} seconds, query size: {len(query)}, response size: {len(results)}, total size: {len(query) + len(results)}')
    return results


def chat_cli():
    """
    A function that provides a command-line interface for interacting with the DDG (DuckDuckGo) chatbot.

    This function creates an instance of the DDGS class with a timeout of 120 seconds.
    It then enters a loop where it prompts the user to input a query and sends
    it to the chatbot using the `chat` method of the DDGS instance.
    The response from the chatbot is then printed to the console.

    Parameters:
        None

    Returns:
        None
    """
    ddg = DDGS(timeout=120)
    while 1:
        q = input('> ')
        # r = ddg.chat(q, model='claude-3-haiku')
        r = ddg.chat(q, model='gpt-3.5')
        print(r)


if __name__ == '__main__':
    chat_cli()
    
    # print(get_links("курс доллара"))

    # for x in range(100):
    #     print(x)
    #     print(ai("напиши рассказ 500 слов про золото", model='gpt-3.5')[:100].replace('\n', ' '))
    #     print(ai("напиши рассказ 500 слов про золото")[:100].replace('\n', ' '))

    # t = open('1.txt', 'r', encoding='utf-8').read()
    # q = f'Кратко перескажи текст:\n\n{t[:4000]}'
    # print(ai(q, 'gpt-3.5'))
