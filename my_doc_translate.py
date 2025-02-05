#!/usr/bin/env python3


import time
import uuid

import my_pandoc

import cfg
import my_db
import my_gemini
import my_groq
from utils import async_run_with_limit
from my_doc_translate_cache import TextCache


TRANSLATE_CACHE = None


def get_prompt_dialog(dst: str) -> str:
    '''
    Get prompt for ai
    '''
    help = (
        f'Делаем качественный художественный перевод текста на язык [{dst}]. '
        'Можешь использовать синонимы что бы сделать текст более художественным. '
        'Я посылаю тебе куски текста один за другим а ты делаешь перевод и показываешь мне '
        'только перевод без комментариев и лишних слов. '
        'Сохраняй оригинальное форматирование, абзацы, переносы строк итп.'
    )
    return help


def get_prompt(dst: str) -> str:
    '''
    Get prompt for ai
    '''
    help = (
        f'Делаем качественный художественный перевод текста на язык [{dst}]. '
        'Можешь использовать синонимы что бы сделать текст более художественным. '
        'Сохраняй оригинальное форматирование, теги, абзацы, переносы строк итп.'
    )
    return help


@async_run_with_limit(max_threads=1)
def translate_text(text: str, src: str, dst: str, results: dict, index: int) -> str:
    '''
    Translate text with ai
    results - dict[index] = text (translated or original(fail to translate))
    '''
    help = get_prompt(dst)
    result = my_gemini.translate(text, src, dst, help = help)
    if not result:
        result = my_groq.translate(text, src, dst, help = help)

    results[index] = result or text


def translate_text_in_dialog(chunk: str, dst: str, chat_id: str) -> str:
    '''
    Translate text in dialog mode with gemini
    '''
    global TRANSLATE_CACHE

    if not TRANSLATE_CACHE:
        TRANSLATE_CACHE = TextCache('db/translate_cache.db', 1000)

    if chunk in TRANSLATE_CACHE and TRANSLATE_CACHE[chunk]:
        return TRANSLATE_CACHE[chunk]


    help = get_prompt_dialog(dst)

    r = my_gemini.chat(
        query=chunk,
        chat_id = chat_id,
        model=cfg.gemini_flash_model,
        system = help,
        temperature=0.3,
        max_tokens=int(len(chunk)/2),
        max_chat_lines=3,
        do_not_update_history=True,
        )

    if not r:
        r = my_gemini.chat(
            query=chunk,
            chat_id = chat_id,
            model=cfg.gemini_flash_model_fallback,
            system = help,
            temperature=0.3,
            max_tokens=int(len(chunk)/2),
            max_chat_lines=3,
            do_not_update_history=True,
            )

    if r:
        TRANSLATE_CACHE.add(chat_id, chunk, r)

    return r or chunk


def split_text(text: str, chunk_size: int = 5000) -> list[str]:
    """
    Splits the input text into chunks, respecting the maximum chunk size.
    Handles lines longer than chunk_size by splitting them into smaller parts.

    Args:
        text: The input text to be split.
        chunk_size: The maximum size of each chunk.

    Returns:
        A list of text chunks.
    """
    chunks: list[str] = []
    current_chunk: str = ""

    for line in text.splitlines():
        # Если строка длиннее чем chunk_size, разбиваем ее на части
        if len(line) > chunk_size:
            for i in range(0, len(line), chunk_size):
                sub_line = line[i:i + chunk_size]
                # проверяем, поместится ли sub_line в текущий чанк
                if len(current_chunk) + len(sub_line) + 1 <= chunk_size:
                     current_chunk += sub_line + "\n"
                else:
                    chunks.append(current_chunk.strip())
                    current_chunk = sub_line + "\n"

        # Если строка не превышает chunk_size, добавляем ее в текущий чанк
        else:
            if len(current_chunk) + len(line) + 1 <= chunk_size:
                current_chunk += line + "\n"
            else:
                chunks.append(current_chunk.strip())
                current_chunk = line + "\n"
    
    # добавляем последний чанк
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    return chunks


def translate_file(data: bytes, src: str, dst: str, fname: str) -> bytes:
    '''
    Translate document file.
    1. Convert to markdown with pandoc
    2. split to chunks
    3. Translate with google gemini
    4. convert back to document with pandoc
    '''
    if isinstance(data, str):
        text = data
    else:
        # Convert the document to HTML using pandoc
        text = my_pandoc.convert_file_to_html(data, filename=fname)

    # Split the HTML into chunks for translation
    chunks = split_text(text)

    # Create a dictionary to store the translated chunks
    results: dict[int, str] = {}
    index = 1
    # Translate each chunk asynchronously
    for chunk in chunks:
        translate_text(chunk, src, dst, results=results, index=index)
        index += 1

    # Wait for all translations to complete
    while len(results) != len(chunks):
        time.sleep(1)

    # Concatenate the translated chunks
    translated_text = ""
    for i in range(1, len(chunks) + 1):
        translated_text += results[i] + "\n"

    # Convert the translated HTML back to the original document format using pandoc
    new_data = my_pandoc.convert_html_to_bytes(translated_text, fname)

    return new_data


def translate_file_in_dialog(data: bytes, src: str, dst: str, fname: str, chat_id_full: str) -> bytes:
    '''
    Translate document file in dialog mode.
    1. Convert to markdown with pandoc
    2. split to chunks
    3. Translate with google gemini
    4. convert back to document with pandoc
    '''
    if isinstance(data, str):
        with open(data, 'rb') as f:
            data = f.read()

    # Convert the document to HTML using pandoc
    text = my_pandoc.convert_file_to_html(data, filename=fname)

    # Split the HTML into chunks for translation
    chunks = split_text(text)

    result = ''
    chat_id = 'translate_doc_' + str(uuid.uuid4())

    for chunk in chunks:
        result += translate_text_in_dialog(chunk, dst, chat_id)
        if result and result.strip():
            my_db.add_msg(chat_id_full, 'gemini')

    my_gemini.reset(chat_id)

    # Convert the translated HTML back to the original document format using pandoc
    new_data = my_pandoc.convert_html_to_bytes(result, fname)

    return new_data


if __name__ == '__main__':
    pass
    my_groq.load_users_keys()
    my_gemini.load_users_keys()
    my_db.init(backup=False)

    with open('c:/Users/user/Downloads/1.epub', 'rb') as f:
        data = f.read()
        # new_data = translate_file_in_dialog(data, 'en', 'ru', '1.epub')
        new_data = translate_file(data, 'en', 'ru', '1.epub')
        with open('c:/Users/user/Downloads/2.epub', 'wb') as f:
            f.write(new_data)

    my_db.close()
