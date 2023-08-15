#!/usr/bin/env python3
#pip install pandoc


import os
import subprocess
import sys
from pathlib import Path

import utils


# сработает если бот запущен питоном из этого venv
pandoc_cmd = Path(Path(sys.executable).parent, 'pandoc')


def fb2_to_txt(data: bytes) -> str:
    input_file = utils.get_tmp_fname()
    output_file = utils.get_tmp_fname()
    open(input_file, 'wb').write(data)
    subprocess.run([pandoc_cmd, '-f', 'fb2', '-t', 'plain', input_file, output_file], 
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    result = open(output_file, 'r').read()
    os.remove(input_file)
    os.remove(output_file)
    return result


if __name__ == '__main__':
    print(fb2_to_txt(open('1.fb2', 'rb').read()))