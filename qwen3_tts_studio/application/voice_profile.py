"""Portable, tensor-only voice profiles and non-destructive file operations."""

# Copyright (c) 2026 Nendis. SPDX-License-Identifier: MIT

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from .workspace import CloningMode


class VoiceCancelled(Exception):
    """Cooperative cancellation at supported operation boundaries."""


def check_cancel(cancelled) -> None:
    if cancelled():
        raise VoiceCancelled()


@dataclass(frozen=True)
class VoiceProfile:
    identifier: str
    mode: CloningMode
    compatibility: dict
    items: tuple[dict, ...]
    created: str
    source_reference: Path | None = None
    imported_from: Path | None = None


def model_identity(models: Path) -> dict:
    directory = models / "Qwen3-TTS-12Hz-1.7B-Base"
    config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    tokenizer = json.loads((directory / "speech_tokenizer/config.json").read_text(encoding="utf-8"))
    if (config.get("tts_model_type") != "base" or config.get("tts_model_size") != "1b7"
            or config.get("tokenizer_type") != "qwen3_tts_tokenizer_12hz"):
        raise ValueError("The local model must be Qwen3-TTS-12Hz-1.7B-Base.")
    digest = hashlib.sha256(json.dumps([config, tokenizer], sort_keys=True).encode()).hexdigest()
    return {
        "model": "Qwen3-TTS-12Hz-1.7B-Base", "configuration_sha256": digest,
        "embedding_size": config["speaker_encoder_config"]["enc_dim"],
        "code_groups": config["talker_config"]["num_code_groups"],
        "semantic_vocab": tokenizer["decoder_config"]["semantic_codebook_size"],
        "acoustic_vocab": tokenizer["decoder_config"]["codebook_size"],
    }


def validate_items(items, mode: CloningMode, identity: dict) -> tuple[dict, ...]:
    # Torch is imported only in a background operation, never during UI startup.
    import torch

    if not isinstance(items, (list, tuple)) or len(items) != 1:
        raise ValueError("A profile must contain exactly one voice clone prompt item.")
    item = items[0]
    fields = {"ref_code", "ref_spk_embedding", "x_vector_only_mode", "icl_mode", "ref_text"}
    if not isinstance(item, dict) or set(item) != fields:
        raise ValueError("Invalid voice clone prompt structure.")
    x_vector = mode == CloningMode.X_VECTOR_ONLY
    if (type(item["x_vector_only_mode"]) is not bool or type(item["icl_mode"]) is not bool
            or item["x_vector_only_mode"] != x_vector or item["icl_mode"] == x_vector):
        raise ValueError("The profile mode and prompt flags disagree.")
    embedding = item["ref_spk_embedding"]
    if (not isinstance(embedding, torch.Tensor) or embedding.layout != torch.strided
            or embedding.shape != (identity["embedding_size"],)
            or not embedding.is_floating_point() or not torch.isfinite(embedding).all()):
        raise ValueError("Invalid speaker embedding.")
    code, text = item["ref_code"], item["ref_text"]
    if x_vector:
        if code is not None or text is not None:
            raise ValueError("X-Vector Only profiles must not contain reference codes or text.")
    else:
        if not isinstance(text, str) or not text.strip() or len(text) > 100_000:
            raise ValueError("An ICL profile requires reference text.")
        if (not isinstance(code, torch.Tensor) or code.layout != torch.strided
                or code.dtype not in (torch.int32, torch.int64) or code.ndim != 2
                or not 0 < code.shape[0] <= 45_000 or code.shape[1] != identity["code_groups"]):
            raise ValueError("Invalid reference speech codes.")
        if ((code < 0).any() or (code[:, 0] >= identity["semantic_vocab"]).any()
                or (code[:, 1:] >= identity["acoustic_vocab"]).any()):
            raise ValueError("Reference codes exceed the model vocabulary.")
    return ({**item, "ref_spk_embedding": embedding.detach().cpu().contiguous().clone(),
             "ref_code": code.detach().cpu().contiguous().clone() if code is not None else None},)


def profile_from_prompt(prompt, mode: CloningMode, models: Path, reference: Path) -> VoiceProfile:
    fields = ("ref_code", "ref_spk_embedding", "x_vector_only_mode", "icl_mode", "ref_text")
    identity = model_identity(models)
    items = validate_items([{name: getattr(item, name) for name in fields} for item in prompt], mode, identity)
    return VoiceProfile(uuid4().hex, mode, identity, items, datetime.now(timezone.utc).isoformat(), reference)


def _commit_file(temporary: Path, destination: Path, overwrite: bool) -> None:
    if overwrite:
        os.replace(temporary, destination)
    else:
        # A same-directory hard link commits atomically and fails if another
        # process created the destination after the user's file selection.
        os.link(temporary, destination)


def write_copy(destination: Path, writer, overwrite: bool, cancelled) -> Path:
    destination = destination.expanduser().absolute()
    if not destination.parent.is_dir():
        raise FileNotFoundError(f"The destination folder does not exist: {destination.parent}")
    if destination.exists() and not overwrite:
        raise FileExistsError(f"The destination already exists: {destination}")
    with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        check_cancel(cancelled)
        writer(temporary)
        check_cancel(cancelled)
        _commit_file(temporary, destination, overwrite)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def save_profile(profile: VoiceProfile, destination: Path, overwrite: bool, cancelled) -> Path:
    import torch

    if destination.suffix.lower() != ".pt":
        raise ValueError("Voice profiles must use the .pt extension.")
    payload = {
        "format": "qwen3-tts-studio-voice", "version": 1,
        "identifier": profile.identifier, "mode": profile.mode.value,
        "compatibility": profile.compatibility, "created": profile.created,
        "items": list(validate_items(profile.items, profile.mode, profile.compatibility)),
    }
    return write_copy(destination, lambda path: torch.save(payload, path), overwrite, cancelled)


def load_profile(path: Path, models: Path, cancelled) -> VoiceProfile:
    import torch

    path = path.resolve(strict=True)
    if path.suffix.lower() != ".pt" or not path.is_file() or not 0 < path.stat().st_size <= 128 * 1024 * 1024:
        raise ValueError("Choose a .pt voice profile smaller than 128 MiB.")
    identity = model_identity(models)
    check_cancel(cancelled)
    payload = torch.load(path, map_location="cpu", weights_only=True)
    check_cancel(cancelled)
    if not isinstance(payload, dict) or set(payload) != {
        "format", "version", "identifier", "mode", "compatibility", "created", "items"
    }:
        raise ValueError("This file is not a Qwen3 TTS Studio voice profile.")
    if payload["format"] != "qwen3-tts-studio-voice" or type(payload["version"]) is not int or payload["version"] != 1:
        raise ValueError("Unsupported voice profile format or version.")
    if payload["compatibility"] != identity:
        raise ValueError("This profile is incompatible with the local Base model configuration.")
    if (not isinstance(payload["identifier"], str) or len(payload["identifier"]) != 32
            or any(c not in "0123456789abcdef" for c in payload["identifier"])
            or not isinstance(payload["created"], str) or len(payload["created"]) > 100):
        raise ValueError("Invalid profile metadata.")
    mode = CloningMode(payload["mode"])
    items = validate_items(payload["items"], mode, identity)
    check_cancel(cancelled)
    return VoiceProfile(payload["identifier"], mode, identity, items, payload["created"], imported_from=path)


def export_wav(recording, destination: Path, overwrite: bool, cancelled) -> Path:
    """Only explicit export persists the current RAM-only generated recording."""
    if destination.suffix.lower() != ".wav":
        raise ValueError("Exported recordings must use the .wav extension.")
    def copy(temporary):
        data = memoryview(recording.wav_data)
        with temporary.open("wb") as writer:
            for offset in range(0, len(data), 1024 * 1024):
                check_cancel(cancelled)
                writer.write(data[offset:offset + 1024 * 1024])
    return write_copy(destination, copy, overwrite, cancelled)
