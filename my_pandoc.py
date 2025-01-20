#!/usr/bin/env python3


import io
import os
import subprocess

import chardet
import PyPDF2
import pandas as pd
from pptx import Presentation

import my_log
import utils


pandoc_cmd = 'pandoc'
catdoc_cmd = 'catdoc'


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
    '''convert md text to docx file'''
    output_file = utils.get_tmp_fname() + '.docx'
    html = utils.bot_markdown_to_html(text)
    html = html.replace('\n', '<br>')
    subprocess.run(['pandoc', '-f', 'html', '-t', 'docx', '-o', output_file, '-'], input=html.encode('utf-8'), stdout=subprocess.PIPE)
    with open(output_file, 'rb') as f:
        data = f.read()
    utils.remove_file(output_file)
    return data


def convert_text_to_odt(text: str) -> bytes:
    '''convert md text to odt file'''
    output_file = utils.get_tmp_fname() + '.odt'
    html = utils.bot_markdown_to_html(text)
    html = html.replace('\n', '<br>')
    subprocess.run(['pandoc', '-f', 'html', '-t', 'odt', '-o', output_file, '-'], input=html.encode('utf-8'), stdout=subprocess.PIPE)
    with open(output_file, 'rb') as f:
        data = f.read()
    utils.remove_file(output_file)
    return data


def convert_text_to_pdf(text: str) -> bytes:
    '''convert text to pdf file'''
    output_file = utils.get_tmp_fname() + '.pdf'
    html = utils.bot_markdown_to_html(text)
    html = html.replace('\n', '<br>')
    subprocess.run(['pandoc', '-f', 'html', '-t', 'pdf', '-o', output_file, '-'], input=html.encode('utf-8'), stdout=subprocess.PIPE)
    with open(output_file, 'rb') as f:
        data = f.read()
    utils.remove_file(output_file)
    return data


def convert_file_to_html(data: bytes, filename: str) -> str:
    """
    Convert any supported file to HTML, determining the input format from the filename extension.

    Args:
        data: The file content as bytes.
        filename: The name of the file, used to determine the input format.

    Returns:
        The converted content in HTML format as a string.
    """
    output_file: str = utils.get_tmp_fname() + '.html'  # Generate a temporary file name for the output
    result: str = ''
    _, file_extension = os.path.splitext(filename)
    input_format: str = file_extension[1:].lower()  # Remove the leading dot and convert to lowercase

    if input_format == 'txt':
        # autodetect codepage and convert to utf8
        try:
            from_enc = chardet.detect(data)['encoding']
            if from_enc != 'utf-8':
                data = data.decode(from_enc).encode('utf-8')
        except Exception as error:
            my_log.log2(f'my_pandoc: convert_file_to_html detect txt encoding error: {error}')

    # Mapping of file extensions to pandoc input formats
    format_mapping: dict[str, str] = {
        'bib': 'biblatex',
        'bibtex': 'bibtex',
        'bits': 'bits',
        'commonmark': 'commonmark',
        'cm': 'commonmark_x',  # Assuming .cm is a common extension for CommonMark
        'creole': 'creole',
        'csljson': 'csljson',
        'csv': 'csv',
        'djot': 'djot',
        'docbook': 'docbook',
        'docx': 'docx',
        'dokuwiki': 'dokuwiki',
        'endnote': 'endnotexml', # Assuming .endnote is a possible extension
        'epub': 'epub',
        'fb2': 'fb2',
        'gfm': 'gfm',
        'haddock': 'haddock',
        'html': 'html',
        'xhtml': 'html',
        'ipynb': 'ipynb',
        'jats': 'jats',
        'jira': 'jira',
        'json': 'json',
        'tex': 'latex',
        'latex': 'latex',
        'man': 'man',
        'md': 'markdown',
        'markdown': 'markdown',
        'markdown_github': 'markdown_github',
        'mmd': 'markdown_mmd', # Assuming .mmd is a common extension for MultiMarkdown
        'markdown_phpextra': 'markdown_phpextra',
        'markdown_strict': 'markdown_strict',
        'mediawiki': 'mediawiki',
        'muse': 'muse',
        'native': 'native',
        'odt': 'odt',
        'opml': 'opml',
        'org': 'org',
        'ris': 'ris',
        'rst': 'rst',
        'rtf': 'rtf',
        't2t': 't2t',
        'textile': 'textile',
        'txt': 'commonmark',
        'tikiwiki': 'tikiwiki',
        'tsv': 'tsv',
        'twiki': 'twiki',
        'typst': 'typst',
        'vimwiki': 'vimwiki',
    }

    pandoc_format: str | None = format_mapping.get(input_format)

    if not pandoc_format:
        my_log.log2(f'my_pandoc:convert_file_to_html: Unsupported file extension - {input_format}')
        return ""

    try:
        # Execute the pandoc command to convert the file
        process = subprocess.run(
            ['pandoc', '-f', pandoc_format, '-t', 'html', '-o', output_file, '-'],
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,  # Capture standard error for potential issues
            check=True # Raise an exception for non-zero exit codes
        )
        # Check for errors in pandoc execution
        if process.stderr:
            my_log.log2(f'my_pandoc:convert_file_to_html: Pandoc error - {process.stderr.decode()}')
            return "" # Or handle the error as needed

        with open(output_file, 'r', encoding='utf-8') as f:
            result = f.read()
    except FileNotFoundError:
        my_log.log2('my_pandoc:convert_file_to_html: Pandoc not found. Ensure it is installed and in your PATH.')
    except subprocess.CalledProcessError as error:
        my_log.log2(f'my_pandoc:convert_file_to_html: Pandoc conversion failed - {error}')
    except Exception as error:
        my_log.log2(f'my_pandoc:convert_file_to_html: An unexpected error occurred - {error}')
    finally:
        utils.remove_file(output_file)  # Clean up the temporary file
    return result


def convert_html_to_bytes(html_data: str, output_filename: str) -> bytes:
    """
    Convert HTML content to bytes of a specified format, determining the output
    format from the output filename extension, using a temporary file.

    Args:
        html_data: The HTML content as a string.
        output_filename: The name of the output file, used to determine the output format.

    Returns:
        The converted content in bytes.
    """
    _, file_extension = os.path.splitext(output_filename)
    output_format: str = file_extension[1:].lower()  # Remove the leading dot and convert to lowercase

    # Mapping of file extensions to pandoc output formats
    format_mapping_out: dict[str, str] = {
        'adoc': 'asciidoc',
        'asciidoc': 'asciidoc',
        'beamer': 'beamer',
        'bib': 'biblatex',
        'biblatex': 'biblatex',
        'bibtex': 'bibtex',
        'csljson': 'csljson',
        'csv': 'csv',
        'context': 'context',
        'djot': 'djot',
        'docbook': 'docbook',
        'docbook4': 'docbook4',
        'docbook5': 'docbook5',
        'docx': 'docx',
        'dokuwiki': 'dokuwiki',
        'dzslides': 'dzslides',
        'epub': 'epub',
        'epub2': 'epub2',
        'epub3': 'epub3',
        'fb2': 'fb2',
        'gfm': 'gfm',
        'haddock': 'haddock',
        'html': 'html',
        'html4': 'html4',
        'html5': 'html5',
        'icml': 'icml',
        'ipynb': 'ipynb',
        'jats': 'jats',
        'jats_archiving': 'jats_archiving',
        'jats_articleauthoring': 'jats_articleauthoring',
        'jats_publishing': 'jats_publishing',
        'jira': 'jira',
        'json': 'json',
        'tex': 'latex',
        'latex': 'latex',
        'man': 'man',
        'md': 'markdown',
        'markdown': 'markdown',
        'markdown_github': 'markdown_github',
        'markdown_mmd': 'markdown_mmd',
        'markdown_phpextra': 'markdown_phpextra',
        'markdown_strict': 'markdown_strict',
        'markua': 'markua',
        'mediawiki': 'mediawiki',
        'ms': 'ms',
        'muse': 'muse',
        'native': 'native',
        'odt': 'odt',
        'opendocument': 'opendocument',
        'opml': 'opml',
        'org': 'org',
        'pdf': 'pdf',
        'pptx': 'pptx',
        'plain': 'plain',
        'revealjs': 'revealjs',
        'rst': 'rst',
        'rtf': 'rtf',
        's5': 's5',
        'slideous': 'slideous',
        'slidy': 'slidy',
        'tei': 'tei',
        'txt': 'plain',
        'texinfo': 'texinfo',
        'textile': 'textile',
        'typst': 'typst',
        'xwiki': 'xwiki',
        'zimwiki': 'zimwiki',
    }

    pandoc_format_out: str | None = format_mapping_out.get(output_format)

    if not pandoc_format_out:
        my_log.log2(f'my_pandoc:convert_html_to_bytes: Unsupported output file extension - {output_format}')
        return b""

    temp_output_file: str = utils.get_tmp_fname()  # Generate a temporary file name
    try:
        # Execute the pandoc command to convert the HTML to a temporary file
        process = subprocess.run(
            ['pandoc', '-f', 'html', '-t', pandoc_format_out, '-o', temp_output_file, '-'],
            input=html_data.encode('utf-8', 'replace'),  # Encode HTML string to bytes
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,  # Capture standard error for potential issues
            check=True  # Raise an exception for non-zero exit codes
        )
        # Check for errors in pandoc execution
        if process.stderr:
            my_log.log2(f'my_pandoc:convert_html_to_bytes: Pandoc error - {process.stderr.decode()}')
            # return b""

        with open(temp_output_file, 'rb') as f:
            return f.read()

    except FileNotFoundError:
        my_log.log2('my_pandoc:convert_html_to_bytes: Pandoc not found. Ensure it is installed and in your PATH.')
        return b""
    except subprocess.CalledProcessError as error:
        my_log.log2(f'my_pandoc:convert_html_to_bytes: Pandoc conversion failed - {error}')
        return b""
    except Exception as error:
        my_log.log2(f'my_pandoc:convert_html_to_bytes: An unexpected error occurred - {error}')
        return b""
    finally:
        utils.remove_file(temp_output_file)  # Clean up the temporary file


if __name__ == '__main__':
    pass
    # result = fb2_to_text(open('c:/Users/user/Downloads/1.xlsx', 'rb').read(), '.xlsx')
    # result = fb2_to_text(open('1.pdf', 'rb').read(), '.pdf')
    # print(result)
    # print(convert_djvu2pdf('/home/ubuntu/tmp/2.djvu'))



    # with open('c:/Users/user/Downloads/2.docx', 'rb') as f:
    #     html = convert_file_to_html(f.read(), '2.docx')
    #     with open('c:/Users/user/Downloads/2.html', 'w', encoding='utf-8') as f:
    #         f.write(html)

    # with open('c:/Users/user/Downloads/2.html', 'r', encoding='utf-8') as f:
    #     data = convert_html_to_bytes(f.read(), '3.docx')
    #     with open('c:/Users/user/Downloads/3.docx', 'wb') as f:
    #         f.write(data)

