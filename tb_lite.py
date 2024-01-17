#!/usr/bin/env python3


import telebot
import cfg
import utils


bot = telebot.TeleBot(cfg.token, skip_pending=True)


@bot.message_handler(commands=['start'])
def command_code(message: telebot.types.Message):
    t = r"""Sure, here is the query without the HTML tags:

```sql
WITH RECURSIVE catalog ("@Catalog", "Parent", "Name", "Context", "Path") AS (
    SELECT c."@Catalog", c."Parent", c."Name", "Context", array[c."@Catalog"] as "Path"
    FROM "Catalog" c
    WHERE
        !temp_filter_catalogs_to_recursion
    UNION
    SELECT c2."@Catalog", c2."Parent", c2."Name", c2."Context", catalog."Path" || c2."@Catalog"
    FROM "Catalog" c2 INNER JOIN catalog ON( catalog."@Catalog"= c2."Parent")
),
-- Отбираем  константы по фильтрам значений
constant_with_filtered_values AS (
    SELECT
        DISTINCT "@Constant"
    FROM "Value" val
        INNER JOIN "Constant" con ON (val."Constant" = con."@Constant")
    WHERE
        TRUE
        {% ifnotnull date_range %}
            AND !date_range BETWEEN "PeriodStart" and "PeriodEnd"
        {% endif %}
        {% iftrue search_by_object_type %}
        AND "@Value" = ANY(
            SELECT DISTINCT "Value"
            FROM "ObjectLink" ol
                JOIN "ObjectType" ot ON (ol."ObjectType" = ot."@ObjectType")
            WHERE
                TRUE
                {% ifnotnull subdivision %}
                    AND ot."Code" = 'subdivision' AND ol."ObjectId" = ANY(!subdivision)
                {% endif %}
                {% ifnotnull employee %}
                    AND ot."Code" = 'employee' AND ol."ObjectId" = ANY(!employee)
                {% endif %}
                {% ifnotnull region %}
                    AND ot."Code" = 'region' AND ol."ObjectId" = ANY(!region)
                {% endif %}
        )
        {% endif %}
        {% ifnotnull user_type %}
            AND (
                CASE
                    WHEN con."System" THEN 'system'
                    WHEN con."System" IS FALSE AND con."ClientId" IS NULL AND val."ClientId" IS NULL THEN 'typo'
                    WHEN con."System" IS FALSE AND con."ClientId" IS NULL AND val."ClientId" IS NOT NULL THEN 'changed'
                    ELSE 'user'
                END
            ) = ANY(!user_type)
        {% endif %}
    GROUP BY "@Constant", "Catalog"
),
-- Получаем константы по фильтрам констант
filtered_constants as (
    SELECT con."@Constant", con."Catalog"
    FROM
        "Constant" con
        {% iftrue is_filter_by_value %}
            -- Соединяем с константами отфильтрованными по значениям только в случае фильтрации по значениям,
            --      иначе не покажутся константы без значений
            INNER JOIN constant_with_filtered_values cwfv ON con."@Constant" = cwfv."@Constant"
        {% endif %}
    WHERE
        TRUE
        {% ifnotnull value_type %}
            AND con."ValueType" = ANY(
                SELECT "@ValueType"
                FROM "ValueType"
                WHERE "Code" = ANY(!value_type::text[])
            )
        {% endif %}
        {% ifnotnull constant_name %}
            AND lower(con."Name") like '%'::text  lower(!constant_name)  '%'::text
        {% endif %}
),
-- Получаем каталоги по фильтрам констант
catalogs_filtered_by_constants as (
    SELECT
        fil_con."Catalog",
        catalog."Path",
        count(fil_con."@Constant") as "Count"
    FROM
        filtered_constants fil_con
            INNER JOIN catalog ON (fil_con."Catalog" = catalog."@Catalog")
    GROUP BY fil_con."Catalog", catalog."Path"
),
-- Получаем каталоги отфильтрованные по имени
catalogs_filtered_by_name as (
    SELECT
        "@Catalog" as "Catalog",
        "Path"
    FROM catalog
    {% ifnotnull catalog_name %}
    WHERE
        lower(catalog."Name") like '%'::text  lower(!catalog_name)  '%'::text
    {% endif %}
),
-- Получаем итоговую выборку каталогов по всем фильтрам
result_catalog as (
    SELECT
        cat_filter_name."Catalog",
        cat_filter_name."Path",
        COALESCE(catalogs_filtered_by_constants."Count", 0) as "Count"
    FROM
        -- Если фильтруем каталоги по имени, то cte catalogs_filtered_by_name в приоритете,
        --      т.к. должны показать все каталоги подходящие по имени
        {% ifnotnull catalog_name %}
            catalogs_filtered_by_name
        {% endif %}{% ifnull catalog_name %}
            catalogs_filtered_by_constants
        {% endif %}
        as cat_filter_name
            LEFT JOIN catalogs_filtered_by_constants on (
                cat_filter_name."Catalog" = catalogs_filtered_by_constants."Catalog"
            )
)
SELECT DISTINCT ON ("Id")
    'con_' || catalog."@Catalog" AS "Id",
    catalog."Name",
    'con_' || catalog."Parent" AS "Parent",
    CASE
        WHEN array_position(result_catalog."Path", catalog."@Catalog") < array_length(result_catalog."Path", 1)
        THEN TRUE
    END AS "Parent@",
    COALESCE(sum(result_catalog."Count") OVER (PARTITION BY path_cat_id)::int, 0) AS "Count",
    catalog."Context",
    TRUE AS "CanCreate"
FROM
    catalog
    RIGHT JOIN
    (
        -- Строим путь от найденных каталогов до корневых
        result_catalog CROSS JOIN LATERAL UNNEST(result_catalog."Path") as path_cat_id
    ) on  path_cat_id = "@Catalog"
WHERE
    !temp_filter_catalogs_to_result
    AND COALESCE(sum(result_catalog."Count") OVER (PARTITION BY path_cat_id)::int, 0) > 0
ORDER BY "Id", "Parent@"
```

I hope this is helpful!
"""

    t = utils.bot_markdown_to_html(t)
    for x in utils.split_html(t, 4000):
        print(x)
        bot.reply_to(message, x, parse_mode = 'HTML')



if __name__ == '__main__':
    bot.polling()
