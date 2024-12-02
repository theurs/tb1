#!/usr/bin/env python3
# pip install -U duckduckgo_search[lxml]
# pip install pyTelegramBotAPI


import time
from duckduckgo_search import DDGS
import telebot

import cfg
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
    bot.reply_to(message, "Привет! Я простой чат-бот. Напиши мне что-нибудь.")
    answer = '''
**IV. Types of Errors**

In hypothesis testing, there are two potential types of errors that can occur:

* **Type I Error (False Positive):**  This occurs when the null hypothesis is rejected when it is actually true. In other words, the researcher concludes there is an effect or difference when there really isn't one. The probability of making a Type I error is denoted by alpha (α), which is the significance level set for the test.
* **Type II Error (False Negative):** This occurs when the null hypothesis is not rejected when it is actually false. This means the researcher fails to detect a real effect or difference. The probability of making a Type II error is denoted by beta (β). The power of a test, denoted as (1-β), is the probability of correctly rejecting the null hypothesis when it is false—essentially, the probability of finding a real effect if one exists.

The relationship between α and β is important: decreasing α (making the test more stringent) increases β, and vice versa. The desired balance between these error rates depends on the context of the research and the consequences of each type of error.

**V. Choosing the Right Statistical Test**

Selecting the appropriate statistical test is crucial for valid hypothesis testing. The choice depends on several factors:

* **Type of Data:** Categorical (nominal, ordinal) or continuous (interval, ratio).
* **Number of Groups:** One, two, or more.
* **Research Question:** Comparing means, proportions, or examining relationships.
* **Assumptions of the Test:**  Many tests assume certain characteristics of the data, such as normality (data follows a normal distribution) and independence of observations. Violating these assumptions can lead to inaccurate results.

Commonly used tests include:

* **t-tests:** Comparing means of one or two groups.
* **Chi-square tests:** Analyzing relationships between categorical variables.
* **Analysis of Variance (ANOVA):**  Comparing means of three or more groups.
* **Correlation and Regression:**  Examining relationships between continuous variables.

Choosing the wrong test can lead to invalid conclusions, so careful consideration of these factors is essential.

**VI. Examples and Applications of Hypothesis Tests**

* **Comparing Drug Effectiveness:** A pharmaceutical company wants to test if a new drug is more effective than a standard drug. They conduct a randomized controlled trial and compare the average recovery times between the two groups using a t-test.
* **Evaluating a Marketing Campaign:** A marketing team wants to see if a new campaign increased brand awareness. They survey customers before and after the campaign and compare the proportions of customers who recognize the brand using a chi-square test.
* **Testing for Gender Bias in Hiring:** A human resources department wants to determine if there is gender bias in hiring practices. They compare the hiring rates of male and female applicants using a chi-square test.

These examples illustrate the wide applicability of hypothesis testing across different fields.

**VII. Common Misinterpretations**

* **The p-value is *not* the probability that the null hypothesis is true.**  It is the probability of observing the obtained data (or more extreme data) *if* the null hypothesis were true.
* **Statistical significance does *not* necessarily equate to practical significance.** A very small p-value might indicate a statistically significant difference, but the magnitude of the difference might be too small to be meaningful in practice.
* **Failing to reject the null hypothesis does *not* prove that the null hypothesis is true.** It simply means that there was not enough evidence to reject it based on the available data.

**VIII. Conclusion**

Hypothesis testing is a powerful tool for making inferences about populations based on sample data. By following a structured process and carefully considering the type of data, research question, and potential errors, researchers can use hypothesis testing to draw meaningful conclusions. Correct interpretation of results, avoiding common misinterpretations, is crucial for drawing accurate inferences and making informed decisions.

**IX. References**

* Include a list of reputable sources used in researching and writing the paper. Follow a consistent citation style (APA, MLA, Chicago, etc.). Examples of sources could include statistics textbooks, peer-reviewed journal articles, and credible online resources. List specific references used rather than generic examples.

This expanded response provides a more comprehensive discussion of the key aspects of hypothesis testing. Remember that using specific examples relevant to your field of study will strengthen your term paper. Always consult appropriate statistical resources for guidance and ensure that you correctly cite any sources used.
'''

    answer = utils.bot_markdown_to_html(answer)

    for chunk in utils.split_html(answer, 3800):
        bot.reply_to(message, chunk, parse_mode='HTML')


# Обработчик текстовых сообщений
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    query = message.text
    chat_id = str(message.chat.id)
    response = chat(query, chat_id)
    if response:
        answer = utils.bot_markdown_to_html(response)
        bot.reply_to(message, answer, parse_mode='MarkdownV2')


# Запуск бота
bot.polling()
