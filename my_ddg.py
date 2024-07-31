#!/usr/bin/env python3
#pip install -U duckduckgo_search[lxml]


import io
import random
import time
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image

import langcodes
from duckduckgo_search import DDGS

import cfg
import my_db
import my_gemini
import my_log
import utils


# не принимать запросы больше чем, это ограничение для телеграм бота, в этом модуле оно не используется
MAX_REQUEST = 4000
MAX_LINES = 20

# Объекты для доступа к чату {id:DDG object}
CHATS_OBJ = {}

# хранилище диалогов {id:list(mem)}
# Эти диалоги на самом деле не работают, просто что бы были, нет смысла сохранять их на диск
CHATS = {}

# блокировка чатов что бы не испортить историю 
# {id:lock}
LOCKS = {}



def undo(chat_id: str):
    """
    Undo the last two lines of chat history for a given chat ID.

    Args:
        chat_id (str): The ID of the chat.

    Raises:
        Exception: If there is an error while undoing the chat history.

    Returns:
        None
    """
    try:
        if chat_id in CHATS:
            mem = CHATS[chat_id]
            # remove 2 last lines from mem
            mem = mem[:-2]
            CHATS[chat_id] = mem
    except Exception as error:
        my_log.log_ddg(f'Failed to undo chat {chat_id}: {error}')


def get_mem_as_string(chat_id: str) -> str:
    """
    Returns the chat history as a string for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to get the history for.

    Returns:
        str: The chat history as a string.
    """
    if chat_id not in CHATS:
        CHATS[chat_id] = []
    mem = CHATS[chat_id]
    result = ''
    for x in mem:
        role = x['role']
        if role == 'user': role = '𝐔𝐒𝐄𝐑'
        if role == 'assistant': role = '𝐁𝐎𝐓'

        text = x['content']

        if text.startswith('[Info to help you answer'):
            end = text.find(']') + 1
            text = text[end:].strip()
        result += f'{role}: {text}\n'
        if role == '𝐁𝐎𝐓':
            result += '\n'
    return result


def update_mem(query: str, resp: str, chat_id: str):
    if chat_id not in CHATS:
        CHATS[chat_id] = []

    mem = CHATS[chat_id]

    mem += [{'role': 'user', 'content': query}]
    mem += [{'role': 'assistant', 'content': resp}]

    mem = mem[-MAX_LINES*2:]

    CHATS[chat_id] = mem


def reset(chat_id: str):
    if chat_id in CHATS_OBJ:
        del CHATS_OBJ[chat_id]
    if chat_id in CHATS:
        del CHATS[chat_id]


def chat_new_connection():
    '''Connect with proxy and return object'''
    if hasattr(cfg, 'DDG_PROXY'):
        return DDGS(proxy=random.choice(cfg.DDG_PROXY), timeout=120)
    else:
        return DDGS(timeout=120)


def chat(query: str,
         chat_id: str,
         model: str = '',
         ) -> str:
    '''model = 'claude-3-haiku' | 'gpt-3.5' | 'llama-3-70b' | 'mixtral-8x7b' | 'gpt-4o-mini'
    '''

    if chat_id not in CHATS_OBJ:
        CHATS_OBJ[chat_id] = chat_new_connection()

    if not model:
        model='claude-3-haiku'

    if chat_id not in LOCKS:
        LOCKS[chat_id] = threading.Lock()

    with LOCKS[chat_id]:
        try:
            resp = CHATS_OBJ[chat_id].chat(query, model)
            my_db.add_msg(chat_id, model)
            update_mem(query, resp, chat_id)
            return resp
        except Exception as error:
            my_log.log_ddg(f'my_ddg:chat: {error}')
            time.sleep(2)
            try:
                CHATS_OBJ[chat_id] = chat_new_connection()
                reset(chat_id)
                resp = CHATS_OBJ[chat_id].chat(query, model)
                my_db.add_msg(chat_id, model)
                update_mem(query, resp, chat_id)
                return resp
            except Exception as error:
                my_log.log_ddg(f'my_ddg:chat: {error}')
                return ''


def get_links(query: str, max_results: int = 5) -> list:
    """
    Retrieves a list of links from the DuckDuckGo search engine based on the given query.

    Args:
        query (str): The search query.
        max_results (int, optional): The maximum number of results to return. Defaults to 5.

    Returns:
        list: A list of links found in the search results.

    Raises:
        Exception: If an error occurs during the search.

    Note:
        The `safesearch` parameter is set to 'off' to include potentially unsafe content in the search results.

    """
    try:
        results = chat_new_connection().text(query, max_results = max_results, safesearch='off')
        return [x['href'] for x in results]
    except Exception as error:
        my_log.log2(f'my_ddg:get_links: {error}')
        return []


def is_valid_image(data: bytes) -> bool:
    """
    Checks if the given bytes represent a valid image.

    Args:
        data: The image data as bytes.

    Returns:
        True if the data represents a valid image, False otherwise.
    """
    try:
        Image.open(io.BytesIO(data)).verify()
        return True
    except Exception:
        return False


def download_image_wrapper(image):
    data = utils.download_image_as_bytes(image[0])
    title = image[1]
    # detect if image is correct else data=None
    if not is_valid_image(data):
        data = None
    return (data, title)


def check_image_against_query(image) -> bool:
    """
    Check if an image is relevant to a given query by asking a superhot AI assistant.
    
    Args:
        image (tuple): A tuple containing the image data and the search query.
        
    Returns:
        bool: True if the image is relevant to the query, False otherwise.
    """
    query = f'''This image was found in google with the following query: {image[1]}

Decided if it is relevant to the query.
Answer supershot, your answer should be "yes" or "no" or "other".
'''
    result = my_gemini.img2txt(image[0], query)
    return True if 'yes' in result.lower() else False


def get_images(query: str, max_results: int = 16) -> list:
    """
    Retrieves a list of images from the DuckDuckGo search engine based on the given query.

    Args:
        query (str): The search query.
        max_results (int, optional): The maximum number of results to return. Defaults to 5.

    Returns:
        list: A list of image as [(downloaded bytes, title),...]

    Raises:
        Exception: If an error occurs during the search.

    Note:
        The `safesearch` parameter is set to 'off' to include potentially unsafe content in the search results.

    """
    results = chat_new_connection().images(
        keywords=query,
        region="wt-wt",
        safesearch="off",
        # size='Large',
        size='Wallpaper',
        color=None,
        type_image=None,
        layout=None,
        license_image=None,
        max_results=max_results,
    )

    images_with_data = [(x['image'], x['title']) for x in results]

    # Downloading images.
    with ThreadPoolExecutor() as executor:
        result = list(executor.map(download_image_wrapper, images_with_data))
    
    # Filter only images that were successfully downloaded.
    images_to_check = [(img_data, query) for img_data, _ in result if img_data]

    # Now we use ThreadPoolExecutor to check images against the query in parallel.
    relevant_images = []
    with ThreadPoolExecutor() as executor:
        # Submit all check_image_against_query tasks to the executor.
        future_to_image = {executor.submit(check_image_against_query, image): image for image in images_to_check}
        
        # Iterate over completed tasks.
        for future in as_completed(future_to_image):
            image = future_to_image[future]
            try:
                is_relevant = future.result()  # Getting the result from check_image_against_query.
                if is_relevant:
                    relevant_images.append(image)  # If relevant add to the results list.
            except Exception as exc:
                print(f'Image relevance check generated an exception: {exc}')
    
    # Sort by data size.
    sorted_images = sorted(relevant_images, key=lambda x: len(x[0]), reverse=True)

    # restore lost titles
    restored_images = []
    for i in result:
        data = i[0]
        title = i[1]
        for j in sorted_images[:10]:
            data2 = j[0]
            if data == data2:
                restored_images.append((data, title))

    return restored_images


def ai(query: str, model: str = 'claude-3-haiku') -> str:
    """
    Generates a response from an AI model based on a given query and model.

    Args:
        query (str): The input query for the AI model.
        model (str, optional): The model to use for generating the response. Defaults to 'claude-3-haiku'.

    Returns:
        str: The generated response from the AI model. If an error occurs during the chat, an empty string is returned.

    Raises:
        None

    Note:
        The `model` parameter can be either "gpt-3.5" or "claude-3-haiku". If an invalid model is provided,
        the default model 'claude-3-haiku' will be used.
    """
    # model = "gpt-3.5" or "claude-3-haiku"
    # start_time = time.time()
    try:
        results = chat_new_connection().chat(query, model=model)
    except Exception as error:
        my_log.log2(f'my_ddg:ai: {error}')
        time.sleep(2)
        try:
            results = chat_new_connection().chat(query, model=model)
        except Exception as error:
            my_log.log2(f'my_ddg:ai: {error}')
            return ''

    # end_time = time.time()
    # print(f'Elapsed time: {end_time - start_time:.2f} seconds, query size: {len(query)}, response size: {len(results)}, total size: {len(query) + len(results)}')
    return results


def chat_cli():
    """
    A function that provides a command-line interface for interacting with the DDG (DuckDuckGo) chatbot.

    This function creates an instance of the DDGS class with a timeout of 120 seconds.
    It then enters a loop where it prompts the user to input a query and sends
    it to the chatbot using the `chat` method of the DDGS instance.
    The response from the chatbot is then printed to the console.

    Parameters:
        None

    Returns:
        None
    """
    while 1:
        q = input('> ')
        if q == 'mem':
            print(get_mem_as_string('test'))
            continue
        # r = chat(q, 'test', model='mixtral-8x7b')
        # r = chat(q, 'test', model='llama-3-70b')
        # r = chat(q, 'test', model='claude-3-haiku')
        r = chat(q, 'test', model='gpt-4o-mini')
        # r = chat(q, 'test', model='gpt-3.5')
        print(r)
        print('')


def translate(text: str, from_lang: str = '', to_lang: str = '', help: str = '', censored: bool = False) -> str:
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
        my_log.log_translate(f'my_ddg:translate:error1: {error1}\n\n{error_traceback}')
        
    try:
        to_lang = langcodes.Language.make(language=to_lang).display_name(language='en')
    except Exception as error2:
        error_traceback = traceback.format_exc()
        my_log.log_translate(f'my_ddg:translate:error2: {error2}\n\n{error_traceback}')

    if help:
        query = f'Translate from language [{from_lang}] to language [{to_lang}], your reply should only be the translated text, this can help you to translate better [{help}]:\n\n{text}'
    else:
        query = f'Translate from language [{from_lang}] to language [{to_lang}], your reply should only be the translated text:\n\n{text}'

    translated = ai(query)
    return translated


if __name__ == '__main__':
    # my_db.init(backup=False)
    pass
    chat_cli()
    # my_db.close()
