#!/usr/bin/env python3

import pickle
import threading
import time

import cfg
import my_gemini
import my_groq
import my_db
import my_ddg
from utils import async_run_with_limit


PRINT_LOCK = threading.Lock()


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
    'af', 'am', 'ar', 'ar2', 'ar3', 'ar4', 'ar5', 'ar6', 'ar7', 'ar8'
    'ar9', 'ar10', 'ar11', 'ar12', 'ar13', 'ar14', 'ar15', 'ar16', 'az', 'bg'
    'bn', 'bn2', 'bs', 'ca', 'cs', 'cy', 'da', 'de', 'de2', 'de3'
    'de4', 'de5', 'el', 'en', 'en2', 'en3', 'en4', 'en5', 'en6', 'en7'
    'en8', 'en9', 'en10', 'en11', 'en12', 'en13', 'en14', 'en15', 'en16', 'en17'
    'en18', 'en19', 'en20', 'en21', 'en22', 'en23', 'en24', 'en25', 'es', 'es2'
    'es3', 'es4', 'es5', 'es6', 'es7', 'es8', 'es9', 'es10', 'es11', 'es12'
    'es13', 'es14', 'es15', 'es16', 'es17', 'es18', 'es19', 'es20', 'es21', 'es22'
    'es23', 'et', 'fa', 'fi', 'fil', 'fr', 'fr2', 'fr3', 'fr4', 'fr5'
    'fr6', 'fr7', 'fr8', 'ga', 'gl', 'gu', 'he', 'hi', 'hr', 'hu'
    'id', 'is', 'it1', 'it2', 'it3', 'iu', 'iu2', 'ja', 'jv', 'ka'
    'kk', 'km', 'kn', 'ko1', 'ko2', 'lo', 'lt', 'lv', 'mk', 'ml'
    'mn', 'mr', 'ms', 'mt', 'my', 'nb', 'ne', 'nl', 'nl2', 'nl3'
    'pl', 'ps', 'pt1', 'pt2', 'pt3', 'ro', 'ru', 'si', 'sk', 'sl'
    'so', 'sq', 'sr', 'su', 'sv', 'sw', 'sw2', 'ta', 'ta2', 'ta3'
    'ta4', 'te', 'th', 'tr', 'uk', 'ur', 'ur2', 'uz', 'vi', 'zh'
    'zh2', 'zh3', 'zh4', 'zh5', 'zh6', 'zh7', 'zh8', 'zu'
]


PROMPT_DESCRIBE = 'Provide a detailed description of everything you see in the image. Break down long responses into easy-to-read paragraphs. Use markdown formatting to make it look good.'
PROMPT_COPY_TEXT = 'Copy all the text from this image, save it as is - do not translate. Maintain the original formatting (except for line breaks, which should be corrected).'

PROMPT_COPY_TEXT_TTS = '''Copy all the text from this image. Preserve the original formatting, including line breaks. Never translate the text, keep original languages in text! Rewrite the text for TTS reading:

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



PROMPT_COPY_TEXT_TR = 'Provide a high-quality artistic translation of all texts from this image into my language (the language of this TEXT request). Format the output using Markdown, correcting any line breaks.'
PROMPT_REPROMPT = 'Write an image generation prompt as if you were an expert prompt engineer. 50-300 words. Format your response as follows:'
# PROMPT_SOLVE = 'Solve all problems presented in the image. Show your step-by-step solution and clearly indicate the final answer. Rewrite latex expressions with unicode symbols with no markdown in it.'
PROMPT_SOLVE = "Solve all problems presented in the image. Rewrite LaTeX expressions with Unicode symbols (no markdown), if any. Don't mention the rewrite in the answer."
PROMPT_QRCODE = 'Read QRCODE.'


start_msg = '''Hello, I'm an AI chat bot. I'm here to help you with anything you need.

✨ Access to all text AIs
🎨 Picture drawing
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

🎙️ You can issue commands and make requests using voice messages.

👻 `/purge` command to remove all your data


This bot utilizes only free models. However, if you wish to utilize all other models within this bot, you can create a paid account on the website https://openrouter.ai and insert the API key from that site into this bot.

This will grant you access to all commercial models at manufacturer prices, or even cheaper.

You can create an API key here: https://openrouter.ai/settings/keys

View the list of available models here: https://openrouter.ai/models

Use the command `/openrouter <API key>` to insert your key.

Use the command `/openrouter` to view settings and switch to this mode.

Use the command `/model <model name>` to select a model, for example, `/model openai/o1-preview` will select the o1-preview model from OpenAI.


Report issues on Telegram:
https://t.me/kun4_sun_bot_support

"""

start_msg_file = 'msg_hello.dat'
help_msg_file = 'msg_help.dat'

# команды для администратора
admin_help = '''
/ping - ping bot no dependency
/gmodels - list of gemini models

/tgui - localization fix
/create_all_translations - create translation cache
/init - recreate telegram info (bot name, description, menu commands)

/vacuum - drop large gemini dialogs and users files

/sdonate - add or remove stars for a user, it will only be visible in the log that they are virtual

/reset <id> - reset mem for user
/alang - set language for specific user
/set_stt_mode - mandatory switch user from one stt engine to another
/set_chat_mode - mandatory switch user from one chatbot to another
/addkeys - add gemini API keys for a user for them
/reset_gemini2 - reset gemini memory for specific chat
/style2 - change style for specific chat
/drop_subscription - drop user subscription

/think, /th - `gemini_2_flash_thinking`
/flash, /f - `gemini`
/code, /c - `codestral`
Usage: /<command> <user_id>

/downgrade - downgrade llm model for free users mandatory

/disable_chat_mode - mandatory switch <b>all</b> users from one chatbot to another

/kc - clear bing cookies
/k - set bing cookies

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


def get_hidden_prompt_for_user(message, chat_id_full, bot_name, lang_of_user, formatted_date):
    hidden_text = (
                    f'[Info to help you answer. You are a telegram chatbot named "{bot_name}", '
                    f'you are working in chat named "{message.chat.title}", your memory limited to last 20 messages, '
                    'you need a user`s api keys or telegram stars for working (/keys for more info), '
                    'user have telegram commands (/img - image generator, /bing - bing image creator, /hf - huggingface image generator, /tts - text to speech, /reset - clear chat context, '
                    '/trans - translate, /sum - summarize, /google - search, /ytb - download mp3 from youtube, you can answer voice messages, '
                    'images, documents, urls(any text and youtube subs)) and you can use it yourself, you cannot do anything in the background, '
                    'you can OCR image, transcribe audio, read and answer many types document files, translate documents, read text from url, '
                    'you are using different neural networks for work and the user can configure these networks with the /config command and see details with the /id command, '
                    f'user name is "{message.from_user.full_name}", user language code is "{lang_of_user}" '
                    f'but it`s not important, your current date is "{formatted_date}", do not address the user by name and '
                    "no emoji unless it is required, rewrite LaTeX expressions with Unicode symbols (no markdown), if any, don't mention the rewrite in the answer, "
                    'you can generate images with the /img command, type /img "prompt" to generate an image for user, '
                    'you can google search with the /google command, type /google "question" to get the answer for user, '
                    'you can summarize text with the /sum command, type /sum URL to get the summary for user, '
                    'you can say your answer with voice message with the /tts command, type /tts <2 letter language code> TEXT to answer to user with voice, '
                    "provide the best possible answer to the user's request, improvising if needed, "
                    f'{"your special role here is " + my_db.get_user_property(chat_id_full, "role") + ", " if my_db.get_user_property(chat_id_full, "role") else ""}'
                )

    return hidden_text


def get_hidden_prompt_for_group(message, chat_id_full, bot_name, lang, formatted_date):
    hidden_text = (
                    f'[Info to help you answer. You are a telegram chatbot named "{bot_name}", '
                    f'you are working in private for user named "{message.from_user.full_name}", your memory limited to last 20 messages, '
                    'you need a user`s api keys or telegram stars for working (/keys for more info), '
                    'user have telegram commands (/img - image generator, /bing - bing image creator, /hf - huggingface image generator, /tts - text to speech, /reset - clear chat context, '
                    '/trans - translate, /sum - summarize, /google - search, /ytb - download mp3 from youtube, you can answer voice messages, '
                    'images, documents, urls(any text and youtube subs)) and you can use it yourself, you cannot do anything in the background, '
                    'you can OCR image, transcribe audio, read and answer many types document files, translate documents, read text from url, '
                    'you are using different neural networks for work and the user can configure these networks with the /config command and see details with the /id command, '
                    f'user language code is "{lang}" but it`s not important, your current date is "{formatted_date}", do not address the user by name and '
                    "no emoji unless it is required, rewrite LaTeX expressions with Unicode symbols (no markdown), if any, don't mention the rewrite in the answer, "
                    'you can generate images with the /img command, type /img "prompt" to generate an image for user, '
                    'you can google search with the /google command, type /google "question" to get the answer for user, '
                    'you can summarize text with the /sum command, type /sum URL to get the summary for user, '
                    'you can say your answer with voice message with the /tts command, type /tts <2 letter language code> TEXT to answer to user with voice, '
                    "provide the best possible answer to the user's request, improvising if needed, "
                    f'{"your special role here is " + my_db.get_user_property(chat_id_full, "role") + ", " if my_db.get_user_property(chat_id_full, "role") else ""}'
                )

    return hidden_text


def get_hidden_prompt_for_llama(tr, lang):
    return tr(f"Answer in '{lang}' language, do not address the user by name and no emoji unless it is required. Rewrite LaTeX expressions with Unicode symbols (no markdown), if any. Don't mention the rewrite in the answer.", lang)


def get_img2txt_prompt(tr, lang):
    return tr(f"Answer in '{lang}' language, if not asked other. Rewrite LaTeX expressions with Unicode symbols (no markdown), if any. Don't mention the rewrite in the answer.", lang)


def generate_start_msg():
    msgs = {}
    for x in supported_langs_trans:
    # for x in ['ru', 'uk', 'de']:
        msg = ''

        if not msg:
            msg = my_gemini.translate(start_msg, from_lang='en', to_lang=x, help='It is a /start message for telegram chat bot. Keep the formatting.')
        if not msg:
            msg = my_groq.translate(start_msg, from_lang='en', to_lang=x, help='It is a /start message for telegram chat bot. Keep the formatting.')
        if not msg:
            msg = start_msg
        if msg:
            msgs[x] = msg
            print('\n\n', x, '\n\n', msg)
        if not msg:
            print(f'google translate failed {x}')

    with open(start_msg_file, 'wb') as f:
        pickle.dump(msgs, f)


@async_run_with_limit(1)
def translate_help_msg(msg_source: str, source: str, target: str, container: dict):
    msg = my_gemini.translate(msg_source, from_lang=source, to_lang=target, help='It is a /help message for telegram chat bot. Keep the formatting.')
    if not msg:
        msg = my_groq.translate(msg_source, from_lang=source, to_lang=target, help='It is a /help message for telegram chat bot. Keep the formatting.')
    if msg:
        container[target] = msg
    else:
        with PRINT_LOCK:
            print(f'google translate failed {target}')
        container[target] = msg_source
    time.sleep(5)


def generate_help_msg():
    container = {}

    for x in supported_langs_trans:
        translate_help_msg(help_msg, 'en', x, container)

    while len(container) < len(supported_langs_trans):
        time.sleep(1)

    with open(help_msg_file, 'wb') as f:
        pickle.dump(container, f)


def regenerate_help_msg(langs):
    if isinstance(langs, str):
        langs = [langs, ]

    with open(help_msg_file, 'rb') as f:
        msgs = pickle.load(f)

    missing = [x for x in supported_langs_trans if x not in msgs.keys()]
    print(missing)

    for x in langs:
        msg = my_gemini.translate(help_msg, from_lang='en', to_lang=x, help='It is a /help message for telegram chat bot. Keep the formatting.')
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
            msg = my_gemini.translate(
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
        translated = my_gemini.translate(original, to_lang=lang, model = cfg.gemini_pro_model)
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
    my_gemini.load_users_keys()

    # with open(help_msg_file, 'rb') as f:
    #     d = pickle.load(f)
    # d['pt-br'] = d['pt']
    # with open(help_msg_file, 'wb') as f:
    #     pickle.dump(d, f)

    # generate_start_msg()

    # generate_help_msg()

    # regenerate_help_msg(('zu', 'sw'))
    # regenerate_start_msg('en')

    my_db.close()
