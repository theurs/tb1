#!/usr/bin/env python3


import time

import cfg
import my_db


def get_targets(DDOS_BLOCKED_USERS, chat_id_full):
    ids = []
    all_users = list(set(my_db.get_all_users_ids()))
    for x in all_users:
        chat_id = x
        x = x.replace('[','').replace(']','')
        try:
            chat = int(x.split()[0])
        except:
            print(x)
            continue

        # посылать только админам, для проверки    
        # if chat not in cfg.admins:
        #     continue

        # try:
        #     thread = int(x.split()[1])
        # except IndexError:
        #     print(x)
        #     continue

        # в чаты не слать
        if chat < 0:
            continue

        # заблокированым не посылать
        if chat_id in DDOS_BLOCKED_USERS or \
        my_db.get_user_property(chat_id, 'blocked') or \
        my_db.get_user_property(chat_id, 'blocked_bing') or \
        my_db.get_user_property(chat_id, 'blocked_totally'):
            continue

        # Только тем у кого больше 1000 сообщений или картинок за последние 90 дней
        total_msgs = my_db.count_msgs(chat_id, 'all', 60*60*24*90) or 0
        total_images = my_db.get_user_property(chat_id, 'image_generated_counter') or 0
        most_of_two = total_msgs if total_msgs > total_images else total_images
        if most_of_two < 1000:
            continue

        # только тех кто был активен в течение 30 дней
        if my_db.get_user_property(chat_id_full, 'last_time_access') and my_db.get_user_property(chat_id_full, 'last_time_access') + (3600*30*24) < time.time():
            continue

        ids.append(chat)
    return ids


if __name__ == '__main__':
    pass
