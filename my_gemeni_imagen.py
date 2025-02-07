#!/usr/bin/env python3

import os
from io import BytesIO
import traceback
from typing import List

from google import genai
from google.genai import types
from PIL import Image

from my_gemini import get_next_key, load_users_keys
from my_log import log_gemini


def generate_images_as_bytes(
    prompt: str,
    model: str = 'imagen-3.0-generate-002',
    number_of_images: int = 4,
    aspect_ratio: str = "3:4",
    safety_filter_level: str = "BLOCK_LOW_AND_ABOVE",
    person_generation: str = "DONT_ALLOW",
) -> List[bytes]:
    """
    Generates images based on a text prompt and returns them as a list of byte strings.

    Args:
        prompt: The text prompt to generate the images from.  (e.g., "A cat wearing a hat")
        model: The name of the model to use for image generation.  Defaults to 'imagen-3.0-generate-002'. (e.g., 'imagen-3.0-generate-002', 'another-image-model')
        number_of_images: The number of images to generate. Defaults to 4. (e.g., 1, 2, 5)
        aspect_ratio: The aspect ratio of the generated images. Defaults to "3:4". (e.g., "1:1", "9:16", "16:9", "3:4", "4:3")
        safety_filter_level: The level of safety filtering to apply. Defaults to "BLOCK_LOW_AND_ABOVE". (e.g., "BLOCK_NONE", "BLOCK_LOW_AND_ABOVE", "BLOCK_MEDIUM_AND_ABOVE", "BLOCK_HIGH_AND_ABOVE")
        person_generation: Controls whether images with people can be generated. Defaults to "DONT_ALLOW". (e.g., "ALLOW", "DONT_ALLOW")

    Returns:
        A list of bytes objects, where each bytes object represents an image.
        Returns an empty list if an error occurs.
    """
    image_bytes_list = []
    try:
        client = genai.Client(api_key=get_next_key())
        response = client.models.generate_images(
            model=model,
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=number_of_images,
                aspect_ratio=aspect_ratio,
                safety_filter_level=safety_filter_level,
                person_generation=person_generation,
            )
        )

        for generated_image in response.generated_images:
            image_bytes_list.append(generated_image.image.image_bytes)

    except Exception as error:
        traceback_error = traceback.format_exc()
        log_gemini(f"my_gemeni_imagen:generate_images_as_bytes: Error generating images: {error}\n"
                   f"{prompt}\n{model}\n{number_of_images}\n{aspect_ratio}\n{safety_filter_level}\n"
                   f"{person_generation}\n\n{traceback_error}")
        return []

    return image_bytes_list


if __name__ == '__main__':
    load_users_keys()

    # Example usage:
    image_bytes_list = generate_images_as_bytes(prompt="A beautiful sunset over the ocean", number_of_images=2)

    if image_bytes_list:
        # Save images to the user's Downloads folder (Windows specific)
        try:
            downloads_folder = r"C:\Users\user\Downloads"

            for i, image_bytes in enumerate(image_bytes_list):
                try:
                    image = Image.open(BytesIO(image_bytes))
                    image_path = os.path.join(downloads_folder, f"generated_image_{i+1}.png")
                    image.save(image_path)
                    print(f"Image saved to: {image_path}")
                except Exception as save_error:
                    print(f"Error saving image {i+1}: {save_error}")

        except Exception as e:
            print(f"Error saving images: {e}")
