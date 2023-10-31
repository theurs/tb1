#!/usr/bin/env python3


import telebot

import cfg


bot = telebot.TeleBot(cfg.token, skip_pending=True)


@bot.message_handler(content_types = ['photo'])
def handle_photo(message: telebot.types.Message):
    """получает несколько фотографий и склеивает в 1"""
    pass


@bot.message_handler(func=lambda message: True)
def do_task(message):
    """функция обработчик сообщений работающая в отдельном потоке"""
    text = """
Хорошо, вот программа на Rust для вычисления среднего значения:

<pre><code class = "language-rust">fn main() {
    let mut numbers = vec![1, 2, 3, 4, 5];

    // Находим сумму чисел
    let sum = numbers.iter().sum();

    // Находим количество чисел
    let count = numbers.len();

    // Вычисляем среднее значение
    let mean = sum / count;

    // Выводим среднее значение
    println!(&quot;Среднее значение: {}&quot;, mean);
}
</code></pre>

Эта программа работает следующим образом:

• Сначала мы создаем вектор чисел.
• Затем мы используем метод <code>iter()</code> для получения итератора по вектору.
• С помощью метода <code>sum()</code> мы вычисляем сумму чисел в векторе.
• С помощью метода <code>len()</code> мы получаем количество чисел в векторе.
• Наконец, мы используем оператор деления для вычисления среднего значения.

Вот пример вывода программы:

<pre><code class = "language-python">Среднее значение: 3
</code></pre>

Вот еще одна версия программы, которая использует цикл <code>for</code>:

<pre><code class = "language-rust">fn main() {
    let mut numbers = vec![1, 2, 3, 4, 5];

    let mut sum = 0;
    let mut count = 0;

    for number in numbers.iter() {
        sum += number;
        count += 1;
    }

    let mean = sum / count;

    println!(&quot;Среднее значение: {}&quot;, mean);
}
</code></pre>

Эта программа работает следующим образом:

• Сначала мы создаем вектор чисел.
• Затем мы инициализируем переменные <code>sum</code> и <code>count</code> с нулем.
• В цикле <code>for</code> мы увеличиваем <code>sum</code> на значение текущего числа и увеличиваем <code>count</code> на единицу.
• Наконец, мы используем оператор деления для вычисления среднего значения.

Вот пример вывода программы:

<pre><code class = "language-python">Среднее значение: 3
</code></pre>

Какую версию программы ты предпочитаешь?

"""

    bot.reply_to(message, text, parse_mode='HTML')


def main():
    """
    Runs the main function, which sets default commands and starts polling the bot.
    """

    bot.polling()


if __name__ == '__main__':
    main()
