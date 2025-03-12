import zipfile
import os
import chardet
from typing import Optional

import my_log
import utils


# не распаковывать больше 1 мегабайта, все равно ллм не сможет обработать столько
MAX_DECOMPRESS_SIZE = 1000000


def detect_zip_bomb(zip_file: str, threshold: int = 100) -> bool:
    """
    Обнаруживает zip-бомбу, проверяя коэффициент сжатия и размер извлеченных файлов.

    Args:
        zip_file: Путь к zip-файлу.
        threshold: Пороговое значение для коэффициента сжатия.

    Returns:
        True, если обнаружена zip-бомба, False в противном случае.
    """
    try:
        with zipfile.ZipFile(zip_file, 'r') as zf:
            for file_info in zf.infolist():
                # Проверяем коэффициент сжатия
                if file_info.compress_size > 0:
                    compression_ratio = file_info.file_size / file_info.compress_size
                else:
                    compression_ratio = float('inf')

                if compression_ratio > threshold:
                    my_log.log_zip(f'Zip bomb detected! File: {file_info.filename}, Compression ratio: {compression_ratio:.2f}')
                    return True
        return False
    except zipfile.BadZipFile:
        my_log.log_zip(f'Error: Invalid zip file: {zip_file}')
        return True
    except Exception as e:
        my_log.log_zip(f'Error: {e}')
        return True


def extract_and_concatenate(zip_file: str) -> Optional[str]:
    """
    Извлекает все файлы из zip-архива, читает их как текст и объединяет в одну строку,
    автоматически определяя кодировку.

    Args:
        zip_file: Путь к zip-файлу. Или байты zip-файла.

    Returns:
        Объединенный текст из всех файлов в zip-архиве, или None в случае ошибки.
    """
    tmpfname = ''
    try:
        if isinstance(zip_file, bytes):
            tmpfname = utils.get_tmp_fname() + '.zip'
            with open(tmpfname, 'wb') as f:
                f.write(zip_file)
            zip_file = tmpfname
            if detect_zip_bomb(zip_file):
                my_log.log_zip("Обнаружена возможная zip-бомба. Обработка остановлена.")
                return None

        extracted_text = ""
        with zipfile.ZipFile(zip_file, 'r') as zf:
            for file_info in zf.infolist():
                try:
                    with zf.open(file_info) as extracted_file:
                        # Читаем файл как байты
                        raw_bytes = extracted_file.read()

                        # Определяем кодировку
                        encoding_result = chardet.detect(raw_bytes)
                        encoding = encoding_result['encoding']

                        # Если кодировка не определена, используем UTF-8 в качестве запасного варианта
                        if encoding is None:
                            encoding = 'utf-8'
                            my_log.log_zip(f"Не удалось определить кодировку файла {file_info.filename}. Используется utf-8.")

                        # Декодируем байты в текст
                        try:
                            text = raw_bytes.decode(encoding, errors='replace')
                        except UnicodeDecodeError:
                            my_log.log_zip(f"Не удалось декодировать файл {file_info.filename} с кодировкой {encoding}. Пропускаем.")
                            continue

                        extracted_text += f'<FILE>\n<NAME>{file_info.filename}</NAME>\n<BODY>\n{text}\n</BODY>\n</FILE>\n\n'
                        if len(extracted_text) > MAX_DECOMPRESS_SIZE:
                            return extracted_text[:MAX_DECOMPRESS_SIZE]
                except Exception as e:
                    my_log.log_zip(f"Произошла ошибка при обработке файла {file_info.filename}: {e}")
                    continue
        return extracted_text
    except zipfile.BadZipFile:
        my_log.log_zip("Ошибка: Некорректный zip-файл.")
        return None
    except FileNotFoundError:
        my_log.log_zip(f"Ошибка: Файл {zip_file} не найден.")
        return None
    except Exception as e:
        my_log.log_zip(f"Произошла общая ошибка: {e}")
        return None
    finally:
        if tmpfname:
            utils.remove_file(tmpfname)


def main():
    zip_file_path = r'C:\Users\user\Downloads\samples for ai\несколько текстов.zip'

    if not os.path.exists(zip_file_path):
        print("Файл не существует.")
        return

    concatenated_text = extract_and_concatenate(zip_file_path)

    if concatenated_text:
        print("Объединенный текст:")
        print(concatenated_text)
    else:
        print("Не удалось извлечь и объединить текст из zip-файла.")


if __name__ == "__main__":
    main()
