#!/usr/bin/env python3
# pip install telegraph


import traceback

from sqlitedict import SqliteDict
from telegraph import Telegraph

import my_log


# {userid: token,}
TOKENS = SqliteDict('db/telegraph_tokens.db', autocommit=True)


def post(text: str, user_id: str) -> str:
    try:
        if user_id in TOKENS:
            token = TOKENS[user_id] 
            telegraph = Telegraph(access_token=token)
        else:
            telegraph = Telegraph()
            telegraph.create_account(short_name='kun4sun_bot', author_name='kun4sun_bot', author_url='https://t.me/kun4sun_bot')
            token = telegraph.get_access_token()
            if token:
                TOKENS[user_id] = token
            else:
                return None

        response = telegraph.create_page(
            f'kun4sun_bot - {str(hash(user_id))[:-8]}',
            html_content=text,
        )
        return response['url']
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'my_telegraph:post: {error}\n\n{traceback_error}\n\n{text}\n\n{user_id}')
        return None


if __name__ == '__main__':
    pass
    p1 = '''
hi

'''
    p2 = '<p>!!!Этот абзац содержит!!! <strong>много текста</strong>, включая <a href="https://example.com">ссылку</a> и <em>выделенный текст</em>. Он также содержит специальный символ &amp; и тег изображения <img src="image.jpg" alt="Пример изображения"></p>'
    print(post(p1, '[1234567890] [0]'))
    # print(post(p2, '[1234567890] [0]'))
