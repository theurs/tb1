#!/usr/bin/env python3
# pip install -U simpleeval


import cachetools.func
import datetime
import decimal
import math
import mpmath
import numbers
import numpy
import numpy as np
import os
import pytz
import random
import requests
import subprocess
import time
import traceback

from simpleeval import simple_eval
from typing import Callable, Tuple, List, Union

# it will import word random and broke code
# from random import *
#from random import betavariate, choice, choices, expovariate, gammavariate, gauss, getrandbits, getstate, lognormvariate, normalvariate, paretovariate, randbytes, randint, randrange, sample, seed, setstate, shuffle, triangular, uniform, vonmisesvariate, weibullvariate

from geopy.geocoders import Nominatim
from sqlitedict import SqliteDict

import cfg
import my_db
import my_google
import my_gemini_google
import my_log
import my_groq
import my_tts
import my_sum
import utils


MAX_REQUEST = 25000


STORAGE = SqliteDict('db/skills_storage.db', autocommit=True)


def text_to_image(prompt: str) -> str:
    '''
    Generate and send image message from text to user.
    Use it only if asked by user to generate image from text.
    Args:
        prompt: str - text to generate image from
    '''
    my_log.log_gemini_skills(f'/img "{prompt}"')
    return "The function itself does not return an image. It returns a string containing instructions for the assistant. The assistant must send a new message, starting with the /img command, followed by a space, and then the prompt provided. This specific message format will be automatically recognized by an external system as a request to generate and send an image to the user."


def tts(
    text: str,
    lang: str = 'ru',
    chat_id: str = "",
    rate: str = '+0%',
    natural: bool = False,
    ) -> str:
    '''
    Generate and send audio message from text to user.
    Use it only if asked by user to generate audio from text.
    Args:
        text: str - text to say (up to 8000 symbols)
        lang: str - language code
        chat_id: str - telegram user chat id (Usually looks like 2 numbers in brackets '[9834xxxx] [24xx]')
        rate: str - speed rate, +-100%, default is '+0%'
        natural: bool - use natural voice, better quality, default is False
    Example: tts("Привет", "ru")
    '''
    def is_integer(s):
        try:
            int(s)
            return True
        except ValueError:
            return False

    my_log.log_gemini_skills(f'/tts "{text}" "{lang}" "{rate}" "{natural}" "{chat_id}"')

    # chat_id может приехать в виде одного числа - надо проверять и переделывать, добавлять скобки и число
    if is_integer(chat_id):
        chat_id = f"[{chat_id}] [0]"
    # если нет второго числа до добавить '[0]', как проверить что нету второго числа есть только одно в скобках?
    if chat_id.count('[') == 1:
        chat_id = f"{chat_id} [0]"

    if my_db.get_user_property(chat_id, 'tts_gender'):
        gender = my_db.get_user_property(chat_id, 'tts_gender')
    else:
        gender = 'female'

    if natural:
        if gender == 'female':
            gender = 'gemini_Leda'
        elif gender == 'male':
            gender = 'gemini_Puck'

    data = my_tts.tts(
        text=text,
        voice=lang,
        rate='+0%',
        gender=gender
    )

    if data and chat_id:
        STORAGE[chat_id] = (data, time.time())
        my_log.log_gemini_skills(f'TTS OK. Send to user: {chat_id}')
        return 'Backend report: Text was generated and sent to user.'
    else:
        my_log.log_gemini_skills(f'TTS ERROR. Send to user: {chat_id}')
        return 'Some error occurred.'


def init():
    """
    Iterate over STORAGE dict and remove expired entries
    """
    now = time.time()
    for key, value in list(STORAGE.items()):
        if now - value[1] > 600:  # 10 minutes
            del STORAGE[key]


@cachetools.func.ttl_cache(maxsize=10, ttl=60*60)
def get_coords(loc: str):
    '''Get coordinates from Nominatim API
    Example: get_coords("Vladivostok")
    Return tuple (latitude, longitude)
    '''
    geolocator = Nominatim(user_agent="kun4sun_bot")
    location = geolocator.geocode(loc)
    if location:
        return round(location.latitude, 2), round(location.longitude, 2)
    else:
        return None, None


@cachetools.func.ttl_cache(maxsize=10, ttl=60*60)
def get_weather(location: str) -> str:
    '''Get weather data from OpenMeteo API 7 days forth and back
    Example: get_weather("Vladivostok")
    Return json string
    '''
    try:
        location = decode_string(location)
        my_log.log_gemini_skills(f'Weather: {location}')
        lat, lon = get_coords(location)
        if not any([lat, lon]):
            return 'error getting data'
        my_log.log_gemini_skills(f'Weather: {lat} {lon}')
        # Make sure all required weather variables are listed here
        # The order of variables in hourly or daily is important to assign them correctly below
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,rain,showers,snowfall,weather_code,cloud_cover,pressure_msl,surface_pressure,wind_speed_10m,wind_direction_10m,wind_gusts_10m&daily=weather_code,temperature_2m_max,temperature_2m_min,apparent_temperature_max,apparent_temperature_min,sunrise,sunset,daylight_duration,sunshine_duration,uv_index_max,uv_index_clear_sky_max,precipitation_sum,rain_sum,showers_sum,snowfall_sum,precipitation_hours,precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max,wind_direction_10m_dominant,shortwave_radiation_sum,et0_fao_evapotranspiration&past_days=7"
        responses = requests.get(url, timeout = 20)
        my_log.log_gemini_skills(f'Weather: {responses.text[:100]}')
        return responses.text
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_gemini_skills(f'get_weather:Error: {error}\n\n{traceback_error}')
        return f'ERROR {error}'


@cachetools.func.ttl_cache(maxsize=10, ttl=60*60)
def get_currency_rates(date: str = '') -> str:
    '''Return json all currencies rates from https://openexchangerates.org
    date in YYYY-MM-DD format, if absent than latest'''
    try:
        if hasattr(cfg, 'OPENEXCHANGER_KEY') and cfg.OPENEXCHANGER_KEY:
            # https://openexchangerates.org/api/latest.json?app_id=APIKEY
            my_log.log_gemini_skills(f'Currency: {date or "latest"}')
            if date:
                url = f'https://openexchangerates.org/api/historical/{date}.json?app_id={cfg.OPENEXCHANGER_KEY}'
            else:
                url = f'https://openexchangerates.org/api/latest.json?app_id={cfg.OPENEXCHANGER_KEY}'
            responses = requests.get(url, timeout = 20)
            my_log.log_gemini_skills(f'Currency: {responses.text[:300]}')
            return responses.text
        else:
            my_log.log_gemini_skills(f'Currency: ERROR NO API KEY')
            return 'Error: no API key provided'
    except Exception as error:
        backtrace_error = traceback.format_exc()
        my_log.log_gemini_skills(f'get_currency_rates:Error: {error}\n\n{backtrace_error}')
        return f'ERROR {error}'


@cachetools.func.ttl_cache(maxsize=10, ttl=60 * 60)
def search_google(query: str, lang: str = 'ru') -> str:
    """
    Searches Google for the given query and returns the search results.
    You are able to mix this functions with other functions and your own ability to get best results for your needs.

    Args:
        query: The search query string.
        lang: The language to use for the search.

    Returns:
        A string containing the search results.
        In case of an error, returns a string 'ERROR' with the error description.
    """
    query = decode_string(query)
    my_log.log_gemini_skills(f'Google: {query}')
    try:
        # r = my_google.search_v3(query, 'ru')[0]
        r = my_google.search_v3(query, lang = lang, download_only=True)
        my_log.log_gemini_skills(f'Google: {r[:2000]}')
        return r
    except Exception as error:
        my_log.log_gemini_skills(f'search_google:Error: {error}')
        return f'ERROR {error}'


@cachetools.func.ttl_cache(maxsize=10, ttl=60 * 60)
def download_text_from_url(url: str) -> str:
    '''Download text from url if user asked to.
    Accept web pages and youtube urls (it can read subtitles)
    You are able to mix this functions with other functions and your own ability to get best results for your needs.
    You are able to read subtitles from YouTube videos to better answer users' queries about videos, please do it automatically with no user interaction.
    '''
    language = 'ru'
    my_log.log_gemini_skills(f'Download URL: {url} {language}')
    try:
        result = my_sum.summ_url(url, download_only = True, lang = language)
        return result[:MAX_REQUEST]
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_gemini_skills(f'download_text_from_url:Error: {error}\n\n{traceback_error}')
        return f'ERROR {error}'


def decode_string(s: str) -> str:
    if isinstance(s, str) and s.count('\\') > 2:
        try:
            s = s.replace('\\\\', '\\')
            s = str(bytes(s, "utf-8").decode("unicode_escape").encode("latin1").decode("utf-8"))
            return s
        except Exception as error:
            my_log.log_gemini_skills(f'Error: {error}')
            return s
    else:
        return s


@cachetools.func.ttl_cache(maxsize=10, ttl = 60*60)
def calc(expression: str) -> str:
    '''Calculate expression with pythons eval(). Use it for all calculations.
    Available modules: decimal, math, mpmath, numbers, numpy, random, datetime.
    Do not import them, they are already imported.
    Use only one letter variables.
    Avoid text in math expressions.

    You can also make requests in natural language if you need to do more complex calculations, for example: What is the digit after the decimal point in the number pi at position 7864?

    return str(eval(expression))
    Examples: calc("56487*8731") -> '493187997'
              calc("pow(10, 2)") -> '100'
              calc("math.sqrt(2+2)/3") -> '0.6666666666666666'
              calc("decimal.Decimal('0.234234')*2") -> '0.468468'
              calc("numpy.sin(0.4) ** 2 + random.randint(12, 21)")
              etc
    '''
    try:
        my_log.log_gemini_skills(f'New calc: {expression}')
        # expression = expression.replace('math.factorial', 'my_factorial')
        # decimal, math, mpmath, numbers, numpy, random, datetime
        allowed_functions = {
            'math': math,
            'decimal': decimal,
            'mpmath': mpmath,
            'numbers': numbers,
            'numpy': numpy,
            'np': np,
            'random': random,
            'datetime': datetime,
            # 'my_factorial': my_factorial,
            'abs': abs,
            'max': max,
            'min': min,
            'round': round,
            'sum': sum,
            'pow': pow,
            'complex': complex,
            'divmod': divmod,
            'float': float,
            'int': int,
        }
        result = str(simple_eval(expression, functions=allowed_functions))
        my_log.log_gemini_skills(f'Internal calc result: {result}')
        return result
    except Exception as error:
        #first try groq
        r = my_groq.calc(expression)
        if r:
            my_db.add_msg('groq-calc', 'compound-beta')
            return r
        r1, r0 = my_gemini_google.calc(expression)
        result = f'{r0}\n\n{r1}'.strip()
        if result:
            my_log.log_gemini_skills(f'Google calc result: {result}')
            return result
        else:
            traceback_error = traceback.format_exc()
            my_log.log_gemini_skills(f'Calc error: {expression}\n{error}\n\n{traceback_error}')
            return f'Error: {error}\n\n{traceback_error}'


calc_tool = calc


def test_calc(func: Callable = calc) -> None:
    """
    Тестирует функцию calc (которая теперь не принимает chat_id и возвращает строку)
    с набором предопределенных тестовых случаев.
    """

    test_cases: List[Tuple[str, Union[str, None]]] = [
        # Валидные выражения.
        # ('3.96140812E+28+3.96140812E+28', '7.92281624e+28'),
        # ("2 + 2", "4"),
        # ("10 * 5", "50"),
        # ("100 / 4", "25.0"),
        # ("2 ** 3", "8"),
        # ("1 + 2 * 3", "7"),
        # ("(1 + 2) * 3", "9"),
        # ("2 ++ 2", "4"), # 2 + (+2) = 4
        # ("sqrt(16)", "4.0"),
        # ("math.sqrt(16)", "4.0"),
        # ("math.sin(0)", "0.0"),
        # ("math.factorial(5)", "120"),
        # # Пример с Decimal (если ваша функция calc поддерживает его)
        # ("decimal.Decimal('1.23') + decimal.Decimal('4.56')", "5.79"),
        # ('math.factorial(10)', '3628800'),
        # ('math.factorial(1600)', ''),
        ('round((80 / 270) * 100, 2)', '29.63'),
        #date example
        # ("datetime.datetime.now()", ""),
        # # Примеры, где мы не можем предсказать *точный* вывод, но все равно можем проверить:
        # ("random.randint(1, 10)", None),  # Мы не знаем точное число
        # ("x + y + z", None),  # Предполагая, что функция обрабатывает неопределенные переменные
        # ("a*2+b-c", None),
        # # Недопустимые выражения (ожидаем ошибки).
        # ("x = 5\ny = 10\nx + y", ""),
        # ("invalid_function(5)", ""),
        # ("2 + abc", ""),
        # ("print('hello')", ""),
        # ("os.system('ls -l')", ""),  # Если функция блокирует os.system
        # ("1 / 0", ""),
        # ("math.unknown_function()", ""),
        # ("", ""),  # Пустое выражение тоже должно быть ошибкой.
        # ('89479**78346587', ''),
    ]

    for expression, expected_result in test_cases:
        result = func(expression)

        print(f"Запрос: {expression}")
        print(f"Ответ: {result}")

        if expected_result == "":  # Случай ошибки
            if result == "" or result.startswith('Error'):
                print(f"Результат: OK (Ожидалась ошибка) {result}")
            else:
                print(f"Результат: FAIL (Ожидалась ошибка, получено: {result})")
        elif expected_result is None:  # Непредсказуемый результат
            if result != "":
                print("Результат: OK (Результат получен)")
            else:
                print("Результат: FAIL (Результат не получен)")
        else:  # У нас есть конкретный ожидаемый результат
            if result == expected_result:
                print("Результат: OK")
            else:
                print(f"Результат: FAIL (Ожидалось: {expected_result}, Получено: {result})")
        print("-" * 20)

    print("Тесты завершены.")


def get_time_in_timezone(timezone_str: str) -> str:
    """
    Returns the current time in the specified timezone.

    Args:
        timezone_str: A string representing the timezone (e.g., "Europe/Moscow", "America/New_York").

    Returns:
        A string with the current time in "YYYY-MM-DD HH:MM:SS" format, or an error message if the timezone is invalid.
    """
    try:
        timezone = pytz.timezone(timezone_str)
        now = datetime.datetime.now(timezone)
        time_str = now.strftime("%Y-%m-%d %H:%M:%S")
        my_log.log_gemini_skills(f'get_time_in_timezone: timezone_str={timezone_str} time={time_str}')
        return now.strftime("%Y-%m-%d %H:%M:%S")
    except Exception as error:
        my_log.log_gemini_skills(f'get_time_in_timezone: Invalid timezone {timezone_str}\n{error}')
        return f"Error: Invalid timezone '{timezone_str}'"


def run_script(filename: str, body: str) -> str:
    """
    Saves and runs a script in the shell, returning its output. This script has full access to files and network, there are no sandboxes.
    Allowed file extensions are ".py" for Python and ".sh" for Bash. Do not add any shebang to the body.
    The function will execute the code using: subprocess.check_output(f'./run_script_{filename}', shell=True, timeout=300)

    Args:
        filename: The name of the file to be created.
        body: The content of the script to be executed.

    Returns:
        The output of the executed script.

    Instructions:
        1. Pass the filename with the extension (.py or .sh) to the 'filename' argument.
        2. Pass the script content without the shebang (#!... ) to the 'body' argument.
        3. If 'filename' ends with .py, the 'body' will be executed as a Python script.
        4. If 'filename' ends with .sh, the 'body' will be executed as a Bash script.
        5. The function will save the script to disk, make it executable, run it, and return the output.
        6. If an error occurs during script execution, the function will return the error message.
        7. After executing the script, it will be deleted from the disk.

    Example:
        filename = 'script.py'
        body = '''
import os
print(os.getcwd())
'''
        result = run_script(filename, body)
        print(result)

    Or:

        filename = 'script.sh'
        body = '''
echo "Hello, world!"
ls -l
'''
        result = run_script(filename, body)
        print(result)

    Important:
    - Ensure the script content in `body` is properly formatted and does not contain syntax errors.
    - Be cautious when running scripts with network access, as they have full access to the network.
    - If the script generates files, make sure to handle them appropriately (e.g., delete them after use).
    - Double quotes inside the script body are NOT escaped anymore.
    - Use triple quotes (''') to pass multiline strings with quotes to avoid manual escaping.
    """
    body = decode_string(body)
    filename = 'run_script_' + filename
    ext = utils.get_file_ext(filename)
    if ext.startswith('.'):
        ext = ext[1:]

    if ext == 'py':
        if not body.split()[0].startswith('#!/'):
            body = '#!/usr/bin/env python3\n\n' + body
        # Do not escape double quotes
    elif ext == 'sh':
        if not body.split()[0].startswith('#!/'):
            body = '#!/bin/bash\n\n' + body
    # Remove extra escaping that was added previously
    # body = body.replace('\\\\', '\\')

    my_log.log_gemini_skills(f'run_script {filename}\n\n{body}')

    try:
        with open(filename, 'w') as f:
            f.write(body)
        os.chmod(filename, 0o777)
        try:
            output = subprocess.check_output(f'./{filename}', shell=True, timeout=300, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as error:
            if not error.output:
                output = str(error).encode('utf-8', errors='replace')
            else:
                output = error.output
        utils.remove_file(filename)
        result = output.decode('utf-8', errors='replace')
        my_log.log_gemini_skills(f'run_script: {result}')
        return result
    except Exception as error:
        utils.remove_file(filename)
        traceback_error = traceback.format_exc()
        my_log.log_gemini_skills(f'run_script: {error}\n{traceback_error}\n\n{filename}\n{body}')
        return f'{error}\n\n{traceback_error}'


if __name__ == '__main__':
    pass
    init()
    my_db.init(backup=False)
    my_groq.load_users_keys()
    # moscow_time = get_time_in_timezone("Europe/Moscow")
    # print(f"Time in Moscow: {moscow_time}")

    test_calc()

    # print(sys.get_int_max_str_digits())
    # print(sys.set_int_max_str_digits())

    # text='''ls -l'''
    # print(run_script('test.sh', text))

    my_db.close()
