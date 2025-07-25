import os
import re
import shutil
import subprocess
import tempfile
from typing import List

import my_log

def split_audio_by_silence(
    input_audio_file: str,
    target_duration_seconds: int,
    silence_duration: float = 1.0,
    noise_threshold_db: int = -25
) -> List[str]:
    """Splits an audio file by silence into a system temporary directory.

    This function creates a new directory in the system's temporary location
    (e.g., /tmp or C:\\Users\\...\\AppData\\Local\\Temp) to store the final
    output files. Intermediate processing files are created and deleted
    automatically during the process.

    Warning:
        The directory containing the final files is NOT automatically deleted
        upon function completion. The OS will typically clean it up on reboot,
        but it will persist otherwise. The caller should move or copy these
        files to a permanent location if needed.

    Args:
        input_audio_file: The path to the input audio file.
        target_duration_seconds: The desired maximum duration for each output
            file in seconds.
        silence_duration: The minimum duration in seconds to be considered
            silence.
        noise_threshold_db: The volume level in dB below which audio is
            considered silent (e.g., -30).

    Returns:
        A list of full, absolute paths to the created audio files on success.
        Returns an empty list `[]` if any error occurs.
    """
    def _get_duration(file_path: str) -> float or None:
        """Fetches the total duration of a media file using ffprobe."""
        command = [
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', file_path
        ]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, check=True
            )
            return float(result.stdout.strip())
        except (subprocess.CalledProcessError, ValueError, FileNotFoundError) as e:
            my_log.log2(
                f"my_split_audio: ERROR - ffprobe failed for '{file_path}'. "
                f"Command: {' '.join(command)}. Exception: {e}"
            )
            return None
    if not os.path.exists(input_audio_file):
        my_log.log2(f"my_split_audio: ERROR - Input file not found: {input_audio_file}")
        return []

    # Create a persistent temporary directory for the final output files.
    try:
        output_dir = tempfile.mkdtemp()
    except Exception as e:
        my_log.log2(f"my_split_audio: ERROR - Could not create final output temp dir: {e}")
        return []

    try:
        # Step 1: Detect silence periods
        detect_cmd = [
            'ffmpeg', '-i', input_audio_file,
            '-af', f'silencedetect=n={noise_threshold_db}dB:d={silence_duration}',
            '-f', 'null', '-'
        ]
        result = subprocess.run(detect_cmd, capture_output=True, text=True, check=False)
        stderr_output = result.stderr
        silence_starts = [float(t) for t in re.findall(r"silence_start: (\d+\.?\d*)", stderr_output)]
        silence_ends = [float(t) for t in re.findall(r"silence_end: (\d+\.?\d*)", stderr_output)]

        # Step 2: Define and split audible segments
        total_duration = _get_duration(input_audio_file)
        if total_duration is None:
            raise ValueError("Could not determine audio duration.")

        audible_segments, last_silence_end = [], 0.0
        if not silence_starts:
            audible_segments.append({'start': 0.0, 'end': total_duration})
        else:
            for start, end in zip(silence_starts, silence_ends):
                if start > last_silence_end:
                    audible_segments.append({'start': last_silence_end, 'end': start})
                last_silence_end = end
            if total_duration > last_silence_end:
                audible_segments.append({'start': last_silence_end, 'end': total_duration})

        processed_segments = []
        for seg in audible_segments:
            seg_duration = seg['end'] - seg['start']
            if seg_duration > target_duration_seconds:
                num_chunks = int(seg_duration // target_duration_seconds) + 1
                chunk_duration = seg_duration / num_chunks
                current_start = seg['start']
                for _ in range(num_chunks):
                    chunk_end = min(current_start + chunk_duration, seg['end'])
                    processed_segments.append({'start': current_start, 'end': chunk_end})
                    current_start = chunk_end
                    if current_start >= seg['end']: break
            else:
                processed_segments.append(seg)
        audible_segments = processed_segments

        # Step 3: Group segments
        final_groups, current_group, group_duration = [], [], 0.0
        for seg in audible_segments:
            seg_duration = seg['end'] - seg['start']
            if current_group and group_duration + seg_duration > target_duration_seconds:
                final_groups.append(current_group)
                current_group = [seg]
                group_duration = seg_duration
            else:
                current_group.append(seg)
                group_duration += seg_duration
        if current_group:
            final_groups.append(current_group)

        # Step 4: Extract and concatenate files
        created_files = []
        base_name, ext = os.path.splitext(os.path.basename(input_audio_file))

        # This inner temporary directory will be deleted after each group is processed
        with tempfile.TemporaryDirectory(prefix="processing_") as temp_processing_dir:
            for i, group in enumerate(final_groups):
                concat_list_path = os.path.join(temp_processing_dir, f"concat_{i}.txt")
                with open(concat_list_path, 'w', encoding='utf-8') as f:
                    for j, segment in enumerate(group):
                        temp_path = os.path.join(temp_processing_dir, f"temp_{i}_{j}{ext}")
                        extract_cmd = [
                            'ffmpeg', '-y', '-i', input_audio_file,
                            '-ss', str(segment['start']), '-to', str(segment['end']),
                            '-c', 'copy', temp_path
                        ]
                        subprocess.run(extract_cmd, check=True, capture_output=True)
                        f.write(f"file '{os.path.abspath(temp_path)}'\n")

                # The final file is written to the persistent temporary directory
                output_filename = os.path.join(output_dir, f"{base_name}_part_{i+1:02d}{ext}")
                concat_cmd = [
                    'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                    '-i', concat_list_path, '-c', 'copy', output_filename
                ]
                subprocess.run(concat_cmd, check=True, capture_output=True)
                created_files.append(output_filename)

        return sorted(created_files)

    except Exception as e:
        # If anything fails, clean up the persistent temporary directory we created
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)

        if isinstance(e, subprocess.CalledProcessError):
            err_msg = e.stderr.decode('utf-8', errors='ignore')
            my_log.log2(
                f"my_split_audio: ERROR - Ffmpeg failed. "
                f"Command: {' '.join(e.cmd)}. Stderr: {err_msg}"
            )
        else:
            my_log.log2(
                f"my_split_audio: ERROR - An unexpected error of type "
                f"{type(e).__name__} occurred: {e}"
            )

        return []

if __name__ == '__main__':
    # Make sure 'my_log.py' is in the same directory.
    input_audio = r'C:\Users\user\Downloads\1.ogg'

    if os.path.exists(input_audio):
        created_files = split_audio_by_silence(
            input_audio_file=input_audio,
            target_duration_seconds=840
        )

        if created_files:
            print("--- Success! Files created in a system temporary directory: ---")
            for file_path in created_files:
                print(f" -> {file_path}")

            print("\nNOTE: These files are in a temporary folder.")
            print("You should move them to a permanent location if you want to keep them.")
        else:
            print("\n--- Failure. No files were created. Check 'my_log.log' for details. ---")
    else:
        print(f"Error: Input file not found at: {input_audio}")
