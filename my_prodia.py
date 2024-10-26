#!/usr/bin/env python3
#pip install prodiapy

import random
import traceback

from prodiapy import Prodia

import cfg
import utils
import my_log


# растягиваем 1 ключ на неделю при условии что всего 500 запросов в день делается
if hasattr(cfg, 'PRODIA_KEYS'):
    daily_resource = 500  # единиц ресурса в день
    total_resource = 1000 # общие единицы ресурса
    days = 7
    chance_per_request = (1000 / (500 * 7)) * len(cfg.PRODIA_KEYS) # вероятность сделать запрос в каждый день
# debug!!!
# chance_per_request = 1


def gen_image(prompt: str, negative_prompt: str) -> bytes:
    try:
        if not hasattr(cfg, 'PRODIA_KEYS') or len(cfg.PRODIA_KEYS) < 1:
            return b''

        if random.random() > chance_per_request:
            return b''

        prodia = Prodia(
            api_key=random.choice(cfg.PRODIA_KEYS)
        )

        job = prodia.sdxl.generate(
            prompt=prompt,
            negative_prompt=negative_prompt,
            # model='',
            height = 1024,
            width=1024)

        result = prodia.wait(job)

        if result.image_url:
            return utils.download_image_as_bytes(result.image_url)
        else:
            return b''
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log2(f'my_prodia:gen_image: {error}\n\n{error_traceback}')
        return b''


if __name__ == "__main__":
    pass
    # print(gen_image('cat', ''))
