#!/usr/bin/env python3

import pickle

import my_trans
import my_openrouter


supported_langs_trans = [
        "af","am","ar","az","be","bg","bn","bs","ca","ceb","co","cs","cy","da","de",
        "el","en","eo","es","et","eu","fa","fi","fr","fy","ga","gd","gl","gu","ha",
        "haw","he","hi","hmn","hr","ht","hu","hy","id","ig","is","it","iw","ja","jw",
        "ka","kk","km","kn","ko","ku","ky","la","lb","lo","lt","lv","mg","mi","mk",
        "ml","mn","mr","ms","mt","my","ne","nl","no","ny","or","pa","pl","ps","pt",
        "ro","ru","rw","sd","si","sk","sl","sm","sn","so","sq","sr","st","su","sv",
        "sw","ta","te","tg","th","tl","tr","ua","uk","ur","uz","vi","xh","yi","yo","zh",
        "zh-TW","zu"]

supported_langs_tts = [
        'af', 'am', 'ar', 'as', 'az', 'be', 'bg', 'bn', 'bs', 'ca', 'cs', 'cy', 'da',
        'de', 'el', 'en', 'eo', 'es', 'et', 'eu', 'fa', 'fi', 'fil', 'fr', 'ga', 'gl',
        'gu', 'he', 'hi', 'hr', 'ht', 'hu', 'hy', 'id', 'is', 'it', 'ja', 'jv', 'ka',
        'kk', 'km', 'kn', 'ko', 'ku', 'ky', 'la', 'lb', 'lo', 'lt', 'lv', 'mg', 'mi',
        'mk', 'ml', 'mn', 'mr', 'ms', 'mt', 'my', 'nb', 'ne', 'nl', 'nn', 'no', 'ny',
        'or', 'pa', 'pl', 'ps', 'pt', 'ro', 'ru', 'rw', 'sd', 'si', 'sk', 'sl', 'sm',
        'sn', 'so', 'sq', 'sr', 'st', 'su', 'sv', 'sw', 'ta', 'te', 'tg', 'th', 'tk',
        'tl', 'tr', 'tt', 'ua', 'ug', 'uk', 'ur', 'uz', 'vi', 'xh', 'yi', 'yo', 'zh', 'zu']


start_msg = '''Hello, I`m AI chat bot powered by Google Gemini [1.0/1.5/Vision/Flash], llama3-70, claude 3, gpt-4o etc!

Ask me anything. Send me you text/image/audio/documents with questions.

You can change language with /lang command.

You can generate images with /image command. Image editing is not supported yet.

Remove keyboard /remove_keyboard
'''

help_msg = f"""The bot can't edit images or draw, and it doesn't search Google itself.
These are all done by separate commands. 

The bot doesn't do anything between questions and answers.
It can't remind you of anything because it doesn't exist until you write to it.
It only works and exists when it's reading your messages or writing a response.

Please only use /image2 command for generating not safe pictures (nsfw).

🔭 If you send a link or text file in a private message, the bot will try to extract and provide a brief summary of the content.
After the file or link is downloaded, you can ask questions about file using the /ask command.

🛸 To get text from an image, send the image with the caption "ocr".

🎙️ You can issue commands and make requests using voice messages.

👻 /purge command to remove all your data

Change model:
/gemini10 - Google Gemini 1.5 flash
/gemini15 - Google Gemini 1.5 pro
/llama370 - LLaMa 3 70b (Groq)
/openrouter - all other models including new GPT-4o, Claude 3 Opus etc, you will need your own account

Report issues on Telegram:
https://t.me/kun4_sun_bot_support

"""

start_msg_file = 'msg_hello.dat'
help_msg_file = 'msg_help.dat'


def generate_start_msg():
    msgs = {}
    for x in supported_langs_trans:
    # for x in ['ru', 'uk', 'de']:
        msg = my_trans.translate_text2(start_msg, x)
        if msg and len(msg) > (len(start_msg)/3):
            msgs[x] = msg
            print('\n\n', x, '\n\n', msg)
        if not msg or len(msg) < (len(start_msg)/3):
            print(f'google translate failed {x}')
            msg = my_openrouter.translate(start_msg, from_lang='en', to_lang=x, help='This is a /start message for telegram bot.')
            if msg and len(msg) > (len(start_msg)/3):
                msgs[x] = msg
                print('\n\n', x, '\n\n', msg)
            else:
                print(f'haiju translate failed {x}')

    with open(start_msg_file, 'wb') as f:
        pickle.dump(msgs, f)


def generate_help_msg():
    msgs = {}
    for x in supported_langs_trans:
    # for x in ['ru', 'uk', 'de']:
        msg = my_trans.translate_text2(help_msg, x)
        if msg:
            msgs[x] = msg
            print('\n\n', x, '\n\n', msg)
        if not msg:
            print(f'google translate failed {x}')

    with open(help_msg_file, 'wb') as f:
        pickle.dump(msgs, f)


if __name__ == '__main__':
    pass
    generate_start_msg()
    # generate_help_msg()

