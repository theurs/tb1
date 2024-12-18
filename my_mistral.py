#!/usr/bin/env python3
# pip install -U mistralai


import os
from mistralai import Mistral

import cfg


api_key = cfg.mistral_ai[0]
# model = "mistral-large-latest"
model = 'open-mistral-nemo'

client = Mistral(api_key=api_key)

chat_response = client.chat.complete(
    model = model,
    messages = [
        {
            "role": "user",
            "content": "Расскажи коротко о книге Незнайка на луне.",
        },
    ]
)

print(chat_response.choices[0].message.content)
