#!/usr/bin/env python3

from flask import Flask, request, jsonify, Response

import cfg

import my_log

from utils import async_run


# API для доступа к функциям бота (бинг в основном)
FLASK_APP = Flask(__name__)


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
    print(f"Processing audio for user_id: {user_id}")
    # Here you would add your actual audio processing logic
    # For example, you might send the audio to a speech-to-text service,
    # then to a text-to-speech service, and return the result.
    # For now, we'll just return the original audio.
    return audio_data


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
        return Response(processed_audio, mimetype='audio/wav')

    except Exception as e:
        my_log.log_bing_api(f'tb:process_voice: {e}')
        return jsonify({"error": str(e)}), 500


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

    if hasattr(cfg, 'BING_API') and cfg.BING_API:
        run_flask(addr='0.0.0.0', port=42796)


if __name__ == '__main__':
    main()
