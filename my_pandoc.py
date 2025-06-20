#!/usr/bin/env python3


import cachetools.func
import io
import os
import subprocess
import tempfile
import traceback

import markdown
import PyPDF2
import pandas as pd
from bs4 import BeautifulSoup
from pptx import Presentation
from pygments.formatters import HtmlFormatter

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
        proc = subprocess.run([pandoc_cmd, '+RTS', '-M256M', '-RTS', '-f', 'epub', '-t', 'gfm', input_file], stdout=subprocess.PIPE)
    elif 'pptx' in book_type:
        text = read_pptx(input_file)
        utils.remove_file(input_file)
        return text
    elif 'docx' in book_type:
        proc = subprocess.run([pandoc_cmd, '-f', '+RTS', '-M256M', '-RTS', 'docx', '-t', 'gfm', input_file], stdout=subprocess.PIPE)
    elif 'html' in book_type:
        proc = subprocess.run([pandoc_cmd, '-f', '+RTS', '-M256M', '-RTS', 'html', '-t', 'gfm', input_file], stdout=subprocess.PIPE)
    elif 'odt' in book_type:
        proc = subprocess.run([pandoc_cmd, '-f', '+RTS', '-M256M', '-RTS', 'odt', '-t', 'gfm', input_file], stdout=subprocess.PIPE)
    elif 'rtf' in book_type:
        proc = subprocess.run([pandoc_cmd, '-f', '+RTS', '-M256M', '-RTS', 'rtf', '-t', 'gfm', input_file], stdout=subprocess.PIPE)
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
        proc = subprocess.run([pandoc_cmd, '+RTS', '-M256M', '-RTS', '-f', 'fb2', '-t', 'gfm', input_file], stdout=subprocess.PIPE)
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


@cachetools.func.ttl_cache(maxsize=10, ttl=5 * 60)
def convert_markdown_to_document(text: str, output_format: str) -> bytes | str:
    """
    Converts Markdown-formatted text to a specified document format (DOCX or PDF).
    Uses Pandoc for DOCX and wkhtmltopdf for PDF.
    Assumes Pandoc and wkhtmltopdf are installed and accessible in the system's PATH.

    Args:
        text (str): The input text in Markdown format.
        output_format (str): The desired output format ('docx' or 'pdf').

    Returns:
        bytes | str: The content of the generated document file. Or error string.

    """

    temp_input_file = None # Может быть HTML или Markdown
    output_document_file = None

    try:
        if output_format == 'docx':
            file_extension = '.docx'
            # Для DOCX: создаем временный файл с исходным Markdown
            with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.md', encoding='utf-8') as f_md:
                temp_input_file = f_md.name
                f_md.write(text)

            output_document_file = utils.get_tmp_fname() + file_extension

            # Команда для Pandoc: читаем Markdown, выводим в DOCX, используем стиль подсветки
            command = [
                'pandoc', '+RTS', '-M256M', '-RTS',
                '-f', 'markdown',              # Входной формат: Markdown
                '-t', 'docx',
                '--highlight-style=pygments',  # Активируем подсветку Pandoc
                '-o', output_document_file,
                temp_input_file
            ]

        elif output_format == 'pdf':
            file_extension = '.pdf'
            # Для PDF: сначала генерируем HTML с Pygments CSS, как раньше
            pygments_css = HtmlFormatter(style='default').get_style_defs('.codehilite')

            STYLE = f"""<style>
              /* Общие стили для тела документа */
              body {{
                font-family: 'Segoe UI', 'Roboto', 'Helvetica Neue', Arial, sans-serif; /* Выбирай шрифты с поддержкой кириллицы */
                line-height: 1.6;
                color: #333;
                margin: 20mm; /* Поля для страницы, чтобы выглядело как документ */
              }}

              /* Заголовки */
              h1 {{
                font-size: 2.5em;
                border-bottom: 1px solid #ccc;
                padding-bottom: 0.3em;
                margin-top: 1.5em;
                margin-bottom: 0.8em;
                color: #0056b3; /* Чуть темнее синий для заголовков */
              }}
              h2 {{
                font-size: 2em;
                border-bottom: 1px dashed #eee;
                padding-bottom: 0.3em;
                margin-top: 1.2em;
                margin-bottom: 0.6em;
                color: #0056b3;
              }}
              h3 {{
                font-size: 1.5em;
                margin-top: 1em;
                margin-bottom: 0.5em;
                color: #0056b3;
              }}
              h4, h5, h6 {{
                font-size: 1.2em;
                margin-top: 0.8em;
                margin-bottom: 0.4em;
                color: #0056b3;
              }}

              /* Параграфы */
              p {{
                margin-bottom: 1em;
              }}

              /* Списки */
              ul, ol {{
                margin-left: 20px;
                margin-bottom: 1em;
              }}
              li {{
                margin-bottom: 0.5em;
              }}

              /* Жирный и курсив */
              strong, b {{
                font-weight: bold;
              }}
              em, i {{
                font-style: italic;
              }}

              /* Цитаты */
              blockquote {{
                border-left: 4px solid #b3d9ff; /* Легкая синяя полоса */
                padding: 10px 15px;
                margin: 1em 0;
                color: #555;
                background-color: #f0f8ff; /* Очень легкий фон */
              }}

              /* Код в строке */
              code {{
                font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
                background-color: #f8f8f8;
                padding: 2px 4px;
                border-radius: 3px;
                font-size: 0.9em;
              }}

              /* Блоки кода */
              pre {{
                background-color: #f8f8f8;
                padding: 10px 15px;
                border-radius: 5px;
                overflow-x: auto; /* Для длинных строк кода */
                margin-bottom: 1em;
              }}
              pre code {{
                background-color: transparent; /* Убираем фон для внутреннего кода */
                padding: 0;
                font-size: 1em; /* Размер шрифта для блоков кода */
                display: block; /* Чтобы код занимал всю ширину pre */
              }}

              /* Ссылки */
              a {{
                color: #007bff;
                text-decoration: none;
              }}
              a:hover {{
                text-decoration: underline;
              }}

              /* Горизонтальная линия */
              hr {{
                border: 0;
                border-top: 1px solid #ccc;
                margin: 2em 0;
              }}

              /* Изображения */
              img {{
                max-width: 100%; /* Чтобы изображения не вылезали за пределы страницы */
                height: auto;
                display: block; /* Центрирование, если нужно, можно добавить margin: 0 auto; */
                margin-bottom: 1em;
              }}

              /* Стили для синтаксической подсветки Pygments */
              {pygments_css}
            </style>
            """

            raw_html_body = markdown.markdown(text, extensions=['smarty', 'toc', 'extra', 'codehilite', 'sane_lists', 'markdown_del_ins'])
            html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Документ из Markdown</title>
    {STYLE}
</head>
<body>
{raw_html_body}
</body>
</html>"""

            with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.html', encoding='utf-8') as f_html:
                temp_input_file = f_html.name
                f_html.write(html_content)

            output_document_file = utils.get_tmp_fname() + file_extension
            # Команда для wkhtmltopdf: читаем HTML, выводим в PDF
            command = ['wkhtmltopdf', temp_input_file, output_document_file]

        else:
            return f"Unsupported output format: {output_format}. Choose 'docx' or 'pdf'."

        # Выполняем команду конвертации
        result = subprocess.run(command, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            error_message = f"Conversion to {output_format} failed with error code {result.returncode}:\n{result.stderr}"
            return f"Failed to convert text to {output_format}: {error_message}"

        # Читаем сгенерированный файл
        with open(output_document_file, 'rb') as f_doc:
            document_data = f_doc.read()

        return document_data

    finally:
        # Удаляем временные файлы
        if temp_input_file:
            utils.remove_file(temp_input_file)
        if output_document_file:
            utils.remove_file(output_document_file)


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

        data = utils.extract_text_from_bytes(data)
        if not data:
            my_log.log2(f'my_pandoc: convert_file_to_html: no data or unknown codepage {filename}')
            return ''

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
        'htm': 'html',
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
            ['pandoc', '+RTS', '-M256M', '-RTS', '-f', pandoc_format, '-t', 'html', '-o', output_file, '-'],
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


def ensure_utf8_meta(html_content: str) -> str:
    """
    Ensures the HTML content has a UTF-8 charset meta tag using BeautifulSoup,
    replacing any existing charset declaration.

    Args:
        html_content: The HTML content as a string.

    Returns:
        The HTML content with a UTF-8 charset meta tag.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    meta_charset = soup.find('meta', attrs={'charset': True})

    if meta_charset:
        meta_charset['charset'] = 'utf-8'
    else:
        meta_charset = soup.new_tag('meta', charset='utf-8')
        head_tag = soup.find('head')
        if head_tag:
            head_tag.insert(0, meta_charset)
        else:
            soup.insert(0, meta_charset) # insert to the beginning if no <head> tag

    return str(soup)


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

    # Гарантируем, что в HTML задана кодировка UTF-8
    html_data = ensure_utf8_meta(html_data)

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
        'htm': 'html',
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
            ['pandoc', '+RTS', '-M256M', '-RTS', '-f', 'html', '-t', pandoc_format_out, '-o', temp_output_file, '-'],
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


def convert_html_to_plain(html_data: str) -> str:
    """
    Converts HTML data to plain text using pandoc.

    Args:
        html_data: The HTML string to convert.

    Returns:
        The plain text representation of the HTML data.
    """
    result: str = html_data

    try:
        src_file: str = utils.get_tmp_fname() + '.html'
        dst_file: str = utils.get_tmp_fname() + '.txt'

        with open(src_file, 'w', encoding='utf-8', errors='replace') as f:
            f.write(html_data)

        process = subprocess.run(
            ['pandoc', '+RTS', '-M256M', '-RTS', '-f', 'html', '-t', 'plain', '-o', dst_file, src_file],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)

        if process.returncode != 0:
            error_message = f"Pandoc failed with return code: {process.returncode}\nstderr: {process.stderr.decode('utf-8', errors='replace')}"
            my_log.log2(f'my_pandoc:convert_html_to_plain: {error_message}')
        else:
            with open(dst_file, 'r', encoding='utf-8', errors='replace') as f:
                result = f.read()

    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'my_pandoc:convert_html_to_plain: {error}\n{traceback_error}') # Log other exceptions

    utils.remove_file(src_file)
    utils.remove_file(dst_file)

    return result


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

    t = '''Громаш, словно обезумев, начал колотить кулаками по каменной стене, словно он пытался разбить её в щепки, словно он пытался вырваться из этой тюрьмы. &quot;Я найду тебя, Максимус, и я заставлю тебя страдать! - ревел он, и его голос разносился по всему залу, - я отплачу тебе за все мои страдания, и я не успокоюсь, пока не увижу твою смерть! <i>А было это так… Я буду мучить тебя так, как ты мучил моих братьев, я буду терзать тебя до тех пор, пока не вырву твою душу, и я буду наслаждаться твоими страданиями, словно это самый вкусный нектар. Я хочу видеть боль в твоих глазах, я хочу слышать твои крики, и это будет моей местью, это будет моим искуплением, и я не отступлю, пока я не добьюсь своего!</i>&quot; Он посмотрел на своих соплеменников, и его глаза горели адским огнем, словно он был одержим демоном. &quot;Мы покажем всему миру, что такое сила орков, и мы заставим всех бояться нас, и мы будем править этим миром, и все будут подчиняться нам, и все будут преклоняться перед нами!&quot; Орки, слыша его слова, начали вопить и стучать оружием, готовясь к битве, словно стая диких зверей, готовых разорвать свою жертву на куски. Максимус, слушая его крики, повернулся к своим товарищам и сказал: &quot;Мы все пали, но мы не должны сдаваться, мы не должны позволить этой ненависти сломить нас. Мы должны сражаться вместе, чтобы выжить, и мы должны помнить, что мы не одни.&quot; Его голос был тихим, но в нем чувствовалась решимость и готовность бороться до конца, словно он знал, что они смогут справиться со всеми испытаниями. &quot;Я не верю в шансы,&quot; - сказала Лираэль, и ее голос был полон цинизма, - &quot;но я готова сражаться, если это будет нужно для достижения моих целей, я готова убивать, если это поможет мне выжить, но я не верю в то, что у нас есть шанс, я не верю в то, что мы сможем изменить свою судьбу. <i>А было это так… Я всегда сражалась в одиночку, я не доверяла никому, и я всегда полагалась только на себя, но сейчас я чувствую, что что-то меняется, словно я становлюсь частью чего-то большего, и я не понимаю, что это значит. Я вспоминаю свои прошлые победы, как я достигала всего самостоятельно, но сейчас всё по-другому, и я не знаю, что будет дальше.</i>&quot; Она посмотрела на остальных, и в её глазах можно было заметить искорку надежды, словно она хотела верить, что у них есть шанс. Борд, вздохнув, проговорил: &quot;Я создал много мечей, но ни один из них не спас меня от предательства, и я не знаю, почему я должен сражаться, зачем я должен помогать другим, когда никто не помог мне, я просто устал, и я не знаю, что делать дальше. *А было это так… Я вспоминаю свою кузницу, я её так любил, я отдавал ей всю свою жизнь, но судьба забрала у меня всё, и я не знаю, почему это случилось со мной.'''
    print(convert_html_to_plain(t))
