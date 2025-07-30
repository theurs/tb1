import os
from PIL import Image

def convert_png_to_webp(input_folder, output_folder, quality_setting, compression_method, is_lossless):
    """
    Конвертирует все PNG файлы из указанной папки в формат WebP
    с заданными параметрами качества и метода сжатия, а также опцией без потерь.
    Результат сохраняется в другую папку.

    :param input_folder: Путь к папке с исходными PNG файлами.
    :param output_folder: Путь к папке, куда будут сохранены WebP файлы.
    :param quality_setting: Уровень качества для WebP (от 0 до 100). Используется, если is_lossless=False.
    :param compression_method: Метод сжатия (от 0 до 6), где 6 - самый медленный, но эффективный.
    :param is_lossless: Булево значение. True для сжатия без потерь, False для сжатия с потерями.
    """

    # Создаем выходную директорию, если она не существует
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
        print(f"Создана директория для сохранения WebP файлов: {output_folder}")
    else:
        print(f"Директория для сохранения WebP файлов уже существует: {output_folder}")

    print(f"\nНачинаем конвертацию PNG в WebP с параметрами:")
    print(f"  - Качество: {quality_setting}% (активно при сжатии с потерями)")
    print(f"  - Метод сжатия: {compression_method} (от 0 до 6, чем выше, тем лучше сжатие, но дольше)")
    print(f"  - Сжатие без потерь: {'Да' if is_lossless else 'Нет'}")
    print("-" * 50)

    # Перебираем все файлы в исходной папке
    for filename in os.listdir(input_folder):
        # Проверяем, является ли файл изображением PNG
        if filename.lower().endswith(".png"):
            input_path = os.path.join(input_folder, filename)

            # Формируем имя выходного файла с расширением .webp
            # os.path.splitext(filename)[0] берет имя файла без расширения
            output_filename = os.path.splitext(filename)[0] + ".webp"
            output_path = os.path.join(output_folder, output_filename)

            try:
                # Открываем изображение
                with Image.open(input_path) as img:
                    # Сохраняем в формат WebP с заданными параметрами
                    # quality используется только при lossless=False
                    # method влияет на эффективность как lossless, так и lossy сжатия
                    img.save(output_path, 
                             "webp", 
                             quality=quality_setting, 
                             method=compression_method, 
                             lossless=is_lossless)
                print(f"✅ Конвертировано '{filename}' в '{output_filename}'")
            except Exception as e:
                print(f"❌ Ошибка при конвертации '{filename}': {e}")
        else:
            print(f"⏩ Пропущен файл '{filename}' (не является PNG)")

    print("\n" + "-" * 50)
    print("Конвертация завершена!")

# --- НАСТРОЙКИ ---
# Параметры сжатия WebP:
# 1. quality (Качество):
#    - От 0 (максимальное сжатие, минимальное качество) до 100 (минимальное сжатие, максимальное качество).
#    - Активно только при `is_lossless=False`.
#    - Если вы хотите "максимальное сжатие" с потерями (самый маленький файл), установите webp_quality = 0.
webp_quality = 50 

# 2. method (Метод сжатия):
#    - От 0 (самый быстрый, наименее эффективный) до 6 (самый медленный, наиболее эффективный).
#    - Чем выше значение, тем дольше процесс, но потенциально меньше размер файла.
compression_method = 6 

# 3. lossless (Без потерь):
#    - True: Сжатие без потерь (как PNG). quality в этом случае игнорируется.
#    - False: Сжатие с потерями (как JPEG). quality определяет степень потерь.
is_lossless = False


# Укажите путь к вашей папке с исходными PNG файлами
# Важно: используйте двойные обратные слеши или префикс r для пути в Windows
input_folder_path = r"C:\Users\user\Downloads\Cards-png" 

# Определяем папку для сохранения конвертированных файлов.
# Она будет создана внутри input_folder_path
output_folder_path = os.path.join(input_folder_path, "webp_output")


# --- ЗАПУСК ПРОГРАММЫ ---
if __name__ == "__main__":
    convert_png_to_webp(input_folder_path, output_folder_path, webp_quality, compression_method, is_lossless)
