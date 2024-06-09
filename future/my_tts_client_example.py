#!/usr/bin/env python3

import base64
import requests
import time


url = "http://10.147.17.227:34671/get-voice/"  # замените на адрес вашего сервера

# text = open('1.txt', 'r', encoding='utf-8').read()
text = 'Where you was little boy? Where you was little girl? Where you was little boy? Where you was little girl?'

data = {
    "text": text,  # текст для озвучивания
    "language": "en",  # язык
    "user_id": "theurs"  # ваш идентификатор пользователя
}

start_time = time.time()
response = requests.post(url, json=data)
print(f"Скорость в символах в секунду: {len(text) / (time.time() - start_time)}")

if response.status_code == 200:
    voice_data = base64.b64decode(response.json()["voice"])
    with open("voice.ogg", "wb") as f:  # сохраняем аудио в файл
        f.write(voice_data)
else:
    print("Ошибка:", response.text)
