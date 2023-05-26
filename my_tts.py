#!/usr/bin/env python3


import io  # Библиотека для работы с байтовыми потоками
import edge_tts  # Библиотека для генерации речи 
import tempfile  # Библиотека для создания временных файлов
import subprocess  # Библиотека для вызова внешних процессов
import os  # Библиотека для работы с файловой системой


def tts(text: str, voice: str = 'ru-RU-SvetlanaNeural', rate: str = '+50%') -> bytes: 
    """Генерирует аудио из текста с помощью edge-tts и возвращает байтовый поток

    Эта функция принимает:

    text: Строку с текстом для озвучивания

    voice: Необязательный параметр, указывает голос для синтеза речи. По умолчанию используется русский голос 'ru-RU-SvetlanaNeural'. Можно указать любой другой голос, доступный в edge-tts.

    rate: Необязательный параметр, указывает скорость речи. По умолчанию '+50%' - повышенная скорость. Можно указать любую скорость речи, поддерживаемую edge-tts.


    Функция возвращает байтовый поток с сгенерированным аудио.
    """
    
    # Удаляем символы переноса строки и перевода каретки 
    text = text.replace('\r','') 
    text = text.replace('\n',' ')  
    
    # Создаем временный файл для записи аудио
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f: 
        filename = f.name 
        
    # Запускаем edge-tts для генерации аудио
    command = [
        "/home/ubuntu/.local/bin/edge-tts",     # Исполняемый файл 
        "--rate="+rate, # Скорость речи
        "--text",       # Входной текст 
        text,          
        "-v",           # Голос
        voice,
        "--write-media",# Записать аудио в файл
        filename        # Имя выходного файла
    ]
    subprocess.run(command)
    
    # Читаем аудио из временного файла 
    with open(filename, "rb") as f: 
        data = io.BytesIO(f.read())
        
    # Удаляем временный файл
    os.remove(filename)
    
    # Возвращаем байтовый поток с аудио
    return data.getvalue()


if __name__ == "__main__":  
    # Пример использования   
    with open('test.mp3', 'wb') as f: 
        f.write(tts('Привет, как дела!'))
