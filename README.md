# Qwen3 TTS Studio

**Offline-first desktop voice cloning, speech synthesis, and transcription.**

Qwen3 TTS Studio is a Windows-focused application project using Qwen3-TTS and Faster Whisper. Its goal is to make it practical to prepare, clone, generate, review, and export voices locally, including voices from short reference recordings.

## Project Status

**Desktop workspace with reference audio playback and local transcription (0.1.0).**

A runnable PySide6 desktop application is available. The current version includes:

- A compact, resizable workspace with Reference Audio above Transcription on the left, Speech Text above Generation on the right, and a larger Output section across the bottom. Splitters adjust column widths, the panels within each column, and the balance between the workspace and Output.
- Import one local WAV or OGG recording using Choose reference (`Ctrl+O`) or by dropping it from File Explorer into Reference Audio. The filename and duration appear after validation; the full path is available in the filename tooltip. Import reads the original in place without copying or modifying it.
- Reference playback uses Qt Multimedia with an actual waveform, a thin moving playhead, one Play/Pause toggle, and current/total time. Play resumes at the paused position and replays from the beginning after completion. Click the waveform to seek or drag to scrub; playback resumes after scrubbing if it was playing. During dragging, the playhead follows the mouse immediately and the paused source seeks on release. The focused codec checks cover PCM WAV and OGG Vorbis; other codec variants depend on the installed decoders and fail with an actionable message if unsupported.
- Played audio appears in brighter blue with a subtle background tint; unplayed audio uses muted blue-gray in both themes. Qt Widgets/QPainter cache the waveform geometry and rendered layers. Playback interpolates Qt's authoritative position using a monotonic clock, with notification corrections. Qt's shared animation driver schedules updates without an application-defined frame rate; only the changed waveform strip repaints. Continuous animation stops while paused, stopped, stalled, scrubbing, or finished.
- Output uses the same player component, with playback and Export WAV disabled until generated audio exists. There is no separate timeline slider. Open output folder remains functional.
- Waveform preparation runs in cancellable background workers with elapsed-time status. Superseded imports cannot replace the active reference. A failed import preserves the previous recording and drafts; successful replacement releases the previous playback source. Keep the source file available during playback.
- Editable transcript and speech text drafts, with a speech character count. Drafts remain in memory only. Closing with drafts requires discard confirmation; replacing a reference requires confirmation before clearing its transcript. The transcript is temporarily read-only during import and clears only after a different reference loads successfully.
- A compact voice cloning mode selector defaults to **ICL Mode – With Transcription**. **X-Vector Only – Without Transcription** disables the transcript editor and Transcribe reference while retaining the text. Switching back restores editing. Manual typing, pasting, and correction are available in ICL even before reference import; importing audio never starts transcription automatically.
- **Transcribe reference** runs the existing local Faster Whisper Small model in a background worker, automatically detects the language, and places recognized text in the editor for review. It is enabled only in ICL with a loaded reference and no pending import/transcription. The model loads on the first request and is reused afterward, including after Clear reference and New Voice. Status shows loading/transcription, elapsed time, and **GPU (CUDA)** or **CPU**. The completed status tooltip includes actual precision and any GPU error that caused CPU fallback; errors are also logged. Empty results and errors keep the existing draft.
- Automatic transcription asks before replacing nonempty text. Declining preserves the whole workspace. Editing the transcript, switching modes, selecting another reference, Clear reference, or New Voice invalidates the pending result. Old results cannot overwrite later edits, even if you switch back to the original mode. Model operations run serially; after cancellation a new request waits until native work reaches a cancellation checkpoint. Closing waits responsively for work and background model cleanup.
- Application state prepares validated future Qwen3-TTS prompt arguments: ICL requires nonempty reviewed `ref_text` and sets `x_vector_only_mode=False`; X-Vector Only omits `ref_text` and sets `x_vector_only_mode=True`. Speech generation remains unimplemented.
- Clear reference, next to Choose reference, unloads reference audio and clears its transcription while keeping Speech Text, cloning mode, and Output. It asks before discarding nonempty transcription; Cancel leaves the workspace intact, including an active transcription. Application > New Voice (`Ctrl+N`) resets the reference, both text drafts, Output preview, and cloning mode to ICL, with confirmation whenever the workspace contains content or a pending import. Both actions cancel obsolete loading/transcription results and never delete files. New Voice preserves loaded models, appearance preferences, and splitter positions.
- Centralized light/dark styling that follows Windows appearance by default, including runtime notifications. Settings offers optional Light/Dark overrides and remembers the choice locally through Qt settings.
- Functional New Voice, Settings, About, and Exit menu actions, and an Open output folder button. Keyboard shortcuts: `Ctrl+N` for New Voice, `Ctrl+O` to select a reference, `Ctrl+,` for Settings, and `Ctrl+Q` to exit. Space toggles the player containing focus; elsewhere it toggles the playing player or Reference Audio (Output if only Output is loaded). Space inside text inputs/editors continues to enter text, and modal dialogs retain their native keyboard behavior.

**TTS inference, audio post-processing, and export are not implemented.** Their workflow actions are disabled placeholders. Startup loads Qt Multimedia without importing AI libraries or accessing model weights. SoundFile and NumPy load in the decoding worker when importing a reference; Faster Whisper/CTranslate2 load only when requesting transcription. Reference import, playback, and transcription run locally without model downloads.

Initial command-line experiments with Qwen3-TTS and Faster Whisper previously succeeded on CPU and an NVIDIA GPU. Those scripts were removed; those results do not establish model support in the desktop application. The items under *Planned Features* remain goals.

## Planned Features

- Clone a voice from a short WAV or OGG reference recording.
- Generate speech with Qwen3-TTS 1.7B Base.
- Generate custom text, including longer passages, for review and export.
- Choose CPU or supported NVIDIA GPU execution.
- Expose compatible model sampling settings and report timing information.
- Preview and compare generated results.
- Save WAV output using unique filenames.
- Later add optional, non-destructive tempo, pitch, and pause processing.
- Display honest progress/status, elapsed time, and actionable errors.

## Technology and Target Platform

- Windows (initial target)
- Python 3.12
- Conda environment located in `.cenv/` inside the project
- PySide6 / Qt Widgets and Qt Multimedia (verified with version `6.12.0`)
- SoundFile `0.14.0` / libsndfile `1.2.2` and NumPy `2.5.3` (reference waveform decoding)
- [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS), initially `Qwen3-TTS-12Hz-1.7B-Base`
- [Faster Whisper](https://github.com/SYSTRAN/faster-whisper) `1.2.1`, Small; CTranslate2 `4.8.2` and PyAV `18.1.0` (local transcription)
- PyTorch and TorchAudio (future model integrations)

The desktop shell was checked on the development Windows machine using Python `3.12.15` and PySide6 / Qt `6.12.0`. Other platforms and packaged executables have not been tested.

The original AI experiments used an RTX 4070 with PyTorch and TorchAudio `2.11.0+cu130`. This is a record of that machine, **not a universal requirement**. AI installation instructions and compatible versions will be finalized with the model integrations.

## Repository Layout

```text
Qwen3 TTS Studio/
├── .cenv/                 # Local Conda environment (not tracked)
├── models/                # Locally downloaded model data (not tracked)
│   └── .gitkeep
├── output/                # Generated audio and results (not tracked)
│   └── .gitkeep
├── samples/               # Reference audio (not tracked)
│   └── .gitkeep
├── qwen3_tts_studio/
│   ├── __main__.py         # python -m entry point
│   ├── app.py              # Application composition and event loop
│   ├── application/        # Session state, validation, audio/transcription workers
│   ├── audio/              # File validation and waveform envelope preparation
│   ├── ui/                 # Window, reusable player, waveform, dialogs, and themes
│   │   └── assets/         # Application icon (Qwen3-TTS-Studio-icon.ico)
│   └── integrations/       # Lazy offline Faster Whisper adapter; future TTS boundary
├── tests/
│   ├── test_desktop.py     # Focused workspace checks; no inference
│   ├── test_audio.py       # Local codec, playback, drop, and cancellation checks
│   └── test_transcription.py # Modes, offline validation, and worker/result safety
├── requirements-desktop.txt
├── requirements-transcription.txt
├── .gitignore
├── AGENTS.md
├── LICENSE
├── README.md
└── THIRD_PARTY_NOTICES.md
```

Session state and path validation remain independent of Qt and model libraries. The application layer orchestrates reference decoding and serial transcription through Qt threads; the audio layer reads bounded blocks and produces a compact peak envelope without retaining the entire recording. The reusable UI player owns Qt playback resources and validates a replacement before committing it. The integration adapter owns the resident Faster Whisper model and uses only a validated local directory. Request identities and editor revisions protect results. Shutdown cancels preparation/transcription and keeps the event loop responsive until workers finish and unload the model. Future TTS inference and export must also run off the UI thread.

## Environment Setup

Open the **Qwen3 TTS Studio** directory in Visual Studio Code. In the integrated **PowerShell** terminal, activate the existing project-local environment:

```powershell
conda activate .\.cenv
```

Check that it is active:

```powershell
python --version
```

The intended Python version is 3.12. The existing `.cenv` already contains the desktop and Faster Whisper dependencies; no packages or model files were changed for this implementation.

If you need to recreate the environment on a different machine, you can first create an empty local environment:

```powershell
conda create --prefix .\.cenv python=3.12 -y
conda activate .\.cenv
```

**This only creates Python.** [requirements-desktop.txt](requirements-desktop.txt) records the verified UI and reference-decoding dependencies, separate from AI dependencies. On a newly created environment, install the desktop dependencies explicitly:

```powershell
python -m pip install -r requirements-desktop.txt
```

For local transcription, [requirements-transcription.txt](requirements-transcription.txt) separately records the installed Faster Whisper, CTranslate2, and PyAV versions. On a new environment, install those explicitly with `python -m pip install -r requirements-transcription.txt`, and supply the Small model separately. Recreating an environment has not been tested. A complete synthesis dependency manifest is still pending. CUDA-enabled PyTorch must be installed from a build appropriate for the target OS, Python version, and GPU driver; it is unnecessary for launching the workspace or for Faster Whisper CPU transcription.

## Models

Models are downloaded separately and are **not included in Git**.

Initial model paths used during development:

```text
models/Qwen3-TTS-12Hz-1.7B-Base/
models/faster-whisper/
```

Official model references:

- [Qwen3-TTS 1.7B Base](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base)
- [Faster Whisper Small](https://huggingface.co/Systran/faster-whisper-small)

Transcription accepts a direct Small model directory at `models/faster-whisper/`, or the existing Hugging Face cache under `models/faster-whisper/models--Systran--faster-whisper-small/`. For a cache it reads `refs/main` and uses the corresponding local `snapshots/<revision>/`. Required files are `model.bin`, `config.json`, `tokenizer.json`, and `vocabulary.txt`; an incomplete or missing model produces an actionable error without downloading anything. Paths are resolved relative to the application source, independent of the working directory.

The adapter prefers CUDA float16 when supported, with CPU fallback on a Windows DLL setup, CUDA initialization, or CUDA transcription error. Device and precision are read from the loaded CTranslate2 model. CPU normally uses int8. See [Faster Whisper's runtime requirements](https://github.com/SYSTRAN/faster-whisper#gpu).

On Windows, before importing Faster Whisper/CTranslate2 on the first request, the application locates NVIDIA DLLs under the current interpreter's environment (`.cenv/` for the documented launch command):

```text
.cenv/Lib/site-packages/nvidia/cublas/bin/
.cenv/Lib/site-packages/nvidia/cudnn/bin/
.cenv/Lib/site-packages/nvidia/cuda_nvrtc/bin/  # Optional installed runtime compiler
```

The application registers existing directories with `os.add_dll_directory()` and retains the handles for its process lifetime. The process's Windows default DLL search enables these directories for native library loads as well. It loads the NVIDIA cuBLAS/cuDNN cores by absolute path before CTranslate2 so cuDNN can use matching companion DLLs. This addresses the earlier `cublas64_12.dll` lookup failure. Neither process/system PATH, the CUDA installation, nor PyTorch configuration is modified; PyTorch is not imported by this integration. No packages or DLLs were installed, copied, or changed.

The actual application's Transcribe reference workflow was verified on the NVIDIA GeForce RTX 4070 with **CUDA float16**, using the existing cuBLAS `12.9.2.10`, cuDNN `9.27.0.42`, and NVRTC `12.9.86` packages. Other GPU/runtime combinations are not verified. Missing or incompatible GPU libraries retain the CPU fallback and report the error in logs and the completed status tooltip.

## How to Run

From the repository root in the VS Code PowerShell terminal, use the **verified startup command**:

```powershell
& .\.cenv\python.exe -m qwen3_tts_studio
```

This selects the existing project-local environment without requiring activation. After `conda activate .\.cenv`, the equivalent command is `python -m qwen3_tts_studio`.

No model setup is required to launch the UI, play a reference, or enter text manually. Automatic transcription requires the local Small model and transcription dependencies described above. Missing `PySide6` errors mean the selected Python environment lacks the desktop dependency. Commands for the removed experimental scripts, such as `python generate_quest.py`, are no longer valid.

## Focused Verification

Run from the repository root with a Windows desktop session:

```powershell
& .\.cenv\python.exe -m unittest discover -s tests -v
```

The nineteen checks cover startup/window exposure, Exit/event-loop shutdown, resizing and Output visibility, splitter limits and dragging, WAV/OGG import, invalid files, draft protection, muted Qt playback, the Play/Pause toggle, Space handling, seeking/scrubbing, completion/replay, and seeking after completion. Rendering checks verify played/unplayed colors and highlighting in both themes, forward animation, synchronization, partial repainting, cache reuse, and stopped animation when paused. Workspace checks exercise Clear Reference and New Voice confirmation/cancellation, reset during playback/loading, and successful imports after reset. Transcription checks cover ICL/X-Vector switching, manual draft preservation, overwrite confirmation/cancellation, lazy model reuse, offline model validation, retained process-local DLL handles, float16 preference, CPU fallback/error logs, future Qwen prompt validation, errors/empty results, UI heartbeat, stale results after edits/mode/reference/reset changes, and shutdown during active work. These use a delayed model stand-in and temporary recordings/settings; the regular suite does not load AI models or download data. File Explorer-style drops use local-file Qt drag/drop events. Settings and About are exercised; the output-folder action uses a mocked OS launcher.

Separately, the actual application entry point and Transcribe reference button transcribed a 9.35-second temporary English speech fixture in WAV and OGG Vorbis on the RTX 4070. CTranslate2's loaded model reported `device=cuda` and `compute_type=float16` for both completed requests, not merely GPU availability. The model was reused; UI timers continued; PATH remained unchanged and PyTorch was not imported. Both returned the expected sentence and automatically detected English. An earlier CPU fallback check also covered model retention after New Voice and background unloading on exit. Inference checks are intentionally outside the normal test suite. Other languages and GPU configurations have not been tested.

Light/dark mode appearance and the minimum-size layout were visually reviewed locally. Automated theme checks exercise Qt's notification path without changing Windows personalization settings; a real Windows Settings toggle during execution remains a manual check. Audible speaker output, physical Explorer dragging, multi-monitor DPI changes, other codec variants, other machines, TTS inference, and packaged builds are outside this verification.

## Project Data

- `samples/`: place your own WAV/OGG reference files here. Their contents are ignored by Git.
- `output/`: future generated WAV files and related results go here. Their contents are ignored by Git.
- `models/`: local model weights and caches go here. Their contents are ignored by Git.

Each folder contains a `.gitkeep` placeholder so the empty directory structure exists in a fresh clone.

Do not put personal recordings, generated audio, or large model files in commits.

## Privacy and Responsible Use

The intended application processes voice recordings locally. Downloading dependencies and models requires an internet connection; ordinary transcription and synthesis should work offline once those assets are present.

Only clone or distribute voices and recordings you have permission to use. Third-party game audio, voice performances, trademarks, and other assets may be protected independently of the model or application license.

## License

The original Qwen3 TTS Studio application source is licensed under the **MIT License**, Copyright (c) 2026 **Nendis**. See [LICENSE](LICENSE).

Qwen3-TTS code and the initial 1.7B Base weights are licensed under **Apache License 2.0**. Faster Whisper and the initial Faster Whisper Small model are licensed under **MIT**. Those components retain their own licenses; the project's MIT license does not relicense them.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for source references and packaging obligations. A full inventory of redistributed runtime dependencies must be prepared before binary release.
