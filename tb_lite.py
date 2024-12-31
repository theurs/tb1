#!/usr/bin/env python3


import telebot
import cfg
import utils


bot = telebot.TeleBot(cfg.token)



def restore_message_text(s1: str, l) -> str:
    """
    Функция принимает строку s1 и список l с описанием форматирования,
    и возвращает строку s0 с примененным форматированием.

    Args:
        s1: Строка, к которой нужно применить форматирование.
        l: Список словарей, описывающих форматирование.
        Каждый словарь содержит информацию о типе форматирования (type),
        начальной позиции (offset), длине (length) и языке (language,
        если применимо).

    Returns:
        Строка s0 с примененным форматированием.
    """
    s0 = ""
    last_pos = 0
    for i in sorted(l, key=lambda x: x.offset):
        # Добавляем текст до текущего форматированного блока
        s0 += s1[last_pos:i.offset]
        
        # Извлекаем форматируемый текст
        formatted_text = s1[i.offset:i.offset + i.length]

        # Применяем соответствующий формат
        if i.type == 'bold':
            s0 += f"**{formatted_text}**"
        elif i.type == 'italic':
            s0 += f"__{formatted_text}__"
        elif i.type == 'strikethrough':
            s0 += f"~~{formatted_text}~~"
        elif i.type == 'code':
            s0 += f"`{formatted_text}`"
        elif i.type == 'pre':
            if i.language:
                s0 += f"```{i.language}\n{formatted_text}\n```"
            else:
                s0 += f"```\n{formatted_text}\n```"

        # Обновляем индекс последней позиции
        last_pos = i.offset + i.length

    # Добавляем оставшийся текст после последнего форматирования
    s0 += s1[last_pos:]
    return s0


@bot.message_handler()
# @bot.message_handler(commands=['start'])
def command_code(message: telebot.types.Message):
    link = f'https://videochat.dns.army/?user_id={message.from_user.id}'
    bot.reply_to(message, link)


if __name__ == '__main__':
    bot.polling()
