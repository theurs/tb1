#!/usr/bin/env python3
# pip install -U opencv-python

import cachetools.func
import cv2
import numpy as np

import my_log


@cachetools.func.ttl_cache(maxsize=10, ttl=60)
def get_text(image_bytes: bytes):
    """
    Extracts text from a QR code in an image using OpenCV.

    Args:
        image_bytes: The image as bytes.

    Returns:
        The decoded text from the QR code, or None if no QR code is found.
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
            return ''

    except Exception as e:
        my_log.log2(f'qr_reader:get_text_from_qr_image error: {e}')
        return ''


if __name__ == '__main__':
    pass
    with open('C:/Users/user/Downloads/2.jpg', 'rb') as f:
        data = f.read()
    text = get_text(data)
    print(text)

