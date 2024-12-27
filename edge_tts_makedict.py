#!/usr/bin/env python3


# создает словарь из языков которые поддерживает edge-tts. есть некоторые проблемы с длинными языками, у которых коды больше 2 символов

import subprocess


def parse_voices(text):
    voices = {}
    current_gender = None
    for line in text.split('\n'):
        if line.startswith("Name: "):
            _, name = line.split(": ")
            language, region, _ = name.split('-', maxsplit=2)
            if language not in voices:
                voices[language] = {}
            if region not in voices[language]:
                voices[language][region] = {'Male': [], 'Female': []}
        elif line.startswith("Gender: "):
          current_gender = line.split(": ")[1]
          voices[language][region][current_gender].append(name)
    return voices


def format_voices(voices):
    formatted_voices = {}
    for lang, regions in voices.items():
        lang_count = 1

        # 1. Формируем мульти-язычные пары
        male_multi = []
        female_multi = []
        for region, genders in regions.items():
            for voice in genders['Male']:
                if "Multilingual" in voice and voice.split('-')[0] == lang:
                    male_multi.append(voice)
            for voice in genders['Female']:
                if "Multilingual" in voice and voice.split('-')[0] == lang:
                    female_multi.append(voice)

        for i in range(min(len(male_multi), len(female_multi))):
            key = lang if lang_count == 1 else f"{lang}{lang_count}"
            formatted_voices[key] = {'male': male_multi[i], 'female': female_multi[i]}
            lang_count += 1

        # 2. Формируем пары внутри регионов
        for region, genders in regions.items():
            # Создаем списки для мужских и женских голосов в текущем регионе
            male_voices = [v for v in genders['Male'] if v not in male_multi]
            female_voices = [v for v in genders['Female'] if v not in female_multi]

            # Формируем пары голосов внутри региона
            for i in range(min(len(male_voices), len(female_voices))):
                key = lang if lang_count == 1 else f"{lang}{lang_count}"
                formatted_voices[key] = {'male': male_voices[i], 'female': female_voices[i]}
                lang_count += 1

            # Добавляем оставшиеся непарные голоса в регионе
            for i in range(min(len(male_voices), len(female_voices)), len(male_voices)):
                key = f"{lang}{lang_count}"
                formatted_voices[key] = {'male': male_voices[i], 'female': None}
                lang_count += 1

            for i in range(min(len(male_voices), len(female_voices)), len(female_voices)):
                key = f"{lang}{lang_count}"
                formatted_voices[key] = {'male': None, 'female': female_voices[i]}
                lang_count += 1

    return formatted_voices



if __name__ == '__main__':
    proc = subprocess.run(['edge-tts', '-l'], stdout=subprocess.PIPE)
    text = proc.stdout.decode('utf-8', errors='replace').strip()

    text = text.replace('\r', '')
    d = parse_voices(text)
    format_voices(d)
    d = parse_voices(text)
    dd = format_voices(d)
    l = []
    for k in dd:
        print(f"'{k}': {dd[k]},")
        if k not in l:
            l.append(k)
    print('')
    print(l)
