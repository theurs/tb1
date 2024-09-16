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
    t = r"""
Для нахождения напряженности электрического поля в точке, находящейся на оси кольца на расстоянии h от его центра, можно воспользоваться формулой для напряженности электрического поля от кольца заряда:

\[ E = \frac{k \cdot q \cdot h}{(h^2 + R^2)^{3/2}}, \]

где:
– E - напряженность электрического поля,
– k - постоянная Кулона, \( k \approx 8,99 \times 10^9 \, Н \cdot м^2/Кл^2 \),
– q - заряд кольца,
– h - расстояние от центра кольца до точки на оси,
– R - радиус кольца.

Подставляя известные значения, получаем:

\[ E = \frac{8,99 \times 10^9 \cdot 1,5 \times 10^{-9} \cdot 0,15}{(0,15^2 + 0,2^2)^{3/2}}. \]

\[ E = \frac{1,35 \times 10^{-9}}{(0,0225 + 0,04)^{3/2}}. \]

\[ E = \frac{1,35 \times 10^{-9}}{(0,0625)^{3/2}}. \]

\[ E = \frac{1,35 \times 10^{-9}}{0,0625^{3/2}}. \]

\[ E = \frac{1,35 \times 10^{-9}}{0,0625^{3/2}}. \]

\[ E = \frac{1,35 \times 10^{-9}}{0,0625^{3/2}}. \]

\[ E ≈ 1,94 \times 10^5 \, Н/Кл. \]

Таким образом, напряженность электрического поля в указанной точке равна примерно \( 1,94 \times 10^5 \, Н/Кл \).
"""


    # tt = utils.bot_markdown_to_html(t)
    # print(len(tt))
    # print(tt)
    # for ttt in utils.split_html(tt, 3800):
    #     print(ttt)
    #     bot.reply_to(message, ttt, parse_mode = 'HTML')

    # url = 'https://youtu.be/zB7DVYSltGM?si=ldHqem6B4FfW1nEN'
    # kbd  = telebot.types.InlineKeyboardMarkup()
    # button1 = telebot.types.InlineKeyboardButton('ссылка', url=url)
    # kbd.add(button1)
    # video = telebot.types.InputMediaVideo(url)
    # bot.send_video(chat_id=message.chat.id,
    #                caption = 'caption',
    #                video = video,
    #                reply_markup = kbd)

    print(restore_message_text(message.text, message.entities))



if __name__ == '__main__':
    bot.polling()
