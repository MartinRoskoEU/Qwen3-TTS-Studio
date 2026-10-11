"""Versioned UTF-8 workspace sessions, independent of Qt and loaded models."""

# Copyright (c) 2026 Nendis. SPDX-License-Identifier: MIT

from dataclasses import dataclass, replace
import json
import logging
import os
from pathlib import Path
import tempfile

from .generation_settings import GenerationSettings
from .workspace import CloningMode, ProfileStatus, WorkspaceSession

FORMAT = "qwen3-tts-studio-session"
VERSION = 1
MAX_BYTES = 4 * 1024 * 1024


def workspace_snapshot(workspace):
    """Comparable editable state; output, models, job status and timings excluded."""
    return (workspace.speech_text, workspace.transcript, workspace.cloning_mode,
            workspace.reference, workspace.profile_path, workspace.generation_settings,
            workspace.profile.identifier if workspace.profile else None)


def session_document(workspace, destination):
    def stored(path):
        if path is None:
            return None
        try:
            return Path(os.path.relpath(path.resolve(), destination.parent.resolve())).as_posix()
        except ValueError:  # Different Windows drives.
            return str(path.resolve())
    return {
        "format": FORMAT, "version": VERSION,
        "speech_text": workspace.speech_text, "reference_transcription": workspace.transcript,
        "cloning_mode": workspace.cloning_mode.value,
        "reference_audio": stored(workspace.reference), "voice_profile": stored(workspace.profile_path),
        "profile_kind": "imported" if workspace.reference_locked else "prepared",
        "profile_required": workspace.profile is not None,
        "generation_settings": workspace.generation_settings.arguments(),
    }


def save_session(workspace, destination):
    """Atomically replace only the explicitly selected JSON session file."""
    destination = Path(destination).resolve()
    if destination.suffix.lower() != ".json":
        raise ValueError("Save sessions with a .json extension.")
    if not destination.parent.is_dir():
        raise ValueError("Select an existing writable folder for the session.")
    encoded = (json.dumps(session_document(workspace, destination), ensure_ascii=False,
                          indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(encoded) > MAX_BYTES:
        raise ValueError("Session exceeds the 4 MiB size limit; shorten the text drafts.")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination


@dataclass
class RestoredSession:
    path: Path
    workspace: WorkspaceSession
    reference_recording: object = None
    notices: tuple[str, ...] = ()


def load_session(path, models, languages, cancelled=lambda: False, report=lambda message: None):
    """Run in a worker: validate JSON, decode reference, safely load profile tensors."""
    from .voice_profile import VoiceCancelled, check_cancel, load_profile
    from ..audio.decoding import DecodeCancelled, prepare_waveform

    path = Path(path).resolve(strict=True)
    report("Reading session...")
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Session exceeds the 4 MiB size limit.")
    data = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("This is not a Qwen3 TTS Studio session.")
    if type(data.get("version")) is not int or data["version"] != VERSION:
        raise ValueError("Unsupported session version. Open it with a compatible Studio version.")
    for key in ("speech_text", "reference_transcription"):
        if not isinstance(data.get(key), str):
            raise ValueError(f"Invalid session text field: {key}")
    if data.get("profile_kind") not in {"prepared", "imported"} or type(data.get("profile_required")) is not bool:
        raise ValueError("Invalid session profile state.")
    settings = GenerationSettings.from_dict(data.get("generation_settings"), languages)
    workspace = WorkspaceSession(speech_text=data["speech_text"], transcript=data["reference_transcription"],
                                 cloning_mode=CloningMode(data.get("cloning_mode")), generation_settings=settings)
    notices = []
    def referenced(key):
        value = data.get(key)
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Invalid file reference: {key}")
        selected = Path(value)
        return (selected if selected.is_absolute() else path.parent / selected).resolve()

    reference, profile_path = referenced("reference_audio"), referenced("voice_profile")
    if data["profile_kind"] == "imported" and (reference is not None or workspace.transcript):
        raise ValueError("Imported-profile sessions must have cleared reference inputs.")
    recording = None
    if reference is not None:
        check_cancel(cancelled)
        report("Restoring reference audio...")
        try:
            recording = prepare_waveform(reference, cancelled)
            workspace.reference = recording.path
        except (DecodeCancelled, VoiceCancelled):
            raise
        except Exception as error:
            logging.getLogger(__name__).warning("Session reference unavailable: %s", error)
            notices.append(f"Reference audio could not be restored: {reference}\n{error}\nChoose its new location for playback or preparing again. A successfully restored saved profile can still generate speech.")
    if profile_path is not None:
        check_cancel(cancelled)
        report("Restoring voice profile...")
        try:
            profile = load_profile(profile_path, models, cancelled)
            if profile.mode != workspace.cloning_mode:
                raise ValueError("The profile mode differs from the session mode.")
            if data["profile_kind"] == "prepared":
                if reference is None:
                    raise ValueError("The session has no source reference for this prepared profile.")
                if profile.mode == CloningMode.ICL and profile.items[0]["ref_text"] != workspace.transcript.strip():
                    raise ValueError("The saved profile does not match the reviewed reference transcription.")
                # A cached profile generates without reopening its source audio.
                # Retain the unavailable path as its provenance, with a notice.
                workspace.reference = reference
                profile = replace(profile, imported_from=None, source_reference=workspace.reference)
            workspace.accept_profile(profile)
            workspace.profile_path = profile_path
            workspace.profile_name = profile_path.stem
        except (DecodeCancelled, VoiceCancelled):
            raise
        except Exception as error:
            logging.getLogger(__name__).warning("Session profile unavailable: %s", error)
            notices.append(f"Voice profile could not be restored: {profile_path}\n{error}\nPrepare or load the voice again.")
    elif data["profile_required"]:
        notices.append("The voice profile existed only in memory and was not saved in this session. Prepare or load the voice again.")
    if workspace.profile is None and (data["profile_required"] or profile_path is not None):
        workspace.profile_status = ProfileStatus.NEEDS_PREPARATION
    check_cancel(cancelled)
    return RestoredSession(path, workspace, recording, tuple(notices))
