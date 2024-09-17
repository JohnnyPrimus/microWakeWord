# coding=utf-8
# Copyright 2024 Kevin Ahrendt.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import numpy as np
import tensorflow as tf
import webrtcvad

from tensorflow.lite.experimental.microfrontend.python.ops import (
    audio_microfrontend_op as frontend_op,
)
from scipy.io import wavfile

from microwakeword.audio.cGenerateFeatures import generate_features

from silero_vad import load_silero_vad, get_speech_timestamps

model = load_silero_vad()



def generate_features_for_clip(audio_samples: np.ndarray, step_ms: int = 20, use_c: bool = True):
    """Generates spectrogram features for the given audio data.

    Args:
        audio_samples (numpy.ndarray): The clip's audio samples.
        step_ms (int, optional): The window step size in ms. Defaults to 20.

    Returns:
        numpy.ndarray: The spectrogram features for the provided audio clip.
    """

    # Convert any float formatted audio data to an int16 array
    if audio_samples.dtype in (np.float32, np.float64):
        audio_samples = (audio_samples * 32767).astype(np.int16)

    if use_c:
        return generate_features(audio_samples)

    with tf.device("/cpu:0"):
        # The default settings match the TFLM preprocessor settings.
        # Preproccesor model is available from the tflite-micro repository, accessed December 2023.
        micro_frontend = frontend_op.audio_microfrontend(
            tf.convert_to_tensor(audio_samples),
            sample_rate=16000,
            window_size=30,
            window_step=step_ms,
            num_channels=40,
            upper_band_limit=7500,
            lower_band_limit=125,
            enable_pcan=True,
            min_signal_remaining=0.05,
            out_scale=1,
            out_type=tf.uint16,
        )

        spectrogram = micro_frontend.numpy()
        return spectrogram


def save_clip(audio_samples: np.ndarray, output_file: str) -> None:
    """Saves an audio clip's sample as a wave file.

    Args:
        audio_samples (numpy.ndarray): The clip's audio samples.
        output_file (str): Path to the desired output file.
    """
    if audio_samples.dtype in (np.float32, np.float64):
        audio_samples = (audio_samples * 32767).astype(np.int16)
    wavfile.write(output_file, 16000, audio_samples)

def remove_silence_silero(
    audio_data: np.ndarray,
    threshold: float = 0.8,
    speech_pad_ms: int = 0, # 30,
    min_silence_duration_ms: int = 100,
) -> np.ndarray:
    """ Uses Silero VAD to remove siilence from the audio data

    Args:
        audio_data (np.ndarray): The input clip's audio samples.

    Returns:
        np.ndarray: Array with the trimmed audio clip's samples.
    """
    integer_type = audio_data.dtype == np.int16
    if integer_type:
        audio_data = (audio_data/32767).astype(np.float32)
    
    # # Pad to make sure there is enough time after the speech for hte min_silence_duratioN_ms to kick in
    # audio_data = np.pad(audio_data, (0,int(2*min_silence_duration_ms/1000*16000)), 'constant', constant_values=(0,0))
        
    filtered_audio = []    
    speech_timestamps = get_speech_timestamps(audio_data, model, threshold=threshold, speech_pad_ms=speech_pad_ms, min_silence_duration_ms=min_silence_duration_ms)
    
    for timestamp in speech_timestamps:
        filtered_audio.extend(audio_data[timestamp['start'] : timestamp['end']].tolist())
    
    if integer_type:
        filtered_audio = np.array(filtered_audio*32767).astype(np.int16)
    else:
        filtered_audio = np.array(filtered_audio)
    return filtered_audio

def remove_silence_webrtc(
    audio_data: np.ndarray,
    frame_duration: float = 0.030,
    sample_rate: int = 16000,
    min_start: int = 2000,
) -> np.ndarray:
    """Uses webrtc voice activity detection to remove silence from the clips

    Args:
        audio_data (numpy.ndarray): The input clip's audio samples.
        frame_duration (float): The frame_duration for webrtcvad. Defaults to 0.03.
        sample_rate (int): The audio's sample rate. Defaults to 16000.
        min_start: (int): The number of audio samples from the start of the clip to always include. Defaults to 2000.

    Returns:
        numpy.ndarray: Array with the trimmed audio clip's samples.
    """
    vad = webrtcvad.Vad(0)

    # webrtcvad expects int16 arrays as input, so convert if audio_data is a float
    float_type = audio_data.dtype in (np.float32, np.float64)
    if float_type:
        audio_data = (audio_data * 32767).astype(np.int16)

    filtered_audio = audio_data[0:min_start].tolist()

    step_size = int(sample_rate * frame_duration)

    for i in range(min_start, audio_data.shape[0] - step_size, step_size):
        vad_detected = vad.is_speech(
            audio_data[i : i + step_size].tobytes(), sample_rate
        )
        if vad_detected:
            # If voice activity is detected, add it to filtered_audio
            filtered_audio.extend(audio_data[i : i + step_size].tolist())

    # If the original audio data was a float array, convert back
    if float_type:
        trimmed_audio = np.array(filtered_audio)
        return np.array(trimmed_audio / 32767).astype(np.float32)

    return np.array(filtered_audio).astype(np.int16)
