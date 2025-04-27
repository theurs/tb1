# pip install -U playwright
# playwright install chromium


import cachetools.func
import time
import traceback
import threading

from playwright.sync_api import sync_playwright

import my_log


LOCK = threading.Lock()


@cachetools.func.ttl_cache(maxsize=10, ttl=10 * 60)
def gettext(url: str, timeout: int = 30) -> str:
    '''
    Пытаемся получить весь текст из тела страницы
    '''
    global LOCK
    with LOCK:
        with sync_playwright() as p:
            all_text = ''
            try:
                # Запускаем браузер в безголовом режиме
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
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
