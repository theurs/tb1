#!/usr/bin/env python3


import os

from bardapi import Bard

import cfg


if __name__ == "__main__":
    
    os.environ['all_proxy'] = cfg.all_proxy
    
    bard = Bard(token=cfg.bard_token, language='ru', timeout=30)
    bard.get_answer('Привет как дела?')
