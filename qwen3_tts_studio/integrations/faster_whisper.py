"""Lazy, offline Faster Whisper Small adapter; no Qt or imports at startup."""

# Copyright (c) 2026 Nendis. SPDX-License-Identifier: MIT

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Callable

from .windows_cuda import configure_cuda_dlls


class TranscriptionCancelled(Exception):
    """A superseded request must not publish a result."""


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    language: str
    language_probability: float
    device: str
    compute_type: str = ""
    gpu_error: str = ""


def small_model_directory(models: Path) -> Path:
    """Resolve the existing direct folder or Small cache's active local revision."""
    root = models / "faster-whisper"
    directory = root
    if not (directory / "model.bin").is_file():
        cache = root / "models--Systran--faster-whisper-small"
        revision_file = cache / "refs" / "main"
        if not revision_file.is_file():
            raise FileNotFoundError(f"Local Faster Whisper Small model not found in {root}.")
        revision = revision_file.read_text(encoding="utf-8").strip()
        if not revision or any(char not in "0123456789abcdef" for char in revision):
            raise ValueError(f"Invalid local Small model revision in {revision_file}.")
        directory = cache / "snapshots" / revision
    # Requiring the local tokenizer prevents Faster Whisper's online fallback.
    for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt"):
        if not (directory / name).is_file():
            raise FileNotFoundError(f"Local Small model is incomplete: missing {directory / name}.")
    return directory.resolve()


class FasterWhisperTranscriber:
    """One serial worker owns and reuses this adapter's resident model."""

    def __init__(self, models: Path):
        self.models = models
        self._model = None
        self.device = ""
        self.compute_type = ""
        self.gpu_error = ""

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @staticmethod
    def _check_cancel(cancelled: Callable[[], bool]) -> None:
        if cancelled():
            raise TranscriptionCancelled()

    def _load(self, device: str, cancelled, report) -> None:
        self._check_cancel(cancelled)
        directory = small_model_directory(self.models)
        import ctranslate2
        from faster_whisper import WhisperModel

        supported = ctranslate2.get_supported_compute_types(device)
        preferred = ("float16", "int8_float16", "float32") if device == "cuda" else ("int8", "float32")
        compute_type = next((kind for kind in preferred if kind in supported), "default")
        target = "GPU (CUDA)" if device == "cuda" else "CPU"
        report(f"Loading Small model on {target}")
        self._model = WhisperModel(str(directory), device=device, compute_type=compute_type,
                                  local_files_only=True, cpu_threads=4, num_workers=1)
        self.device = self._model.model.device
        self.compute_type = self._model.model.compute_type
        logging.getLogger(__name__).info("Faster Whisper initialized: device=%s, compute_type=%s",
                                        self.device, self.compute_type)
        self._check_cancel(cancelled)

    def transcribe(self, reference: Path, cancelled, report) -> TranscriptionResult:
        self._check_cancel(cancelled)
        if self._model is None:
            self.gpu_error = ""
            dll_ready = True
            try:
                configure_cuda_dlls()
            except OSError as error:
                dll_ready = False
                self._gpu_failed(f"Windows CUDA DLL setup failed: {error}", report)
            import ctranslate2

            try:
                use_cuda = dll_ready and ctranslate2.get_cuda_device_count() > 0
            except RuntimeError as error:
                self._gpu_failed(f"CUDA device initialization failed: {error}", report)
                use_cuda = False
            if use_cuda:
                try:
                    self._load("cuda", cancelled, report)
                except RuntimeError as error:
                    self.release()
                    self._gpu_failed(f"CUDA model initialization failed: {error}", report)
                    self._load("cpu", cancelled, report)
            else:
                self._load("cpu", cancelled, report)
        try:
            return self._recognize(reference, cancelled, report)
        except RuntimeError as error:
            if self.device != "cuda":
                raise
            self.release()
            self._gpu_failed(f"CUDA transcription failed: {error}", report)
            self._load("cpu", cancelled, report)
            return self._recognize(reference, cancelled, report)

    def _recognize(self, reference, cancelled, report) -> TranscriptionResult:
        self._check_cancel(cancelled)
        device_label = "GPU (CUDA)" if self.device == "cuda" else "CPU"
        report(f"Transcribing · {device_label} · detecting language")
        segments, info = self._model.transcribe(str(reference), language=None, task="transcribe")
        self._check_cancel(cancelled)
        report(f"Transcribing · {device_label} · {info.language}")
        text = []
        for segment in segments:
            self._check_cancel(cancelled)
            if segment.text.strip():
                text.append(segment.text.strip())
        self._check_cancel(cancelled)
        logging.getLogger(__name__).info("Transcription completed: device=%s, compute_type=%s, language=%s",
                                        self.device, self.compute_type, info.language)
        return TranscriptionResult(" ".join(text), info.language, info.language_probability,
                                   self.device, self.compute_type, self.gpu_error)

    def _gpu_failed(self, message: str, report) -> None:
        self.gpu_error = message
        logging.getLogger(__name__).warning("%s; using CPU fallback", message)
        report(f"CUDA unavailable; using CPU ({message})")

    def release(self) -> None:
        if self._model is not None:
            self._model.model.unload_model()
            self._model = None
        self.device = ""
        self.compute_type = ""
