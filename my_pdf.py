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
from concurrent.futures import ThreadPoolExecutor, as_completed

import PyPDF2
import pymupdf as fitz

import cfg
import my_gemini3
import my_gemini_general
import my_log


# количество параллельных потоков для doc2txt
MAX_THREADS = 2


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


def get_text(data: bytes, max_threads: int = MAX_THREADS) -> str:
    """
    Extracts text from a PDF document.

    First, it attempts a fast native text extraction. If the extracted text is less than 300 characters,
    it assumes the document is a scan and performs OCR using the gemini AI model. The OCR is done in
    parallel, processing the document in chunks of 5 pages. The number of concurrent threads is
    controlled by the `max_threads` parameter.

    Args:
        data (bytes): The byte content of the PDF file.
        max_threads (int, optional): The maximum number of threads for parallel OCR processing.
                                     Defaults to the MAX_THREADS constant.

    Returns:
        str: The text extracted from the PDF. Returns an empty string if both extraction methods fail.
    """
    text = ''
    try:
        text_ = extract_text_from_pdf_bytes(data)

        if len(text_) < 300:
            CHUNK_SIZE = 5
            pdf_chunks = _split_pdf(data, chunk_size=CHUNK_SIZE)

            ocr_results = [None] * len(pdf_chunks)
            with ThreadPoolExecutor(max_workers=max_threads) as executor:
                future_to_index = {executor.submit(my_gemini3.doc2txt, chunk, model=cfg.gemini_flash_model): i for i, chunk in enumerate(pdf_chunks)}
                for future in as_completed(future_to_index):
                    index = future_to_index[future]
                    try:
                        chunk_text = future.result()
                        ocr_results[index] = chunk_text
                    except Exception as error:
                        my_log.log2(f"my_pdf:get_text: Error processing PDF chunk with doc2txt: {error}")
                        ocr_results[index] = "" 

            text = "\n\n".join(ocr_results)

    except Exception as error:
        traceback_error = traceback.format_exc()
        my_log.log2(f"my_pdf:get_text: Error processing PDF: {error}\n\n{traceback_error}")

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


def get_text_from_images(images: list[bytes], max_threads: int = MAX_THREADS) -> str:
    """
    Extracts text from a list of image bytes by first converting them into a single PDF.

    Args:
        images (List[bytes]): A list of image bytes.
        max_threads (int, optional): The maximum number of threads for parallel OCR.
                                     Defaults to the MAX_THREADS constant.

    Returns:
        str: The extracted text from the images. Returns an empty string on failure.
    """
    if not images:
        return ""

    doc = None
    try:
        # Create a new PDF document in memory
        doc = fitz.open()

        # Iterate through each image and add it to a new page
        for image_data in images:
            page = doc.new_page()
            # Insert the image, making it fill the entire page rectangle
            page.insert_image(page.rect, stream=image_data)

        # Get the complete PDF as bytes
        pdf_bytes = doc.tobytes(garbage=4, deflate=True)

        # Use the existing get_text function to perform OCR on the generated PDF
        return get_text(pdf_bytes, max_threads=max_threads)
    except Exception as e:
        my_log.log2(f"my_pdf:get_text_from_images: Failed to process images into PDF: {e}")
        return ""
    finally:
        # Ensure the document is closed
        if doc:
            doc.close()


if __name__ == "__main__":
    my_gemini_general.load_users_keys()

    # with open(r"C:\Users\user\Downloads\samples for ai\скан документа.pdf", "rb") as f:
    #     data = f.read()
    #     print(get_text(data))
