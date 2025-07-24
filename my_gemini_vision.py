from google import genai
from google.genai import types
from io import BytesIO
import json_repair
import os
from PIL import Image, ImageDraw, ImageFont

import my_gemini_general


def draw_annotations(image_path: str, json_data_string: str, output_path: str, save_quality: int = 95):
    """
    Накладывает на изображение рамки и подписи из JSON от модели.

    Функция предполагает, что модель обработала изображение,
    непропорционально смасштабировав его до квадрата 1024x1024.
    Она автоматически вычисляет оригинальные размеры изображения
    и корректно пересчитывает координаты рамок.

    Args:
        image_path (str): Путь к ИСХОДНОМУ изображению.
        json_data_string (str): Строка JSON с координатами, полученными от модели.
        output_path (str): Путь для сохранения результирующего изображения.
        save_quality (int): Качество сохранения JPEG (от 0 до 100).
    """
    # --- 1. Загрузка изображения и получение его реальных размеров ---
    try:
        base_image = Image.open(image_path).convert("RGBA")
        original_width, original_height = base_image.size
    except FileNotFoundError:
        print(f"Ошибка: Файл не найден по пути: {image_path}")
        return

    # --- 2. Вычисление коэффициентов масштабирования ---
    # Размер холста, который "видела" нейросеть
    MODEL_CANVAS_SIZE = 1024.0  # Используем float для точности деления

    # Коэффициенты для пересчета координат из пространства 1024x1024
    # в пространство оригинального изображения.
    scale_x = original_width / MODEL_CANVAS_SIZE
    scale_y = original_height / MODEL_CANVAS_SIZE

    # --- 3. Загрузка данных и подготовка к рисованию ---
    try:
        annotations = json_repair.loads(json_data_string)
    except Exception as e:
        print(f"Ошибка: Неверный формат JSON строки. {e}")
        return

    overlay = Image.new("RGBA", base_image.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)

    try:
        # Уменьшаем размер шрифта для подписей в блоке
        font_explanation = ImageFont.truetype("fonts/NotoSans-Bold.ttf", size=14)
    except IOError:
        print("Шрифт fonts/NotoSans-Bold.ttf не найден, используется стандартный шрифт.")
        font_explanation = ImageFont.load_default()

    # Заранее определенные, хорошо различимые цвета (RGBA: непрозрачный для рамки, полупрозрачный для фона текста)
    # Расширенный список из 25 различных цветов
    colors_opaque = [
        (255, 0, 0, 255),      # Red
        (0, 0, 255, 255),      # Blue
        (0, 255, 0, 255),      # Green
        (255, 255, 0, 255),    # Yellow
        (255, 0, 255, 255),    # Magenta
        (0, 255, 255, 255),    # Cyan
        (255, 165, 0, 255),    # Orange
        (128, 0, 128, 255),    # Purple
        (0, 128, 0, 255),      # Dark Green
        (139, 69, 19, 255),    # Saddle Brown
        (255, 192, 203, 255),  # Pink
        (0, 0, 128, 255),      # Navy
        (173, 216, 230, 255),  # Light Blue
        (255, 99, 71, 255),    # Tomato
        (60, 179, 113, 255),   # Medium Sea Green
        (75, 0, 130, 255),     # Indigo
        (255, 215, 0, 255),    # Gold
        (169, 169, 169, 255),  # Dark Gray
        (255, 20, 147, 255),   # Deep Pink
        (100, 149, 237, 255),  # Cornflower Blue
        (218, 112, 214, 255),  # Orchid
        (154, 205, 50, 255),   # Yellow Green
        (240, 230, 140, 255),  # Khaki
        (205, 92, 92, 255),    # Indian Red
        (127, 255, 0, 255)     # Chartreuse
    ]
    # Прозрачные цвета для фона подписей (та же палитра, но с альфа-каналом 128)
    colors_transparent_bg = [
        (c[0], c[1], c[2], 128) for c in colors_opaque
    ]

    # Список для сбора информации для блока пояснений
    explanation_items = []

    # --- 4. Цикл рисования рамок с пересчетом координат ---
    for i, item in enumerate(annotations):
        box = item.get("box_2d")
        label = item.get("label")

        if not box or not label:
            continue

        # Получаем координаты из пространства модели (1024x1024)
        # Ожидаемый формат от модели: [y1, x1, y2, x2]
        y1_model, x1_model, y2_model, x2_model = map(int, box)

        # Пересчитываем координаты для оригинального изображения
        x1 = int(x1_model * scale_x)
        y1 = int(y1_model * scale_y)
        x2 = int(x2_model * scale_x)
        y2 = int(y2_model * scale_y)

        # Убедимся, что координаты идут по возрастанию
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)

        # Присваиваем уникальный цвет на основе индекса
        color_index = i % len(colors_opaque) # Используем остаток от деления для зацикливания, если объектов > 25
        border_color_opaque = colors_opaque[color_index]
        label_bg_color_transparent = colors_transparent_bg[color_index]

        # Рисуем рамку
        draw.rectangle([x1, y1, x2, y2], outline=border_color_opaque, width=3) # Увеличим толщину рамки для видимости

        # Добавляем информацию для блока пояснений (только сам лейбл)
        explanation_items.append({
            "text": label,
            "bg_color": label_bg_color_transparent,
            "text_color": (255, 255, 255, 255) # Белый текст для контраста на цветном фоне
        })

    # --- 5. Рисуем консолидированный блок пояснений внизу слева ---
    if explanation_items: # Рисуем только если есть что объяснять
        margin = 15 # Отступ от краев изображения
        line_padding = 8 # Отступ между строками текста
        text_side_padding = 10 # Отступ слева/справа для текста внутри его фона

        # Вычисляем общую высоту всех строк текста с учетом отступов
        total_text_height = 0
        current_line_heights = []
        for item in explanation_items:
            # Приблизительная высота одной строки
            approx_line_height = font_explanation.getbbox(item["text"])[3] - font_explanation.getbbox(item["text"])[1]
            current_line_heights.append(approx_line_height)

        if current_line_heights:
            total_text_height = sum(current_line_heights) + (len(current_line_heights) - 1) * line_padding

        # Начальная Y-координата для первого элемента текста
        current_y_offset = original_height - margin - total_text_height

        for i, item in enumerate(explanation_items):
            text_to_draw = item["text"]
            text_bg_color = item["bg_color"]
            text_color = item["text_color"]

            # Вычисляем точную ширину текста для текущей строки
            current_text_width = draw.textlength(text_to_draw, font=font_explanation)
            current_line_height = current_line_heights[i]

            # Координаты для подложки текущей строки текста
            text_bg_x1 = margin
            text_bg_y1 = current_y_offset
            text_bg_x2 = text_bg_x1 + current_text_width + 2 * text_side_padding
            text_bg_y2 = text_bg_y1 + current_line_height + line_padding # Добавляем line_padding для высоты фона строки

            # Рисуем подложку для текущей строки текста
            draw.rectangle([text_bg_x1, text_bg_y1, text_bg_x2, text_bg_y2], fill=text_bg_color)

            # Рисуем текст
            # Центрируем текст внутри его фонового прямоугольника по вертикали
            text_y_position = text_bg_y1 + (text_bg_y2 - text_bg_y1 - current_line_height) / 2
            draw.text((text_bg_x1 + text_side_padding, text_y_position), text_to_draw, fill=text_color, font=font_explanation)

            # Обновляем Y-координату для следующей строки
            current_y_offset += current_line_height + line_padding

    # --- 6. Сохранение результата ---
    combined_image = Image.alpha_composite(base_image, overlay)
    final_image = combined_image.convert("RGB")
    final_image.save(output_path, quality=save_quality, subsampling=0)
    print(f"Обработка завершена. Файл сохранен как: {output_path}")


def find_objects_in_image(
    image: str,
    prompt: str,
    output_path: str,
    save_quality: int = 90,
    model_name="gemini-2.5-flash",
    thinking_budget=0
    ):

    client = genai.Client(api_key=my_gemini_general.get_next_key())

    bounding_box_system_instructions = """
    Возвращать ограничивающие рамки в виде массива JSON с метками.
    Никогда не возвращайте маски или ограждения кода. Ограничьтесь 25 объектами.
    Если объект присутствует несколько раз, называйте их в соответствии с их
    уникальными характеристиками (цвета, размер, положение, уникальные характеристики и т. д.).

    Пример корректного ответа:
    ```json
    [
    {"box_2d": [18, 14, 82, 93], "label": "А"},
    {"box_2d": [84, 14, 95, 93], "label": "АРИФ"},
    {"box_2d": [420, 473, 804, 786], "label": "Что происходит, когда вмешиваешься в оригинал"},
    {"box_2d": [920, 615, 959, 664], "label": "Том 5"},
    {"box_2d": [920, 684, 959, 862], "label": "Ракине"},
    {"box_2d": [962, 684, 975, 862], "label": "Студия Ариф"}
    ]
    ```
        """

    safety_settings = [
        types.SafetySetting(
            category="HARM_CATEGORY_DANGEROUS_CONTENT",
            threshold="BLOCK_NONE",
        ),
        types.SafetySetting(
            category="HARM_CATEGORY_HARASSMENT",
            threshold="BLOCK_NONE",
        ),
        types.SafetySetting(
            category="HARM_CATEGORY_HATE_SPEECH",
            threshold="BLOCK_NONE",
        ),
        types.SafetySetting(
            category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
            threshold="BLOCK_NONE",
        ),
    ]


    # Load and resize image
    im = Image.open(BytesIO(open(image, "rb").read()))


    # Run model to find bounding boxes
    response = client.models.generate_content(
        model=model_name,
        contents=[prompt, im],
        config = types.GenerateContentConfig(
            system_instruction=bounding_box_system_instructions,
            temperature=0.2,
            safety_settings=safety_settings,
            thinking_config=types.ThinkingConfig(
            thinking_budget=thinking_budget
            )
        )
    )

    # Check output
    print(str(response))
    print(response.text)

    output_path = r'C:\Users\user\Downloads\1_processed.jpg'

    # Твоя JSON строка. Теперь она будет интерпретироваться как [y1, x1, y2, x2]
    json_string = response.text

    if os.path.exists(image):
        draw_annotations(image, json_string, output_path, save_quality=save_quality)
    else:
        print(f"Исходный файл не найден: {image}")


if __name__ == "__main__":
    my_gemini_general.load_users_keys()
    prompt = """Выдели всех кто пьет воду"""
    image_path = r'C:\Users\user\Downloads\1.jpg'
    output_path = r'C:\Users\user\Downloads\1_processed.jpg'
    find_objects_in_image(image_path, prompt, output_path, save_quality=90, model_name="gemini-2.5-flash")
