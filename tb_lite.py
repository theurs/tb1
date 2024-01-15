#!/usr/bin/env python3


import telebot
import cfg


bot = telebot.TeleBot(cfg.token, skip_pending=True)


@bot.message_handler(commands=['start'])
def command_code(message: telebot.types.Message):
    t = """
<pre><code class = "language-erlang">[1 | [2,3] | 4 | 5].
</code></pre>
Этот код можно выполнить в консоли Erlang следующим образом:

<pre><code class = "language-erlang">1&gt; [1 | [2,3] | 4 | 5].
[[1,[2,3]],4,5]
</code></pre>
В этом примере:

• <code>[1 | [2,3] | 4 | 5]</code> создает новый список, который состоит из числа <code>1</code>, списка <code>[2,3]</code>, числа <code>4</code> и числа <code>5</code>.

Таким образом, мы построили список <code>[[1,[2,3]],4,5]</code> в консоли Erlang, используя только числовые значения и оператор <code>|</code>."""

    bot.reply_to(message, t, parse_mode='HTML')


if __name__ == '__main__':
    bot.polling()
