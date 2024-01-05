#!/usr/bin/env python3


import time
import threading
import traceback

import random
import re
import requests
from sqlitedict import SqliteDict

import cfg
import my_dic
import my_log
import my_proxy


BIG_LOCK = threading.Lock()


# do not use 1 same key at the same time for different requests
LOCKS = {}

LOCK_STORAGE = threading.Lock()

# {0: cookie0, 1: cookie1, ...}
COOKIE = SqliteDict('db/bing_cookie.db', autocommit=True)
# {cookie:datetime, ...}
# cookies frozen for a day
COOKIE_SUSPENDED = SqliteDict('db/bing_cookie_suspended.db', autocommit=True)
SUSPEND_COOKIE_TIME = 60 * 60 * 1

# storage of requests that Bing rejected, they cannot be repeated
BAD_IMAGES_PROMPT = SqliteDict('db/bad_images_prompt.db', autocommit=True)

# proxy pool {'proxies': list of proxies}
PROXY_POOL = SqliteDict('db/bing_proxy_pool.db', autocommit=True)
REMOVED_PROXY = [] # list of removed proxies
GOOD_PROXY = my_dic.PersistentList('db/bing_good_proxy.pkl') # list of working proxies
PROXY_POOL_MAX = 30
PROXY_POOL_MAX_WORKERS = 50


BING_URL = "https://www.bing.com"


def get_header() -> str:
    """
    Get the header for HTTP requests with random ipv4 x-forwarded-for address.
    
    Returns:
        str: The header for the HTTP requests.
    """
    while 1:
        random_ip = ".".join(str(random.randint(0, 255)) for _ in range(4))
        if not random_ip.startswith(('192.168.','10.','172.16.')):
            break
    HEADERS = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.77",
        "accept-language": "en,zh-TW;q=0.9,zh;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "cache-control": "max-age=0",
        "content-type": "application/x-www-form-urlencoded",
        "referrer": "https://www.bing.com/images/create/",
        "origin": "https://www.bing.com",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/119.0.0.0 "
                    "Safari/537.36 "
                    "Edg/119.0.0.0",
        "x-forwarded-for": random_ip,
    }
    return HEADERS


def get_images(prompt: str,
               u_cookie: str,
               proxy: str = None,
               timeout: int = 200,
               max_generate_time_sec: int = 60):
    """
    Retrieves a list of normal image links from Bing search based on a given prompt.
    
    Args:
        prompt (str): The search prompt to use for retrieving images.
        u_cookie (str): The user cookie for authentication.
        proxy (str, optional): The proxy server to use for the request. Defaults to None.
        timeout (int, optional): The timeout duration for the request in milliseconds. Defaults to 200.
        max_generate_time_sec (int, optional): The maximum time in seconds to wait for image generation. Defaults to 60.
        
    Raises:
        Exception: If the prompt is being reviewed by Bing.
        Exception: If the prompt has been blocked by Bing.
        Exception: If the language of the prompt is unsupported.
        Exception: If the request for image creation fails.
        TimeoutError: If the request times out while waiting for image generation.
        Exception: If no images are found in the search results.
        Exception: If any of the retrieved image links are in the list of bad images.
        
    Returns:
        list: A list of normal image links (URLs) from Bing search.
    """

    TIMEOUT2 = 5

    url_encoded_prompt = requests.utils.quote(prompt)

    payload = f"q={url_encoded_prompt}&qs=ds"

    url = f"{BING_URL}/images/create?q={url_encoded_prompt}&rt=4&FORM=GUH2CR"

    session = requests.Session()
    if proxy:
        session.proxies.update({'http': proxy, 'https': proxy})
    session.headers = get_header()
    session.cookies.set("_U", u_cookie)

    response = session.post(
        url,
        allow_redirects=False,
        data=payload,
        timeout=TIMEOUT2,
    )
    # check for content waring message
    if "this prompt is being reviewed" in response.text.lower():
        raise Exception("error1_being_reviewed_prompt")
    if "this prompt has been blocked" in response.text.lower():
        raise Exception('error1_blocked_prompt')
    if "we're working hard to offer image creator in more languages" in response.text.lower():
        raise Exception('error1_unsupported_lang')
    if response.status_code != 302:
        url = f"{BING_URL}/images/create?q={url_encoded_prompt}&rt=3&FORM=GUH2CR"
        response = session.post(url, allow_redirects=False, timeout=TIMEOUT2)
        if response.status_code != 302:
            Exception ('Image create failed pls check cookie or old image still creating')

    redirect_url = response.headers["Location"].replace("&nfy=1", "")
    request_id = redirect_url.split("id=")[-1]
    session.get(f"{BING_URL}{redirect_url}")

    polling_url = f"{BING_URL}/images/create/async/results/{request_id}?q={url_encoded_prompt}"

    start_wait = time.time()
    time_sec = 0
    while True:
        if int(time.time() - start_wait) > timeout:
            raise Exception('error2_timeout')
        response = session.get(polling_url)
        if response.status_code != 200:
            raise Exception('error2_noresults')
        if not response.text or response.text.find("errorMessage") != -1:
            time.sleep(1)
            time_sec = time_sec + 1
            if time_sec >= max_generate_time_sec:
                raise TimeoutError("Out of generate time")
            continue
        else:
            break
    # Use regex to search for src=""
    image_links = re.findall(r'src="([^"]+)"', response.text)
    # Remove size limit
    normal_image_links = [link.split("?w=")[0] for link in image_links]
    # Remove duplicates
    normal_image_links = list(set(normal_image_links))

    # Bad images
    bad_images = [
        "https://r.bing.com/rp/in-2zU3AJUdkgFe7ZKv19yPBHVs.png",
        "https://r.bing.com/rp/TX9QuO3WzcCJz1uaaSwQAz39Kb0.jpg",
    ]
    for img in normal_image_links:
        if img in bad_images:
            raise Exception("error1_Bad images")
    # No images
    if not normal_image_links:
        raise Exception('error_no_images')

    normal_image_links = [x for x in normal_image_links if not x.startswith('https://r.bing.com/')]
    time.sleep(5)
    return normal_image_links


def gen_images(query: str, custom_proxies = None, remove_auto_proxies = False) -> list:
    """
    Generate images based on the given query.

    Args:
        query (str): The query to generate images for.

    Returns:
        list: A list of generated images.

    Raises:
        Exception: If there is an error getting the images.

    """
    if query in BAD_IMAGES_PROMPT:
        my_log.log2(f'get_images: {query} is in BAD_IMAGES_PROMPT')
        return []

    cookies = []

    with LOCK_STORAGE:
        # unsuspend
        unsuspend = [x[0] for x in COOKIE_SUSPENDED.items() if time.time() > x[1] + SUSPEND_COOKIE_TIME]
        for x in unsuspend:
            COOKIE[time.time()] = x
        for x in COOKIE.items():
            cookie = x[1].strip()
            cookies.append(cookie)

    random.shuffle(cookies)
    for cookie in cookies:
        if cookie not in LOCKS:
            LOCKS[cookie] = threading.Lock()
        with LOCKS[cookie]:
            if custom_proxies:
                p_list = custom_proxies
            else:
                try:
                    p_list = cfg.bing_proxy
                except AttributeError:
                    p_list = []
            if p_list:
                shuffled_proxy = p_list[:]
                random.shuffle(shuffled_proxy)
                # good proxy first
                random.shuffle(GOOD_PROXY)
                shuffled_proxy = list(set(GOOD_PROXY + shuffled_proxy))
                # for proxy in cfg.bing_proxy:
                for proxy in shuffled_proxy:
                    try:
                        r = get_images(query, cookie, proxy)
                        if r:
                            if proxy not in GOOD_PROXY:
                                GOOD_PROXY.append(proxy)
                            return r
                    except Exception as error:
                        # print(error)
                        if 'location' in str(error):
                            my_log.log2(f'gen_images:suspend_cookie: {error} Cookie: {cookie} Proxy: {proxy}')
                            with LOCK_STORAGE:
                                for z in COOKIE.items():
                                    if z[1] == cookie:
                                        del COOKIE[z[0]]
                                        COOKIE_SUSPENDED[z[1]] = time.time()
                                        break
                        else:
                            if remove_auto_proxies and not str(error).startswith('error'):
                                if proxy in GOOD_PROXY:
                                    GOOD_PROXY.remove(proxy)
                                else:
                                    PROXY_POOL['proxies'] = [x for x in PROXY_POOL['proxies'] if x != proxy]
                                    REMOVED_PROXY.append(proxy)
                                    print(f'proxies left: {len(PROXY_POOL["proxies"])} removed: {len(REMOVED_PROXY)}')
                            my_log.log2(f'gen_images: {error}\n\nQuery: {query}\n\nCookie: {cookie}\n\nProxy: {proxy}')
                        if str(error).startswith('error1'):
                            BAD_IMAGES_PROMPT[query] = True
                            return []
            else:
                try:
                    return get_images(query, cookie)
                except Exception as error:
                    if 'location' in str(error):
                            my_log.log2(f'gen_images: {error} Cookie: {cookie}')
                            with LOCK_STORAGE:
                                for z in COOKIE.items():
                                    if z[1] == cookie:
                                        del COOKIE[z[0]]
                                        COOKIE_SUSPENDED[z[1]] = time.time()
                                        break
                    else:
                        my_log.log2(f'gen_images: {error}\n\nQuery: {query}\n\nCookie: {cookie}')
                    if str(error).startswith('error1'):
                        BAD_IMAGES_PROMPT[query] = True
                        return []
    return []


def probe_proxy(proxy: str) -> str:
    """
    Sends a request to a proxy server and returns the proxy if the request is successful.

    Args:
        proxy (str): The proxy server to send the request to.

    Returns:
        str: The proxy server if the request is successful, otherwise an empty string.
    """
    prompts = ['собака лает на луну',
 'железный гвоздь на тарелке',
 'кошка в шляпе',
 'слон на велосипеде',
 'рыба в дереве',
 'птица в клетке',
 'человек с крыльями',
 'робот играет в футбол',
 'инопланетянин ест мороженое',
 'дракон в облаках',
 'русалка в океане',
 'призрак в замке',
 'фея в лесу',
 'единорог в поле',
 'зомби в городе',
 'вампир в гробу',
 'ведьма на метле',
 'волшебник с волшебной палочкой',
 'супергерой спасает мир',
 'злодей планирует захватить мир',
 'лев, сидящий на троне',
 'олень, пьющий воду из озера',
 'бабочка, сидящая на цветке',
 'пчела, собирающая нектар с цветка',
 'муравей, несущий лист',
 'паук, плетущий паутину',
 'змея, ползущая по дереву',
 'ящерица, сидящая на камне',
 'лягушка, сидящая на лилии',
 'рыба, плавающая в аквариуме',
 'птица, летящая в небе',
 'облако в форме сердца',
 'дерево с дуплом',
 'цветок с росой',
 'гора с заснеженной вершиной',
 'озеро с лебедями',
 'река с течением',
 'море с волнами',
 'пляж с песком и ракушками',
 'лес с деревьями и кустами',
 'поле с цветами и травой',
 'луна в ночном небе',
 'звезды в космосе',
 'солнце в ясный день',
 'радуга после дождя',
 'рыцарь в доспехах сражается с драконом',
 'пират на корабле ищет сокровища',
 'ковбой верхом на лошади скачет по прерии',
 'индеец в головном уборе танцует вокруг костра',
 'гейша в кимоно играет на сямисэне',
 'сумоист в набедренной повязке борется на арене',
 'самурай с катаной сражается с ниндзя',
 'монах в оранжевых одеждах медитирует в храме',
 'йог в позе лотоса занимается йогой',
 'балерина в пачке танцует на сцене',
 'художник рисует картину в своей студии',
 'писатель пишет книгу за своим письменным столом',
 'музыкант играет на гитаре в концертном зале',
 'певец поет песню на сцене',
 'актер играет роль в пьесе',
 'режиссер снимает фильм на съемочной площадке',
 'оператор снимает видеокамерой репортаж',
 'фотограф фотографирует модель в фотостудии',
 'дизайнер создает одежду в своей мастерской',
 'архитектор проектирует здание за своим рабочим столом',
 'инженер строит мост на стройплощадке',
 'врач лечит пациента в больнице',
 'учитель учит детей в школе',
 'полицейский патрулирует город',
 'пожарный тушит пожар',
 'спасатель спасает людей из горящего здания',
 'военный сражается на войне',
 'бизнесмен заключает сделку в офисе',
 'фермер собирает урожай на своем поле',
 'рабочий трудится на заводе',
 'продавец продает товар в магазине',
 'официант обслуживает клиентов в ресторане',
 'парикмахер стрижет волосы клиенту',
 'массажист делает массаж клиенту',
 'косметолог делает маникюр клиенту',
 'таксист везет пассажиров в такси',
 'автобус перевозит пассажиров по городу',
 'поезд перевозит пассажиров между городами',
 'самолет перевозит пассажиров между странами',
 'корабль перевозит грузы по морю',]

    prompt = random.choice(prompts)
    u_cookie = '123'  # random.choice(COOKIE)
    # timeout = 200
    timeout = 30

    url_encoded_prompt = requests.utils.quote(prompt)
    payload = f"q={url_encoded_prompt}&qs=ds"
    url = f"{BING_URL}/images/create?q={url_encoded_prompt}&rt=4&FORM=GUH2CR"

    session = requests.Session()
    session.proxies.update({'http': proxy, 'https': proxy})
    session.headers = get_header()
    session.cookies.set("_U", u_cookie)

    try:
        response = session.post(
            url,
            allow_redirects=False,
            data=payload,
            timeout=timeout,
        )
    except requests.exceptions.ProxyError:
        return ''
    except requests.exceptions.ConnectTimeout:
        return ''
    except requests.exceptions.ConnectionError:
        return ''
    except requests.exceptions.ReadTimeout:
        return ''
    except requests.exceptions.ChunkedEncodingError:
        return ''
    except Exception as unknown:
        error_traceback = traceback.format_exc()
        my_log.log2(f'bing_img:probe: {str(unknown)}\n\n{error_traceback}')
        return ''

    # # check for content waring message
    # if "this prompt is being reviewed" in response.text.lower():
    #     raise Exception("error1_being_reviewed_prompt")
    # if "this prompt has been blocked" in response.text.lower():
    #     raise Exception('error1_blocked_prompt')
    # if "we're working hard to offer image creator in more languages" in response.text.lower():
    #     raise Exception('error1_unsupported_lang')

    if response.status_code in (200, 302):
        return proxy

    # if response.status_code != 302:
    #     url = f"{BING_URL}/images/create?q={url_encoded_prompt}&rt=3&FORM=GUH2CR"
    #     response = session.post(url, allow_redirects=False, timeout=timeout)
    #     if response.status_code != 302:
    #         # Exception ('Image create failed pls check cookie or old image still creating')
    #         return False

    return ''


def run_proxy_pool_daemon():
    """
    Run a daemon thread that continuously adds working proxies to the proxy pool.

    This function runs in an infinite loop and checks the length of the PROXY_POOL. If the length is less than the maximum allowed (PROXY_POOL_MAX), it calls the `find_working_proxies` function from the `my_proxy` module to find working proxies. The `probe_proxy` parameter is passed to the `find_working_proxies` function, along with `max_workers=100` and `max_results=10`.

    The working proxies returned by the `find_working_proxies` function are then added to the `PROXY_POOL['proxies']` list using the `extend` method. The function then waits for 2 seconds before checking the PROXY_POOL length again.

    This process continues indefinitely, with the function sleeping for 2 seconds between each iteration of the loop.

    Parameters:
        None

    Returns:
        None
    """
    def run_proxy_pool_daemon_thread():
        """
        Run a daemon thread that continuously adds working proxies to the proxy pool.

        This function runs in an infinite loop and checks the length of the PROXY_POOL. If the length is less than the maximum allowed (PROXY_POOL_MAX), it calls the `find_working_proxies` function from the `my_proxy` module to find working proxies. The `probe_proxy` parameter is passed to the `find_working_proxies` function, along with `max_workers=100` and `max_results=10`.

        The working proxies returned by the `find_working_proxies` function are then added to the `PROXY_POOL['proxies']` list using the `extend` method. The function then waits for 2 seconds before checking the PROXY_POOL length again.

        This process continues indefinitely, with the function sleeping for 2 seconds between each iteration of the loop.

        Parameters:
            None

        Returns:
            None
        """
        if not 'proxies' in PROXY_POOL:
            PROXY_POOL['proxies'] = []
        while 1:
            if len(PROXY_POOL['proxies']) < PROXY_POOL_MAX:
                proxies = my_proxy.find_working_proxies(probe_proxy, max_workers=PROXY_POOL_MAX_WORKERS, max_results=10)
                proxies = [x for x in proxies if x not in REMOVED_PROXY]
                PROXY_POOL['proxies'] = PROXY_POOL['proxies'] + proxies
                PROXY_POOL['proxies'] = list(set(PROXY_POOL['proxies']))
                time.sleep(2)
            time.sleep(2)
    thread = threading.Thread(target=run_proxy_pool_daemon_thread)
    thread.start()


def gen_images_with_proxy_pool(prompt: str):
    if not 'proxies' in PROXY_POOL:
        PROXY_POOL['proxies'] = []
    while len(PROXY_POOL['proxies']) < 1:
        time.sleep(2)

    ps = PROXY_POOL['proxies'][:]

    return gen_images(prompt, ps, remove_auto_proxies = True)

if __name__ == '__main__':

    run_proxy_pool_daemon()

    p = 'большой дымящийся пирог в руке в маленькой руке'
    images = gen_images_with_proxy_pool(p)
    if images:
        print(images)
