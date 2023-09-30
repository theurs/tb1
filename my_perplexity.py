#!/usr/bin/env python3


import subprocess


def ask(query: str) -> str:
    process = subprocess.Popen(['/home/ubuntu/.tb1/bin/python',
                                '/home/ubuntu/tb1/my_perplexity_cmd.py',
                                query], stdout = subprocess.PIPE)
    output, error = process.communicate()
    r = output.decode('utf-8').strip()
    if error != None:
        return None
    return r


if __name__ == '__main__':
    while True:
        q = input('>')
        print(ask(q))
