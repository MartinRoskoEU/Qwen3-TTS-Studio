"""Immutable generated PCM, RAM-only WAV playback data, and waveform preparation."""

# Copyright (c) 2026 Nendis. SPDX-License-Identifier: MIT

from dataclasses import dataclass
from io import BytesIO
from typing import Mapping

from .decoding import DecodeCancelled


@dataclass(frozen=True, eq=False)
class MemoryRecording:
    pcm: bytes  # Interleaved little-endian float32; never mutated by playback.
    sample_rate: int
    channels: int
    duration_ms: int
    lower: tuple[float, ...]
    upper: tuple[float, ...]
    wav_data: bytes
    suggested_filename: str
    metadata: Mapping


def prepare_memory_recording(audio, sample_rate, filename, metadata, cancelled=lambda: False,
                             report=lambda stage: None) -> MemoryRecording:
    """Encode and reduce in the calling worker, without filesystem access."""
    import numpy as np
    import soundfile as sf
    from types import MappingProxyType

    def check():
        if cancelled():
            raise DecodeCancelled()

    check()
    samples = np.asarray(audio, dtype="<f4")
    if (samples.ndim != 1 or not samples.size or not np.isfinite(samples).all()
            or type(sample_rate) is not int or sample_rate <= 0):
        raise ValueError("Generation returned empty or invalid PCM audio.")
    report("Saving audio to memory...")
    pcm = samples.tobytes()
    with BytesIO() as stream:
        # IEEE float WAV preserves Qwen's float32 PCM without quantization.
        sf.write(stream, samples, sample_rate, format="WAV", subtype="FLOAT")
        wav_data = stream.getvalue()
    check()
    report("Preparing waveform...")
    bin_frames = max(1, (samples.size + 4095) // 4096)
    starts = np.arange(0, samples.size, bin_frames)
    lower = tuple(map(float, np.minimum.reduceat(samples, starts)))
    upper = tuple(map(float, np.maximum.reduceat(samples, starts)))
    check()
    return MemoryRecording(pcm, sample_rate, 1, max(1, round(samples.size * 1000 / sample_rate)),
                           lower, upper, wav_data, filename, MappingProxyType(dict(metadata)))
