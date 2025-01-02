#!/usr/bin/env python3


import gradio as gr
from TTS.api import TTS


# Initialize the TTS model
tts = TTS(model_name="voice_conversion_models/multilingual/vctk/freevc24", progress_bar=False, gpu=False)

def process_audio(source_audio, target_audio):
    if source_audio is None or target_audio is None:
        return None

    output_path = "output.wav"  # Temporary output file

    try:
        tts.voice_conversion_to_file(
            source_wav=target_audio,# тут так и надо перепутать их
            target_wav=source_audio,#
            file_path=output_path
        )
        return output_path
    except Exception as e:
        print(f"Error processing audio: {e}")
        return None

with gr.Blocks() as demo:
    gr.Markdown(" # Voice Conversion Space")
    with gr.Column():
        source_audio_input = gr.Audio(type="filepath", label="Source Audio")
        target_audio_input = gr.Audio(type="filepath", label="Target Audio")
        output_audio = gr.Audio(label="Output Audio")
        process_button = gr.Button("Convert Voice")

    process_button.click(
        fn=process_audio,
        inputs=[source_audio_input, target_audio_input],
        outputs=output_audio
    )

if __name__ == "__main__":
    demo.launch()
