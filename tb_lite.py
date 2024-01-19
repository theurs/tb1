#!/usr/bin/env python3


import telebot
import cfg
import utils


bot = telebot.TeleBot(cfg.token, skip_pending=True)


@bot.message_handler(commands=['start'])
def command_code(message: telebot.types.Message):
    t = r"""<code>&amp;nbsp;</code> - это HTML-код для неразрывного пробела. Неразрывный пробел не учитывается при переносе слов, поэтому он используется для предотвращения разрыва слов в нежелательных местах.

Например, следующий код предотвращает разрыв слова &quot;неразрывный&quot; при переносе слов:

<pre><code class = "language-html">&lt;p&gt;Это неразрывный&amp;nbsp;пробел.&lt;/p&gt;
</code></pre>
Неразрывные пробелы также используются для выравнивания текста. Например, следующий код выравнивает текст в таблице по центру:

<pre><code class = "language-html">&lt;table&gt;
  &lt;tr&gt;
    &lt;td align=&quot;center&quot;&gt;Column 1&lt;/td&gt;
    &lt;td align=&quot;center&quot;&gt;Column 2&lt;/td&gt;
    &lt;td align=&quot;center&quot;&gt;Column 3&lt;/td&gt;
  &lt;/tr&gt;
&lt;/table&gt;
</code></pre>
Неразрывные пробелы также используются для создания отступов. Например, следующий код создает отступ перед первым словом в абзаце:

<pre><code class = "language-html">&lt;p&gt;&amp;nbsp;&amp;nbsp;&amp;nbsp;&amp;nbsp;This is a paragraph with an indent.&lt;/p&gt;
</code></pre>
Наконец, неразрывные пробелы используются для создания специальных символов. Например, следующий код создает символ копирайта:

<pre><code class = "language-html">&amp;copy;
</code></pre>
Это лишь несколько способов использования неразрывных пробелов в HTML. Существует множество других способов сделать это, поэтому не стесняйтесь экспериментировать, чтобы найти тот, который лучше всего подходит для ваших нужд.
"""

    # t = utils.bot_markdown_to_html(t)
    # for x in utils.split_html(t, 4000):
    #     print(x)
    #     bot.reply_to(message, x, parse_mode = 'HTML')

    bot.reply_to(message, t, parse_mode = 'HTML')


if __name__ == '__main__':
    bot.polling()
