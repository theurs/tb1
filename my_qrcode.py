#!/usr/bin/env python3
# pip install -U opencv-python pyzbar
# sudo apt install libzbar0


import cv2
import numpy as np
from pyzbar.pyzbar import decode
from pyzbar.pyzbar import ZBarSymbol

import my_log
import utils


@utils.memory_safe_ttl_cache(maxsize=100, ttl=300)
def get_text(image_bytes: bytes) -> str:
    """
    Extracts text from a QR code in an image using OpenCV.

    Args:
        image_bytes: The image as bytes.

    Returns:
        The decoded text from the QR code, or '' if no QR code is found.
    """
    try:
        # Convert bytes to numpy array
        nparr = np.frombuffer(image_bytes, np.uint8)

        # Decode the image using OpenCV
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # Initialize the QRCode detector
        qr_detector = cv2.QRCodeDetector()

        # Detect and decode the QR code
        decoded_text, points, _ = qr_detector.detectAndDecode(img)

        if points is not None:
            return decoded_text
        else:
            return get_text_from_barcode_image(image_bytes)

    except Exception as e:
        my_log.log2(f'qr_reader:get_text_from_qr_image error: {e}')
        return ''


@utils.memory_safe_ttl_cache(maxsize=100, ttl=300)
def get_text_from_barcode_image(image_bytes: bytes) -> str:
    """
    Extracts text from a linear barcode in an image using OpenCV and pyzbar.

    Args:
        image_bytes: The image as bytes.

    Returns:
        The decoded text from the first found barcode, or '' if no barcode is found.
    """
    try:
        # Convert bytes to numpy array
        nparr = np.frombuffer(image_bytes, np.uint8)

        # Decode the image using OpenCV
        # cv2.IMREAD_GRAYSCALE часто лучше работает для баркодов
        img = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)

        if img is None:
            my_log.log2(f'barcode_reader:get_text_from_barcode_image error: Could not decode image bytes.')
            return ''

        # Detect and decode barcodes
        # Исправлено: вместо ZBarSymbol.ITF используем ZBarSymbol.I25
        # barcodes = decode(img, symbols=[ZBarSymbol.EAN13, ZBarSymbol.CODE128, ZBarSymbol.CODE39, ZBarSymbol.UPCA, ZBarSymbol.I25])
        barcodes = decode(img, symbols=[
            ZBarSymbol.EAN2, ZBarSymbol.EAN5, ZBarSymbol.EAN8, ZBarSymbol.UPCE,
            ZBarSymbol.ISBN10, ZBarSymbol.UPCA, ZBarSymbol.EAN13, ZBarSymbol.ISBN13,
            ZBarSymbol.COMPOSITE, ZBarSymbol.I25, ZBarSymbol.DATABAR, ZBarSymbol.DATABAR_EXP,
            ZBarSymbol.CODABAR, ZBarSymbol.CODE39, ZBarSymbol.PDF417, ZBarSymbol.QRCODE,
            ZBarSymbol.SQCODE, ZBarSymbol.CODE93, ZBarSymbol.CODE128
        ])


        if barcodes:
            # Возвращаем данные первого найденного баркода, декодированные в UTF-8
            return barcodes[0].data.decode('utf-8')
        else:
            return ''

    except Exception as e:
        my_log.log2(f'barcode_reader:get_text_from_barcode_image error: {e}')
        return ''


if __name__ == '__main__':
    pass
    # with open('C:/Users/user/Downloads/2.jpg', 'rb') as f:
    #     data = f.read()
    # text = get_text(data)
    # print(text)

    # with open('C:/Users/user/Downloads/4.png', 'rb') as f:
    #     data = f.read()
    # text = get_text_from_barcode_image(data)
    # print(text)
