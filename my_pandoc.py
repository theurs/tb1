#!/usr/bin/env python3


import io
import os
import subprocess

import PyPDF2
import pandas as pd
from pptx import Presentation

import my_log
import utils


pandoc_cmd = 'pandoc'
catdoc_cmd = 'catdoc'


def convert_md2mdtelegram(md: str) -> str:
    '''
    Convert markdown to markdown for telegram
    strike 
    
    '''




def fb2_to_text(data: bytes, ext: str = '', lang: str = '') -> str:
    """convert from fb2 or epub (bytes) and other types of books file to string"""
    if isinstance(data, str):
        with open(data, 'rb') as f:
            data = f.read()

    ext = ext.lower()
    if ext.startswith('.'):
        ext = ext[1:]

    input_file = utils.get_tmp_fname() + '.' + ext

    with open(input_file, 'wb') as f:
        f.write(data)

    book_type = ext

    if 'epub' in book_type:
        proc = subprocess.run([pandoc_cmd, '-f', 'epub', '-t', 'gfm', input_file], stdout=subprocess.PIPE)
    elif 'pptx' in book_type:
        text = read_pptx(input_file)
        utils.remove_file(input_file)
        return text
    elif 'docx' in book_type:
        proc = subprocess.run([pandoc_cmd, '-f', 'docx', '-t', 'gfm', input_file], stdout=subprocess.PIPE)
    elif 'html' in book_type:
        proc = subprocess.run([pandoc_cmd, '-f', 'html', '-t', 'gfm', input_file], stdout=subprocess.PIPE)
    elif 'odt' in book_type:
        proc = subprocess.run([pandoc_cmd, '-f', 'odt', '-t', 'gfm', input_file], stdout=subprocess.PIPE)
    elif 'rtf' in book_type:
        proc = subprocess.run([pandoc_cmd, '-f', 'rtf', '-t', 'gfm', input_file], stdout=subprocess.PIPE)
    elif 'doc' in book_type:
        proc = subprocess.run([catdoc_cmd, input_file], stdout=subprocess.PIPE)
    elif 'pdf' in book_type or 'djvu' in book_type:
        if 'djvu' in book_type:
            input_file = convert_djvu2pdf(input_file)

        pdf_reader = PyPDF2.PdfReader(input_file)
        text = ''
        for page in pdf_reader.pages:
            text += page.extract_text()

        utils.remove_file(input_file)
        return text
    elif book_type in ('xlsx', 'ods', 'xls'):
        xls = pd.ExcelFile(io.BytesIO(data))
        result = ''
        for sheet in xls.sheet_names:
            csv = xls.parse(sheet_name=sheet).to_csv(index=False)
            result += f'\n\n{sheet}\n\n{csv}\n\n'
        # df = pd.DataFrame(pd.read_excel(io.BytesIO(data)))
        # buffer = io.StringIO()
        # df.to_csv(buffer)
        utils.remove_file(input_file)
        # return buffer.getvalue()
        return result
    elif 'fb2' in book_type:
        proc = subprocess.run([pandoc_cmd, '-f', 'fb2', '-t', 'gfm', input_file], stdout=subprocess.PIPE)
    else:
        utils.remove_file(input_file)
        try:
            result = data.decode('utf-8').replace(u'\xa0', u' ')
            return result
        except Exception as error:
            my_log.log2(f'my_pandoc:fb2_to_text other type error {error}')
            return ''

    utils.remove_file(input_file)

    output = proc.stdout.decode('utf-8', errors='replace')

    return output


def read_pptx(input_file: str) -> str:
    """read pptx file"""
    prs = Presentation(input_file)
    text = ''
    for _, slide in enumerate(prs.slides):
        for shape in slide.shapes: 
            if hasattr(shape, "text"): 
                text += shape.text + '\n'
    return text


def convert_djvu2pdf(input_file: str) -> str:
    '''convert djvu to pdf and delete source file, return new file name'''
    output_file = input_file + '.pdf'
    subprocess.run(['ddjvu', '-format=pdf', input_file, output_file], check=True)
    utils.remove_file(input_file)
    return output_file


def convert_text_to_docx(text: str) -> bytes:
    '''convert text to docx file'''
    output_file = utils.get_tmp_fname() + '.docx'
    subprocess.run(['pandoc', '-f', 'markdown', '-t', 'docx', '-o', output_file, '-'], input=text.encode('utf-8'), stdout=subprocess.PIPE)
    with open(output_file, 'rb') as f:
        data = f.read()
    utils.remove_file(output_file)
    return data


def convert_text_to_odt(text: str) -> bytes:
    '''convert text to odt file'''
    output_file = utils.get_tmp_fname() + '.odt'
    subprocess.run(['pandoc', '-f', 'markdown', '-t', 'odt', '-o', output_file, '-'], input=text.encode('utf-8'), stdout=subprocess.PIPE)
    with open(output_file, 'rb') as f:
        data = f.read()
    utils.remove_file(output_file)
    return data


def convert_text_to_pdf(text: str) -> bytes:
    '''convert text to pdf file'''
    output_file = utils.get_tmp_fname() + '.pdf'
    subprocess.run(['pandoc', '-f', 'markdown', '-t', 'pdf', '-o', output_file, '-'], input=text.encode('utf-8'), stdout=subprocess.PIPE)
    with open(output_file, 'rb') as f:
        data = f.read()
    utils.remove_file(output_file)
    return data


if __name__ == '__main__':
    pass
    # result = fb2_to_text(open('c:/Users/user/Downloads/1.xlsx', 'rb').read(), '.xlsx')
    # result = fb2_to_text(open('1.pdf', 'rb').read(), '.pdf')
    # print(result)
    # print(convert_djvu2pdf('/home/ubuntu/tmp/2.djvu'))

    with open('c:/Users/user/Downloads/1.docx', 'rb') as f:
        print(fb2_to_text(f.read(), '.docx'))
