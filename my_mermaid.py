import glob
import os
import tempfile
import subprocess
import shutil
import threading

import my_log
import utils


LOCK = threading.Lock()


def clean_puppeteer_temp_dirs():
    """
    Удаляет временные папки 'puppeteer_dev_chrome_profile-*' из системной временной папки.
    """
    temp_dir = tempfile.gettempdir()
    dir_pattern = os.path.join(temp_dir, 'puppeteer_dev_chrome_profile-*')

    for d in glob.glob(dir_pattern):
        if os.path.isdir(d): # Убедимся, что это директория
            try:
                shutil.rmtree(d)
            except OSError as e:
                my_log.log2(f"my_mermaid:clean_puppeteer_temp_dirs: Ошибка при удалении папки {d}: {e}")


def generate_mermaid_png_bytes(diagram_text: str, puppeteer_config_path: str = "puppeteer-config.txt_json") -> bytes | str:
    """
    Генерирует диаграмму Mermaid в формате PNG и возвращает ее как байты.
    Для Linux, если переменная окружения PUPPETEER_EXECUTABLE_PATH не установлена,
    функция автоматически пытается найти chrome-headless-shell в стандартном кеше Puppeteer
    (~/.cache/puppeteer/) и установить ее.
    Использует пайпы для ввода/вывода, избегая промежуточных файлов диаграммы.

    Args:
        diagram_text: Строка с текстом диаграммы Mermaid.
        puppeteer_config_path: Путь к файлу puppeteer-config.json,
                               содержащему аргументы для Puppeteer (например, "--no-sandbox").

    Returns:
        Байты PNG-изображения в случае успеха.
        Строка с сообщением об ошибке, если генерация диаграммы не удалась,
        или если 'mmdc' не найден.
    """
    with LOCK:

        cmd = "mmdc"
        is_linux = False
        is_windows = False 

        platform_name = utils.platform().lower()
        if 'windows' in platform_name:
            cmd = "mmdc.cmd"
            is_windows = True
        elif 'linux' in platform_name:
            is_linux = True

        # Если PUPPETEER_EXECUTABLE_PATH не установлен, пытаемся его найти
        if 'PUPPETEER_EXECUTABLE_PATH' not in os.environ:
            home_dir = os.path.expanduser('~') # Домашняя директория пользователя, одинаково для Linux и Windows

            if is_linux:
                executable_pattern = os.path.join(home_dir, '.cache', 'puppeteer', 'chrome-headless-shell', '*', '*', 'chrome-headless-shell')

                my_log.log2(f"my_mermaid:generate_mermaid_png_bytes: PUPPETEER_EXECUTABLE_PATH не задан (Linux). Ищем в: {executable_pattern}")
                potential_executables = glob.glob(executable_pattern)

                if potential_executables:
                    os.environ['PUPPETEER_EXECUTABLE_PATH'] = potential_executables[0]
                    my_log.log2(f"my_mermaid:generate_mermaid_png_bytes: PUPPETEER_EXECUTABLE_PATH установлен: {potential_executables[0]}")
                else:
                    my_log.log2("my_mermaid:generate_mermaid_png_bytes: chrome-headless-shell не найден в стандартных путях Puppeteer для Linux.")
            elif is_windows:
                my_log.log2(f"my_mermaid:generate_mermaid_png_bytes: PUPPETEER_EXECUTABLE_PATH не задан (Windows). Пытаемся найти chrome-headless-shell.exe или chrome.exe.")

                # Приоритет 1: Собственный кеш Puppeteer для chrome-headless-shell.exe (в ~/.cache)
                puppeteer_cache_pattern = os.path.join(home_dir, '.cache', 'puppeteer', 'chrome-headless-shell', '*', '*', 'chrome-headless-shell.exe')

                my_log.log2(f"my_mermaid:generate_mermaid_png_bytes: Ищем chrome-headless-shell.exe в кеше Puppeteer: {puppeteer_cache_pattern}")
                potential_executables = glob.glob(puppeteer_cache_pattern)

                if potential_executables:
                    os.environ['PUPPETEER_EXECUTABLE_PATH'] = potential_executables[0]
                    my_log.log2(f"my_mermaid:generate_mermaid_png_bytes: PUPPETEER_EXECUTABLE_PATH установлен из кеша Puppeteer: {potential_executables[0]}")

                # Приоритет 2: Стандартные пути установки Google Chrome, если не найдено в кеше Puppeteer
                if 'PUPPETEER_EXECUTABLE_PATH' not in os.environ:
                    my_log.log2("my_mermaid:generate_mermaid_png_bytes: chrome-headless-shell.exe не найден в кеше Puppeteer. Ищем chrome.exe в стандартных путях Google Chrome.")
                    chrome_paths = [
                        os.path.join(os.environ.get('PROGRAMFILES', 'C:\\Program Files'), 'Google', 'Chrome', 'Application', 'chrome.exe'),
                        os.path.join(os.environ.get('PROGRAMFILES(X86)', 'C:\\Program Files (x86)'), 'Google', 'Chrome', 'Application', 'chrome.exe'),
                        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google', 'Chrome', 'Application', 'chrome.exe')
                    ]

                    found_chrome = False
                    for path in chrome_paths:
                        if os.path.exists(path):
                            os.environ['PUPPETEER_EXECUTABLE_PATH'] = path
                            my_log.log2(f"my_mermaid:generate_mermaid_png_bytes: PUPPETEER_EXECUTABLE_PATH установлен из стандартного пути Chrome: {path}")
                            found_chrome = True
                            break

                    if not found_chrome:
                        my_log.log2("my_mermaid:generate_mermaid_png_bytes: chrome-headless-shell.exe или chrome.exe не найдены в стандартных путях Puppeteer или Chrome.")
        else:
            pass
            # my_log.log2(f"my_mermaid:generate_mermaid_png_bytes: PUPPETEER_EXECUTABLE_PATH уже задан: {os.environ['PUPPETEER_EXECUTABLE_PATH']}")

        command = [cmd, "-e", "png", "-i", "-", "-o", "-", "-s", "2", "-p", puppeteer_config_path]

        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ.copy()
            )

            stdout_data, stderr_data = process.communicate(input=diagram_text.encode('utf-8'))

            clean_puppeteer_temp_dirs()

            if process.returncode != 0:
                env_info = f"PUPPETEER_EXECUTABLE_PATH: {os.environ.get('PUPPETEER_EXECUTABLE_PATH', 'Не задан')}"
                error_message = stderr_data.decode('utf-8').strip()
                my_log.log2(f"my_mermaid:generate_mermaid_png_bytes: Ошибка subprocess (код {process.returncode}): {error_message}. {env_info}")
                return f"Ошибка при генерации диаграммы: {error_message}. {env_info}"
# my_log.log2("my_mermaid:generate_mermaid_png_bytes: Диаграмма успешно сгенерирована.")
            return stdout_data
        except FileNotFoundError:
            my_log.log2("my_mermaid:generate_mermaid_png_bytes: Ошибка: mmdc не найден.")
            return "mmdc не найден. Убедись, что mermaid-cli установлен и доступен в PATH."
        except Exception as e:
            my_log.log2(f"my_mermaid:generate_mermaid_png_bytes: Неизвестная ошибка: {e}")
            return f"Неизвестная ошибка: {e}"


if __name__ == "__main__":
    mermaid_diagram = """
graph TD
    subgraph Инициализация Системы
        A[Старт Приложения] --> B(Загрузка Конфигурации)
        B --> C{Проверка Подключения к БД?}
        C -- Да --> D[Подключение к Базе Данных]
        C -- Нет --> E(Сообщение об Ошибке и Выход)
        D --> F[Инициализация Модулей]
    end

    subgraph Обработка Запросов Пользователя
        G[Ожидание Входящих Запросов]
        F --> G

        G --> H{Тип Запроса?}
        H -- Запрос Данных --> I[Валидация Запроса]
        H -- Запись Данных --> J[Валидация Запроса на Запись]
        H -- Отчет --> K[Генерация Отчета]
        H -- Неизвестный --> L(Ошибка: Неизвестный Запрос)
    end

    subgraph Модуль Обработки Данных
        I --> M(Извлечение Данных из БД)
        J --> N(Запись Данных в БД)

        M --> P{Данные Найдены?}
        P -- Да --> Q[Форматирование Результата]
        P -- Нет --> R(Сообщение: Данные не найдены)

        N --> S{Запись Успешна?}
        S -- Да --> T(Подтверждение Записи)
        S -- Нет --> U(Ошибка Записи: Откат Транзакции)
    end

    subgraph Модуль Генерации Отчетов
        K --> V(Сбор Данных для Отчета)
        V --> W[Анализ и Агрегация]
        W --> X(Генерация PDF/Excel Отчета)
        X --> Y(Отправка Отчета Пользователю)
    end

    Q --> Z(Отправка Ответа Пользователю)
    R --> Z
    T --> Z
    U --> Z
    L --> Z

    E --- Завершение ---> END_APP(Завершение Приложения)
    Z --- Продолжение ---> G
    """
    try:
        png_bytes = generate_mermaid_png_bytes(mermaid_diagram)
        if isinstance(png_bytes, bytes):
            with open(r"c:\Users\user\Downloads\output.png", "wb") as f:
                f.write(png_bytes)
            print("Диаграмма успешно сохранена в output.png")
        else:
            print(f"Ошибка: {png_bytes}")
    except Exception as e:
        print(f"Неизвестная ошибка в main: {e}")
