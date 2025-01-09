#!/usr/bin/env python3

import cachetools.func
import subprocess

import my_log
import utils


@cachetools.func.ttl_cache(maxsize=10, ttl = 10 * 60)
def translate(text: str, lang: str = 'ru') -> str:
    """
    Translates the given text into the specified language using an external 
    translation service. Requires the `trans` command to be installed.

    Args:
        text (str): The text to be translated.
        lang (str, optional): The language to translate the text to. Defaults to 'ru'.
    
    Returns:
        str: The translated text.
    """
    if 'windows' in utils.platform().lower():
        return text

    if lang == 'ua':
        lang = 'uk'

    text = text.strip()
    startswithslash = False
    if text.startswith('/'):
        text = text.replace('/', '@', 1)
        startswithslash = True

    process = subprocess.Popen(['trans', f':{lang}', '-b', text], stdout = subprocess.PIPE)
    output, error = process.communicate()
    result = output.decode('utf-8').strip()
    if error:
        my_log.log2(f'my_trans:translate_text2: {error}\n\n{text}\n\n{lang}')
        return ''

    if startswithslash:
        if result.startswith('@'):
            result = result.replace('@', '/', 1)

    return result


if __name__ == "__main__":
    pass
