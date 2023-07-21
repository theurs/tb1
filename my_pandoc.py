#!/usr/bin/env python3


import pandoc
import PyPDF2

import my_log


def get_text_from_file(path_to_file: str):
    try:
        doc = pandoc.read(file=path_to_file)
        result = pandoc.write(doc, format = 'plain').strip()
    except Exception as error:
        if 'Pandoc can convert to PDF, but not from PDF' in str(error):
            text = ''
            pdf_reader = PyPDF2.PdfReader(path_to_file)
            for page in pdf_reader.pages:
                text += page.extract_text()
            return text
        else:
            print(error)
            my_log.log2(f'my_pandoc:get_text_from_file:{error}')
            return ''
    return result


if __name__ == '__main__':
    print(get_text_from_file('C:\\Users\\user\\AppData\\Local\\Temp\\tmpprw49fox1.docx'))
