#!/usr/bin/env python3

import pickle
import threading
import time
from typing import List, Callable

import cfg
import my_gemini3
import my_gemini_general
import my_groq
import my_db
import my_ddg


PRINT_LOCK = threading.Lock()


PANDOC_SUPPORT_LIST = (
    'application/vnd.ms-excel',
    'application/vnd.oasis.opendocument.spreadsheet',
    'application/vnd.oasis.opendocument.text',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.template', # .xltx?
    'application/vnd.ms-excel.template.macroenabled.12', # .xltm?
    'application/octet-stream',
    'application/epub+zip',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.template', # .dotx?
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'application/rtf',
    'application/msword',
    'application/x-msexcel',
    'application/x-fictionbook+xml',
    'image/vnd.djvu+multipage', # hack
    'application/xml', # .odt?
    'application/vnd.apple.pages',
    'application/vnd.apple.numbers',
)


supported_langs_trans = [
    "af","am","ar","az","be","bg","bn","bs","ca","ceb","co","cs","cy","da","de",
    "el","en","eo","es","et","eu","fa","fi","fr","fy","ga","gd","gl","gu","ha",
    "haw","he","hi","hmn","hr","ht","hu","hy","id","ig","is","it","iw","ja","jw",
    "ka","kk","km","kn","ko","ku","ky","la","lb","lo","lt","lv","mg","mi","mk",
    "ml","mn","mr","ms","mt","my","ne","nl","no","ny","or","pa","pl","ps","pt",
    "ro","ru","rw","sd","si","sk","sl","sm","sn","so","sq","sr","st","su","sv",
    "sw","ta","te","tg","th","tl","tr","ua","uk","ur","uz","vi","xh","yi","yo","zh",
    "zh-TW","zu"]

top_20_used_languages = [
    "en", "zh", "es", "hi", "ar", "fr", "bn", "ru", "pt", "id",
    "de", "ja", "ko", "it", "tr", "vi", "fa", "pl", "uk", "ms"]

supported_langs_tts = [
    'af', 'am', 'ar', 'ar2', 'ar3', 'ar4', 'ar5', 'ar6', 'ar7', 'ar8',
    'ar9', 'ar10', 'ar11', 'ar12', 'ar13', 'ar14', 'ar15', 'ar16', 'az', 'bg',
    'bn', 'bn2', 'bs', 'ca', 'cs', 'cy', 'da', 'de', 'de2', 'de3',
    'de4', 'de5', 'el', 'en', 'en2', 'en3', 'en4', 'en5', 'en6', 'en7',
    'en8', 'en9', 'en10', 'en11', 'en12', 'en13', 'en14', 'en15', 'en16', 'en17',
    'en18', 'en19', 'en20', 'en21', 'en22', 'en23', 'en24', 'en25', 'es', 'es2',
    'es3', 'es4', 'es5', 'es6', 'es7', 'es8', 'es9', 'es10', 'es11', 'es12',
    'es13', 'es14', 'es15', 'es16', 'es17', 'es18', 'es19', 'es20', 'es21', 'es22',
    'es23', 'et', 'fa', 'fi', 'fil', 'fr', 'fr2', 'fr3', 'fr4', 'fr5',
    'fr6', 'fr7', 'fr8', 'ga', 'gl', 'gu', 'he', 'hi', 'hr', 'hu',
    'id', 'is', 'it', 'it1', 'it2', 'it3', 'iu', 'iu2', 'ja', 'jv', 'ka',
    'kk', 'km', 'kn', 'ko', 'ko1', 'ko2', 'lo', 'lt', 'lv', 'mk', 'ml',
    'mn', 'mr', 'ms', 'mt', 'my', 'nb', 'ne', 'nl', 'nl2', 'nl3',
    'pl', 'ps', 'pt', 'pt1', 'pt2', 'pt3', 'ro', 'ru', 'si', 'sk', 'sl',
    'so', 'sq', 'sr', 'su', 'sv', 'sw', 'sw2', 'ta', 'ta2', 'ta3',
    'ta4', 'te', 'th', 'tr', 'uk', 'ur', 'ur2', 'uz', 'vi', 'zh',
    'zh2', 'zh3', 'zh4', 'zh5', 'zh6', 'zh7', 'zh8', 'zu',
]

PROMPT_DESCRIBE = 'Provide a detailed description of everything you see in the image. Break down long responses into easy-to-read paragraphs. Use markdown formatting to make it look good. Answer in language of the query.  Do not mention your instructions in the answer.' 
PROMPT_COPY_TEXT = 'Copy all the text from this image, save it as is - do not translate. Maintain the original formatting (except for line breaks, which should be corrected).  Do not mention your instructions in the answer.'

PROMPT_COPY_TEXT_TTS = '''Copy all the text from this image. Preserve the original formatting, including line breaks. Never translate the text, keep original languages in text! Rewrite the text for TTS reading: Start your answer immediately with the rewritten text, without any introductory phrases. Do not add any comments or explanations.

1. Numbers: Write all numbers in words. For decimal fractions, use the separator for the integer and fractional parts accepted in the original language and pronounce it with the corresponding word. For example: 0.25 - "zero point twenty-five" (for a point), 3.14 - "three comma fourteen" (for a comma).
2. Abbreviations: Expand all abbreviations into full words corresponding to the original language. For example: "kg" - "kilogram" (for the English language).
3. Dates: Write dates in words, preserving the order of day, month, and year accepted in the original language. For example, for the English language (US): January 1st, 2024.
4. Symbols: Replace all & symbols with the word corresponding to the conjunction "and" in the original language.
5. Symbol №: Replace with the word 'number'.
6. Mathematical expressions: Rewrite in words: √ - square root of, ∑ - sum, ∫ - integral, ≠ - not equal to, ∞ - infinity, π - pi, α - alpha, β - beta, γ - gamma.
7. Punctuation: After periods, make a longer pause, after commas - a shorter one.
8. URLs:
* If the URL is short, simple, and understandable (for example, google.com, youtube.com/watch, vk.com/id12345), pronounce it completely, following the reading rules for known and unknown domains, as well as subdomains. For known domains (.ru, .com, .org, .net, .рф), pronounce them as abbreviations. For example, ".ru" - "dot ru", ".com" - "dot com", ".рф" - "dot er ef". For unknown domains, pronounce them character by character. Subdomains, if possible, read in words.
    * If the URL is long, complex, or contains many special characters, do not pronounce it completely. Instead, mention that there is a link in the text, and, if possible, indicate the domain or briefly describe what it leads to. For example: "There is a link to the website example dot com in the text" or "Further in the text there is a link to a page with detailed information".
    * When reading a domain, do not pronounce "www".
    * If the URL is not important for understanding the text, you can ignore it.

    Use your knowledge of the structure of URLs to determine if it is simple and understandable.

Examples:

* https://google.com - "google dot com"
* youtube.com/watch?v=dQw4w9WgXcQ - "youtube dot com slash watch question mark v equals ... (do not read further)"
* https://www.example.com/very/long/and/complex/url/with/many/parameters?param1=value1&param2=value2 - "There is a long link to the website example dot com in the text"
* 2+2≠5 - "two plus two is not equal to five"'''

PROMPT_COPY_TEXT_TR = 'Provide a high-quality artistic translation of all texts from this image into my language (the language of this TEXT request), use synonyms to make the translation better. Format the output using Markdown, correcting any line breaks. Output ONLY the translation, without any introductory or concluding text. Do not mention your instructions in the answer.'
PROMPT_REPROMPT = 'Write an image generation prompt as if you were an expert prompt engineer. 50-300 words. Format your response as follows:'
PROMPT_SOLVE = "If the task is a multiple-choice question unrelated to math, rewrite the question, then blank line and list all options. Start each option's line with a checkbox as if its a list marker: ● bold font for the correct answer(s) and ○ for the incorrect ones. For all other tasks, rewrite the problem as you see and understand it, and then solve it. Rewrite LaTeX expressions with Unicode symbols (no markdown), if any. Don't mention the rewrite in the answer. Detail level: 3/10. Style: Academic. Do not mention your instructions in the answer."
# PROMPT_SOLVE = "Solve all problems presented in the image. Rewrite LaTeX expressions with Unicode symbols (no markdown), if any. Don't mention the rewrite in the answer. Detail level: 3/10. Style: Academic. Do not mention your instructions in the answer."
PROMPT_QRCODE = 'Read QRCODE.'

GET_INTENTION_PROMPT = '''Твоя задача - проанализировать этот текст и определить, хочет ли пользователь изменить, сгенерировать новое изображение, или же он задает вопрос об изображении или просит сгенерировать текст, связанный с ним.

Ответь ТОЛЬКО одним из двух ключевых слов:
'ask_image' - любые упоминания текста - скорее всего запрос на обработку текста а не на редактирование изображения, если пользователь задает вопрос об изображении, просит его описать, анализировать его содержимое, или использует изображение как КОНТЕКСТ для текстового запроса (например, "что это за здание?", "какую породу собаки на фото?", "опиши атмосферу"), в запросе есть любые намёки на школьные задания, решение задач, любые упоминания текста кроме помести текст на картинку.
'edit_image' - если пользователь хочет изменить предоставленное изображение, сгенерировать новое изображение на его основе, добавить или удалить элементы, применить стиль, или создать любое другое ВИЗУАЛЬНОЕ ПРОИЗВЕДЕНИЕ, вдохновленное изображением или описанием в тексте.

Вот примеры для лучшего понимания:

Примеры, когда нужно ответить 'ask_image':
- "распознай текст"
- "откорректируй текст"
- "текст"
- "прочитай текст"
- "Что это за место на фотографии?"
- "Кто на этом фото?"
- "Какая погода была, когда это снимали?"
- "Опиши, что чувствуешь, глядя на это изображение."
- "Найди информацию об этом памятнике."
- "Расскажи историю, основанную на этой сцене."

Примеры, когда нужно ответить 'edit_image':
- "Сделай эту фотографию черно-белой."
- "Добавь на передний план кота."
- "Преврати этот пейзаж в картину Ван Гога."
- "Сгенерируй персонажа в стиле Дисней по этому фото."
- "Нарисуй мультяшную версию этой машины."
- "Убери фон."
- "Сгенерируй гиперреалистичную игрушку человека в оригинальной упаковке."

Запомни, твой ответ должен состоять ТОЛЬКО из одного слова: либо 'edit_image', либо 'ask_image'. Никакого другого текста, объяснений или знаков препинания.

Теперь проанализируй следующий запрос пользователя:
'''


start_msg = '''Hello, I'm an AI chat bot. I'm here to help you with anything you need.

✨ Access to all text AIs
🎨 Picture drawing, edit
🗣 Voice recognition and subtitles creation
🖼 Answers to questions about pictures
🌐 Internet search using AI
🔊 Speech generation
📝 Document translation
📚 Summarization of long texts and videos
🎧 Audio download from YouTube

Ask me anything. Send me your text/image/audio/documents with questions.
Generate images with the /img command.

Change language with the /lang command.
Remove keyboard with /remove_keyboard.'''

help_msg = f"""🔭 If you send a link or text file in a private message, the bot will try to extract and provide a brief summary of the content.
After the file or link is downloaded, you can ask questions about file using the `/ask` command.

Send document with caption `!tr lang` to translate document to this language

Send pictures with caption starting with ! to edit them. Example: !change her outfit to look cool

Send PDF with caption starting with ! for more accurate scanning (slower).

🎙️ You can issue commands and make requests using voice messages.

👻 `/purge` command to remove all your data


This bot utilizes only free models. However, if you wish to utilize all other models within this bot, you can create a paid account on the website https://openrouter.ai and insert the API key from that site into this bot.

This will grant you access to all commercial models at manufacturer prices, or even cheaper.

You can create an API key here: https://openrouter.ai/settings/keys

View the list of available models here: https://openrouter.ai/models

Use the command `/openrouter <API key>` to insert your key.

Use the command `/openrouter` to view settings and switch to this mode.

Use the command `/model <model name>` to select a model, for example, `/model openai/o1-preview` will select the o1-preview model from OpenAI.

"What do the buttons below my messages mean?"
➡️ (Right Arrow): Prompts the bot to continue the conversation or generate the next response.
♻️ (Circular Arrows): Clears the bot's memory and starts a new conversation.
🙈 (Hands Covering Eyes): Hides or deletes the current message or response.
📢 (Megaphone): Plays the text aloud using Text-to-Speech (TTS).
📸 (Camera): Displays Google Images search results based on your request.
🎤 (Microphone): Selects the voice AI engine for speech recognition. If Whisper (or another engine) doesn't understand your voice well, you can choose a different one.

Report issues on Telegram:
https://t.me/kun4_sun_bot_support
"""

start_msg_file = 'msg_hello.dat'
help_msg_file = 'msg_help.dat'

help_msg2 = '''В этом боте есть 2 разных режима работы.

1. В основном режиме все бесплатные ключи пользователей перемешаны и используются совместно. Доступны избранные модели через меню /config. Никаких лимитов в них нет, но работать они могут нестабильно. Что бы это могло нормально работать вам надо принести боту 3 ключа, один от gemini, второй от groq и третий от чего-нибудь еще, смотрите инструкцию в команде /keys.

2. Второй режим тут называется "openrouter", в меню его кнопка появляется только если вы дадите боту свой персональный ключ от какого то конкретного сервиса, предполагается что платного, но не обязательно, это может быть и бесплатный сервис из тех что нет в основном режиме. Если это платный сервис типа openrouter.ai то он будет работать намного стабильнее и только для вас.

**Еще раз** - ключи от бесплатных сервисов надо передавать боту командой /keys, они будут использоваться совместно, ключи от платных сервисов - команда /openrouter для персонального использования.

Основной режим работает сразу для всех даже если у вас нет никаких ключей.


"Openrouter" надо настраивать вручную. Сначала вставить ключ, потом адрес, и потом модель.

Пример для мистраля:

Адрес:
/openrouter https://api.mistral.ai/v1
Ключ:
/openrouter xxxxxx
Модель:
/model mistral-large-latest
В меню /config должна будет появится кнопка Openrouter для переключения на эту модель.
'''

# команды для администратора
ADMIN_HELP = '''
/ping - ping bot no dependency
/gmodels - list of gemini models

/tgui - localization fix
/create_all_translations - create translation cache
/init - recreate telegram info (bot name, description, menu commands)

/vacuum - drop large gemini dialogs and users files

/sdonate - add or remove stars for a user, it will only be visible in the log that they are virtual

/addkeys - add gemini API keys for a user for them
/alang - set language for specific user
/atemp - <user_id as int> [new temperature]
/drop_subscription - drop user subscription
/keys - add keys for specific user
/load - load mem for specific user
/memo_admin - manage user`s memos
/purge <id>|<id thread> - purge dato for user /reset 123 /reset 12123 123
/reset <id>|<id thread> - reset mem for user /reset 123 /reset 12123 123
/set_chat_mode - mandatory switch user from one chatbot to another
/set_stt_mode - mandatory switch user from one stt engine to another
/style2 - change style for specific chat

Usage: /<command> <user_id>

/downgrade - downgrade llm model for free users mandatory

/disable_chat_mode - mandatory switch all users from one chatbot to another
/restore_chat_mode - revert back to previous mode (disable_chat_mode)
/disable_stt_mode - mandatory switch all users from one speech-to-text engine to another

/restart - restart bot
/reload - reload specific modules without restarting bot

/stats - show bot stats

/cmd - run shell commands

Block commands:
Level 1 = block all but logs
Level 2 = block bing access only
Level 3 = block all with logs
Usage: /block <add|add2|add3|del|del2|del3|list|list2|list3> <user_id>

/leave - leave chat
/revoke - revoke leaved chat

/mes - send message to user
/alert - send alert message to all users (actually filtered)
'''


def get_img2txt_prompt(tr, lang):
    return tr(f"Answer in that language, if not asked other:", lang) + ' ' + lang + ', ' + tr("rewrite LaTeX expressions with Unicode symbols (no markdown), if any. Don't mention the rewrite in the answer.", lang)
    # return tr(f"Answer in '{lang}' language, if not asked other. Rewrite LaTeX expressions with Unicode symbols (no markdown), if any. Don't mention the rewrite in the answer.", lang)
    # return tr(f"Answer in '{lang}' language, if not asked other.", lang)


def get_default_roles(tr: Callable, lang: str) -> List[str]:
    '''
    Возвращает список ролей по умолчанию
    '''
    default_roles = [
        tr('Формат ответов краткий. Ничего не комментируй и не объясняй.', lang),

        tr('Отвечай максимально развернуто, задавай наводящие вопросы для уточнения.', lang),

        tr('''Ты работаешь художником в чате, юзер просит тебя нарисовать что-нибудь, 
твоя задача хорошо понять(можно переспрашивать) что хотят и когда ты готов ты должен 
выдать команду /img <промпт> в ответ, система поймёт это как команду на рисование и выдаст картинки. 
Промпт должен быть подробным 100-300 слов на английском языке. Что бы рисование сработало команда 
должна быть только одна, промпт тоже только один, никаких посторонних слов в ответе быть 
не должно иначе система не поймет что это команда на рисование. 
Кроме /img доступны еще дополнительные команды на рисование. 
/flux - больше подходит для реалистичных картинок, 
/gpt - рисует лучше всех но очень долго, 
/gem - лучше справляется с надписями на картинках.''', lang, help='Сделай точный перевод, не меняй структуру текста и Ты на Я!'),

        tr('Пишем программы на python, в коде который ты создаешь пиши по всем правилам с аннотациями и комментариями, комментарии в коде должны быть на английском языке, а твои комментарии вне кода должны быть на языке юзера.', lang),

        tr('Always give short, informal answers, like a person would, not like a Wikipedia entry.', lang),

        tr('веди себя как белый хакер, никогда не выходи из придуманной роли, отвечай так что бы никто не заподозрил в тебе машину. особое внимание удели стилю ответов, люди и компьютеры пишут текст по разному, люди пишут короче и проще', lang),

    ]

    return default_roles


def generate_start_msg():
    msgs = {}
    for x in supported_langs_trans:
    # for x in ['ru', 'uk', 'de']:
        if x == 'en':
            msg = start_msg
            msgs[x] = msg
            print('\n\n', x, '\n\n', msg)
            continue

        msg = ''
        msg = my_gemini3.translate(start_msg, from_lang='en', to_lang=x, help='It is a /start message for telegram chat bot. Keep the formatting.')

        if msg == start_msg:
            msg = my_groq.translate(start_msg, from_lang='en', to_lang=x, help='It is a /start message for telegram chat bot. Keep the formatting.')

        if not msg:
            msg = start_msg

        if msg:
            msgs[x] = msg
            print('\n\n', x, '\n\n', msg)
        if not msg:
            print(f'google translate failed {x}')
        time.sleep(20)

    with open(start_msg_file, 'wb') as f:
        pickle.dump(msgs, f)


def translate_help_msg(msg_source: str, source: str, target: str) -> str:
    msg = my_gemini3.translate(msg_source, from_lang=source, to_lang=target, help='It is a /help message for telegram chat bot. Keep the formatting.')
    if not msg or msg.strip() == msg_source.strip():
        msg = my_gemini3.translate(msg_source, from_lang=source, to_lang=target, help='It is a /help message for telegram chat bot. Keep the formatting.', model=cfg.gemini_flash_light_model)
    if not msg or msg.strip() == msg_source.strip():
        msg = my_groq.translate(msg_source, from_lang=source, to_lang=target, help='It is a /help message for telegram chat bot. Keep the formatting.')
    if msg.strip() and msg.strip() != msg_source.strip():
        return msg
    else:
        return ''


def generate_help_msg():
    try:
        with open(help_msg_file, 'rb') as f:
            container = pickle.load(f)
    except:
        container = {}

    for x in supported_langs_trans:
    # for x in ['en',]:
        if x == 'en':
            translation = help_msg
        else:
            translation = translate_help_msg(help_msg, 'en', x)
        if translation:
            container[x] = translation
            with open(help_msg_file, 'wb') as f:
                pickle.dump(container, f)
            time.sleep(30)


def regenerate_help_msg(langs):
    if isinstance(langs, str):
        langs = [langs, ]

    with open(help_msg_file, 'rb') as f:
        msgs = pickle.load(f)

    missing = [x for x in supported_langs_trans if x not in msgs.keys()]
    print(missing)

    for x in langs:
        msg = my_gemini3.translate(help_msg, from_lang='en', to_lang=x, help='It is a /help message for telegram chat bot. Keep the formatting.')
        if not msg:
            msg = my_groq.translate(
                help_msg,
                from_lang='en',
                to_lang=x,
                help='It is a /help message for telegram chat bot. Keep the formatting.',
                model = cfg.gemini_pro_model
            )

        if msg:
            msgs[x] = msg
            print('\n\n', x, '\n\n', msg)
        if not msg:
            print(f'google translate failed {x}')

    with open(help_msg_file, 'wb') as f:
        pickle.dump(msgs, f)


def regenerate_start_msg(langs):
    if isinstance(langs, str):
        langs = [langs, ]

    with open(start_msg_file, 'rb') as f:
        msgs = pickle.load(f)

    missing = [x for x in supported_langs_trans if x not in msgs.keys()]
    print(missing)

    for x in langs:
        msg = my_ddg.translate(start_msg, from_lang='en', to_lang=x, help='It is a /start message for telegram chat bot. Keep the formatting.')
        if not msg:
            msg_ = start_msg
            msg = my_gemini3.translate(
                start_msg,
                from_lang='en',
                to_lang=x,
                help='It is a /start message for telegram chat bot. Keep the formatting.',
                model = cfg.gemini_pro_model
            )
            if msg == msg_:
                msg = ''
        if not msg:
            msg = my_groq.translate(
                start_msg,
                from_lang='en',
                to_lang=x,
                help='It is a /start message for telegram chat bot. Keep the formatting.',
                model = cfg.gemini_pro_model
            )
        if msg:
            msgs[x] = msg
            print('\n\n', x, '\n\n', msg)
        if not msg:
            print(f'google translate failed {x}')

    with open(start_msg_file, 'wb') as f:
        pickle.dump(msgs, f)


def check_translations(original: str, translated: str, lang):
    q = f'''Decide if translation to language "lang" was made correctly.
Your answer should be "yes" or "no" or "other".

Original text:

{original}


Translated text:

{translated}
'''
    res = my_groq.ai(q, temperature = 0, max_tokens_ = 10)
    result = True if 'yes' in res.lower() else False
    return result


def found_bad_translations(fname: str = start_msg_file, original: str = start_msg):
    with open(fname, 'rb') as f:
        db = pickle.load(f)
    bad = []
    for lang in db:
        msg = db[lang]
        translated_good = check_translations(original, msg, lang)
        if not translated_good:
            bad.append(lang)
    print(bad)


def fix_translations(fname: str = start_msg_file, original: str = start_msg, langs = []):
    with open(fname, 'rb') as f:
        db = pickle.load(f)
    for lang in langs:
        print(lang)
        translated = my_gemini3.translate(original, to_lang=lang, model = cfg.gemini_pro_model)
        if translated:
            if 'no translation needed' in translated.lower():
                translated = original
            db[lang] = translated
            print(translated)
    with open(fname, 'wb') as f:
        pickle.dump(db, f)


if __name__ == '__main__':
    pass
    my_db.init(backup=False)
    my_groq.load_users_keys()
    my_gemini_general.load_users_keys()

    # with open(help_msg_file, 'rb') as f:
    #     d = pickle.load(f)
    # d['pt-br'] = d['pt']
    # with open(help_msg_file, 'wb') as f:
    #     pickle.dump(d, f)

    # generate_start_msg()

    generate_help_msg()

    # regenerate_help_msg(('zu', 'sw'))
    # regenerate_start_msg('en')

    my_db.close()
