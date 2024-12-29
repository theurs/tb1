#!/usr/bin/env python3
# pip install -U markdown2


import telegramify_markdown
from telegramify_markdown import customize


def md2md(text: str) -> str:
    converted = telegramify_markdown.markdownify(
        text,
        max_line_length=None,  # If you want to change the max line length for links, images, set it to the desired value.
        normalize_whitespace=False,
        )
    return converted


if __name__ == '__main__':
    pass
    # Use `r` to avoid escaping the backslash.
    markdown_text = r""" 
1. **Отсутствует **`begin`** после заголовка программы:**
    `pascal
    program Program1;

    {... объявления переменных и процедур ...}

    {* Здесь должен быть begin *}

    end.  // <- Строка 24
    `

   **Решение:** Добавьте `begin` перед строкой 24 (или там, где должен начинаться основной блок кода программы).


"""

    r = md2md(markdown_text)
    print(r)
