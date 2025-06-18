# pip install segno


import cachetools.func
import io
import traceback
from typing import Union

import segno
from PIL import Image

import my_log


@cachetools.func.ttl_cache(maxsize=10, ttl=5*60)
def generate_qr_with_logo_bytes(text: str, logo_source: Union[str, bytes]) -> Union[bytes, str]:
    """
    Generates a QR code from text, embeds a logo image in its center,
    and returns the image as bytes in PNG format.
    Returns an error message string if an error occurs.

    Args:
        text (str): The text data to be encoded in the QR code.
        logo_source (Union[str, bytes]): The file path to the logo image (str)
                                         or the raw bytes of the logo image (bytes).

    Returns:
        bytes: The PNG image data as bytes if successful.
        str: An error message string if an error occurs.
    """
    try:
        # 1. Generate the QR code using Segno with a high error correction level ('H')
        qr_buffer = io.BytesIO()
        segno.make(text, error='h', encoding='utf-8').save(qr_buffer, scale=10, kind='png')
        qr_buffer.seek(0) # Reset buffer position to the beginning for Pillow to read

        # 2. Open the generated QR code image using Pillow
        qr_img = Image.open(qr_buffer)
        qr_img = qr_img.convert('RGB') # Ensure the QR code image is in RGB format for pasting

        # 3. Open the logo image from either a file path or bytes
        try:
            if isinstance(logo_source, str):
                # If logo_source is a string, assume it's a file path
                logo_img = Image.open(logo_source)
            elif isinstance(logo_source, bytes):
                # If logo_source is bytes, create an in-memory buffer and open it
                logo_buffer = io.BytesIO(logo_source)
                logo_img = Image.open(logo_buffer)
            else:
                return "Error: logo_source must be a file path (str) or image bytes (bytes)."
        except FileNotFoundError:
            return f"Error: Logo file not found at {logo_source}"
        except Exception as e:
            return f"Error opening logo source: {e}"

        # 4. Calculate the maximum allowed size for the logo
        qr_width, qr_height = qr_img.size
        logo_max_size = min(qr_width, qr_height) // 5

        # 5. Resize the logo proportionally to fit within the calculated max size
        logo_img.thumbnail((logo_max_size, logo_max_size), Image.Resampling.LANCZOS)

        # 6. Calculate the position to paste the logo in the center of the QR code
        box = (
            (qr_width - logo_img.size[0]) // 2,
            (qr_height - logo_img.size[1]) // 2
        )

        # 7. Paste the resized logo onto the QR code image
        qr_img.paste(logo_img, box)

        # 8. Save the final QR code image to a new BytesIO object and return its contents
        final_buffer = io.BytesIO()
        qr_img.save(final_buffer, format='PNG')
        final_buffer.seek(0) # Reset buffer position

        return final_buffer.getvalue()

    except Exception as e:
        traceback_error = traceback.format_exc()
        msg = f'my_qrcode_generate:generate_qr_with_logo_bytes error: {str(e)}\n\n{traceback_error}'
        my_log.log2(msg)
        return msg


if __name__ == "__main__":
    logo = './pics/photo_2023-07-10_01-36-39.jpg'
    text = '''
test url = https://www.youtube.com/watch?v=12345678
'''

    with open(logo, 'rb') as f:
        logo_bytes = f.read()

    qr_bytes = generate_qr_with_logo_bytes(text, logo_bytes)

    if isinstance(qr_bytes, bytes):
        with open(r'c:\Users\user\Downloads\test.png', 'wb') as f:
            f.write(qr_bytes)
    else:
        print(qr_bytes)
