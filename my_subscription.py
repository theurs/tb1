import math
import time
import pendulum


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
