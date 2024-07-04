## Что сделать

Requires fastapi, uvicorn, and latest version of starlette.

## Баги

функция для преобразования маркдауна в хтмл работает некорректно в некоторых случаях
   utils.bot_markdown_to_html

не понятно как детектить математические записи (латекс) в ответах ботов, сейчас детектятся только те которые между $$

utils.replace_tables - есть баги, не всегда может переделать таблицу


## Как добавлять новый движок

Добавить и проверить функции в tb.py
   keyboard и callback
   add_to_bots_mem
   undo
   reset
   mem
   stats
   id
   purge

   do_task
      hidden_text (стиль)

Добавить в help и перегенерировать их.
Добавить в commands.txt и сделать /init

