#!/usr/bin/env python3


import subprocess
import tempfile
import os
import sys
from pathlib import Path

import gpt_basic


# сработает если бот запущен питоном из этого venv
vosk_cmd = Path(Path(sys.executable).parent, 'vosk-transcriber')


def stt(input_file):
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        output_file = temp_file.name

    subprocess.run([vosk_cmd, "--server", "--input", input_file, "--output", output_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(output_file, "r") as f:
        text = f.read()
    # Удаление временного файла
    os.remove(output_file)
    cleared = gpt_basic.clear_after_stt(text)
    return cleared


if __name__ == "__main__":
    print(vosk_cmd)
    #text = stt('2.ogg')
    #print(text)
