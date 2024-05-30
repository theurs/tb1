#!/usr/bin/env python3


import io
import os
import subprocess

import PyPDF2
import pandas as pd

import utils


pandoc_cmd = 'pandoc'
catdoc_cmd = 'catdoc'


def fb2_to_text(data: bytes, ext: str = '') -> str:
    """convert from fb2 or epub (bytes) and other types of books file to string"""
    input_file = utils.get_tmp_fname()

    open(input_file, 'wb').write(data)

    book_type = utils.mime_from_buffer(data)
    ext = ext.lower()
    if ext == 'ods':
        book_type = 'vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    elif ext == 'xlsx' or ext.lower() == 'xls':
        book_type = 'ms-excel'
    elif ext == 'rtf':
        book_type = 'rtf'
    elif ext  == 'docx':
        book_type = 'vnd.openxmlformats-officedocument.wordprocessingml.document'
    elif ext == 'doc':
        book_type = 'doc'

    if 'epub' in book_type:
        proc = subprocess.run([pandoc_cmd, '-f', 'epub', '-t', 'plain', input_file], stdout=subprocess.PIPE)
    elif 'vnd.openxmlformats-officedocument.wordprocessingml.document' in book_type:
        proc = subprocess.run([pandoc_cmd, '-f', 'docx', '-t', 'plain', input_file], stdout=subprocess.PIPE)
    elif 'html' in book_type:
        proc = subprocess.run([pandoc_cmd, '-f', 'html', '-t', 'plain', input_file], stdout=subprocess.PIPE)
    elif 'vnd.oasis.opendocument.text' in book_type:
        proc = subprocess.run([pandoc_cmd, '-f', 'odt', '-t', 'plain', input_file], stdout=subprocess.PIPE)
    elif 'rtf' in book_type:
        proc = subprocess.run([pandoc_cmd, '-f', 'rtf', '-t', 'plain', input_file], stdout=subprocess.PIPE)
    elif 'plain' in book_type:
        os.remove(input_file)
        return data.decode('utf-8').replace(u'\xa0', u' ')
    elif 'doc' in book_type:
        proc = subprocess.run([catdoc_cmd, input_file], stdout=subprocess.PIPE)
    elif 'pdf' in book_type:
        pdf_reader = PyPDF2.PdfReader(input_file)
        text = ''
        for page in pdf_reader.pages:
            text += page.extract_text()
        os.remove(input_file)
        return text
    elif 'ms-excel' in book_type or 'vnd.openxmlformats-officedocument.spreadsheetml.sheet' in book_type:
        df = pd.DataFrame(pd.read_excel(io.BytesIO(data)))
        buffer = io.StringIO()
        df.to_csv(buffer)
        os.remove(input_file)
        return buffer.getvalue()
    else:
        proc = subprocess.run([pandoc_cmd, '-f', 'fb2', '-t', 'plain', input_file], stdout=subprocess.PIPE)

    output = proc.stdout.decode('utf-8')

    os.remove(input_file)

    # result = output.replace(u'\xa0', u' ')
    result = output

    return result


def split_text_of_book(text: str, chunk_size: int) -> list:
    text = text.replace('\r', '')
    # сначала делим на абзацы
    new_text = ''
    for p in [x for x in text.split('\n\n')]:
        p = p.replace('\n', ' ')
        p = p.replace('  ', ' ')
        new_text = new_text + p + '\n\n'

    new_text = new_text.strip()

    return utils.split_text_my(new_text, chunk_size)


if __name__ == '__main__':
    result = fb2_to_text(open('1.doc', 'rb').read(), 'doc')

    # for i in split_text_of_book(result, 5000):
    #     print(i)

    print(result)
