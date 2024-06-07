#!/usr/bin/env python3


import telebot
import cfg
import utils


bot = telebot.TeleBot(cfg.token, skip_pending=True)


@bot.message_handler(commands=['start'])
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

    # t = utils.bot_markdown_to_html(t)
    # for x in utils.split_html(t, 4000):
    #     print(x)
    #     bot.reply_to(message, x, parse_mode = 'HTML')

    # bot.reply_to(message, t, parse_mode = 'HTML')
    tt = utils.bot_markdown_to_html(t)
    print(len(tt))
    print(tt)
    for ttt in utils.split_html(tt, 3800):
        print(ttt)
        bot.reply_to(message, ttt, parse_mode = 'HTML')


if __name__ == '__main__':
    bot.polling()
