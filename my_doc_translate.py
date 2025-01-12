#!/usr/bin/env python3


import my_pandoc
import my_gemini
import my_groq


def translate_text(text: str, src: str, dst: str) -> str:
    '''
    Translate text with ai
    '''
    help = 'Надо перевести текст сохраняя форматирование html, перевод надо выполнить как его сделал бы профессиональный переводчик с большим опытом'
    result = my_gemini.translate(text, src, dst, help = help)
    if not result:
        result = my_groq.translate(text, src, dst, help = help)
    return result or ''


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
    text = my_pandoc.convert_file_to_html(data, filename=fname)

    chunks = split_text(text)

    result = ''
    for chunk in chunks:
        r = translate_text(chunk, src, dst)
        result += r

    new_data = my_pandoc.convert_html_to_bytes(result, fname)

    return new_data


if __name__ == '__main__':
    pass
    my_groq.load_users_keys()
    my_gemini.load_users_keys()


    with open('c:/Users/user/Downloads/1.docx', 'rb') as f:
        data = f.read()
        new_data = translate_file(data, 'en', 'ru', '1.docx')
        with open('c:/Users/user/Downloads/2.docx', 'wb') as f:
            f.write(new_data)
