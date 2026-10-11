"""Validated, immutable Qwen-TTS 0.1.1 talker generation controls."""

# Copyright (c) 2026 Nendis. SPDX-License-Identifier: MIT

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path


@dataclass(frozen=True)
class GenerationSettings:
    temperature: float = 0.9
    top_p: float = 1.0
    top_k: int = 50
    repetition_penalty: float = 1.05
    language: str = "Auto"

    def validate(self, languages=None):
        for name, low, high in (("temperature", .01, 5), ("top_p", .01, 1),
                                ("repetition_penalty", .01, 5)):
            value = getattr(self, name)
            if (type(value) not in (int, float) or not math.isfinite(value)
                    or not low <= value <= high):
                raise ValueError(f"{name} must be a finite number between {low} and {high}.")
        if type(self.top_k) is not int or not 0 <= self.top_k <= 3072:
            raise ValueError("top_k must be an integer between 0 and 3072 (0 disables filtering).")
        if not isinstance(self.language, str) or not self.language.strip():
            raise ValueError("Select a generation language.")
        if languages is not None and self.language.lower() not in {s.lower() for s in languages}:
            raise ValueError(f"The local model does not support language: {self.language}")
        return self

    def arguments(self):
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, values, languages=None):
        if not isinstance(values, dict) or set(values) != set(cls.__dataclass_fields__):
            raise ValueError("Invalid advanced generation settings fields.")
        return cls(**values).validate(languages)


def local_generation_defaults(models: Path):
    """Read metadata only; no Torch import, model loading, or network access.

    Fallbacks are the inspected SDK's defaults when local metadata is absent.
    Language discovery mirrors the installed model's get_supported_languages().
    """
    directory = models / "Qwen3-TTS-12Hz-1.7B-Base"
    defaults = GenerationSettings().arguments()
    path = directory / "generation_config.json"
    if path.is_file():
        config = json.loads(path.read_text(encoding="utf-8"))
        defaults.update({key: config[key] for key in defaults if key != "language" and key in config})
    languages = ["Auto"]
    path = directory / "config.json"
    if path.is_file():
        config = json.loads(path.read_text(encoding="utf-8"))
        languages += [key.capitalize() for key in config["talker_config"]["codec_language_id"]
                      if "dialect" not in key and key != "auto"]
    return GenerationSettings.from_dict(defaults, languages), tuple(languages)
