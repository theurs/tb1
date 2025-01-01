#!/usr/bin/env python3
# https://medium.com/the-ai-forum/building-a-real-time-voice-assistant-application-with-fastapi-groq-and-openai-tts-api-a8a8fe38c315
# pip install -U webrtcvad

import logging
import struct
from typing import Optional

import numpy as np
import uvicorn
import webrtcvad
from fastapi import FastAPI, WebSocket, Request, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import my_groq_voice_chat
import my_tts_voicechat


## Audio Detection
######################################################################
class VoiceDetector:
    def __init__(self, sample_rate=16000, frame_duration=30):
        self.vad = webrtcvad.Vad(2)  # Reduced aggressiveness for better continuous speech detection
        self.sample_rate = sample_rate
        self.frame_duration = frame_duration
        self.frame_size = int(sample_rate * frame_duration / 1000)
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)
        self.silence_frames = 0
        self.max_silence_frames = 15  # Allow more silence between words
        self.min_speech_frames = 3  # Require minimum speech frames to avoid spurious detections
        self.speech_frames = 0
        self.is_speaking = False

    def _frame_generator(self, audio_data):
        """Generate audio frames from raw audio data."""
        if len(audio_data) < self.frame_size:
            self.logger.warning(f"Audio data too short: {len(audio_data)} bytes")
            return []

        n = len(audio_data)
        offset = 0
        frames = []
        while offset + self.frame_size <= n:
            frames.append(audio_data[offset:offset + self.frame_size])
            offset += self.frame_size
        return frames

    def _convert_audio_data(self, audio_data):
        """Convert audio data to the correct format."""
        try:
            # First try to interpret as float32
            float_array = np.frombuffer(audio_data, dtype=np.float32)
            # Convert float32 [-1.0, 1.0] to int16 [-32768, 32767]
            int16_array = (float_array * 32767).astype(np.int16)
            return int16_array
        except ValueError:
            try:
                # If that fails, try direct int16 interpretation
                return np.frombuffer(audio_data, dtype=np.int16)
            except ValueError as e:
                # If both fail, try to pad the data to make it aligned
                padding_size = (2 - (len(audio_data) % 2)) % 2
                if padding_size > 0:
                    padded_data = audio_data + b'\x00' * padding_size
                    return np.frombuffer(padded_data, dtype=np.int16)
                raise e

    def detect_voice(self, audio_data):
        """
        Detect voice activity in audio data.

        Args:
            audio_data (bytes): Raw audio data

        Returns:
            bool: True if voice activity is detected, False otherwise
        """
        try:
            if audio_data is None or len(audio_data) == 0:
                self.logger.warning("Audio data is empty or None")
                return False

            # Convert audio data to the correct format
            try:
                audio_array = self._convert_audio_data(audio_data)
                if len(audio_array) == 0:
                    self.logger.warning("No valid audio data after conversion")
                    return False
            except ValueError as e:
                self.logger.error(f"Error converting audio data: {str(e)}")
                return False

            # Process frames
            frames = self._frame_generator(audio_array)
            if not frames:
                self.logger.warning("No frames generated from audio data")
                return False

            # Count speech frames in this chunk
            current_speech_frames = 0
            for frame in frames:
                try:
                    # Pack the frame into bytes
                    frame_bytes = struct.pack("%dh" % len(frame), *frame)

                    # Check for voice activity
                    if self.vad.is_speech(frame_bytes, self.sample_rate):
                        current_speech_frames += 1
                        self.speech_frames += 1
                        self.silence_frames = 0
                    else:
                        self.silence_frames += 1

                except struct.error as se:
                    self.logger.error(f"Error packing frame data: {str(se)}")
                    continue
                except Exception as e:
                    self.logger.error(f"Error processing frame: {str(e)}")
                    continue

            # Update speaking state
            if current_speech_frames > 0:
                if not self.is_speaking and self.speech_frames >= self.min_speech_frames:
                    self.is_speaking = True
                return True
            elif self.silence_frames > self.max_silence_frames:
                if self.is_speaking:
                    self.is_speaking = False
                    self.speech_frames = 0
                return False

            # Keep current state if in transition
            return self.is_speaking

        except Exception as e:
            self.logger.error(f"Error in voice detection: {str(e)}")
            return False 


# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()


######### надо создать эти файлы или удалить из кода #########
# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# project_root/
# ├── main.py # Main FastAPI application
# ├── config.py # Configuration settings
# ├── requirements.txt # Python dependencies
# │
# ├── static/ # Static files directory
# │ ├── css/
# │ ├── js/
# │ └── assets/
# │
# ├── templates/ # Jinja2 templates
# │ └── index.html # Main template file
# │
# ├── voice_modules/ # Voice processing modules
# │ ├── __init__.py
# │ └── realtime_voice_detection.py # Voice detection implementation
# │
# └── README.md # Project documentation
######### надо создать эти файлы или удалить из кода #########


@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


async def transcribe_audio(audio_data: bytes):
    """Transcribe audio using Groq's Whisper model"""
    result = my_groq_voice_chat.stt(audio_data)
    if result:
        return result
    logger.error(f"Transcription error: empty result")
    return None


async def get_chat_response(text: str, user_id: str = "unknown") -> Optional[str]:
    """Get chat response from Groq"""
    response = my_groq_voice_chat.chat(
        text,
        chat_id=user_id,
        model='',
        style='',
        temperature=1,
        timeout=60,
        max_tokens=500
        )
    if response:
        return response
    logger.error(f"Chat response error: empty result")
    return None


async def generate_speech(text: str, user_id: str = "unknown") -> Optional[bytes]:
    """Generate speech using OpenAI TTS"""
    result = my_tts_voicechat.tts(
        text,
        voice='de',
        rate='+50%',
        gender='female',
        )
    if result:
        return result
    logger.error(f"Speech generation error: empty result")
    return None


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket connection established")

    voice_detector = VoiceDetector()
    audio_buffer = bytearray()
    silence_duration = 0
    max_silence_duration = 1.5  # seconds
    frames_per_second = 1000 / voice_detector.frame_duration  # frames per second
    max_silence_frames = int(max_silence_duration * frames_per_second)

    try:
        while True:
            try:
                data = await websocket.receive_bytes()

                if not data:
                    logger.warning("Received empty data frame")
                    continue

                # Check for voice activity
                voice_detected = voice_detector.detect_voice(data)

                if voice_detected:
                    # Reset silence counter and add to buffer
                    silence_duration = 0
                    audio_buffer.extend(data)
                    await websocket.send_json({"type": "vad", "status": "active"})
                else:
                    # Increment silence counter
                    silence_duration += 1
                    
                    # If we were collecting speech and hit max silence, process the buffer
                    if len(audio_buffer) > 0 and silence_duration >= max_silence_frames:
                        logger.info(f"Processing audio buffer of size: {len(audio_buffer)} bytes")

                        # Process the complete utterance
                        transcription = await transcribe_audio(bytes(audio_buffer))
                        if transcription:
                            logger.info(f"Transcription: {transcription}")
                            await websocket.send_json({
                                "type": "transcription",
                                "text": transcription
                            })

                            # Get chat response
                            chat_response = await get_chat_response(transcription)
                            if chat_response:
                                logger.info(f"Chat response: {chat_response}")
                                await websocket.send_json({
                                    "type": "chat_response",
                                    "text": chat_response
                                })

                                # Generate and send voice response
                                voice_response = await generate_speech(chat_response)
                                if voice_response:
                                    logger.info("Generated voice response")
                                    await websocket.send_bytes(voice_response)

                        # Clear the buffer after processing
                        audio_buffer = bytearray()
                        await websocket.send_json({"type": "vad", "status": "inactive"})
                    elif len(audio_buffer) > 0:
                        # Still collecting silence, add to buffer
                        audio_buffer.extend(data)

            except WebSocketDisconnect:
                logger.info("WebSocket disconnected")
                break
            except Exception as e:
                logger.error(f"Error processing websocket frame: {str(e)}")
                continue

    except Exception as e:
        logger.error(f"WebSocket connection error: {str(e)}")
    finally:
        logger.info("Closing WebSocket connection")
        await websocket.close()


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=42796, reload=True)
