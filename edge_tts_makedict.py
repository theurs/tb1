#!/usr/bin/env python3


# создает словарь из языков которые поддерживает edge-tts. есть некоторые проблемы с длинными языками, у которых коды больше 2 символов

import subprocess


def get_voices() -> dict:
    lang = ''
    voice = ''
    gender = ''


    voices = {}


    proc = subprocess.run(['edge-tts', '-l'], stdout=subprocess.PIPE)
    out = proc.stdout.decode('utf-8', errors='replace').strip()

    block = {'male': '', 'female': ''}
    n = 0
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
                block[gender] = voice
                n += 1
                if n == 2:

                    if lang not in voices:
                        voices[lang] = block
                    else:
                        for x in range(2, 1000):
                            if lang+str(x) not in voices:
                                voices[lang+str(x)] = block
                                break

                    block = {'male': '', 'female': ''}
                    n = 0
                continue

    return voices


if __name__ == '__main__':
    d = get_voices()
    for k in d:
        print(k, d[k])
