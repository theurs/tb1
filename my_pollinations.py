import time
from io import BytesIO
from typing import Optional
from urllib.parse import quote_plus

import requests
from PIL import Image, UnidentifiedImageError

import my_log


def fetch_image_bytes(
    prompt: str,
    width: int = 1024,
    height: int = 1024,
    model: str = "flux",
    nologo: bool = True,
    seed: Optional[int] = None,
) -> Optional[bytes]:
    """
    Generates, validates, and resizes an image to comply with Telegram limits.

    Args:
        prompt: The text prompt for the image.
        width: Image width. Defaults to 1024.
        height: Image height. Defaults to 1024.
        model: Generation model. "flux" | "turbo" | "kontext". Надо писать любую модель кроме этих Ж) иначе не срабатывает. турбо вроде работает
        nologo: Remove logo. Defaults to True.
        seed: Optional seed for reproducibility.

    Returns:
        Image data as bytes (JPEG), or None on failure.
    """
    MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024  # 20 MB download limit
    TELEGRAM_MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB file size limit
    TELEGRAM_MAX_DIM_SUM = 10000  # Sum of width and height limit

    used_seed = seed if seed is not None else int(time.time() * 1000)
    encoded_prompt = quote_plus(prompt)

    base_url = "https://image.pollinations.ai/prompt/"
    params = (
        f"?width={width}&height={height}&nologo={str(nologo).lower()}"
        f"&seed={used_seed}&model={model}"
    )
    url = f"{base_url}{encoded_prompt}{params}"

    try:
        with requests.get(url, stream=True, timeout=(10, 40)) as response:
            response.raise_for_status()
            content_length = response.headers.get('Content-Length')
            if content_length and int(content_length) > MAX_DOWNLOAD_BYTES:
                my_log.log2(f"Error: Content-Length {content_length} exceeds limit.")
                return None
            image_bytes = response.content
    except Exception as e:
        if 'Details: 502 Server Error: Bad Gateway for url:' in str(e)[:150]:
            return None
        # my_log.log2(f"Error: Request failed for URL {url}. Details: {e}")
        return None

    try:
        img = Image.open(BytesIO(image_bytes))

        # Resize if dimensions exceed Telegram's limits
        w, h = img.size
        if w + h > TELEGRAM_MAX_DIM_SUM:
            my_log.log2(f"Info: Image dimensions ({w}x{h}) exceed sum limit. Resizing.")
            scale = TELEGRAM_MAX_DIM_SUM / (w + h)
            new_w = int(w * scale)
            new_h = int(h * scale)
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # Convert to RGB if needed
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')

        # Initial save to check size
        buffer = BytesIO()
        img.save(buffer, format='JPEG', quality=60)

        # Further reduce size if image still exceeds Telegram's file limit
        if buffer.tell() > TELEGRAM_MAX_SIZE_BYTES:
            return None

        return buffer.getvalue()

    except Exception as e:
        if 'Details: 502 Server Error: Bad Gateway for url:' in str(e)[:150]:
            return None
        my_log.log2(f"Error: Invalid image data from {url}. Details: {e}")
        return None


if __name__ == "__main__":
    # prompt = 'curly woman dring water'
    prompt = '''Generate a highly detailed and hyperrealistic image of an immense blue whale crammed inside a standard-sized porcelain bathtub. Focus on accurate anatomy and scale, emphasizing the absurd contrast between the gigantic marine mammal and the confined domestic setting. Show water splashing vigorously out of the tub, reflecting natural light. The whale's skin should exhibit realistic textures, barnacles, and subtle ripples, suggesting the wet environment. The bathtub should appear solid and slightly overflowing, with reflections on its glazed surface. Use dramatic volumetric lighting to enhance depth and realism, captured with a professional high-resolution camera, akin to an award-winning wildlife photograph.'''
    image = fetch_image_bytes(prompt, model='cccontext')
    if image:
        with open(r'c:\Users\user\Downloads\image.jpg', 'wb') as f:
            f.write(image)
