#!/usr/bin/env python3

import os
import re
import pprint


# Папка с логами чатов
log_folder = 'logs2/'

# Словарь для хранения языков программирования и их количества
languages = {}

# Регулярное выражение для поиска языков программирования
pattern = r'<pre><code class = "language-([\w-]+)'

# Ищем файлы логов чатов в папке
for filename in os.listdir(log_folder):
    if '[' in filename and ']' in filename and filename.endswith('.log'):
        # print(filename)
        # Открываем файл и читаем его содержимое
        with open(os.path.join(log_folder, filename), 'r', encoding='utf8') as file:
            content = file.read()

            # Ищем языки программирования в содержимом файла
            matches = re.findall(pattern, content)

            # Обрабатываем найденные языки
            for match in matches:
                language = match.strip().lower()
                if language in languages:
                    languages[language] += 1
                else:
                    languages[language] = 1


# Сортируем языки по количеству упоминаний в порядке убывания и преобразуем в список кортежей
sorted_languages_items = sorted(languages.items(), key=lambda item: item[1], reverse=True)

# Выводим отсортированный результат
pprint.pprint(sorted_languages_items)
