import threading
import uuid
import io

import pydub
import requests

import utils


OPEANAI_API_LOCK = threading.Lock()


def concatenate_wav_with_pydub(wav_bytes_list: list[bytes]) -> bytes | None:
    """Concatenates a list of wav byte strings using pydub and returns the result as bytes.

    Args:
        wav_bytes_list: A list of wav byte strings.

    Returns:
        The concatenated OGG data as bytes, or None if an error occurred.
    """
    combined = pydub.AudioSegment.empty()
    for wav_bytes in wav_bytes_list:
        try:
            audio = pydub.AudioSegment.from_file(io.BytesIO(wav_bytes), format="wav")
            # Remove silence from the beginning and end of the audio segment
            audio = audio.strip_silence(silence_len=1000, silence_thresh=-40)  # Adjust parameters as needed
            combined += audio
        except Exception as e:

            return None

    try:
        ogg_stream = io.BytesIO()
        combined.export(ogg_stream, format="ogg", codec="libopus")  # Explicitly specify libopus
        return ogg_stream.getvalue()
    except Exception as e:

        return None


def openai_get_audio_bytes(text: str, voice: str = "ash", prompt: str = '') -> bytes | None:
    """Generates audio from a URL with given text and voice, and returns it as OGG bytes using pydub.

    Args:
        text: The text to be converted to speech.
        voice: The voice to be used for speech synthesis. Defaults to "ash".
               Available voices: alloy, ash, ballad, coral, echo, fable, onyx, nova, sage, shimmer, verse.
        prompt: Optional prompt to guide the voice synthesis. Available prompts:
                Connoisseur, Calm, Emo Teenager, Serene, Patient Teacher or any other text.

    Returns:
        The audio data as bytes in OGG format, or None if an error occurred.
    """
    def openai_get_audio_bytes_(text: str, voice: str = "ash", prompt: str = '') -> bytes | None:
        with OPEANAI_API_LOCK:

            if prompt == 'Connoisseur':
                prompt = '''Accent/Affect: slight French accent; sophisticated yet friendly, clearly understandable with a charming touch of French intonation.

        Tone: Warm and a little snooty. Speak with pride and knowledge for the art being presented.

        Pacing: Moderate, with deliberate pauses at key observations to allow listeners to appreciate details.

        Emotion: Calm, knowledgeable enthusiasm; show genuine reverence and fascination for the artwork.

        Pronunciation: Clearly articulate French words (e.g., "Mes amis," "incroyable") in French and artist names (e.g., "Leonardo da Vinci") with authentic French pronunciation.

        Personality Affect: Cultured, engaging, and refined, guiding visitors with a blend of artistic passion and welcoming charm.'''
            elif prompt == 'Calm':
                prompt = '''Voice Affect: Calm, composed, and reassuring; project quiet authority and confidence.

        Tone: Sincere, empathetic, and gently authoritative—express genuine apology while conveying competence.

        Pacing: Steady and moderate; unhurried enough to communicate care, yet efficient enough to demonstrate professionalism.

        Emotion: Genuine empathy and understanding; speak with warmth, especially during apologies ("I'm very sorry for any disruption...").

        Pronunciation: Clear and precise, emphasizing key reassurances ("smoothly," "quickly," "promptly") to reinforce confidence.

        Pauses: Brief pauses after offering assistance or requesting details, highlighting willingness to listen and support.'''
            elif prompt == 'Emo Teenager':
                prompt = '''Tone: Sarcastic, disinterested, and melancholic, with a hint of passive-aggressiveness.

        Emotion: Apathy mixed with reluctant engagement.

        Delivery: Monotone with occasional sighs, drawn-out words, and subtle disdain, evoking a classic emo teenager attitude.'''
            elif prompt == 'Serene':
                prompt = '''Voice Affect: Soft, gentle, soothing; embody tranquility.

        Tone: Calm, reassuring, peaceful; convey genuine warmth and serenity.

        Pacing: Slow, deliberate, and unhurried; pause gently after instructions to allow the listener time to relax and follow along.

        Emotion: Deeply soothing and comforting; express genuine kindness and care.

        Pronunciation: Smooth, soft articulation, slightly elongating vowels to create a sense of ease.

        Pauses: Use thoughtful pauses, especially between breathing instructions and visualization guidance, enhancing relaxation and mindfulness.'''
            elif prompt == 'Patient Teacher':
                prompt = '''Accent/Affect: Warm, refined, and gently instructive, reminiscent of a friendly art instructor. Very fast speech.

        Tone: Calm, encouraging, and articulate, clearly describing each step with patience.

        Pacing: Slow and deliberate, pausing often to allow the listener to follow instructions comfortably.

        Emotion: Cheerful, supportive, and pleasantly enthusiastic; convey genuine enjoyment and appreciation of art.

        Pronunciation: Clearly articulate artistic terminology (e.g., "brushstrokes," "landscape," "palette") with gentle emphasis.

        Personality Affect: Friendly and approachable with a hint of sophistication; speak confidently and reassuringly, guiding users through each painting step patiently and warmly.'''


            base_url = "https://www.openai.fm/api/generate"
            params = {
                "input": requests.utils.quote(text),
                "voice": voice,
                "generation": uuid.uuid4(),
            }
            if prompt:
                params["prompt"] = requests.utils.quote(prompt)

            request_url = f"{base_url}?{'&'.join([f'{k}={v}' for k, v in params.items()])}"

            headers = {
                "accept-encoding": "identity;q=1, *;q=0",
                "range": "bytes=0-",
                "referer": "https://www.openai.fm/",
                "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="132", "Opera";v="117"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 OPR/117.0.0.0",
            }

            response = requests.get(request_url, headers=headers, stream=True, timeout=30)

            if response.status_code == 200:
                wav_bytes = b"".join(chunk for chunk in response.iter_content(chunk_size=8192) if chunk)

                try:
                    # # Load the WAV data using pydub
                    # audio = pydub.AudioSegment.from_wav(io.BytesIO(wav_bytes))

                    # # Export to OGG format in memory
                    # ogg_stream = io.BytesIO()
                    # audio.export(ogg_stream, format="ogg", codec="libopus")  # Specify libopus codec

                    # ogg_bytes = ogg_stream.getvalue()

                    # return ogg_bytes
                    return wav_bytes
                except Exception as e:

                    return None
            else:

                return None
    
    
    chunks = []
    for chunk in utils.split_text(text, chunk_limit=999):
        chunks.append(openai_get_audio_bytes_(chunk, voice, prompt))
    return concatenate_wav_with_pydub(chunks)


if __name__ == "__main__":

    text = """ Я не знал их имен. Никогда не  слышал их голосов."""

    ogg_bytes = openai_get_audio_bytes(text=text)

    if ogg_bytes:
        print("Successfully retrieved OGG bytes.")
        # You can now work with the ogg_bytes (e.g., save to a file, play, etc.)
        # Example:
        with open("output.ogg", "wb") as f:
            f.write(ogg_bytes)
    else:
        print("Failed to retrieve OGG bytes.")
