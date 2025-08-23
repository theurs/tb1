# my_barcode_generate.py
# uv pip install -U python-barcode


import io

from barcode import generate
from barcode.writer import ImageWriter
from barcode.errors import BarcodeError


def generate_barcode_bytes(text: str, barcode_type: str) -> bytes | str:
    '''
    Generates a barcode image in PNG format as bytes.

    Args:
        text: str - text to generate barcode from
        barcode_type: str - type of barcode to generate (e.g., 'EAN13', 'Code128', 'Code39')
    Returns:
        bytes: PNG image data as bytes on success.
        str: Error message on failure.
    '''
    try:
        buffer = io.BytesIO()
        generate(barcode_type, text, writer=ImageWriter(), output=buffer)
        buffer.seek(0)
        png_bytes = buffer.getvalue()
        if not png_bytes:
            return "Failed to generate barcode image: No data generated."
        return png_bytes
    except BarcodeError as be:
        return f"Barcode generation error: Invalid input for barcode type '{barcode_type}'. Details: {be}. For example, EAN13 requires 12 digits, and Code39/Code128 support alphanumeric characters."
    except Exception as e:
        return f"An unexpected error occurred during barcode generation: {e}"


if __name__ == '__main__':
    r = generate_barcode_bytes('1234567890123', 'EAN13')
    if isinstance(r, bytes):
        with open(r'c:/Users/user/Downloads/barcode.png', 'wb') as f:
            f.write(r)
    else:
        print(r)
