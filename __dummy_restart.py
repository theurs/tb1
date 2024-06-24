#!/usr/bin/env python3
# pip install flet


import os
import time

import flet as ft

import cfg


def main(page: ft.Page):
    def check_password(e):
        time.speep(5)
        if not hasattr(cfg, 'RESTART_PASSWORD'):
            return
        if password_field.value == cfg.RESTART_PASSWORD:
            page.add(ft.Text("Верный пароль!"))
            # os.system('sudo systemctl restart telegram-bot')
            print('btn pressed, pass ok')
        else:
            page.add(ft.Text("Неверный пароль!"))
            print('btn pressed, pass bad')
        time.speep(5)

    password_field = ft.TextField(label = "Введите пароль",
                                  password=True,
                                  autofocus = True,
                                  )
    button = ft.ElevatedButton(text="Restart", on_click=check_password)

    page.add(password_field, button)

ft.app(target=main)
