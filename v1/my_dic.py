#!/usr/bin/env python3


import pickle


class PersistentDict(dict):
    def __init__(self, file_path):
        self.file_path = file_path
        try:
            with open(self.file_path, 'rb') as f:
                try:
                    data = pickle.load(f)
                except Exception as e:
                    print('Empty message history')
                    data = []
            self.update(data)
        except FileNotFoundError:
            pass
    
    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        with open(self.file_path, 'wb') as f:
            pickle.dump(dict(self), f)
    
    def __delitem__(self, key):
        super().__delitem__(key)
        with open(self.file_path, 'wb') as f:
            pickle.dump(dict(self), f)
    
    def clear(self):
        super().clear()
        with open(self.file_path, 'wb') as f:
            pickle.dump(dict(self), f)
    
    def pop(self, key, default=None):
        value = super().pop(key, default)
        with open(self.file_path, 'wb') as f:
            pickle.dump(dict(self), f)
        return value
    
    def popitem(self):
        item = super().popitem()
        with open(self.file_path, 'rb') as f:
            pickle.dump(dict(self), f)
        return item
    
    def setdefault(self, key, default=None):
        value = super().setdefault(key, default)
        with open(self.file_path, 'wb') as f:
            pickle.dump(dict(self), f)
        return value
    
    def update(self, E=None, **F):
        super().update(E, **F)
        with open(self.file_path, 'wb') as f:
            pickle.dump(dict(self), f)



if __name__ == '__main__':
    my_dict = PersistentDict('dialogs.pkl')
    my_dict['key'] = 'value'
    print(my_dict)