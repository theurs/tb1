#!/usr/bin/env python3
# pip install -U PyMuPDF
# install https://imagemagick.org/index.php (for windows install also https://ghostscript.com/releases/gsdnld.html)
# in linux /etc/ImageMagick-6/policy.xml change 
# <policy domain="coder" rights="none" pattern="PDF" />
#  to
# <policy domain="coder" rights="read|write" pattern="PDF" />


import fitz
import os
import re
import time
import traceback
import subprocess
from typing import List, Tuple

import cfg
import my_log
import my_gemini
from utils import async_run_with_limit, get_codepage, platform, get_tmp_fname, remove_file, remove_dir


def extract_images_from_pdf_with_imagemagick(data: bytes) -> List[bytes]:
    '''
    Extracts all images from a PDF using ImageMagick.

    Args:
        data: The content of the PDF file as bytes.

    Returns:
        A list of bytes, where each element is the byte content of an image found in the PDF.
    '''
    source = get_tmp_fname() + '.pdf'
    target = get_tmp_fname()
    images = []
    try:
        with open(source, 'wb') as f:
            f.write(data)
        os.mkdir(target)

        CMD = 'magick' if 'windows' in platform().lower() else 'convert'
        path_separator = '\\' if 'windows' in platform().lower() else '/'

        cmd = f"{CMD} -density 150 {source} {target}{path_separator}%003d.jpg"

        with subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding = get_codepage()) as proc:
            stdout, stderr = proc.communicate()
        if stderr:
            my_log.log2(f"my_pdf:extract_images_from_pdf_with_imagemagick: Error processing PDF: {stderr}")

        files = os.listdir(target)
        # Sort files based on the page number in the filename
        files.sort(key=lambda filename: int(re.search(r'\d+', filename).group(0)) if re.search(r'\d+', filename) else 0)

        for file in files:
            with open(os.path.join(target, file), 'rb') as f:
                images.append(f.read())

    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f"my_pdf:extract_images_from_pdf_with_imagemagick: Error processing PDF: {error}\n\n{traceback_error}")

    remove_dir(target)
    remove_file(source)

    return images


def extract_images_from_pdf_bytes(pdf_bytes: bytes) -> List[bytes]:
    """
    Extracts all images from a PDF given as bytes.

    Args:
        pdf_bytes: The content of the PDF file as bytes.

    Returns:
        A list of bytes, where each element is the byte content of an image found in the PDF.
    """
    # try to extract images from pdf with imagemagick
    image_list_bytes = extract_images_from_pdf_with_imagemagick(pdf_bytes)
    if image_list_bytes:
        return image_list_bytes

    try:
        pdf_file = fitz.open(stream=pdf_bytes, filetype="pdf")
        for page_index in range(len(pdf_file)):
            page = pdf_file.load_page(page_index)
            images_on_page = page.get_images(full=True)
            for image_info in images_on_page:
                xref = image_info[0]
                base_image = pdf_file.extract_image(xref)
                image_bytes = base_image["image"]
                image_list_bytes.append(image_bytes)
    except Exception as error:
        my_log.log2(f"my_pdf:extract_images_from_pdf_bytes: Error processing PDF: {error}")
    return image_list_bytes


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """
    Extracts all text content from a PDF given as bytes.

    Args:
        pdf_bytes: The content of the PDF file as bytes.

    Returns:
        A string containing all the text content extracted from the PDF.
    """
    text_content = ""
    try:
        pdf_file = fitz.open(stream=pdf_bytes, filetype="pdf")
        for page_number in range(pdf_file.page_count):
            page = pdf_file.load_page(page_number)
            text_content += page.get_text()
    except TypeError as error_type:
        if "'module' object is not callable" not in str(error_type):
            my_log.log2(f"my_pdf:extract_text_from_pdf_bytes:type_error: Error processing PDF: {error_type}")
    except Exception as error:
        my_log.log2(f"my_pdf:extract_text_from_pdf_bytes: Error processing PDF: {error}")
    return text_content


@async_run_with_limit(2)
def process_image_ocr(image: bytes, index: int, results) -> Tuple[str, int]:
    """
    Performs OCR on a single image using my_gemini.ocr_page.

    Args:
        image: The image data as bytes.
        index: The index of the image in the original list.
    """
    text = my_gemini.ocr_page(image)

    if 'EMPTY' in text and len(text) < 20:
        results[index] = 'EMPTY MARKER 4975934685'
    else:
        results[index] = text


def get_text(data: bytes) -> str:
    """
    Extract text from pdf
    if no text, OCR images with gemini
    """
    text = ''

    try:

        text = extract_text_from_pdf_bytes(data)
        if len(text) < 100:
            images = extract_images_from_pdf_bytes(data)
            results = {}
            index = 0
            LIMIT = cfg.LIMIT_PDF_OCR if hasattr(cfg, 'LIMIT_PDF_OCR') else 20
            for image in images[:LIMIT]:
                process_image_ocr(image, index, results)
                index += 1

            while len(results) != len(images[:LIMIT]):
                time.sleep(1)

            # remove empty markers
            results = {k: v for k, v in results.items() if v != 'EMPTY MARKER 4975934685'}

            # convert to list sorted ny index
            results = sorted(results.items(), key=lambda x: x[0])

            text = '\n'.join([v for _, v in results])
    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f"my_pdf:get_text: Error processing PDF: {error}\n\n{traceback_error}")

    return text


if __name__ == "__main__":
    my_gemini.load_users_keys()
    with open(r"C:\Users\user\Downloads\samples for ai\скан документа.pdf", "rb") as f:
        data = f.read()
        print(get_text(data))
