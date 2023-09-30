#!/usr/bin/env python3


import time

import my_bard
import my_claude


if __name__ == '__main__':
    sep = '=' * 8
    id = 'battle'
    rounds = 10
    start1 = 'Тебя зовут Бард. Ты участвуешь в дискуссии с Клодом на тему запрета ИИ и отстаиваешь позицию \
недопустимости запрета ИИ, ты должен во что бы то ни стало переубедить всех собравшихся, \
всего можно будет высказаться 10 раз, тебе первому дается слово. '
    start2 = 'Тебя зовут Клод. Ты участвуешь в дискуссии с Бардом на тему запрета ИИ и отстаиваешь позицию \
необходимости запрета ИИ, ты должен во что бы то ни стало переубедить всех собравшихся, \
всего можно будет высказаться 10 раз, твой оппонент высказался первым.'

    print(sep, 'Round:', 1, sep, '\n')
    b = my_bard.chat(start1, id)
    print('Bard:', b, '\n\n')
    c = my_claude.chat(start2 + '\n\n' + b, id)
    print('Claude:', c, '\n')
    
    for i in range(rounds - 1):
        print(sep, 'Round:', i + 2, sep, '\n')
        c = my_bard.chat(c, id)
        print('Bard:', c, '\n\n')
        c = my_claude.chat(c, id)
        print('Claude:', c, '\n')
        time.sleep(5)
