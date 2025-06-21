# Убедитесь, что у вас установлены библиотеки и wkhtmltoimage
# pip install imgkit markdown
# https://wkhtmltopdf.org/downloads.html (нужно установить и добавить в PATH)


import cachetools.func
import glob
import io
import html
import os
import re
import shutil
import tempfile
import threading
from typing import List, Optional

import imgkit
import markdown
from PIL import Image
from playwright.sync_api import sync_playwright

import my_log


LOCK = threading.Lock()


CSS1 = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap');

        body {
            /* Используем современный, читаемый шрифт */
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background-color: #f7f8fa; /* Слегка серый фон, чтобы таблица выделялась */
            color: #333;
            margin: 0;
            padding: 40px; /* Больше "воздуха" вокруг таблицы */
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
        }

        table {
            border-collapse: collapse;
            width: 100%;
            max-width: 1400px;
            margin: 0 auto;
            border-radius: 8px; /* Скругленные углы для современного вида */
            overflow: hidden; /* Прячет все, что выходит за рамки скругления */
            box-shadow: 0 4px 25px rgba(0, 0, 0, 0.1); /* Мягкая, глубокая тень */
            background-color: #ffffff;
        }

        th, td {
            padding: 16px 20px;
            text-align: left;
            vertical-align: top;
            /* Убираем вертикальные рамки, оставляем только горизонтальные разделители */
            border-bottom: 1px solid #e9ecef;
        }

        /* Стиль для заголовка таблицы */
        thead th {
            background-color: #f7f8fa;
            color: #6c757d; /* Менее резкий цвет текста заголовка */
            font-size: 12px;
            font-weight: 600; /* Полужирное начертание */
            text-transform: uppercase; /* Все буквы заглавные */
            letter-spacing: 0.05em; /* Небольшое расстояние между буквами */
            border-top: 0; /* Убираем верхнюю границу у заголовков */
            border-bottom: 2px solid #dee2e6; /* Более жирный разделитель для хедера */
        }

        /* Убираем рамку у последней строки для чистого вида */
        tbody tr:last-child td {
            border-bottom: 0;
        }

        /* Эффект при наведении курсора на строку */
        tbody tr:hover {
            background-color: #f1f3f5;
            transition: background-color 0.2s ease-in-out;
        }

        /* Стиль для Markdown-кода внутри ячеек */
        code {
            background-color: #e9ecef;
            color: #c92a2a; /* Красный для акцента на коде */
            padding: 2px 5px;
            border-radius: 4px;
            font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
            font-size: 0.9em;
        }

        strong {
            color: #212529;
            font-weight: 600;
        }
    """


CSS2 = """
            body {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                background-color: #ffffff; /* Use a clean white background */
                margin: 0;
                padding: 20px; /* Add some padding around the table */
                -webkit-font-smoothing: antialiased; /* Better font rendering */
            }
            table {
                border-collapse: collapse;
                margin: 0;
                width: auto; /* Let the content define the width */
                min-width: 600px;
                max-width: 1400px; /* Prevent it from being excessively wide */
                box-shadow: 0 0 15px rgba(0, 0, 0, 0.1);
                table-layout: auto; /* Default algorithm for layout based on content */
            }
            th, td {
                padding: 12px 15px;
                border: 1px solid #dee2e6;
                text-align: left;
                vertical-align: top; /* Align content to the top for readability */
                word-wrap: break-word; /* Wrap long words */
            }
            th {
                background-color: #f8f9fa;
                color: #212529;
                font-weight: 600;
            }
            tbody tr:nth-child(even) {
                background-color: #f8f9fa;
            }
            tbody tr:hover {
                background-color: #e9ecef;
            }
        """


BR = html.escape('<br>')
UL1 = html.escape('<ul>')
UL2 = html.escape('</ul>')
LI1 = html.escape('<li>')
LI2 = html.escape('</li>')


def clean_wkhtml_temp_files():
    """
    Удаляет временные HTML-файлы, созданные wkhtmltoimage, из системной временной папки.
    """
    temp_dir = tempfile.gettempdir()
    file_pattern = os.path.join(temp_dir, 'wktemp-*.html')

    for f in glob.glob(file_pattern):
        try:
            os.remove(f)
        except OSError as e:
            my_log.log2(f"my_md_tables_to_png:clean_wkhtml_temp_files: Ошибка при удалении файла {f}: {e}")


@cachetools.func.ttl_cache(maxsize=100, ttl=5*60)
def html_to_image_bytes(html: str, css_style: Optional[str] = None) -> bytes:
    '''
    Converts an HTML page to a PNG image as bytes.
    The page must be fully formed according to the HTML standard.

    Args:
        html: A string containing the HTML code of the page.
        css_style: Optional string with custom CSS styles. If None,
                   default styles are used.

    Returns:
        PNG image as a byte string.

    Raises:
        Exception: In case of an error during conversion.
    '''
    with LOCK:
        # Inject CSS into the head if provided
        if css_style:
            style_block = f'<style>{css_style}</style>'
            html = html.replace('</head>', f'{style_block}</head>', 1)

        options = {
            'quiet': '',
            'encoding': "UTF-8",
            'enable-local-file-access': None,
            'format': 'png',
        }

        # --- Предварительная проверка наличия wkhtmltoimage в PATH ---
        wkhtmltoimage_path = shutil.which('wkhtmltoimage')
        if not wkhtmltoimage_path:
            error_msg = (
                "FATAL: 'wkhtmltoimage' executable could not be found in the system's PATH. "
                "Its directory might not be included in the PATH environment variable for the "
                "user running this script, or it might lack execute permissions. "
                "Please verify 'wkhtmltoimage' installation and PATH configuration for the current environment."
            )
            my_log.log2(error_msg)
            # Выбрасываем FileNotFoundError, так как это более точная ошибка для "не найдено"
            raise FileNotFoundError(error_msg)

        try:
            # Render to raw PNG bytes
            raw_png_bytes = imgkit.from_string(html, False, options=options)

            clean_wkhtml_temp_files()

            # Optimize via Pillow
            with Image.open(io.BytesIO(raw_png_bytes)) as img:
                output_buffer = io.BytesIO()
                img.save(output_buffer, format='PNG')
                return output_buffer.getvalue()
        except OSError as e:
            # Если мы дошли до этого блока, значит wkhtmltoimage_path был найден,
            # но OSError все равно произошел во время выполнения.
            # Это указывает на проблему во время запуска или выполнения, а не на отсутствие файла.
            # Здесь мы предполагаем, что это может быть связано с проблемами рендеринга HTML.
            my_log.log2(
                f"FATAL: An OSError occurred during the execution of 'wkhtmltoimage' (found at '{wkhtmltoimage_path}'). "
                f"This often indicates an issue with the HTML content itself, a rendering problem by 'wkhtmltoimage', "
                f"or insufficient system resources. The program might have failed to render the image correctly. "
                f"Original OS error details: {e}"
            )
            raise e
        except Exception as e:
            # Ловим другие потенциальные исключения, которые могут возникнуть в процессе
            my_log.log2(f"FATAL: An unexpected error occurred during HTML to image conversion: {e}")
            raise e


@cachetools.func.ttl_cache(maxsize=100, ttl=5*60)
def markdown_table_to_image_bytes(
    markdown_table_string: str,
    css_style: Optional[str] = None,
) -> bytes:
    """
    Конвертирует Markdown-таблицу в стильное PNG-изображение в виде байтов.

    Для автоматического подбора ширины колонок и переноса текста используется
    движок рендеринга WebKit (через wkhtmltoimage), который применяет
    стандартные алгоритмы верстки HTML-таблиц.
    Если в таблице всего 2 строки то не рисует.

    Args:
        markdown_table_string: Строка, содержащая таблицу в формате Markdown.
        css_style: Опциональная строка с кастомными CSS-стилями. Если None,
                   используются стили по умолчанию.

    Returns:
        PNG-изображение в виде байтовой строки.

    Raises:
        OSError: Если утилита `wkhtmltoimage` не найдена в системном PATH.
    """
    with LOCK:
        # Use default styles if none are provided
        if css_style is None:
            css_style = CSS1

        lines = markdown_table_string.strip().split('\n')
        lines = [x for x in lines if x]
        if len(lines) < 3:
            return b''

        # Step 1: Convert Markdown to an HTML fragment.
        table_html = markdown.markdown(
            markdown_table_string, extensions=['tables', 'fenced_code']
        )

        # Step 2: Assemble a full, self-contained HTML document.
        # This includes the crucial UTF-8 meta tag and the CSS for styling.
        full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <style>
        {css_style}
    </style>
</head>
<body>
    {table_html}
</body>
</html>"""

        # Step 3: Define options for imgkit.
        # 'encoding' ensures correct text interpretation.
        # 'enable-local-file-access' is a security best practice.
        options = {
            'quiet': '',
            'encoding': "UTF-8",
            'enable-local-file-access': None,
            'format': 'png',
        }

        try:
            # Step 1: Generate a raw, uncompressed PNG in memory using imgkit.
            # This is fast but results in a large byte object.
            raw_png_bytes = imgkit.from_string(full_html, False, options=options)

            clean_wkhtml_temp_files()

            # Step 2: Use Pillow to re-compress the image data with optimization.
            # Open the image from the raw bytes.
            with Image.open(io.BytesIO(raw_png_bytes)) as img:
                # Create an in-memory byte buffer to save the compressed image.
                output_buffer = io.BytesIO()
                # Save to the buffer with maximum PNG compression.
                # `optimize=True` enables extra passes to find a smaller file size.
                # `compress_level=9` is the highest zlib compression level.
                # img.save(output_buffer, format='PNG', optimize=True, compress_level=9)
                # img.save(output_buffer, format='PNG', compress_level=6)
                img.save(output_buffer, format='PNG')
                # Retrieve the compressed bytes from the buffer.
                compressed_png_bytes = output_buffer.getvalue()

            return compressed_png_bytes
        except OSError as e:
            # Provide a more helpful error if wkhtmltoimage is not found.
            my_log.log2(
                "CRITICAL ERROR: 'wkhtmltoimage' not found.\n"
                "Please install it from https://wkhtmltopdf.org/downloads.html "
                "and ensure it's in your system's PATH."
            )
            raise e


def find_markdown_tables(markdown_text: str) -> List[str]:
    """
    Finds and extracts Markdown tables from a given text.

    This function iterates through the lines of the input text,
    identifying potential Markdown tables based on a header line
    immediately followed by a delimiter line. It then collects
    subsequent data lines that conform to table structure.

    Args:
        markdown_text (str): The input string containing Markdown text.

    Returns:
        List[str]: A list of strings, where each string is a detected
                   Markdown table. Returns an empty list if no tables are found.
    """
    tables = []
    lines = markdown_text.strip().split('\n')
    num_lines = len(lines)

    # Improved Regex for a standard Markdown table delimiter line.
    # It correctly handles optional leading/trailing pipes and whitespace,
    # and requires at least one segment of hyphens with optional colons and a pipe.
    # Pattern explanation for segment: `(?:[:-]?\-+[:]?)`
    #   `[:-]?` : Optional colon at the beginning of the segment (for left alignment).
    #   `\-+`   : One or more hyphens.
    #   `[:]?`  : Optional colon at the end of the segment (for right alignment).
    delimiter_pattern = re.compile(r'^\s*\|?(?:\s*(?:[:-]?\-+[:]?)\s*\|)+\s*$', re.IGNORECASE)

    i = 0
    while i < num_lines:
        line = lines[i].strip()

        # Look for a potential header line (must contain '|')
        if '|' in line and i + 1 < num_lines:
            next_line = lines[i+1].strip()

            # Check if the next line is a valid Markdown table delimiter
            if delimiter_pattern.match(next_line):
                # Found a table: header line + delimiter line
                current_table_lines = [line, next_line]
                i += 2 # Move past the header and delimiter lines

                # Now, collect all subsequent data lines belonging to this table
                while i < num_lines:
                    data_line = lines[i].strip()
                    # A valid data line must contain '|' and NOT be a delimiter line itself.
                    if '|' in data_line and not delimiter_pattern.match(data_line):
                        current_table_lines.append(data_line)
                        i += 1
                    else:
                        # Current line is not a data line (e.g., empty line, plain text, or another delimiter)
                        # So, the current table has ended.
                        break

                # Add the complete table to the list of found tables
                if current_table_lines:
                    # Склеиваем все строки в один блок
                    raw_table_block = "\n".join(current_table_lines)

                    raw_table_block = raw_table_block.replace(BR, '')
                    raw_table_block = raw_table_block.replace(UL1, '')
                    raw_table_block = raw_table_block.replace(UL2, '')
                    raw_table_block = raw_table_block.replace(LI1, '')
                    raw_table_block = raw_table_block.replace(LI2, '')

                    # Находим маркеры: первый и последний '|'
                    first_pipe_pos = raw_table_block.find('|')
                    last_pipe_pos = raw_table_block.rfind('|')

                    # Если маркеры есть — режем по ним. Нет — игнорируем блок.
                    if first_pipe_pos != -1:
                        clean_table = raw_table_block[first_pipe_pos : last_pipe_pos + 1]
                        tables.append(clean_table)
                    else:
                        tables.append(raw_table_block)

                # The outer while loop will handle advancing 'i' from its current position.
            else:
                # The next line is not a delimiter, so this is not a table. Move to the next line.
                i += 1
        else:
            # Current line doesn't contain '|' or is the last line, so it cannot be a table header.
            # Move to the next line.
            i += 1

    return tables


@cachetools.func.ttl_cache(maxsize=100, ttl=5*60)
def html_to_image_bytes_playwright(
    html: str,
    css_style: Optional[str] = None,
    javascript_delay_ms: int = 2000,
    width: int = 1920,
    height: int = 1080,
    ) -> bytes:
    '''
    Converts an HTML page to a PNG image as bytes using Playwright.
    The page must be fully formed according to the HTML standard.
    Supports full HTML5, CSS3, and JavaScript execution for dynamic content rendering.

    Args:
        html: A string containing the HTML code of the page.
        css_style: Optional string with custom CSS styles. If None,
                   default styles are used.
        javascript_delay_ms: Optional delay in milliseconds to wait after loading HTML
                             and before taking a screenshot. Useful for pages with
                             JavaScript that needs time to execute and render content
                             (e.g., canvas drawings, dynamic DOM manipulation).
                             Defaults to 2000ms (2 seconds).

    Returns:
        PNG image as a byte string.

    Raises:
        Exception: In case of an error during conversion.
    '''
    with LOCK:
        # Inject CSS into the head if provided
        if css_style:
            style_block = f'<style>{css_style}</style>'
            # Простая замена </head> может быть не совсем надежной для всех HTML-структур,
            # но для большинства случаев она работает.
            html = html.replace('</head>', f'{style_block}</head>', 1)

        browser = None
        try:
            with sync_playwright() as p:
                # Запускаем браузер в безголовом режиме (без графического интерфейса)
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.set_viewport_size({"width": width, "height": height})

                # Устанавливаем содержимое страницы напрямую из HTML строки
                page.set_content(html)

                # Ждем, пока сетевая активность не утихнет. Это часто помогает
                # убедиться, что все ресурсы загружены и начальный JS выполнен.
                page.wait_for_load_state('networkidle')

                # Добавляем явную задержку для выполнения JavaScript,
                # особенно полезно для сложных вычислений или анимаций на Canvas.
                if javascript_delay_ms > 0:
                    page.wait_for_timeout(javascript_delay_ms)

                # Делаем скриншот страницы в формате PNG
                raw_png_bytes = page.screenshot(type='png')


                return raw_png_bytes

                # # Оптимизируем изображение с помощью Pillow, как в исходном коде
                # # Убедитесь, что 'PIL' (Pillow) установлена: pip install Pillow
                # # from PIL import Image # Если не импортирована выше
                # with Image.open(io.BytesIO(raw_png_bytes)) as img:
                #     output_buffer = io.BytesIO()
                #     img.save(output_buffer, format='PNG')
                #     return output_buffer.getvalue()

        except Exception as e:
            my_log.log_gemini(f"Error converting HTML to image: {e}")
            raise Exception(f"Failed to convert HTML to image: {e}") from e
        finally:
            # Убеждаемся, что браузер всегда закрывается
            if browser:
                try:
                    browser.close()
                except Exception as e:
                    if 'Event loop is closed! Is Playwright already stopped?' not in str(e):
                        my_log.log_gemini(f"Error closing browser: {e}")


if __name__ == "__main__":

    # --- Example Usage ---
    markdown_text_with_tables = """

blabla

| Заголовок 1 | Заголовок 2 | Заголовок 3 |
|-------------|-------------|-------------|


Вот простая таблица в формате Markdown:

<pre><code class="language-plaintext">| Заголовок 1 | Заголовок 2 | Заголовок 3 |
|-------------|-------------|-------------|
| Строка 1, Ячейка 1 | Строка 1, Ячейка 2 | Строка 1, Ячейка 3 |
| Строка 2, Ячейка 1 | Строка 2, <br> Ячейка 2 | Строка 2, Ячейка 3 |
| Строка 3, Ячейка 1 | Строка 3, Ячейка 2 | Строка 3, Ячейка 3 |
</code></pre>'


blabla

| Заголовок 1 | Заголовок 2 | Заголовок 3 |
|-------------|-------------|-------------|
| Строка 1, Ячейка 1 | Строка 1, Ячейка 2 | Строка 1, Ячейка 3 |
| Строка 2, Ячейка 1 | Строка 2, Ячейка 2 | Строка 2, Ячейка 3 |
| Строка 3, Ячейка 1 | Строка 3, Ячейка 2 | Строка 3, Ячейка 3 |

asdasd




"""

    found_tables = find_markdown_tables(markdown_text_with_tables)

    n = 1
    for table in reversed(found_tables):
        print(table)

        try:
            # Call the function to get the styled image bytes
            image_data_bytes = markdown_table_to_image_bytes(table)

            # Save it directly to a file (for demonstration/testing):
            output_filename = f"c:/Users/user/Downloads/{n}.png"
            n += 1
            with open(output_filename, "wb") as f:
                f.write(image_data_bytes)
            print(f"Styled image successfully created and saved to '{output_filename}' from bytes.")

        except ValueError as e:
            print(f"Error processing Markdown table: {e}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")



#     example_html = """
# <canvas id="mandelbrotCanvas" width="800" height="700" style="border:1px solid #000;"></canvas>
# <script>
#     const canvas = document.getElementById('mandelbrotCanvas');
#     const ctx = canvas.getContext('2d');
#     const width = canvas.width;
#     const height = canvas.height;

#     // Mandelbrot parameters
#     const MAX_ITERATIONS = 200; // Увеличено количество итераций для большей детализации

#     // Определение границ комплексной плоскости для стандартного вида фрактала
#     const minRe = -2.5;
#     const maxRe = 1.0;
#     const minIm = -1.25;
#     const maxIm = 1.25;

#     for (let x = 0; x < width; x++) {
#         for (let y = 0; y < height; y++) {
#             // Преобразование координат пикселей в координаты комплексной плоскости
#             let ca = minRe + (x / width) * (maxRe - minRe);
#             let cb = minIm + (y / height) * (maxIm - minIm);

#             let a = ca;
#             let b = cb;

#             let n = 0;
#             while (n < MAX_ITERATIONS) {
#                 let aa = a * a - b * b;
#                 let bb = 2 * a * b;
#                 a = aa + ca;
#                 b = bb + cb;

#                 if (a * a + b * b > 4) { // Проверка, выходит ли точка за границы
#                     break;
#                 }
#                 n++;
#             }

#             let color;
#             if (n === MAX_ITERATIONS) {
#                 color = 'black'; // Точка внутри множества
#             } else {
#                 // Окрашивание в зависимости от количества итераций
#                 let hue = (n * 10) % 360; // Изменение множителя для распределения цветов
#                 let saturation = 100;
#                 let lightness = 20 + (n / MAX_ITERATIONS) * 50; // Варьирование яркости для градиента
#                 color = `hsl(${hue}, ${saturation}%, ${lightness}%)`;
#             }
#             ctx.fillStyle = color;
#             ctx.fillRect(x, y, 1, 1);
#         }
#     }
# </script>

#     """
#     image_data_bytes = html_to_image_bytes_playwright(example_html)
#     with open("c:/Users/user/Downloads/html 1.png", "wb") as f:
#         f.write(image_data_bytes)
