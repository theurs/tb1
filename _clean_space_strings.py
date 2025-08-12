# заменяет строки заполненные пробелами на пустые строки (надо после того как гугол в студии код написал)


import os

for file in os.listdir('.'):
    if file.endswith('.py') and os.path.isfile(file):
        with open(file, 'r', encoding='utf-8') as f:
            lines = [line if line.strip() else '\n' for line in f]
        with open(file, 'w', encoding='utf-8') as f:
            f.writelines(lines)
