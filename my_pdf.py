#!/usr/bin/env python3
# pip install -U PyMuPDF


import fitz
import time
from typing import List, Tuple

import cfg
import my_log
import my_gemini
from utils import async_run


def extract_images_from_pdf_bytes(pdf_bytes: bytes) -> List[bytes]:
    """
    Extracts all images from a PDF given as bytes.

    Args:
        pdf_bytes: The content of the PDF file as bytes.

    Returns:
        A list of bytes, where each element is the byte content of an image found in the PDF.
    """
    image_list_bytes: List[bytes] = []
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
            my_log(f"my_pdf:extract_text_from_pdf_bytes:type_error: Error processing PDF: {error_type}")
    except Exception as error:
        my_log(f"my_pdf:extract_text_from_pdf_bytes: Error processing PDF: {error}")
    return text_content


@async_run
def process_image_ocr(image: bytes, index: int, results) -> Tuple[str, int]:
    """
    Performs OCR on a single image using my_gemini.ocr_page.

    Args:
        image: The image data as bytes.
        index: The index of the image in the original list.
    """
    text = my_gemini.ocr_page(image)
    results[index] = text or 'EMPTY MARKER 4975934685'


def get_text(data: bytes) -> str:
    """
    Extract text from pdf
    if no text, OCR images with gemini using 8 threads
    """
    text = extract_text_from_pdf_bytes(data)
    if len(text) < 100:
        images = extract_images_from_pdf_bytes(data)
        results = {}
        index = 0
        LIMIT = cfg.LIMIT_PDF_OCR if hasattr(cfg, 'LIMIT_PDF_OCR') else 50
        for image in images[:LIMIT]:
            process_image_ocr(image, index, results)
            index += 1

        while len(results) != len(images):
            time.sleep(1)

        # remove empty markers
        results = {k: v for k, v in results.items() if v != 'EMPTY MARKER 4975934685'}

        # convert to list sorted ny index
        results = sorted(results.items(), key=lambda x: x[0])

        text = '\n'.join([v for _, v in results])

    return text


if __name__ == "__main__":
    my_gemini.load_users_keys()
    with open("c:/Users/User/Downloads/3.pdf", "rb") as f:
        data = f.read()
        print(get_text(data))
