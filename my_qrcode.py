# sudo apt install zbar-tools
# example: zbarimg -q --raw 1.png


import subprocess

import my_log
import utils


def get_text(data: bytes) -> str:
    try:
        tmp_file_name = utils.get_tmp_fname()
        with open(tmp_file_name, 'wb') as f:
            f.write(data)
        proc = subprocess.run(['zbarimg', '-q', '--raw', tmp_file_name], stdout=subprocess.PIPE)
        text = proc.stdout.decode('utf-8', errors='replace').strip()
        utils.remove_file(tmp_file_name)
        return text
    except Exception as unknown_error:
        my_log.log2(f'my_qrcode:get_text: {unknown_error}')
        return ''


if __name__ == '__main__':
    pass
    print(get_text(open('1.png', 'rb').read()))
