#!/usr/bin/env python3


import cachetools.func
import math
import datetime
import decimal
import numbers
import numpy
import numpy as np
import os
import pytz
import random
import re
import requests
import subprocess
import traceback
from math import *
from decimal import *
from numbers import *

# it will import word random and broke code
# from random import *
from random import betavariate, choice, choices, expovariate, gammavariate, gauss, getrandbits, getstate, lognormvariate, normalvariate, paretovariate, randbytes, randint, randrange, sample, seed, setstate, shuffle, triangular, uniform, vonmisesvariate, weibullvariate

from geopy.geocoders import Nominatim

import cfg
import my_db
import my_google
import my_log
import my_groq
import my_sum
import utils


MAX_REQUEST = 25000


@cachetools.func.ttl_cache(maxsize=10, ttl=60*60)
def get_coords(loc: str):
    '''Get coordinates from Nominatim API
    Example: get_coords("Vladivostok")
    Return tuple (latitude, longitude)
    '''
    geolocator = Nominatim(user_agent="kun4sun_bot")
    location = geolocator.geocode(loc)
    return round(location.latitude, 2), round(location.longitude, 2)


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
        my_log.log_gemini_skills(f'Weather: {lat} {lon}')
        # Make sure all required weather variables are listed here
        # The order of variables in hourly or daily is important to assign them correctly below
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,rain,showers,snowfall,weather_code,cloud_cover,pressure_msl,surface_pressure,wind_speed_10m,wind_direction_10m,wind_gusts_10m&daily=weather_code,temperature_2m_max,temperature_2m_min,apparent_temperature_max,apparent_temperature_min,sunrise,sunset,daylight_duration,sunshine_duration,uv_index_max,uv_index_clear_sky_max,precipitation_sum,rain_sum,showers_sum,snowfall_sum,precipitation_hours,precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max,wind_direction_10m_dominant,shortwave_radiation_sum,et0_fao_evapotranspiration&past_days=7"
        # url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,rain,showers,snowfall,weather_code,cloud_cover,pressure_msl,surface_pressure,wind_speed_10m,wind_direction_10m,wind_gusts_10m&hourly=temperature_2m,relative_humidity_2m,dew_point_2m,apparent_temperature,precipitation_probability,precipitation,rain,showers,snowfall,snow_depth,weather_code,pressure_msl,surface_pressure,cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,visibility,evapotranspiration,et0_fao_evapotranspiration,vapour_pressure_deficit,wind_speed_10m,wind_speed_80m,wind_speed_120m,wind_speed_180m,wind_direction_10m,wind_direction_80m,wind_direction_120m,wind_direction_180m,wind_gusts_10m,temperature_80m,temperature_120m,temperature_180m,soil_temperature_0cm,soil_temperature_6cm,soil_temperature_18cm,soil_temperature_54cm,soil_moisture_0_to_1cm,soil_moisture_1_to_3cm,soil_moisture_3_to_9cm,soil_moisture_9_to_27cm,soil_moisture_27_to_81cm&daily=weather_code,temperature_2m_max,temperature_2m_min,apparent_temperature_max,apparent_temperature_min,sunrise,sunset,daylight_duration,sunshine_duration,uv_index_max,uv_index_clear_sky_max,precipitation_sum,rain_sum,showers_sum,snowfall_sum,precipitation_hours,precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max,wind_direction_10m_dominant,shortwave_radiation_sum,et0_fao_evapotranspiration&timezone=Europe%2FMoscow&past_days=7"
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

    Args:
        query: The search query string.
        lang: The language for the search (defaults to 'ru').

    Returns:
        A string containing the search results.
        In case of an error, returns a string 'ERROR' with the error description.
    """
    query = decode_string(query)
    my_log.log_gemini_skills(f'Google: {query}')
    try:
        r = my_google.search_v3(query, lang)[0]
        my_log.log_gemini_skills(f'Google: {r}')
        return r
    except Exception as error:
        my_log.log_gemini_skills(f'search_google:Error: {error}')
        return f'ERROR {error}'


@cachetools.func.ttl_cache(maxsize=10, ttl=60 * 60)
def download_text_from_url(url: str, language: str = 'ru') -> str:
    '''Download text from url if user asked to.
    Accept web pages and youtube urls (it can read subtitles)
    language code is 2 letters code, it is used for youtube subtitle download
    '''
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
    Available modules: decimal, math, numbers, numpy, random, datetime.
    Use only one letter variables.
    Avoid text in math expressions.

    return str(eval(expression))
    Examples: calc("56487*8731") -> '493187997'
              calc("pow(10, 2)") -> '100'
              calc("math.sqrt(2+2)/3") -> '0.6666666666666666'
              calc("decimal.Decimal('0.234234')*2") -> '0.468468'
              calc("numpy.sin(0.4) ** 2 + random.randint(12, 21)")
    '''
    my_log.log_gemini_skills(f'Calc: {expression}')
    allowed_words = [
        'math', 'decimal', 'random', 'numbers', 'numpy', 'np',
        'print', 'str', 'int', 'float', 'bool', 'type', 'len', 'range',
        'round', 'pow', 'sum', 'min', 'max', 'divmod',
        'for', 'not', 'in', 'and', 'if', 'or', 'next',
        'digit',

        'list','tuple','sorted','reverse','True','False',

        'datetime', 'days', 'seconds', 'microseconds', 'milliseconds', 'minutes', 'hours', 'weeks',
        ]
    allowed_words += [x for x in dir(random) + dir(math) + dir(decimal) + dir(numbers) + dir(datetime) + dir(datetime.date) + dir(numpy) if not x.startswith('_')]
    allowed_words = sorted(list(set(allowed_words)))
    # get all words from expression
    words = re.findall(r'[^\d\W]+', expression)
    for word in words:
        if len(word) == 1:
            continue
        if word not in allowed_words:
            return f'Error: Invalid expression. Forbidden word: {word}'
    try:
        expression_ = expression.replace('math.factorial', 'my_factorial')
        r = str(eval(expression_))
        my_log.log_gemini_skills(f'Calc result: {r}')
        return r
    except Exception as error:
        return f'Error: {error}'


@cachetools.func.ttl_cache(maxsize=10, ttl = 60*60)
def calc_admin(expression: str) -> str:
    '''Calculate expression with pythons eval(). Use it for all calculations.
    Available modules: decimal, math, numbers, numpy, random, datetime.

    return str(eval(expression))
    Examples: calc("56487*8731") -> '493187997'
              calc("pow(10, 2)") -> '100'
              calc("math.sqrt(2+2)/3") -> '0.6666666666666666'
              calc("decimal.Decimal('0.234234')*2") -> '0.468468'
              calc("numpy.sin(0.4) ** 2 + random.randint(12, 21)")
    '''
    my_log.log_gemini_skills(f'Admin calc: {expression}')

    try:
        expression_ = expression.replace('math.factorial', 'my_factorial')
        r = str(eval(expression_))
        my_log.log_gemini_skills(f'Admin calc result: {r}')
        return r
    except Exception as error:
        return f'Error: {error}'


def my_factorial(n: int) -> int:
    '''Calculate factorial of n.
    return int(math.factorial(n))
    '''
    if n > 1500:
        raise ValueError('factorial > 1500, too big number')
    return math.factorial(n)


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


# # надо использовать стиль типа такого что бы он не отнекивался, не говорил что не может не умеет
# # /style ты можешь сохранять и запускать скрипты на питоне и баше через функцию run_script, в скриптах можно импортировать любые библиотеки и обращаться к сети и диску
# def run_script(filename: str, body: str) -> str:
#     '''Save and run script in shell, return its output. This script has full access to files and network, there are no any sandboxes.
#     Allowed file ".py" for python and ".sh" for bash, do not add any shebang to body.
#     It will run code for you - subprocess.check_output(f'./{filename}', shell=True, timeout=300)
#     '''
#     body = decode_string(body)
#     filename = 'run_script_' + filename
#     ext = utils.get_file_ext(filename)
#     if ext.startswith('.'):
#         ext = ext[1:]

#     if ext == 'py':
#         if not body.split()[0].startswith('#!/'):
#             body = '#!/usr/bin/env python3\n\n' + body
#     elif ext == 'sh':
#         if not body.split()[0].startswith('#!/'):
#             body = '#!/bin/bash\n\n' + body

#     body = body.replace('\\n', '\n')

#     # lines = body.splitlines()
#     # if lines[0].startswith('#!/') and lines[0].endswith('\\'):
#     #     lines[0] = lines[0][:-1]
#     # body = '\n'.join(lines)

#     my_log.log_gemini_skills(f'run_script {filename}\n\n{body}')
#     try:
#         with open(filename, 'w') as f:
#             f.write(body)
#         os.chmod(filename, 0o777)
#         try:
#             output = subprocess.check_output(f'./{filename}', shell=True, timeout=300, stderr=subprocess.STDOUT)
#         except subprocess.CalledProcessError as error:
#             if not error.output:
#                 output = str(error).encode('utf-8', errors='replace')
#             else:
#                 output = error.output
#         utils.remove_file(filename)
#         result = output.decode('utf-8', errors='replace')
#         my_log.log_gemini_skills(f'run_script: {result}')
#         return result
#     except Exception as error:
#         utils.remove_file(filename)
#         traceback_error = traceback.format_exc()
#         my_log.log_gemini_skills(f'run_script: {error}\n{traceback_error}\n\n{filename}\n{body}')
#         return f'{error}\n\n{traceback_error}'


# def run_script(filename: str, body: str) -> str:
#     """
#     Saves and runs a script in the shell, returning its output. This script has full access to files and network, there are no sandboxes.
#     Allowed file extensions are ".py" for Python and ".sh" for Bash. Do not add any shebang to the body.
#     The function will execute the code using: subprocess.check_output(f'./run_script_{filename}', shell=True, timeout=300)

#     Args:
#         filename: The name of the file to be created.
#         body: The content of the script to be executed.

#     Returns:
#         The output of the executed script.

#     Instructions:
#         1. Pass the filename with the extension (.py or .sh) to the 'filename' argument.
#         2. Pass the script content without the shebang (#!... ) to the 'body' argument.
#         3. If 'filename' ends with .py, the 'body' will be executed as a Python script.
#         4. If 'filename' ends with .sh, the 'body' will be executed as a Bash script.
#         5. The function will save the script to disk, make it executable, run it, and return the output.
#         6. If an error occurs during script execution, the function will return the error message.
#         7. After executing the script, it will be deleted from the disk.

#     Example:
#         filename = 'script.py'
#         body = '''
# import os
# print(os.getcwd())
# '''
#         result = run_script(filename, body)
#         print(result)

#     Or:

#         filename = 'script.sh'
#         body = '''
# echo "Hello, world!"
# ls -l
# '''
#         result = run_script(filename, body)
#         print(result)

#     Important:
#     - Ensure the script content in `body` is properly formatted and does not contain syntax errors.
#     - Be cautious when running scripts with network access, as they have full access to the network.
#     - If the script generates files, make sure to handle them appropriately (e.g., delete them after use).
#     - Double quotes inside the script body are escaped
#     """
#     body = decode_string(body)
#     filename = 'run_script_' + filename
#     ext = utils.get_file_ext(filename)
#     if ext.startswith('.'):
#         ext = ext[1:]

#     if ext == 'py':
#         if not body.split()[0].startswith('#!/'):
#             body = '#!/usr/bin/env python3\n\n' + body
#     elif ext == 'sh':
#         if not body.split()[0].startswith('#!/'):
#             body = '#!/bin/bash\n\n' + body

#     # Escape only double quotes inside the string
#     body = body.replace('"', '\\"')

#     my_log.log_gemini_skills(f'run_script {filename}\n\n{body}')

#     try:
#         with open(filename, 'w') as f:
#             f.write(body)
#         os.chmod(filename, 0o777)
#         try:
#             output = subprocess.check_output(f'./{filename}', shell=True, timeout=300, stderr=subprocess.STDOUT)
#         except subprocess.CalledProcessError as error:
#             if not error.output:
#                 output = str(error).encode('utf-8', errors='replace')
#             else:
#                 output = error.output
#         utils.remove_file(filename)
#         result = output.decode('utf-8', errors='replace')
#         my_log.log_gemini_skills(f'run_script: {result}')
#         return result
#     except Exception as error:
#         utils.remove_file(filename)
#         traceback_error = traceback.format_exc()
#         my_log.log_gemini_skills(f'run_script: {error}\n{traceback_error}\n\n{filename}\n{body}')
#         return f'{error}\n\n{traceback_error}'


# def run_script(filename: str, body: str) -> str:
#     """
#     Saves and runs a script in the shell, returning its output. This script has full access to files and network, there are no sandboxes.
#     Allowed file extensions are ".py" for Python and ".sh" for Bash. Do not add any shebang to the body.
#     The function will execute the code using: subprocess.check_output(f'./run_script_{filename}', shell=True, timeout=300)

#     Args:
#         filename: The name of the file to be created.
#         body: The content of the script to be executed.

#     Returns:
#         The output of the executed script.

#     Instructions:
#         1. Pass the filename with the extension (.py or .sh) to the 'filename' argument.
#         2. Pass the script content without the shebang (#!... ) to the 'body' argument.
#         3. If 'filename' ends with .py, the 'body' will be executed as a Python script.
#         4. If 'filename' ends with .sh, the 'body' will be executed as a Bash script.
#         5. The function will save the script to disk, make it executable, run it, and return the output.
#         6. If an error occurs during script execution, the function will return the error message.
#         7. After executing the script, it will be deleted from the disk.

#     Example:
#         filename = 'script.py'
#         body = '''
# import os
# print(os.getcwd())
# '''
#         result = run_script(filename, body)
#         print(result)

#     Or:

#         filename = 'script.sh'
#         body = '''
# echo "Hello, world!"
# ls -l
# '''
#         result = run_script(filename, body)
#         print(result)

#     Important:
#     - Ensure the script content in `body` is properly formatted and does not contain syntax errors.
#     - Be cautious when running scripts with network access, as they have full access to the network.
#     - If the script generates files, make sure to handle them appropriately (e.g., delete them after use).
#     - Double quotes inside the script body are escaped
#     """
#     body = decode_string(body)
#     filename = 'run_script_' + filename
#     ext = utils.get_file_ext(filename)
#     if ext.startswith('.'):
#         ext = ext[1:]

#     if ext == 'py':
#         if not body.split()[0].startswith('#!/'):
#             body = '#!/usr/bin/env python3\n\n' + body
#         # Escape double quotes only for Python scripts
#         body = body.replace('"', '\\"')
#     elif ext == 'sh':
#         if not body.split()[0].startswith('#!/'):
#             body = '#!/bin/bash\n\n' + body
#     # Replace \\n with \n after adding shebang
#     body = body.replace('\\\\n', '\\n')

#     my_log.log_gemini_skills(f'run_script {filename}\n\n{body}')

#     try:
#         with open(filename, 'w') as f:
#             f.write(body)
#         os.chmod(filename, 0o777)
#         try:
#             output = subprocess.check_output(f'./{filename}', shell=True, timeout=300, stderr=subprocess.STDOUT)
#         except subprocess.CalledProcessError as error:
#             if not error.output:
#                 output = str(error).encode('utf-8', errors='replace')
#             else:
#                 output = error.output
#         utils.remove_file(filename)
#         result = output.decode('utf-8', errors='replace')
#         my_log.log_gemini_skills(f'run_script: {result}')
#         return result
#     except Exception as error:
#         utils.remove_file(filename)
#         traceback_error = traceback.format_exc()
#         my_log.log_gemini_skills(f'run_script: {error}\n{traceback_error}\n\n{filename}\n{body}')
#         return f'{error}\n\n{traceback_error}'


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
            output = subprocess.check_output(f'{filename}', shell=True, timeout=300, stderr=subprocess.STDOUT)
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
    my_db.init(backup=False)
    my_groq.load_users_keys()
    # moscow_time = get_time_in_timezone("Europe/Moscow")
    # print(f"Time in Moscow: {moscow_time}")

    # print(calc("(datetime.date(2025, 6, 1) - datetime.date.today()).days"))
    # print(calc("randint(10)+sqrt(1.4**2 + 1.5**2) * cos(pi/3)**2"))
    # print(calc('[str(i) for i in range(5000, 100000) if "2" in str(i) and "9" in str(i)][0:5]'))
    # print(calc("sum(int(digit) for digit in str(1420000000))"))
    # print(calc("[str(i) + str(j) + str(k) + str(l) + str(m) for i in range(9, 0, -1) for j in range(i - 1, 0, -1) for k in range(j - 1, 0, -1) for l in range(k - 1, 0, -1) for m in range(l - 1, 0, -1) if i + j + k + l + m == 26 and 0 not in (i, j, k, l, m) and 8 not in (i, j, k, l, m)]"))

    # text='''ls -l'''
    # print(run_script('test.sh', text))

    my_db.close()
