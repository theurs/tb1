#!/usr/bin/env python3
# pip install flet


import os

import flet as ft


def main(page: ft.Page):
    def restart_bot(e):
        os.system('sudo systemctl restart telegram-bot')

    button = ft.ElevatedButton(text="Restart", on_click=restart_bot)

    page.add(button)

ft.app(target=main)
