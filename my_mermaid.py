import glob
import os
import tempfile
import subprocess
import shutil
import threading
import xml.etree.ElementTree as ET
import re

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


def extract_width_from_svg(svg_content: str) -> int | None:
    """
    Извлекает ширину из SVG-строки.
    Приоритет: viewBox, затем width (если указан в px), затем max-width из style.
    """
    try:
        root = ET.fromstring(svg_content)

        # 1. Приоритет: Попытка получить ширину из атрибута 'viewBox'
        # viewBox обычно имеет формат "min-x min-y width height"
        viewbox_str = root.get('viewBox')
        if viewbox_str:
            parts = viewbox_str.split()
            if len(parts) == 4:
                try:
                    # Третий элемент - это ширина. Конвертируем в float, затем в int.
                    return int(float(parts[2])) 
                except ValueError:
                    my_log.log2(f"my_mermaid:extract_width_from_svg: Некорректный формат ширины в viewBox: {parts[2]}")
                    # Продолжаем поиск, если парсинг viewBox не удался
            else:
                my_log.log2(f"my_mermaid:extract_width_from_svg: Некорректное количество частей в viewBox: {viewbox_str}")

        # 2. Попытка получить ширину из атрибута 'width' (только если это пиксельное значение)
        width_str = root.get('width')
        if width_str:
            if width_str.endswith('px'):
                try:
                    return int(float(width_str.replace('px', '')))
                except ValueError:
                    my_log.log2(f"my_mermaid:extract_width_from_svg: Некорректный формат ширины в атрибуте width (px): {width_str}")
                    # Продолжаем поиск, если парсинг width (px) не удался
            elif width_str == '100%':
                my_log.log2("my_mermaid:extract_width_from_svg: Атрибут width='100%', ищем ширину другим способом.")
                # Пропускаем, так как '100%' не является фиксированной шириной для PNG
            else:
                my_log.log2(f"my_mermaid:extract_width_from_svg: Неподдерживаемый формат ширины в атрибуте width: {width_str}")

        # 3. Последний шанс: max-width из атрибута 'style' (как было в описании проблемы на GitHub)
        style_str = root.get('style')
        if style_str:
            match = re.search(r'max-width:\s*(\d+\.?\d*)px', style_str)
            if match:
                try:
                    return int(float(match.group(1)))
                except ValueError:
                    my_log.log2(f"my_mermaid:extract_width_from_svg: Некорректный формат ширины в style (max-width): {match.group(1)}")
                    # Продолжаем поиск, если парсинг style (max-width) не удался

        my_log.log2("my_mermaid:extract_width_from_svg: Не удалось найти ширину в SVG (ни viewBox, ни width (px), ни max-width в style).")
        return None
    except ET.ParseError:
        my_log.log2("my_mermaid:extract_width_from_svg: Ошибка парсинга SVG-контента. Возможно, SVG некорректен.")
        return None
    except Exception as e:
        my_log.log2(f"my_mermaid:extract_width_from_svg: Неизвестная ошибка при извлечении ширины из SVG: {e}")
        return None


def generate_mermaid_png_bytes(diagram_text: str, puppeteer_config_path: str = "puppeteer-config.txt_json") -> bytes | str:
    """
    Генерирует диаграмму Mermaid в формате PNG и возвращает ее как байты.
    Автоматически определяет оптимальную ширину, сначала генерируя SVG,
    затем используя его ширину для генерации PNG.
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
    try:
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
                home_dir = os.path.expanduser('~')

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
                    puppeteer_cache_pattern = os.path.join(home_dir, '.cache', 'puppeteer', 'chrome-headless-shell', '*', '*', 'chrome-headless-shell.exe')
                    my_log.log2(f"my_mermaid:generate_mermaid_png_bytes: Ищем chrome-headless-shell.exe в кеше Puppeteer: {puppeteer_cache_pattern}")
                    potential_executables = glob.glob(puppeteer_cache_pattern)

                    if potential_executables:
                        os.environ['PUPPETEER_EXECUTABLE_PATH'] = potential_executables[0]
                        my_log.log2(f"my_mermaid:generate_mermaid_png_bytes: PUPPETEER_EXECUTABLE_PATH установлен из кеша Puppeteer: {potential_executables[0]}")

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

            # --- Шаг 1: Генерируем SVG для определения размера ---
            svg_command = [cmd, "-e", "svg", "-i", "-", "-o", "-", "-p", puppeteer_config_path]
            try:
                # my_log.log2("my_mermaid:generate_mermaid_png_bytes: Генерируем SVG для определения ширины...")
                process_svg = subprocess.Popen(
                    svg_command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=os.environ.copy()
                )
                stdout_svg, stderr_svg = process_svg.communicate(input=diagram_text.encode('utf-8'))

                if process_svg.returncode != 0:
                    error_message = stderr_svg.decode('utf-8').strip()
                    my_log.log2(f"my_mermaid:generate_mermaid_png_bytes: Ошибка subprocess при генерации SVG (код {process_svg.returncode}): {error_message}")
                    return f"Ошибка при генерации SVG для определения размера: {error_message}"

                svg_content = stdout_svg.decode('utf-8')

            except FileNotFoundError:
                my_log.log2("my_mermaid:generate_mermaid_png_bytes: Ошибка: mmdc не найден (при попытке генерации SVG).")
                return "mmdc не найден. Убедись, что mermaid-cli установлен и доступен в PATH."
            except Exception as e:
                my_log.log2(f"my_mermaid:generate_mermaid_png_bytes: Неизвестная ошибка при генерации SVG: {e}")
                return f"Неизвестная ошибка при генерации SVG: {e}"

            # --- Шаг 2: Извлекаем ширину из SVG ---
            # Используем fallback-ширину, если не удалось определить
            auto_width = extract_width_from_svg(svg_content)
            if auto_width is None:
                my_log.log2("my_mermaid:generate_mermaid_png_bytes: Не удалось определить ширину из SVG, используем ширину по умолчанию (1600px).")
                auto_width = 1600 # Разумная ширина по умолчанию, если не удалось определить
            else:
                pass # my_log.log2(f"my_mermaid:generate_mermaid_png_bytes: Определена ширина из SVG: {auto_width}px.")

            # --- Шаг 3: Генерируем PNG с определенной шириной ---
            png_command = [cmd, "-e", "png", "-i", "-", "-o", "-", "-w", str(auto_width), "-p", puppeteer_config_path]

            try:
                # my_log.log2(f"my_mermaid:generate_mermaid_png_bytes: Генерируем PNG с шириной {auto_width}px...")
                process_png = subprocess.Popen(
                    png_command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=os.environ.copy()
                )
                stdout_png, stderr_png = process_png.communicate(input=diagram_text.encode('utf-8'))

                if process_png.returncode != 0:
                    env_info = f"PUPPETEER_EXECUTABLE_PATH: {os.environ.get('PUPPETEER_EXECUTABLE_PATH', 'Не задан')}"
                    error_message = stderr_png.decode('utf-8').strip()
                    my_log.log2(f"my_mermaid:generate_mermaid_png_bytes: Ошибка subprocess при генерации PNG (код {process_png.returncode}): {error_message}. {env_info}")
                    return f"Ошибка при генерации диаграммы PNG: {error_message}. {env_info}"

                # my_log.log2("my_mermaid:generate_mermaid_png_bytes: Диаграмма успешно сгенерирована в PNG с автоматически определенной шириной.")
                return stdout_png
            except FileNotFoundError:
                my_log.log2("my_mermaid:generate_mermaid_png_bytes: Ошибка: mmdc не найден (при попытке генерации PNG).")
                return "mmdc не найден. Убедись, что mermaid-cli установлен и доступен в PATH."
            except Exception as e:
                my_log.log2(f"my_mermaid:generate_mermaid_png_bytes: Неизвестная ошибка при генерации PNG: {e}")
                return f"Неизвестная ошибка при генерации PNG: {e}"
    finally:
        clean_puppeteer_temp_dirs()

    return "Неизвестная ошибка при генерации диаграммы."


if __name__ == "__main__":
    mermaid_diagram = """
%%{init: { 'flowchart': { 'nodeSpacing': 150, 'rankSpacing': 250 } } }%%
graph LR
    A[Начало] --> B[/Ссылка на страницу ВБ/];
    B --> C{{Wildberries}};
    C -- Запрос данных --> D[Парсинг и сбор отзывов];
    D --> E[(Собранные отзывы)];
    E --> F[Модуль анализа контента];
    F --> G[Анализ: Спам];
    F --> H[Анализ: Нерелевантность];
    F --> I[Анализ: 18+];
    F --> J[Анализ: Токсичность];
    F --> K[Анализ: Запрещенные объекты];
    G --> L{Формирование общего статуса проверки};
    H --> L;
    I --> L;
    J --> L;
    K --> L;
    L --> M{Инциденты обнаружены?};
    M -- Да --> N[Уведомление об инциденте];
    N -- Отправка уведомления --> O{{Wildberries}};
    N --> P[/Итоговый статус проверки/];
    M -- Нет --> P;
    P --> Q[Конец];
    linkStyle 18 stroke-dasharray: 5 5;
"""

    # Дополнительная диаграмма для проверки очень широкого случая
    wide_diagram = """
graph TD
    A[Start] --> B(Step 1 - Long long long description that makes this node very wide);
    B --> C{Decision Point with more text and some extra words};
    C -- Yes --> D[Action if Yes, and this action also has quite a bit of explanatory text];
    C -- No --> E[Alternative action, potentially with a different, slightly shorter text description];
    D --> F(End Process for Yes Path - This also needs to be long enough to push the width);
    E --> G(End Process for No Path - A bit shorter, but still contributes to overall width);
    F --> H[Final Merge or Outcome, requiring even more detailed text];
    G --> H;
    H --> I(Completion);
    I --> J[Next System or Integration Point, needing a very lengthy explanation];
    J --> K[Final Final Final Step, extremely detailed description to ensure max width];
    K --> L(Process Complete - Done and dusted, nothing more to see here, moving on to the next task after this one is finished);
    """

    # Новая, небольшая диаграмма для тестирования
    small_diagram = """
graph TD
    A[Начало] --> B{Проверка условия?};
    B -- Да --> C[Выполнить действие 1];
    B -- Нет --> D[Выполнить действие 2];
    C --> E[Конец];
    D --> E;
    """

    try:
        my_log.log2("\n--- Тест 1: Исходная диаграмма (средняя) ---")
        png_bytes_1 = generate_mermaid_png_bytes(mermaid_diagram)
        if isinstance(png_bytes_1, bytes):
            output_path_1 = os.path.join(os.path.expanduser('~'), "Downloads", "output_auto_1_medium.png")
            with open(output_path_1, "wb") as f:
                f.write(png_bytes_1)
            print(f"Диаграмма 1 успешно сохранена в {output_path_1}")
        else:
            print(f"Ошибка для диаграммы 1: {png_bytes_1}")

        my_log.log2("\n--- Тест 2: Широкая диаграмма ---")
        png_bytes_2 = generate_mermaid_png_bytes(wide_diagram)
        if isinstance(png_bytes_2, bytes):
            output_path_2 = os.path.join(os.path.expanduser('~'), "Downloads", "output_auto_2_wide.png")
            with open(output_path_2, "wb") as f:
                f.write(png_bytes_2)
            print(f"Диаграмма 2 успешно сохранена в {output_path_2}")
        else:
            print(f"Ошибка для диаграммы 2: {png_bytes_2}")

        my_log.log2("\n--- Тест 3: Небольшая диаграмма ---")
        png_bytes_3 = generate_mermaid_png_bytes(small_diagram)
        if isinstance(png_bytes_3, bytes):
            output_path_3 = os.path.join(os.path.expanduser('~'), "Downloads", "output_auto_3_small.png")
            with open(output_path_3, "wb") as f:
                f.write(png_bytes_3)
            print(f"Диаграмма 3 успешно сохранена в {output_path_3}")
        else:
            print(f"Ошибка для диаграммы 3: {png_bytes_3}")


    except Exception as e:
        print(f"Неизвестная ошибка в main: {e}")
