#!/usr/bin/env python3
# pip install cryptocompare

import cachetools.func
import math
import decimal
import numbers
import numpy
import numpy as np
import random
import re
import requests
import traceback
from math import *
from decimal import *
from numbers import *

# it will import word random and broke code
# from random import *
from random import betavariate, choice, choices, expovariate, gammavariate, gauss, getrandbits, getstate, lognormvariate, normalvariate, paretovariate, randbytes, randint, randrange, sample, seed, setstate, shuffle, triangular, uniform, vonmisesvariate, weibullvariate

import cryptocompare
from geopy.geocoders import Nominatim

import cfg
import my_db
import my_google
import my_log
import my_sum


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
def search_google(query: str) -> str:
    '''Search Google for query, return texts of found web pages.
    It works slow, do not call it often.
    '''
    query = decode_string(query)
    my_log.log_gemini_skills(f'Google: {query}')
    try:
        r = my_google.search_v3(query, max_search=10, download_only=True)
        return r[:MAX_REQUEST]
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


def update_user_profile(name: str,
                        location: str,
                        gender: str,
                        age: str,
                        language: str,
                        interests: str,
                        remember: str,
                        user_id: str) -> None:
    """
    Updates user profile info.

    Call this function if the user shares something about themselves,
    or if the user asks to remember some info.

    Important: Always send all info filled, use None for unknown data.

    Args:
        name: A string with user name.
        location: A string with user location.
        gender: A string with user gender.
        age: A string with user age example '18', '33'.
        language: A string with user language, 2 letters example 'ru', 'en', 'uk'.
        interests: A string with user interests.
        remember: A string with user asked to remember info.
                  Examples: name: Иван Иванов, location: Москва, gender: Мужской, age: 25, language: Русский, interests: Путешествия, фотография, музыка, remember: Моя кошка зовут Мурка
                            name: Дмитрий, location: , gender: , age: 28, language: Русский, interests: Программирование, видеоигры, remember: Купить подарок маме на день рождения
                            name: Алина, location: , gender: , age: , language: Русский, interests: , remember: Купить молоко и хлеб
        user_id: A string with the user ID, examples '[1234356345] [0]', '[-102754275491] [58644]', '[777000777] [0]'.
        If it's negative, then the user is not a person but a Telegram public chat.
    """
    name = decode_string(name)
    location = decode_string(location)
    gender = decode_string(gender)
    age = decode_string(age)
    language = decode_string(language)
    interests = decode_string(interests)
    remember = decode_string(remember)
    bio = f'name: {name}, location: {location}, gender: {gender}, age: {age}, language: {language}, interests: {interests}, remember: {remember}'
    my_log.log_gemini_skills(bio)
    my_db.set_user_property(user_id, 'persistant_memory', bio)


@cachetools.func.ttl_cache(maxsize=10, ttl = 60*60)
def calc(expression: str) -> str:
    '''Calculate expression with pythons eval(). Use it for all calculations.
    Available modules: decimal, math, numbers, numpy, random.
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
        'for', 'in', 'and', 'if', 'next',
        'digit',
        ]
    allowed_words += [x for x in dir(random) + dir(math) + dir(decimal) + dir(numbers) + dir(numpy) if not x.startswith('_')]
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


@cachetools.func.ttl_cache(maxsize=1, ttl = 60*60)
def get_cryptocurrency_rates():
    '''Get cryptocurrency rates.
    Return top 20 coins rates.
    '''
    try:
        my_log.log_gemini_skills('Cryptocurrency: get')
        if hasattr(cfg, 'CRYPTOCOMPARE_KEY') and cfg.CRYPTOCOMPARE_KEY:
            cryptocompare.cryptocompare._set_api_key_parameter(cfg.CRYPTOCOMPARE_KEY)
            r = cryptocompare.get_coin_list()
            coins = []
            for key in r.keys():
                if int(r[key]['SortOrder']) <= 20:
                    coins.append(r[key]['Name'])

            r = cryptocompare.get_price(coins, 'USD')
            my_log.log_gemini_skills(f'Cryptocurrency: {r}')
            return str(r)
        else:
            return ''
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log_gemini_skills(f'get_cryptocurrency_rates:Error: {error}\n\n{traceback_error}')
        return f'Error: {error}'


if __name__ == '__main__':
    pass
    # my_db.init()

    # print(calc("(1/5461512)**3 * (math.factorial(185)/(math.factorial(3)*math.factorial(128)))"))
    # print(calc("randint(10)+sqrt(1.4**2 + 1.5**2) * cos(pi/3)**2"))
    # print(calc('[str(i) for i in range(5000, 100000) if "2" in str(i) and "9" in str(i)][0:5]'))
    # print(calc("sum(int(digit) for digit in str(1420000000))"))
    # print(calc("dir(cfg)"))

    print(get_cryptocurrency_rates())

    # my_db.close()
