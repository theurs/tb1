import subprocess

import utils


def generate_mermaid_png_bytes(diagram_text: str, puppeteer_config_path: str = "puppeteer-config.txt_json") -> bytes | str:
    """
    Генерирует диаграмму Mermaid в формате PNG и возвращает ее как байты.
    Использует пайпы для ввода/вывода, избегая промежуточных файлов диаграммы.

    Args:
        diagram_text: Строка с текстом диаграммы Mermaid.
        puppeteer_config_path: Путь к файлу puppeteer-config.json,
                               содержащему аргументы для Puppeteer (например, "--no-sandbox").

    Returns:
        Байты PNG-изображения. Или строка, если генерация диаграммы не удалась.
    """
    cmd = "mmdc"
    if 'windows' in utils.platform().lower():
        cmd = "mmdc.cmd"

    command = [cmd, "-e", "png", "-i", "-", "-o", "-", "-p", puppeteer_config_path]

    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        stdout_data, stderr_data = process.communicate(input=diagram_text.encode('utf-8'))

        if process.returncode != 0:
            raise Exception(f"Ошибка при генерации диаграммы: {stderr_data.decode('utf-8')}")

        return stdout_data
    except FileNotFoundError:
        return "mmdc не найден. Убедись, что mermaid-cli установлен и доступен в PATH."
    except Exception as e:
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
        with open(r"c:\Users\user\Downloads\output.png", "wb") as f:
            f.write(png_bytes)
        print("Диаграмма успешно сохранена в output.png")
    except Exception as e:
        print(f"Ошибка: {e}")
