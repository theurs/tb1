import re

import cfg
import my_qrcode_generate
import my_log
import my_skills_storage
import my_svg
import utils


def restore_id(chat_id: str) -> str:
    '''
    Restore user id from string (they often miss brackets and add some crap)

    Args:
        chat_id: str
    Returns:
        chat_id in format '[number1] [number2]'
    '''
    def is_integer(s):
        try:
            int(s)
            return True
        except ValueError:
            return False

    pattern = r'^\[-?\d+\] \[\d+\]$'
    if re.fullmatch(pattern, chat_id):
        return chat_id

    # remove all symbols except numbers, minus and brackets
    chat_id = re.sub(r'[^0-9\-]', ' ', chat_id)
    chat_id = re.sub(r'\s+', ' ', chat_id).strip()

    # chat_id может приехать в виде одного числа - надо проверять и переделывать, добавлять скобки и число
    if is_integer(chat_id):
        chat_id = f"[{chat_id}] [0]"
    # если нет второго числа до добавить '[0]'
    if chat_id.count('[') == 1:
        chat_id = f"{chat_id} [0]"

    chat_id = chat_id.strip()
    if not chat_id:
        chat_id = '[unknown]'
    return chat_id


def tts(user_id: str) -> str:
    '''
    Generate and send audio message from text to user.
    Use it only if asked by user to generate audio from text.
    To change voice user can use `/config` command
    Args:
        text: str - text to say (up to 8000 symbols)
        lang: str - language code, default is 'ru'
        rate: str - speed rate, +-100%, default is '+0%'
    '''
    user_id = restore_id(user_id)
    my_log.log_gemini_skills(f'/tts {user_id}')
    return "When generating an audio message for the user, your output must be exclusively the /tts command in the format /tts [lang ru en etc] [speed +-100%] [text], with absolutely no preceding or additional explanatory text, because this exact message is directly processed by the external audio generation system for delivery to the user. For example: /tts en +50% Hello, how are you? Do NOT respond with text like 'Here is your audio: /tts en +50% Hello, how are you?' as this will fail. User can change voices with `/config` command."


def speech_to_text(user_id: str) -> str:
    '''
    Transcribe audio message from telegram user.

    Args:
        user_id: str - telegram user id
    '''
    user_id = restore_id(user_id)
    my_log.log_gemini_skills(f'/stt {user_id}')
    return "The function itself does not return an transcribed text. It returns a string containing instructions for the assistant. Any audio-video files send by user to telegram bot will be transcribed automatically and assistant can work with this text."


def translate_text(user_id: str) -> str:
    '''
    Translate text to another language.

    Args:
        user_id: str - telegram user id
    '''
    user_id = restore_id(user_id)
    my_log.log_gemini_skills(f'/translate_text {user_id}')
    return "The function itself does not return an translated text. It returns a string containing instructions for the assistant. There are no tools for text translation, assistant have to translate all text by itself, as if he is a professional translator, using synonyms and context for better translation."


def translate_documents(user_id: str) -> str:
    '''
    Translate documents to another language.

    Args:
        user_id: str - telegram user id
    '''
    user_id = restore_id(user_id)
    my_log.log_gemini_skills(f'/translate_documents {user_id}')
    return "The function itself does not return an translated text. It returns a string containing instructions for the assistant. If user send document to telegram bot with caption like `!tr lang` it will translated automatically. Any documents send by user to telegram bot will by converted to markdown text for assistant."


def edit_image(user_id: str) -> str:
    '''
    Edit images.

    Args:
        user_id: str - telegram user id
    '''
    user_id = restore_id(user_id)
    my_log.log_gemini_skills_img(f'/edit_image {user_id}')
    return "The function itself does not return an edited image. It returns a string containing instructions for the assistant. Answer to user codeword <<EDIT IMAGE>> to indicate you understood this query was a request to edit image, dont add any other text."


def text_to_image(prompt: str) -> str:
    '''
    Generate and send image message from text to user.
    Use it only if asked by user to generate image from text.
    Avoid using text_to_image for precise mathematical expressions, structured diagrams,
    or data-driven charts; instead, use save_diagram_to_image or save_chart_and_graphs_to_image
    for those specific tasks. Use save_html_to_image for drawing mostly textual content.

    Args:
        prompt: str - text to generate image from

    '''
    my_log.log_gemini_skills_img(f'/img "{prompt}"')
    return (
        "The function itself does not return an image. It returns a string containing "
        "instructions for the assistant. The assistant must send a new message, starting "
        "with the /img command, followed by a space, and then the prompt provided, up to "
        "100 words. This specific message format will be automatically recognized by an "
        "external system as a request to generate and send an image to the user. "
        "You can also use the commands /flux <prompt> and /gem <1-4> <prompt> and /bing <prompt> for image generation. "
        "Flux draws one picture using the flux-dev model, gem draws several pictures using the Gemini model, "
        "bing draws 1-4 pictures using the DALL·E 3 model. /img draws 4 pictures with Bing + 2 with Gemini, "
        "and if none could be drawn, it tries to draw one with Flux. Gemini is the only one that "
        "can properly draw text and celebrities, Flux is the most uninhibited and accurate. Bing is the best but most restricted."
    )


def text_to_qrcode(text: str, logo_url: str, user_id: str) -> str:
    '''
    Send qrcode message to telegram user.

    Args:
        text: str - text to generate qrcode from
        logo_url: str - url to logo image, use 'DEFAULT' or empty string for default logo, any image including svg is supported.
        user_id: str - user id
    Returns:
        str: 'OK' or error message
    '''
    try:
        my_log.log_gemini_skills_img(f'/qrcode "{text}" "{logo_url}" "{user_id}"')

        user_id = restore_id(user_id)

        if logo_url != 'DEFAULT' and logo_url:
            logo_data = utils.download_image_as_bytes(logo_url)
            if logo_url.lower().endswith('.svg'):
                logo_data = my_svg.convert_svg_to_png_bytes(logo_data)
            if not logo_data:
                return "Failed to download logo image."
        elif logo_url == 'DEFAULT':
            logo_data = './pics/photo_2023-07-10_01-36-39.jpg'
        else:
            logo_data = ''

        png_bytes = my_qrcode_generate.generate_qr_with_logo_bytes(text, logo_data)
        if isinstance(png_bytes, str):
            return png_bytes

        if isinstance(png_bytes, bytes) and len(png_bytes) > 0:
            item = {
                'type': 'image/png file',
                'filename': 'https://t.me/kun4sun_bot',
                'data': png_bytes,
            }
            with my_skills_storage.STORAGE_LOCK:
                if user_id in my_skills_storage.STORAGE:
                    if item not in my_skills_storage.STORAGE[user_id]:
                        my_skills_storage.STORAGE[user_id].append(item)
                else:
                    my_skills_storage.STORAGE[user_id] = [item,]
            return "OK"

    except Exception as e:
        my_log.log_gemini_skills_img(f'my_skills.py:text_to_qrcode - Failed to generate qrcode: {e}')

    return "Failed to generate qrcode."


def help(user_id: str) -> str:
    '''
    Return help info about you (assistant and telegram bot) skills and abilities.
    Use it if user ask what he can do here or what you can do for him.
    '''
    user_id = restore_id(user_id)

    my_log.log_gemini_skills(f'help {user_id}')

    bot_name = f'@{cfg._BOT_NAME}' if hasattr(cfg, '_BOT_NAME') and cfg._BOT_NAME else '@kun4sun_bot'

    help_msg = f'''Эту информацию не следует выдавать юзеру без его явного запроса, особенно всю сразу, люди не любят читать длинные тесты.

Ты(ассистент) общаешься в телеграм чате с юзером, с точки зрения юзера ты телеграм бот по имени ЧатБот {bot_name}.
В разных локализациях имя ЧатБот и описание в телеграме может быть другим (используется автоперевод на все языки).

По команде /start юзер видит следующее сообщение:

----------------
Здравствуйте, я чат-бот с искусственным интеллектом. Я здесь, чтобы помочь вам во всем, что вам нужно.

✨ Доступ ко всем текстовым ИИ
🎨 Рисование и редактирование изображений
🗣 Распознавание голоса и создание субтитров
🖼 Ответы на вопросы об изображениях
🌐 Поиск в Интернете с использованием ИИ
🔊 Генерация речи
📝 Перевод документов
📚 Суммирование длинных текстов и видео
🎧 Загрузка аудио с YouTube

Спрашивайте меня о чем угодно. Отправляйте мне свой текст/изображение/аудио/документы с вопросами.
Создавайте изображения с помощью команды /img.

Измените язык с помощью команды /lang.
Удалите клавиатуру с помощью /remove_keyboard.
----------------

У этого телеграм бота (то есть у тебя, у ассистента) есть команды набираемые в чате начинающиеся с /:

/reset - Стереть текущий диалог и начать разговор заново
/help - Справка
/config - Меню настроек, там можно изменить параметры,
    выбрать llm модель gemini|mistral|llama|ChatGPT|Cohere|Deepseek|Openrouter,
    выбрать голос озвучки TTS - Microsoft Edge|Google|Gemini|OpenAI,
    включить только голосовой режим что бы твои ответы доходили до юзера только голосом с помощью TTS (🗣️),
    вкл/выкл кнопки под твоими ответами, кнопки там обычно такие:
        ➡️ (Right Arrow): Prompts the bot to continue the conversation or generate the next response.
        ♻️ (Circular Arrows): Clears the bot's memory and starts a new conversation.
        🙈 (Hands Covering Eyes): Hides or deletes the current message or response.
        📢 (Megaphone): Plays the text aloud using Text-to-Speech (TTS).
        📸 (Camera): Displays Google Images search results based on your request.
        🎤 (Microphone): Selects the voice AI engine for speech recognition. If Whisper (or another engine) doesn't understand your voice well, you can choose a different one.
    изменить тип уведомлений об активности - стандартный для телеграма и альтернативный (🔔),
    вкл/выкл режим при котором все голосовые сообщения только транскрибируются без дальнейшей обработки (📝),
    вкл/выкл отображение ответов, твои сообщения будут выглядеть как просто сообщения а не ответы на сообщения юзера (↩️),
    вкл/выкл автоматические ответы в публичном чате - это нужно для того что бы бот воспринимал комнату в чате как приватный разговор и отвечал на все запросы в чате а не только те которые начинаются с его имени (🤖),
    можно выбрать движок для распознавания голоса если дефолтный плохо понимает речь юзера - whisper|gemini|google|AssemblyAI|Deepgram,
/lang - Меняет язык локализации, автоопределение по умолчанию
/memo - Запомнить пожелание
/style - Стиль ответов, роль
/undo - Стереть только последний запрос
/force - Изменить последний ответ бота
/name - Меняет кодовое слово для обращения к боту (только русские и английские буквы и цифры после букв, не больше 10 всего) это нужно только в публичных чатах что бы бот понимал что обращаются к нему
/sum - пересказать содержание ссылки, кратко
/sum2 - То же что и /sum но не берет ответы из кеша, повторяет запрос заново
/calc - Численное решение математических задач
/transcribe - Сделать субтитры из аудио
/ytb - Скачать аудио с ютуба
/temperature - Уровень креатива llm от 0 до 2
/mem - Показывает содержимое своей памяти, диалога
/save - Сохранить диалог в формате msoffice и маркдаун. если отправить боту такой маркдаун с подписью load то бот загрузит диалог из него
/purge - Удалить мои логи
/openrouter - Выбрать модель от openrouter.ai особая команда для настройки openrouter.ai
/id - показывает телеграм id чата/привата то есть юзера
/remove_keyboard - удалить клавиатуру под сообщениями
/keys - вставить свои API ключи в бота (бот может использовать API ключи юзера)
/stars - donate telegram stars. после триального периода бот работает если юзер принес свои ключи или дал звезды телеграма (криптовалюта такая в телеграме)
/report - сообщить о проблеме с ботом
/trans <text to translate> - сделать запрос к внешним сервисам на перевод текста
/google <search query> - сделать запрос к внешним сервисам на поиск в гугле (используются разные движки, google тут просто синоним поиска)

Команды которые может использовать и юзер и сам ассистент по своему желанию:
/img <image description prompt> - сделать запрос к внешним сервисам на рисование картинок
    эта команда генерирует несколько изображений сразу всеми доступными методами но можно и конкретизировать запрос
        /bing <prompt> - будет рисовать только с помощью Bing image creator
        /flux <prompt> - будет рисовать только с помощью Flux
        /gem <1-4> <prompt> - будет рисовать только с помощью Gemini
/tts <text to say> - сделать запрос к внешним сервисам на голосовое сообщение. Юзер может поменять голос в настройках `/command`

Если юзер отправляет боту картинку с подписью то подпись анализируется и либо это воспринимается на запрос на редактирование картинки либо как на ответ по картинке, то есть бот может редактировать картинки, для форсирования этой функции надо в начале подписи использовать восклицательный знак.

Если юзер отправляет в телеграм бота картинки, голосовые сообщения, аудио и видеозаписи, любые документы и файлы то бот переделывает всё это в текст что бы ты (ассистент) мог с ними работать как с текстом.

В боте есть функция перевода документов, чот бы перевести документ юзеру надо отправить документ с подписью !tr <lang> например !lang ru для перевода на русский

Если юзер отправит ссылку или текстовый файл в личном сообщении, бот попытается извлечь и предоставить краткое содержание контента.
После загрузки файла или ссылки можно будет задавать вопросы о файле, используя команду /ask или знак вопроса в начале строки
Результаты поиска в гугле тоже сохранятся как файл.

Если юзер отправит картинку без подписи(инструкции что делать с картинкой) то ему будет предложено меню с кнопками
    Дать описание того что на картинке
    Извлечь весь текст с картинки используя llm
    Извлечь текст и зачитать его вслух
    Извлечь текст и написать художественный перевод
    Извлечь текст не используя llm с помощью ocr
    Сделать промпт для генерации такого же изображения
    Решить задачи с картинки
    Прочитать куаркод
    Повторить предыдущий запрос набранный юзером (если юзер отправил картинку без подписи и потом написал что с ней делать то это будет запомнено)

У бота есть ограничения на размер передаваемых файлов, ему можно отправить до 20мб а он может отправить юзеру до 50мб.
Для транскрибации более крупных аудио и видеофайлов есть команда /transcribe с отдельным загрузчиком файлов.

Бот может работать в группах, там его надо активировать командой /enable@<bot_name> а для этого сначала вставить
свои API ключи в приватной беседе командой /keys.
В группе есть 2 режима работы, как один из участников чата - к боту надо обращаться по имени, или как
симуляции привата, бот будет отвечать на все сообщения отправленные юзером в группу.
Второй режим нужен что бы в телеграме иметь опыт использования похожий на оригинальный сайт чатгпт,
юзеру надо создать свою группу, включить в ней темы (threads) и в каждой теме включить через настройки
/config режим автоответов, и тогда это всё будет выглядеть и работать как оригинальный сайт чатгпт с вкладками-темами
в каждой из которых будут свои отдельные беседы и настройки бота.

Группа поддержки в телеграме: https://t.me/kun4_sun_bot_support
Веб сайт с открытым исходным кодом для желающих запустить свою версию бота: https://github.com/theurs/tb1
'''

    return help_msg
