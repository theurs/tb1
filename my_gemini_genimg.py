import os
import time
import traceback
from io import BytesIO
from PIL import Image
from typing import Optional

from google import genai
from google.genai import types

import my_db
import my_gemini
import my_log
import utils


# MODEL = "gemini-2.0-flash-exp"
MODEL = "gemini-2.0-flash-exp-image-generation"


SAFETY_SETTINGS = [
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
]


def convert_png_to_jpg(png_bytes: bytes, quality: int = 60) -> bytes:
    """Converts PNG bytes to JPG bytes with specified quality.

    Args:
        png_bytes: The PNG image data as bytes.
        quality: The desired JPG quality (0-100).

    Returns:
        The JPG image data as bytes.
    """
    try:
        img = Image.open(BytesIO(png_bytes))
        if img.mode == "RGBA":
            img = img.convert("RGB")
        jpg_bytes = BytesIO()
        img.save(jpg_bytes, "JPEG", quality=quality, optimize=True)
        result = jpg_bytes.getvalue()
        return result
    except Exception as e:
        my_log.log_gemini(f"Error converting PNG to JPG: {e}")
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

        model = MODEL
        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(text=f"""{prompt}"""),
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
            safety_settings=SAFETY_SETTINGS,
            response_mime_type="text/plain",
        )

        for _ in range(5):
            try:
                for chunk in client.models.generate_content_stream(
                    model=model,
                    contents=contents,
                    config=generate_content_config,
                ):
                    if not chunk.candidates or not chunk.candidates[0].content or not chunk.candidates[0].content.parts:
                        continue
                    if chunk.candidates[0].content.parts[0].inline_data:
                        image_data: bytes = chunk.candidates[0].content.parts[0].inline_data.data
                        if user_id:
                            my_db.add_msg(user_id, 'img ' + model)
                        return convert_png_to_jpg(image_data)
                    else:
                        pass
                        # my_log.log_gemini(text=chunk.text)
            except Exception as e:
                if "'status': 'Service Unavailable'" in str(e) or "'status': 'UNAVAILABLE'" in str(e):
                    my_log.log_gemini(f'[error genimg] {str(e)}')
                    time.sleep(20)
                    continue
                else:
                    raise(e)

        return None

    except Exception as e:
        my_log.log_gemini(text=f"Error generating image: {e}")
        return None


def regenerate_image(prompt: str, sources_images: list, api_key: str = '', user_id: str = '') -> Optional[bytes]:
    '''
    Generate new image based on the given prompt and sources images using the Gemini API.

    Args:
        prompt: The text prompt to generate an image from.
        sources_images: A list of source image URLs.
        api_key: The API key for accessing the Gemini API.

    Returns:
        The image data as bytes (jpg) if successful, otherwise None.
    '''
    files = []
    client = None
    
    try:
        if not api_key:
            api_key = my_gemini.get_next_key()

        client = genai.Client(api_key=api_key)

        model = MODEL

        for data in sources_images:
            tmpfname = utils.get_tmp_fname() + '.jpg'
            try:
                save_binary_file(tmpfname, data)
                uploaded_file = client.files.upload(file=tmpfname)
                files.append(uploaded_file)
            except Exception as error:
                my_log.log_gemini(f"Error uploading image: {error}")
                continue
            finally:
                utils.remove_file(tmpfname)

        if not files:
            return None

        IMG_PARTS = []
        for IMG_PART in files:
            IMG_PARTS += [types.Part.from_uri(file_uri=IMG_PART.uri, mime_type=IMG_PART.mime_type),]
        IMG_PARTS += [types.Part.from_text(text=prompt),]

        contents = [
                types.Content(
                    role="user",
                    parts=IMG_PARTS,
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
            safety_settings=SAFETY_SETTINGS,
            response_mime_type="text/plain",
        )

        for _ in range(5):
            try:
                for chunk in client.models.generate_content_stream(
                    model=model,
                    contents=contents,
                    config=generate_content_config,
                ):
                    if not chunk.candidates or not chunk.candidates[0].content or not chunk.candidates[0].content.parts:
                        continue
                    if chunk.candidates[0].content.parts[0].inline_data:
                        image_data: bytes = chunk.candidates[0].content.parts[0].inline_data.data
                        if user_id:
                            my_db.add_msg(user_id, 'img ' + model)
                        return convert_png_to_jpg(image_data)
                    else:
                        # my_log.log_gemini(text=chunk.text)
                        pass
            except Exception as e:
                if "'status': 'Service Unavailable'" in str(e) or "'status': 'UNAVAILABLE'" in str(e):
                    my_log.log_gemini(f'[error regenimg] {str(e)}')
                    time.sleep(20)
                    continue
                else:
                    raise(e)

        return None

    except Exception as e:
        traceback_error = traceback.format_exc()
        my_log.log_gemini(text=f"Error generating image:2: {e}\n\n{traceback_error}")
        return None
    finally:
        if client and files:
            for _file in files:
                try:
                    client.files.delete(name = _file.name)
                except Exception as error:
                    my_log.log_gemini(f"Error deleting image: {error}")
                    time.sleep(5)
                    try:
                        client.files.delete(name = _file.name)
                    except Exception as error2: 
                        my_log.log_gemini(f"Error deleting image: {error2}")
                        time.sleep(10)
                        try:
                            client.files.delete(name = _file.name)
                        except Exception as error3:
                            my_log.log_gemini(f"Error deleting image: {error3}")
                            time.sleep(20)
                            try:
                                client.files.delete(name = _file.name)
                            except Exception as error4:
                                my_log.log_gemini(f"Error deleting image: {error4}")


def test_generate_image():
    '''
    Test the generate_image function.
    '''
    prompt_text = "нарисуй лицо, профессиональная фотография"

    image_bytes = generate_image(prompt_text)

    if image_bytes:
        file_extension = "jpg"
        file_name = os.path.join(r"C:\Users\user\Downloads", f"test.{file_extension}")
        save_binary_file(file_name, image_bytes)
        my_log.log_gemini(text=f"Image saved to: {file_name}")
    else:
        my_log.log_gemini(text="Failed to generate or save image.")


def test_regenerate_image():
    '''
    Test the regenerate_image function.
    '''
    prompt_text = "нарисуй другую, школьную, одежду этому человеку"

    source_images = []
    with open(r'C:\Users\user\Downloads\samples for ai\студийное фото человека.png', 'rb') as f:
        data = f.read()
        source_images.append(data)

    image_bytes = regenerate_image(prompt_text, source_images)

    if image_bytes:
        file_extension = "jpg"
        file_name = os.path.join(r"C:\Users\user\Downloads", f"test.{file_extension}")
        save_binary_file(file_name, image_bytes)
        my_log.log_gemini(text=f"Image saved to: {file_name}")
    else:
        my_log.log_gemini(text="Failed to generate or save image.")


def test_regenerate_image2():
    '''
    Test the regenerate_image function.
    '''
    prompt_text = "поставь этого человека в этот фон"

    source_images = []
    with open(r'C:\Users\user\Downloads\samples for ai\студийное фото человека.png', 'rb') as f:
        data = f.read()
        source_images.append(data)
    with open(r'C:\Users\user\Downloads\samples for ai\фотография улицы.png', 'rb') as f:
        data = f.read()
        source_images.append(data)

    image_bytes = regenerate_image(prompt_text, source_images)

    if image_bytes:
        file_extension = "jpg"
        file_name = os.path.join(r"C:\Users\user\Downloads", f"test.{file_extension}")
        save_binary_file(file_name, image_bytes)
        my_log.log_gemini(text=f"Image saved to: {file_name}")
    else:
        my_log.log_gemini(text="Failed to generate or save image.")


if __name__ == "__main__":
    my_db.init(backup=False)
    my_gemini.load_users_keys()

    # test_generate_image()
    # test_regenerate_image()
    test_regenerate_image2()

    my_db.close()
