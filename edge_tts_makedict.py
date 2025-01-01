#!/usr/bin/env python


import subprocess
from pprint import pprint


def parse_voices(text):
    """
    Parses the output of `edge-tts -l` command and returns a dictionary of voices.

    Args:
        text: The output of `edge-tts -l` command.

    Returns:
        A dictionary where keys are languages, values are dictionaries of regions,
        and values of regions are dictionaries with 'Male' and 'Female' lists of voices.
    """
    voices = {}
    lines = text.split('\n')
    
    # Skip the header lines (first two lines)
    for line in lines[2:]:
        line = line.strip()
        if not line:
            continue

        # Split the line into parts (using multiple spaces as delimiter)
        parts = line.split()
        if len(parts) >= 2:
            name = parts[0]
            gender = parts[1]
            
            language, region, _ = name.split('-', maxsplit=2)

            if language not in voices:
                voices[language] = {}
            if region not in voices[language]:
                voices[language][region] = {'Male': [], 'Female': []}

            if gender == 'Male':
                voices[language][region]['Male'].append(name)
            elif gender == 'Female':
                voices[language][region]['Female'].append(name)

    return voices


def format_voices(voices):
    """
    Formats the voices dictionary to create male-female pairs for each language.
    Prioritizes multilingual voices to be at the beginning of the list for each language,
    ensures pairs are formed within the same region, and generates keys in the format
    "language" or "language + number".

    Args:
        voices: A dictionary of voices as returned by parse_voices.

    Returns:
        A dictionary where keys are language codes (with optional numerical suffix),
        and values are dictionaries with 'male' and 'female' keys mapping to voice names.
    """
    formatted_voices = {}
    for lang, regions in voices.items():
        lang_count = 1

        # 1. Collect and prioritize multilingual voices
        multi_male_voices = []
        multi_female_voices = []
        for region, genders in regions.items():
            for voice in genders['Male']:
                if "Multilingual" in voice and voice.split('-')[0] == lang:
                    multi_male_voices.append(voice)
            for voice in genders['Female']:
                if "Multilingual" in voice and voice.split('-')[0] == lang:
                    multi_female_voices.append(voice)

        # Remove duplicates while preserving order
        multi_male_voices = list(dict.fromkeys(multi_male_voices))
        multi_female_voices = list(dict.fromkeys(multi_female_voices))

        # 2. Create pairs for multilingual voices
        for i in range(min(len(multi_male_voices), len(multi_female_voices))):
            key = lang if lang_count == 1 else f"{lang}{lang_count}"
            formatted_voices[key] = {'male': multi_male_voices[i], 'female': multi_female_voices[i]}
            lang_count += 1

        # Add remaining unpaired multilingual male voices
        for i in range(min(len(multi_male_voices), len(multi_female_voices)), len(multi_male_voices)):
            key = f"{lang}{lang_count}"
            formatted_voices[key] = {'male': multi_male_voices[i], 'female': None}
            lang_count += 1

        # Add remaining unpaired multilingual female voices
        for i in range(min(len(multi_male_voices), len(multi_female_voices)), len(multi_female_voices)):
            key = f"{lang}{lang_count}"
            formatted_voices[key] = {'male': None, 'female': multi_female_voices[i]}
            lang_count += 1

        # 3. Create pairs for other voices within each region
        region_voices = {}
        for region, genders in regions.items():
            region_voices[region] = {
                'male': [v for v in genders['Male'] if v not in multi_male_voices],
                'female': [v for v in genders['Female'] if v not in multi_female_voices]
            }

        for region, voices_in_region in region_voices.items():
            male_voices = voices_in_region['male']
            female_voices = voices_in_region['female']

            for i in range(min(len(male_voices), len(female_voices))):
                key = lang if lang_count == 1 else f"{lang}{lang_count}"
                formatted_voices[key] = {'male': male_voices[i], 'female': female_voices[i]}
                lang_count += 1

            # Add remaining unpaired male voices
            for i in range(min(len(male_voices), len(female_voices)), len(male_voices)):
                key = f"{lang}{lang_count}"
                formatted_voices[key] = {'male': male_voices[i], 'female': None}
                lang_count += 1

            # Add remaining unpaired female voices
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

    # New code for formatted output:
    for i in range(0, len(l), 10):
        print(", ".join(f"'{x}'" for x in l[i:i+10]))

    print('')

    # Вместо вывода пар ключ-значение, сразу формируем и выводим строки
    last_lang = None  # Переменная для хранения предыдущего языка
    for key, value in dd.items():
        male_voice = value['male'] if value['male'] else "None"
        female_voice = value['female'] if value['female'] else "None"

        # Получаем текущий язык из ключа
        current_lang = key.split('-')[0].split(' ')[0].rstrip('0123456789')

        # Если текущий язык отличается от предыдущего, добавляем пустую строку
        if current_lang != last_lang:
            if last_lang is not None:  # Проверяем, что это не первая итерация
                print()
            last_lang = current_lang

        print(f"{key} {male_voice}, {female_voice}")
