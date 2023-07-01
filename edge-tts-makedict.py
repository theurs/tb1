#!/usr/bin/env python3


# создает словарь из языков которые поддерживает edge-tts. есть некоторые проблемы с длинными языками, у которых коды больше 2 символов


import pprint

lang = ''
voice = ''
gender = ''

voices = {}

# edge-tts -l >1.txt что бы получить список

for i in open('1.txt').readlines():
    i = i.strip()
    if i:
        a, b = i.split(' ')
        #print(a, b)
        if a == 'Name:':
            lang = b[:2]
            voice = b
            continue
        elif a == 'Gender:':
            if b == 'Male':
                gender = 'male'
            elif b == 'Female':
                gender = 'female'
            if lang in voices:
                voices[lang][gender] = voice
            else:
                voices[lang] = {gender:voice}



pprint.pprint(voices)