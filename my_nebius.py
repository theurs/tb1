# https://studio.nebius.ai/billing
# https://studio.nebius.ai/settings/api-keys


import base64
import traceback
from openai import OpenAI


import cfg
import my_log


BASE_URL = "https://api.studio.nebius.ai/v1/"


CURRENT_KEYS_SET = []


def get_next_key():
    '''
    Get next key from the list of keys
    '''
    if not CURRENT_KEYS_SET:
        CURRENT_KEYS_SET.extend(cfg.NEBIUS_AI_KEYS)
    if CURRENT_KEYS_SET:
        return CURRENT_KEYS_SET.pop(0)
    else:
        raise Exception("No more keys")


def txt2img(
    prompt: str,
    width: int = 1024,
    height: int = 1024,
    output_format: str = 'webp',
    negative_prompt: str = '',
    seed: int = -1,
    num_interence_steps: int = 28,
    ) -> bytes:
    '''
    Generate image from text

    Args:
        prompt (str): The text prompt to generate an image from.
        width (int, optional): The width of the generated image. Defaults to 1024.
        height (int, optional): The height of the generated image. Defaults to 1024.
        output_format (str, optional): The format of the generated image. Defaults to 'webp'.
        negative_prompt (str, optional): The negative prompt to generate an image from. Defaults to ''.
        seed (int, optional): The seed to generate an image from. Defaults to -1.
        num_interence_steps (int, optional): The number of inference steps to generate an image. Defaults to 28.

    Returns:
        bytes: The generated image data in bytes format.
    '''
    try:
        key = get_next_key()
        client = OpenAI(
            base_url=BASE_URL,
            api_key=key,
        )

        response = client.images.generate(
            model="black-forest-labs/flux-dev",
            response_format="b64_json",
            extra_body={
                "response_extension": output_format,
                "width": width,
                "height": height,
                "num_inference_steps": num_interence_steps,
                "negative_prompt": negative_prompt,
                "seed": seed,
                "num_images": 1,
            },
            prompt=prompt
        )

        image_data = response.data[0]
        b64_string = image_data.b64_json
        image_bytes = base64.b64decode(b64_string)

        return image_bytes
    except Exception as unknown_error:
        traceback_error = traceback.format_exc()
        my_log.log_nebius(f'Error: {unknown_error}\n{traceback_error}')
        return None


def test_txt2img():
    data = txt2img(
        "A whimsical image of Pippi Longstocking joyfully sailing in a small wooden rowboat on a serene lake, bright sunny "
        "day, lush green trees surrounding the lake, realism pro movie style.",
        )
    if data:
        with open(f'c:/users/user/downloads/1.webp', 'wb') as f:
            f.write(data)
            print('Image saved')
    else:
        print('Error')


if __name__ == "__main__":
    pass

