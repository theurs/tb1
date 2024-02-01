#!/usr/bin/env python3


import pickle
import time
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


class PersistDict:
    def __init__(self, filename = 'test.pickle', timer = 2):
        self.filename = filename
        self.data = {}
        self.last_hash = None
        self.timer = timer
        self.lock = threading.Lock()

        self.load()

        self._thread = threading.Thread(target=self.run)
        self.running = True
        self._thread.start()

    def stop(self):
        self.running = False
        self._thread.join()
        self.check_for_changes()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value

    def __delitem__(self, key):
        del self.data[key]

    def __contains__(self, key):
        return key in self.data

    def __reversed__(self):
        return reversed(self.data)

    def __eq__(self, other):
        return self.data == other
    
    def __hash__(self):
        return hash(pickle.dumps(self.data))

    def __ne__(self, other):
        return self.data != other

    def __len__(self):
        return len(self.data)

    def __iter__(self):
        return iter(self.data)

    def clear(self):
        self.data.clear()

    # def copy(self):
    #     return PersistDict(self.filename, self.data.copy())

    @classmethod
    def fromkeys(cls, keys, value=None):
        return cls({key: value for key in keys})

    def get(self, key, default=None):
        return self.data.get(key, default)

    def items(self):
        return self.data.items()

    def keys(self):
        return self.data.keys()

    def pop(self, key, default=None):
        value = self.data.pop(key, default)
        return value

    def popitem(self):
        key, value = self.data.popitem()
        return key, value

    def setdefault(self, key, default=None):
        value = self.data.setdefault(key, default)
        return value

    def update(self, other):
        self.data.update(other)

    def values(self):
        return self.data.values()

    def load(self):
        try:
            with open(self.filename, 'rb') as f:
                self.data = pickle.load(f)
            self.last_hash = hash(pickle.dumps(self.data))
        except FileNotFoundError:
            pass

    def save(self):
        with self.lock:
            with open(self.filename, 'wb') as f:
                # print('saving')
                pickle.dump(self.data, f)

    def check_for_changes(self):
        new_hash = hash(pickle.dumps(self.data))
        if new_hash != self.last_hash:
            self.save()
            self.last_hash = new_hash

    def run(self):
        while self.running:
            time.sleep(self.timer)
            self.check_for_changes()


if __name__ == '__main__':
    with PersistDict() as d:
        for x in range(10):
            d[x] = x+1
            time.sleep(1)
            print(d[x])

    # d = PersistDict()
    # d.clear()
    # for x in range(2):
    #     d[x] = x+1
    #     time.sleep(1)
    #     print(d[x])
    # d.stop()

    print('finished')
