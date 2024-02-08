#!/usr/bin/env python3
# pip install unofficial-claude2-api

from sys import exit as sys_exit
from claude2_api.session import SessionData
from claude2_api.client import ClaudeAPIClient, SendMessageResponse, HTTPProxy, SOCKSProxy
from claude2_api.errors import ClaudeAPIError, MessageRateLimitError, OverloadError
from fake_useragent import UserAgent
from claude2_api.session import get_session_data


if __name__ == '__main__':
    ua = UserAgent(browsers=["firefox"])
    cookie_header_value  = cfg.cookie_header_value
    user_agent = ua.random
    organization_id = None
    # Create SOCKSProxy instance
    socks_proxy = SOCKSProxy(
        "172.28.1.5",    # Proxy IP
        1080,                   # Proxy port
        version_num=5           # Either 4 or 5, defaults to 4
    )

    session = SessionData(cookie_header_value, user_agent, organization_id)
    # List of attachments filepaths, up to 5, max 10 MB each
    FILEPATH_LIST = [
        "test1.txt",
        "test2.txt",
    ]
    
    session = SessionData(cookie_header_value, user_agent, organization_id)

    client = ClaudeAPIClient(session, timeout=240, proxy=socks_proxy)

    chat_id = client.create_chat()
    if not chat_id:
        print("\nMessage limit hit, cannot create chat...")
        sys_exit(1)

    try:
        res: SendMessageResponse = client.send_message(
            chat_id, "Hello!",
            # attachment_paths=FILEPATH_LIST
        )
        # Inspect answer
        if res.answer:
            print(res.answer)
        else:
            # Inspect response status code and raw answer bytes
            print(f"\nError code {res.status_code}, raw_answer: {res.raw_answer}")
    except ClaudeAPIError as e:
        # Identify the error
        if isinstance(e, MessageRateLimitError):
            # The exception will hold these informations about the rate limit:
            print(f"\nMessage limit hit, resets at {e.reset_date}")
            print(f"\n{e.sleep_sec} seconds left until -> {e.reset_timestamp}")
        elif isinstance(e, OverloadError):
            print(f"\nOverloaded error: {e}")
        else:
            print(f"\nGot unknown Claude error: {e}")
    finally:
        # Perform chat deletion for cleanup
        client.delete_chat(chat_id)

    # Get a list of all chats ids
    all_chat_ids = client.get_all_chat_ids()
    # Delete all chats
    for chat in all_chat_ids:
        client.delete_chat(chat)

    # Or by using a shortcut utility
    client.delete_all_chats()
    sys_exit(0)