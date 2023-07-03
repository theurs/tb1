#!/usr/bin/env python3


import sys
import threading

import whisper

import cfg


MODEL = None
if cfg.stt == 'whisper':
    MODEL = whisper.load_model(cfg.whisper_model)
lock = threading.Lock()

def get_text(audio_file):
    with lock:
        result = MODEL.transcribe(audio_file)

    #text = '\n'.join(x['text'] for x in result['segments'])
    text = result['text']
    return text


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: my_whisper.py <audio file>")
        #print(whisper.available_models())
        sys.exit(1)
    print(get_text(sys.argv[1]))
