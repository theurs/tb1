#!/usr/bin/env python3
# pip install Proxy-List-Scrapper


import random
import time
import threading
import concurrent.futures

import requests
from sqlitedict import SqliteDict
from Proxy_List_Scrapper import Scrapper

import my_log


# do not get new proxies if they are less than 1 hour old
# {proxies: list of cashed proxies, time: time of last update}
cache = SqliteDict('db/proxy_cache.db', autocommit=True)
cache_lock = threading.Lock()
MAX_CACHE_TIME = 3600*4


def get_proxies():
    """
    Retrieves a list of proxies from multiple sources.

    Returns:
        list: A list of proxy URLs.
    """
    with cache_lock:
        if 'proxies' in cache and 'time' in cache:
            if time.time() - cache['time'] < MAX_CACHE_TIME:
                return cache['proxies']

    try:
        scrapper = Scrapper(category='ALL', print_err_trace=False)
        data = scrapper.getProxies()
        proxies = [f'http://{x.ip}:{x.port}' for x in data.proxies]

        p_socks5h = 'https://raw.githubusercontent.com/MuRongPIG/Proxy-Master/main/socks5.txt'
        p_socks4 = 'https://raw.githubusercontent.com/MuRongPIG/Proxy-Master/main/socks4.txt'
        p_http = 'https://raw.githubusercontent.com/MuRongPIG/Proxy-Master/main/http.txt'

        try:
            p_socks5h = requests.get(p_socks5h, timeout=60).text.split('\n')
            p_socks5h = [f'socks5h://{x}' for x in p_socks5h if x]
            p_socks4 = requests.get(p_socks4, timeout=60).text.split('\n')
            p_socks4 = [f'socks4://{x}' for x in p_socks4 if x]
            p_http = requests.get(p_http, timeout=60).text.split('\n')
            p_http = [f'http://{x}' for x in p_http if x]
            proxies += p_socks5h + p_socks4 + p_http
            random.shuffle(proxies)
        except Exception as error:
            my_log.log2(f'my_proxy:get_proxies: {error}')
    except Exception as error:
        my_log.log2(f'my_proxy:get_proxies: {error}')

    with cache_lock:
        cache['proxies'] = proxies
        cache['time'] = time.time()

    return proxies


def find_working_proxies(probe_function, max_workers: int = 100, max_results: int = 20):
    """
    Find working proxies using a probe function.

    Parameters:
        probe_function (function): The function to probe the proxies.
        max_workers (int, optional): The maximum number of workers for the thread pool. Defaults to 100.
        max_results (int, optional): The maximum number of results to return. Defaults to 20.

    Returns:
        list: A list of working proxies.
    """
    proxies = get_proxies()
    random.shuffle(proxies)
    n = 0
    maxn = len(proxies)
    step = max_workers
    results = []

    while n < maxn:
        if len(results) >= max_results:
            break
        step = max_workers
        chunk = proxies[n:n+step]
        n += step
        print(f'Proxies found: {len(results)} (processing {n} of {maxn})')
        with concurrent.futures.ThreadPoolExecutor(max_workers=step) as executor:
            futures = [executor.submit(probe_function, proxy) for proxy in chunk]
            for future in futures:
                r = future.result()
                if r:
                    results.append(r)
                    if len(results) >= max_results:
                        break
    return results[:max_results]


if __name__ == '__main__':
    print(get_proxies())