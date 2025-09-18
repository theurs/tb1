# my_cmd_img2txt.py

# Standard library imports
import time
import traceback
from typing import Callable, Dict, List, Optional, Union

# Local application/library specific imports
import cfg
import my_db
import my_gemini_genimg
import my_init
import my_log
import my_qrcode
import my_transcribe
import utils
# import utils_llm

# AI/LLM specific imports
import my_cohere
import my_gemini3
import my_github
import my_groq
import my_mistral
import my_openrouter
import my_openrouter_free


def img2img(
    text: Union[bytes, List[bytes]],
    lang: str,
    chat_id_full: str,
    query: str = '',
    model: str = '',
    temperature: float = 1.0,
    system_message: str = '',
    timeout: int = 120,
) -> Optional[bytes]:
    """
    Regenerate the image using a query.
    Tries OpenRouter first, then falls back to the old method.

    Args:
        text (bytes): The source image data.
        lang (str): The language code (unused, for compatibility).
        chat_id_full (str): The full chat ID for logging.
        query (str): The user's prompt for the edit.
        model (str): The model to use (for OpenRouter).
        temperature (float): Generation temperature.
        system_message (str): System message for the model.
        timeout (int): Request timeout in seconds.

    Returns:
        Optional[bytes]: The new image as bytes, or None on failure.
    """
    edited_image = None

    # Attempt to edit the image using the new OpenRouter method
    # if not model or model == 'google/gemini-2.5-flash-image-preview:free':
    #     edited_image: Optional[bytes] = my_openrouter_free.edit_image(
    #         prompt=query,
    #         source_image=text,
    #         user_id=chat_id_full,
    #         # model = model,
    #         timeout=timeout,
    #         system_prompt=system_message,
    #         temperature=temperature
    #     )

    # If the new method succeeds, return the result
    if edited_image:
        return edited_image

    # If the new method fails, fall back to the original method
    if isinstance(text, bytes):
        images: list[bytes] = [text,]
    elif isinstance(text, list):
        images: list[bytes] = text
    else:
        my_log.log2(f'my_cmd_img2txt:img2img:2: unknown type: {type(text)}')
        return None
    return my_gemini_genimg.regenerate_image(query, sources_images=images, user_id=chat_id_full)


def img2txt(
    text: Union[bytes, str],
    lang: str,
    chat_id_full: str,
    query: str,
    model: str,
    temperature: float,
    system_message: str,
    timeout: int,
    images: List[Union[bytes, str]],
    WHO_ANSWERED: Dict[str, str],
    UNCAPTIONED_IMAGES: Dict[str, tuple],
    add_to_bots_mem: Callable,
    tr: Callable,
) -> Optional[Union[str, bytes]]:
    """
    Generate the text description of an image.

    Args:
        text (str): The image file URL or downloaded data(bytes).
        lang (str): The language code for the image description.
        chat_id_full (str): The full chat ID.
        query (str): The user's query text.
        model (str): gemini model
        temperature (float): temperature
        system_message (str): system message (role/style)
        timeout (int): timeout
        images (List[bytes|str]): List of image data or URLs.
        WHO_ANSWERED (Dict[str, str]): Dictionary to store which model answered.
        UNCAPTIONED_IMAGES (Dict[str, tuple]): Storage for user images without captions.
        add_to_bots_mem (Callable): Function to add entries to the bot's memory.
        tr (Callable): Translation function.

    Returns:
        str: The text description of the image.
    """
    try:
        query = query.strip()
        query__ = query
        time_to_answer_start = time.time()

        # если запрос начинается на ! то надо редактировать картинку а не отвечать на вопрос
        if query.startswith('!'):
            imgs = images if images else text
            r = img2img(
                imgs,
                lang,
                chat_id_full,
                query[1:],
                model,
                temperature,
                system_message,
                timeout,
            )
            if r:
                add_to_bots_mem(tr('User asked to edit image', lang) + f' <prompt>{query[1:]}</prompt>', tr('Changed image successfully.', lang), chat_id_full)
            else:
                add_to_bots_mem(tr('User asked to edit image', lang) + f' <prompt>{query[1:]}</prompt>', tr('Failed to edit image.', lang), chat_id_full)
            return r

        if temperature is None:
            temperature = my_db.get_user_property(chat_id_full, 'temperature') or 1
        if system_message is None:
            system_message = my_db.get_user_property(chat_id_full, 'role') or ''

        if isinstance(text, bytes):
            data = text
        else:
            data = utils.download_image_as_bytes(text)

        original_query = query or tr('Describe in detail what you see in the picture. If there is text, write it out in a separate block. If there is very little text, then write a prompt to generate this image.', lang)

        if not query:
            query = tr('Describe the image, what do you see here? Extract all text and show it preserving text formatting. Write a prompt to generate the same image - use markdown code with syntax highlighting ```prompt\n/img your prompt in english```', lang)
        if 'markdown' not in query.lower() and 'latex' not in query.lower():
            query = query + '\n\n' + my_init.get_img2txt_prompt(tr, lang)

        text = ''
        qr_code = my_qrcode.get_text(data)
        if qr_code:
            query = f"{query}\n\n{tr('QR Code was automatically detected on the image, it`s text:', lang)} {qr_code}"

        try:
            chat_mode = my_db.get_user_property(chat_id_full, 'chat_mode') or ''

            system_message_gemini = system_message
            if 'gemini' in chat_mode:
                system_message_gemini = system_message + '\n\n' + tr("Если ты не можешь ответить на запрос пользователя то ответь словом 'STOP', никаких других слов не должно быть, не отвечай что ты не можешь что то сделать.", lang)


            # запрос на OCR?
            if query__ == 'OCR':
                if not text:
                    text = my_mistral.ocr_image(data, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_mistral_ocr'
            # если запрос - gpt то сначала пробуем через gpt
            if query__ == 'gpt':
                if not text:
                    text = my_github.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, model=my_github.BIG_GPT_41_MODEL, system=system_message, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + my_github.BIG_GPT_41_MODEL
                    else:
                        text = my_github.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, model=my_github.DEFAULT_41_MINI_MODEL, system=system_message, timeout=timeout)
                        if text:
                            WHO_ANSWERED[chat_id_full] = 'img2txt_' + my_github.DEFAULT_41_MINI_MODEL

                if not text:
                    text = my_github.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, model=my_github.BIG_GPT_MODEL, system=system_message, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + my_github.BIG_GPT_MODEL
                    else:
                        text = my_github.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, model=my_github.DEFAULT_MODEL, system=system_message, timeout=timeout)
                        if text:
                            WHO_ANSWERED[chat_id_full] = 'img2txt_' + my_github.DEFAULT_MODEL


            # попробовать с помощью openrouter
            # если модель не указана явно то определяем по режиму чата
            if not model and not text:
                if not text and chat_mode == 'openrouter':
                    text = my_openrouter.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, system=system_message, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + 'openrouter'

                # if not text and chat_mode == 'qwen3':
                #     text = my_openrouter_free.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, system=system_message, timeout=timeout)
                #     if text:
                #         WHO_ANSWERED[chat_id_full] = 'img2txt_' + 'qwen3'

                elif not text and chat_mode == 'gpt-4o':
                    text = my_github.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, model=my_github.BIG_GPT_MODEL, system=system_message, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + my_github.BIG_GPT_MODEL
                    else:
                        text = my_github.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, model=my_github.DEFAULT_MODEL, system=system_message, timeout=timeout)
                        if text:
                            WHO_ANSWERED[chat_id_full] = 'img2txt_' + my_github.DEFAULT_MODEL

                elif not text and chat_mode == 'gpt_41':
                    text = my_github.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, model=my_github.BIG_GPT_41_MODEL, system=system_message, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + my_github.BIG_GPT_41_MODEL
                    else:
                        text = my_github.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, model=my_github.DEFAULT_41_MINI_MODEL, system=system_message, timeout=timeout)
                        if text:
                            WHO_ANSWERED[chat_id_full] = 'img2txt_' + my_github.DEFAULT_41_MINI_MODEL

                elif not text and chat_mode == 'gpt_41_mini':
                    text = my_github.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, model=my_github.DEFAULT_41_MINI_MODEL, system=system_message, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + my_github.DEFAULT_41_MINI_MODEL
                    else:
                        text = my_github.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, model=my_github.DEFAULT_MODEL, system=system_message, timeout=timeout)
                        if text:
                            WHO_ANSWERED[chat_id_full] = 'img2txt_' + my_github.DEFAULT_MODEL

                elif not text and chat_mode == 'gemini15':
                    text = my_gemini3.img2txt(data, query, model=cfg.gemini_pro_model, temp=temperature, chat_id=chat_id_full, system=system_message_gemini, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + cfg.gemini_pro_model
                elif not text and chat_mode == 'gemini25_flash':
                    text = my_gemini3.img2txt(data, query, model=cfg.gemini25_flash_model, temp=temperature, chat_id=chat_id_full, system=system_message_gemini, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + cfg.gemini25_flash_model
                elif not text and chat_mode == 'gemini-exp':
                    text = my_gemini3.img2txt(data, query, model=cfg.gemini_exp_model, temp=temperature, chat_id=chat_id_full, system=system_message_gemini, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + cfg.gemini_exp_model
                elif not text and chat_mode == 'gemini-learn':
                    text = my_gemini3.img2txt(data, query, model=cfg.gemini_learn_model, temp=temperature, chat_id=chat_id_full, system=system_message_gemini, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + cfg.gemini_learn_model
                elif not text and chat_mode == 'gemma3_27b':
                    text = my_gemini3.img2txt(data, query, model=cfg.gemma3_27b_model, temp=temperature, chat_id=chat_id_full, system=system_message, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + cfg.gemma3_27b_model
                elif not text and chat_mode == 'gemini-lite':
                    text = my_gemini3.img2txt(data, query, model=cfg.gemini_flash_light_model, temp=temperature, chat_id=chat_id_full, system=system_message_gemini, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + cfg.gemini_flash_light_model
                elif not text and chat_mode == 'gemini':
                    text = my_gemini3.img2txt(data, query, model=cfg.gemini_flash_model, temp=temperature, chat_id=chat_id_full, system=system_message_gemini, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + cfg.gemini_flash_model
                elif not text and chat_mode == 'cohere':
                    text = my_cohere.img2txt(
                        image_data=data,
                        prompt=query,
                        temperature=temperature,
                        chat_id=chat_id_full,
                        system=system_message,
                        timeout=timeout
                    )
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_cohere'

            # если модель не указана явно и не был получен ответ в предыдущем блоке то используем
            # стандартную модель (возможно что еще раз)
            if not model and not text:
                model = cfg.img2_txt_model

            # сначала попробовать с помощью дефолтной модели
            if not text:
                if 'gpt' in model:
                    text = my_github.img2txt(data, query, chat_id=chat_id_full, model=model, temperature=temperature, system=system_message, timeout=timeout)
                    if not text:
                        text = my_gemini3.img2txt(data, query, model=model, temp=temperature, chat_id=chat_id_full, system=system_message_gemini, timeout=timeout)
                else:
                    text = my_gemini3.img2txt(data, query, model=model, temp=temperature, chat_id=chat_id_full, system=system_message_gemini, timeout=timeout)
                if text:
                    WHO_ANSWERED[chat_id_full] = 'img2txt_' + model


            # если это была джемини про то пробуем ее фолбек
            if not text and model == cfg.gemini_pro_model:
                text = my_gemini3.img2txt(data, query, model=cfg.gemini_pro_model_fallback, temp=temperature, chat_id=chat_id_full, system=system_message_gemini, timeout=timeout)
                if text:
                    WHO_ANSWERED[chat_id_full] = 'img2txt_' + cfg.gemini_pro_model_fallback

            # если это была не джемини лайт то пробуем ее
            if not text and model != cfg.gemini_flash_light_model:
                text = my_gemini3.img2txt(data, query, model=cfg.gemini_flash_light_model, temp=temperature, chat_id=chat_id_full, system=system_message_gemini, timeout=timeout)
                if text:
                    WHO_ANSWERED[chat_id_full] = 'img2txt_' + cfg.gemini_flash_light_model


            # флеш25 фолбек
            if not text and model == cfg.gemini25_flash_model:
                text = my_gemini3.img2txt(data, query, model=cfg.gemini25_flash_model_fallback, temp=temperature, chat_id=chat_id_full, system=system_message_gemini, timeout=timeout)
                if text:
                    WHO_ANSWERED[chat_id_full] = 'img2txt_' + cfg.gemini25_flash_model_fallback

            # флеш фолбек
            if not text and model == cfg.gemini_flash_model:
                text = my_gemini3.img2txt(data, query, model=cfg.gemini_flash_model_fallback, temp=temperature, chat_id=chat_id_full, system=system_message_gemini, timeout=timeout)
                if text:
                    WHO_ANSWERED[chat_id_full] = 'img2txt_' + cfg.gemini_flash_model_fallback

            # если ответ длинный и в нем очень много повторений то вероятно это зависший ответ
            # передаем эстафету следующему претенденту
            if len(text) > 2000 and my_transcribe.detect_repetitiveness_with_tail(text):
                text = ''



            # джемини отказалась отвечать?
            if 'stop' in text.lower() and len(text) < 10:
                text = ''



            # далее пробуем gpt4.1 из гитхаба
            if not text:
                text = my_github.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, model=my_github.BIG_GPT_41_MODEL, system=system_message, timeout=timeout)
                if text:
                    WHO_ANSWERED[chat_id_full] = 'img2txt_' + my_github.BIG_GPT_41_MODEL
                else:
                    text = my_github.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, model=my_github.DEFAULT_41_MINI_MODEL, system=system_message, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + my_github.DEFAULT_41_MINI_MODEL


            # gpt 4o
            if not text:
                text = my_github.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, model=my_github.BIG_GPT_MODEL, system=system_message, timeout=timeout)
                if text:
                    WHO_ANSWERED[chat_id_full] = 'img2txt_' + my_github.BIG_GPT_MODEL
                else:
                    text = my_github.img2txt(data, query, temperature=temperature, chat_id=chat_id_full, model=my_github.DEFAULT_MODEL, system=system_message, timeout=timeout)
                    if text:
                        WHO_ANSWERED[chat_id_full] = 'img2txt_' + my_github.DEFAULT_MODEL

            # llama-4-maverick at groq
            if not text:
                text = my_groq.img2txt(data, query, model = 'meta-llama/llama-4-maverick-17b-128e-instruct', temperature=temperature, chat_id=chat_id_full, system=system_message, timeout=timeout)
                if text:
                    WHO_ANSWERED[chat_id_full] = 'img2txt_' + 'meta-llama/llama-4-maverick-17b-128e-instruct'

            # далее пробуем Cohere command-a-vision
            if not text:
                text = my_cohere.img2txt(
                    image_data=data,
                    prompt=query,
                    temperature=temperature,
                    chat_id=chat_id_full,
                    system=system_message,
                    timeout=timeout
                )
                if text:
                    WHO_ANSWERED[chat_id_full] = 'img2txt_cohere'

        except Exception as img_from_link_error:
            traceback_error = traceback.format_exc()
            my_log.log2(f'my_cmd_img2txt:img2txt1: {img_from_link_error}\n\n{traceback_error}')

        if text:
            # если режим не джемини или ответил не джемини значит надо добавить в память ответ вручную
            if 'gemini' not in chat_mode or 'gemini' not in WHO_ANSWERED.get(chat_id_full, ''):
                add_to_bots_mem(tr('User asked about a picture:', lang) + ' ' + original_query, text, chat_id_full)

        if chat_id_full in WHO_ANSWERED:
            if text:
                complete_time = time.time() - time_to_answer_start
                my_log.log3(chat_id_full, complete_time)
                WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(complete_time)}👇'
            else:
                del WHO_ANSWERED[chat_id_full]


        # добавляем в UNCAPTIONED_IMAGES[chat_id_full] эту картинку что бы она стала последней
        if images:
            UNCAPTIONED_IMAGES[chat_id_full] = (time.time(), data, images)
        else:
            UNCAPTIONED_IMAGES[chat_id_full] = (time.time(), data, [data])

        # если запрос на редактирование
        if utils.edit_image_detect(text, lang, tr):
            if 'gemini' in chat_mode:
                my_gemini3.undo(chat_id_full)

            # Используем свежие картинки, если они пришли в функцию.
            # Если нет — достаем из хранилища.
            if images:
                source_images = images
            else:
                # Достаем список оригиналов из хранилища.
                # Индекс [2] — это список оригиналов.
                source_images = UNCAPTIONED_IMAGES[chat_id_full][2] if chat_id_full in UNCAPTIONED_IMAGES else None

            # Если картинок все равно нет, выходим.
            if not source_images:
                my_log.log2(f'my_cmd_img2txt:img2txt2: no source images')
                return

            r = img2img(
                text=source_images,
                lang=lang,
                chat_id_full=chat_id_full,
                query=query__,
                model=model,
                temperature=temperature,
                system_message=system_message,
                timeout=timeout
            )
            if r:
                add_to_bots_mem(tr('User asked to edit image', lang) + f' <prompt>{query[1:]}</prompt>', tr('Changed image successfully.', lang), chat_id_full)
            else:
                add_to_bots_mem(tr('User asked to edit image', lang) + f' <prompt>{query[1:]}</prompt>', tr('Failed to edit image.', lang), chat_id_full)
            return r

        return text
    except Exception as unexpected_error:
        traceback_error = traceback.format_exc()
        my_log.log2(f'my_cmd_img2txt:img2txt2:{unexpected_error}\n\n{traceback_error}')
        return ''
