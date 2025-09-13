# my_cmd_doc.py

# Standard library imports
import io
import threading
import traceback
from typing import Any, Callable, Dict, List, Type

# Third-party imports
import telebot

# Local application/library specific imports
import cfg
import my_db
import my_doc_translate
import my_init
import my_log
import my_mistral
import my_pandoc
import my_pdf
import my_psd
import my_sum
import my_subscription
import my_svg
import my_zip
import utils
import utils_llm


def handle_document(
    message: telebot.types.Message,

    # Core objects and constants
    bot: telebot.TeleBot,
    BOT_ID: int,
    _bot_name: str,
    BOT_NAME_DEFAULT: str,

    # Global state dictionaries
    COMMAND_MODE: Dict[str, str],
    DOCUMENT_LOCKS: Dict[str, threading.Lock],
    CHECK_DONATE_LOCKS: Dict[int, threading.Lock],
    FILE_GROUPS: Dict[str, str],

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
    ShowAction: Type,

    # Command handler functions
    handle_voice: Callable,
    handle_photo: Callable,
    reset_: Callable,
    process_wg_config: Callable,
) -> None:
    """Handles document messages"""
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        COMMAND_MODE[chat_id_full] = ''
        # проверка на подписку
        if not my_subscription.check_donate(message, chat_id_full, lang, COMMAND_MODE, CHECK_DONATE_LOCKS, BOT_ID, tr, bot_reply, get_keyboard):
            return

        if chat_id_full in COMMAND_MODE and COMMAND_MODE[chat_id_full] != 'transcribe':
            COMMAND_MODE[chat_id_full] = ''

        is_private = message.chat.type == 'private'
        supch = my_db.get_user_property(chat_id_full, 'superchat') or 0
        if supch == 1:
            is_private = True

        # chat_id = message.chat.id

        message.caption = my_log.restore_message_text(message.caption, message.caption_entities)

        # if check_blocks(chat_id_full) and not is_private:
        #     return
        bot_name = my_db.get_user_property(chat_id_full, 'bot_name') or BOT_NAME_DEFAULT
        if not is_private:
            if not message.caption or not message.caption.startswith('?') or \
                not message.caption.startswith(f'@{_bot_name}') or \
                    not message.caption.startswith(bot_name):
                return

        if chat_id_full in DOCUMENT_LOCKS:
            lock = DOCUMENT_LOCKS[chat_id_full]
        else:
            lock = threading.Lock()
            DOCUMENT_LOCKS[chat_id_full] = lock

        pandoc_support = my_init.PANDOC_SUPPORT_LIST

        if not message.document.mime_type:
            message.document.mime_type = 'application/xml'

        with lock:
            # if message.media_group_id
            # если прислали текстовый файл или pdf
            # то скачиваем и вытаскиваем из них текст и показываем краткое содержание
            if is_private :

                if message.document and message.document.mime_type.startswith('audio/') or \
                    message.document and message.document.mime_type.startswith('video/') or \
                    message.document.file_name.lower().endswith('.aac'):
                    handle_voice(message)
                    return

                if message.document and message.document.mime_type.startswith(('image/','animation/gif')) and message.document.mime_type not in ('image/svg+xml', 'image/vnd.djvu+multipage',):
                    handle_photo(message)
                    return

                with ShowAction(message, 'typing'):
                    try:
                        file_info = bot.get_file(message.document.file_id)
                    except telebot.apihelper.ApiTelegramException as error:
                        if 'file is too big' in str(error):
                            bot_reply_tr(message, 'Too big file')
                            return
                        else:
                            raise error
                    downloaded_file = bot.download_file(file_info.file_path)

                    caption = message.caption or ''
                    caption = caption.strip()

                    # если подпись начинается на load то это запрос на загрузку сохраненной памяти
                    if caption == 'load' or message.document.file_name.startswith('resp.md'):
                        # bytes to string
                        mem_dict = utils_llm.text_to_mem_dict(downloaded_file)
                        reset_(message, say = False)
                        for k, v in mem_dict.items():
                            add_to_bots_mem(k, v, chat_id_full)
                        bot_reply_tr(message, 'Память загружена из файла.')
                        return

                    # если подпись к документу начинается на !tr то это запрос на перевод
                    # и через пробел должен быть указан язык например !tr ru
                    if caption.startswith('!tr '):
                        target_lang = caption[4:].strip()
                        if target_lang:
                            bot_reply_tr(message, 'Translating it will take some time...')
                            new_fname = message.document.file_name if hasattr(message, 'document') else 'noname.txt'
                            new_data = my_doc_translate.translate_file_in_dialog(
                                downloaded_file,
                                lang,
                                target_lang,
                                fname = new_fname,
                                chat_id_full = chat_id_full)
                            if new_data:
                                new_fname2 = f'(translated by @{_bot_name}) {new_fname}'
                                m = send_document(
                                    message,
                                    message.chat.id,
                                    new_data,
                                    reply_to_message_id=message.message_id,
                                    message_thread_id=message.message_thread_id,
                                    caption=new_fname2,
                                    visible_file_name=new_fname2,
                                    disable_notification=True
                                )
                                log_message(m)
                                return
                            else:
                                bot_reply_tr(message, 'Translation failed.')
                                return


                    file_bytes = io.BytesIO(downloaded_file)
                    text = ''
                    if message.document.mime_type == 'application/pdf':
                        if message.caption and message.caption.startswith('!') and not message.caption.startswith('!tr '):
                            message.caption = message.caption[1:].strip()
                            caption = message.caption or ''
                            caption = caption.strip()
                            text = my_pdf.get_text(downloaded_file)
                        else:
                            LIMIT = cfg.LIMIT_PDF_OCR if hasattr(cfg, 'LIMIT_PDF_OCR') else 20
                            amount_of_pages = my_pdf.count_pages_in_pdf(downloaded_file)
                            if amount_of_pages > LIMIT:
                                text = my_mistral.ocr_pdf(downloaded_file, timeout=300)
                            else:
                                text = my_pdf.get_text(downloaded_file)
                            if not text and amount_of_pages > LIMIT:
                                text = my_pdf.get_text(downloaded_file)
                            elif not text and amount_of_pages < LIMIT:
                                text = my_mistral.ocr_pdf(downloaded_file, timeout=300)
                    elif message.document.mime_type == 'application/zip':
                        text = my_zip.extract_and_concatenate(downloaded_file)
                    elif message.document.mime_type in pandoc_support:
                        ext = utils.get_file_ext(file_info.file_path)
                        text = my_pandoc.fb2_to_text(file_bytes.read(), ext)
                    elif message.document.mime_type == 'image/svg+xml' or message.document.file_name.lower().endswith('.psd'):
                        try:
                            if message.document.file_name.lower().endswith('.psd'):
                                image = my_psd.convert_psd_to_jpg(file_bytes.read())
                            elif message.document.mime_type == 'image/svg+xml':
                                image = my_svg.convert_svg_to_png_bytes(file_bytes.read())
                            else:
                                bot_reply_tr(message, f'Unknown image type {message.document.mime_type}')
                                return
                            image = utils.resize_image_dimention(image)
                            image = utils.resize_image(image)
                            #send converted image back
                            m = send_photo(
                                message,
                                message.chat.id,
                                image,
                                reply_to_message_id=message.message_id,
                                message_thread_id=message.message_thread_id,
                                caption=message.document.file_name + '.png',
                            )
                            log_message(m)
                            if not message.caption:
                                proccess_image(chat_id_full, image, message)
                                return
                            text = img2txt(image, lang, chat_id_full, message.caption)
                            if text:
                                text = utils.bot_markdown_to_html(text)
                                # text += tr("<b>Every time you ask a new question about the picture, you have to send the picture again.</b>", lang)
                                bot_reply(message, text, parse_mode='HTML',
                                                    reply_markup=get_keyboard('translate', message))
                            else:
                                bot_reply_tr(message, 'Sorry, I could not answer your question.')
                            return
                        except Exception as error:
                            my_log.log2(f'my_cmd_document:handle_document:svg: {error}')
                            bot_reply_tr(message, 'Не удалось распознать изображение')
                            return
                    else:
                        text = utils.extract_text_from_bytes(downloaded_file)
                        if not text:
                            bot_reply_tr(message, 'Unknown type of file.')
                            my_log.log2(f'my_cmd_document:handle_document: unknown file or empty text {message.document.mime_type} Name: {message.document.file_name} Size: {file_info.file_size}')
                            return

                    if text and text.strip():
                        # если это группа файлов, то прибавляем этот файл к группе
                        if message.media_group_id:

                            if (chat_id_full in FILE_GROUPS and FILE_GROUPS[chat_id_full] != message.media_group_id) or chat_id_full not in FILE_GROUPS:
                                # drop old text
                                prev_text = ''
                            else:
                                prev_text = my_db.get_user_property(chat_id_full, 'saved_file')
                            FILE_GROUPS[chat_id_full] = message.media_group_id

                            my_db.set_user_property(chat_id_full, 'saved_file_name', 'group of files')

                            text = f'{prev_text}\n\n<FILE>\n<NAME>\n{message.document.file_name if hasattr(message, "document") else "noname.txt"}\n</NAME>\n<TEXT>\n{text}\n</TEXT>\n</FILE>\n\n'
                            max_size = cfg.MAX_SAVE_DOCUMENTS_SIZE if hasattr(cfg, 'MAX_SAVE_DOCUMENTS_SIZE') else 1000000
                            if len(text) > max_size:
                                text = text[:max_size]
                            my_db.set_user_property(chat_id_full, 'saved_file', text.strip())
                            bot_reply(message, tr('The file has been added to the group of files, use /ask to query it', lang) + ': ' + message.document.file_name if hasattr(message, 'document') else 'noname.txt')
                        else:
                            # если админ отправил .conf файл и внутри есть нужные поля для настройки ваиргарда то применить этот конфиг
                            if message.from_user.id in cfg.admins and message.document.file_name.endswith('.conf'):
                                if process_wg_config(text, message):
                                    bot_reply_tr(message, 'OK')
                                    return

                            summary = my_sum.summ_text(text, 'text', lang, caption)
                            my_db.set_user_property(chat_id_full, 'saved_file_name', message.document.file_name if hasattr(message, 'document') else 'noname.txt')
                            my_db.set_user_property(chat_id_full, 'saved_file', text)
                            summary_html = utils.bot_markdown_to_html(summary)
                            if summary_html.strip():
                                bot_reply(
                                    message,
                                    summary_html,
                                    parse_mode='HTML',
                                    disable_web_page_preview = True,
                                    reply_markup=get_keyboard('translate', message)
                                )
                            bot_reply_tr(message, 'Use /ask command to query or delete this file. Example:\n/ask generate a short version of part 1.\n? How many persons was invited.')

                            caption_ = tr("юзер попросил ответить по содержанию файла", lang)
                            if caption:
                                caption_ += ', ' + caption
                            add_to_bots_mem(
                                caption_,
                                f'{tr("бот посмотрел файл и ответил:", lang)} {summary}',
                                chat_id_full)
                    else:
                        bot_reply_tr(message, 'Не удалось получить никакого текста из документа.')
                    return
    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'my_cmd_document:handle_document: {unknown}\n{traceback_error}')
        bot_reply_tr(message, 'Unknown error. It may be a password in the file.')
        return

    my_log.log2(f'my_cmd_document:handle_document: Unknown type of file: {message.document.mime_type}')
    bot_reply_tr(message, 'Unknown type of file.')
