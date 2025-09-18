# Standard library imports
import re
import threading
import time
import traceback
from decimal import Decimal
from typing import Any, Callable, Dict, List, Tuple, Type

# Third-party imports
import telebot

# Local application/library specific imports
import cfg
import my_cerebras
import my_cerebras_tools
import my_cohere
import my_db
import my_github
import my_gemini3
import my_groq
import my_log
import my_mistral
import my_skills
import my_skills_general
import my_nebius
import my_openrouter
import my_openrouter_free
import my_sum
import my_subscription
import my_transcribe
import utils
import utils_llm


def trim_mem(chat_id_full: str):
    max_hist_size = my_db.get_user_property(chat_id_full, 'max_history_size')
    if max_hist_size is not None:
        chat_mode = my_db.get_user_property(chat_id_full, 'chat_mode')
        if chat_mode.startswith(('gemini', 'gemma')):
            my_gemini3.trim_user_history(chat_id_full, max_hist_size)
        else:
            my_openrouter.trim_user_history(chat_id_full, max_hist_size)


def do_task(
    message: telebot.types.Message,

    # Core objects and constants
    bot: telebot.TeleBot,
    request_counter,
    BOT_ID: int,
    _bot_name: str,

    # Global state dictionaries
    COMMAND_MODE: Dict[str, str],
    MESSAGE_QUEUE: Dict[str, str],
    CHAT_LOCKS: Dict[str, threading.Lock],
    WHO_ANSWERED: Dict[str, str],
    CHECK_DONATE_LOCKS: Dict[int, threading.Lock],
    IMG_MODE_FLAG: Dict[str, str],
    CACHE_CHECK_PHONE: Dict[str, Tuple[str, str]],
    DEBUG_MD_TO_HTML: Dict[str, str],
    GEMIMI_TEMP_DEFAULT: float,
    BOT_NAME_DEFAULT: str,

    # Helper functions and classes
    get_topic_id: Callable[[telebot.types.Message], str],
    get_lang: Callable[[str, telebot.types.Message], str],
    tr: Callable[[str, str], str],
    bot_reply: Callable,
    bot_reply_tr: Callable,
    get_keyboard: Callable,
    reset_: Callable,
    undo_cmd: Callable,
    detect_img_answer: Callable,
    edit_image_detect: Callable,
    send_all_files_from_storage: Callable,
    transcribe_file: Callable,
    proccess_image: Callable,
    process_image_stage_2: Callable,
    ShowAction,
    getcontext: Callable,

    # Command handler functions
    tts: Callable,
    trans: Callable,
    change_mode: Callable,
    change_style2: Callable,
    image_gen: Callable,
    image_bing_gen: Callable,
    image_bing_gen_gpt: Callable,
    image_flux_gen: Callable,
    image_gemini_gen: Callable,
    google: Callable,
    ask_file: Callable,
    ask_file2: Callable,
    memo_handler: Callable,
    summ_text: Callable,
    send_name: Callable,
    calc_gemini: Callable,

    custom_prompt: str = '',
):
    """default handler"""
    try:
        chat_id_full = get_topic_id(message)
    except Exception as error:
        my_log.log2(f'my_cmd_text:do_task: {error}')
        return

    try:
        message.text = my_log.restore_message_text(message.text, message.entities)
        if message.forward_date:
            full_name_forwarded_from = message.forward_from.full_name if hasattr(message.forward_from, 'full_name') else 'Noname'
            username_forwarded_from = message.forward_from.username if hasattr(message.forward_from, 'username') else 'Noname'
            message.text = f'forward sender name {full_name_forwarded_from} (@{username_forwarded_from}): {message.text}'
        message.text += '\n\n'

        from_user_id = f'[{message.from_user.id}] [0]'
        if my_db.get_user_property(from_user_id, 'blocked'):
            return

        # chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        # catch too long messages
        if chat_id_full not in MESSAGE_QUEUE:
            MESSAGE_QUEUE[chat_id_full] = message.text
            last_state = MESSAGE_QUEUE[chat_id_full]
            n = 10
            while n > 0:
                n -= 1
                time.sleep(0.1)
                new_state = MESSAGE_QUEUE[chat_id_full]
                if last_state != new_state:
                    last_state = new_state
                    n = 10
            message.text = last_state
            del MESSAGE_QUEUE[chat_id_full]
        else:
            MESSAGE_QUEUE[chat_id_full] += message.text + '\n\n'
            u_id_ = str(message.chat.id)
            if u_id_ in request_counter.counts:
                if request_counter.counts[u_id_]:
                    request_counter.counts[u_id_].pop(0)
            return

        message.text = message.text.strip()

        if custom_prompt:
            message.text = custom_prompt

        # определяем откуда пришло сообщение  
        is_private = message.chat.type == 'private'
        supch = my_db.get_user_property(chat_id_full, 'superchat') or 0
        # если бот должен отвечать всем в этом чате то пусть ведет себя как в привате
        # но если это ответ на чье-то сообщение то игнорируем
        if supch == 1:
            is_private = True

        # удаляем пробелы в конце каждой строки,
        # это когда текст скопирован из кривого терминала с кучей лишних пробелов
        message.text = "\n".join([line.rstrip() for line in message.text.split("\n")])

        msg = message.text.lower()

        # проверка на подписку
        if not my_subscription.check_donate(message, chat_id_full, lang, COMMAND_MODE, CHECK_DONATE_LOCKS, BOT_ID, tr, bot_reply, get_keyboard):
            return

        # detect /tts /t /tr /trans command
        if msg.startswith('/tts'):
            tts(message)
            return

        if msg.startswith(('/t', '/tr', '/trans')):
            trans(message)
            return

        if msg.startswith(('/style2',)):
            change_style2(message)
            return

        if msg.startswith(('/style',)):
            change_mode(message)
            return

        chat_mode_ = my_db.get_user_property(chat_id_full, 'chat_mode')


        # но даже если ключ есть всё равно больше 300 сообщений в день нельзя
        if chat_mode_ in ('gemini15', 'gemini-exp') and my_db.count_msgs_last_24h(chat_id_full) > 300:
            chat_mode_ = 'gemini25_flash'


        # обработка \image это неправильное /image
        if (msg.startswith('\\image ') and is_private):
            message.text = message.text.replace('/', '\\', 1)
            image_gen(message)
            return

        # не обрабатывать неизвестные команды, если они не в привате, в привате можно обработать их как простой текст
        chat_bot_cmd_was_used = False


        # является ли это сообщение топика, темы (особые чаты внутри чатов)
        is_topic = message.is_topic_message or (message.reply_to_message and message.reply_to_message.is_topic_message)
        # является ли это ответом на сообщение бота
        is_reply = message.reply_to_message and message.reply_to_message.from_user.id == BOT_ID

        # не отвечать если это ответ юзера другому юзеру
        try:
            _ = message.dont_check_topic
        except AttributeError:
            message.dont_check_topic = False
        if not message.dont_check_topic:
            if is_topic: # в топиках всё не так как в обычных чатах
                # если ответ не мне либо запрос ко всем(в топике он выглядит как ответ с content_type == 'forum_topic_created')
                if not (is_reply or message.reply_to_message.content_type == 'forum_topic_created'):
                    return
            else:
                # если это ответ в обычном чате но ответ не мне то выход
                if message.reply_to_message and not is_reply:
                    return

        # определяем какое имя у бота в этом чате, на какое слово он отзывается
        bot_name = my_db.get_user_property(chat_id_full, 'bot_name') or BOT_NAME_DEFAULT

        bot_name_used = False
        # убираем из запроса кодовое слово
        if msg.startswith((f'{bot_name} ', f'{bot_name},', f'{bot_name}\n')):
            bot_name_used = True
            message.text = message.text[len(f'{bot_name} '):].strip()

        bot_name2 = f'@{_bot_name}'
        # убираем из запроса имя бота в телеграме
        if msg.startswith((f'{bot_name2} ', f'{bot_name2},', f'{bot_name2}\n')):
            bot_name_used = True
            message.text = message.text[len(f'{bot_name2} '):].strip()

        message.text = message.text.strip()
        msg = message.text.lower()


        # если предварительно была введена какая то команда то этот текст надо отправить в неё
        if chat_id_full in COMMAND_MODE and not chat_bot_cmd_was_used:
            if COMMAND_MODE[chat_id_full]:
                if COMMAND_MODE[chat_id_full] == 'image':
                    if chat_id_full in IMG_MODE_FLAG and 'bing' in IMG_MODE_FLAG[chat_id_full]:
                        message.text = f'/bing {message.text}'
                    else:
                        message.text = f'/img {message.text}'
                    image_gen(message)
                if COMMAND_MODE[chat_id_full] == 'ask':
                    message.text = f'/ask {message.text}'
                    ask_file(message)
                if COMMAND_MODE[chat_id_full] == 'ask2':
                    message.text = f'/ask2 {message.text}'
                    ask_file2(message)
                if COMMAND_MODE[chat_id_full] == 'gem':
                    message.text = f'/gem {message.text}'
                    image_gemini_gen(message)
                elif COMMAND_MODE[chat_id_full] == 'tts':
                    message.text = f'/tts {message.text}'
                    tts(message)
                elif COMMAND_MODE[chat_id_full] == 'memo':
                    message.text = f'/memo {message.text}'
                    memo_handler(message)
                elif COMMAND_MODE[chat_id_full] == 'trans':
                    message.text = f'/trans {message.text}'
                    trans(message)
                elif COMMAND_MODE[chat_id_full] == 'google':
                    message.text = f'/google {message.text}'
                    google(message)
                elif COMMAND_MODE[chat_id_full] == 'name':
                    message.text = f'/name {message.text}'
                    send_name(message)
                elif COMMAND_MODE[chat_id_full] == 'sum':
                    message.text = f'/sum {message.text}'
                    summ_text(message)
                elif COMMAND_MODE[chat_id_full] == 'image_prompt':
                    image_prompt = message.text
                    process_image_stage_2(image_prompt, chat_id_full, lang, message)
                elif COMMAND_MODE[chat_id_full] == 'enter_start_amount':
                    try:
                        amount = int(message.text)
                    except ValueError:
                        amount = 0
                    if amount:
                        prices = [telebot.types.LabeledPrice(label = "XTR", amount = amount)]
                        try:
                            bot.send_invoice(
                                message.chat.id,
                                title=tr(f'Donate stars amount:', lang) + ' ' + str(amount),
                                description = tr(f'Donate stars amount:', lang) + ' ' + str(amount),
                                invoice_payload="stars_donate_payload",
                                provider_token = "",  # Для XTR этот токен может быть пустым
                                currency = "XTR",
                                prices = prices,
                                reply_markup = get_keyboard(f'pay_stars_{amount}', message)
                            )
                        except Exception as error:
                            my_log.log_donate(f'my_cmd_text:do_task: {error}\n\n{message.chat.id} {amount}')
                            bot_reply_tr(message, 'Invalid input. Please try the donation process again. Make sure the donation amount is correct. It might be too large or too small.')
                    else:
                        bot_reply_tr(message, 'Invalid input. Please try the donation process again.')
                if COMMAND_MODE[chat_id_full] != 'transcribe':
                    COMMAND_MODE[chat_id_full] = ''
                    return

        if msg == tr('забудь', lang) and (is_private or is_reply) or bot_name_used and msg==tr('забудь', lang):
            reset_(message)
            return

        if hasattr(cfg, 'PHONE_CATCHER') and cfg.PHONE_CATCHER:
            # если это номер телефона
            # удалить из текста все символы кроме цифр
            if len(msg) < 18 and len(msg) > 9  and not re.search(r"[^0-9+\-()\s]", msg):
                number = re.sub(r'[^0-9]', '', msg)
                if number:
                    if number.startswith(('7', '8')):
                        number = number[1:]
                    if len(number) == 10:
                        if number in CACHE_CHECK_PHONE:
                            response = CACHE_CHECK_PHONE[number][0]
                            text__ = CACHE_CHECK_PHONE[number][1]
                            my_db.set_user_property(chat_id_full, 'saved_file_name', f'User googled phone number: {message.text}.txt')
                            my_db.set_user_property(chat_id_full, 'saved_file', text__)
                        else:
                            with ShowAction(message, 'typing'):
                                response, text__ = my_groq.check_phone_number(number)
                                my_db.add_msg(chat_id_full, my_groq.DEFAULT_MODEL)
                        if response:
                            my_db.set_user_property(chat_id_full, 'saved_file_name', f'User googled phone number: {message.text}.txt')
                            my_db.set_user_property(chat_id_full, 'saved_file', text__)
                            CACHE_CHECK_PHONE[number] = (response, text__)
                            response = utils.bot_markdown_to_html(response)
                            bot_reply(message, response, parse_mode='HTML', not_log=True)
                            my_log.log_echo(message, '[gemini] ' + response)
                            return

        # если в сообщении только ссылка и она отправлена боту в приват
        # тогда сумморизируем текст из неё
        if my_sum.is_valid_url(message.text) and (is_private or bot_name_used):
            if utils.is_image_link(message.text):
                    proccess_image(chat_id_full, utils.download_image_as_bytes(message.text), message)
                    return
            else:
                if chat_id_full in COMMAND_MODE and COMMAND_MODE[chat_id_full] == 'transcribe':
                    transcribe_file(message.text, utils.get_filename_from_url(message.text), message)
                else:
                    message.text = '/sum ' + message.text
                    summ_text(message)
                return
        # if chat_id_full in COMMAND_MODE and COMMAND_MODE[chat_id_full] == 'transcribe':
        #     COMMAND_MODE[chat_id_full] = ''
        #     return


        # сбрасываем режим команды
        COMMAND_MODE[chat_id_full] = ''


        # проверяем не начинается ли на вопросик и если да и в памяти есть файл то перенаправляем в команду /ask
        if msg.startswith('?') and my_db.get_user_property(chat_id_full, 'saved_file_name') and msg != '?':
            message.text = '/ask ' + message.text[1:]
            ask_file(message)
            return


        # # проверяем просят ли нарисовать что-нибудь
        # translated_draw = tr('нарисуй', lang)
        # pattern = r"^(" + translated_draw + r"|нарисуй|нарисуйте|draw)[ ,.\n]+"
        # if re.match(pattern, message.text, re.IGNORECASE):
        #     prompt = re.sub(pattern, "", message.text, flags=re.IGNORECASE).strip()
        #     if prompt:
        #         message.text = f"/image {prompt}"
        #         image_gen(message)
        #         return
        #     else:
        #         pass # считать что не сработало


        # можно перенаправить запрос к гуглу, но он долго отвечает
        # не локализуем
        if re.match(r"^(гугл|google)[ ,.\n]+", message.text, re.IGNORECASE):
            query = re.sub(r"^(гугл|google)[ ,.\n]+", "", message.text, flags=re.IGNORECASE).strip()
            if query:
                message.text = f"/google {query}"
                google(message)
                return


        # так же надо реагировать если это ответ в чате на наше сообщение или диалог происходит в привате
        elif is_reply or is_private or bot_name_used or chat_bot_cmd_was_used or (hasattr(message, 'next_button_pressed') and message.next_button_pressed):
            if len(msg) > cfg.max_message_from_user:
                my_db.set_user_property(chat_id_full, 'saved_file_name', 'big_request_auto_saved_to_file.txt')
                my_db.set_user_property(chat_id_full, 'saved_file', message.text)
                bot_reply(message, f'{tr("Слишком длинное сообщение для чат-бота было автоматически сохранено как файл, используйте команду /ask  что бы задавать вопросы по этому тексту:", lang)} {len(msg)} {tr("из", lang)} {cfg.max_message_from_user}')
                return

            if my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                action = 'record_audio'
                message.text = f'[{tr("голосовое сообщение, возможны ошибки распознавания речи, отвечай просто без форматирования текста - ответ будет зачитан вслух", lang)}]: ' + message.text
            else:
                action = 'typing'


            # formatted_date = utils.get_full_time()
            user_role = my_db.get_user_property(chat_id_full, 'role') or ''
            hidden_text = f'{my_db.get_user_property(chat_id_full, "role") or ""}'

            memos = my_db.blob_to_obj(my_db.get_user_property(chat_id_full, 'memos')) or []
            if memos:
                hidden_text += '\n\nUser asked you to keep in mind this memos: '
                hidden_text += '\n'.join(memos)


            # for DDG who dont support system_prompt
            helped_query = f'{hidden_text} {message.text}'
            helped_query = helped_query.strip()

            if chat_id_full not in CHAT_LOCKS:
                CHAT_LOCKS[chat_id_full] = threading.Lock()
            with CHAT_LOCKS[chat_id_full]:
                gmodel = 'unknown'
                if chat_mode_ == 'gemini':
                    gmodel = cfg.gemini_flash_model
                if chat_mode_ == 'gemini25_flash':
                    gmodel = cfg.gemini25_flash_model
                elif chat_mode_ == 'gemini15':
                    gmodel = cfg.gemini_pro_model
                elif chat_mode_ == 'gemini-lite':
                    gmodel = cfg.gemini_flash_light_model
                elif chat_mode_ == 'gemini-exp':
                    gmodel = cfg.gemini_exp_model
                elif chat_mode_ == 'gemini-learn':
                    gmodel = cfg.gemini_learn_model
                elif chat_mode_ == 'gemma3_27b':
                    gmodel = cfg.gemma3_27b_model

                WHO_ANSWERED[chat_id_full] = chat_mode_

                if chat_mode_.startswith(('gemini', 'gemma')):
                    WHO_ANSWERED[chat_id_full] = gmodel
                time_to_answer_start = time.time()


                def command_in_answer(answer: str, message: telebot.types.Message) -> bool:
                    try:
                        answer = utils.html.unescape(answer)
                    except Exception as error:
                        my_log.log2(f'my_cmd_text:command_in_answer: {error}\n{answer}')

                    if answer.startswith('```'):
                        answer = answer[3:]
                    if answer.startswith(('/img ', '/image ', '/image: ', '/bing ', '/gpt', '/flux ', '/gem ', '/tts ', '/google ', '/trans ', '/sum ', '/reset', '/calc ', '/ask ')):
                        cmd = answer.split(maxsplit=1)[0]
                        message.text = answer
                        if cmd == '/img' or cmd == '/image':
                            image_gen(message)
                        elif cmd == '/bing':
                            image_bing_gen(message)
                        elif cmd == '/gpt':
                            image_bing_gen_gpt(message)
                        elif cmd == '/flux':
                            image_flux_gen(message)
                        elif cmd == '/gem':
                            image_gemini_gen(message)
                        elif cmd == '/ask':
                            ask_file(message)
                        elif cmd == '/tts':
                            message.text = utils.html_to_markdown(answer)
                            tts(message)
                        elif cmd == '/google':
                            google(message)
                        elif cmd == '/trans':
                            trans(message)
                        elif cmd == '/sum':
                            summ_text(message)
                        elif cmd == '/reset':
                            reset_(message)
                        elif cmd == '/calc':
                            message.text = f'{answer} {tr("Answer in my language please", lang)}, [language = {lang}].'
                            calc_gemini(message)
                        return True

                    if answer.startswith(('{"was_translated": "true"', '{&quot;was_translated&quot;: &quot;true&quot;,')):
                        message.text = f'/img {message.text}'
                        image_gen(message)
                        return True

                    return False

                if not my_db.get_user_property(chat_id_full, 'temperature'):
                    my_db.set_user_property(chat_id_full, 'temperature', GEMIMI_TEMP_DEFAULT)


                # обрезать историю
                trim_mem(chat_id_full)


                answer = ''

                telegram_user_name = ''
                is_not_bot = message.from_user.username and not message.from_user.username.lower().endswith('bot')
                has_any_name_info = (message.from_user.first_name or
                     message.from_user.last_name or
                     (message.from_user.username and len(message.from_user.username) > 1))
                if is_not_bot and has_any_name_info:
                    telegram_user_name = (f'First name: {message.from_user.first_name} '
                                        f'Last name: {message.from_user.last_name} '
                                        f'Username: {message.from_user.username}')

                # если активирован режим общения с Gemini
                if chat_mode_.startswith(('gemini', 'gemma')):
                    if len(msg) > my_gemini3.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для Gemini, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_gemini3.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            temp = my_db.get_user_property(chat_id_full, 'temperature') or 1

                            # чувакам из этого списка флудеров не давать доступа к редкой модели
                            if hasattr(cfg, 'BLOCK_SYSTEM_MSGS') and cfg.BLOCK_SYSTEM_MSGS:
                                if message.from_user.id in cfg.BLOCK_SYSTEM_MSGS:
                                    gmodel = cfg.gemini_flash_light_model

                            # у флеш 2.5 лайт мысли отключены по умолчанию, их надо вручную включать
                            THINKING_BUDGET = -1
                            if gmodel == cfg.gemini_flash_light_model:
                                THINKING_BUDGET = 20000

                            answer = my_gemini3.chat(
                                message.text,
                                chat_id_full,
                                temp,
                                model = gmodel,
                                system = hidden_text,
                                use_skills=True,
                                telegram_user_name=telegram_user_name,
                                THINKING_BUDGET = THINKING_BUDGET
                            )

                            if not answer:
                                if gmodel == cfg.gemini_pro_model:
                                    gmodel = cfg.gemini_pro_model_fallback
                                elif gmodel == cfg.gemini_flash_model:
                                    gmodel = cfg.gemini_flash_model_fallback
                                elif gmodel == cfg.gemini25_flash_model:
                                    gmodel = cfg.gemini25_flash_model_fallback
                                elif cfg.gemini_flash_light_model == gmodel:
                                    gmodel = cfg.gemini_flash_light_model_fallback
                                elif gmodel == cfg.gemini_learn_model:
                                    gmodel = cfg.gemini_learn_model_fallback
                                elif gmodel == cfg.gemini_exp_model:
                                    gmodel = cfg.gemini_exp_model_fallback
                                elif gmodel == cfg.gemma3_27b_model:
                                    gmodel = cfg.gemma3_27b_model_fallback

                                answer = my_gemini3.chat(
                                    message.text,
                                    chat_id_full,
                                    temp,
                                    model = gmodel,
                                    system = hidden_text,
                                    telegram_user_name=telegram_user_name,
                                    use_skills=True
                                )
                                WHO_ANSWERED[chat_id_full] = gmodel


                            # если обычное джемини не ответили (перегруз?) то попробовать лайв версию
                            # if not answer:
                            #     gmodel = cfg.gemini_flash_live_model
                            #     answer = my_gemini3.chat(
                            #         message.text,
                            #         chat_id_full,
                            #         temp,
                            #         model = gmodel,
                            #         system = hidden_text,
                            #         telegram_user_name=telegram_user_name,
                            #         use_skills=True
                            #     )
                            #     WHO_ANSWERED[chat_id_full] = gmodel


                            # если ответ длинный и в нем очень много повторений то вероятно это зависший ответ
                            # передаем эстафету следующему претенденту (ламе)
                            if len(answer) > 2000 and my_transcribe.detect_repetitiveness_with_tail(answer):
                                answer = ''


                            if chat_id_full not in WHO_ANSWERED:
                                WHO_ANSWERED[chat_id_full] = gmodel
                            complete_time = time.time() - time_to_answer_start
                            my_log.log3(chat_id_full, complete_time)
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(complete_time)}👇'


                            if edit_image_detect(answer, lang, chat_id_full, message, hidden_text, gemini_mem = True):
                                return


                            flag_gpt_help = False
                            if not answer:
                                mem__ = my_gemini3.get_mem_for_llama(chat_id_full, lines_amount = 10, model = gmodel)

                                answer = my_mistral.ai(
                                    message.text,
                                    mem = mem__,
                                    user_id=chat_id_full,
                                    system=hidden_text,
                                    temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                    model = my_mistral.MEDIUM_MODEL, # большая модель постояно перегружена
                                )

                                cohere_used = False
                                if not answer:
                                    answer = my_cohere.ai(
                                        message.text,
                                        mem_ = mem__,
                                        user_id=chat_id_full,
                                        system=hidden_text,
                                        temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1)
                                    cohere_used = True

                                flag_gpt_help = True
                                if not answer:
                                    answer = 'Gemini ' + tr('did not answered, try to /reset and start again', lang)

                                my_gemini3.update_mem(message.text, answer, chat_id_full, model = my_db.get_user_property(chat_id_full, 'chat_mode'))

                            if detect_img_answer(message, answer):
                                return

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            if flag_gpt_help:
                                help_model = 'cohere' if cohere_used else 'mistral'
                                complete_time = time.time() - time_to_answer_start
                                my_log.log3(chat_id_full, complete_time)
                                WHO_ANSWERED[chat_id_full] = f'👇{gmodel} + {help_model} {utils.seconds_to_str(complete_time)}👇'
                                my_log.log_echo(message, f'[{gmodel} + {help_model}] {answer}')
                            else:
                                my_log.log_echo(message, f'[{gmodel}] {answer}')


                            # отправляем файлы если они были сгенерированы в скилах
                            send_all_files_from_storage(message, chat_id_full)


                            try:
                                if command_in_answer(answer, message):
                                    return
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'my_cmd_text:do_task: {error}')
                                my_log.log2(f'my_cmd_text:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'my_cmd_text:do_task:{gmodel} {error3}\n{error_traceback}')


                # если активирован режим общения с openrouter
                elif chat_mode_ == 'openrouter':
                    with ShowAction(message, action):
                        try:
                            tool_use_level: str = my_db.get_user_property(chat_id_full, 'tool_use_level') or 'off'
                            if tool_use_level == 'off':
                                TOOLS = AVAILABLE_TOOLS = None
                            elif tool_use_level == 'min':
                                TOOLS, AVAILABLE_TOOLS = my_cerebras_tools.get_tools(*my_cerebras.funcs_min)
                            elif tool_use_level == 'medium':
                                TOOLS, AVAILABLE_TOOLS = my_cerebras_tools.get_tools(*my_cerebras.funcs_medium)
                            elif tool_use_level == 'max':
                                TOOLS, AVAILABLE_TOOLS = my_cerebras_tools.get_tools(*my_cerebras.funcs)

                            timeout_ = my_db.get_user_property(chat_id_full, 'openrouter_timeout') or my_openrouter.DEFAULT_TIMEOUT
                            answer = my_openrouter.chat(
                                message.text,
                                chat_id_full,
                                system=hidden_text,
                                timeout = timeout_,
                                tools=TOOLS,
                                available_tools=AVAILABLE_TOOLS
                            )


                            if answer:
                                def float_to_string(num):
                                    # This helper function ensures price is formatted cleanly.
                                    getcontext().prec = 8  # Set precision
                                    num = Decimal(str(num))  # Convert to Decimal
                                    num = num.quantize(Decimal('1e-7')) # Round to 7 decimal places
                                    return str(num).rstrip('0').rstrip('.') # Remove trailing zeros and dot

                                if chat_id_full in my_openrouter.PRICE:
                                    price_in = my_db.get_user_property(chat_id_full, 'openrouter_in_price')
                                    price_out = my_db.get_user_property(chat_id_full, 'openrouter_out_price')
                                    if price_in or price_out:
                                        # Convert stored prices (integers) to per-token cost.
                                        price_in = Decimal(str(price_in)) / 1000000
                                        price_out = Decimal(str(price_out)) / 1000000

                                        # Get token counts from the latest API call.
                                        t_in = my_openrouter.PRICE[chat_id_full][0]
                                        t_out = my_openrouter.PRICE[chat_id_full][1]

                                        # Calculate cost for this specific request.
                                        p_in = t_in * price_in
                                        p_out = t_out * price_out
                                        total_cost = p_in + p_out

                                        currency = my_db.get_user_property(chat_id_full, 'openrouter_currency') or '$'

                                        # --- PATCHED LINE ---
                                        # This is the new, clean format for displaying cost.
                                        s = f'\n\n`💰 In: {t_in}, Out: {t_out} | Total: {float_to_string(total_cost)} {currency}`'

                                        answer += s
                                    del my_openrouter.PRICE[chat_id_full]

                            WHO_ANSWERED[chat_id_full] = 'openrouter ' + my_openrouter.PARAMS[chat_id_full][0]
                            complete_time = time.time() - time_to_answer_start
                            my_log.log3(chat_id_full, complete_time)
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(complete_time)}👇'

                            thoughts, answer = utils_llm.split_thoughts(answer)
                            thoughts = utils.bot_markdown_to_html(thoughts)

                            if detect_img_answer(message, answer):
                                return

                            if edit_image_detect(answer, lang, chat_id_full, message, hidden_text):
                                return

                            # отправляем файлы если они были сгенерированы в скилах
                            send_all_files_from_storage(message, chat_id_full)


                            if not answer:
                                answer = 'Openrouter ' + tr('did not answered, try to /reset and start again. Check your balance or /help2', lang)

                            if answer.startswith('The bot successfully generated images on the external services'):
                                undo_cmd(message, show_message=False)
                                message.text = f'/img {message.text}'
                                image_gen(message)
                                return

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            my_log.log_echo(message, f'[openrouter {my_openrouter.PARAMS[chat_id_full][0]}] {answer}')
                            try:
                                if command_in_answer(answer, message):
                                    return
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'my_cmd_text:do_task: {error}')
                                my_log.log2(f'my_cmd_text:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'my_cmd_text:do_task:openrouter {error3}\n{error_traceback}')


                # если активирован режим общения с Mistral Large
                elif chat_mode_ == 'mistral':
                    if len(msg) > my_mistral.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для Mistral Large, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_mistral.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            TOOLS, AVAILABLE_TOOLS = my_cerebras_tools.get_tools(*my_cerebras.funcs)
                            answer = my_mistral.chat(
                                message.text,
                                chat_id_full,
                                temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                system=hidden_text,
                                model = my_mistral.DEFAULT_MODEL,
                                tools=TOOLS,
                                available_tools=AVAILABLE_TOOLS                                
                            )

                            WHO_ANSWERED[chat_id_full] = my_mistral.DEFAULT_MODEL
                            autor = WHO_ANSWERED[chat_id_full]
                            complete_time = time.time() - time_to_answer_start
                            my_log.log3(chat_id_full, complete_time)
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(complete_time)}👇'


                            if edit_image_detect(answer, lang, chat_id_full, message, hidden_text):
                                return


                            # отправляем файлы если они были сгенерированы в скилах
                            send_all_files_from_storage(message, chat_id_full)

                            if detect_img_answer(message, answer):
                                return

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            answer = answer.strip()
                            if not answer:
                                answer = f'{autor} ' + tr('did not answered, try to /reset and start again.', lang)

                            my_log.log_echo(message, f'[{autor}] {answer}')

                            try:
                                if command_in_answer(answer, message):
                                    return
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'my_cmd_text:do_task: {error}')
                                my_log.log2(f'my_cmd_text:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'my_cmd_text:do_task:mistral {error3}\n{error_traceback}')


                # если активирован режим общения с Magistral Medium
                elif chat_mode_ == 'magistral':
                    if len(msg) > my_mistral.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для Magistral Medium, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_mistral.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            answer = my_mistral.chat(
                                message.text,
                                chat_id_full,
                                temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                system=hidden_text,
                                model = my_mistral.MAGISTRAL_MODEL,
                            )

                            if not answer:
                                answer = my_mistral.chat(
                                    message.text,
                                    chat_id_full,
                                    temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                    system=hidden_text,
                                    model = my_mistral.MAGISTRAL_MODEL_SMALL,
                                )

                            WHO_ANSWERED[chat_id_full] = 'Magistral Medium'
                            complete_time = time.time() - time_to_answer_start
                            my_log.log3(chat_id_full, complete_time)
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(complete_time)}👇'

                            thoughts, answer = utils_llm.split_thoughts(answer)
                            thoughts = utils.bot_markdown_to_html(thoughts)

                            if detect_img_answer(message, answer):
                                return

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            answer = answer.strip()
                            if not answer:
                                answer = 'Magistral Medium ' + tr('did not answered, try to /reset and start again.', lang)

                            my_log.log_echo(message, f'[Magistral Medium] {answer}')

                            try:
                                if command_in_answer(answer, message):
                                    return
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'my_cmd_text:do_task: {error}')
                                my_log.log2(f'my_cmd_text:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'my_cmd_text:do_task:magistral {error3}\n{error_traceback}')


                # если активирован режим общения с Cloacked (free OpenRouter)
                elif chat_mode_ == 'cloacked':
                    with ShowAction(message, action):
                        try:
                            TOOLS, AVAILABLE_TOOLS = my_cerebras_tools.get_tools(*my_cerebras.funcs)

                            # Вызов обновленной функции chat из my_openrouter_free
                            answer = my_openrouter_free.chat(
                                query=message.text,
                                chat_id=chat_id_full,
                                system=hidden_text,
                                model=my_openrouter_free.CLOACKED_MODEL,
                                tools=TOOLS,
                                available_tools=AVAILABLE_TOOLS
                            )
                            WHO_ANSWERED[chat_id_full] = my_openrouter_free.CLOACKED_MODEL
                            if not answer:
                                answer = my_openrouter_free.chat(
                                    query=message.text,
                                    chat_id=chat_id_full,
                                    system=hidden_text,
                                    model=my_openrouter_free.CLOACKED_MODEL_FALLBACK,
                                    tools=TOOLS,
                                    available_tools=AVAILABLE_TOOLS
                                )
                                WHO_ANSWERED[chat_id_full] = my_openrouter_free.CLOACKED_MODEL_FALLBACK
                            if not answer:
                                answer = my_openrouter_free.chat(
                                    query=message.text,
                                    chat_id=chat_id_full,
                                    system=hidden_text,
                                    model=my_openrouter_free.CLOACKED_MODEL_FALLBACK2,
                                    tools=TOOLS,
                                    available_tools=AVAILABLE_TOOLS
                                )
                                WHO_ANSWERED[chat_id_full] = my_openrouter_free.CLOACKED_MODEL_FALLBACK2
                            if not answer:
                                answer = my_openrouter_free.chat(
                                    query=message.text,
                                    chat_id=chat_id_full,
                                    system=hidden_text,
                                    model=my_openrouter_free.CLOACKED_MODEL_FALLBACK3,
                                    tools=TOOLS,
                                    available_tools=AVAILABLE_TOOLS
                                )
                                WHO_ANSWERED[chat_id_full] = my_openrouter_free.CLOACKED_MODEL_FALLBACK3


                            autor = WHO_ANSWERED[chat_id_full]
                            complete_time = time.time() - time_to_answer_start
                            my_log.log3(chat_id_full, complete_time)
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(complete_time)}👇'

                            if edit_image_detect(answer, lang, chat_id_full, message, hidden_text):
                                return

                            # отправляем файлы если они были сгенерированы в скилах
                            send_all_files_from_storage(message, chat_id_full)

                            if detect_img_answer(message, answer):
                                return

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            answer = answer.strip()
                            if not answer:
                                answer = f'{autor} ' + tr('did not answered, try to /reset and start again.', lang)

                            my_log.log_echo(message, f'[{autor}] {answer}')

                            try:
                                if command_in_answer(answer, message):
                                    return
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'my_cmd_text:do_task: {error}')
                                my_log.log2(f'my_cmd_text:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'my_cmd_text:do_task:cloacked {error3}\n{error_traceback}')


                # если активирован режим общения с Qwen 3 235b a22b
                elif chat_mode_ == 'qwen3':
                    if len(msg) > my_cerebras.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для Qwen 3 235b a22b, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_cerebras.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            # Tools for the primary model (Qwen) and Mistral
                            TOOLS_SCHEMA, AVAILABLE_TOOLS = my_cerebras_tools.get_tools(*my_cerebras.funcs)

                            # Specific, limited toolset for Cohere (fallback)
                            funcs_cohere = [
                                my_skills.calc,
                                my_skills.search_google_fast,
                                my_skills.search_google_deep,
                                my_skills.download_text_from_url,
                                my_skills_general.save_to_txt,
                                my_skills.send_tarot_cards,
                            ]
                            TOOLS_SCHEMA_COHERE, AVAILABLE_TOOLS_COHERE = my_cerebras_tools.get_tools(*funcs_cohere)

                            answer = my_cerebras.chat(
                                message.text,
                                chat_id_full,
                                temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                system=hidden_text,
                                model = my_cerebras.MODEL_QWEN_3_235B_A22B_THINKING,
                                tools = TOOLS_SCHEMA,
                                available_tools = AVAILABLE_TOOLS
                            )
                            author = 'Qwen 3 thinking'
                            WHO_ANSWERED[chat_id_full] = author

                            if not answer:
                                answer = my_cerebras.chat(
                                    message.text,
                                    chat_id_full,
                                    temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                    system=hidden_text,
                                    model = my_cerebras.MODEL_QWEN_3_235B_A22B_INSTRUCT,
                                    tools = TOOLS_SCHEMA,
                                    available_tools = AVAILABLE_TOOLS
                                )
                                author = 'Qwen 3 instruct'
                                WHO_ANSWERED[chat_id_full] = author

                            # Fallback to Mistral
                            if not answer:
                                answer = my_mistral.chat(
                                    message.text,
                                    chat_id_full,
                                    temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                    system=hidden_text,
                                    model = my_mistral.DEFAULT_MODEL,
                                    tools=TOOLS_SCHEMA, 
                                    available_tools=AVAILABLE_TOOLS
                                )
                                author += ' -> Mistral'
                                WHO_ANSWERED[chat_id_full] = author

                            # Fallback to Cohere
                            if not answer:
                                answer = my_cohere.chat(
                                    message.text,
                                    chat_id_full,
                                    temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                    system=hidden_text,
                                    model = my_cohere.DEFAULT_MODEL,
                                    tools=TOOLS_SCHEMA_COHERE,
                                    available_tools=AVAILABLE_TOOLS_COHERE
                                )
                                author += ' -> Cohere'
                                WHO_ANSWERED[chat_id_full] = author


                            complete_time = time.time() - time_to_answer_start
                            my_log.log3(chat_id_full, complete_time)
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(complete_time)}👇'

                            thoughts, answer = utils_llm.split_thoughts(answer)
                            thoughts = utils.bot_markdown_to_html(thoughts)

                            if edit_image_detect(answer, lang, chat_id_full, message, hidden_text):
                                return

                            if detect_img_answer(message, answer):
                                return

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            answer = answer.strip()
                            if not answer:
                                answer = 'Qwen 3 235b a22b ' + tr('did not answered, try to /reset and start again.', lang)

                            my_log.log_echo(message, f'[{author}] {answer}')

                            # send files if they were generated in skills
                            send_all_files_from_storage(message, chat_id_full)

                            try:
                                if command_in_answer(answer, message):
                                    return
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                my_log.log2(f'my_cmd_text:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'my_cmd_text:do_task:qwen3 {error3}\n{error_traceback}')


                # если активирован режим общения с Qwen 3 Coder 480b
                elif chat_mode_ == 'qwen3coder':
                    if len(msg) > my_cerebras.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для Qwen 3 Coder 480b, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_cerebras.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            # Tools for the primary model (Qwen Coder) and Mistral
                            TOOLS_SCHEMA, AVAILABLE_TOOLS = my_cerebras_tools.get_tools(*my_cerebras.funcs_coder)

                            # Specific, limited toolset for Cohere (fallback)
                            funcs_cohere = [
                                my_skills.calc,
                                my_skills.search_google_fast,
                                my_skills.search_google_deep,
                                my_skills.download_text_from_url,
                                my_skills_general.save_to_txt,
                                my_skills.send_tarot_cards,
                            ]
                            TOOLS_SCHEMA_COHERE, AVAILABLE_TOOLS_COHERE = my_cerebras_tools.get_tools(*funcs_cohere)

                            answer = my_cerebras.chat(
                                message.text,
                                chat_id_full,
                                temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                system=hidden_text,
                                model = my_cerebras.MODEL_QWEN_3_CODER_480B,
                                tools = TOOLS_SCHEMA,
                                available_tools = AVAILABLE_TOOLS
                            )

                            author = 'Qwen 3 Coder 480b'
                            WHO_ANSWERED[chat_id_full] = author

                            # Fallback to Mistral
                            if not answer:
                                answer = my_mistral.chat(
                                    message.text,
                                    chat_id_full,
                                    temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                    system=hidden_text,
                                    model = my_mistral.DEFAULT_MODEL,
                                    tools=TOOLS_SCHEMA, 
                                    available_tools=AVAILABLE_TOOLS
                                )
                                author += ' -> Mistral'
                                WHO_ANSWERED[chat_id_full] = author

                            # Fallback to Cohere
                            if not answer:
                                answer = my_cohere.chat(
                                    message.text,
                                    chat_id_full,
                                    temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                    system=hidden_text,
                                    model = my_cohere.DEFAULT_MODEL,
                                    tools=TOOLS_SCHEMA_COHERE,
                                    available_tools=AVAILABLE_TOOLS_COHERE
                                )
                                author += ' -> Cohere'
                                WHO_ANSWERED[chat_id_full] = author


                            complete_time = time.time() - time_to_answer_start
                            my_log.log3(chat_id_full, complete_time)
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(complete_time)}👇'

                            thoughts, answer = utils_llm.split_thoughts(answer)
                            thoughts = utils.bot_markdown_to_html(thoughts)

                            if edit_image_detect(answer, lang, chat_id_full, message, hidden_text):
                                return

                            if detect_img_answer(message, answer):
                                return

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            answer = answer.strip()
                            if not answer:
                                answer = 'Qwen 3 Coder 480b ' + tr('did not answered, try to /reset and start again.', lang)

                            my_log.log_echo(message, f'[{author}] {answer}')

                            # send files if they were generated in skills
                            send_all_files_from_storage(message, chat_id_full)

                            try:
                                if command_in_answer(answer, message):
                                    return
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                my_log.log2(f'my_cmd_text:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'my_cmd_text:do_task:qwen3coder {error3}\n{error_traceback}')


                # если активирован режим общения с GPT OSS 120b
                elif chat_mode_ == 'gpt_oss':
                    if len(msg) > my_cerebras.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для GPT OSS 120b, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_cerebras.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            # Tools for Cerebras (main)
                            TOOLS_SCHEMA, AVAILABLE_TOOLS = my_cerebras_tools.get_tools_gpt_oss(*my_cerebras.funcs)

                            # Specific, limited toolset for Cohere (fallback)
                            funcs_cohere = [
                                my_skills.calc,
                                my_skills.search_google_fast,
                                my_skills.search_google_deep,
                                my_skills.download_text_from_url,
                                my_skills_general.save_to_txt,
                                my_skills.send_tarot_cards,
                            ]
                            TOOLS_SCHEMA_COHERE, AVAILABLE_TOOLS_COHERE = my_cerebras_tools.get_tools(*funcs_cohere)

                            answer = my_cerebras.chat(
                                message.text,
                                chat_id_full,
                                temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                system=hidden_text,
                                model = my_cerebras.MODEL_GPT_OSS_120B,
                                tools = TOOLS_SCHEMA,
                                available_tools = AVAILABLE_TOOLS
                            )

                            author = 'GPT OSS 120b'
                            WHO_ANSWERED[chat_id_full] = author

                            # fallback logic if the primary model fails
                            if not answer:
                                # Assuming Mistral can handle the full toolset or its wrapper manages it
                                answer = my_mistral.chat(
                                    message.text,
                                    chat_id_full,
                                    temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                    system=hidden_text,
                                    model = my_mistral.DEFAULT_MODEL,
                                    tools=TOOLS_SCHEMA, 
                                    available_tools=AVAILABLE_TOOLS
                                )
                                author += ' -> Mistral'
                                WHO_ANSWERED[chat_id_full] = author

                                # second fallback using Cohere's limited toolset
                                if not answer:
                                    answer = my_cohere.chat(
                                        message.text,
                                        chat_id_full,
                                        temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                        system=hidden_text,
                                        model = my_cohere.DEFAULT_MODEL,
                                        tools=TOOLS_SCHEMA_COHERE,
                                        available_tools=AVAILABLE_TOOLS_COHERE
                                    )
                                    author += ' -> Cohere'
                                    WHO_ANSWERED[chat_id_full] = author

                            complete_time = time.time() - time_to_answer_start
                            my_log.log3(chat_id_full, complete_time)
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(complete_time)}👇'

                            thoughts, answer = utils_llm.split_thoughts(answer)
                            thoughts = utils.bot_markdown_to_html(thoughts)

                            if edit_image_detect(answer, lang, chat_id_full, message, hidden_text):
                                return

                            if detect_img_answer(message, answer):
                                return

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            answer = answer.strip()
                            if not answer:
                                answer = 'GPT OSS 120b ' + tr('did not answered, try to /reset and start again.', lang)

                            my_log.log_echo(message, f'[{author}] {answer}')

                            # send files if they were generated in skills
                            send_all_files_from_storage(message, chat_id_full)

                            try:
                                if command_in_answer(answer, message):
                                    return
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                my_log.log2(f'my_cmd_text:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'my_cmd_text:do_task:gpt_oss {error3}\n{error_traceback}')


                # если активирован режим общения с Llama 4
                elif chat_mode_ == 'llama4':
                    if len(msg) > my_cerebras.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для Llama 4, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_cerebras.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            # Define toolsets for fallback models
                            TOOLS_SCHEMA, AVAILABLE_TOOLS = my_cerebras_tools.get_tools(*my_cerebras.funcs)
                            funcs_cohere = [
                                my_skills.calc,
                                my_skills.search_google_fast,
                                my_skills.search_google_deep,
                                my_skills.download_text_from_url,
                                my_skills_general.save_to_txt,
                                my_skills.send_tarot_cards,
                            ]
                            TOOLS_SCHEMA_COHERE, AVAILABLE_TOOLS_COHERE = my_cerebras_tools.get_tools(*funcs_cohere)

                            # First attempt with the primary Llama 4 model (no tools, as they might not work)
                            answer = my_cerebras.chat(
                                message.text,
                                chat_id_full,
                                temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                system=hidden_text,
                                model = my_cerebras.MODEL_LLAMA_4_MAVERICK_17B_128E_INSTRUCT
                            )
                            author = 'Llama 4'
                            WHO_ANSWERED[chat_id_full] = author

                            # Second attempt with the fallback Llama 4 model
                            if not answer:
                                answer = my_cerebras.chat(
                                    message.text,
                                    chat_id_full,
                                    temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                    system=hidden_text,
                                    model = my_cerebras.MODEL_LLAMA_4_SCOUT_17B_16E_INSTRUCT,
                                    tools = my_cerebras.TOOLS_SCHEMA,
                                    available_tools = my_cerebras.AVAILABLE_TOOLS
                                )
                                author = 'Llama 4 Scout' # Update author if this model is used
                                WHO_ANSWERED[chat_id_full] = author

                            # Fallback to Mistral if Llama fails
                            if not answer:
                                answer = my_mistral.chat(
                                    message.text,
                                    chat_id_full,
                                    temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                    system=hidden_text,
                                    model = my_mistral.DEFAULT_MODEL,
                                    tools=TOOLS_SCHEMA, 
                                    available_tools=AVAILABLE_TOOLS
                                )
                                author += ' -> Mistral'
                                WHO_ANSWERED[chat_id_full] = author

                            # Fallback to Cohere if Mistral also fails
                            if not answer:
                                answer = my_cohere.chat(
                                    message.text,
                                    chat_id_full,
                                    temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                    system=hidden_text,
                                    model = my_cohere.DEFAULT_MODEL,
                                    tools=TOOLS_SCHEMA_COHERE,
                                    available_tools=AVAILABLE_TOOLS_COHERE
                                )
                                author += ' -> Cohere'
                                WHO_ANSWERED[chat_id_full] = author

                            complete_time = time.time() - time_to_answer_start
                            my_log.log3(chat_id_full, complete_time)
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(complete_time)}👇'

                            thoughts, answer = utils_llm.split_thoughts(answer)
                            thoughts = utils.bot_markdown_to_html(thoughts)

                            if detect_img_answer(message, answer):
                                return

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            answer = answer.strip()
                            if not answer:
                                answer = 'Llama 4 ' + tr('did not answered, try to /reset and start again.', lang)

                            my_log.log_echo(message, f'[{author}] {answer}')

                            # send files if they were generated in skills
                            send_all_files_from_storage(message, chat_id_full)

                            try:
                                if command_in_answer(answer, message):
                                    return
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                my_log.log2(f'my_cmd_text:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'my_cmd_text:do_task:llama4 {error3}\n{error_traceback}')


                # если активирован режим общения с gpt-4o
                elif chat_mode_ == 'gpt-4o':
                    if len(msg) > my_github.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для GPT-4o, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_github.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            answer = my_github.chat(
                                message.text,
                                chat_id_full,
                                temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                system=hidden_text,
                                model = my_github.BIG_GPT_MODEL,
                            )
                            if not answer:
                                answer = my_github.chat(
                                    message.text,
                                    chat_id_full,
                                    temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                    system=hidden_text,
                                    model = my_github.DEFAULT_MODEL,
                                )
                                WHO_ANSWERED[chat_id_full] = 'GPT-4o-mini'
                            else:
                                WHO_ANSWERED[chat_id_full] = 'GPT-4o'

                            complete_time = time.time() - time_to_answer_start
                            my_log.log3(chat_id_full, complete_time)
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(complete_time)}👇'

                            if detect_img_answer(message, answer):
                                return

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            answer = answer.strip()
                            if not answer:
                                answer = 'GPT-4o ' + tr('did not answered, try to /reset and start again.', lang)

                            my_log.log_echo(message, f'[GPT-4o] {answer}')

                            try:
                                if command_in_answer(answer, message):
                                    return
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'my_cmd_text:do_task: {error}')
                                my_log.log2(f'my_cmd_text:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'my_cmd_text:do_task:gpt-4o {error3}\n{error_traceback}')


                # если активирован режим общения с gpt_41
                elif chat_mode_ == 'gpt_41':
                    if len(msg) > my_github.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для GPT 4.1, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_github.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            answer = my_github.chat(
                                message.text,
                                chat_id_full,
                                temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                system=hidden_text,
                                model = my_github.BIG_GPT_41_MODEL,
                            )
                            if not answer:
                                answer = my_github.chat(
                                    message.text,
                                    chat_id_full,
                                    temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                    system=hidden_text,
                                    model = my_github.DEFAULT_41_MINI_MODEL,
                                )
                                WHO_ANSWERED[chat_id_full] = 'GPT 4.1 mini'
                            else:
                                WHO_ANSWERED[chat_id_full] = 'GPT 4.1'

                            complete_time = time.time() - time_to_answer_start
                            my_log.log3(chat_id_full, complete_time)
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(complete_time)}👇'

                            if detect_img_answer(message, answer):
                                return

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            answer = answer.strip()
                            if not answer:
                                answer = 'GPT 4.1 ' + tr('did not answered, try to /reset and start again.', lang)

                            my_log.log_echo(message, f'[GPT 4.1] {answer}')

                            try:
                                if command_in_answer(answer, message):
                                    return
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'my_cmd_text:do_task: {error}')
                                my_log.log2(f'my_cmd_text:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'my_cmd_text:do_task:gpt_41 {error3}\n{error_traceback}')


                # если активирован режим общения с gpt_41_mini
                elif chat_mode_ == 'gpt_41_mini':
                    if len(msg) > my_github.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для GPT 4.1 mini, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_github.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            answer = my_github.chat(
                                message.text,
                                chat_id_full,
                                temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                system=hidden_text,
                                model = my_github.DEFAULT_41_MINI_MODEL,
                            )
                            if not answer:
                                answer = my_github.chat(
                                    message.text,
                                    chat_id_full,
                                    temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                    system=hidden_text,
                                    model = my_github.DEFAULT_MODEL,
                                )
                                WHO_ANSWERED[chat_id_full] = 'GPT 4.1 mini'
                            else:
                                WHO_ANSWERED[chat_id_full] = 'GPT 4.1 mini'

                            complete_time = time.time() - time_to_answer_start
                            my_log.log3(chat_id_full, complete_time)
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(complete_time)}👇'

                            if detect_img_answer(message, answer):
                                return

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            answer = answer.strip()
                            if not answer:
                                answer = 'GPT 4.1 mini ' + tr('did not answered, try to /reset and start again.', lang)

                            my_log.log_echo(message, f'[GPT 4.1 mini] {answer}')

                            try:
                                if command_in_answer(answer, message):
                                    return
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'my_cmd_text:do_task: {error}')
                                my_log.log2(f'my_cmd_text:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'my_cmd_text:do_task:gpt_41_mini {error3}\n{error_traceback}')


                # если активирован режим общения с DeepSeek R1
                elif chat_mode_ == 'deepseek_r1':
                    if len(msg) > my_nebius.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для DeepSeek R1, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_nebius.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            answer = my_nebius.chat(
                                message.text,
                                chat_id_full,
                                temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                system=hidden_text,
                                model = my_nebius.DEFAULT_MODEL,
                            )
                            if not answer:
                                answer = my_nebius.chat(
                                    message.text,
                                    chat_id_full,
                                    temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                    system=hidden_text,
                                    model = my_nebius.DEFAULT_MODEL_FALLBACK,
                                    max_tokens = 4000,
                                )
                                WHO_ANSWERED[chat_id_full] = 'DeepSeek R1+V3'
                            else:
                                WHO_ANSWERED[chat_id_full] = 'DeepSeek R1'

                            complete_time = time.time() - time_to_answer_start
                            my_log.log3(chat_id_full, complete_time)
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(complete_time)}👇'

                            answer = answer.strip()
                            if not answer:
                                answer = 'DeepSeek R1 ' + tr('did not answered, try to /reset and start again.', lang)

                            thoughts, answer = utils_llm.split_thoughts(answer)
                            thoughts = utils.bot_markdown_to_html(thoughts)

                            if detect_img_answer(message, answer):
                                return

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            # answer = utils_llm.reconstruct_html_answer_with_thoughts(thoughts, answer)

                            my_log.log_echo(message, f'[DeepSeek R1] {answer}')

                            try:
                                if command_in_answer(answer, message):
                                    return
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'my_cmd_text:do_task: {error}')
                                my_log.log2(f'my_cmd_text:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'my_cmd_text:do_task:deepseek_r1 {error3}\n{error_traceback}')


                # если активирован режим общения с DeepSeek V3
                elif chat_mode_ == 'deepseek_v3':
                    if len(msg) > my_nebius.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для DeepSeek V3, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_nebius.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            TOOLS_SCHEMA, AVAILABLE_TOOLS = my_cerebras_tools.get_tools(*my_cerebras.funcs)
                            answer = my_nebius.chat(
                                message.text,
                                chat_id_full,
                                temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                system=hidden_text,
                                model = my_nebius.DEFAULT_MODEL,
                                tools = TOOLS_SCHEMA,
                                available_tools = AVAILABLE_TOOLS
                            )

                            WHO_ANSWERED[chat_id_full] = 'DeepSeek V3'
                            complete_time = time.time() - time_to_answer_start
                            my_log.log3(chat_id_full, complete_time)
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(complete_time)}👇'


                            if edit_image_detect(answer, lang, chat_id_full, message, hidden_text):
                                return


                            answer = answer.strip()
                            if not answer:
                                answer = 'DeepSeek V3 ' + tr('did not answered, try to /reset and start again.', lang)

                            thoughts, answer = utils_llm.split_thoughts(answer)
                            thoughts = utils.bot_markdown_to_html(thoughts)

                            if detect_img_answer(message, answer):
                                return

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            # answer = utils_llm.reconstruct_html_answer_with_thoughts(thoughts, answer)

                            my_log.log_echo(message, f'[DeepSeek V3] {answer}')

                            # отправляем файлы если они были сгенерированы в скилах
                            send_all_files_from_storage(message, chat_id_full)

                            try:
                                if command_in_answer(answer, message):
                                    return
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                            except Exception as error:
                                print(f'my_cmd_text:do_task: {error}')
                                my_log.log2(f'my_cmd_text:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'my_cmd_text:do_task:deepseek_v3 {error3}\n{error_traceback}')


                # если активирован режим общения с Command A
                elif chat_mode_ == 'cohere':
                    if len(msg) > my_cohere.MAX_REQUEST:
                        bot_reply(message, f'{tr("Слишком длинное сообщение для Command A, можно отправить как файл:", lang)} {len(msg)} {tr("из", lang)} {my_cohere.MAX_REQUEST}')
                        return

                    with ShowAction(message, action):
                        try:
                            # ограниченный набор функций иначе тупит
                            funcs = [
                                my_skills.calc,
                                my_skills.search_google_fast,
                                my_skills.search_google_deep,
                                my_skills.download_text_from_url,
                                my_skills_general.save_to_txt,
                                # my_skills.save_html_to_image,
                                my_skills.send_tarot_cards,
                            ]
                            TOOLS_SCHEMA, AVAILABLE_TOOLS = my_cerebras_tools.get_tools(*funcs) # (*my_cerebras.funcs)
                            answer = my_cohere.chat(
                                message.text,
                                chat_id_full,
                                temperature=my_db.get_user_property(chat_id_full, 'temperature') or 1,
                                system=hidden_text,
                                model = my_cohere.DEFAULT_MODEL,
                                tools=TOOLS_SCHEMA,
                                available_tools=AVAILABLE_TOOLS
                            )

                            WHO_ANSWERED[chat_id_full] = 'Command A'
                            complete_time = time.time() - time_to_answer_start
                            my_log.log3(chat_id_full, complete_time)
                            WHO_ANSWERED[chat_id_full] = f'👇{WHO_ANSWERED[chat_id_full]} {utils.seconds_to_str(complete_time)}👇'

                            thoughts, answer = utils_llm.split_thoughts(answer)
                            thoughts = utils.bot_markdown_to_html(thoughts)

                            if edit_image_detect(answer, lang, chat_id_full, message, hidden_text):
                                return


                            if detect_img_answer(message, answer):
                                return

                            if not my_db.get_user_property(chat_id_full, 'voice_only_mode'):
                                answer_ = utils.bot_markdown_to_html(answer)
                                DEBUG_MD_TO_HTML[answer_] = answer
                                answer = answer_

                            answer = answer.strip()
                            if not answer:
                                answer = 'Command A ' + tr('did not answered, try to /reset and start again.', lang)

                            my_log.log_echo(message, f'[Command A] {answer}')

                            # отправляем файлы если они были сгенерированы в скилах
                            send_all_files_from_storage(message, chat_id_full)

                            try:
                                if command_in_answer(answer, message):
                                    return
                                bot_reply(message, answer, parse_mode='HTML', disable_web_page_preview = True,
                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)

                            except Exception as error:
                                print(f'my_cmd_text:do_task: {error}')
                                my_log.log2(f'my_cmd_text:do_task: {error}')
                                bot_reply(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                        reply_markup=get_keyboard('chat', message), not_log=True, allow_voice = True)
                        except Exception as error3:
                            error_traceback = traceback.format_exc()
                            my_log.log2(f'my_cmd_text:do_task:cohere {error3}\n{error_traceback}')


    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'my_cmd_text:do_task: {unknown}\n{traceback_error}')
    finally:
        # обрезать историю
        trim_mem(chat_id_full)
