#!/usr/bin/env python3
# pip install psd-tools


import io


from psd_tools import PSDImage


def convert_psd_to_jpg(data: bytes) -> bytes:
    '''
    Convert psd to jpg
    :param data: psd data
    :return: jpg data
    '''

    if isinstance(data, str):
        with open('c:/Users/user/Downloads/1.psd', 'rb') as f:
            data = f.read()

    iobytes0 = io.BytesIO(data)
    psd = PSDImage.open(iobytes0)

    image = psd.composite()
    iobytes1 = io.BytesIO()
    iobytes1.name = 'dummy.jpg'
    image.save(iobytes1)
    data2 = iobytes1.getvalue()

    return data2


if __name__ == '__main__':
    pass

    with open('c:/Users/user/Downloads/2.jpg', 'wb') as f:
        f.write(convert_psd_to_jpg('c:/Users/user/Downloads/1.psd'))
