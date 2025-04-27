# pip install -U playwright
# playwright install chromium


import time
import traceback
import threading
import urllib.parse

import cachetools.func
from playwright.sync_api import sync_playwright

import my_log


LOCK = threading.Lock()


def is_local_url(url: str) -> bool:
    try:
        parsed_url = urllib.parse.urlparse(url)
        # Проверяем схемы, которые могут указывать на локальные файлы
        if parsed_url.scheme in ['file', 'ftp']:
            return True
        # Проверяем хосты, которые обычно локальные
        # Список можно расширить!
        local_hosts = ['localhost', '127.0.0.1']
        if parsed_url.hostname in local_hosts:
            return True
        # Можно добавить проверку на диапазоны частных IP (10.x.x.x, 192.168.x.x, 172.16-31.x.x)
        # Это сложнее, но надежнее
        # ...
        return False
    except Exception:
        # Если URL не парсится, считаем его подозрительным или просто пропускаем
        # В данном случае, наверное, лучше пропустить, если не уверен
        return False


@cachetools.func.ttl_cache(maxsize=10, ttl=10 * 60)
def gettext(url: str, timeout: int = 30) -> str:
    '''
    Пытаемся получить весь текст из тела страницы
    '''

    # Проверка на входе
    if is_local_url(url):
        my_log.log_playwright(f'Blocked access to initial local URL: {url}')
        return "" # Блокируем сразу

    global LOCK
    with LOCK:
        with sync_playwright() as p:
            all_text = ''
            try:
                # Запускаем браузер в безголовом режиме
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()


                def handle_route(route):
                    request_url = route.request.url
                    if is_local_url(request_url):
                        my_log.log_playwright(f'Blocked internal access to local URL: {request_url}')
                        route.abort() # Блокируем этот запрос
                    else:
                        route.continue_() # Разрешаем запрос

                # Перехватываем все запросы (**/*) и применяем нашу логику
                page.route('**/*', handle_route)


                page.goto(url)

                # Ждем немного, чтобы страница загрузилась
                start_time = time.time()
                page.wait_for_load_state("networkidle", timeout=timeout * 1000)
                timeout -= time.time() - start_time

                # Пытаемся получить весь текст из тела страницы
                all_text = page.inner_text('body', timeout=timeout * 1000)
                page.close()
            except Exception as error:
                traceback_error = traceback.format_exc()
                my_log.log_playwright(f'{error}\n{url} {timeout}\n{traceback_error}')
            finally:
                browser.close()

    return all_text


if __name__ == '__main__':
    print(gettext('https://www.opennet.ru/opennews/art.shtml?num=63126'))
    print(gettext('https://www.opennet.ru/opennews/art.shtml?num=63127'))
    print(gettext('https://www.youtube.com/watch?v=dQw4w9WgXcQ'))
