"""Validate and reduce recordings to a bounded waveform envelope."""

# Copyright (c) 2026 Nendis. SPDX-License-Identifier: MIT

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..application.workspace import validate_reference


class DecodeCancelled(Exception):
    """A superseded import or application shutdown interrupted preparation."""


@dataclass(frozen=True)
class AudioRecording:
    path: Path
    duration_ms: int
    sample_rate: int
    channels: int
    lower: tuple[float, ...]
    upper: tuple[float, ...]


def prepare_waveform(path: Path, cancelled: Callable[[], bool] = lambda: False) -> AudioRecording:
    """Read blocks, retaining at most 4096 peak bins across all channels.

    Imports and all file I/O happen in the caller's worker. Recordings are never
    written or converted. Opposite-phase channels cannot cancel the envelope.
    """
    import numpy as np
    import soundfile as sf

    def check_cancelled() -> None:
        if cancelled():
            raise DecodeCancelled()

    check_cancelled()
    reference = validate_reference(path)
    with sf.SoundFile(str(reference)) as audio:
        formats = {".wav": {"WAV", "WAVEX", "RF64"}, ".ogg": {"OGG"}}
        if audio.format not in formats[reference.suffix.lower()]:
            raise ValueError("The file contents do not match its WAV or OGG extension.")
        if audio.frames <= 0 or audio.samplerate <= 0 or audio.channels <= 0:
            raise ValueError("The recording contains no decodable audio samples.")
        bin_frames = max(1, (audio.frames + 4095) // 4096)
        bins = (audio.frames + bin_frames - 1) // bin_frames
        lower = np.full(bins, np.inf, dtype=np.float32)
        upper = np.full(bins, -np.inf, dtype=np.float32)
        offset = 0
        # Bound block memory for multichannel recordings as well as long files.
        block_frames = max(1, 65536 // audio.channels)
        while True:
            check_cancelled()
            block = audio.read(block_frames, dtype="float32", always_2d=True)
            if len(block) == 0:
                break
            if not np.isfinite(block).all():
                raise ValueError("The recording contains invalid audio sample values.")
            indexes = (np.arange(len(block), dtype=np.int64) + offset) // bin_frames
            if indexes[-1] >= bins:
                raise ValueError("The recording changed while it was being read. Import it again.")
            np.minimum.at(lower, indexes, block.min(axis=1))
            np.maximum.at(upper, indexes, block.max(axis=1))
            offset += len(block)
        check_cancelled()
        if offset != audio.frames or not np.isfinite(lower).all():
            raise ValueError("The recording is incomplete or could not be decoded fully.")
        return AudioRecording(
            reference, max(1, round(audio.frames * 1000 / audio.samplerate)),
            audio.samplerate, audio.channels, tuple(map(float, lower)), tuple(map(float, upper)),
        )
