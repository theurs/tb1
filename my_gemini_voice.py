import asyncio
import io
import time
import traceback
from google import genai
from google.genai import types
from pydub import AudioSegment

import my_gemini
import my_log
import utils


# Default model constant
DEFAULT_MODEL = "gemini-2.0-flash-live-001"


async def generate_audio_bytes(
    text: str,
    lang: str = "ru",
    voice: str = "Zephyr",
    model: str = DEFAULT_MODEL
) -> bytes:
    """
    Generates audio from text using the Google GenAI Live API and returns the audio data as raw bytes.

    Note: The Google GenAI Live API likely streams raw PCM audio data (e.g., S16LE at 24000 Hz).
    This function returns those raw bytes directly. Use the 'convert_raw_pcm_to_ogg_bytes'
    function to convert these bytes to OGG format if needed.

    Args:
        text (str): The text to synthesize into speech.
        lang (str, optional): The language for pronunciation guidance. Defaults to "ru".
        voice (str, optional): The voice to use for synthesis. Defaults to "Zephyr".
                               Other available voices: Puck, Charon, Kore, Fenrir, Aoede, Leda, Orus, and Zephyr
        model (str, optional): The generative model to use. Defaults to DEFAULT_MODEL.

    Returns:
        bytes: A bytes object containing the raw audio data received from the API.
               Returns empty bytes if no audio data is received or an error occurs.
    """
    client = genai.Client(api_key=my_gemini.get_next_key(), http_options={'api_version': 'v1alpha'})

    config = types.LiveConnectConfig(
        generation_config=types.GenerationConfig(temperature=0),
        response_modalities=["AUDIO"],
        system_instruction=types.Content(
            parts = [
                types.Part(text=f"Отвечай эхом на все запросы юзера, просто произноси всё точно так как он тебе написал, цифры произноси на языке [{lang}]"),
                types.Part(text=f"Запрос юзера надо предварительно переписать, исправить опечатки, исправить ошибки оформления"),
            ]
        ),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
            )
        ),
    )

    audio_data = bytearray()
    try:
        async with client.aio.live.connect(model=model, config=config) as session:
            await session.send(input=text, end_of_turn=True)
            async for response in session.receive():
                if response.data is not None:
                    audio_data.extend(response.data)
    except Exception as e:
        my_log.log_gemini(f"my_gemini_voice:generate_audio_bytes: An error occurred during GenAI Live API interaction: {e}")
        return b''

    return bytes(audio_data)


def convert_raw_pcm_to_ogg_bytes(
    raw_audio_bytes: bytes,
    sample_rate: int = 24000,
    sample_width: int = 2, # Bytes per sample (e.g., 2 for 16-bit audio)
    channels: int = 1      # Number of audio channels (e.g., 1 for mono)
) -> bytes | None:
    """
    Converts raw PCM audio bytes to OGG Vorbis format bytes using pydub.

    Requires pydub library and ffmpeg installed and accessible in PATH.

    Args:
        raw_audio_bytes (bytes): The raw PCM audio data.
        sample_rate (int): The sample rate of the raw audio (e.g., 24000 Hz).
        sample_width (int): The number of bytes per sample (e.g., 2 for 16-bit).
        channels (int): The number of audio channels (e.g., 1 for mono).

    Returns:
        bytes | None: A bytes object containing the OGG Vorbis formatted audio,
                      or None if conversion fails (e.g., pydub/ffmpeg not found or error).
    """
    try:
        # Load raw PCM data into an AudioSegment
        audio_segment = AudioSegment.from_raw(
            io.BytesIO(raw_audio_bytes),
            sample_width=sample_width,
            frame_rate=sample_rate,
            channels=channels
        )

        # Export the AudioSegment to OGG format in memory
        ogg_buffer = io.BytesIO()
        # Export using 'ogg' format and 'libvorbis' codec
        audio_segment.export(
            ogg_buffer,
            format="ogg",
            codec="libvorbis",
            parameters=["-q:a", "5"],
        )

        # Get the bytes from the in-memory buffer
        ogg_bytes = ogg_buffer.getvalue()
        return ogg_bytes

    except Exception as e:
        # Catch potential errors during pydub processing or ffmpeg execution
        my_log.log_gemini(f"my_gemini_voice:convert_raw_pcm_to_ogg_bytes: Error during OGG conversion: {e}\nEnsure ffmpeg is installed and accessible in your system's PATH.\n\n{traceback.format_exc()}")
        return None


def generate_and_convert_to_ogg_sync_chunked(
    text: str,
    chunk_limit: int = 8000, # Max characters per chunk for API call
    lang: str = "ru",
    voice: str = "Zephyr",
    model: str = DEFAULT_MODEL, # Ensure DEFAULT_MODEL is accessible
    sample_rate: int = 24000,
    sample_width: int = 2,
    channels: int = 1
) -> bytes | None:
    """
    Synchronously generates audio for potentially long text by chunking,
    concatenates the raw audio, converts the final result to OGG, and returns OGG bytes.

    Handles text longer than chunk_limit by splitting it and processing chunks sequentially.
    Runs the asynchronous generate_audio_bytes for each chunk using asyncio.run().
    Concatenates raw PCM audio bytes from chunks and converts to OGG once at the end.

    Args:
        text (str): The text to synthesize. Can be very long.
        chunk_limit (int, optional): Maximum character length per chunk for the API.
                                     Defaults to 8000.
        lang (str, optional): Language for pronunciation guidance. Defaults to "ru".
        voice (str, optional): The voice to use for synthesis. Defaults to "Zephyr".
        model (str, optional): The generative model to use. Defaults to DEFAULT_MODEL.
        sample_rate (int, optional): The sample rate expected for the raw audio
                                     before conversion. Defaults to 24000.
        sample_width (int, optional): The sample width (bytes) expected for the raw
                                      audio. Defaults to 2 (for 16-bit).
        channels (int, optional): The number of channels expected for the raw audio.
                                  Defaults to 1 (mono).

    Returns:
        bytes | None: A bytes object containing the OGG Vorbis formatted audio for the
                      entire text if successful, or None if any step fails.
                      Note: OGG quality is determined by convert_raw_pcm_to_ogg_bytes.
    """
    if not text:
        my_log.log_gemini("my_gemini_voice:generate_and_convert_to_ogg_sync_chunked: Input text is empty, returning None.")
        return None

    # Use bytearray for efficient accumulation of raw bytes from chunks
    all_raw_audio_bytes = bytearray()

    def get_raw_audio_bytes_for_chunk(chunk, chunk_num):
        # --- Generate raw audio for the current chunk ---
        # Run the async function generate_audio_bytes synchronously for this chunk
        raw_chunk_bytes: bytes | None = None
        try:
            # asyncio.run creates a new event loop for each call here
            raw_chunk_bytes = asyncio.run(generate_audio_bytes(
                text=chunk,
                lang=lang,
                voice=voice,
                model=model
            ))
            return raw_chunk_bytes
        except RuntimeError as e:
            # This happens if asyncio.run is called from an already running event loop
            my_log.log_gemini(f"my_gemini_voice:generate_and_convert_to_ogg_sync_chunked: RuntimeError calling asyncio.run for chunk {chunk_num}: {e}. Cannot run from existing loop.")
            # return None # Critical failure, cannot proceed
        except Exception as e:
            # Catch other potential errors during the async call execution
            my_log.log_gemini(f"my_gemini_voice:generate_and_convert_to_ogg_sync_chunked: Unexpected error during generate_audio_bytes for chunk {chunk_num}: {e}\n{traceback.format_exc()}")
            # return None # Critical failure
        return b''


    try:
        # Iterate through the text in chunks
        chunks = utils.split_text(text, chunk_limit=8000)
        chunk_num = 0
        for chunk in chunks:
            chunk_num += 1

            raw_chunk_bytes = get_raw_audio_bytes_for_chunk(chunk, chunk_num)

            # --- Check chunk generation result ---
            if not raw_chunk_bytes:
                time.sleep(5)
                #try one more
                raw_chunk_bytes = get_raw_audio_bytes_for_chunk(chunk, chunk_num)

            # --- Check chunk generation result ---
            if not raw_chunk_bytes:
                time.sleep(5)
                #try one more
                raw_chunk_bytes = get_raw_audio_bytes_for_chunk(chunk, chunk_num)

            # --- Check chunk generation result ---
            if not raw_chunk_bytes:
                my_log.log_gemini(f"my_gemini_voice:generate_and_convert_to_ogg_sync_chunked: Chunk {chunk_num} failed to generate raw audio.")
                # return None

            # --- Append successful raw bytes ---
            all_raw_audio_bytes.extend(raw_chunk_bytes or b'')

        # --- Post-chunk processing ---
        # Check if any data was collected at all
        if not all_raw_audio_bytes:
             my_log.log_gemini("my_gemini_voice:generate_and_convert_to_ogg_sync_chunked: No raw audio data was collected after processing all chunks.")
             return None

        # --- Convert the *entire* concatenated raw audio to OGG *once* ---
        # Pass the combined bytearray (converted to bytes) to the conversion function
        ogg_bytes = convert_raw_pcm_to_ogg_bytes(
            raw_audio_bytes=bytes(all_raw_audio_bytes), # Convert bytearray -> bytes
            sample_rate=sample_rate,
            sample_width=sample_width,
            channels=channels
        )

        # --- Check final conversion result ---
        if ogg_bytes is None:
            my_log.log_gemini("my_gemini_voice:generate_and_convert_to_ogg_sync_chunked: Final OGG conversion failed.")
            # convert_raw_pcm_to_ogg_bytes should have logged the specific error via my_log
            return None # Indicate overall failure
        else:
            return ogg_bytes # Success! Return the final OGG bytes

    except Exception as e:
        # Catch any unexpected errors in the chunking loop logic or final steps
        my_log.log_gemini(f"my_gemini_voice:generate_and_convert_to_ogg_sync_chunked: Unexpected error during overall chunk processing or final conversion: {e}\n{traceback.format_exc()}")
        return None


if __name__ == "__main__":
    my_gemini.load_users_keys()
    long_text = """
    Глава 1


     Скитер Джексон  был  негодяем. Прожженным,  заматерелым,  самым  гадким
негодяем из негодяев. Таким, что пробу негде ставить.
     Ясное  дело,  сам  он  это  знал  и  знал  не  хуже  любого  другого  в
Ла-ла-ландии (по крайней мере любого, кто пробыл на Вокзале Шангри-ла больше
недели). Мало того, он не  только это знал, но и гордился этим  --  так, как
гордятся  боевыми  заслугами, низким  содержанием холестерина  в  крови  или
удачными биржевыми сделками.

"""
    print("Starting synchronous chunked generation...")
    final_ogg_data = generate_and_convert_to_ogg_sync_chunked(long_text)

    if final_ogg_data:
        print(f"Successfully generated OGG data, size: {len(final_ogg_data)} bytes.")
        try:
            output_filename = r"c:\Users\user\Downloads\output_audio_long_chunked.ogg"
            with open(output_filename, "wb") as f:
                f.write(final_ogg_data)
            print(f"Saved final OGG to {output_filename}")
        except Exception as e:
            print(f"Error saving final OGG file: {e}")
    else:
        print("Failed to generate OGG data for the long text.")
