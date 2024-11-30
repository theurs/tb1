#!/usr/bin/env python3
# pip install chatgpt-md-converter


from chatgpt_md_converter import telegram_format


def md2mdv2(markdown_text: str) -> str:
    formatted_text = telegram_format(markdown_text)
    return formatted_text


if __name__ == '__main__':
    pass
    print(md2mdv2("""Here is some **bold**, __underline__, and `inline code`.\n```python\nprint('Hello, world!')\n```"""))
