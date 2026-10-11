"""Repository paths and the in-memory voice preparation session."""

# Copyright (c) 2026 Nendis. SPDX-License-Identifier: MIT

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .voice_profile import VoiceProfile
    from ..audio.memory import MemoryRecording


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


class CloningMode(StrEnum):
    ICL = "icl"
    X_VECTOR_ONLY = "x_vector_only"


class ProfileStatus(StrEnum):
    NOT_PREPARED = "Not Prepared"
    PREPARING = "Preparing"
    READY = "Ready"
    NEEDS_PREPARATION = "Needs Preparation"


@dataclass
class WorkspaceSession:
    reference: Path | None = None
    transcript: str = ""
    speech_text: str = ""
    cloning_mode: CloningMode = CloningMode.ICL
    profile: "VoiceProfile | None" = None
    profile_status: ProfileStatus = ProfileStatus.NOT_PREPARED
    voice_revision: int = 0
    output: "MemoryRecording | None" = None
    profile_name: str = ""

    def __post_init__(self):
        if self.profile is not None:
            profile, self.profile = self.profile, None
            self.accept_profile(profile)

    def __setattr__(self, name, value) -> None:
        if name in {"reference", "transcript", "cloning_mode"} and name in self.__dict__:
            if self.__dict__[name] != value:
                self.require_reference_editable()
                object.__setattr__(self, name, value)
                if self.profile is not None or self.profile_status == ProfileStatus.PREPARING:
                    self.invalidate_profile()
                return
        object.__setattr__(self, name, value)

    @property
    def reference_locked(self) -> bool:
        return self.profile is not None and self.profile.imported_from is not None

    def require_reference_editable(self) -> None:
        if self.reference_locked:
            raise ValueError("Clear the imported voice profile before editing reference inputs.")

    @property
    def can_prepare(self) -> bool:
        return (not self.reference_locked and self.reference is not None
                and (self.cloning_mode == CloningMode.X_VECTOR_ONLY or bool(self.transcript.strip())))

    @property
    def can_generate(self) -> bool:
        return self.profile is not None and self.profile_status == ProfileStatus.READY and bool(self.speech_text.strip())

    def clear_profile(self) -> None:
        self.profile = None
        self.profile_name = ""
        self.profile_status = ProfileStatus.NOT_PREPARED
        self.voice_revision += 1

    def invalidate_profile(self) -> None:
        if self.profile is not None or self.profile_status != ProfileStatus.NOT_PREPARED:
            self.profile_status = ProfileStatus.NEEDS_PREPARATION
        self.profile = None
        self.profile_name = ""
        self.voice_revision += 1

    def accept_profile(self, profile: "VoiceProfile") -> None:
        if profile.imported_from is not None:
            self.clear_profile()
            self.reference = None
            self.transcript = ""
            self.cloning_mode = profile.mode
        elif (profile.source_reference is None or profile.source_reference != self.reference
              or profile.mode != self.cloning_mode):
            raise ValueError("The prepared profile does not match the current reference inputs.")
        self.voice_revision += 1
        self.profile = profile
        self.profile_name = (profile.imported_from or profile.source_reference).stem
        self.profile_status = ProfileStatus.READY

    def voice_clone_arguments(self) -> dict[str, object]:
        """Validate future Qwen3-TTS prompt arguments without loading a model."""
        self.require_reference_editable()
        if self.reference is None:
            raise ValueError("Load a reference recording before generating speech.")
        arguments: dict[str, object] = {
            "ref_audio": str(self.reference),
            "x_vector_only_mode": self.cloning_mode == CloningMode.X_VECTOR_ONLY,
        }
        if self.cloning_mode == CloningMode.ICL:
            if not self.transcript.strip():
                raise ValueError("ICL Mode requires a nonempty reference transcript.")
            arguments["ref_text"] = self.transcript.strip()
        return arguments

    @property
    def has_drafts(self) -> bool:
        return bool(self.transcript or self.speech_text)

    @property
    def has_content(self) -> bool:
        return self.reference is not None or self.has_drafts or self.profile is not None or self.output is not None

    def clear_reference(self) -> None:
        self.require_reference_editable()
        if self.profile is not None and self.profile.source_reference is not None:
            self.invalidate_profile()
        self.reference = None
        self.transcript = ""

    def new_voice(self) -> None:
        self.clear_profile()
        self.clear_reference()
        self.speech_text = ""
        self.cloning_mode = CloningMode.ICL
        self.profile_status = ProfileStatus.NOT_PREPARED
        self.output = None

    def select_reference(self, path: Path) -> None:
        self.require_reference_editable()
        self.apply_reference(validate_reference(path))

    def apply_reference(self, reference: Path) -> None:
        """Commit a reference already validated by background preparation."""
        self.require_reference_editable()
        if reference != self.reference:
            self.invalidate_profile()
            self.reference = reference
            # A transcript belongs to its reference, never to a replacement file.
            self.transcript = ""
