import random
import zipfile
from typing import Tuple, List

import my_log


tarots_files = [
    # --- Старшие Арканы (Major Arcana), отсортированные по номеру ---
    '_00_fool.png',               # Шут (0)
    '_01_magician.png',         # Маг (I)
    '_02_highpriestess.png',    # Верховная Жрица (II)
    '_03_empress.png',          # Императрица (III)
    '_04_emperor.png',          # Император (IV)
    '_05_hierophant.png',       # Иерофант (V)
    '_06_lovers.png',           # Влюбленные (VI)
    '_07_chariot.png',           # Колесница (VII)
    '_11_strength.png',         # Сила (VIII, в некоторых колодах XI) - предполагаю VIII по традиц. RW
    '_09_hermit.png',           # Отшельник (IX)
    '_10_wheel_of_fortune.png', # Колесо Фортуны (X)
    '_11_justice.png',          # Справедливость (XI, в некоторых колодах VIII) - предполагаю XI по традиц. RW
    '_12_hanged_man.png',       # Повешенный (XII)
    '_13_death.png',            # Смерть (XIII)
    '_14_temperance.png',       # Умеренность (XIV)
    '_15_devil.png',            # Дьявол (XV)
    '_16_tower.png',            # Башня (XVI)
    '_17_star.png',             # Звезда (XVII)
    '_18_moon.png',             # Луна (XVIII)
    '_19_sun.png',              # Солнце (XIX)
    '_20_judgement.png',        # Суд (XX)
    '_21_world.png',            # Мир (XXI)

    # --- Младшие Арканы: Кубки (Kub/Cups) ---
    '_01_kub.png', '_02_kub.png', '_03_kub.png', '_04_kub.png',
    '_05_kub.png', '_06_kub.png', '_07_kub.png', '_08_kub.png',
    '_09_kub.png', '_10_kub.png', '_11_kub.png', '_12_kub.png',
    '_13_kub.png', '_14_kub.png',

    # --- Младшие Арканы: Мечи (Mech/Swords) ---
    '_01_mech.png', '_02_mech.png', '_03_mech.png', '_04_mech.png',
    '_05_mech.png', '_06_mech.png', '_07_mech.png', '_08_mech.png',
    '_09_mech.png', '_10_mech.png', '_11_mech.png', '_12_mech.png',
    '_13_mech.png', '_14_mech.png',

    # --- Младшие Арканы: Пентакли (Pentakl/Pentacles) ---
    '_01_pentakl.png', '_02_pentakl.png', '_03_pentakl.png', '_04_pentakl.png',
    '_05_pentakl.png', '_06_pentakl.png', '_07_pentakl.png', '_08_pentakl.png',
    '_09_pentakl.png', '_10_pentakl.png', '_11_pentakl.png', '_12_pentakl.png',
    '_13_pentakl.png', '_14_pentakl.png',

    # --- Младшие Арканы: Посохи (Posoh/Wands) ---
    '_01_posoh.png', '_02_posoh.png', '_03_posoh.png', '_04_posoh.png',
    '_05_posoh.png', '_06_posoh.png', '_07_posoh.png', '_08_posoh.png',
    '_09_posoh.png', '_10_posoh.png', '_11_posoh.png', '_12_posoh.png',
    '_13_posoh.png', '_14_posoh.png',
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
