#!/usr/bin/env python3

import pickle

import cfg
import my_gemini
import my_groq
import my_db
import my_ddg
import my_trans


languages_ocr = ["afr", "amh", "ara", "asm", "aze", "aze_cyrl", "bel", "ben", "bod",
                 "bos", "bre", "bul", "cat", "ceb", "ces", "chi_sim", "chi_tra", "chr",
                 "cos", "cym", "dan", "dan_frak", "deu", "deu_frak", "deu_latf", "dzo",
                 "ell", "eng", "enm", "epo", "equ", "est", "eus", "fao", "fas", "fil",
                 "fin", "fra", "frk", "frm", "fry", "gla", "gle", "glg", "grc", "guj",
                 "hat", "heb", "hin", "hrv", "hun", "hye", "iku", "ind", "isl", "ita",
                 "ita_old", "jav", "jpn", "kan", "kat", "kat_old", "kaz", "khm", "kir",
                 "kmr", "kor", "kor_vert", "kur", "lao", "lat", "lav", "lit", "ltz",
                 "mal", "mar", "mkd", "mlt", "mon", "mri", "msa", "mya", "nep", "nld",
                 "nor", "oci", "ori", "osd", "pan", "pol", "por", "pus", "que", "ron",
                 "rus", "san", "sin", "slk", "slk_frak", "slv", "snd", "spa", "spa_old",
                 "sqi", "srp", "srp_latn", "sun", "swa", "swe", "syr", "tam", "tat", "tel",
                 "tgk", "tgl", "tha", "tir", "ton", "tur", "uig", "ukr", "urd", "uzb", "uzb_cyrl",
                 "vie", "yid", "yor",
                 "arab", "armn", "beng", "cans", "cher", "cyrl", "deva", "ethi", "frak", 
                 "geor", "grek", "gujr", "guru", "hans", "hans-vert", "hant", "hant-vert", "hang",
                 "hang-vert", "hebr", "jpan", "jpan-vert", "knda", "khmr", "laoo", "latn", "mlym",
                 "mymr", "orya", "sinh", "syrc", "taml", "telu", "thaa", "thai", "tibt", "viet"]


supported_langs_trans = [
        "af","am","ar","az","be","bg","bn","bs","ca","ceb","co","cs","cy","da","de",
        "el","en","eo","es","et","eu","fa","fi","fr","fy","ga","gd","gl","gu","ha",
        "haw","he","hi","hmn","hr","ht","hu","hy","id","ig","is","it","iw","ja","jw",
        "ka","kk","km","kn","ko","ku","ky","la","lb","lo","lt","lv","mg","mi","mk",
        "ml","mn","mr","ms","mt","my","ne","nl","no","ny","or","pa","pl","ps","pt",
        "ro","ru","rw","sd","si","sk","sl","sm","sn","so","sq","sr","st","su","sv",
        "sw","ta","te","tg","th","tl","tr","ua","uk","ur","uz","vi","xh","yi","yo","zh",
        "zh-TW","zu"]

supported_langs_tts = ['af', 'am', 'ar', 'ar2', 'ar3', 'ar4', 'ar5', 'ar6', 'ar7', 'ar8', 'ar9', 'ar10', 'ar11', 'ar12', 
                       'ar13', 'ar14', 'ar15', 'ar16', 'az', 'bg', 'bn', 'bn2', 'bs', 'ca', 'cs', 'cy', 'da', 'de', 
                       'de2', 'de3', 'de4', 'de5', 'el', 'en', 'en2', 'en3', 'en4', 'en5', 'en6', 'en7', 'en8', 'en9', 
                       'en10', 'en11', 'en12', 'en13', 'en14', 'en15', 'en16', 'en17', 'en18', 'en19', 'en20', 'en21',
                       'en22', 'en23', 'en24', 'en25', 'es', 'es2', 'es3', 'es4', 'es5', 'es6', 'es7', 'es8', 'es9',
                       'es10', 'es11', 'es12', 'es13', 'es14', 'es15', 'es16', 'es17', 'es18', 'es19', 'es20', 'es21',
                       'es22', 'es23', 'et', 'fa', 'fi', 'fil', 'fr', 'fr2', 'fr3', 'fr4', 'fr5', 'fr6', 'fr7', 'fr8',
                       'ga', 'gl', 'gu', 'he', 'hi', 'hr', 'hu', 'id', 'is', 'it', 'it2', 'ja', 'jv', 'ka', 'kk', 
                       'km', 'kn', 'ko', 'ko2', 'lo', 'lt', 'lv', 'mk', 'ml', 'mn', 'mr', 'ms', 'mt', 'my', 'nb',
                       'ne', 'nl', 'nl2', 'nl3', 'pl', 'ps', 'pt', 'pt2', 'pt3', 'ro', 'ru', 'si', 'sk', 'sl', 
                       'so', 'sq', 'sr', 'su', 'sv', 'sw', 'sw2', 'ta', 'ta2', 'ta3', 'ta4', 'te', 'th', 'tr', 
                       'uk', 'ur', 'ur2', 'uz', 'vi', 'zh', 'zh2', 'zh3', 'zh4', 'zh5', 'zh6', 'zh7', 'zh8', 'zu']


PROMPT_DESCRIBE = 'Provide a detailed description of everything you see in the image. Break down long responses into easy-to-read paragraphs. Use markdown formatting to make it look good.'
PROMPT_COPY_TEXT = 'Copy all the text from this image, save it as is - do not translate. Maintain the original formatting (except for line breaks, which should be corrected).'
PROMPT_COPY_TEXT_TR = 'Copy all the text from this image, translate to my language. Maintain the original formatting (except for line breaks, which should be corrected).'
PROMPT_REPROMPT = 'Write an image generation prompt as if you were an expert prompt engineer. 50-300 words. Format your response as follows:'
PROMPT_SOLVE = 'Solve all problems presented in the image. Show your step-by-step solution and clearly indicate the final answer. Use Unicode characters for mathematical notation to ensure accurate representation, dont use symbols like <0xE1><0x83><0xAE><0xE0><0xBF><0xA0>.'
PROMPT_QRCODE = 'Read QRCODE.'


start_msg = '''Hello, I`m AI chat bot powered by Google, Microsoft, Openai etc.

Ask me anything. Send me you text/image/audio/documents with questions.
Generate images with /image command.

Change language with /lang command.
Remove keyboard /remove_keyboard.
'''

help_msg = f"""🔭 If you send a link or text file in a private message, the bot will try to extract and provide a brief summary of the content.
After the file or link is downloaded, you can ask questions about file using the `/ask` command.

🛸 To get text from an image, send the image with the caption "ocr".

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


def get_hidden_prompt_for_user(message, chat_id_full, bot_name, lang_of_user, formatted_date):
    hidden_text = (
                    f'[Info to help you answer. You are a telegram chatbot named "{bot_name}", '
                    f'you are working in chat named "{message.chat.title}", your memory limited to last 20 messages, '
                    f'user have telegram commands (/img - image generator, /bing - bing image creator, /hf - huggingface image generator, /tts - text to speech, /reset - clear chat context, '
                    f'/trans - translate, /sum - summarize, /google - search, you can answer voice messages, '
                    f'images, documents, urls(any text and youtube subs)) and you can use it yourself, you cannot do anything in the background, '
                    f'user name is "{message.from_user.full_name}", user language code is "{lang_of_user}" '
                    f'but it`s not important, your current date is "{formatted_date}", do not address the user by name and '
                    f'no emoji unless it is required. Use Unicode characters for mathematical notation to ensure accurate representation, dont use symbols like <0xE1><0x83><0xAE><0xE0><0xBF><0xA0>. '
                    f'{"your special role here is " + my_db.get_user_property(chat_id_full, "role") + ", " if my_db.get_user_property(chat_id_full, "role") else ""}'
                )

    return hidden_text


def get_hidden_prompt_for_group(message, chat_id_full, bot_name, lang, formatted_date):
    hidden_text = (
                    f'[Info to help you answer. You are a telegram chatbot named "{bot_name}", '
                    f'you are working in private for user named "{message.from_user.full_name}", your memory limited to last 20 messages, '
                    f'user have telegram commands (/img - image generator, /bing - bing image creator, /hf - huggingface image generator, /tts - text to speech, /reset - clear chat context, '
                    f'/trans - translate, /sum - summarize, /google - search, you can answer voice messages, '
                    f'images, documents, urls(any text and youtube subs)) and you can use it yourself, you cannot do anything in the background, '
                    f'user language code is "{lang}" but it`s not important, your current date is "{formatted_date}", do not address the user by name and '
                    f'no emoji unless it is required. Use Unicode characters for mathematical notation to ensure accurate representation, dont use symbols like <0xE1><0x83><0xAE><0xE0><0xBF><0xA0>. '
                    f'{"your special role here is " + my_db.get_user_property(chat_id_full, "role") + ", " if my_db.get_user_property(chat_id_full, "role") else ""}'
                )

    return hidden_text


def get_hidden_prompt_for_llama(tr, lang):
    return tr(f'Answer in "{lang}" language, do not address the user by name and no emoji unless it is required. Use Unicode characters for mathematical notation to ensure accurate representation, dont use symbols like <0xE1><0x83><0xAE><0xE0><0xBF><0xA0>.', lang)


def generate_start_msg():
    msgs = {}
    for x in supported_langs_trans:
    # for x in ['ru', 'uk', 'de']:
        msg = ''

        if not msg:
            msg = my_trans.translate_deepl(start_msg, to_lang=x)
        if not msg:
            msg = my_groq.translate(start_msg, to_lang = x)
        if not msg:
            msg = start_msg
        if msg:
            msgs[x] = msg
            print('\n\n', x, '\n\n', msg)
        if not msg:
            print(f'google translate failed {x}')

    with open(start_msg_file, 'wb') as f:
        pickle.dump(msgs, f)


def generate_help_msg():
    msgs = {}
    for x in supported_langs_trans:
    # for x in ['ru', 'uk', 'de']:
        # msg = my_trans.translate_text2(help_msg, x)
        msg = my_ddg.translate(help_msg, from_lang='en', to_lang=x, help='It is a /help message for telegram chat bot. Keep the formatting.')
        if msg:
            msgs[x] = msg
            print('\n\n', x, '\n\n', msg)
        if not msg:
            print(f'google translate failed {x}')

    with open(help_msg_file, 'wb') as f:
        pickle.dump(msgs, f)


def regenerate_help_msg(langs):
    if isinstance(langs, str):
        langs = [langs, ]

    with open(help_msg_file, 'rb') as f:
        msgs = pickle.load(f)

    missing = [x for x in supported_langs_trans if x not in msgs.keys()]
    print(missing)

    for x in langs:
        msg = my_ddg.translate(help_msg, from_lang='en', to_lang=x, help='It is a /help message for telegram chat bot. Keep the formatting.')
        if not msg:
            msg_ = help_msg
            msg = my_gemini.translate(
                help_msg,
                from_lang='en',
                to_lang=x,
                help='It is a /help message for telegram chat bot. Keep the formatting.',
                model = cfg.gemini_pro_model
            )
            if msg == msg_:
                msg = ''
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
    my_trans.load_users_keys()

    # with open(help_msg_file, 'rb') as f:
    #     d = pickle.load(f)
    # d['pt-br'] = d['pt']
    # with open(help_msg_file, 'wb') as f:
    #     pickle.dump(d, f)

    # generate_start_msg()
    # generate_help_msg()
    regenerate_help_msg('eo')
    # regenerate_start_msg('en')

    my_db.close()
