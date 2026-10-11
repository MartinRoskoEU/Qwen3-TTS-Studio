"""Lazy, offline Qwen3-TTS Base preparation and cached-profile generation."""

# Copyright (c) 2026 Nendis. SPDX-License-Identifier: MIT

from dataclasses import dataclass
from datetime import datetime, timezone
import gc
import logging
from pathlib import Path
import re
import time
from uuid import uuid4

from ..application.voice_profile import check_cancel, model_identity, profile_from_prompt
from ..application.workspace import CloningMode, validate_reference
from ..audio.memory import MemoryRecording, prepare_memory_recording


@dataclass(frozen=True)
class GeneratedSpeech:
    recording: MemoryRecording
    profile_identifier: str
    text: str
    seconds: float
    device: str
    precision: str
    attention: str


class QwenVoiceModel:
    def __init__(self, models: Path):
        self.models = models
        self._model = None
        self.device = ""
        self.precision = ""
        self.attention = ""
        self.gpu_error = ""

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def _ensure_model(self, cancelled, report):
        check_cancel(cancelled)
        if self.loaded:
            return self._model
        directory = self.models / "Qwen3-TTS-12Hz-1.7B-Base"
        model_identity(self.models)
        for name in ("model.safetensors", "tokenizer_config.json", "vocab.json", "merges.txt",
                     "preprocessor_config.json", "generation_config.json",
                     "speech_tokenizer/model.safetensors", "speech_tokenizer/preprocessor_config.json"):
            if not (directory / name).is_file():
                raise FileNotFoundError(f"The local Qwen3 Base model is incomplete: missing {directory / name}")
        report("Loading model...")
        import torch
        from qwen_tts import Qwen3TTSModel

        cuda = torch.cuda.is_available()
        dtype = torch.bfloat16 if cuda and torch.cuda.is_bf16_supported() else torch.float16 if cuda else torch.float32
        attention = "sdpa" if hasattr(torch.nn.functional, "scaled_dot_product_attention") else "eager"
        def load(device, precision):
            report(f"Loading model... · {'GPU (CUDA)' if device.startswith('cuda') else 'CPU'} · {str(precision).removeprefix('torch.')} · {attention.upper()}")
            return Qwen3TTSModel.from_pretrained(
                str(directory.resolve()), device_map=device, dtype=precision,
                attn_implementation=attention, local_files_only=True,
            )
        try:
            self._model = load("cuda:0" if cuda else "cpu", dtype)
        except (RuntimeError, OSError) as error:
            if not cuda:
                raise
            self.gpu_error = f"{type(error).__name__}: {error}"
            logging.getLogger(__name__).warning("Qwen3 CUDA initialization failed; using CPU: %s", self.gpu_error)
            check_cancel(cancelled)
            gc.collect()
            torch.cuda.empty_cache()
            self._model = load("cpu", torch.float32)
        self.device = str(self._model.device)
        self.precision = str(self._model.model.dtype).removeprefix("torch.")
        self.attention = self._model.model.config._attn_implementation
        check_cancel(cancelled)
        return self._model

    def description(self) -> str:
        device = "GPU (CUDA)" if self.device.startswith("cuda") else "CPU"
        return f"{device} · {self.precision} · {self.attention.upper()}"

    def prepare(self, arguments: dict, cancelled, report):
        report("Validating reference audio...")
        reference = validate_reference(Path(arguments["ref_audio"]))
        mode = CloningMode.X_VECTOR_ONLY if arguments["x_vector_only_mode"] else CloningMode.ICL
        model = self._ensure_model(cancelled, report)
        report(f"Creating voice profile... · {self.description()}")
        prompt = model.create_voice_clone_prompt(**{**arguments, "ref_audio": str(reference)})
        check_cancel(cancelled)
        return profile_from_prompt(prompt, mode, self.models, reference)

    def generate(self, profile, text: str, settings, cancelled, report):
        text = text.strip()
        if not text:
            raise ValueError("Enter nonempty Speech Text before generating.")
        if profile.compatibility != model_identity(self.models):
            raise ValueError("The voice profile is incompatible with the local model.")
        model = self._ensure_model(cancelled, report)
        settings.validate(model.get_supported_languages())
        parameters = settings.arguments()
        import numpy as np
        from qwen_tts import VoiceClonePromptItem

        report(f"Preparing generation inputs... · {self.description()}")

        # Reconstruct the public prompt item rather than the SDK's dict shortcut:
        # ICL needs ref_text as well as the codes and speaker embedding.
        prompt = [VoiceClonePromptItem(**{
            **item,
            "ref_spk_embedding": item["ref_spk_embedding"].to(model.device),
            "ref_code": item["ref_code"].to(model.device) if item["ref_code"] is not None else None,
        }) for item in profile.items]
        report(f"Generating speech... · {self.description()}")
        started = time.monotonic()
        check_cancel(cancelled)
        # Qwen-TTS 0.1.1's core generate() does not forward stopping_criteria
        # from **kwargs to the talker. Keep this native call intact; cancellation
        # is checked immediately afterwards, before any audio is published.
        try:
            wavs, sample_rate = model.generate_voice_clone(
                text=text, voice_clone_prompt=prompt, **parameters,
                non_streaming_mode=True, do_sample=True, subtalker_dosample=True,
            )
        except RuntimeError as error:
            import torch
            if isinstance(error, torch.cuda.OutOfMemoryError):
                torch.cuda.empty_cache()
                raise RuntimeError("GPU memory is exhausted. Your voice profile and drafts are kept. Close other GPU applications or use shorter Speech Text, then try again.") from error
            raise
        seconds = time.monotonic() - started
        check_cancel(cancelled)
        if len(wavs) != 1 or not isinstance(sample_rate, int) or sample_rate <= 0:
            raise ValueError("Qwen3 returned an invalid audio result.")
        audio = np.asarray(wavs[0], dtype=np.float32)
        if audio.ndim != 1 or not audio.size or not np.isfinite(audio).all():
            raise ValueError("Qwen3 returned empty or invalid audio.")
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", text[:36]).strip("-") or "speech"
        name = f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{slug}-{uuid4().hex[:12]}.wav"
        metadata = {
            "model": profile.compatibility, "profile_id": profile.identifier, "mode": profile.mode.value,
            "reference": str(profile.source_reference) if profile.source_reference else None,
            "text": text, "created": datetime.now(timezone.utc).isoformat(),
            "device": self.device, "precision": self.precision, "attention": self.attention,
            "generation_seconds": seconds, "duration_seconds": audio.size / sample_rate,
            "real_time_factor": seconds / (audio.size / sample_rate),
            "generation_parameters": {**model.generate_defaults, **parameters, "non_streaming_mode": True,
                                      "do_sample": True, "subtalker_dosample": True},
        }
        recording = prepare_memory_recording(
            audio, sample_rate, name, metadata, cancelled,
            lambda stage: report(f"{stage} · {self.description()}"),
        )
        check_cancel(cancelled)
        return GeneratedSpeech(recording, profile.identifier, text, seconds, self.device, self.precision, self.attention)

    def release(self) -> None:
        if self._model is None:
            return
        self._model = None
        gc.collect()
        import torch
        if self.device.startswith("cuda"):
            torch.cuda.empty_cache()
