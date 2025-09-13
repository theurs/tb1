import random
import re
import time
import threading
import traceback
from typing import Any, Callable, Dict, List, Tuple, Type, Union

import telebot

import cfg
import my_db
import my_genimg
# import my_gemini3
import my_log
import my_subscription
import utils


def image_gen(
    message: telebot.types.Message,

    # Core objects and constants
    _bot_name: str,
    BOT_ID: int,
    pics_group: Union[int, None],

    # Global state dictionaries
    IMG_MODE_FLAG: Dict[str, str],
    COMMAND_MODE: Dict[str, str],
    IMG_GEN_LOCKS: Dict[str, threading.Lock],
    BING_FAILS: Dict[str, List[Union[int, float]]],
    CHECK_DONATE_LOCKS: Dict[int, threading.Lock],

    # Helper functions and classes
    get_topic_id: Callable[[telebot.types.Message], str],
    get_lang: Callable[[str, telebot.types.Message], str],
    tr: Callable[..., str],
    bot_reply: Callable,
    bot_reply_tr: Callable,
    get_keyboard: Callable,
    add_to_bots_mem: Callable,
    send_images_to_user: Callable,
    send_images_to_pic_group: Callable,
    ShowAction: Type,
    NoLock: Type,

    # Command handler functions
    image_flux_gen: Callable,
) -> None:
    """Generates a picture from a description"""
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)


        if message.text.lower().startswith('/i'):
            if chat_id_full in IMG_MODE_FLAG:
                del IMG_MODE_FLAG[chat_id_full]


        # # в группе рисовать можно только тем у кого есть все ключи или подписка или админы
        # if message.chat.id < 0:
        #     chat_id_full_from = f'[{message.from_user.id}] [0]'
        #     user_id = message.from_user.id
        #     have_keys = (chat_id_full_from in my_gemini_general.USER_KEYS and chat_id_full_from in my_groq.USER_KEYS) or \
        #             user_id in cfg.admins or \
        #             (my_db.get_user_property(chat_id_full_from, 'telegram_stars') or 0) >= 50
        #     if not have_keys:
        #         return


        # не использовать бинг для рисования запрещенки, он за это банит
        NSFW_FLAG = False
        if message.text.endswith('NSFW'):
            NSFW_FLAG = True
            message.text = message.text[:-4]

        # забаненный в бинге юзер
        if my_db.get_user_property(chat_id_full, 'blocked_bing'):
            NSFW_FLAG = True

        # if NSFW_FLAG:
        #     bot_reply(message, tr('Images was blocked.', lang) + ' ' + 'https://www.google.com/search?q=nsfw', disable_web_page_preview=True)
        #     return

        show_timeout = 5 # как долго показывать активность

        # рисовать только бингом, команда /bing
        BING_FLAG = 0
        if message.text.endswith('[{(BING)}]'):
            message.text = message.text[:-10]
            BING_FLAG = 1

        # рисовать только gpt, команда /bing_gpt
        GPT_FLAG = 0
        if message.text.endswith('[{(GPT)}]'):
            message.text = message.text[:-9]
            GPT_FLAG = 1

        # 10х и 20х отключены пока
        # BING_FLAG = 0

        if chat_id_full in IMG_GEN_LOCKS:
            lock = IMG_GEN_LOCKS[chat_id_full]
        else:
            # lock = threading.Lock()
            lock = NoLock() # временно отключаем блокировку, юзеры смогут делать несколько запросов одновременно
            IMG_GEN_LOCKS[chat_id_full] = lock

        COMMAND_MODE[chat_id_full] = ''
        # проверка на подписку
        if not my_subscription.check_donate(message, chat_id_full, lang, COMMAND_MODE, CHECK_DONATE_LOCKS, BOT_ID, tr, bot_reply, get_keyboard):
            return



        # не ставить в очередь рисование, кроме белого списка
        # if lock.locked():
        #     if hasattr(cfg, 'ALLOW_PASS_NSFW_FILTER') and utils.extract_user_id(chat_id_full) in cfg.ALLOW_PASS_NSFW_FILTER:
        #         pass
        #     else:
        #         return



        # # не ставить в очередь рисование x10 x20 bing
        # if lock.locked() and BING_FLAG > 1:
        #     return

        with lock:

            # замедление для юзеров из черного списка
            # случайное время от 1 до 4 минут
            # пауза до включения отображения активности что бы не дрочить сервер телеграма зря
            if hasattr(cfg, 'SLOW_MODE_BING') and utils.extract_user_id(chat_id_full) in cfg.SLOW_MODE_BING:
                if my_db.count_imaged_per24h(chat_id_full) > 500:
                    time.sleep(random.randint(60, 240))

            draw_text = tr('draw', lang)
            if lang == 'ru':
                draw_text = 'нарисуй'
            if lang == 'en':
                draw_text = 'draw'
            help = f"""/image {tr('Text description of the picture, what to draw.', lang)}

/image {tr('космический корабль в полете', lang)}
/img {tr('средневековый замок с рвом и мостом', lang)}
/i {tr('подводный мир с рыбами и кораллами', lang)}
<b>{draw_text}</b> {tr('красивый сад с цветами и фонтаном', lang)}

{tr('Use /bing command for Bing only.', lang)}
{tr('Use /gpt command for GPT4o only.', lang)}
{tr('Use /flux command for black-forest-labs/flux-dev only.', lang)}
{tr('Use /gem command for Gemini only.', lang)}

{tr('Write what to draw, what it looks like.', lang)}
"""
            message.text = my_log.restore_message_text(message.text, message.entities)
            prompt = message.text.split(maxsplit = 1)

            if len(prompt) > 1:
                prompt = prompt[1].strip()
                COMMAND_MODE[chat_id_full] = ''

                if prompt == tr('Продолжай', lang):
                    return

                if prompt:
                    if chat_id_full in IMG_MODE_FLAG:
                        if IMG_MODE_FLAG[chat_id_full] == 'bing':
                            BING_FLAG = 1
                        elif IMG_MODE_FLAG[chat_id_full] == 'gpt':
                            GPT_FLAG = 1

                # get chat history for content
                # conversation_history = my_gemini3.get_mem_as_string(chat_id_full) or ''
                # conversation_history = conversation_history[-8000:]
                # как то он совсем плохо стал работать с историей, отключил пока что
                conversation_history = ''

                with ShowAction(message, 'upload_photo', max_timeout = show_timeout):
                    moderation_flag = False

                    if NSFW_FLAG:
                        images = my_genimg.gen_images(prompt, moderation_flag, chat_id_full, conversation_history, use_bing = False)
                    else:
                        if BING_FLAG:
                            bf = BING_FAILS[chat_id_full] if chat_id_full in BING_FAILS else [0, 0]
                            if bf[0] >= 5:
                                if time.time() - bf[1] > 5 * 60:
                                    bf = [0, 0]
                            if bf[0] < 5:
                                images = my_genimg.gen_images_bing_only(prompt, chat_id_full, conversation_history, BING_FLAG)
                                if not images:
                                    bf[0] += 1
                                    bf[1] = time.time()
                            else:
                                images = []
                                time.sleep(random.randint(5,10))
                            if not images:
                                bot_reply_tr(message, 'Bing не смог ничего нарисовать.')
                            BING_FAILS[chat_id_full] = bf
                        elif GPT_FLAG:
                            bf = BING_FAILS[chat_id_full] if chat_id_full in BING_FAILS else [0, 0]
                            if bf[0] >= 5:
                                if time.time() - bf[1] > 5 * 60:
                                    bf = [0, 0]
                            if bf[0] < 5:
                                images = my_genimg.gen_images_bing_only(prompt, chat_id_full, conversation_history, BING_FLAG, model='gpt')
                                if not images:
                                    bot_reply_tr(message, 'Bing не смог ничего нарисовать.')
                            else:
                                images = []
                                time.sleep(random.randint(20,30))
                        else:
                            images = my_genimg.gen_images(prompt, moderation_flag, chat_id_full, conversation_history, use_bing = True)

                    # try flux if no results
                    if not images and hasattr(cfg, 'USE_FLUX_IF_EMPTY_IMAGES') and cfg.USE_FLUX_IF_EMPTY_IMAGES:
                        prompt = prompt.strip()
                        # remove trailing !
                        prompt = re.sub(r'^!+', '', prompt).strip()
                        message.text = f'/flux {prompt}'
                        image_flux_gen(message)
                        return

                    medias = []
                    has_good_images = False
                    for x in images:
                        if isinstance(x, bytes):
                            has_good_images = True
                            break
                    for i in images:
                        if isinstance(i, str):
                            if i.startswith('moderation') and not has_good_images:
                                bot_reply_tr(message, 'Ваш запрос содержит потенциально неприемлемый контент.')
                                return
                            elif 'error1_Bad images' in i and not has_good_images:
                                bot_reply_tr(message, 'Ваш запрос содержит неприемлемый контент.')
                                return
                            if not has_good_images and not i.startswith('https://'):
                                bot_reply_tr(message, i)
                                return
                        d = None
                        bot_addr = f'https://t.me/{_bot_name}'
                        caption_ = re.sub(r"(\s)\1+", r"\1\1", prompt)[:900]
                        # caption_ = prompt[:900]
                        if isinstance(i, str):
                            d = utils.download_image_as_bytes(i)
                            if len(d) < 2000: # placeholder?
                                continue
                            if GPT_FLAG:
                                caption_ = f'{bot_addr} bing.com - gpt4o\n\n' + caption_
                                my_db.add_msg(chat_id_full, 'img ' + 'bing.com_gtp4o')
                            else:
                                caption_ = f'{bot_addr} bing.com - dalle\n\n' + caption_
                                my_db.add_msg(chat_id_full, 'img ' + 'bing.com')
                        elif isinstance(i, bytes):
                            if utils.fast_hash(i) in my_genimg.WHO_AUTOR:
                                nn_ = '\n\n'
                                author = my_genimg.WHO_AUTOR[utils.fast_hash(i)]
                                caption_ = f"{bot_addr} {author}{nn_}{caption_}"
                                my_db.add_msg(chat_id_full, 'img ' + author)
                                del my_genimg.WHO_AUTOR[utils.fast_hash(i)]
                            else:
                                caption_ = f'{bot_addr} error'
                            d = i
                        if d:
                            try:
                                medias.append(telebot.types.InputMediaPhoto(d, caption = caption_[:900]))
                            except Exception as add_media_error:
                                error_traceback = traceback.format_exc()
                                my_log.log2(f'my_cmd_img:image:add_media_bytes: {add_media_error}\n\n{error_traceback}')

                    if len(medias) > 0:
                        # делим картинки на группы до 10шт в группе, телеграм не пропускает больше за 1 раз
                        chunk_size = 10
                        chunks = [medias[i:i + chunk_size] for i in range(0, len(medias), chunk_size)]

                        send_images_to_user(chunks, message, chat_id_full, medias, images)

                        if pics_group and not NSFW_FLAG:
                            send_images_to_pic_group(chunks, message, chat_id_full, prompt)

                        add_to_bots_mem(message.text, f'The bot successfully generated images on the external services <service>bing, fusion, flux, nebius, gemini</service> based on the request <prompt>{prompt}</prompt>', chat_id_full)

                    else:
                        bot_reply_tr(message, 'Could not draw anything.')

                        my_log.log_echo(message, '[image gen error] ')

                        add_to_bots_mem(message.text, 'FAIL', chat_id_full)

            else:
                COMMAND_MODE[chat_id_full] = 'image'
                bot_reply(message, help, parse_mode = 'HTML', reply_markup=get_keyboard('command_mode', message))
    except Exception as error_unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'my_cmd_img:image:send: {error_unknown}\n{traceback_error}')
