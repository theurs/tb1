import math
import threading
import time
import traceback

import pendulum
import telebot

import cfg
import my_cerebras
import my_cohere
import my_db
import my_gemini_general
import my_groq
import my_log
import my_mistral
import my_github


def get_subscription_status_string(
    chat_id_full: str,
    lang: str,
    telegram_stars: int,
    total_msgs: int,
    last_donate_time: float,
    tr: callable,
) -> str:
    """
    Generates a string about the user's subscription status based on their stars,
    message count, and API keys.
    """
    # 1. Pre-cache all text strings with context
    texts = {
        'telegram_stars': tr('Telegram stars:', lang),
        'balance_label': tr('Звёзд на балансе:', lang),
        'sub_active': tr('Подписка активна', lang),
        'next_debit': tr('Следующее списание:', lang),
        'balance_enough_until': tr('Текущего баланса хватит до:', lang),
        'sub_expired': tr('Подписка истекла', lang),
        'last_payment': tr('Последний платёж:', lang),
        'payment_due_part1': tr('Следующий платёж в размере', lang),
        'payment_due_part2': tr('будет списан при вашем следующем обращении к боту.', lang),
        'not_enough_to_renew': tr('недостаточно для продления', lang),
        'sub_inactive_stars': tr('Подписка по звёздам неактивна', lang),
        'resume_with_stars_or_keys': tr('Для возобновления работы требуется пополнить счёт звёздами или добавьте свои API-ключи (команда /keys).', lang)
    }

    # 2. Check for keys and get parameters
    # Efficiently count non-empty API keys with a single .get() call per check
    key_checks = [
        # For Gemini, a non-empty list of keys counts as 1
        bool(my_gemini_general.USER_KEYS.get(chat_id_full)),
        bool(my_groq.USER_KEYS.get(chat_id_full)),
        bool(my_mistral.USER_KEYS.get(chat_id_full)),
        bool(my_cohere.USER_KEYS.get(chat_id_full)),
        bool(my_github.USER_KEYS.get(chat_id_full)),
        bool(my_cerebras.USER_KEYS.get(chat_id_full))
    ]
    num_keys = sum(key_checks)

    MAX_TOTAL_MESSAGES = getattr(cfg, 'MAX_TOTAL_MESSAGES', 999999)
    DONATE_PRICE = getattr(cfg, 'DONATE_PRICE', 1)

    # 3. Main logic: Show simple status for users in trial period or with 2+ keys
    if total_msgs <= MAX_TOTAL_MESSAGES or num_keys > 1:
        icon = '🌟' if telegram_stars > 0 else '⭐️'
        return f"{icon} {texts['telegram_stars']} {telegram_stars} /stars"

    SECONDS_IN_MONTH = 60 * 60 * 24 * 30
    stars_balance_str = f"🌟 {texts['balance_label']} {telegram_stars}"
    is_active = (time.time() - last_donate_time) < SECONDS_IN_MONTH if last_donate_time else False

    if is_active:
        # Scenario 2: Active subscription
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
        # Scenarios 3 and 4: Expired subscription
        if telegram_stars >= DONATE_PRICE:
            # Scenario 3: Enough stars to renew
            msg = f"{stars_balance_str}\n⚠️ {texts['sub_expired']}"
            if last_donate_time:
                try:
                    last_payment_str = pendulum.from_timestamp(last_donate_time).format('DD MMMM YYYY', locale=lang)
                except Exception:
                    last_payment_str = pendulum.from_timestamp(last_donate_time).format('DD MMMM YYYY', locale='en')
                msg += f"\n{texts['last_payment']} {last_payment_str}"

            payment_due_msg = f"{texts['payment_due_part1']} {DONATE_PRICE} 🌟 {texts['payment_due_part2']}"
            msg += f"\n{payment_due_msg}"
            return msg
        else:
            # Scenario 4: Not enough stars
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


_GLOBAL_CHECK_DONATE_LOCKS_ACCESS_LOCK = threading.Lock()
# @cache_positive_by_user_id(maxsize=1000, ttl=10*60)
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
                if my_gemini_general.USER_KEYS.get(chat_id_full):
                    have_keys += 1
                if my_groq.USER_KEYS.get(chat_id_full):
                    have_keys += 1
                if my_mistral.USER_KEYS.get(chat_id_full):
                    have_keys += 1
                if my_cohere.USER_KEYS.get(chat_id_full):
                    have_keys += 1
                if my_cerebras.USER_KEYS.get(chat_id_full):
                    have_keys += 1
                if my_github.USER_KEYS.get(chat_id_full):
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
