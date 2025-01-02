#!/usr/bin/env python3
# pip install -U gradio_client

import os
import random
import threading
import traceback
from io import BytesIO

from pydub import AudioSegment
from gradio_client import Client, handle_file

import my_log
import my_genimg
import utils


LOCK = threading.Lock()


def cut_file(data: bytes) -> bytes:
    '''
    Cut file to 30 seconds.
    '''
    try:
        audio = AudioSegment.from_file(BytesIO(data))
        # Cut to the first 30 seconds (30000 milliseconds)
        thirty_seconds = 30 * 1000
        if len(audio) > thirty_seconds:
            audio = audio[:thirty_seconds]
        # Export the cut audio to MP3 bytes
        output_buffer = BytesIO()
        audio.export(output_buffer, format="mp3")
        return output_buffer.getvalue()
    except Exception as e:
        my_log.log_fish_speech(f'cut_file: {e}')
        return b""


def convert_wav_bytes_to_mp3(wav_bytes: bytes) -> bytes:
    """
    Converts WAV byte data to MP3 byte data.

    Args:
        wav_bytes: The byte data of the WAV audio.

    Returns:
        The byte data of the MP3 audio.
    """
    if not wav_bytes:
        return b""

    wav_file = BytesIO(wav_bytes)
    mp3_file = BytesIO()

    try:
        audio = AudioSegment.from_wav(wav_file)
        audio.export(mp3_file, format="mp3")
        return mp3_file.getvalue()
    except Exception as e:
        my_log.log_fish_speech(f'convert_wav_bytes_to_mp3: {e}')
        return b""


def tts(text: str, voice_sample: bytes) -> bytes:
    '''Text to speech with fish speech from huggingface
    text - text to speech
    voice_sample - voice sample up to 30 seconds
    return - cloned voice mp3 format
    '''
    with LOCK:
        result_data = None
        source_file = utils.get_tmp_fname() + '.mp3'
        with open(source_file, 'wb') as f:
            f.write(voice_sample)
        try:
            client = Client("fishaudio/fish-speech-1", hf_token=random.choice(my_genimg.ALL_KEYS))
            result = client.predict(
                text=text,
                normalize=False,
                reference_audio=handle_file(source_file),
                reference_text="",
                max_new_tokens=1024,
                chunk_length=200,
                top_p=0.7,
                repetition_penalty=1.2,
                temperature=0.7,
                seed=0,
                use_memory_cache="never",
                api_name="/inference_wrapper"
            )

            try:
                result_file = result[0]
                with open(result_file, 'rb') as f:
                    result_data = f.read()
            except:
                result_data = None

        except Exception as error:
            traceback_error = traceback.format_exc()
            my_log.log_fish_speech(f'tts: {error}\n\n{traceback_error}')

    utils.remove_file(source_file)
    try:
        utils.remove_file(result_file)
        base_path = os.path.dirname(result_file)
        try:
            os.rmdir(base_path)
        except Exception as error:
            my_log.log_fish_speech(f'tts: error remove {error}') 
    except UnboundLocalError:
        pass

    return convert_wav_bytes_to_mp3(result_data)


if __name__ == '__main__':
    my_genimg.load_users_keys()

    # voice_sample = open('c:/Users/user/Downloads/1.ogg', 'rb').read()
    # # Example of cutting the voice sample
    # cut_voice_sample = cut_file(voice_sample)
    # if cut_voice_sample:
    #     with open('c:/Users/user/Downloads/cut_output.mp3', 'wb') as f:
    #         f.write(cut_voice_sample)
    #     print("Successfully cut the voice sample.")
    # else:
    #     print("Failed to cut the voice sample.")

    # text = 'Да ёб твою мать, чтоб тебя налево!'
    # result = tts(text, cut_voice_sample if cut_voice_sample else voice_sample)
    # if result:
    #     with open('c:/Users/user/Downloads/result.mp3', 'wb') as f:
    #         f.write(result)
