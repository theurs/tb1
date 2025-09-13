# my_cmd_voice.py

# Standard library imports
import concurrent.futures
import threading
import time
import traceback
from typing import Any, Callable, Dict, List, Type

# Third-party imports
import telebot

# Local application/library specific imports
import my_db
import my_gemini3
import my_log
import my_stt
import my_subscription
import utils


def handle_voice(
    message: telebot.types.Message,

    # Core objects and constants
    bot: telebot.TeleBot,
    BOT_ID: int,
    _bot_name: str,
    BOT_NAME_DEFAULT: str,

    # Global state dictionaries
    COMMAND_MODE: Dict[str, str],
    CHECK_DONATE_LOCKS: Dict[int, threading.Lock],
    MESSAGE_QUEUE_AUDIO_GROUP: Dict[str, List[telebot.types.Message]],

    # Helper functions and classes
    get_topic_id: Callable[[telebot.types.Message], str],
    get_lang: Callable[[str, telebot.types.Message], str],
    tr: Callable[..., str],
    bot_reply: Callable,
    bot_reply_tr: Callable,
    get_keyboard: Callable,
    transcribe_file: Callable,
    ShowAction: Type,

    # Command handler functions
    echo_all: Callable,
) -> None:
    """Handles voice, video, video_note, and audio messages."""
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    # Проверка на подписку/донат
    if not my_subscription.check_donate(message, chat_id_full, lang, COMMAND_MODE, CHECK_DONATE_LOCKS, BOT_ID, tr, bot_reply, get_keyboard):
        return


    is_private = message.chat.type == 'private'
    supch = my_db.get_user_property(chat_id_full, 'superchat') or 0
    if supch == 1:
        is_private = True


    # определяем какое имя у бота в этом чате, на какое слово он отзывается
    bot_name = my_db.get_user_property(chat_id_full, 'bot_name') or BOT_NAME_DEFAULT
    if not is_private:
        if not message.caption or not message.caption.startswith('?') or \
            not message.caption.startswith(f'@{_bot_name}') or \
                not message.caption.startswith(bot_name):
            return


    # --- ПРИОРИТЕТНАЯ ОБРАБОТКА ДЛЯ /transcribe ---
    if chat_id_full in COMMAND_MODE and COMMAND_MODE[chat_id_full] == 'transcribe':
        try:
            file_info, file_name = (None, 'unknown')
            if message.voice:
                file_info = bot.get_file(message.voice.file_id)
                file_name = 'telegram voice message'
            elif message.audio:
                file_info = bot.get_file(message.audio.file_id)
                file_name = message.audio.file_name
            elif message.video:
                file_info = bot.get_file(message.video.file_id)
                file_name = message.video.file_name
            elif message.video_note:
                file_info = bot.get_file(message.video_note.file_id)
            elif message.document:
                file_info = bot.get_file(message.document.file_id)
                file_name = message.document.file_name

            if file_info:
                downloaded_file = bot.download_file(file_info.file_path)
                transcribe_file(downloaded_file, file_name, message)
            else:
                 bot_reply_tr(message, 'Could not get file info for transcription.')
        except telebot.apihelper.ApiTelegramException as e:
            if 'file is too big' in str(e):
                bot_reply_tr(message, 'Too big file. Try /transcribe command. (Button - [Too big file])')
        except Exception as e:
            my_log.log2(f'my_cmd_voice:handle_voice:transcribe_mode_error: {e}')
            bot_reply_tr(message, 'Error during transcription.')
        finally:
            COMMAND_MODE[chat_id_full] = ''
        return


    # --- Механизм сбора группы сообщений ---
    if chat_id_full not in MESSAGE_QUEUE_AUDIO_GROUP:
        MESSAGE_QUEUE_AUDIO_GROUP[chat_id_full] = [message]
        last_state = MESSAGE_QUEUE_AUDIO_GROUP[chat_id_full]
        n = 10
        while n > 0:
            n -= 1
            time.sleep(0.1)
            new_state = MESSAGE_QUEUE_AUDIO_GROUP.get(chat_id_full, [])
            if len(last_state) != len(new_state):
                last_state = new_state
                n = 10
    else:
        MESSAGE_QUEUE_AUDIO_GROUP[chat_id_full].append(message)
        return

    messages_to_process = MESSAGE_QUEUE_AUDIO_GROUP.pop(chat_id_full, [])
    if not messages_to_process:
        return

    try:
        COMMAND_MODE[chat_id_full] = ''
        # --- ЕДИНАЯ ЛОГИКА ОБРАБОТКИ ДЛЯ ВСЕХ СЛУЧАЕВ ---

        # Если это одиночный файл без подписи в режиме "только транскрипция"
        is_transcribe_only = (
            my_db.get_user_property(chat_id_full, 'transcribe_only') and
            len(messages_to_process) == 1 and
            not messages_to_process[0].caption
        )
        is_voice_only_mode = my_db.get_user_property(chat_id_full, 'voice_only_mode') or 0

        with ShowAction(messages_to_process[0], 'typing'):
            # Вспомогательная функция для параллельной транскрипции
            def transcribe_in_parallel(msg_to_transcribe):
                try:
                    file_info, file_name = (None, 'unknown.ogg')
                    if msg_to_transcribe.voice:
                        file_info = bot.get_file(msg_to_transcribe.voice.file_id)
                        file_name = f'voice_message_{msg_to_transcribe.message_id}.ogg'
                    elif msg_to_transcribe.audio:
                        file_info = bot.get_file(msg_to_transcribe.audio.file_id)
                        file_name = msg_to_transcribe.audio.file_name or f'audio_{msg_to_transcribe.message_id}.mp3'
                    elif msg_to_transcribe.video:
                        file_info = bot.get_file(msg_to_transcribe.video.file_id)
                        file_name = msg_to_transcribe.video.file_name or f'video_{msg_to_transcribe.message_id}.mp4'
                    elif msg_to_transcribe.video_note:
                        file_info = bot.get_file(msg_to_transcribe.video_note.file_id)
                        file_name = f'video_note_{msg_to_transcribe.message_id}.mp4'
                    elif msg_to_transcribe.document:
                        file_info = bot.get_file(msg_to_transcribe.document.file_id)
                        file_name = msg_to_transcribe.document.file_name
                    if file_info:
                        downloaded_file = bot.download_file(file_info.file_path)
                        transcription = my_stt.stt(downloaded_file, lang, chat_id_full)
                        return {'filename': file_name, 'transcription': transcription or '[ERROR: Transcription failed]'}
                except Exception as e:
                    if 'file is too big' in str(e):
                        bot_reply_tr(message, 'Too big file. Try /transcribe command. (Button - [Too big file])')
                    else:
                        my_log.log2(f'my_cmd_voice:handle_voice:transcribe_in_parallel_error: {e}')
                return {'filename': 'error_file', 'transcription': '[ERROR: Processing failed]'}

            # Запускаем транскрипцию в потоках, сохраняя порядок
            transcribed_data = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                results_iterator = executor.map(transcribe_in_parallel, messages_to_process)
                transcribed_data = list(results_iterator) # Преобразуем генератор в список

            full_transcription_text = ""
            for item in transcribed_data:
                # Добавляем имя файла, если файлов больше одного
                if len(transcribed_data) > 1:
                    full_transcription_text += f"<b>{utils.html.escape(item['filename'])}:</b>\n"
                full_transcription_text += f"{utils.html.escape(item.get('transcription', ''))}\n\n"

            full_transcription_text = full_transcription_text.strip()

            msg = messages_to_process[0] if messages_to_process else None
            # если это видео и в нем нет текста то пробуем обработать как видео
            is_video = msg and (msg.video or msg.video_note or msg.document)
            many_text = len(full_transcription_text) > 100
            if is_video and not many_text:
                try:
                    if msg.video: file_id = msg.video.file_id
                    elif msg.video_note: file_id = msg.video_note.file_id
                    elif msg.document: file_id = msg.document.file_id
                    file_info = bot.get_file(file_id)
                    if file_info:
                        video_bytes = bot.download_file(file_info.file_path)
                        query = msg.caption or tr('Describe this video, make text transcription on user language:', lang) + ' [' + lang + ']'
                        system_prompt = my_db.get_user_property(chat_id_full, 'role') or ''
                        temperature = my_db.get_user_property(chat_id_full, 'temperature') or 1
                        description = my_gemini3.video2txt(
                            video_data=video_bytes,
                            prompt=query,
                            system=system_prompt,
                            chat_id=chat_id_full,
                            temperature=temperature,
                            timeout=300
                        )

                    # Создаем "фейковое" сообщение для передачи в основной обработчик
                    fake_message = msg # тут должно было быть копирование но похоже происходит только присвоение

                    # Формируем XML-подобную запись для памяти
                    xml_memory_entry = "User sent a video:\n\n<video_analysis_result>\n"
                    xml_memory_entry += f"    <user_query>\n        {query}\n    </user_query>\n"
                    xml_memory_entry += f"    <system_response>\n        {utils.html.escape(description)}\n    </system_response>\n"
                    xml_memory_entry += "</video_analysis_result>"

                    fake_message.text = xml_memory_entry
                    fake_message.entities = []

                    # Передаем "фейковое" сообщение с читаемым текстом в основной обработчик
                    echo_all(fake_message)
                    return

                except Exception as video_as_img_error:
                    if 'file is too big' in str(video_as_img_error):
                        bot_reply_tr(message, 'Too big file')
                        return
                    traceback_error = traceback.format_exc()
                    my_log.log2(f'my_cmd_voice:handle_voice:video_as_image_fallback: {video_as_img_error}\n\n{traceback_error}')


            # Отправляем, если есть что отправлять, и если это не режим "только голос"
            if full_transcription_text and not is_voice_only_mode:
                bot_reply(
                    messages_to_process[0],
                    full_transcription_text,
                    parse_mode='HTML',
                    reply_markup=get_keyboard('translate', messages_to_process[0]),
                    collapse_text = True
                )

            # Если это был режим transcribe_only, на этом все
            if is_transcribe_only:
                return


            # Если это был режим transcribe_only, просто отправляем текст и выходим
            if is_transcribe_only:
                transcription = transcribed_data[0].get('transcription', '')
                if transcription and not transcription.startswith('[ERROR'):
                    bot_reply(messages_to_process[0], utils.bot_markdown_to_html(transcription),
                              parse_mode='HTML',
                              reply_markup=get_keyboard('translate', messages_to_process[0]))
                else:
                    bot_reply_tr(messages_to_process[0], 'Не удалось распознать текст')
                return

            # Собираем все подписи из группы
            combined_caption = "\n".join(
                [my_log.restore_message_text(msg.caption, msg.caption_entities) for msg in messages_to_process if msg.caption]
            ).strip()

            # Формируем XML-подобный промпт
            xml_prompt = "<audio_batch_analysis_request>\n"
            if combined_caption:
                xml_prompt += f"    <user_instruction>\n        {utils.html.escape(combined_caption)}\n    </user_instruction>\n"
            else:
                # Если подписей не было, но файл всего один, считаем, что пользователь просто хочет транскрипцию и ответ от ЛЛМ
                if len(messages_to_process) == 1:
                     xml_prompt += f"    <user_instruction>\n        {tr('User sent an audio file.', lang)}\n    </user_instruction>\n"
                else: # Если файлов много без подписи
                     xml_prompt += f"    <user_instruction>\n        {tr('User sent a batch of audio files.', lang)}\n    </user_instruction>\n"

            xml_prompt += "    <audio_files>\n"
            for item in transcribed_data:
                xml_prompt += "        <file>\n"
                xml_prompt += f"            <filename>{utils.html.escape(item['filename'])}</filename>\n"
                xml_prompt += f"            <transcription>\n                {utils.html.escape(item.get('transcription', ''))}\n            </transcription>\n"
                xml_prompt += "        </file>\n"
            xml_prompt += "    </audio_files>\n"
            xml_prompt += "</audio_batch_analysis_request>"

            # Создаем "фейковое" сообщение и передаем собранный запрос в основной обработчик
            fake_message = messages_to_process[0]
            fake_message.text = xml_prompt
            fake_message.entities = []

            echo_all(fake_message)

    except Exception as e:
        error_traceback = traceback.format_exc()
        my_log.log2(f'my_cmd_voice:handle_voice_main_logic: {e}\n{error_traceback}')
        # Гарантированно очищаем очередь, если что-то пошло не так
        if chat_id_full in MESSAGE_QUEUE_AUDIO_GROUP:
            del MESSAGE_QUEUE_AUDIO_GROUP[chat_id_full]
