#!/usr/bin/env python3

from flask import Flask, request, jsonify, Response
from flask_cors import CORS

import cfg
import my_groq_voice_chat
import my_tts_voicechat

import my_log
from utils import async_run


# API для доступа к функциям бота (бинг в основном)
FLASK_APP = Flask(__name__)
CORS(FLASK_APP)


def process_audio_data(audio_data: bytes, user_id: int) -> bytes:
    """
    This function simulates processing of the audio data.
    Replace this with your actual audio processing logic.

    Args:
        audio_data: The audio data in bytes.
        user_id: The ID of the user.

    Returns:
        The processed audio data in bytes.
    """
    c_id = f'[{user_id}] [0]'

    if not audio_data or len(audio_data) < 2000:
        return b''

    query = my_groq_voice_chat.stt(audio_data)

    if not query.strip():
        return b''

    print('запрос: ', query)

    answer = my_groq_voice_chat.chat(query, c_id)
    print('ответ: ', answer)
    if answer:
        audio_data = my_tts_voicechat.tts(answer, voice='de', gender='female')
        print('audio_data len: ', len(audio_data))
        if audio_data:
            return audio_data
    print('audio_data zero')
    return b''


@FLASK_APP.route('/voice', methods=['POST'])
def process_voice():
    """
    API endpoint for receiving and processing voice messages.
    Expects a multipart/form-data POST request with 'audio' and 'user_id' fields.
    Returns processed audio data.
    """
    try:
        # Check if the post request has the file part and user_id
        if 'audio' not in request.files:
            return jsonify({"error": "No audio file part"}), 400
        if 'user_id' not in request.form:
            return jsonify({"error": "No user_id provided"}), 400

        audio_file = request.files['audio']
        user_id = int(request.form['user_id'])

        # Check if the file is empty
        if audio_file.filename == '':
            return jsonify({"error": "No selected file"}), 400

        # Read the audio data
        audio_data = audio_file.read()

        # Process the audio
        processed_audio = process_audio_data(audio_data, user_id)

        # Return the processed audio data as a response
        return Response(processed_audio, mimetype='audio/ogg; codecs=opus')

    except Exception as e:
        my_log.log_bing_api(f'tb:process_voice: {e}')
        return jsonify({"error": str(e)}), 500


@FLASK_APP.route('/', methods=['GET'])
def index():
    """
    Root endpoint, displays "OK" to indicate the server is running.
    """
    return "OK"


@async_run
def run_flask(addr: str ='127.0.0.1', port: int = 58796):
    try:
        FLASK_APP.run(debug=True, use_reloader=False, host=addr, port = port)
    except Exception as error:
        my_log.log_bing_api(f'tb:run_flask: {error}')


def main():
    """
    Runs the main function, which sets default commands and starts polling the bot.
    """
    my_groq_voice_chat.load_users_keys()

    if hasattr(cfg, 'BING_API') and cfg.BING_API:
        run_flask(addr='0.0.0.0', port=42796)


if __name__ == '__main__':
    # main()

    audio_data = my_tts_voicechat.tts('hello all', voice='de', rate='+50%', gender='female')
    print(len(audio_data))
