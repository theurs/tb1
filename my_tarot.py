import random
import zipfile
from typing import Tuple, List

import my_log


# tarots_files = [
#     # --- Старшие Арканы (Major Arcana), отсортированные по номеру ---
#     '_00_fool.webp',               # Шут (0)
#     '_01_magician.webp',         # Маг (I)
#     '_02_highpriestess.webp',    # Верховная Жрица (II)
#     '_03_empress.webp',          # Императрица (III)
#     '_04_emperor.webp',          # Император (IV)
#     '_05_hierophant.webp',       # Иерофант (V)
#     '_06_lovers.webp',           # Влюбленные (VI)
#     '_07_chariot.webp',           # Колесница (VII)
#     '_11_strength.webp',         # Сила (VIII, в некоторых колодах XI) - предполагаю VIII по традиц. RW
#     '_09_hermit.webp',           # Отшельник (IX)
#     '_10_wheel_of_fortune.webp', # Колесо Фортуны (X)
#     '_11_justice.webp',          # Справедливость (XI, в некоторых колодах VIII) - предполагаю XI по традиц. RW
#     '_12_hanged_man.webp',       # Повешенный (XII)
#     '_13_death.webp',            # Смерть (XIII)
#     '_14_temperance.webp',       # Умеренность (XIV)
#     '_15_devil.webp',            # Дьявол (XV)
#     '_16_tower.webp',            # Башня (XVI)
#     '_17_star.webp',             # Звезда (XVII)
#     '_18_moon.webp',             # Луна (XVIII)
#     '_19_sun.webp',              # Солнце (XIX)
#     '_20_judgement.webp',        # Суд (XX)
#     '_21_world.webp',            # Мир (XXI)

#     # --- Младшие Арканы: Кубки (Kub/Cups) ---
#     '_01_kub.webp', '_02_kub.webp', '_03_kub.webp', '_04_kub.webp',
#     '_05_kub.webp', '_06_kub.webp', '_07_kub.webp', '_08_kub.webp',
#     '_09_kub.webp', '_10_kub.webp', '_11_kub.webp', '_12_kub.webp',
#     '_13_kub.webp', '_14_kub.webp',

#     # --- Младшие Арканы: Мечи (Mech/Swords) ---
#     '_01_mech.webp', '_02_mech.webp', '_03_mech.webp', '_04_mech.webp',
#     '_05_mech.webp', '_06_mech.webp', '_07_mech.webp', '_08_mech.webp',
#     '_09_mech.webp', '_10_mech.webp', '_11_mech.webp', '_12_mech.webp',
#     '_13_mech.webp', '_14_mech.webp',

#     # --- Младшие Арканы: Пентакли (Pentakl/Pentacles) ---
#     '_01_pentakl.webp', '_02_pentakl.webp', '_03_pentakl.webp', '_04_pentakl.webp',
#     '_05_pentakl.webp', '_06_pentakl.webp', '_07_pentakl.webp', '_08_pentakl.webp',
#     '_09_pentakl.webp', '_10_pentakl.webp', '_11_pentakl.webp', '_12_pentakl.webp',
#     '_13_pentakl.webp', '_14_pentakl.webp',

#     # --- Младшие Арканы: Посохи (Posoh/Wands) ---
#     '_01_posoh.webp', '_02_posoh.webp', '_03_posoh.webp', '_04_posoh.webp',
#     '_05_posoh.webp', '_06_posoh.webp', '_07_posoh.webp', '_08_posoh.webp',
#     '_09_posoh.webp', '_10_posoh.webp', '_11_posoh.webp', '_12_posoh.webp',
#     '_13_posoh.webp', '_14_posoh.webp',
# ]


tarots_files = [
    # --- Старшие Арканы (Major Arcana) ---
    "00-TheFool.webp",
    "01-TheMagician.webp",
    "02-TheHighPriestess.webp",
    "03-TheEmpress.webp",
    "04-TheEmperor.webp",
    "05-TheHierophant.webp",
    "06-TheLovers.webp",
    "07-TheChariot.webp",
    "08-Strength.webp",
    "09-TheHermit.webp",
    "10-WheelOfFortune.webp",
    "11-Justice.webp",
    "12-TheHangedMan.webp",
    "13-Death.webp",
    "14-Temperance.webp",
    "15-TheDevil.webp",
    "16-TheTower.webp",
    "17-TheStar.webp",
    "18-TheMoon.webp",
    "19-TheSun.webp",
    "20-Judgement.webp",
    "21-TheWorld.webp",

    # --- Младшие Арканы: Кубки (Cups) ---
    "Cups01.webp",
    "Cups02.webp",
    "Cups03.webp",
    "Cups04.webp",
    "Cups05.webp",
    "Cups06.webp",
    "Cups07.webp",
    "Cups08.webp",
    "Cups09.webp",
    "Cups10.webp",
    "Cups11.webp",  # Page of Cups
    "Cups12.webp",  # Knight of Cups
    "Cups13.webp",  # Queen of Cups
    "Cups14.webp",  # King of Cups

    # --- Младшие Арканы: Пентакли (Pentacles) ---
    "Pentacles01.webp",
    "Pentacles02.webp",
    "Pentacles03.webp",
    "Pentacles04.webp",
    "Pentacles05.webp",
    "Pentacles06.webp",
    "Pentacles07.webp",
    "Pentacles08.webp",
    "Pentacles09.webp",
    "Pentacles10.webp",
    "Pentacles11.webp", # Page of Pentacles
    "Pentacles12.webp", # Knight of Pentacles
    "Pentacles13.webp", # Queen of Pentacles
    "Pentacles14.webp", # King of Pentacles

    # --- Младшие Арканы: Мечи (Swords) ---
    "Swords01.webp",
    "Swords02.webp",
    "Swords03.webp",
    "Swords04.webp",
    "Swords05.webp",
    "Swords06.webp",
    "Swords07.webp",
    "Swords08.webp",
    "Swords09.webp",
    "Swords10.webp",
    "Swords11.webp", # Page of Swords
    "Swords12.webp", # Knight of Swords
    "Swords13.webp", # Queen of Swords
    "Swords14.webp", # King of Swords

    # --- Младшие Арканы: Жезлы (Wands) ---
    "Wands01.webp",
    "Wands02.webp",
    "Wands03.webp",
    "Wands04.webp",
    "Wands05.webp",
    "Wands06.webp",
    "Wands07.webp",
    "Wands08.webp",
    "Wands09.webp",
    "Wands10.webp",
    "Wands11.webp", # Page of Wands
    "Wands12.webp", # Knight of Wands
    "Wands13.webp", # Queen of Wands
    "Wands14.webp", # King of Wands
]


path = 'tarot'
zip_file = f'{path}/1.zip'


def get_single_tarot_card_data() -> Tuple[bytes, str]:
    """
    Retrieves the binary data and filename of a random tarot card from the ZIP archive.

    This function randomly selects a tarot card image file from the predefined
    list and reads its content from the specified ZIP archive.

    Returns:
        Tuple[bytes, str]: A tuple containing the binary content of the
                           selected card image and its filename.
    """
    try:
        name: str = random.choice(tarots_files)
        # Изменение: Открытие ZIP файла и чтение из него
        with zipfile.ZipFile(zip_file, 'r') as zf:
            # Путь внутри ZIP архива
            file_in_zip_path = f'{name}'
            if file_in_zip_path in zf.namelist():
                return zf.read(file_in_zip_path), name
            else:
                my_log.log2(f'my_tarot:get_single_tarot_card_data: File not found in zip: {file_in_zip_path}')
                return b'', ''
    except FileNotFoundError:
        my_log.log2(f'my_tarot:get_single_tarot_card_data: ZIP file not found: {zip_file}')
        return b'', ''
    except Exception as e:
        my_log.log2(f'my_tarot:get_single_tarot_card_data: Error reading from zip: {e}')
        return b'', ''


def get_three_unique_tarot_card_data() -> List[Tuple[bytes, str]]:
    """
    Retrieves a list of three unique tarot card data (binary content and filename) from the ZIP archive.

    This function randomly selects three distinct tarot cards, reads their
    binary content from the specified ZIP archive, and returns them along with
    their filenames. It ensures that no card is repeated.

    Returns:
        List[Tuple[bytes, str]]: A list of three tuples, where each tuple
                                 contains the binary content of a card image
                                 and its filename.
    """
    try:
        selected_cards_data: List[Tuple[bytes, str]] = []
        selected_card_names: List[str] = []

        while len(selected_cards_data) < 3:
            card_data, card_name = get_single_tarot_card_data()
            if card_data and card_name and card_name not in selected_card_names:
                selected_cards_data.append((card_data, card_name))
                selected_card_names.append(card_name)
        return selected_cards_data
    except Exception as e:
        my_log.log2(f'my_tarot:get_three_unique_tarot_card_data: {e}')
        return []


if __name__ == '__main__':
    print(get_three_unique_tarot_card_data())
