#!/usr/bin/env python3
# тут дают 25 кредитов на аккаунте за регистрацию без телефона, но этого слишком мало
# https://platform.stability.ai/account/keys
# https://platform.stability.ai/account/credits
# STABILITY_AI_KEYS = [   
#     'xxx', 'yyy',
# ]


import io
import random
import requests

from PIL import Image

import cfg
import my_log


def remove_metadata_and_optimize_to_png(image_bytes: bytes) -> bytes:
    try:
        # Open the image from bytes
        image = Image.open(io.BytesIO(image_bytes))

        # Create a BytesIO object to save the image without metadata
        output = io.BytesIO()

        # Ensure the image has an alpha channel
        if image.mode != 'RGBA':
            image = image.convert('RGBA')

        # Create a mask that covers the entire image
        mask = Image.new('L', image.size, 255)  # 255 means fully opaque

        # Apply the mask to the alpha channel
        image.putalpha(mask)

        # Save the image as PNG with optimized settings
        image.save(output, format='PNG', optimize=True)

        # Get the bytes from the BytesIO object
        optimized_image_bytes = output.getvalue()

        return optimized_image_bytes
    except Exception as error:
        # my_log.log_stability_ai(f'remove_metadata_and_optimize_to_png: {error}')
        print(f'remove_metadata_and_optimize_to_png: {error}')
        return None


def get_key() -> str:
    if hasattr(cfg, 'STABILITY_AI_KEYS'):
        return random.choice(cfg.STABILITY_AI_KEYS)
    else:
        return ''


def inpaint(image: bytes,
            prompt: str,
            negative_prompt: str = '',
            mask: bytes = None,
            output_format: str = 'jpeg'
            ) -> bytes:
    '''
    Меняет изображение по запросу, промпт только по английски
    Маска может указать конкретное место, но в телеграме это сложно сделать,
    нужно запускать веб приложение с онлайн редактором
    '''
    if not hasattr(cfg, 'STABILITY_AI_KEYS'):
        return 'No keys left.'

    if output_format == 'jpg':
        output_format = 'jpeg'

    rebuilded_image = remove_metadata_and_optimize_to_png(image)
    if not rebuilded_image:
        return 'Error in remove_metadata_and_optimize'


    response = requests.post(
        f"https://api.stability.ai/v2beta/stable-image/edit/inpaint",
        headers={
            "authorization": f"Bearer {get_key()}",
            "accept": "image/*"
        },
        files={
            "image": io.BytesIO(image),
            "mask": io.BytesIO(rebuilded_image),
        },
        data={
            "prompt": prompt,
            # "negative_prompt": negative_prompt,
            "output_format": output_format,
        },
    )

    if response.status_code == 200:
        return response.content
    else:
        error_msg = str(response.json())
        return error_msg


if __name__ == "__main__":
    pass

    with open('C:/Users/user/Downloads/1.jpg', 'rb') as f:
        image = f.read()

    result_image = 'c:/Users/user/Downloads/2.jpg'

    # prompt = 'Мake it styled dark elf old woman with black skin'
    prompt = 'Add labels with names Masha and Misha on man and woman'
    result_data = inpaint(image, prompt, output_format='jpg')

    if result_image and isinstance(result_data, bytes):
        with open(result_image, 'wb') as f:
            f.write(result_data)
    elif isinstance(result_data, str):
        print(result_data)
