#!/usr/bin/env python3


import pickle
import threading
import traceback

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


PersistentListLock = {}
class PersistentList(list):
    """Постоянный список, хранящий состояние в файле на диске, данные сохраняются между перезапусками программы"""
    def __init__(self, filename):
        self.filename = filename
        PersistentListLock[self.filename] = threading.Lock()
        try:
            with open(filename, 'rb') as f:
                self.extend(pickle.load(f))
        except Exception as unknown:
            error_traceback = traceback.format_exc()
            if 'No such file or directory' not in str(error_traceback):
                my_log.log2(f'my_dic:PersistentList:init: {filename} {str(unknown)}\n\n{error_traceback}')

    def save(self):
        with PersistentListLock[self.filename]:
            with open(self.filename, 'wb') as f:
                try:
                    pickle.dump(self, f)
                except Exception as unknown:
                    error_traceback = traceback.format_exc()
                    my_log.log2(f'my_dic:PersistentList:save: {str(unknown)}\n\n{error_traceback}')

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.save()

    def __delitem__(self, key):
        super().__delitem__(key)
        self.save()

    def append(self, value):
        super().append(value)
        self.save()

    def remove(self, value):
        super().remove(value)
        self.save()

    def remove_all(self, value):
        while value in self:
            super().remove(value)
        self.save()

    def insert(self, index, value):
        super().insert(index, value)
        self.save()

    def pop(self, index=-1):
        value = super().pop(index)
        self.save()
        return value

    def clear(self):
        super().clear()
        self.save()

    def deduplicate(self):
        new_list = list(set(self))
        super().clear()
        self.extend(new_list)
        self.save()

    def recreate(self, new_list):
        super().clear()
        self.extend(new_list)
        self.save()


if __name__ == '__main__':
    pass
