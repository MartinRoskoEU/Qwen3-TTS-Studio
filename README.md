# Qwen3 TTS Studio

**Offline-first desktop voice cloning, speech synthesis, and transcription.**

A Windows desktop application built with PySide6, local Qwen3-TTS 1.7B Base, and Faster Whisper Small. Application source is MIT-licensed, Copyright (c) 2026 Nendis.

## Run

From the repository root in PowerShell, use the verified startup command:

```powershell
& .\.cenv\python.exe -m qwen3_tts_studio
```

This selects the existing Python 3.12 environment without activation. Alternatively, activate it with `conda activate .\.cenv` and run `python -m qwen3_tts_studio`.

Startup does not import Torch, Qwen, or Faster Whisper, or load model weights. Model setup is unnecessary for launching the workspace, entering drafts, or playing reference audio.

## Voice Preparation Workflow

1. **Choose reference** (`Ctrl+O`) or drop one WAV/OGG file into Reference Audio. Its filename, duration, and actual waveform appear after background validation. The original is read in place; keep it available during preparation and reference playback. Importing never starts transcription or voice preparation automatically.
2. Select the cloning mode. **ICL Mode – With Transcription** is the default: enter, paste, or edit the reference transcript, or use **Transcribe reference** and review the result. ICL requires nonempty reference text. **X-Vector Only – Without Transcription** disables the editor and transcription action while keeping any draft; preparation uses audio without reference text.
3. Click **Prepare Voice**. The application lazily loads the local Base model and calls its public `create_voice_clone_prompt()` API. It caches the resulting profile, including speaker embedding, reference speech codes and text for ICL, and mode flags. Status shows **Not Prepared**, **Preparing**, **Ready**, or **Needs Preparation**. Prepare Voice remains available for preparing again when idle.
4. Enter **Speech Text** and click **Generate Speech**. Each click starts a new stochastic generation using `generate_voice_clone(voice_clone_prompt=...)` and the cached profile. The application does not prepare the voice again. Repeated unchanged text can produce different recordings. Editing Speech Text preserves the profile; changing the reference, transcript, or cloning mode invalidates it.
5. Review the latest generated recording in **Output**. Generation keeps float32 PCM, sample rate, waveform, playback data, and generation metadata in RAM. It creates no WAV, JSON sidecar, or temporary audio file. A successful replacement is published only after Qt accepts the new playback buffer; errors and cancellation preserve the previous recording. **Export WAV** is the only action that saves generated audio: choose a filename/destination and confirm before overwriting. The IEEE float WAV preserves the generated float32 samples and sample rate without PCM16 quantization. Output shows the exported filename and its destination in a tooltip. Export previous recordings before replacing them if you want to keep them.

Generation requires a ready profile and nonempty Speech Text. Preparation, profile file operations, and generation use serial background workers; controls prevent overlapping work. Model loading, inference, RAM encoding, waveform preparation, and export stay off the UI thread. Processing status reports elapsed time and the actual model device/precision. Transcription and voice operations are also prevented from starting together, avoiding concurrent GPU inference. Generation no longer requires a writable output directory.

**Stop Generation**, next to Generate Speech, requests cancellation immediately and shows **Stopping generation...** until the worker actually finishes, then **Generation canceled.** Repeated Stop clicks are harmless. The installed Qwen-TTS 0.1.1 public voice-cloning path does **not** support actual mid-inference interruption: its core `generate()` does not forward a `stopping_criteria` callback to the talker. The native call finishes safely in its background worker; cancellation checkpoints discard the result before RAM preparation/publication. No thread is terminated and no CUDA resources are destroyed during inference. Another operation waits until the worker has finished. Stop preserves the previous Output, reference playback, prepared profile, and loaded model. Canceling during output preflight also preserves the previous preview.

## Sessions and Advanced Generation Settings

**Application > Open Session** (`Ctrl+Shift+O`), **Save Session** (`Ctrl+S`), and **Save Session As** (`Ctrl+Shift+S`) use version 1 UTF-8 JSON sessions (`*.qtts.json` by default). Sessions preserve Unicode Speech Text, reviewed reference transcription, ICL/X-Vector mode, reference and saved/imported profile file paths, and advanced generation settings. Saving uses an atomic replacement; Save As asks before replacing an existing file. Sessions contain private text and paths; the default filename pattern is ignored by Git.

Sessions store file references, not recordings, voice tensors, loaded Qwen/Faster Whisper models, or generated audio. **Save Profile** remains a separate explicit action. A profile prepared only in memory is marked as requiring preparation/loading after reopening; saving reports that it was not persisted, and reopening shows a recovery notice. Save the profile first if you want a session to restore it ready for generation.

Paths are relative to the session folder when possible, with absolute paths for different Windows drives. Moving a session and its referenced files together preserves those references. Missing, unreadable, or incompatible references produce a notice while keeping text and settings. Use Choose Reference or Load Profile to locate moved files. A valid saved prepared profile remains usable for generation even if its original audio is unavailable; restoring it keeps the reviewed transcript and editable reference inputs. Imported profiles restore the existing input locks and keep ICL text inside the profile. Invalid JSON, unsupported versions, or invalid settings preserve the current workspace. Loading validates audio and profile data in the serial background worker; it cancels obsolete work and waits for active native calls before replacement. Sessions are limited to 4 MiB, and loading never downloads models.

The workspace title and draft footer report actual changes relative to the last save or opened session. Speech/transcript edits, reference/mode changes, profile preparation/clearing/file changes, and generation settings count as changes. Reverting edits to the saved state clears the warning. Closing, Open Session, and New Voice offer **Save / Discard / Cancel** when needed. Save uses the current session path or opens Save Session As; failed or canceled saving keeps the workspace open. Playback, generation, export, appearance, and splitters do not make the session dirty. Generated previews remain transient: use **Export WAV** before closing or replacing the workspace if you want to keep them.

**Generation > Advanced Settings** starts collapsed. Numeric controls show their values, validate bounds, and provide tooltips. Defaults come from the local model's `generation_config.json`, and languages come from its configuration using the installed SDK's supported-language rule. If local model metadata is absent, the panel uses the inspected Qwen-TTS 0.1.1 defaults and offers Auto language; inference still requires the complete local model.

| Setting | Local default | Studio input range | Effect |
| --- | --- | --- | --- |
| Temperature | 0.9 | 0.01–5 | Changes sampling randomness |
| Top P | 1.0 | 0.01–1 | Cumulative-probability sampling threshold |
| Top K | 50 | 0–3072 | Limits candidate tokens; 0 disables this filter |
| Repetition Penalty | 1.05 | 0.01–5 | 1 is neutral; values above 1 discourage repeated tokens |
| Language | Auto | Local model's supported languages | Selects generated speech language |

The numeric bounds are Studio input limits. These controls affect stochastic talker sampling; they are not deterministic speed/emotion controls. They forward the public `temperature`, `top_p`, `top_k`, `repetition_penalty`, and `language` arguments to `generate_voice_clone()`. Subtalker settings retain their original model defaults. **Reset to Defaults** restores the model's original values and Auto language. Each job captures an immutable settings value at start; edits during generation affect the next job. Settings changes and profile switching preserve prepared voice data, allowing variants without preparing again. Sessions restore settings, while **New Voice** restores the defaults.

## Voice Profiles

**Save Profile** writes a `.pt` file; an existing destination requires confirmation. **Load Profile** validates the file before replacing the current preparation and restores its cloning mode. Invalid or incompatible profiles preserve the current reference, transcript, and profile. Loading keeps Speech Text and the existing Output preview.

An imported profile is ready without the original reference recording or a transcript in the editor. ICL reference text is retained inside the profile. The Qwen model loads lazily when generation requires it. Missing original reference audio alone does not invalidate an imported profile.

Voice Profile is a separate panel with **Prepare Voice**, **Load Profile**, **Save Profile**, and **Clear Profile**, plus the current profile name and status. Prepared profiles use the reference filename as their name; saving updates the displayed name to the profile filename. Imported profiles use their `.pt` filename.

Profiles prepared from the current reference leave Reference Audio and Transcription editable; changes invalidate preparation. Imported profiles lock those two sections, including selection, drag/drop, transcription editing, automatic transcription, and mode selection. Application state also rejects reference-input changes while imported, so programmatic calls cannot bypass disabled controls. Prepare Voice is unavailable while imported; Load Profile can replace it after confirmation and validation. Failed or canceled replacement keeps the existing workspace. Successful import clears unrelated reference inputs before locking them.

**Clear Profile** cancels pending voice work, removes the cached profile, resets its name/status, and unlocks reference inputs. It preserves Speech Text, existing Output, loaded models, and every file on disk. Prepared reference inputs remain available for preparing again. **New Voice** remains the complete workspace reset.

Voice Profile and Generation share a compact progress presentation: an indeterminate Qt bar during real work, the current stage, elapsed time, and GPU/CPU information when known. Generation reports model loading, input preparation, speech generation, saving audio to memory, waveform preparation, playback preflight, and completion. No percentages or invented intermediate stages are shown. Generation stays active through Qt's acceptance of the output recording and completes only when the preview is ready. Errors stop the indicator, preserve the previous recording/profile where applicable, and include technical details in tooltips and traceback logs. Clear Profile and resets stop the UI indicator immediately; a canceled native call may still need to finish before another job can start.

The versioned format contains only dictionaries, primitive metadata, and CPU tensors. Loading uses `torch.load(weights_only=True, map_location="cpu")`; it never unpickles Qwen prompt classes or adds arbitrary objects to a safe list. Validation checks tensor shapes, finite embeddings, code ranges, mode flags, required ICL text, and the local model/tokenizer configuration fingerprint. Profiles are limited to 128 MiB. These are Studio profiles, not arbitrary upstream `.pt` objects. Compatibility compares configurations, not a checksum of the complete model weights; use the same Base weights. Profiles contain voice data and, in ICL mode, reference transcription. Profile files are ignored by Git.

## Playback, Layout, and Workspace

- The resizable two-column workspace has three independent left panels: Reference Audio, Transcription, and Voice Profile. Speech Text and Generation remain on the right, with Output across the bottom. Existing splitters adjust each area, including both dividers in the left column. The six sections fit the existing 900 × 870 minimum window size. The reference waveform is compact; Output retains a larger waveform area. The icon and Windows taskbar identity are preserved.
- Both players share Qt Multimedia playback and cached Qt Widgets/QPainter waveforms. Played audio is brighter blue with subtle highlighting; unplayed audio is muted blue-gray. The thin playhead interpolates Qt's authoritative playback position using a monotonic clock and Qt's shared animation driver. There is no separate slider or fixed display-specific frame rate.
- Output uses an in-memory WAV container through Qt's supported [`QMediaPlayer.setSourceDevice()`](https://doc.qt.io/qt-6/qmediaplayer.html#setSourceDevice) API. Each player's `QBuffer` owns its bytes and stays alive with the media player until its source is detached and the player is destroyed. Reference WAV/OGG files retain their existing file playback path. Playback never creates temporary audio files.
- **Play/Pause** resumes from the paused position and replays after completion. Click to seek or drag to scrub directly in the waveform. Current position and duration remain visible. Output controls are disabled until actual audio is loaded. PCM WAV and OGG Vorbis are verified; other variants depend on the available decoders.
- **Clear reference** unloads the recording, clears its transcription, and invalidates its prepared voice. It confirms before discarding nonempty transcription, keeps Speech Text/Output, and never deletes files.
- **Application > New Voice** (`Ctrl+N`) protects unsaved session changes with Save/Discard/Cancel, then clears the reference, transcript, profile, Speech Text, and generated audio in RAM, restores ICL mode and default generation settings, and detaches the session filename. Cancel changes nothing. An active generation is invalidated and finishes safely without restoring audio. Loaded models, preferences, and splitter positions are preserved; exported recordings and saved profiles remain on disk. Clear Profile and Clear Reference preserve the current in-memory Output.
- Requests carry identities and workspace revisions. Edits, reference changes, clearing, and New Voice discard obsolete worker results and pending Output loads. Native Qwen model calls cannot be interrupted mid-call with the installed public API; canceled results are ignored, and another job waits for that call to return. Shutdown stays responsive while workers finish and release models.
- Centralized light/dark styling follows Windows appearance, including runtime notifications. Settings offers persistent Light/Dark overrides. Application contains New Voice, Open Session, Save Session, Save Session As, Settings, and Exit; primary voice actions stay in the workspace.
- Drafts remain in memory until Save Session. Shortcuts: `Ctrl+O` reference, `Ctrl+N` New Voice, `Ctrl+Shift+O` Open Session, `Ctrl+S` Save Session, `Ctrl+Shift+S` Save Session As, `Ctrl+,` Settings, `Ctrl+Q` Exit. Space toggles the focused or active player outside text inputs; editors and modal dialogs retain native keyboard behavior.

## Local Models and Runtime

Models are supplied separately and never downloaded by these workflows:

```text
models/Qwen3-TTS-12Hz-1.7B-Base/
models/faster-whisper/
```

Qwen preparation/generation requires a complete local Base model and speech tokenizer. The adapter validates required files before loading from an absolute local path with `local_files_only=True`. The RTX 4070 was verified using **CUDA, bfloat16, and SDPA**. BF16 selection checks runtime support; FP16 is used for a compatible GPU without BF16, and CPU float32 is the fallback if GPU initialization fails. Runtime GPU out-of-memory errors keep drafts/profile and report recovery guidance. CPU synthesis and other GPU configurations were not exercised in this change.

Faster Whisper lazily loads and reuses Small, detects the spoken language, and runs in a background thread. It confirms before replacing nonempty text, preserves drafts on errors/empty results, and discards results after manual edits, mode/reference changes, Clear Reference, or New Voice. A direct model directory or the existing `models--Systran--faster-whisper-small/refs/main` cache layout is accepted. Required files are `model.bin`, `config.json`, `tokenizer.json`, and `vocabulary.txt`.

On Windows, its existing process-local CUDA setup registers NVIDIA DLL directories under the selected interpreter's `Lib/site-packages/nvidia/{cublas,cudnn,cuda_nvrtc}/bin`, retains `os.add_dll_directory()` handles, and loads matching cuBLAS/cuDNN cores before CTranslate2. It does not modify PATH, system CUDA, or PyTorch configuration. Faster Whisper prefers CUDA float16 and retains CPU fallback with logged/status-tooltip errors. Actual CUDA transcription was verified both before and after Qwen inference in the same application process.

Verified existing environment:

- Python 3.12.15; PySide6 / Qt 6.12.0.
- Qwen-TTS 0.1.1; PyTorch 2.11.0+cu130; Transformers 4.57.3; Accelerate 1.12.0.
- SoundFile 0.14.0 / libsndfile 1.2.2; NumPy 2.5.3.
- Faster Whisper 1.2.1; CTranslate2 4.8.2; PyAV 18.1.0.
- NVIDIA GeForce RTX 4070; existing transcription cuBLAS 12.9.2.10 and cuDNN 9.27.0.42.

No packages, CUDA configuration, or model files were installed or changed. The installed Qwen package prints a missing-SoX diagnostic during import; the verified preparation/generation paths succeed without SoX. Audio post-processing remains unimplemented.

For a separate new environment, create Python with `conda create --prefix .\.cenv python=3.12 -y`. [requirements-desktop.txt](requirements-desktop.txt) and [requirements-transcription.txt](requirements-transcription.txt) record the existing UI/decoding and transcription versions. They do not install the synthesis stack or models. Recreating the complete environment is untested; a complete synthesis dependency manifest and binary packaging audit remain pending. CUDA PyTorch builds must match the target machine. Official sources: [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS), [Base model](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base), [Faster Whisper](https://github.com/SYSTRAN/faster-whisper), [Small model](https://huggingface.co/Systran/faster-whisper-small).

## Architecture and Data

```text
qwen3_tts_studio/
  __main__.py, app.py     # Entry point and application composition
  application/           # Workspace state, JSON sessions, generation settings, profile I/O, workers
  audio/                 # File validation, immutable generated PCM, RAM WAV/waveform preparation
  integrations/          # Lazy offline Faster Whisper and Qwen model adapters
  ui/                    # Window, shared player/waveform/progress, dialogs, themes, original icon
tests/                   # Focused checks; normal suite does not run model inference
models/, samples/, output/  # Preserved data directories with tracked .gitkeep files
```

Keep reference recordings in `samples/` and models in `models/`. `output/` is the default Save dialog location for explicit WAV exports; generation does not write into it. Existing files and all three directories remain untouched. These directories' contents and exported `.pt` profiles are ignored by Git. Never commit environments, model weights, recordings, generated audio, caches, or secrets. Export and profile operations never silently overwrite files. No original recording or exported audio is automatically deleted.

## Focused Verification

```powershell
& .\.cenv\python.exe -m unittest discover -s tests -v
```

The 34 checks cover startup/shutdown, six-section minimum-size resizing and both left splitter handles, light/dark theme notifications, WAV/OGG decoding and drops, smooth shared waveform playback/seeking/scrubbing, Clear Reference/New Voice confirmation/cancellation, transcription modes/edit protection and fallback, reusable profile state, repeated RAM-only generation orchestration, profile import validation/cancellation/replacement, imported-input locking, stale-result protection, progress through output acceptance and failure, exact PCM export, overwrite confirmation/canceled dialogs, Stop during blocked work and output preflight, prevention of overlapping jobs, UI heartbeat, and background cleanup. Session/settings checks add Unicode and relative-path relocation, missing references/profiles and memory-only recovery notices, atomic-save failure preservation, unsupported-version/type/settings rejection, Save/Discard/Cancel and canceled/failed saving, session switching during generation, default reset, immutable per-job settings, profile reuse, and public Qwen argument/metadata forwarding. Delayed adapters stand in for model calls. A separate subprocess checks real tensor-only profile serialization and rejects incompatible/nonfinite/arbitrary-object files. Regular checks do not perform inference or download assets.

For the session/settings change, two real desktop generations used the existing imported ICL profile and the same loaded **CUDA/bfloat16/SDPA** model. Defaults produced 3.84 seconds of audio in 13.19 seconds; temperature 0.75, top P 0.9, top K 30, repetition penalty 1.1, and English produced 3.68 seconds in 11.92 seconds. Editing controls during the first job preserved its captured defaults; the second used the edits without preparing the voice again. Real JSON reopening restored Unicode text, settings, and the imported profile's locks. UI heartbeats continued. A Python file-write audit detected no WAV/OGG writes, and existing samples/output filenames and hashes stayed unchanged. Expanded and collapsed light/dark layouts were checked at 900 × 870. CPU synthesis, other languages, and new reference preparation were not rerun for this change. The application is left running for manual testing.

For the earlier in-memory change, the actual desktop entry point used an existing ICL profile on the **RTX 4070 with CUDA/bfloat16/SDPA**: two successful generations replaced RAM recordings using the same loaded model; actual Qt RAM playback passed Play/Pause, seeking, scrubbing, completion, and replay. Three further native inference calls were canceled through Stop, New Voice, and shutdown. Stop kept the prior Output/profile/model; New Voice rejected stale audio; shutdown retained GPU resources until the call returned, then released the model. UI timers continued throughout. Explicit export retained the exact float32 samples/sample rate and overwrite Yes/No worked. A write audit detected no automatic WAV/OGG creation, and hashes/names of existing `output/` files stayed unchanged. Loaded-waveform light/dark layouts were reviewed at 900 × 870.

Earlier GPU verification prepared and imported both ICL and X-Vector profiles, generated in both modes without original reference inputs after import, and transcribed through Faster Whisper CUDA float16 before/after Qwen usage. Those model/transcription paths were preserved; X-Vector inference and Faster Whisper were not rerun for this storage/cancellation change.

Automatic checks simulate local-file Explorer drops and Qt appearance notifications. Audible speaker output, physical Explorer dragging, a real Windows personalization change, long-form synthesis, voice quality across speakers/languages, CPU synthesis, other machines/GPUs, and packaged builds remain manual or unverified. The application is left running for manual testing.

## Privacy and License

Recordings, transcripts, profiles, and generated speech are processed locally once dependencies/models are available. Only clone or distribute voices you have permission to use. Tool/model licenses do not grant rights to performances or speaker identities.

Original application source: **MIT License**, Copyright (c) 2026 **Nendis**; see [LICENSE](LICENSE). Qwen3-TTS code and Base weights retain **Apache-2.0**; Faster Whisper/Small retain **MIT**. Their licenses are not replaced by the application's MIT license. [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) was reviewed; no dependencies were installed or changed. A complete inventory of exact redistributed runtime dependencies is required before binary release.
