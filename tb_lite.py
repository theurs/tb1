#!/usr/bin/env python3


import telebot
import cfg
import utils


bot = telebot.TeleBot(cfg.token, skip_pending=True)


@bot.message_handler(commands=['start'])
def command_code(message: telebot.types.Message):
    t = r"""
```c++
#include <windows.h>
#include <iostream>

// Определение идентификатора окна чата в игре Lineage 2
#define CHAT_WINDOW_ID 0x00000001

// Определение идентификатора кнопки в интерфейсном окне
#define BUTTON_ID 1

// Определение текста сообщения, которое будет отправлено в чат
#define MESSAGE_TEXT "Привет!"

// Функция для отправки сообщения в чат игры Lineage 2
void SendChatMessage(const char* message)
{
    // Получение дескриптора окна чата в игре Lineage 2
    HWND chatWindow = FindWindow(NULL, "Lineage II Chat");

    // Если окно чата не найдено, то вывести сообщение об ошибке и выйти из функции
    if (chatWindow == NULL)
    {
        std::cout << "Error: Could not find chat window." << std::endl;
        return;
    }

    // Получение дескриптора поля ввода текста в окне чата
    HWND chatInput = FindWindowEx(chatWindow, NULL, "RichEdit20W", NULL);

    // Если поле ввода текста не найдено, то вывести сообщение об ошибке и выйти из функции
    if (chatInput == NULL)
    {
        std::cout << "Error: Could not find chat input field." << std::endl;
        return;
    }

    // Установка фокуса на поле ввода текста
    SetFocus(chatInput);

    // Отправка сообщения в поле ввода текста
    SendMessage(chatInput, WM_SETTEXT, 0, (LPARAM)message);

    // Нажатие клавиши Enter для отправки сообщения в чат
    SendMessage(chatInput, WM_KEYDOWN, VK_RETURN, 0);
    SendMessage(chatInput, WM_KEYUP, VK_RETURN, 0);
}

// Функция для обработки нажатия кнопки в интерфейсном окне
LRESULT CALLBACK WindowProc(HWND hwnd, UINT message, WPARAM wParam, LPARAM lParam)
{
    switch (message)
    {
        case WM_COMMAND:
            // Если нажата кнопка с идентификатором BUTTON_ID, то отправить сообщение в чат
            if (LOWORD(wParam) == BUTTON_ID)
            {
                SendChatMessage(MESSAGE_TEXT);
            }
            break;

        case WM_DESTROY:
            // Если окно закрыто, то выйти из программы
            PostQuitMessage(0);
            break;
    }

    return DefWindowProc(hwnd, message, wParam, lParam);
}

// Точка входа в DLL-библиотеку
BOOL APIENTRY DllMain(HMODULE hModule, DWORD ul_reason_for_call, LPVOID lpReserved)
{
    switch (ul_reason_for_call)
    {
        case DLL_PROCESS_ATTACH:
            // DLL-библиотека была внедрена в процесс игры Lineage 2

            // Создание класса окна для интерфейсного окна
            WNDCLASSEX wc;
            wc.cbSize = sizeof(WNDCLASSEX);
            wc.style = CS_HREDRAW | CS_VREDRAW;
            wc.lpfnWndProc = WindowProc;
            wc.cbClsExtra = 0;
            wc.cbWndExtra = 0;
            wc.hInstance = GetModuleHandle(NULL);
            wc.hIcon = LoadIcon(NULL, IDI_APPLICATION);
            wc.hCursor = LoadCursor(NULL, IDC_ARROW);
            wc.hbrBackground = (HBRUSH)GetStockObject(WHITE_BRUSH);
            wc.lpszMenuName = NULL;
            wc.lpszClassName = "L2InjectorWindowClass";
            wc.hIconSm = LoadIcon(NULL, IDI_APPLICATION);

            // Регистрация класса окна
            if (!RegisterClassEx(&wc))
            {
                std::cout << "Error: Could not register window class." << std::endl;
                return FALSE;
            }

            // Создание интерфейсного окна
            HWND window = CreateWindowEx(WS_EX_TOPMOST, "L2InjectorWindowClass", "L2 Injector", WS_POPUP, 0, 0, 200, 100, NULL, NULL, GetModuleHandle(NULL), NULL);

            // Если окно не создано, то вывести сообщение об ошибке и выйти из функции
            if (window == NULL)
            {
                std::cout << "Error: Could not create window." << std::endl;
                return FALSE;
            }

            // Создание кнопки в интерфейсном окне
            HWND button = CreateWindow("BUTTON", "Привет", WS_CHILD | WS_VISIBLE, 10, 10, 100, 25, window, (HMENU)BUTTON_ID, GetModuleHandle(NULL), NULL);

            // Если кнопка не создана, то вывести сообщение об ошибке и выйти из функции
            if (button == NULL)
            {
                std::cout << "Error: Could not create button." << std::endl;
                return FALSE;
            }

            // Отображение интерфейсного окна
            ShowWindow(window, SW_SHOW);

            break;

        case DLL_PROCESS_DETACH:
            // DLL-библиотека была удалена из процесса игры Lineage 2
            break;
    }

    return TRUE;
}
```

Эта DLL-библиотека создает интерфейсное окно поверх игры Lineage 2 с кнопкой "Привет". При нажатии на кнопку в чат игры отправляется сообщение "Привет!".

Чтобы использовать эту DLL-библиотеку, вам нужно:

1. Скомпилировать DLL-библиотеку в файл DLL.
2. Внедрить DLL-библиотеку в процесс игры Lineage 2 с помощью инжектора.
3. Запустить игру Lineage 2.

После запуска игры на экране появится интерфейсное окно с кнопкой "Привет". При нажатии на кнопку в чат игры будет отправлено сообщение "Привет!".

Обратите внимание, что использование инжекторов является нарушением правил игры Lineage 2 и может привести к блокировке игрового аккаунта. Поэтому используйте инжектор на свой страх и риск.
"""

    t = utils.bot_markdown_to_html(t)
    for x in utils.split_html(t, 4000):
        bot.reply_to(message, x, parse_mode = 'HTML')



if __name__ == '__main__':
    bot.polling()
