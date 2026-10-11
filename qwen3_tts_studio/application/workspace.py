"""Repository paths and the in-memory voice preparation session."""

# Copyright (c) 2026 Nendis. SPDX-License-Identifier: MIT

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkspacePaths:
    root: Path

    @classmethod
    def from_source(cls) -> "WorkspacePaths":
        return cls(Path(__file__).resolve().parents[2])

    @property
    def models(self) -> Path:
        return self.root / "models"

    @property
    def samples(self) -> Path:
        return self.root / "samples"

    @property
    def output(self) -> Path:
        return self.root / "output"


def validate_reference(path: Path) -> Path:
    """Validate a selection; waveform preparation separately checks decoding."""
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError("Select an existing audio file, not a folder.")
    if resolved.suffix.lower() not in {".wav", ".ogg"}:
        raise ValueError("Select a WAV or OGG reference recording.")
    # Opening without reading audio verifies access without decoding or copying it.
    with resolved.open("rb"):
        pass
    return resolved


@dataclass
class WorkspaceSession:
    reference: Path | None = None
    transcript: str = ""
    speech_text: str = ""

    @property
    def has_drafts(self) -> bool:
        return bool(self.transcript or self.speech_text)

    @property
    def has_content(self) -> bool:
        return self.reference is not None or self.has_drafts

    def clear_reference(self) -> None:
        self.reference = None
        self.transcript = ""

    def new_voice(self) -> None:
        self.clear_reference()
        self.speech_text = ""

    def select_reference(self, path: Path) -> None:
        self.apply_reference(validate_reference(path))

    def apply_reference(self, reference: Path) -> None:
        """Commit a reference already validated by background preparation."""
        if reference != self.reference:
            self.reference = reference
            # A transcript belongs to its reference, never to a replacement file.
            self.transcript = ""
