#!/usr/bin/env python3
# pip install -U gradio_client

import os
import random
import threading
import traceback
from io import BytesIO

from pydub import AudioSegment
from gradio_client import Client, handle_file

import cfg
import my_log
import my_genimg
import utils


LOCK_TTS = threading.Lock()
LOCK_CLONE = threading.Lock()


def cut_file(data: bytes) -> bytes:
    '''
    Cut file to 30 seconds.
    '''
    try:
        if not data:
            return b""
        audio = AudioSegment.from_file(BytesIO(data))
        # Cut to the first 30 seconds (30000 milliseconds)
        thirty_seconds = 30 * 1000
        if len(audio) > thirty_seconds:
            audio = audio[:thirty_seconds]
        else:
            return data
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

    try:
        wav_file = BytesIO(wav_bytes)
        mp3_file = BytesIO()

        try:
            audio = AudioSegment.from_wav(wav_file)
            audio.export(mp3_file, format="mp3")
            return mp3_file.getvalue()
        except Exception as e:
            my_log.log_fish_speech(f'convert_wav_bytes_to_mp3: {e}')
    except Exception as e:
        traceback_error = traceback.format_exc()
        my_log.log_fish_speech(f'convert_wav_bytes_to_mp3: {e}\n\n{traceback_error}')

    return b""


def tts(text: str, voice_sample: bytes) -> bytes:
    '''Text to speech with fish speech from huggingface
    text - text to speech
    voice_sample - voice sample up to 30 seconds
    return - cloned voice mp3 format
    '''
    with LOCK_TTS:
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
        if result_file:
            utils.remove_file(result_file)
            base_path = os.path.dirname(result_file)
            try:
                os.rmdir(base_path)
            except Exception as error:
                my_log.log_fish_speech(f'tts: error remove {error}')
    except UnboundLocalError:
        pass

    return convert_wav_bytes_to_mp3(result_data)


def clone_voice_sample(voice_sample_source: bytes, voice_sample_target: bytes) -> bytes:
    '''
    Клонирует войс-сэмпл, уменьшает его до 30 секунд и возвращает его в mp3 формате
    voice_sample_source - исходный войс-сэмпл, образец голоса
    voice_sample_target - целевой войс-сэмпл, голос который надо изменить используя образец
    '''
    if not (hasattr(cfg, 'CLONE_VOICE_HF_API_KEYS') and len(cfg.CLONE_VOICE_HF_API_KEYS) > 0):
        return b""

    with LOCK_CLONE:
        try:

            result_data = None
            source_file = utils.get_tmp_fname() + '.mp3'
            with open(source_file, 'wb') as f:
                f.write(voice_sample_source)
            target_file = utils.get_tmp_fname() + '.mp3'
            with open(target_file, 'wb') as f:
                f.write(voice_sample_target)

            voice_sample_source = cut_file(voice_sample_source)
            voice_sample_target = cut_file(voice_sample_target)

            client = Client("parfiriolis/xtts_clone_voice", hf_token=random.choice(cfg.CLONE_VOICE_HF_API_KEYS))

            result_file = ''
            try:
                result_file = client.predict(
                        source_audio=handle_file(source_file),
                        target_audio=handle_file(target_file),
                        api_name="/process_audio"
                )
            except Exception as error:
                my_log.log_fish_speech(f'clone_voice_sample: {error}')

            if result_file:
                try:
                    with open(result_file, 'rb') as f:
                        result_data = f.read()
                except:
                    result_data = None

            utils.remove_file(source_file)
            utils.remove_file(target_file)
            utils.remove_file(result_file)

            try:
                base_path = os.path.dirname(result_file)
                os.rmdir(base_path)
            except Exception as error:
                my_log.log_fish_speech(f'clone_voice_sample: error remove {error}')

            if result_data:
                return convert_wav_bytes_to_mp3(result_data)
            else:
                return b""
        except Exception as e:
            my_log.log_fish_speech(f'clone_voice_sample: {e}')
            return b""


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


    # voice_sample_source = open('c:/Users/user/Downloads/klim_10.mp3', 'rb').read()
    # voice_sample_target = open('c:/Users/user/Downloads/shilman_10.mp3', 'rb').read()
    # result = clone_voice_sample(voice_sample_source, voice_sample_target)
    # if result:
    #     with open('c:/Users/user/Downloads/clone_result.mp3', 'wb') as f:
    #         f.write(result)
