#!/usr/bin/env python3


import telebot
import cfg
import utils


bot = telebot.TeleBot(cfg.token, skip_pending=True)


@bot.message_handler(commands=['start'])
def command_code(message: telebot.types.Message):
    t = r"""
## Получение связанных ID в массиве PostgreSQL из таблицы "Parents"
**1. Анализ предоставленной информации:**
- Таблица: "Context"
- Дополнительная таблица: "Parents"
- Структура массива: Неизвестно (целые числа, строки или другие значения)
- Связи между ID: Неизвестно (требуется уточнение)
**2. Возможные варианты запроса:**
**Вариант 1: Связи через "ParentID":**
**Предположение:**
- В таблице "Context" есть поле "ParentID", указывающее на родительский контекст.
- В таблице "Parents" хранятся связи между контекстами (ID и список связанных ID).
**Запрос:**
```sql
WITH recursive all_parents AS (
    SELECT
        "Context"."@Context" AS "ContextID",
        "Parents"."ChildID" AS "RelatedID",
        ARRAY(COALESCE("ParentID", 0)) AS "Path"
    FROM "Context"
    INNER JOIN "Parents" ON "Parents"."ParentID" = "Context"."@Context"
    WHERE "Context"."IsDeleted" = FALSE
    UNION ALL
    SELECT
        "all_parents"."ContextID",
        "p"."ChildID",
        "all_parents"."Path" || "p"."ChildID"
    FROM all_parents
    INNER JOIN "Parents" AS "p" ON "p"."ParentID" = "all_parents"."ContextID"
)
SELECT
    "Context"."@Context",
    "Context"."Name",
    "all_parents"."RelatedID",
    "all_parents"."Path"
FROM "Context"
INNER JOIN all_parents ON "all_parents"."ContextID" = "Context"."@Context"
WHERE "Context"."IsDeleted" = FALSE;
```
**Объяснение:**
1. CTE `all_parents` рекурсивно находит все связанные ID для каждого контекста.
2. Запрос сначала выбирает ID родительского контекста и его детей.
3. Затем рекурсивно добавляет ID детей к пути, пока не будут найдены все потомки.
4. В результате получаем таблицу со всеми контекстами, их связанными ID и полным путем к ним.
**Вариант 2: Связи через другие поля:**
**Предположение:**
- Связи между ID в массиве не основаны на "ParentID".
- В таблице "Parents" могут быть другие поля, определяющие связи (например, "Group", "Category").
**Запрос:**
```sql
SELECT
    "Context"."@Context",
    "Context"."Name",
    "Parents"."ChildID" AS "RelatedID"
FROM "Context"
INNER JOIN "Parents" ON "Parents"."ParentID" = "Context"."@Context"
WHERE "Context"."IsDeleted" = FALSE
AND "Parents"."Group" = 'your_group_name' -- Укажите вашу группу
AND "Parents"."Category" = 'your_category_name' -- Укажите вашу категорию;
```
**Объяснение:**
1. Запрос выбирает контексты, их связанные ID и фильтрует их по группе и категории.
2. Вам необходимо заменить "your_group_name" и "your_category_name" на ваши значения.
**3. Дополнительные шаги:**
- **Адаптация запросов:** Вам нужно будет адаптировать эти запросы, чтобы соответствовать вашей точной структуре таблицы и типу данных массива.
- **Уточнение информации:** Пожалуйста, предоставьте больше информации о структуре массива и связях между ID, чтобы я мог 
    помочь вам с более точным запросом.
**4. Рекомендации:**
- Изучите функции PostgreSQL для работы с массивами, такие как `unnest`, `array_agg`, `array_to_string`.
- Используйте комментарии в запросе, чтобы сделать его более понятным.
**5. Поддержка:**
Если вам нужна помощь в адаптации запросов или у вас есть другие вопросы, пишите, я буду рад помочь!
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
