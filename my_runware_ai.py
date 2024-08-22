#!/usr/bin/env python3
# pip install runware


import asyncio
import random

from runware import Runware, IImageInference

import cfg


def generate_images(
    positive_prompt: str,
    model: str = "runware:100@1",
    number_results: int = 4,
    negative_prompt: str = '',
    use_cache: bool = False,
    height: int = 1024,
    width: int = 1024,
    api_key: str = '',
) -> list:
    """
    Generates images using Runware's image inference API.

    Args:
        positive_prompt: The positive prompt for the image generation.
        model: The model to use for image generation.
        number_results: The number of images to generate.
        negative_prompt: The negative prompt for the image generation.
        use_cache: Whether to use the cache for image generation.
        height: The height of the generated images.
        width: The width of the generated images.
        api_key: The API key for Runware.

    Returns:
        A list of image URLs.
    """
    if not api_key:
        if hasattr(cfg, 'RUNWARE_KEYS'):
            api_key = random.choice(cfg.RUNWARE_KEYS)
        else:
            return []

    async def async_generate_images():
        runware = Runware(api_key=api_key)
        await runware.connect()

        request_image = IImageInference(
            positivePrompt=positive_prompt,
            model=model,
            numberResults=number_results,
            negativePrompt=negative_prompt,
            useCache=use_cache,
            height=height,
            width=width,
        )

        images = await runware.imageInference(requestImage=request_image)
        return [image.imageURL for image in images]

    return asyncio.run(async_generate_images())


if __name__ == '__main__':
    # Example usage:
    images = generate_images(positive_prompt="a beautiful sunset over the mountains")
    print(images)
