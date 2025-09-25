# my_cmd_style.py

# Standard library imports
from typing import Callable, Dict

# Third-party imports
import telebot

# Local application/library specific imports
import cfg
import my_db
import my_init
import my_log
import utils
import utils_llm


def change_style(
    message: telebot.types.Message,
    COMMAND_MODE: Dict[str, str],
    get_topic_id: Callable[[telebot.types.Message], str],
    get_lang: Callable[[str, telebot.types.Message], str],
    tr: Callable[..., str],
    bot_reply: Callable,
) -> None:
    """
    Handles the 'style' command from the bot. Changes the prompt for the GPT model
    based on the user's input. If no argument is provided, it displays the current
    prompt and the available options for changing it.

    Parameters:
        message (telebot.types.Message): The message object received from the user.
        COMMAND_MODE (Dict[str, str]): Global command mode state.
        get_topic_id (Callable): Function to get the full chat ID.
        get_lang (Callable): Function to get the user's language.
        tr (Callable): Translation function.
        bot_reply (Callable): Bot reply function.

    Returns:
        None
    """
    try:
        chat_id_full = get_topic_id(message)
        lang = get_lang(chat_id_full, message)

        # check for blocked users in config
        if hasattr(cfg, 'BLOCK_SYSTEM_MSGS') and cfg.BLOCK_SYSTEM_MSGS:
            if any(x == message.from_user.id for x in cfg.BLOCK_SYSTEM_MSGS):
                bot_reply(message, "OK.")
                return

        COMMAND_MODE[chat_id_full] = ''

        DEFAULT_ROLES = my_init.get_default_roles(tr, lang)

        # FIX: Check for command arguments safely
        try:
            arg = message.text.split(maxsplit=1)[1].strip()
        except IndexError:
            arg = None # No argument was provided

        if arg:
            # support for callback-like arguments e.g. <1>
            if arg.startswith('<') and arg.endswith('>') and arg[1:-1].isdigit():
                arg = arg[1:-1]

            # FIX: Dynamically create the role_map based on the actual size of DEFAULT_ROLES
            # to prevent IndexError.
            role_map = {'0': ''}
            for i, role_text in enumerate(DEFAULT_ROLES):
                role_map[str(i + 1)] = role_text

            # Use .get() for safe dictionary access. If key not found, use arg as custom prompt.
            new_prompt = role_map.get(arg, arg)

            if utils_llm.detect_forbidden_prompt(new_prompt):
                # my_log is not available here, silent return
                return

            my_db.set_user_property(chat_id_full, 'role', new_prompt)

            if new_prompt:
                msg =  f'{tr("New role was set.", lang)}'
            else:
                msg =  f'{tr("Roles was reset.", lang)}'
            bot_reply(message, msg, parse_mode='HTML', disable_web_page_preview=True)
        else:
            msg = f"""{tr('Меняет роль бота, строку с указаниями что и как говорить', lang)}

`/style <0|1|2|3|4|5|6|{tr('свой текст', lang)}>`

{tr('Сброс, нет никакой роли', lang)}
`/style 0`

`/style 1`
`/style {DEFAULT_ROLES[0]}`

`/style 2`
`/style {DEFAULT_ROLES[1]}`

{tr('Режим художника', lang)}
`/style 3`
{tr('Все запросы воспринимаются как просьбы нарисовать что то', lang)}

{tr('Фокус на выполнение какой то задачи', lang)}
`/style 4`
`/style {DEFAULT_ROLES[3]}`

{tr('Неформальное общение', lang)}
`/style 5`
`/style {DEFAULT_ROLES[4]}`

    """

            msg = utils.bot_markdown_to_html(msg)
            msg += f'''

{tr("Текущий стиль", lang)}
<blockquote expandable><code>/style {utils.html.escape(my_db.get_user_property(chat_id_full, 'role') or tr('нет никакой роли', lang))}</code></blockquote>
        '''

            bot_reply(message, msg, parse_mode='HTML')
    except Exception as e:
        my_log.log2(f'my_cmd_style:change_style: {e}')

