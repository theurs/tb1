import glob
import os
import subprocess

import my_log
import utils


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
    cmd = "mmdc"
    is_linux = False
    if 'windows' in utils.platform().lower():
        cmd = "mmdc.cmd"
    elif 'linux' in utils.platform().lower():
        is_linux = True

    # Если это Linux и PUPPETEER_EXECUTABLE_PATH не установлен, пытаемся его найти
    if is_linux:
        if 'PUPPETEER_EXECUTABLE_PATH' not in os.environ:
            home_dir = os.path.expanduser('~')
            executable_pattern = os.path.join(home_dir, '.cache', 'puppeteer', 'chrome-headless-shell', '*', '*', 'chrome-headless-shell')

            my_log.log2(f"my_mermaid:generate_mermaid_png_bytes: PUPPETEER_EXECUTABLE_PATH не задан. Ищем в: {executable_pattern}")
            potential_executables = glob.glob(executable_pattern)

            if potential_executables:
                os.environ['PUPPETEER_EXECUTABLE_PATH'] = potential_executables[0]
                my_log.log2(f"my_mermaid:generate_mermaid_png_bytes: PUPPETEER_EXECUTABLE_PATH установлен: {potential_executables[0]}")
            else:
                my_log.log2("my_mermaid:generate_mermaid_png_bytes: chrome-headless-shell не найден в стандартных путях Puppeteer.")
        else:
            pass
            # my_log.log2(f"my_mermaid:generate_mermaid_png_bytes: PUPPETEER_EXECUTABLE_PATH уже задан: {os.environ['PUPPETEER_EXECUTABLE_PATH']}")

    command = [cmd, "-e", "png", "-i", "-", "-o", "-", "-p", puppeteer_config_path]

    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ.copy() 
        )

        stdout_data, stderr_data = process.communicate(input=diagram_text.encode('utf-8'))

        if process.returncode != 0:
            env_info = f"PUPPETEER_EXECUTABLE_PATH: {os.environ.get('PUPPETEER_EXECUTABLE_PATH', 'Не задан')}"
            error_message = stderr_data.decode('utf-8').strip()
            my_log.log2(f"my_mermaid:generate_mermaid_png_bytes: Ошибка subprocess (код {process.returncode}): {error_message}. {env_info}")
            return f"Ошибка при генерации диаграммы: {error_message}. {env_info}"

        my_log.log2("my_mermaid:generate_mermaid_png_bytes: Диаграмма успешно сгенерирована.")
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
    A[Начало] --> B{Решение}
    B -- Да --> C[Действие 1]
    B -- Нет --> D[Действие 2]
    C --> E[Конец]
    D --> E
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
