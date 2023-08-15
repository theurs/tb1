#!/usr/bin/env python3
# pip install Pillow


from PIL import Image


if __name__ == '__main__':
    i1 = Image.open('1.jpg')
    i2 = Image.open('2.jpg')
    i3 = Image.new('RGB', (i1.width + i2.width, i1.height))
    i1width, i1height = i2.size
    i2width, i2height = i2.size
    
    # склеить изображжения в 1
    i3.paste(i1, (0, 0))
    i3.paste(i2, (i1width, 0))
    
    i3.tobytes()