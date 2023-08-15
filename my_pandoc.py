#!/usr/bin/env python3
# pip install pandoc


import pandoc



if __name__ == '__main__':
    doc = pandoc.read('1.fb2', format='fb2')
    text = pandoc.write(doc, 'plain')
    print(text)