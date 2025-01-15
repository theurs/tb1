#!/usr/bin/env python3

import cachetools.func
import hashlib
import requests
import time

import my_log


def genTK(text: str) -> str:
    """
    Generates a token for Google Translate API request.

    Args:
        text (str): Text to be translated.

    Returns:
        str: Generated token.
    """
    tkk = int(time.time() / 3600)
    a = tkk
    for char in text:
        a += ord(char)
        a = genRL(a, '+-a^+6')
    a = genRL(a, '+-3^+b+-f')
    a ^= tkk
    if a < 0:
        a = (a & 2147483647) + 2147483648
    a %= 1000000

    # Use hashlib to create a hash of the token
    token = hashlib.md5(f"{a}.{a ^ tkk}".encode()).hexdigest()
    return token


def genRL(a: int, b: str) -> int:
    """
    Helper function for token generation.

    Args:
        a (int): Number to be transformed.
        b (str): String for transformation.

    Returns:
        int: Transformed number.
    """
    for char in b:
        if char == '+':
            a += ord(char)
        elif char == '-':
            a -= ord(char)
        elif char == '^':
            a ^= ord(char)
        elif char.isdigit():
            a = (a << int(char)) & 0xFFFFFFFF
    return a


@cachetools.func.ttl_cache(maxsize=10, ttl=10 * 60)
def translate(text: str, lang: str = 'ru') -> str:
    """
    Translates text to the specified language.

    Args:
        text (str): Text to be translated.
        lang (str): Target language code (e.g., 'en' for English, 'ru' for Russian).

    Returns:
        str: Translated text or an empty string in case of an error.
    """
    url = "https://translate.googleapis.com/translate_a/single"
    params = {
        "client": "gtx",
        "sl": "auto",
        "tl": lang,
        "dt": "t",
        "q": text,
        "tk": genTK(text)
    }

    try:
        # Make a request to the Google Translate API with a timeout of 60 seconds
        response = requests.get(url, params=params, timeout=60)
        response.raise_for_status()
        response_json = response.json()

        translated_text = ""
        for item in response_json[0]:
            translated_text += item[0]

        return translated_text
    except requests.RequestException as error:
        my_log.log_translate(f"Error making request to Google Translate API: {error}\n\n{lang}\n\n{text}")
        return ""


if __name__ == "__main__":
    text = "Hello, world!\n\nHow are you? & What's <up>?"
    target_language = 'ru'
    translated_text = translate(text, target_language)
    print(translated_text)
