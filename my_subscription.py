import cachetools
import functools
import math
import threading
import time
import traceback

import pendulum
import telebot

import cfg
import my_cohere
import my_db
import my_gemini_general
import my_groq
import my_log
import my_mistral
import my_github


def get_subscription_status_string(chat_id_full: str, lang: str, telegram_stars: int, total_msgs: int, last_donate_time: float, cfg, my_db, tr, my_gemini_general, my_groq, my_mistral, my_cohere, my_github) -> str:
    """
    Формирует строку о статусе подписки пользователя на основе его звёзд,
    количества сообщений и наличия API-ключей.
    """
    # 1. Предварительное кэширование всех текстовых строк с контекстом
    texts = {
        'telegram_stars': tr('Telegram stars:', lang, help='Telegram Stars is a new feature that allows users to buy and spend Stars, a new digital currency, on digital goods and services within the Telegram ecosystem, like ebooks, online courses, or items in Telegram games.'),
        'balance_label': tr('Звёзд на балансе:', lang, help="A label for the user's star balance. Full example: 'Звёзд на балансе: 150'. Please translate only the label part: 'Звёзд на балансе:'"),
        'sub_active': tr('Подписка активна', lang, help="A status message indicating the user's subscription is active. Example: '✅ Подписка активна'. Please translate only the text: 'Подписка активна'"),
        'next_debit': tr('Следующее списание:', lang, help="A label for the date of the next automatic payment. Full example: 'Следующее списание: 07 августа 2025'. Please translate only the label part: 'Следующее списание:'"),
        'balance_enough_until': tr('Текущего баланса хватит до:', lang, help="A label indicating the future date until which the user's current balance will last. Full example: 'Текущего баланса хватит до: 07 сентября 2025'. Please translate only the label part: 'Текущего баланса хватит до:'"),
        'sub_expired': tr('Подписка истекла', lang, help="A status message indicating the user's subscription has expired. Example: '⚠️ Подписка истекла'. Please translate only the text: 'Подписка истекла'"),
        'last_payment': tr('Последний платёж:', lang, help="A label for the date of the user's last payment. Full example: 'Последний платёж: 08 июля 2025'. Please translate only the label part: 'Последний платёж:'"),
        'payment_due_part1': tr('Следующий платёж в размере', lang, help="This is the first part of a sentence. The full original sentence is: 'Следующий платёж в размере 50 🌟 будет списан при вашем следующем обращении к боту.' Please translate only the initial part: 'Следующий платёж в размере'"),
        'payment_due_part2': tr('будет списан при вашем следующем обращении к боту.', lang, help="This is the second part of a sentence. The full original sentence is: 'Следующий платёж в размере 50 🌟 будет списан при вашем следующем обращении к боту.' Please translate only the final part: 'будет списан при вашем следующем обращении к боту.'"),
        'not_enough_to_renew': tr('недостаточно для продления', lang, help="A short note in parentheses indicating the user's balance is too low to renew the subscription. Full example: 'Звёзд на балансе: 20 (недостаточно для продления)'. Please translate only the part in parentheses: 'недостаточно для продления'"),
        'sub_inactive_stars': tr('Подписка по звёздам неактивна', lang, help="A status message indicating the subscription that uses 'Stars' currency is not active. Example: '❌ Подписка по звёздам неактивна'. Please translate only the text: 'Подписка по звёздам неактивна'"),
        'resume_with_stars_or_keys': tr('Для возобновления работы требуется пополнить счёт звёздами или добавьте свои API-ключи (команда /keys).', lang, help="A call-to-action message for a user with an inactive subscription, explaining how to resume service. The text is a full sentence.")
    }

    # 2. Проверка наличия ключей и получение параметров
    have_keys = (
        (chat_id_full in my_gemini_general.USER_KEYS) or
        (chat_id_full in my_groq.USER_KEYS) or
        (chat_id_full in my_mistral.USER_KEYS) or
        (chat_id_full in my_cohere.USER_KEYS) or
        (chat_id_full in my_github.USER_KEYS)
    )
    #DEBUG
    # have_keys = False

    MAX_TOTAL_MESSAGES = getattr(cfg, 'MAX_TOTAL_MESSAGES', 999999)
    DONATE_PRICE = getattr(cfg, 'DONATE_PRICE', 1)

    # 3. Основная логика
    if total_msgs <= MAX_TOTAL_MESSAGES or have_keys:
        icon = '🌟' if telegram_stars > 0 else '⭐️'
        return f"{icon} {texts['telegram_stars']} {telegram_stars} /stars"

    SECONDS_IN_MONTH = 60 * 60 * 24 * 30
    stars_balance_str = f"🌟 {texts['balance_label']} {telegram_stars}"
    is_active = (time.time() - last_donate_time) < SECONDS_IN_MONTH if last_donate_time else False

    if is_active:
        # Сценарий 2: Активная подписка
        affordable_renewals = max(0, math.floor(telegram_stars / DONATE_PRICE))
        current_expiry_date = pendulum.from_timestamp(last_donate_time).add(months=1)
        final_expiry_date = current_expiry_date.add(months=affordable_renewals)

        try:
            current_expiry_date_str = current_expiry_date.format('DD MMMM YYYY', locale=lang)
            final_expiry_date_str = final_expiry_date.format('DD MMMM YYYY', locale=lang)
        except Exception:
            current_expiry_date_str = current_expiry_date.format('DD MMMM YYYY', locale='en')
            final_expiry_date_str = final_expiry_date.format('DD MMMM YYYY', locale='en')

        return (
            f"{stars_balance_str}\n"
            f"✅ {texts['sub_active']}\n"
            f"{texts['next_debit']} {current_expiry_date_str}\n"
            f"💰 {texts['balance_enough_until']} {final_expiry_date_str}"
        )
    else:
        # Сценарии 3 и 4: Подписка истекла
        if telegram_stars >= DONATE_PRICE:
            # Сценарий 3: Достаточно звёзд для продления
            msg = f"{stars_balance_str}\n⚠️ {texts['sub_expired']}"
            if last_donate_time:
                try:
                    last_payment_str = pendulum.from_timestamp(last_donate_time).format('DD MMMM YYYY', locale=lang)
                except Exception:
                    last_payment_str = pendulum.from_timestamp(last_donate_time).format('DD MMMM YYYY', locale='en')
                msg += f"\n{texts['last_payment']} {last_payment_str}"

            # <<< ИЗМЕНЕНИЕ ЗДЕСЬ: Собираем строку из переведенных частей и числа >>>
            payment_due_msg = f"{texts['payment_due_part1']} {DONATE_PRICE} 🌟 {texts['payment_due_part2']}"
            msg += f"\n{payment_due_msg}"
            return msg
        else:
            # Сценарий 4: Недостаточно звёзд
            stars_balance_str += f" ({texts['not_enough_to_renew']})"
            msg = f"{stars_balance_str}\n❌ {texts['sub_inactive_stars']}"
            if last_donate_time:
                try:
                    last_payment_str = pendulum.from_timestamp(last_donate_time).format('DD MMMM YYYY', locale=lang)
                except Exception:
                    last_payment_str = pendulum.from_timestamp(last_donate_time).format('DD MMMM YYYY', locale='en')
                msg += f"\n{texts['last_payment']} {last_payment_str}"

            msg += f"\n{texts['resume_with_stars_or_keys']}"
            return msg


def cache_positive_by_user_id(maxsize: int = 1000, ttl: int = 10*60):
    """
    Декоратор для кеширования результатов функции.
    Кеширует только положительные (True) результаты, используя chat_id_full в качестве ключа.
    """
    _cache = cachetools.TTLCache(maxsize=maxsize, ttl=ttl)
    _cache_lock = threading.Lock()

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Предполагаем, что chat_id_full всегда второй позиционный аргумент
            # или передается как именованный
            user_id = kwargs.get('chat_id_full')
            if user_id is None and len(args) > 1:
                user_id = args[1]

            if user_id is None:
                # Если user_id не найден, кеширование не применимо, просто вызываем функцию
                return func(*args, **kwargs)

            # Проверяем кеш
            with _cache_lock:
                if user_id in _cache:
                    return _cache[user_id] # Возвращаем True, так как кешируем только его

            # Вызываем оригинальную функцию
            result = func(*args, **kwargs)

            # Кешируем только если результат True
            if result is True:
                with _cache_lock:
                    _cache[user_id] = True

            return result
        return wrapper
    return decorator


_GLOBAL_CHECK_DONATE_LOCKS_ACCESS_LOCK = threading.Lock()
@cache_positive_by_user_id(maxsize=1000, ttl=10*60)
def check_donate(
    message: telebot.types.Message,
    chat_id_full: str,
    lang: str,
    COMMAND_MODE,
    CHECK_DONATE_LOCKS,
    BOT_ID,
    tr,
    bot_reply,
    get_keyboard
) -> bool:
    '''
    Если общее количество сообщений превышает лимит то надо проверить подписку
    и если не подписан то предложить подписаться.

    Если у юзера есть все ключи, и есть звезды в достаточном количестве то
    звезды надо потреблять всё равно, что бы не накапливались.
    '''
    try:
        SECONDS_IN_MONTH = 60 * 60 * 24 * 30
        # если ожидается нестандартная сумма то пропустить
        if chat_id_full in COMMAND_MODE and COMMAND_MODE[chat_id_full] == 'enter_start_amount':
            return True

        with _GLOBAL_CHECK_DONATE_LOCKS_ACCESS_LOCK:
            lock = CHECK_DONATE_LOCKS.setdefault(message.from_user.id, threading.Lock())

        with lock:
            try:
                chat_mode = my_db.get_user_property(chat_id_full, 'chat_mode')
                # если админ или это в группе происходит то пропустить или режим чата = openrouter
                if message.from_user.id in cfg.admins or chat_id_full.startswith('[-') or message.from_user.id == BOT_ID or chat_mode == 'openrouter':
                    return True

                # если за сутки было меньше 10 запросов то пропустить
                # msgs24h = my_db.count_msgs_last_24h(chat_id_full)
                # max_per_day = cfg.MAX_FREE_PER_DAY if hasattr(cfg, 'MAX_FREE_PER_DAY') else 10
                # if msgs24h <= max_per_day:
                #     return True

                # юзеры у которых есть 2 ключа не требуют подписки,
                # но если есть звезды то их надо снимать чтоб не копились
                have_keys = 0
                if chat_id_full in my_gemini_general.USER_KEYS:
                    have_keys += 1
                if chat_id_full in my_groq.USER_KEYS:
                    have_keys += 1
                if chat_id_full in my_mistral.USER_KEYS:
                    have_keys += 1
                if chat_id_full in my_cohere.USER_KEYS:
                    have_keys += 1
                if chat_id_full in my_github.USER_KEYS:
                    have_keys += 1
                have_keys = have_keys > 1

                total_messages = my_db.count_msgs_total_user(chat_id_full)
                MAX_TOTAL_MESSAGES = cfg.MAX_TOTAL_MESSAGES if hasattr(cfg, 'MAX_TOTAL_MESSAGES') else 500000
                DONATE_PRICE = cfg.DONATE_PRICE if hasattr(cfg, 'DONATE_PRICE') else 50

                if total_messages > MAX_TOTAL_MESSAGES:
                    last_donate_time = my_db.get_user_property(chat_id_full, 'last_donate_time') or 0
                    if time.time() - last_donate_time > SECONDS_IN_MONTH:
                        stars = my_db.get_user_property(chat_id_full, 'telegram_stars') or 0
                        if stars >= DONATE_PRICE:
                            my_db.set_user_property(chat_id_full, 'last_donate_time', time.time())
                            my_db.set_user_property(chat_id_full, 'telegram_stars', stars - DONATE_PRICE)
                            my_log.log_donate_consumption(f'{chat_id_full} -{DONATE_PRICE} stars')
                            # msg = tr(f'You need {DONATE_PRICE} stars for a month of free access.', lang)

                            # msg = tr('You have enough stars for a month of free access. Thank you for your support!', lang)
                            # bot_reply(message, msg, disable_web_page_preview = True, reply_markup = get_keyboard('donate_stars', message))
                        else:
                            if have_keys:
                                pass
                            else:
                                msg = tr(f'You need {DONATE_PRICE} stars for a month of free access.', lang)
                                msg += '\n\n' + tr('You have not enough stars for a month of free access.\n\nYou can get free access if bring all free keys, see /keys command for instruction.', lang)
                                bot_reply(message, msg, disable_web_page_preview = True, reply_markup = get_keyboard('donate_stars', message))
                                # my_log.log_donate_consumption_fail(f'{chat_id_full} user have not enough stars {stars}')
                                return False
            except Exception as unexpected_error:
                error_traceback = traceback.format_exc()
                my_log.log2(f'tb:check_donate: {chat_id_full}\n\n{unexpected_error}\n\n{error_traceback}')

    except Exception as unknown:
        traceback_error = traceback.format_exc()
        my_log.log2(f'tb:check_donate: {unknown}\n{traceback_error}')

    return True


def github_models(user_id: str) -> bool:
    """
    Проверяет, имеет ли пользователь рабочую подписку или ключ от гитхаба.

    1. У пользователя есть личный API-ключ от GitHub.
    или
    2. У пользователя активна оплаченная подписка (через Telegram Stars).

    Пробный период (по лимиту сообщений) не учитывается как "рабочая подписка".

    Принимает ID пользователя как строку и возвращает True, если подписка активна, иначе False.
    """
    SECONDS_IN_MONTH = 60 * 60 * 24 * 30

    # 1. Проверка на наличие GitHub API ключа
    has_github_key = (user_id in my_github.USER_KEYS)
    if has_github_key:
        return True

    # 2. Проверка на оплаченную подписку (через Telegram Stars)
    # Пробный период больше не считается "рабочей подпиской".

    last_donate_time = my_db.get_user_property(user_id, 'last_donate_time') or 0
    stars = my_db.get_user_property(user_id, 'telegram_stars') or 0
    DONATE_PRICE = getattr(cfg, 'DONATE_PRICE', 50)

    # Проверяем, активна ли подписка по времени (не истек ли месяц с последнего платежа)
    if (time.time() - last_donate_time) < SECONDS_IN_MONTH:
        return True # Подписка активна по времени

    # Если подписка истекла, проверяем, достаточно ли звезд для продления
    if stars >= DONATE_PRICE:
        # Если звезд достаточно для продления, считаем, что подписка "рабочая",
        # так как пользователь имеет возможность её продлить.
        return True
    else:
        # Нет GitHub ключа, подписка истекла и звезд недостаточно.
        return False
