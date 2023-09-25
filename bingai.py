#!/usr/bin/env python3


import asyncio
import json
import re
import threading
import time
import queue

from re_edge_gpt import Chatbot, ConversationStyle, ImageGen

import my_log


DIALOGS = {}
CHAT_LOCKS = {}
# {id:fifo queue}
DIALOGS_QUEUE = {}
FINAL_SIGN = '85db82jbdv9874h5896sdjf7598lng07234bhlkjh'


lock_gen_img = threading.Lock()


def reset_bing_chat(chat_id: str):
    try:
        chat('', chat_id, reset=True)
    except Exception as error2:
        my_log.log2(f'bingai.reset_bing_chat: {error2}')
        print(f'bingai.reset_bing_chat: {error2}')


async def chat_async(query: str, dialog: str, style = 3, reset = False):
    """
    Asynchronously chats with a chatbot using the specified query and dialog.

    Args:
        query (str): The query to send to the chatbot.
        dialog (str): The identifier of the dialog to use.
        style (int, optional): The conversation style to use. Defaults to 3.
        reset (bool, optional): Whether to reset the dialog before sending the query. Defaults to False.

    Returns:
        dict: A dictionary containing the chatbot's response, including the text, suggestions, 
              number of messages left, and maximum number of messages.

    Raises:
        KeyError: If the specified dialog does not exist in the DIALOGS dictionary.
        Exception: If an error occurs while communicating with the chatbot.

    Note:
        The function first checks if the `reset` flag is set to `True`. If so, it closes the dialog, 
        removes it from the DIALOGS dictionary, and returns. If the specified dialog does 
        not exist in the DIALOGS dictionary, the function creates a new chatbot instance using the 
        cookies loaded from the "cookies.json" file. It then sends the query to the chatbot and 
        retrieves the response. The function replaces any reference links in the response text with 
        actual URLs from the `sources_text` field. Finally, it returns a dictionary containing the 
        chatbot's response, including the text, suggestions, number of messages left, and maximum number 
        of messages.
    """
    if reset:
        try:
            await DIALOGS[dialog].close()
        except KeyError:
            print(f'bingai.chat_async:1:no such key in DIALOGS: {dialog}')
            my_log.log2(f'bingai.chat_async:1:no such key in DIALOGS: {dialog}')
        try:
            del DIALOGS[dialog]
        except KeyError:
            print(f'bingai.chat_async:2:no such key in DIALOGS: {dialog}')
            my_log.log2(f'bingai.chat_async:2:no such key in DIALOGS: {dialog}')
        return

    if style == 1:
        st = ConversationStyle.precise
    elif style == 2:
        st = ConversationStyle.balanced
    elif style == 3:
        st = ConversationStyle.creative

    if dialog not in DIALOGS:
        cookies = json.loads(open("cookies.json", encoding="utf-8").read())
        DIALOGS[dialog] = await Chatbot.create(cookies=cookies)

    try:
        r = await DIALOGS[dialog].ask(prompt=query, conversation_style=st, simplify_response=True)
    except Exception as error:
        #sys.stdout, sys.stderr = orig_stdout, orig_stderr
        print(f'bingai.chat_async:2: {error}')
        my_log.log2(f'bingai.chat_async:2: {error}')
        try:
            await DIALOGS[dialog].close()
        except KeyError:
            print(f'bingai.chat_async:3:no such key in DIALOGS: {dialog}')
            my_log.log2(f'bingai.chat_async:3:no such key in DIALOGS: {dialog}')
        try:
            del DIALOGS[dialog]
        except KeyError:
            print(f'bingai.chat_async:4:no such key in DIALOGS: {dialog}')
            my_log.log2(f'bingai.chat_async:4:no such key in DIALOGS: {dialog}')
        return error
    text = r['text']
    suggestions = r['suggestions']
    messages_left = r['messages_left']
    messages_max = r['max_messages']

    sources_text = r['sources_text']

    urls = re.findall(r'\[(.*?)\]\((.*?)\)', sources_text)
    urls2 = []
    for _, url in urls:
        urls2.append(url.strip())

    def replace_links(match):
        index = int(match.group(1)) - 1
        if index < len(urls2):
            return f'({urls2[index]})'
        else:
            return match.group(0)

    def replace_links2(match):
        index = int(match.group(1)) - 1
        if index < len(urls2):
            return f' [«{index+1}»]({urls2[index]})'
        else:
            return match.group(0)

    my_log.log2(text)
    text = re.sub(r'\[\^(\d{1,2})\^\]', replace_links2, text)
    text = re.sub(r'\(\^(\d{1,2})\^\)', replace_links, text)
    my_log.log2(text)

    return {'text': text, 'suggestions': suggestions, 'messages_left': messages_left, 'messages_max': messages_max}


def chat(query: str, dialog: str, style: int = 3, reset: bool = False):
    """
    This function is used to chat with a bing. It takes in a query string,
    a dialog id, and optional parameters for style and reset. It returns a string as the chat response.
    
    Parameters:
    - query (str): The input query for the dialog system.
    - dialog (str): The current dialog id.
    - style (int, optional): The style parameter for the chat. Defaults to 3.
    - reset (bool, optional): Whether to reset the dialog. Defaults to False.
    
    Returns:
    - Dictionary: The chat response as a dictionary with the keys 'text', 'suggestions', 'messages_left', and 'messages_max'.
    """
    if dialog in CHAT_LOCKS:
        lock = CHAT_LOCKS[dialog]
    else:
        lock = threading.Lock()
        CHAT_LOCKS[dialog] = lock
    with lock:
        try:
            result = asyncio.run(chat_async(query, dialog, style, reset))
        except Exception as error:
            print(f'my_bingai.chat: {error}')
            my_log.log2(f'my_bingai.chat: {error}')
            result = asyncio.run(chat_async(query, dialog, style, reset))
        if not result:
            try:
                result = asyncio.run(chat_async(query, dialog, style, reset))
            except Exception as error2:
                print(f'my_bingai.chat:2: {error2}')
                my_log.log2(f'my_bingai.chat:2: {error2}')
                result = asyncio.run(chat_async(query, dialog, style, reset))
    return result


async def main(prompt1: str, style: int = 3) -> str:
    """
    Asynchronous function that takes a prompt and a style as input and returns a string.

    Args:
        prompt1 (str): The prompt for the chatbot.
        style (int, optional): The style of the conversation. Defaults to 3.

    Returns:
        str: The response text from the chatbot.
    """
    if style == 1:
        st = ConversationStyle.precise
    elif style == 2:
        st = ConversationStyle.balanced
    elif style == 3:
        st = ConversationStyle.creative

    cookies = json.loads(open("cookies.json", encoding="utf-8").read())
    
    try:
        bot = await Chatbot.create(cookies=cookies)
        r = await bot.ask(prompt=prompt1, conversation_style=st, simplify_response=True)
    except Exception as error:
        #sys.stdout, sys.stderr = orig_stdout, orig_stderr
        print(f'my_bingai.main: {error}')
        my_log.log2(f'my_bingai.main: {error}')
        return ''
    await bot.close()

    text = r['text']
    sources_text = r['sources_text']

    urls = re.findall(r'\[(.*?)\]\((.*?)\)', sources_text)
    urls2 = []
    for _, url in urls:
        urls2.append(url.strip())

    def replace_links(match):
        index = int(match.group(1)) - 1
        if index < len(urls2):
            return f'({urls2[index]})'
        else:
            return match.group(0)

    def replace_links2(match):
        index = int(match.group(1)) - 1
        if index < len(urls2):
            return f' [«{index+1}»]({urls2[index]})'
        else:
            return match.group(0)

    text = re.sub(r'\[\^(\d{1,2})\^\]', replace_links2, text)
    text = re.sub(r'\(\^(\d{1,2})\^\)', replace_links, text)

    return text


def ai(prompt: str, style: int = 3) -> str:
    print('bing', len(prompt))
    return asyncio.run(main(prompt, style))


def gen_imgs(prompt: str):
    """
    Generates images based on a prompt.

    Args:
        prompt (str): The prompt used to generate the images.

    Returns:
        Union[str, List[str]]: The generated images as a list of strings, or an error message if the generation fails.

    Raises:
        None
    """
    with lock_gen_img:
        with open("cookies.json") as f:
            c = json.load(f)
            for ck in c:
                if ck["name"] == "_U":
                    auth = ck["value"]
                    break

        if auth:
            image_gen = ImageGen(auth, quiet = True)

            try:
                images = image_gen.get_images(prompt)
            except Exception as error:
                if 'Your prompt has been blocked by Bing. Try to change any bad words and try again.' in str(error):
                    return 'Бинг отказался это рисовать.'
                print(f'my_bingai.gen_imgs: {error}')
                my_log.log2(f'my_bingai.gen_imgs: {error}')
                return str(error)

            return images

        return 'No auth provided'


async def chat_async_stream(query: str, dialog: str, style = 3, reset = False):
    """
    Asynchronously streams a chat response based on a given query and dialog.

    Args:
        query (str): The query string for the chat.
        dialog (str): The dialog identifier.
        style (int, optional): The conversation style. Defaults to 3.
        reset (bool, optional): Whether to reset the dialog. Defaults to False.

    Returns:

    """
    if reset:
        try:
            await DIALOGS[dialog].close()
        except KeyError:
            print(f'bingai.chat_async_stream:1:no such key in DIALOGS: {dialog}')
            my_log.log2(f'bingai.chat_async_stream:1:no such key in DIALOGS: {dialog}')
        try:
            del DIALOGS[dialog]
        except KeyError:
            print(f'bingai.chat_async_stream:2:no such key in DIALOGS: {dialog}')
            my_log.log2(f'bingai.chat_async_stream:2:no such key in DIALOGS: {dialog}')
        return

    if style == 1:
        st = ConversationStyle.precise
    elif style == 2:
        st = ConversationStyle.balanced
    elif style == 3:
        st = ConversationStyle.creative

    if dialog not in DIALOGS:
        cookies = json.loads(open("cookies.json", encoding="utf-8").read())
        DIALOGS[dialog] = await Chatbot.create(cookies=cookies)
        DIALOGS_QUEUE[dialog] = queue.Queue()

    try:
        wrote = 0
        async for final, response in DIALOGS[dialog].ask_stream(prompt=query, conversation_style=st, search_result=False,
                                                                locale='ru'):
            if not final:
                if response[wrote:].startswith('```json'):
                    wrote = len(response)
                    continue
            if not final:
                # print(response[wrote:], end='')
                # yield response[wrote:]
                DIALOGS_QUEUE[dialog].put_nowait(response[wrote:])
            wrote = len(response)
        DIALOGS_QUEUE[dialog].put_nowait(FINAL_SIGN)
    except Exception as error:
        print(f'bingai.chat_async_stream:2: {error}')
        my_log.log2(f'bingai.chat_async_stream:2: {error}')


def chat_stream(query: str, dialog: str, style: int = 3, reset: bool = False) -> str:
    if dialog in CHAT_LOCKS:
        lock = CHAT_LOCKS[dialog]
    else:
        lock = threading.Lock()
        CHAT_LOCKS[dialog] = lock

    with lock:
        try:
            asyncio.run(chat_async_stream(query, dialog, style, reset))
        except Exception as error:
            print(f'my_bingai.chat_stream: {error}')
            my_log.log2(f'my_bingai.chat_stream: {error}')
            asyncio.run(chat_async_stream(query, dialog, style, reset))


def stream_sync_request(query: str):
    """test for chat_stream"""
    thread = threading.Thread(target=chat_stream, args=(query, '0', 3, False))
    thread.start()
    
    while thread.is_alive():
        time.sleep(0.1)
        try:
            chunk = DIALOGS_QUEUE['0'].get_nowait()
            if FINAL_SIGN in chunk:
                chunk = chunk.replace(FINAL_SIGN, '')
                print(chunk, end='')
                break
            print(chunk, end='')
        except KeyError:
            pass
        except queue.Empty:
            pass


if __name__ == "__main__":
    # print(chat('brent oil price', 'test-chat-id', 3, False)['text'])
    #print(ai('hi'))

    #stream_sync_request('brent oil price')

    prompt = 'dogs'
    print(gen_imgs(prompt))


    # """Usage ./bingai.py 'list 10 japanese dishes"""
    # t = sys.argv[1]
    # print(ai(t))
