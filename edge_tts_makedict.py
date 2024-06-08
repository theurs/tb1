#!/usr/bin/env python3


# создает словарь из языков которые поддерживает edge-tts. есть некоторые проблемы с длинными языками, у которых коды больше 2 символов

import subprocess


def get_voices() -> dict:
    lang = ''
    voice = ''
    gender = ''


    voices = {}


    proc = subprocess.run(['/home/ubuntu/.tb1/bin/edge-tts', '-l'], stdout=subprocess.PIPE)
    out = proc.stdout.decode('utf-8', errors='replace').strip()


    for i in [x for x in out.split('\n') if x]:
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


    return voices


if __name__ == '__main__':
    print(get_voices())
