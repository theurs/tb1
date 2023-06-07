#!/usr/bin/python


import whisper
import sys


def get_text(audio_file):
    model = whisper.load_model("base")
    result = model.transcribe(audio_file)
 
    text = '\n'.join(x['text'] for x in result['segments'])

    return text


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: my_whisper.py <audio file>")
        sys.exit(1)
    print(get_text(sys.argv[1]))

