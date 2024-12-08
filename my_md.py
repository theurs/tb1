#!/usr/bin/env python3
# pip install -U markdown2


import markdown2


def md2html(text: str) -> str:
    return markdown2.markdown(text)



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

    r = md2html(markdown_text)
    print(r)
