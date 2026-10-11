"""Focused session format, recovery and public generation forwarding checks."""

# Copyright (c) 2026 Nendis. SPDX-License-Identifier: MIT

from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

from qwen3_tts_studio.application.generation_settings import GenerationSettings, local_generation_defaults
from qwen3_tts_studio.application.sessions import load_session, save_session, workspace_snapshot
from qwen3_tts_studio.application.voice_profile import VoiceProfile, VoiceCancelled
from qwen3_tts_studio.application.workspace import WorkspacePaths, WorkspaceSession, CloningMode, ProfileStatus
from qwen3_tts_studio.integrations.qwen_tts import QwenVoiceModel


class SessionChecks(unittest.TestCase):
    def test_unicode_roundtrip_relocation_and_missing_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "original"
            original.mkdir()
            reference = original / "hlas.wav"
            sf.write(reference, np.zeros(800), 16000)
            settings = GenerationSettings(1.2, .8, 20, 1.2, "English")
            state = WorkspaceSession(reference=reference, transcript="Žltý kôň — 日本語 🎵\nSecond line",
                                     speech_text="Привет! 你好 👋", generation_settings=settings)
            save_session(state, original / "session.qtts.json")
            self.assertIn("Привет", (original / "session.qtts.json").read_text(encoding="utf-8"))
            relocated = root / "relocated"
            original.rename(relocated)
            restored = load_session(relocated / "session.qtts.json", root, ("Auto", "English"))
            self.assertEqual(restored.workspace.transcript, state.transcript)
            self.assertEqual(restored.workspace.speech_text, state.speech_text)
            self.assertEqual(restored.workspace.generation_settings, settings)
            self.assertEqual(restored.workspace.reference, relocated / "hlas.wav")
            self.assertIsNone(restored.workspace.output)
            self.assertFalse(restored.notices)
            (relocated / "hlas.wav").unlink()
            missing = load_session(relocated / "session.qtts.json", root, ("Auto", "English"))
            self.assertIsNone(missing.workspace.reference)
            self.assertEqual(missing.workspace.transcript, state.transcript)
            self.assertIn("could not be restored", missing.notices[0])

    def test_profile_reference_recovery_and_memory_notice(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "session.qtts.json"
            reference = root / "reference.wav"
            sf.write(reference, np.zeros(800), 16000)
            state = WorkspaceSession(reference=reference, transcript="Reviewed text")
            profile = VoiceProfile("voice", CloningMode.ICL, {}, ({"ref_text": "Reviewed text"},),
                                   "fixture", source_reference=reference)
            state.accept_profile(profile)
            save_session(state, path)
            restored = load_session(path, root, ("Auto",))
            self.assertIn("only in memory", restored.notices[0])
            self.assertEqual(restored.workspace.profile_status, ProfileStatus.NEEDS_PREPARATION)
            self.assertIsNone(restored.workspace.profile)
            state.profile_path = root / "voice.pt"
            save_session(state, path)
            imported = replace(profile, source_reference=None, imported_from=state.profile_path)
            with patch("qwen3_tts_studio.application.voice_profile.load_profile", return_value=imported):
                restored = load_session(path, root, ("Auto",))
            self.assertIsNotNone(restored.workspace.profile)
            self.assertFalse(restored.workspace.reference_locked)
            self.assertEqual(restored.workspace.transcript, state.transcript)
            self.assertEqual(restored.workspace.profile_path, state.profile_path)
            reference.unlink()
            with patch("qwen3_tts_studio.application.voice_profile.load_profile", return_value=imported):
                restored = load_session(path, root, ("Auto",))
            self.assertEqual(restored.workspace.profile_status, ProfileStatus.READY)
            self.assertEqual(restored.workspace.reference, reference)
            self.assertIsNone(restored.reference_recording)
            self.assertTrue(restored.notices)
            state.accept_profile(imported)
            save_session(state, path)
            with patch("qwen3_tts_studio.application.voice_profile.load_profile", return_value=imported):
                restored = load_session(path, root, ("Auto",))
            self.assertTrue(restored.workspace.reference_locked)
            with self.assertRaises(ValueError):
                restored.workspace.transcript = "Forbidden"
            missing = load_session(path, root, ("Auto",))
            self.assertIsNone(missing.workspace.profile)
            self.assertIn("Prepare or load", missing.notices[0])

    def test_validation_and_atomic_failure(self):
        defaults, languages = local_generation_defaults(WorkspacePaths.from_source().models)
        self.assertEqual(defaults, GenerationSettings())
        self.assertIn("English", languages)
        for settings in (replace(defaults, temperature=float("nan")), replace(defaults, top_p=0),
                         replace(defaults, top_k=True), replace(defaults, top_k=-1),
                         replace(defaults, repetition_penalty=0), replace(defaults, language="Slovak")):
            with self.assertRaises(ValueError):
                settings.validate(languages)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            state = WorkspaceSession(speech_text="Keep me")
            save_session(state, path)
            original = path.read_bytes()
            with patch("qwen3_tts_studio.application.sessions.os.replace", side_effect=OSError("Disk failure")):
                with self.assertRaises(OSError):
                    save_session(WorkspaceSession(speech_text="Replacement"), path)
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(list(path.parent.glob("*.tmp")))
            data = json.loads(original)
            for key, value in (("version", 99), ("version", True), ("speech_text", 12),
                               ("generation_settings", {}), ("reference_audio", [])):
                path.write_text(json.dumps({**data, key: value}), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_session(path, path.parent, languages)
            state.output = object()
            self.assertEqual(workspace_snapshot(state), workspace_snapshot(WorkspaceSession(speech_text="Keep me")))

    def test_public_qwen_parameter_forwarding_metadata_and_cancellation(self):
        calls = []
        def generate(**arguments):
            calls.append(arguments)
            return [np.zeros(800, dtype=np.float32)], 16000
        model = SimpleNamespace(device="cpu", generate_defaults={"subtalker_temperature": .9},
                                get_supported_languages=lambda: ["auto", "english"], generate_voice_clone=generate)
        profile = VoiceProfile("voice", CloningMode.X_VECTOR_ONLY, {}, ({
            "ref_spk_embedding": SimpleNamespace(to=lambda device: "embedding"), "ref_code": None,
            "x_vector_only_mode": True, "icl_mode": False, "ref_text": None},), "fixture")
        adapter = QwenVoiceModel(Path("unused"))
        adapter.device, adapter.precision, adapter.attention = "cpu", "float32", "sdpa"
        settings = GenerationSettings(1.25, .75, 15, 1.15, "English")
        with patch.object(adapter, "_ensure_model", return_value=model), \
             patch("qwen3_tts_studio.integrations.qwen_tts.model_identity", return_value={}), \
             patch.dict(sys.modules, {"qwen_tts": SimpleNamespace(VoiceClonePromptItem=lambda **kwargs: kwargs)}):
            result = adapter.generate(profile, " Variant ", settings, lambda: False, lambda message: None)
            for key, value in settings.arguments().items():
                self.assertEqual(calls[0][key], value)
                self.assertEqual(result.recording.metadata["generation_parameters"][key], value)
            self.assertEqual(calls[0]["text"], "Variant")
            self.assertEqual(calls[0]["voice_clone_prompt"][0]["ref_spk_embedding"], "embedding")
            with self.assertRaises(VoiceCancelled):
                adapter.generate(profile, "Variant", settings, lambda: bool(len(calls) > 1), lambda message: None)
            self.assertEqual(len(calls), 2)
