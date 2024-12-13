#!/usr/bin/env python3
# pip install -U duckduckgo_search[lxml]
# pip install pyTelegramBotAPI


import glob
import time
from duckduckgo_search import DDGS
import telebot

import cfg
import my_md
import utils


# Объекты для доступа к чату {id:DDG object}
CHATS_OBJ = {}


def chat_new_connection():
    '''Connect with proxy and return object'''
    return DDGS(timeout=120)


def chat(query: str, chat_id: str, model: str = 'gpt-4o-mini') -> str:
    '''model = 'claude-3-haiku' | 'gpt-3.5' | 'llama-3-70b' | 'mixtral-8x7b' | 'gpt-4o-mini'
    '''

    if chat_id not in CHATS_OBJ:
        CHATS_OBJ[chat_id] = chat_new_connection()


    try:
        resp = CHATS_OBJ[chat_id].chat(query, model)
        return resp
    except Exception as error:
        print(f'my_ddg:chat: {error}')
        time.sleep(2)
        try:
            CHATS_OBJ[chat_id] = chat_new_connection()
            resp = CHATS_OBJ[chat_id].chat(query, model)
            return resp
        except Exception as error:
            print(f'my_ddg:chat: {error}')
            return ''


# Инициализация бота Telegram
bot = telebot.TeleBot(cfg.token)


# Обработчик команды /start
@bot.message_handler(commands=['start'])
def send_welcome(message):

    for f in glob.glob('C:/Users/user/Downloads/*.txt'):
        with open(f, 'r', encoding='utf-8') as file:
            answer = file.read()
            answer = utils.bot_markdown_to_html(answer)
            with open('C:/Users/user/Downloads/111.dat', 'w', encoding='utf-8') as f:
                f.write(answer)
            answer2 = utils.split_html(answer, 3800)
            for chunk in answer2:
                try:
                    bot.reply_to(message, chunk, parse_mode='HTML')
                except Exception as error:
                    bot.reply_to(message, str(error))
                    bot.reply_to(message, chunk)
            time.sleep(2)

#     t = r""" 
# # Title
# ## Subtitle
# ### Subsubtitle
# #### Subsubsubtitle

# \(TEST
# \\(TEST
# \\\(TEST
# \\\\(TEST
# \\\\\(TEST

# **Latex Math**
# Function Change:
#     \(\Delta y = f(x_2) - f(x_1)\) can represent the change in the value of a function.
# Average Rate of Change:
#     \(\frac{\Delta y}{\Delta x} = \frac{f(x_2) - f(x_1)}{x_2 - x_1}\) is used to denote the average rate of change of a function over the interval \([x_1, x_2]\).
# - Slope:
#    \[
#    F = G\frac{{m_1m_2}}{{r^2}}
#    \]
# - Inline: \(F = G\frac{{m_1m_2}}{{r^4}}\)

# There \frac{1}{2} not in the latex block.

# **Table**

# | Tables        | Are           | Cool  |
# | ------------- |:-------------:| -----:|
# |               | right-aligned | $1600 |
# | col 2 is      | centered      |   $12 |
# | zebra stripes | are neat      |    $1 |

# '\_', '\*', '\[', '\]', '\(', '\)', '\~', '\`', '\>', '\#', '\+', '\-', '\=', '\|', '\{', '\}', '\.', '\!'
# _ , * , [ , ] , ( , ) , ~ , ` , > , # , + , - , = , | , { , } , . , !
# We will remove the \ symbol from the original text.
# **bold text**
# *bold text*
# _italic text_
# __underline__
# ~no valid strikethrough~
# ~~strikethrough~~
# ||spoiler||
# *bold _italic bold ~~italic bold strikethrough ||italic bold strikethrough spoiler||~~ __underline italic bold___ bold*
# __underline italic bold__
# [link](https://www.google.com)
# - [ ] Uncompleted task list item
# - [x] Completed task list item
# > Quote

# >Multiline Quote In Markdown it's not possible to send multiline quote in telegram without using code block or html tag but telegramify_markdown can do it. 
# ---
# Text

# Text

# Text
# > If you quote is too long, it will be automatically set in expandable citation. 
# > This is the second line of the quote.
# > `This is the third line of the quote.`
# > This is the fourth line of the quote.
# > `This is the fifth line of the quote.`

# ```python
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");
# print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!"); print("Hello, World!");


# ```
# This is `inline code`
# 1. First ordered list item
# 2. Another item
#     - Unordered sub-list.
#     - Another item.
# 1. Actual numbers don't matter, just that it's a number
# """

#     t1=r"""рш еруку

# ## Реализовать распознавание голосовых команд пользователя с помощью библиотеки Vosk и ресурса https://speechpad.ru/.

# .  ## Для этого необходимо настроить библиотеку Vosk и подключиться к ресурсу https://speechpad.ru/. Затем необходимо создать функцию, которая будет принимать на вход аудиоданные и возвращать распознанный текст.
# [hi](https://example.com/123(123))
# [hi](https://example.com/123123)

# **Шаг 3:**
# . ### 135 выберите библиотеку Vosk

# привет  я   медвед    ва

# 1. [a(x<sub>i</sub>) = j]: Это значит, что алгоритм определил, к какому кластеру (j) относится объект (x<sub>i</sub>).

# W(j) = Σ<sub>j=1</sub><sup>k</sup> Σ<sub>i=1</sub><sup>n</sup> [d(c<sub>j</sub>, x<sub>i</sub>)]<sup>2</sup>Π[a(x<sub>i</sub>) = j] → min;

# Ну __вот и наклонный__ текст.



# 1. **Отсутствует **`begin`** после заголовка программы:**
#     `pascal
#     program Program1;

#     {... объявления переменных и процедур ...}

#     {* Здесь должен быть begin *}

#     end.  // <- Строка 24
#     `

#    **Решение:** Добавьте `begin` перед строкой 24 (или там, где должен начинаться основной блок кода программы).


# Это _наклонный _ шрифт
# Это _наклонный_ шрифт
# Это _ наклонный _ шрифт
# Это _наклонный шрифт_ да?
# Это _наклонный шрифт больше чем
# на 1 строку_ да?
# Это _наклонный шрифт_да?
# Это наклонный шрифт (_да_?

# Это *наклонный * шрифт
# Это *наклонный* шрифт
# Это * наклонный * шрифт
# Это *наклонный шрифт* да?
# Это *наклонный шрифт больше чем
# на 1 строку* да?
# Это *наклонный шрифт*да?
# Это *1* + *2* наклонный шрифт да?
# Это наклонный шрифт (*да*?

# Это _*наклонный *_ шрифт
# Это _*наклонный*_ шрифт
# Это _* наклонный *_ шрифт
# Это _*наклонный шрифт*_ да?
# Это _*наклонный шрифт больше чем
# на 1 строку*_ да?
# Это _*наклонный шрифт*_да?
# Это наклонный шрифт (_*да*_?

# Это ~~перечеркнутый~~ шрифт
# Это [||спойлер||, шрифт

# ОХ*ЕЛИ ОТ ПИ*ДАТОСТИ

#    ```python
#    plt.xticks(rotation=45, ha="right", fontsize=8)



#    ```

# Прямая, по которой пересекаются плоскости A<sub>1</sub>BC и A<sub>1</sub>AD — это прямая A<sub>1</sub>A.
# Прямая, по которой пересекаются плоскости A<sub>1</sub>BC и A<sup>1</sup>AD — это прямая A<sub>1</sub>A.

# текст
# > цитата строка *1*
# > цитата строка *2*

# > цитата строка *3*
# текст
# > цитата строка *4*



# text



# # Заголовок первого уровня
# ## Заголовок второго уровня
# ### Заголовок 3 уровня
# #### Заголовок 4 уровня

# Изображение      представляет      собой рисунок девушки     с короткими каштановыми волосами, одетой в серую толстовку с капюшоном. Она выглядит грустной или уставшей, её глаза опухшие, а взгляд опущен. В руке она держит зажжённую сигарету, от которой идёт дым.  Рисунок выполнен в мультяшном стиле, линии несколько неровные, что придаёт ему небрежный, но при этом  милый характер. В правом нижнем углу изображения есть подпись: `@PANI_STRAWBERRY`.

# Подпись на рисунке:

# `@PANI_STRAWBERRY`

# Пример запроса для генерации подобного изображения:

# ```prompt
# /img a cartoon drawing of a sad girl with short brown hair wearing a grey hoodie, holding a cigarette with smoke coming out of it. Her eyes are droopy and she looks tired. The style should be slightly messy and cute, like a quick sketch.  Include the watermark "@PANI_STRAWBERRY" in the bottom right corner.
# ```

# | Столбец 1 | Столбец 2 | Столбец 3 |
# |---|---|---|
# | данные1 | данные2 | данные3 |
# | данные4 | данные5 | данные6 |
# | данные7 | данные8 | данные9 |
# | данные10 | данные11 | данные12 |
# | данные13 | данные14 | данные15 |
# | данные16 | данные17 | данные18 |
# | данные19 | данные20 | данные21 |
# | данные22 | данные23 | данные24 |
# | данные25 | данные26 | данные27 |
# | данные28 | данные29 | данные30 |


# ```prompt
# /img A photorealistic image of a young woman with long black hair, wearing traditional samurai armor, holding a katana, in a dramatic pose. The scene is set in a Japanese garden with a traditional temple in the background. The image is in black and white and has a gritty, cinematic feel.  The lighting is dramatic and the focus is on the woman's face and the katana.  The image is full of details, including the woman's sharp eyes, the intricate patterns on her armor, and the texture of the stone of the temple.
# ```

# `(x + 1) / ((x - 1)(x + 1)) + 2(x - 1) / ((x - 1)(x + 1)) = 3 / ((x - 1)(x + 1))`


# * элемент 1
#   * вложенный элемент 1
#     - еще один вложенный
#   - вложенный элемент 2
# - элемент 2

# \begin{equation}
# \int_{-\infty}^{\infty} e^{-x^2} dx = \sqrt{\pi}
# \end{equation}

# \[ E=mc^2 \]

# \begin
# \int_{-\infty}^{\infty} e^{-x^2} dx = \sqrt{\pi}
# \end

# \begin{enumerate}
#     \item Сложение: $2 + 3 = 5$
#     \item Вычитание: $10 - 5 = 5$
#     \item Умножение: $4 \times 6 = 24$
#     \item Деление: $\frac{12}{3} = 4$
#     \item Возведение в степень: $2^3 = 8$
#     \item Квадратный корень: $\sqrt{16} = 4$
#     \item Дробь: $\frac{1}{2} + \frac{1}{4} = \frac{3}{4}$
#     \item Тригонометрия: $\sin(30^\circ) = \frac{1}{2}$
#     \item Логарифм: $\log_{10} 100 = 2$
#     \item Интеграл: $\int x^2 dx = \frac{x^3}{3} + C$
# \end{enumerate}

# $e^{i\pi} + 1 = 0$

# $$ \int_{-\infty}^{\infty} e^{-x^2} dx = \sqrt{\pi} $$

# \[ \frac{d}{dx} \sin(x) = \cos(x) \]

# \begin{equation}
# a^2 + b^2 = c^2
# \end{equation}

# $\sum_{i=1}^{n} i = \frac{n(n+1)}{2}$

# $$
# \begin{pmatrix}
# 1 & 2 \\
# 3 & 4
# \end{pmatrix}
# $$

# \[
# \begin{cases}
# x + y = 5 \\
# x - y = 1
# \end{cases}
# \]


# Semoga bermanfaat dan menginspirasi.


# **Задание 6**

# | Параметр | Кабамазепин | Этосуксимид | Вальпроевая кислота | Фенитоин |
# |---|---|---|---|---|
# | Блокада Na+ каналов | + |  | + | + |
# | Блокада Ca2+ каналов Т-типа |  | + | + |  |
# | Активация ГАМК |  |  | + | + |
# | Ингибирование CYP | 3A4 |  | 2C9 | 2C9, 2C19 |
# | Угнетение кроветворения | + |  | + | itiuy kduhfg difug kdufg kd dddddddddddddddddddddddddd |
# | Гиперплазия десен | + |  | + | + |
# | Сонливость | + | + | + | + |


# **Задание 7**

# ## Сравнительная таблица: Советская и Кубинская модели государственной службы

# | Признак | Советская модель | Кубинская модель |
# |---|---|---|
# | **Идеологическая основа** | Марксизм-ленинизм | Марксизм-ленинизм, адаптированный к кубинским условиям (идеи Фиделя Кастро, Че Гевары) |
# | **Политическая система** | Однопартийная система,  господствующая роль КПСС | Однопартийная система,  ведущая роль Коммунистической партии Кубы |
# | **Государственное устройство** | Союзная республика,  формально федеративное устройство, фактически централизованное | Унитарное государство |
# | **Экономическая система** | Централизованно-плановая экономика | Плановая экономика с элементами рыночного регулирования (после распада СССР) |
# | **Организация госслужбы** | Строгая иерархия,  централизованное управление кадрами (номенклатурная система) | Иерархическая структура,  влияние партийных органов на назначение кадров,  большая роль общественных организаций |
# | **Гражданское участие** | Ограниченное,  формальное  участие  через  общественные  организации,  контролируемые  партией |  Более активное  участие  граждан  через  местные  органы  власти  и  массовые  организации |
# | **Отношения с другими странами** |  Противостояние  с  капиталистическим  миром,  поддержка  коммунистических  и  социалистических  движений |  Длительная  экономическая  и  политическая  блокада  со  стороны  США,  тесные  связи  с  странами  Латинской  Америки  и  другими  социалистическими  государствами |
# | **Контроль и надзор** |  Развитая  система  партийного  и  государственного  контроля,  органы  безопасности |  Высокий  уровень  контроля  со  стороны  партии  и  государства |


# **Примечания:**

# Состав Антанты (Тройственное Согласие):

# | Страна        | Дата присоединения |
# |----------------|--------------------|
# | **Франция**       | 1892 (военно-политический союз с Россией), 1904 (сердечное согласие с Великобританией), 1907 (образование Тройственной Антанты) |
# | **Российская Империя** | 1892 (военно-политический союз с Францией), 1907 (образование Тройственной Антанты) |
# | **Великобритания** | 1904 (сердечное согласие с Францией), 1907 (образование Тройственной Антанты)|



# """

#     t2 = '''
# 1. **Отсутствует **`begin`** после заголовка программы:**
#     `pascal
#     program Program1;

#     {... объявления переменных и процедур ...}

#     {* Здесь должен быть begin *}

#     end.  // <- Строка 24
#     `

#    **Решение:** Добавьте `begin` перед строкой 24 (или там, где должен начинаться основной блок кода программы).


# '''

#     answer = utils.bot_markdown_to_html(t)

#     a = utils.split_html(answer, 3800)
#     for x in a:
#         print(x)
#         bot.reply_to(message, x, parse_mode='HTML')


# Обработчик текстовых сообщений
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    query = message.text
    chat_id = str(message.chat.id)
    response = chat(query, chat_id)
    if response:
        answer = utils.bot_markdown_to_html(response)
        bot.reply_to(message, answer, parse_mode='HTML')


# Запуск бота
bot.polling()
