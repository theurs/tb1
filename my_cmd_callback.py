# my_cmd_callback.py

# Standard library imports
import io
import threading
import traceback
from typing import Any, Callable, Dict, Type

# Third-party imports
import telebot

# Local application/library specific imports
import cfg
import my_cerebras
import my_db
import my_ddg
import my_gemini3
import my_init
import my_log
import my_openrouter
import my_qrcode
import my_subscription
import my_tavily
import my_tts
import utils


def callback_inline_thread(
    call: telebot.types.CallbackQuery,
    # Core objects
    bot: telebot.TeleBot,
    # Global state dictionaries
    COMMAND_MODE: Dict[str, str],
    TTS_LOCKS: Dict[str, threading.Lock],
    GOOGLE_LOCKS: Dict[str, threading.Lock],
    SEARCH_PICS: Dict[str, str],
    UNCAPTIONED_PROMPTS: Dict[str, str],
    UNCAPTIONED_IMAGES: Dict[str, Any],
    # Helper functions and classes
    get_topic_id: Callable[[telebot.types.Message], str],
    get_lang: Callable[[str, telebot.types.Message], str],
    tr: Callable[..., str],
    get_config_msg: Callable[[str, str], str],
    bot_reply: Callable,
    bot_reply_tr: Callable,
    get_keyboard: Callable,
    add_to_bots_mem: Callable,
    log_message: Callable,
    send_document: Callable,
    send_media_group: Callable,
    is_admin_member: Callable[[telebot.types.CallbackQuery], bool],
    ShowAction: Type,
    # Command handler functions
    reset_: Callable,
    process_image_stage_2: Callable,
    echo_all: Callable,
    tts: Callable,
    language: Callable,
) -> None:
    """Handles inline keyboard callbacks"""
    try:
        message = call.message
        chat_id = message.chat.id
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        MSG_CONFIG = get_config_msg(chat_id_full, lang)


        def _transfer_chat_memory(user_id: str, prev_mode: str, new_mode: str) -> None:
            """
            Transfers chat history between Gemini and OpenAI compatible models.
            Args:
                user_id: The full user identifier.
                prev_mode: The previous chat mode.
                new_mode: The new chat mode.
            """
            # from gemini to openai-like
            if 'gemini' in prev_mode and 'gemini' not in new_mode:
                new_mem = my_gemini3.gemini_to_openai_mem(user_id)
                my_db.set_user_property(user_id, 'dialog_openrouter', my_db.obj_to_blob(new_mem))
            # from openai-like to gemini
            elif 'gemini' not in prev_mode and 'gemini' in new_mode:
                new_mem = my_gemini3.openai_to_gemini_mem(user_id)
                my_db.set_user_property(user_id, 'dialog_gemini3', my_db.obj_to_blob(new_mem))

        def _set_chat_mode(new_mode: str) -> None:
            """
            Sets a new chat mode for the user and handles memory transfer.
            Args:
                new_mode: The target chat mode to set.
            """
            prev_mode = my_db.get_user_property(chat_id_full, 'chat_mode') or cfg.chat_mode_default
            if prev_mode != new_mode:
                _transfer_chat_memory(chat_id_full, prev_mode, new_mode)
                my_db.set_user_property(chat_id_full, 'chat_mode', new_mode)


        if call.data == 'clear_history':
            # обработка нажатия кнопки "Стереть историю"
            reset_(message)
            bot.delete_message(message.chat.id, message.message_id)


        elif call.data.startswith('histsize_toggle_'):
            # handle memory toggle button
            action = call.data.split('_')[-1]
            default_size = 1000

            if action == 'enable':
                my_db.set_user_property(chat_id_full, 'max_history_size', default_size)
            else:  # disable
                my_db.set_user_property(chat_id_full, 'max_history_size', 0)

            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id,
                                text=MSG_CONFIG, disable_web_page_preview=False, reply_markup=get_keyboard('config_behavior', message))


        elif call.data == 'config' or call.data.startswith('config_'):
            bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=message.message_id,
                text=MSG_CONFIG,  # Use the pre-fetched config message text
                parse_mode='HTML',
                disable_web_page_preview=True,
                reply_markup=get_keyboard(call.data, message) # Pass the callback data to get the right menu
            )


        elif call.data == 'image_prompt_describe':
            COMMAND_MODE[chat_id_full] = ''
            image_prompt = tr(my_init.PROMPT_DESCRIBE, lang)
            process_image_stage_2(image_prompt, chat_id_full, lang, message)

        elif call.data == 'image_prompt_text':
            COMMAND_MODE[chat_id_full] = ''
            image_prompt = tr(my_init.PROMPT_COPY_TEXT, lang)
            process_image_stage_2(image_prompt, chat_id_full, lang, message)

        elif call.data == 'image_prompt_ocr':
            COMMAND_MODE[chat_id_full] = ''
            image_prompt = 'OCR'
            process_image_stage_2(image_prompt, chat_id_full, lang, message)

        elif call.data == 'image_prompt_text_tts':
            COMMAND_MODE[chat_id_full] = ''
            image_prompt = tr(my_init.PROMPT_COPY_TEXT_TTS, lang)
            process_image_stage_2(image_prompt, chat_id_full, lang, message)

        elif call.data == 'image_prompt_text_tr':
            COMMAND_MODE[chat_id_full] = ''
            image_prompt = tr(my_init.PROMPT_COPY_TEXT_TR, lang)
            process_image_stage_2(image_prompt, chat_id_full, lang, message)

        elif call.data == 'image_prompt_generate':
            COMMAND_MODE[chat_id_full] = ''
            image_prompt = tr(my_init.PROMPT_REPROMPT, lang) + \
                        '\n\n```prompt\n/img image generation prompt in english```\n\n'
            process_image_stage_2(image_prompt, chat_id_full, lang, message, temp = 1.5)

        elif call.data == 'image_prompt_solve':
            COMMAND_MODE[chat_id_full] = ''
            image_prompt = tr(my_init.PROMPT_SOLVE, lang) + ' ' + f'Answer in [{lang}] language.'
            process_image_stage_2(image_prompt, chat_id_full, lang, message, model = cfg.img2_txt_model_solve, temp = 0, timeout = 60)

        elif call.data == 'image_prompt_qrcode':
            COMMAND_MODE[chat_id_full] = ''
            if chat_id_full in UNCAPTIONED_IMAGES:
                img = UNCAPTIONED_IMAGES[chat_id_full][1]
                text = my_qrcode.get_text(img)
                if text:
                    bot_reply(message, text)
                    add_to_bots_mem(tr('user asked to get the text from an qrcode image', lang), text, chat_id_full)
                    return
            bot_reply_tr(message, 'No image found or text not found')

        elif call.data == 'image_prompt_repeat_last':
            COMMAND_MODE[chat_id_full] = ''
            process_image_stage_2(UNCAPTIONED_PROMPTS[chat_id_full], chat_id_full, lang, message)

        elif call.data.startswith('buy_stars_'):

            amount = int(call.data.split('_')[-1])
            if amount == 0:
                bot_reply_tr(message, 'Please enter the desired amount of stars you would like to donate', reply_markup=get_keyboard('command_mode', message))
                COMMAND_MODE[chat_id_full] = 'enter_start_amount'
                return
            prices = [telebot.types.LabeledPrice(label = "XTR", amount = amount)]
            try:
                bot.send_invoice(
                    call.message.chat.id,
                    title=tr('Donate stars amount:', lang) + ' ' + str(amount),
                    description = tr('Donate stars amount:', lang) + ' ' + str(amount),
                    invoice_payload="stars_donate_payload",
                    provider_token = "",  # Для XTR этот токен может быть пустым
                    currency = "XTR",
                    prices = prices,
                    reply_markup = get_keyboard(f'pay_stars_{amount}', message)
                )
            except Exception as error:
                my_log.log_donate(f'my_cmd_callback:callback_inline_thread1: {error}\n\n{call.message.chat.id} {amount}')
                bot_reply_tr(message, 'An unexpected error occurred during the payment process. Please try again later. If the problem persists, contact support.')

        elif call.data == 'continue_gpt':
            # обработка нажатия кнопки "Продолжай GPT"
            message.dont_check_topic = True
            message.next_button_pressed = True
            echo_all(message, tr('Продолжай', lang))
            return
        elif call.data == 'cancel_command':
            # обработка нажатия кнопки "Отменить ввод команды"
            COMMAND_MODE[chat_id_full] = ''
            bot.delete_message(message.chat.id, message.message_id)
        elif call.data == 'cancel_command_not_hide':
            # обработка нажатия кнопки "Отменить ввод команды, но не скрывать"
            COMMAND_MODE[chat_id_full] = ''
            # bot.delete_message(message.chat.id, message.message_id)
            bot_reply_tr(message, 'Режим поиска в гугле отключен')
        # режим автоответов в чате, бот отвечает на все реплики всех участников
        # комната для разговоров с ботом Ж)
        elif call.data == 'admin_chat' and is_admin_member(call):
            supch = my_db.get_user_property(chat_id_full, 'superchat') or 0
            if supch == 1:
                supch = 0
                my_db.set_user_property(chat_id_full, 'superchat', 0)
            else:
                supch = 1
                my_db.set_user_property(chat_id_full, 'superchat', 1)
            bot.edit_message_text(chat_id=chat_id, parse_mode='HTML', message_id=message.message_id,
                                text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config', message, 'admin'))
        elif call.data == 'erase_answer':
            # обработка нажатия кнопки "Стереть ответ"
            COMMAND_MODE[chat_id_full] = ''
            try:
                bot.delete_message(message.chat.id, message.message_id)
            except telebot.apihelper.ApiTelegramException as error:
                if "Bad Request: message can't be deleted for everyone" not in str(error):
                    traceback_error = traceback.format_exc()
                    my_log.log2(f'my_cmd_callback:callback_inline_thread2: {str(error)}\n\n{traceback_error}')

        elif call.data == 'tts':

            if chat_id_full not in TTS_LOCKS:
                TTS_LOCKS[chat_id_full] = threading.Lock()

            if TTS_LOCKS[chat_id_full].locked():
                return # If a TTS process is already running for this user, ignore the new request

            with TTS_LOCKS[chat_id_full]:
                text = message.text or message.caption
                text = text.strip()
                if text:
                    detected_lang = my_tts.detect_lang_carefully(text)
                    if not detected_lang:
                        detected_lang = lang or "de"

                    rewrited_text = my_gemini3.rewrite_text_for_tts(text, chat_id_full)
                    if not rewrited_text:
                        rewrited_text = my_cerebras.rewrite_text_for_tts(text, chat_id_full)
                        if not rewrited_text:
                            rewrited_text = text
                    message.text = f'/tts {detected_lang} {rewrited_text}'
                    tts(message)
        elif call.data.startswith('select_lang-'):
            l = call.data[12:]
            message.text = f'/lang {l}'
            language(message)
        elif call.data in ('translate', 'translate_chat'):
            # реакция на клавиатуру, кнопка перевести текст
            with ShowAction(message, 'typing'):
                text = message.text if message.text else message.caption
                entities = message.entities if message.entities else message.caption_entities
                kbd = 'translate' if call.data == 'translate' else 'chat'
                text = my_log.restore_message_text(text, entities)
                translated = tr(text, lang, help = 'Please, provide a high-quality artistic translation, format the output using Markdown.', save_cache = False)
                html = utils.bot_markdown_to_html(translated)

                if translated and translated != text:
                    if message.text:
                        func = bot.edit_message_text
                    else:
                        func = bot.edit_message_caption
                    func(
                        chat_id=message.chat.id,
                        message_id=message.message_id,
                        text=html,
                        parse_mode='HTML',
                        disable_web_page_preview = True,
                        reply_markup=get_keyboard(kbd, message))

        elif call.data.startswith('search_pics_'):
            # Поиск картинок в дак дак гоу
            if chat_id_full not in GOOGLE_LOCKS:
                GOOGLE_LOCKS[chat_id_full] = threading.Lock()
            with GOOGLE_LOCKS[chat_id_full]:
                hash_ = call.data[12:]
                if hash_ in SEARCH_PICS:
                    with ShowAction(message, 'upload_photo'):
                        query = SEARCH_PICS[hash_]
                        images = []
                        if hasattr(cfg, 'TAVILY_KEYS') and len(cfg.TAVILY_KEYS) > 0:
                            images = my_tavily.search_images(query, user_id=chat_id_full)
                        if not images:
                            images = my_ddg.get_images(query)

                        medias = []

                        if images:
                            medias = [telebot.types.InputMediaPhoto(x[0], caption = x[1][:900] if x[1] is not None else '') for x in images]

                        if medias:
                            msgs_ids = send_media_group(
                                message,
                                message.chat.id,
                                medias,
                                reply_to_message_id=message.message_id,
                            )
                            log_message(msgs_ids)
                            return
                        bot_reply_tr(message, 'Не смог найти картинки по этому запросу.')
        elif call.data == 'download_saved_text':
            # отдать юзеру его текст
            if my_db.get_user_property(chat_id_full, 'saved_file_name'):
                with ShowAction(message, 'typing'):
                    buf = io.BytesIO()
                    buf.write(my_db.get_user_property(chat_id_full, 'saved_file').encode())
                    buf.seek(0)
                    fname = utils.safe_fname(my_db.get_user_property(chat_id_full, 'saved_file_name')) + '.txt'
                    if fname.endswith('.txt.txt'):
                        fname = fname[:-4]
                    try:
                        m = send_document(
                            message,
                            message.chat.id,
                            document=buf,
                            message_thread_id=message.message_thread_id,
                            caption=fname,
                            visible_file_name = fname
                        )
                    except telebot.apihelper.ApiTelegramException as error:
                        if 'message thread not found' not in str(error):
                            raise error
                        m = send_document(
                            message,
                            message.chat.id,
                            document=buf,
                            caption=fname,
                            visible_file_name = fname
                        )
                    log_message(m)
            else:
                bot_reply_tr(message, 'No text was saved.')


        elif call.data == 'delete_saved_text':
            # удалить сохраненный текст
            if my_db.get_user_property(chat_id_full, 'saved_file_name'):
                my_db.delete_user_property(chat_id_full, 'saved_file_name')
                my_db.delete_user_property(chat_id_full, 'saved_file')
                bot_reply_tr(message, 'Saved text deleted.')
            else:
                bot_reply_tr(message, 'No text was saved.')
            COMMAND_MODE[chat_id_full] = ''



        # --- Model Selection (Stays on Models menu) ---
        elif call.data.startswith('select_'):
            model_id = call.data[7:] # Extract model id from 'select_...'

            # Map callback IDs to internal mode names if they differ
            mode_map = {
                'gemini15': 'gemini15',
                'gemini': 'gemini25_flash',
            }
            mode_to_set = mode_map.get(model_id, model_id)

            # --- Handle models requiring keys ---
            key_required = False
            if mode_to_set in ('gpt-4o', 'gpt_41', 'gpt_41_mini'):
                if not my_subscription.github_models(chat_id_full):
                    bot.answer_callback_query(call.id, text=tr('Insert your github key first. /keys', lang), show_alert=True)
                    key_required = True
            elif mode_to_set == 'openrouter':
                if chat_id_full not in my_openrouter.KEYS:
                    bot.answer_callback_query(call.id, text=tr('Надо вставить свои ключи что бы использовать openrouter. Команда /openrouter', lang), show_alert=True)
                    key_required = True

            # If a key was required and missing, stop processing here.
            if key_required:
                return

            # Set the new mode and transfer memory if needed
            _set_chat_mode(mode_to_set)

            # Redraw the model selection menu to show the updated checkmark
            bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=message.message_id,
                text=MSG_CONFIG,
                parse_mode='HTML',
                disable_web_page_preview=True,
                reply_markup=get_keyboard('config_models', message)
            )



        elif call.data == 'general_reset':
            reset_(message, say = True, chat_id_full = chat_id_full)




        # --- TTS Voice Provider Cycling (Stays on TTS menu) ---
        elif call.data == 'tts_female' and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'tts_gender', 'male')
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id,
                                text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config_tts', message))

        elif call.data == 'tts_male' and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'tts_gender', 'google_female')
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id,
                                text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config_tts', message))

        elif call.data == 'tts_google_female' and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'tts_gender', 'gemini_Achernar')
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id,
                                text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config_tts', message))

        elif call.data.startswith('tts_gemini') and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'tts_gender', 'openai_alloy')
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id,
                                text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config_tts', message))

        elif call.data.startswith('tts_openai') and is_admin_member(call):
            my_db.set_user_property(chat_id_full, 'tts_gender', 'female')
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id,
                                text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config_tts', message))

        # --- Specific Voice Selection (Stays on TTS menu) ---
        elif call.data.startswith('switch_openai_') and is_admin_member(call):
            voice = call.data.split('_')[-1]
            my_db.set_user_property(chat_id_full, 'tts_gender', f'openai_{voice}')
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id,
                                text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config_tts', message))

        elif call.data.startswith('switch_gemini_') and is_admin_member(call):
            voice = call.data.split('_')[-1]
            my_db.set_user_property(chat_id_full, 'tts_gender', f'gemini_{voice}')
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id,
                                text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config_tts', message))





        elif call.data.startswith('switch_do_nothing') and is_admin_member(call):
            pass

        elif call.data == 'send_message_chat_switch' and is_admin_member(call):
            send_message = my_db.get_user_property(chat_id_full, 'send_message') or False
            if send_message:
                my_db.set_user_property(chat_id_full, 'send_message', False)
            else:
                my_db.set_user_property(chat_id_full, 'send_message', True)
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                    text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config', message))

        elif call.data == 'switch_action_style':
            action_style = my_db.get_user_property(chat_id_full, 'action_style') or ''
            if not action_style:
                my_db.set_user_property(chat_id_full, 'action_style', 'message')
            else:
                my_db.set_user_property(chat_id_full, 'action_style', '')
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                    text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config', message))



        # --- Behavior Toggles (Stays on Behavior menu) ---
        elif call.data in ('voice_only_mode_disable', 'voice_only_mode_enable'):
            new_state = (call.data == 'voice_only_mode_enable')
            my_db.set_user_property(chat_id_full, 'voice_only_mode', new_state)
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config_tts', message))

        elif call.data in ('transcribe_only_chat_disable', 'transcribe_only_chat_enable'):
            new_state = (call.data == 'transcribe_only_chat_enable')
            my_db.set_user_property(chat_id_full, 'transcribe_only', new_state)
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id, 
                                text = MSG_CONFIG, disable_web_page_preview = False, reply_markup=get_keyboard('config_behavior', message))



        # --- STT Engine Selection (Stays on STT menu) ---
        elif call.data.startswith('switch_speech_to_text_'):
            # The prefix is 'switch_speech_to_text_', which is 22 characters long
            speech_to_text_engine = call.data[22:]

            my_db.set_user_property(chat_id_full, 'speech_to_text_engine', speech_to_text_engine)

            bot.edit_message_text(
                chat_id=message.chat.id, 
                message_id=message.message_id,
                text=MSG_CONFIG, 
                parse_mode='HTML', 
                disable_web_page_preview=False, 
                reply_markup=get_keyboard('config_stt', message)
            )



        # --- Behavior Toggles (All stay on Behavior menu) ---
        elif call.data.startswith('chat_kbd_'):
            # Note the logic inversion: enabling the button means 'disabled_kbd' is False.
            new_state = (call.data == 'chat_kbd_disable')
            my_db.set_user_property(chat_id_full, 'disabled_kbd', new_state)
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id,
                                text=MSG_CONFIG, disable_web_page_preview=False, reply_markup=get_keyboard('config_behavior', message))

        elif call.data.startswith('action_style_'):
            new_state = 'message' if call.data == 'action_style_enable' else ''
            my_db.set_user_property(chat_id_full, 'action_style', new_state)
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id,
                                text=MSG_CONFIG, disable_web_page_preview=False, reply_markup=get_keyboard('config_behavior', message))

        elif call.data.startswith('voice_only_mode_'):
            new_state = (call.data == 'voice_only_mode_enable')
            my_db.set_user_property(chat_id_full, 'voice_only_mode', new_state)
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id,
                                text=MSG_CONFIG, disable_web_page_preview=False, reply_markup=get_keyboard('config_behavior', message))

        elif call.data.startswith('transcribe_only_chat_'):
            new_state = (call.data == 'transcribe_only_chat_enable')
            my_db.set_user_property(chat_id_full, 'transcribe_only', new_state)
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id,
                                text=MSG_CONFIG, disable_web_page_preview=False, reply_markup=get_keyboard('config_behavior', message))

        elif call.data.startswith('send_message_chat_switch_'):
            new_state = (call.data == 'send_message_chat_switch_enable')
            my_db.set_user_property(chat_id_full, 'send_message', new_state)
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id,
                                text=MSG_CONFIG, disable_web_page_preview=False, reply_markup=get_keyboard('config_behavior', message))

        elif call.data.startswith('admin_chat_'):
            new_state = 1 if call.data == 'admin_chat_enable' else 0
            my_db.set_user_property(chat_id_full, 'superchat', new_state)
            bot.edit_message_text(chat_id=message.chat.id, parse_mode='HTML', message_id=message.message_id,
                                text=MSG_CONFIG, disable_web_page_preview=False, reply_markup=get_keyboard('config_behavior', message))



    except Exception as unexpected_error:
        if 'Bad Request: message is not modified' in str(unexpected_error) or \
           'Bad Request: message to be replied not found' in str(unexpected_error) or \
           'Bad Request: message to edit not found' in str(unexpected_error):
            return
        traceback_error = traceback.format_exc()
        my_log.log2(f'my_cmd_callback:callback_query_handler: {unexpected_error}\n\n{traceback_error}')

