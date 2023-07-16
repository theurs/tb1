#!/usr/bin/env python3

import json
import os
import sys
import time

import openai

import cfg



def ai_test() -> str:
    """
    """
    openai.api_key = cfg.key_test
    openai.api_base = cfg.openai_api_base_test
    
    #   text = open('1.txt', 'r').read()[:20000]
    text = 'Привет как дела'
    
    messages = [{"role": "system", "content": "Ты искусственный интеллект отвечающий на запросы юзера."},
                {"role": "user", "content": text}]

    current_model = cfg.model_test

    # тут можно добавить степень творчества(бреда) от 0 до 1 дефолт - temperature=0.5
    сompletion = openai.ChatCompletion.create(
        model = current_model,
        messages=messages,
        max_tokens=2000,
        temperature=0.5,
        timeout=180,
        stream=False
    )
    return сompletion["choices"][0]["message"]["content"]


def ai(prompt: str = '', temp: float = 0.5, max_tok: int = 2000, timeou: int = 180, messages = None, chat_id = None) -> str:
    """Сырой текстовый запрос к GPT чату, возвращает сырой ответ
    second - использовать ли второй гейт и ключ, для больших запросов
    """
    global CUSTOM_MODELS

    print(cfg.model, len(prompt))

    openai.api_key = cfg.key_ckt1031
    openai.api_base = cfg.openai_api_base_ckt1031

    if messages == None:
        assert prompt != '', 'prompt не может быть пустым'
        messages = [{"role": "system", "content": """Ты искусственный интеллект отвечающий на запросы юзера."""},
                    {"role": "user", "content": prompt}]

    current_model = cfg.model
    if chat_id and chat_id in CUSTOM_MODELS:
        current_model = CUSTOM_MODELS[chat_id]

    completion = None

    for _ in range(3):
        try:
            # тут можно добавить степень творчества(бреда) от 0 до 1 дефолт - temperature=0.5
            completion = openai.ChatCompletion.create(
                model = current_model,
                messages=messages,
                max_tokens=max_tok,
                temperature=temp,
                timeout=timeou
            )
            response = completion.choices[0].message.content
        except Exception as unknown_error1:
            if 'HTTP code 500 from API' in str(unknown_error1):
                time.sleep(2)
                continue
            if str(unknown_error1).startswith('HTTP code 200 from API'):
                # ошибка парсера json?
                text = str(unknown_error1)[24:]
                lines = [x[6:] for x in text.split('\n') if x.startswith('data:') and ':{"content":"' in x]
                content = ''
                for line in lines:
                    parsed_data = json.loads(line)
                    content += parsed_data["choices"][0]["delta"]["content"]
                return content
            print(unknown_error1)
            return ''
    if completion:
        return сompletion["choices"][0]["message"]["content"]
    else:
        return ''


if __name__ == '__main__':
    if cfg.all_proxy:
        os.environ['all_proxy'] = cfg.all_proxy


    for _ in range(20):
        print(ai('привет. одна цифра и вопрос в ответе должна быть и никаких слов. вопрос - 1+2='))
    #print(ai(open('1.txt','r', encoding='utf-8').read()[:25000]))
    sys.exit()

    if len(sys.argv) != 2:
        print("Usage: gptbasic.py filename|'request to qpt'")
        sys.exit(1)
    t = sys.argv[1]
    if os.path.exists(t):
        print(ai(open(t).read(), max_tok = 2000, second = True))
    else:
        print(ai(t, max_tok = 2000))
