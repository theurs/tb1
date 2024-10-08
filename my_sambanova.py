#!/usr/bin/env python3

import json
import random
import requests
import time
import traceback

import langcodes

import cfg
import my_db
import my_log
import utils


# free limit
MAX_REQUEST = 4096


def ai(prompt: str = '',
       system: str = '',
       model = '',
       temperature: float = 1,
       timeout: int = 120,
       json_output: bool = False,
       chat_id: str = '',
       ) -> str:

    if not hasattr(cfg, 'SAMBANOVA_KEYS'):
        return ''

    if not model:
        model = 'Meta-Llama-3.1-405B-Instruct' # 'Meta-Llama-3.1-70B-Instruct', 'Meta-Llama-3.1-8B-Instruct'

    if not temperature:
        temperature = 0.1
    if 'llama' in model.lower() and temperature > 0:
        temperature = temperature / 2

    mem_ = []
    if system:
        mem_ = [{'role': 'system', 'content': system}] + mem_
    if prompt:
        mem_ = mem_ + [{'role': 'user', 'content': prompt}]

    request_size = int(len(system) + len(prompt))
    max_tokens = MAX_REQUEST - request_size
    if max_tokens < 100:
        return ''

    if json_output:
        json_object = 'json_object'
    else:
        json_object = 'text'

    result = ''

    for _ in range(3):
        response = requests.post(
            url="https://api.sambanova.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {random.choice(cfg.SAMBANOVA_KEYS)}",
            },
            data=json.dumps({
                "model": model, # Optional
                "messages": mem_,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "response_format": {"type": json_object},
            }),
            timeout = timeout,
        )

        status = response.status_code
        if status == 200:
            if chat_id:
                my_db.add_msg(chat_id, model)
            try:
                result = response.json()['choices'][0]['message']['content'].strip()
                break
            except Exception as error:
                my_log.log_sambanova(f'Failed to parse response: {error}\n\n{str(response)}')
                result = ''
                time.sleep(2)
        else:
            my_log.log_sambanova(f'Bad response.status_code\n\n{str(response[:2000])}')
            time.sleep(2)

    return result


def translate(text: str, from_lang: str = '', to_lang: str = '', help: str = '', model: str = '') -> str:
    """
    Translates the given text from one language to another.
    
    Args:
        text (str): The text to be translated.
        from_lang (str, optional): The language of the input text. If not specified, the language will be automatically detected.
        to_lang (str, optional): The language to translate the text into. If not specified, the text will be translated into Russian.
        help (str, optional): Help text for tranlator.
        
    Returns:
        str: The translated text.
    """
    if from_lang == '':
        from_lang = 'autodetect'
    if to_lang == '':
        to_lang = 'ru'
    try:
        from_lang = langcodes.Language.make(language=from_lang).display_name(language='en') if from_lang != 'autodetect' else 'autodetect'
    except Exception as error1:
        error_traceback = traceback.format_exc()
        my_log.log_sambanova(f'translate:error1: {error1}\n\n{error_traceback}')
        
    try:
        to_lang = langcodes.Language.make(language=to_lang).display_name(language='en')
    except Exception as error2:
        error_traceback = traceback.format_exc()
        my_log.log_sambanova(f'translate:error2: {error2}\n\n{error_traceback}')

    if help:
        query = f'Translate from language [{from_lang}] to language [{to_lang}], your reply should only be the translated text, this can help you to translate better [{help}]:\n\n{text}'
    else:
        query = f'Translate from language [{from_lang}] to language [{to_lang}], your reply should only be the translated text:\n\n{text}'

    translated = ai(query, model=model, temperature=0.1)

    return translated or text


def get_reprompt_for_image(prompt: str, chat_id: str = '') -> tuple[str, str] | None:
    """
    Generates a detailed prompt for image generation based on user query and conversation history.

    Args:
        prompt: User's query for image generation.

    Returns:
        A tuple of two strings: (positive prompt, negative prompt) or None if an error occurred. 
    """

    result = ai(prompt, temperature=1.5, json_output=True, chat_id=chat_id)
    result_dict = utils.string_to_dict(result)
    if result_dict:
        try:
            return result_dict['reprompt'], result_dict['negative_reprompt']
        except:
            try:
                return result_dict['reprompt'], result_dict['negative_prompt']
            except:
                pass

    if hasattr(cfg, 'SAMBANOVA_KEYS'):
        my_log.log_sambanova(f'get_reprompt_for_image: FAILED {prompt}')

    return None


if __name__ == '__main__':
    pass
    my_db.init(backup=False)

    print(ai('напиши 100 слов самой жуткой лести', 'пиши большими буквами'))
    # print(translate('напиши 100 слов самой жуткой лести, пиши большими буквами', to_lang='en'))

    my_db.close()