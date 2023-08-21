#!/usr/bin/env python3


import re

import wikipedia

import utils


language = "ru"
wikipedia.set_lang(language)


def get_content(query: str) -> str:
    """
    Retrieves the content related to the given query from Wikipedia.

    Args:
        query (str): The query to search for on Wikipedia.

    Returns:
        str: The content retrieved from Wikipedia related to the query.

    Raises:
        wikipedia.exceptions.PageError: If the query does not match any Wikipedia page.
        wikipedia.exceptions.DisambiguationError: If the query is ambiguous and has multiple options.

    Example:
        get_content("Python") returns the content related to the Python programming language.
    """
    try:
        page = wikipedia.page(query)
        if len(page.content) < 11000:
            result = page.content
        else:
            result = wikipedia.summary(query)
    except wikipedia.exceptions.PageError:
        result = wikipedia.search(query)
        if not result:
            result = "Ничего не найдено"
    except wikipedia.exceptions.DisambiguationError as error:
        result = get_content(error.options[0]) + '\n\n**Возможные варианты:**\n' + '\n'.join([f'`/wikipedia {x}`' for x in error.options])
    # заменить всё что находится между двумя ==  на две **
    result = re.sub('=== (.*) ===', '**\\1**', result)
    result = re.sub('== (.*) ==', '**\\1**', result)
    result = utils.bot_markdown_to_html(result)
    return result


if __name__ == '__main__':
    p = get_content("hack")
    print(p)