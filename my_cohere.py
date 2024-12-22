#!/usr/bin/env python3

import random
import traceback

import cohere

import cfg
import my_log


# MAX_SUM_REQUEST = 128 * 1000 * 3
MAX_QUERY_LENGTH = 150000
MAX_SUM_REQUEST = 150000
DEFAULT_MODEL = 'command-r-plus'
FALLBACK_MODEL = 'command-r'


# co = cohere.ClientV2(cfg.COHERE_AI_KEYS[0])

# response = co.chat(
#     model="command-r-plus",
#     messages=[{"role": "user", "content": "hi"}],
# )

# print(response.message.content[0].text)


def ai(prompt: str = '',
       system: str = '',
       mem_ = [],
       temperature: float = 1,
       model_: str = '',
       max_tokens_: int = 4000,
       key_: str = '',
       timeout: int = 180,
       json_output: bool = False,
       ) -> str:
    """
    Generates a response using the cohere AI model.

    Args:
        prompt (str, optional): The user's input prompt. Defaults to ''.
        system (str, optional): The system's initial message. Defaults to ''.
        mem_ (list, optional): The list of previous messages. Defaults to [].
        temperature (float, optional): The randomness of the generated response. Defaults to 1.
        model_ (str, optional): The name of the cohere model to use. Defaults to DEFAULT_MODEL.
        max_tokens_ (int, optional): The maximum number of tokens in the generated response. Defaults to 2000.
        key_ (str, optional): The API key for the cohere model. Defaults to ''.

    Returns:
        str: The generated response from the cohere AI model. Returns an empty string if error.

    Raises:
        Exception: If an error occurs during the generation of the response. The error message and traceback are logged.
    """
    try:
        mem = []
        if mem_:
            if system:
                mem.append({'role': 'system', 'content': system})
                mem += mem_
                if prompt:
                    mem.append({'role': 'user', 'content': prompt})
            else:
                mem = mem_
                if prompt:
                    mem.append({'role': 'user', 'content': prompt})
        else:
            if system:
                mem.append({'role': 'system', 'content': system})
            if prompt:
                mem.append({'role': 'user', 'content': prompt})

        if not mem:
            return ''

        if key_:
            keys = [key_, ]
        else:
            keys = cfg.COHERE_AI_KEYS
            random.shuffle(keys)
            keys = keys[:4]

        model = model_ if model_ else DEFAULT_MODEL

        max_mem = MAX_QUERY_LENGTH

        while token_count(mem) > max_mem + 100:
            mem = mem[2:]

        for key in keys:
            client = cohere.ClientV2(cfg.COHERE_AI_KEYS[0], timeout = timeout)

            if json_output:
                resp_type = 'json_object'
            else:
                resp_type = 'text'
            try:
                response = client.chat(
                    messages=mem,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens_,
                    response_format = {"type": resp_type},
                )
            except Exception as error:
                my_log.log_cohere(f'ai: {error}\n\n{prompt}\n\n{system}\n\n{mem_}\n{temperature}\n{model_}\n{max_tokens_}\n{key_}\n{key}')
                continue
            try:
                resp = response.message.content[0].text.strip()
            except Exception as error2:
                my_log.log_cohere(f'ai: {error2}\n\n{prompt}\n\n{system}\n\n{mem_}\n{temperature}\n{model_}\n{max_tokens_}\n{key_}\n{key}')
                resp = ''
            if resp:
                return resp
        return ''
    except Exception as error2:
        error_traceback = traceback.format_exc()
        my_log.log_cohere(f'my_groq:ai: {error2}\n\n{error_traceback}\n\n{prompt}\n\n{system}\n\n{mem_}\n{temperature}\n{model_}\n{max_tokens_}\n{key_}')

    return ''


def token_count(mem, model:str = "") -> int:
    '''broken, only counts symbols not tokens'''
    if isinstance(mem, str):
        text = mem
    else:
        text = ' '.join([m['content'] for m in mem])
    l = len(text)
    return l


def sum_big_text(text:str, query: str, temperature: float = 1, model = DEFAULT_MODEL) -> str:
    """
    Generates a response from an AI model based on a given text,
    query, and temperature.

    Args:
        text (str): The complete text to be used as input.
        query (str): The query to be used for generating the response.
        temperature (float, optional): The temperature parameter for controlling the randomness of the response. Defaults to 0.1.

    Returns:
        str: The generated response from the AI model.
    """
    query = f'''{query}\n\n{text[:MAX_SUM_REQUEST]}'''
    r = ai(query, temperature=temperature, model_ = model)
    if not r and model == DEFAULT_MODEL:
        r = ai(query, temperature=temperature, model_ = FALLBACK_MODEL)
    return r


if __name__ == '__main__':
    pass

    # r = ai('привет как дела')
    # print(r)

    with open('C:/Users/user/Downloads/2.txt', 'r', encoding='utf-8') as f:
        text = f.read()
    print(sum_big_text(text, 'сделай подробный пересказ по тексту'))