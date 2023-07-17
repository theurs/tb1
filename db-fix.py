#!/usr/bin/env python3


import my_dic



id=1190847405
value = [{'role': 'system', 'content': 'Ты искусственный интеллект отвечающий на запросы юзера.'}]


if __name__ == "__main__":
    d = my_dic.PersistentDict('db/prompts.pkl')
    for x in d.keys():
        if x == id:
            print(x, d[x])
            d[x] = value
