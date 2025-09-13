# my_cmd_photo.py

# Standard library imports
import sys
import threading
import time
import traceback
from typing import Any, Callable, Dict, List, Type

# Third-party imports
import telebot

# Local application/library specific imports
import cfg
import my_db
import my_log
import my_subscription
import utils


def handle_photo(
    message: telebot.types.Message,

    # Core objects and constants
    bot: telebot.TeleBot,
    BOT_ID: int,
    _bot_name: str,
    BOT_NAME_DEFAULT: str,

    # Global state dictionaries
    COMMAND_MODE: Dict[str, str],
    IMG_LOCKS: Dict[str, threading.Lock],
    CHECK_DONATE_LOCKS: Dict[int, threading.Lock],
    MESSAGE_QUEUE_IMG: Dict[str, List[telebot.types.Message]],

    # Helper functions and classes
    get_topic_id: Callable[[telebot.types.Message], str],
    get_lang: Callable[[str, telebot.types.Message], str],
    tr: Callable[..., str],
    bot_reply: Callable,
    bot_reply_tr: Callable,
    get_keyboard: Callable,
    add_to_bots_mem: Callable,
    log_message: Callable,
    send_document: Callable,
    send_photo: Callable,
    proccess_image: Callable,
    img2txt: Callable,
    send_all_files_from_storage: Callable,
    ShowAction: Type,

    download_image_from_message: Callable,
    img2img: Callable,

    # Command handler functions
    google: Callable,
    do_task: Callable,
) -> None:
    """Handles photo, sticker, and animation messages."""
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        COMMAND_MODE[chat_id_full] = ''
        # проверка на подписку
        if not my_subscription.check_donate(message, chat_id_full, lang, COMMAND_MODE, CHECK_DONATE_LOCKS, BOT_ID, tr, bot_reply, get_keyboard):
            return

        # catch groups of images
        if chat_id_full not in MESSAGE_QUEUE_IMG:
            MESSAGE_QUEUE_IMG[chat_id_full] = [message,]
            last_state = MESSAGE_QUEUE_IMG[chat_id_full]
            n = 10
            while n > 0:
                n -= 1
                time.sleep(0.1)
                new_state = MESSAGE_QUEUE_IMG[chat_id_full]
                if last_state != new_state:
                    last_state = new_state
                    n = 10
        else:
            MESSAGE_QUEUE_IMG[chat_id_full].append(message)
            return


        if len(MESSAGE_QUEUE_IMG[chat_id_full]) > 1:
            MESSAGES = MESSAGE_QUEUE_IMG[chat_id_full]
        else:
            MESSAGES = [message,]
        del MESSAGE_QUEUE_IMG[chat_id_full]

        message.caption = my_log.restore_message_text(message.caption, message.caption_entities)

        if message.caption and message.caption.startswith(('/img ', '/image ', '/gem ', '/flux ', '/bing ')):
            # заменить первое слово на !
            message.caption = message.caption.replace('/img ', '!', 1).replace('/image ', '!', 1).replace('/gem ', '!', 1).replace('/flux ', '!', 1).replace('/bing ', '!', 1)

        try:
            is_private = message.chat.type == 'private'
            supch = my_db.get_user_property(chat_id_full, 'superchat') or 0
            is_reply = message.reply_to_message and message.reply_to_message.from_user.id == BOT_ID
            if supch == 1:
                is_private = True

            msglower = message.caption.lower() if message.caption else ''

            bot_name = my_db.get_user_property(chat_id_full, 'bot_name') or BOT_NAME_DEFAULT
            bot_name_was_used = False
            # убираем из запроса кодовое слово
            if msglower.startswith((f'{bot_name} ', f'{bot_name},', f'{bot_name}\n')):
                bot_name_was_used = True
                message.caption = message.caption[len(f'{bot_name} '):].strip()

            state = ''
            bot_name2 = f'@{_bot_name}'
            # убираем из запроса имя бота в телеграме
            if msglower.startswith((f'{bot_name2} ', f'{bot_name2},', f'{bot_name2}\n')):
                bot_name_was_used = True
                message.caption = message.caption[len(f'{bot_name2} '):].strip()
            elif is_private or is_reply or bot_name_was_used:
                state = 'describe'
            elif msglower.startswith('?'):
                state = 'describe'
                message.caption = message.caption[1:]


            if not is_private and not state == 'describe':
                if not message.caption or not message.caption.startswith('?') or \
                    not bot_name_was_used:
                    return

            if is_private:
                # Если прислали медиагруппу то делаем из нее коллаж, и обрабатываем как одну картинку
                # Если картинок больше 4 то вытаскиваем из каждой текст отдельно и пытаемся собрать в 1 большой текст
                if len(MESSAGES) > 1:
                    # найти сообщение у которого есть caption
                    caption = ''
                    for msg in MESSAGES:
                        if msg.caption:
                            caption = msg.caption
                            break
                    caption = caption.strip()
                    with ShowAction(message, 'typing'):
                        images = [download_image_from_message(msg) for msg in MESSAGES]

                        # Если прислали группу картинок и запрос начинается на ! то перенаправляем запрос в редактирование картинок
                        if caption.startswith('!'):
                            caption = caption[1:]

                            temperature = my_db.get_user_property(chat_id_full, 'temperature') or 1
                            role = my_db.get_user_property(chat_id_full, 'role') or ''
                            image = img2img(
                                text = images,
                                lang=lang,
                                chat_id_full=chat_id_full,
                                query=caption,
                                temperature=temperature,
                                system_message=role,
                            )

                            if image:
                                m = send_photo(
                                    message,
                                    message.chat.id,
                                    disable_notification=True,
                                    photo=image,
                                    reply_to_message_id=message.message_id,
                                    reply_markup=get_keyboard('hide', message)
                                )
                                log_message(m)
                                add_to_bots_mem(tr('User asked to edit images', lang) + f' <prompt>{caption}</prompt>', tr('Changed images successfully.', lang), chat_id_full)
                                return
                            else:
                                bot_reply_tr(message, 'Failed to edit images.')
                                add_to_bots_mem(tr('User asked to edit images', lang) + f' <prompt>{caption}</prompt>', tr('Failed to edit images.', lang), chat_id_full)
                                return

                        if len(images) > 4:
                            big_text = ''
                            # соединить группы картинок по 4
                            images_ = utils.create_image_collages(images)
                            if images_:
                                source_images = images[:]
                                images = images_

                            for image in images:
                                if image:
                                    try:
                                        text = img2txt(
                                            text = image,
                                            lang = lang,
                                            chat_id_full = chat_id_full,
                                            query=tr('text', lang),
                                            model = cfg.gemini_flash_light_model,
                                            temperature=0.1,
                                            system_message=tr('Give me all text from image, no any other words but text from this image', lang),
                                            timeout=60,
                                            images=source_images,
                                            )
                                        if text:
                                            big_text += text + '\n\n'
                                    except Exception as bunch_of_images_error1:
                                        my_log.log2(f'my_cmd_photo:handle_photo1: {bunch_of_images_error1}')
                            if big_text:
                                try:
                                    bot_reply(
                                        message,
                                        big_text,
                                        disable_web_page_preview=True,
                                        )
                                    if caption:
                                        message.text = f'{tr("User sent a bunch of images with text and caption:", lang)} {caption}\n\n{big_text}'
                                        do_task(message)
                                    else:
                                        add_to_bots_mem(
                                            query=tr('User sent images.', lang),
                                            resp = f"{tr('Got text from images:', lang)}\n\n{big_text}",
                                            chat_id_full=chat_id_full,
                                        )
                                except Exception as bunch_of_images_error2:
                                    my_log.log2(f'my_cmd_photo:handle_photo2: {bunch_of_images_error2}')
                            else:
                                bot_reply_tr(message, 'No any text in images.')
                            return
                        else:
                            if sys.getsizeof(images) > 10 * 1024 *1024:
                                bot_reply_tr(message, 'Too big files.')
                                return
                            try:
                                result_image_as_bytes = utils.make_collage(images)
                            except Exception as make_collage_error:
                                # my_log.log2(f'my_cmd_photo:handle_photo1: {make_collage_error}')
                                bot_reply_tr(message, 'Too big files.')
                                return
                            if len(result_image_as_bytes) > 10 * 1024 *1024:
                                result_image_as_bytes = utils.resize_image(result_image_as_bytes, 10 * 1024 *1024)
                            try:
                                m = send_photo(
                                    message,
                                    message.chat.id,
                                    result_image_as_bytes,
                                    reply_to_message_id=message.message_id,
                                    reply_markup=get_keyboard('hide', message)
                                )
                                log_message(m)
                            except Exception as send_img_error:
                                my_log.log2(f'my_cmd_photo:handle_photo2: {send_img_error}')
                            # width, height = utils.get_image_size(result_image_as_bytes)
                            # if width >= 1280 or height >= 1280:
                            #     try:
                            #         m = send_document(
                            #             message,
                            #             message.chat.id,
                            #             result_image_as_bytes,
                            #             # caption='images.jpg',
                            #             visible_file_name='images.jpg',
                            #             disable_notification=True,
                            #             reply_to_message_id=message.message_id,
                            #             reply_markup=get_keyboard('hide', message)
                            #         )
                            #         log_message(m)
                            #     except Exception as send_doc_error:
                            #         my_log.log2(f'my_cmd_photo:handle_photo3: {send_doc_error}')
                            my_log.log_echo(message, f'Made collage of {len(images)} images.')
                            if not caption:
                                proccess_image(chat_id_full, result_image_as_bytes, message, original_images=images)
                                return
                            text = img2txt(result_image_as_bytes, lang, chat_id_full, caption, images=images)
                            if text:
                                if isinstance(text, str):
                                    text = utils.bot_markdown_to_html(text)
                                    # text += tr("<b>Every time you ask a new question about the picture, you have to send the picture again.</b>", lang)
                                    bot_reply(message, text, parse_mode='HTML',
                                                        reply_markup=get_keyboard('translate', message),
                                                        disable_web_page_preview=True)
                                elif isinstance(text, bytes):
                                    m = send_photo(
                                        message,
                                        message.chat.id,
                                        text,
                                        reply_to_message_id=message.message_id,
                                        reply_markup=get_keyboard('hide', message),
                                    )
                                    log_message(m)
                                    return

                                # Check for and send any files generated by skills
                                send_all_files_from_storage(message, chat_id_full)

                            else:
                                bot_reply_tr(message, 'Sorry, I could not answer your question.')
                            return


            if chat_id_full in IMG_LOCKS:
                lock = IMG_LOCKS[chat_id_full]
            else:
                lock = threading.Lock()
                IMG_LOCKS[chat_id_full] = lock

            # если юзер хочет найти что то по картинке
            if chat_id_full in COMMAND_MODE and COMMAND_MODE[chat_id_full] == 'google':
                with ShowAction(message, 'typing'):
                    image = download_image_from_message(message)
                    query = tr('The user wants to find something on Google, but he sent a picture as a query. Try to understand what he wanted to find and write one sentence that should be used in Google to search to fillfull his intention. Write just one sentence and I will submit it to Google, no extra words please.', lang)
                    google_query = img2txt(image, lang, chat_id_full, query)
                if google_query:
                    message.text = f'/google {google_query}'
                    bot_reply(message, tr('Googling:', lang) + f' {google_query}')
                    google(message)
                else:
                    bot_reply_tr(message, 'No results.', lang)
                return

            with lock:
                # распознаем что на картинке с помощью гугл джемини
                if state == 'describe':
                    with ShowAction(message, 'typing'):
                        image = download_image_from_message(message)

                        if not image:
                            # my_log.log2(f'my_cmd_photo:handle_photo4: не удалось распознать документ или фото {str(message)}')
                            return

                        if len(image) > 10 * 1024 *1024:
                            image = utils.resize_image(image, 10 * 1024 *1024)

                        image = utils.heic2jpg(image)
                        if not message.caption:
                            proccess_image(chat_id_full, image, message)
                            return
                        # грязный хак, для решения задач надо использовать мощную модель
                        if 'реши' in message.caption.lower() or 'solve' in message.caption.lower() \
                            or 'задач' in message.caption.lower() or 'задан' in message.caption.lower():
                            text = img2txt(image, lang, chat_id_full, message.caption, model = cfg.img2_txt_model_solve, temperature=0)
                        else:
                            text = img2txt(image, lang, chat_id_full, message.caption)
                        if text:
                            if isinstance(text, str):
                                text = utils.bot_markdown_to_html(text)
                                # text += tr("<b>Every time you ask a new question about the picture, you have to send the picture again.</b>", lang)
                                bot_reply(message, text, parse_mode='HTML',
                                                    reply_markup=get_keyboard('translate', message),
                                                    disable_web_page_preview=True)
                            elif isinstance(text, bytes):
                                m = send_photo(
                                    message,
                                    message.chat.id,
                                    text,
                                    reply_to_message_id=message.message_id,
                                    reply_markup=get_keyboard('hide', message)
                                )
                                log_message(m)
                                return

                            # Check for and send any files generated by skills
                            send_all_files_from_storage(message, chat_id_full)

                        else:
                            bot_reply_tr(message, 'Sorry, I could not answer your question.')
                    return
        except Exception as error:
            traceback_error = traceback.format_exc()
            my_log.log2(f'my_cmd_photo:handle_photo6: {error}\n{traceback_error}')
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'my_cmd_photo:handle_photo7: {unknown}\n{traceback_error}')
