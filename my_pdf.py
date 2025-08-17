#!/usr/bin/env python3
# pip install -U PyMuPDF
# install https://imagemagick.org/index.php (for windows install also https://ghostscript.com/releases/gsdnld.html)
# in linux /etc/ImageMagick-6/policy.xml change 
# <policy domain="coder" rights="none" pattern="PDF" />
#  to
# <policy domain="coder" rights="read|write" pattern="PDF" />


import io
import traceback
from typing import List, Union

import PyPDF2
import pymupdf as fitz

import my_gemini3
import my_gemini_general
import my_log


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


def _split_pdf(pdf_bytes: bytes, chunk_size: int = 5) -> List[bytes]:
    """
    Splits a PDF into smaller PDF chunks based on a specified number of pages.

    Args:
        pdf_bytes: The content of the PDF file as bytes.
        chunk_size: The number of pages for each smaller PDF chunk.

    Returns:
        A list of bytes, where each element is a smaller PDF file.
    """
    # open the source document
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pdf_chunks = []

    # iterate through the document in chunks of pages
    for i in range(0, doc.page_count, chunk_size):
        # create a new empty PDF
        new_doc = fitz.open()
        # copy the page range from the source to the new document
        new_doc.insert_pdf(doc, from_page=i, to_page=min(i + chunk_size - 1, doc.page_count - 1))
        # save the new document to bytes
        pdf_chunks.append(new_doc.tobytes(garbage=4, deflate=True))
        new_doc.close()

    doc.close()
    return pdf_chunks


def get_text(data: bytes) -> str:
    """
    Extract text from pdf
    if no text, OCR images with gemini
    """
    text = ''
    try:
        # First, try the fast native text extraction
        text_ = extract_text_from_pdf_bytes(data)

        # If native text is insufficient, use advanced OCR
        if len(text_) < 300:
            CHUNK_SIZE = 5  # Number of pages per chunk
            pdf_chunks = _split_pdf(data, chunk_size=CHUNK_SIZE)

            ocr_results = []
            for chunk in pdf_chunks:
                # Process each chunk with the powerful doc2txt function
                chunk_text = my_gemini3.doc2txt(chunk)
                ocr_results.append(chunk_text)

            text = "\n\n".join(ocr_results)

    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f"my_pdf:get_text: Error processing PDF: {error}\n\n{traceback_error}")

    # Return the result with the most content
    return text if len(text) > len(text_) else text_


def count_pages_in_pdf(file_path: Union[str, bytes]) -> int:
    """
    Counts the number of pages in a PDF file.

    Args:
        file_path (Union[str, bytes]): The path to the PDF file or the file bytes.

    Returns:
        int: The number of pages in the PDF file or None.
    """
    try:
        if isinstance(file_path, bytes):
            file_path = io.BytesIO(file_path)

        reader = PyPDF2.PdfReader(file_path)
        return len(reader.pages)
    except Exception as unknown:
        my_log.log2(f"my_pdf:count_pages_in_pdf: Error processing PDF: {unknown}")
        return 0


if __name__ == "__main__":
    my_gemini_general.load_users_keys()

    # with open(r"C:\Users\user\Downloads\samples for ai\скан документа.pdf", "rb") as f:
    #     data = f.read()
    #     print(get_text(data))
