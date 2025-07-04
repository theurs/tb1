# pip install svglib pycairo


import io
import os
import traceback
from typing import Union

from svglib.svglib import svg2rlg
from reportlab.graphics import renderPM

import my_log


def convert_svg_to_png_bytes(svg_source: Union[str, bytes]) -> bytes:
    """
    Конвертирует SVG-контент (в виде строки или байтов) или SVG-файл (по заданному пути)
    в изображение PNG в виде байтов.

    Аргументы:
        svg_source (Union[str, bytes]): Строка, содержащая непосредственно SVG-код,
                                        путь к SVG-файлу,
                                        или байты, содержащие SVG-код.

    Возвращает:
        Изображение PNG в виде байтовой строки в случае успеха.
        Пустые байты (b'') в случае неудачи или ошибки.
    """
    svg_content_stream = None

    if isinstance(svg_source, str):
        if os.path.exists(svg_source):
            try:
                # Открываем файл в бинарном режиме, так как svg2rlg может читать из бинарного потока
                svg_content_stream = open(svg_source, 'rb')
            except Exception as e:
                my_log.log2(f"my_svg:convert_svg_to_png_bytes:1: Ошибка открытия SVG файла '{svg_source}': {e}")
                return b''
        else:
            # Если строка не путь к файлу, предполагаем, что это прямой SVG-контент
            svg_content_stream = io.BytesIO(svg_source.encode('utf-8'))
    elif isinstance(svg_source, bytes):
        # Если входные данные - байты, используем их напрямую как поток
        svg_content_stream = io.BytesIO(svg_source)
    else:
        my_log.log2(f"my_svg:convert_svg_to_png_bytes:2:Неподдерживаемый тип входных данных для SVG: {type(svg_source)}")
        return b''

    if not svg_content_stream:
        my_log.log2("my_svg:convert_svg_to_png_bytes:3:Ошибка: Не удалось получить SVG-поток из входных данных.")
        return b''


    try:
        # Создаем объект Drawing из SVG-потока
        # svg2rlg читает из файла или потока
        drawing = svg2rlg(svg_content_stream)

        # Закрываем поток, если он был открыт из файла
        if isinstance(svg_source, str) and os.path.exists(svg_source):
            svg_content_stream.close()

        # Создаем буфер для выходного PNG
        png_buffer = io.BytesIO()

        renderPM.drawToFile(drawing, png_buffer, fmt='PNG')

        # Получаем байты из буфера
        png_bytes = png_buffer.getvalue()

        return png_bytes

    except Exception as e:
        # Убеждаемся, что поток закрыт в случае ошибки
        if isinstance(svg_source, str) and os.path.exists(svg_source) and not svg_content_stream.closed:
            svg_content_stream.close()
        error_msg = (
            f"ФАТАЛЬНО: Произошла ошибка во время конвертации SVG в изображение с использованием svglib/reportlab: {e}\n\n{traceback.format_exc()}"
        )
        my_log.log2(f'my_svg:convert_svg_to_png_bytes:4: {error_msg}')
        return b''


if __name__ == '__main__':
    # Создаем фиктивный SVG-файл для тестирования
    dummy_svg_path = r"c:\users\user\downloads\1.svg"

    print("--- Тестирование с путем к SVG-файлу ---")
    png_bytes_from_file = convert_svg_to_png_bytes(dummy_svg_path)
    if png_bytes_from_file:
        with open(r"c:\users\user\downloads\output_from_file.png", "wb") as f:
            f.write(png_bytes_from_file)
        print(f"PNG-изображение из файла сохранено в output_from_file.png (размер: {len(png_bytes_from_file)} байт)")
    else:
        print("Ошибка при конвертации из файла: Возвращены пустые байты.")
