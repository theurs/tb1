#!/usr/bin/env python3


import pickle
import threading
from pprint import pprint

import my_log


class PersistentDict(dict):
    """Словарь который хранит состояние в файле на диске, данные сохраняются между
    перезапусками программы"""
    def __init__(self, file_path):
        self.lock = threading.Lock()
        self.file_path = file_path
        try:
            with open(self.file_path, 'rb') as f:
                try:
                    data = pickle.load(f)
                except Exception as error:
                    print(error, 'Empty message history')
                    my_log.log2(f'my_dic:init:{str(error)}')
                    data = []
            self.update(data)
        except FileNotFoundError:
            pass

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        with self.lock:
            with open(self.file_path, 'wb') as f:
                pickle.dump(dict(self), f)

    def __delitem__(self, key):
        super().__delitem__(key)
        with self.lock:
            with open(self.file_path, 'wb') as f:
                pickle.dump(dict(self), f)

    def clear(self):
        super().clear()
        with self.lock:
            with open(self.file_path, 'wb') as f:
                pickle.dump(dict(self), f)

    def pop(self, key, default=None):
        value = super().pop(key, default)
        with self.lock:
            with open(self.file_path, 'wb') as f:
                pickle.dump(dict(self), f)
        return value

    def popitem(self):
        item = super().popitem()
        with self.lock:
            with open(self.file_path, 'rb') as f:
                pickle.dump(dict(self), f)
        return item

    def setdefault(self, key, default=None):
        value = super().setdefault(key, default)
        with self.lock:
            with open(self.file_path, 'wb') as f:
                pickle.dump(dict(self), f)
        return value

    def update(self, E=None, **F):
        super().update(E, **F)
        with self.lock:
            with open(self.file_path, 'wb') as f:
                pickle.dump(dict(self), f)



if __name__ == '__main__':
    my_dict = PersistentDict('db/super_chat.pkl')
    pprint(my_dict)
