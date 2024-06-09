#!/usr/bin/env python3


import io
import os
import subprocess

import PyPDF2
import pandas as pd

import my_log
import utils


pandoc_cmd = 'pandoc'
catdoc_cmd = 'catdoc'


def fb2_to_text(data: bytes, ext: str = '') -> str:
    """convert from fb2 or epub (bytes) and other types of books file to string"""
    input_file = utils.get_tmp_fname()

    open(input_file, 'wb').write(data)

    ext = ext.lower()
    if ext.startswith('.'):
        ext = ext[1:]

    book_type = ext

    if 'epub' in book_type:
        proc = subprocess.run([pandoc_cmd, '-f', 'epub', '-t', 'plain', input_file], stdout=subprocess.PIPE)
    elif 'docx' in book_type:
        proc = subprocess.run([pandoc_cmd, '-f', 'docx', '-t', 'plain', input_file], stdout=subprocess.PIPE)
    elif 'html' in book_type:
        proc = subprocess.run([pandoc_cmd, '-f', 'html', '-t', 'plain', input_file], stdout=subprocess.PIPE)
    elif 'odt' in book_type:
        proc = subprocess.run([pandoc_cmd, '-f', 'odt', '-t', 'plain', input_file], stdout=subprocess.PIPE)
    elif 'rtf' in book_type:
        proc = subprocess.run([pandoc_cmd, '-f', 'rtf', '-t', 'plain', input_file], stdout=subprocess.PIPE)
    elif 'doc' in book_type:
        proc = subprocess.run([catdoc_cmd, input_file], stdout=subprocess.PIPE)
    elif 'pdf' in book_type:
        pdf_reader = PyPDF2.PdfReader(input_file)
        text = ''
        for page in pdf_reader.pages:
            text += page.extract_text()
        utils.remove_file(input_file)
        return text
    elif book_type in ('xlsx', 'ods'):
        df = pd.DataFrame(pd.read_excel(io.BytesIO(data)))
        buffer = io.StringIO()
        df.to_csv(buffer)
        utils.remove_file(input_file)
        return buffer.getvalue()
    elif 'fb2' in book_type:
        proc = subprocess.run([pandoc_cmd, '-f', 'fb2', '-t', 'plain', input_file], stdout=subprocess.PIPE)
    else:
        utils.remove_file(input_file)
        try:
            result = data.decode('utf-8').replace(u'\xa0', u' ')
        except Exception as error:
            my_log.log2(f'my_pandoc:fb2_to_text other type error {error}')

    utils.remove_file(input_file)

    output = proc.stdout.decode('utf-8', errors='replace')

    return output


if __name__ == '__main__':
    result = fb2_to_text(open('1.fb2', 'rb').read(), '.fb2')

    print(result)
