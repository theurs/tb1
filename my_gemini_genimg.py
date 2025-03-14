import os
from io import BytesIO
from PIL import Image
from typing import Optional

from google import genai
from google.genai import types

import cfg
import my_db
import my_gemini
import my_log


def convert_png_to_jpg(png_bytes: bytes, quality: int = 60) -> bytes:
    """Converts PNG bytes to JPG bytes with specified quality.

    Args:
        png_bytes: The PNG image data as bytes.
        quality: The desired JPG quality (0-100).

    Returns:
        The JPG image data as bytes.
    """
    try:
        print(len(png_bytes))
        img = Image.open(BytesIO(png_bytes))
        if img.mode == "RGBA":
            img = img.convert("RGB")
        jpg_bytes = BytesIO()
        img.save(jpg_bytes, "JPEG", quality=quality, optimize=True)
        result = jpg_bytes.getvalue()
        print(len(result))
        return result
    except Exception as e:
        my_log.log_gemini_error(f"Error converting PNG to JPG: {e}")
        return None


def save_binary_file(file_name: str, data: bytes) -> None:
    """
    Saves binary data to a file.

    Args:
        file_name: The name of the file to save.
        data: The binary data to write to the file.
    """
    with open(file_name, "wb") as f:
        f.write(data)


def generate_image(prompt: str, api_key: str = '', user_id: str = '') -> Optional[bytes]:
    """
    Generates an image based on the given prompt using the Gemini API.

    Args:
        prompt: The text prompt to generate an image from.
        api_key: The API key for accessing the Gemini API.

    Returns:
        The image data as bytes (jpg) if successful, otherwise None.
    """
    try:
        if not api_key:
            api_key = my_gemini.get_next_key()

        client = genai.Client(api_key=api_key)

        model = "gemini-2.0-flash-exp" # You can change the model if needed
        contents = [
            types.Content(
                role="user",
                parts=[
                    # types.Part.from_text(text="""нарисуй самолетик из картона"""), # Fixed text part as in original
                    types.Part.from_text(text=f"""{prompt}"""), # Prompt from function argument as second part
                ],
            ),
        ]
        generate_content_config = types.GenerateContentConfig(
            temperature=1,
            top_p=0.95,
            top_k=40,
            max_output_tokens=8192,
            response_modalities=[
                "image",
                "text",
            ],
            safety_settings=[
                types.SafetySetting(
                    category="HARM_CATEGORY_HARASSMENT",
                    threshold="OFF",  # Block none
                ),
                types.SafetySetting(
                    category="HARM_CATEGORY_HATE_SPEECH",
                    threshold="OFF",  # Block none
                ),
                types.SafetySetting(
                    category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    threshold="OFF",  # Block none
                ),
                types.SafetySetting(
                    category="HARM_CATEGORY_DANGEROUS_CONTENT",
                    threshold="OFF",  # Block none
                ),
                types.SafetySetting(
                    category="HARM_CATEGORY_CIVIC_INTEGRITY",
                    threshold="OFF",  # Block none
                ),
            ],
            response_mime_type="text/plain",
        )

        for chunk in client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=generate_content_config,
        ):
            if not chunk.candidates or not chunk.candidates[0].content or not chunk.candidates[0].content.parts:
                continue # Skip chunks without content parts
            if chunk.candidates[0].content.parts[0].inline_data:
                image_data: bytes = chunk.candidates[0].content.parts[0].inline_data.data
                if user_id:
                    my_db.add_msg(user_id, 'img ' + model)
                return convert_png_to_jpg(image_data)
            else:
                my_log.log_gemini(text=chunk.text) # Use my_log for text responses

        return None # Return None if no image data is found after processing all chunks

    except Exception as e:
        my_log.log_gemini(text=f"Error generating image: {e}") # Use my_log for error logging
        return None # Return None in case of error


if __name__ == "__main__":
    my_db.init(backup=False)
    my_gemini.load_users_keys()

    prompt_text = "нарисуй лицо, профессиональная фотография"

    api_key = my_gemini.get_next_key()
    if cfg.gemini_keys:
        api_key = cfg.gemini_keys[0] # Use API key from cfg.gemini_keys

    image_bytes = generate_image(prompt_text, api_key)

    if image_bytes:
        file_extension = "jpg"
        file_name = os.path.join(r"C:\Users\user\Downloads", f"test.{file_extension}")
        save_binary_file(file_name, image_bytes)
        my_log.log_gemini(text=f"Image saved to: {file_name}")
    else:
        my_log.log_gemini(text="Failed to generate or save image.")

    my_db.close()
