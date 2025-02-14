# pip install -U mistune


from pprint import pprint


import mistune
from mistune import HTMLRenderer
from mistune.plugins.formatting import strikethrough
from mistune.plugins.table import table


class TelegramHTMLMarkdownRenderer(HTMLRenderer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.text_buffer = []
        self.table_column_widths = []
        self.current_table_rows = []
        self.is_in_table = False

    def _safe_render_text(self, text):
        escaped_text = ""
        escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in text:
            if char in escape_chars:
                escaped_text += '\\' + char
            else:
                escaped_text += char
        return escaped_text

    def text(self, children):
        return self._safe_render_text(children)

    def paragraph(self, children):
        return children + '\n'

    def blank_line(self):
        return '\n'

    def heading(self, children, level, style=None, attrs=None):
        return f'<b>{children}</b>\n'

    def emphasis(self, children):
        return '<i>' + children + '</i>'

    def strong(self, children):
        return '<b>' + children + '</b>'

    def codespan(self, children):
        return '<code>' + children + '</code>'

    def linebreak(self):
        return '\n\n'

    def link(self, link, children, title=None):
        return f'<a href="{link}">{children}</a>'

    def block_code(self, code, info=None):
        lang = info if info else ''
        if lang:
            return f'<pre language="{lang}">{code}</pre>'
        else:
            return f'<pre>{code}</pre>'

    def list(self, children, ordered=False, start=None, attrs=None):
        return children + '\n'

    def list_item(self, children, bullet=None, is_checked=None, attrs=None):
        return '• ' + children + '\n'

    def strikethrough(self, children):
        return '<s>' + children + '</s>'

    def table(self, children):
        table_str = "".join(self.current_table_rows)
        self.current_table_rows = []
        self.table_column_widths = []
        self.is_in_table = False
        return f'<code>{table_str}</code>'

    def table_body(self, children):
        for row in children:
            self._update_column_widths(row)
        return ""

    def table_head(self, children):
        for row in children:
            self._update_column_widths(row)
        return ""

    def table_row(self, children):
        row_str = ""
        for i, cell in enumerate(children):
            if i < len(self.table_column_widths):
                row_str += cell.ljust(self.table_column_widths[i]) + "  "
        self.current_table_rows.append(row_str + "\n")
        return ""

    def table_cell(self, children, align=None, head=False):
        if not self.is_in_table:
            self.is_in_table = True
            self.table_column_widths = []
            self.current_table_rows = []
        return children[0]['raw'] # Извлекаем текст из объекта

    def _update_column_widths(self, row):
        for i, cell in enumerate(row):
            cell_text = cell[0]['raw'] # Текст ячейки
            if i >= len(self.table_column_widths):
                self.table_column_widths.append(len(cell_text))
            else:
                self.table_column_widths[i] = max(self.table_column_widths[i], len(cell_text))




renderer = TelegramHTMLMarkdownRenderer()
markdown = mistune.Markdown(renderer, plugins=[strikethrough, table])
markdown2 = mistune.Markdown(renderer = None, plugins=[strikethrough, table])


text = '''
**Жирный текст:** `**жирный текст**`

_Курсивный текст:_ `*курсивный текст*`

~~Зачеркнутый текст:~~ `~~зачеркнутый текст~~`


| First Header  | Second Header |
| ------------- | ------------- |
| Content Cell  | Content Cell  |
| Content Cell  | Content Cell  |

`Моноширинный текст:` `` `моноширинный текст` ``
'''

r1=markdown(text)
r2=markdown2(text)

print(r1)
pprint(r2)
