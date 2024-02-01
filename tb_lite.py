#!/usr/bin/env python3


import telebot
import cfg
import utils


bot = telebot.TeleBot(cfg.token, skip_pending=True)


@bot.message_handler(commands=['start'])
def command_code(message: telebot.types.Message):
    t = r"""
**analogWrite()**

Функция **analogWrite()** используется для управления заполнением ШИМ сигнала на цифровых пинах Arduino. Значение заполнения ШИМ сигнала задаётся в диапазоне от 0 до 255. Чем выше значение заполнения, тем больше будет длительность импульсов ШИМ сигнала.

**Функция **analogWrite()** не позволяет напрямую изменить частоту ШИМ сигнала. Для этого необходимо изменить режим работы таймера, с которым связан пин. Это можно сделать, изменив значения регистров таймера.**

**Пример изменения частоты ШИМ сигнала на пине 9 Arduino Uno:**

```c++
void setup() {
  // Изменяем режим работы таймера 1
  TCCR1B = TCCR1B & 0b11111000 | 0x03;
}

void loop() {
  // Устанавливаем заполнение ШИМ сигнала
  analogWrite(9, 127);
}
```

Этот код изменит режим работы таймера 1 на режим Fast PWM. Частота ШИМ сигнала на пине 9 составит 62,5 кГц.
"""

    # t = utils.bot_markdown_to_html(t)
    # for x in utils.split_html(t, 4000):
    #     print(x)
    #     bot.reply_to(message, x, parse_mode = 'HTML')

    # bot.reply_to(message, t, parse_mode = 'HTML')
    tt = utils.bot_markdown_to_html(t)
    print(len(tt))
    print(tt)
    for ttt in utils.split_html(tt):
      bot.reply_to(message, ttt, parse_mode = 'HTML')


if __name__ == '__main__':
    bot.polling()
