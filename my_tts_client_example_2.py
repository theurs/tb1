#!/usr/bin/env python3


import requests

url = "http://10.147.17.227:34671/set-voice/"
user_name = "theurs"
file_path = "1.oga"

with open(file_path, "rb") as f:
    files = {"filedata": (file_path, f, "audio/any")}
    response = requests.post(url, files=files, params={"user_id": user_name, "fname": file_path})

print(response.text)

