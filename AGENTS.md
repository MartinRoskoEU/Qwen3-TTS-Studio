# AGENTS.md

## Project

Qwen3 TTS Studio is an offline-first Windows desktop application project for voice cloning, text-to-speech generation, audio transcription, and subsequent audio processing.

The application is being developed from a clean repository scaffold. The local Python environment, downloaded models, and data folders already exist on the development machine, but application source files and a GUI have not yet been implemented.

## Current Stack

- Python 3.12
- Project-local Conda environment: `.cenv/`
- Qwen3-TTS 1.7B Base for speech synthesis and voice cloning
- Faster Whisper (initially the Small model) for speech transcription
- PyTorch for inference; CUDA when available and CPU otherwise
- SoundFile for WAV export, where appropriate
- Windows and Visual Studio Code as the initial development setup

Do not infer that other frameworks or packages have been selected.

## Working Rules

1. Inspect relevant files and the existing architecture before making changes.
2. Work incrementally, in the scope requested. Do not add unrelated features or refactors.
3. Prefer official, maintained APIs and production-quality solutions. Do not use monkey patches or unsupported internals.
4. Preserve existing names and conventions unless a change is needed for correctness or explicitly requested.
5. State important assumptions, uncertainties, compatibility risks, and trade-offs clearly.
6. Before choosing the desktop UI toolkit or making a major architectural decision, present the options and obtain approval.
7. Do not install, upgrade, downgrade, or remove packages, download large models, or change the environment without approval.
8. Never modify or delete user reference recordings or existing generated outputs without explicit user intent. Destructive actions require confirmation in the eventual UI.
9. Keep local speech generation and transcription offline after the required dependencies and models have been downloaded.
10. Do not claim that an unimplemented feature or an untested platform is supported.

## Architecture Expectations

Keep the following responsibilities separate:

- User interface and user interaction
- Model loading and inference
- Reference audio preparation and transcription
- Speech-generation parameter validation
- Post-processing, preview, and WAV export
- Model and file management
- Background task orchestration, error reporting, and cancellation

Avoid blocking the UI thread during model loading, inference, audio decoding, or export. Ensure that cancellation, worker completion, and obsolete results cannot corrupt application state. Reuse loaded models when safe and release resources when switching or closing.

The package layout and UI toolkit have not yet been chosen; do not invent them as established project conventions.

## Model Inference

- Initial synthesis model: `models/Qwen3-TTS-12Hz-1.7B-Base/`.
- Support reference-audio voice cloning with `ref_text` and with the officially supported speaker-embedding-only mode.
- Use the actual model API. Only expose generation settings the installed version supports.
- Prefer CUDA where it is available and compatible, with an explicit CPU option or fallback.
- Select device, numerical precision, and attention implementation based on actual runtime support. Do not assume all GPUs support the same settings.
- Handle GPU out-of-memory failures and other model errors without losing user work.
- Different sampling runs may produce different voice results. Do not present stochastic controls as deterministic speed or emotion controls.

## Transcription

- Use Faster Whisper to transcribe reference audio locally.
- Start with English WAV/OGG support; allow future language expansion without coupling transcription to synthesis.
- Show the transcription for human review and correction before using it as `ref_text`.
- Handle unintelligible speech, empty results, bad files, and decoding failures explicitly.
- Do not assume machine transcripts are exact, especially for stylized game voices.

## Audio Processing and Outputs

- Preserve the original reference recording.
- Store reference recordings in `samples/`, generated artifacts in `output/`, and downloaded model files in `models/`.
- Use unique, descriptive filenames; never silently overwrite outputs.
- Preserve useful generation metadata (model, reference, mode, parameters, device, timings) when a suitable design is implemented.
- Tempo, pitch, normalization, and pause adjustment are future post-processing features, not built-in controls of the Base model.
- Any post-processing must be non-destructive and avoid misleading claims about lossless quality.

## Progress and Performance

- Report current operation and elapsed time for long-running work.
- Do not fabricate completion percentages. Only show a percentage when supported by real task progress.
- Record audio duration, generation time, and real-time factor where meaningful.
- Keep CPU-only operation viable, even if slower than GPU execution.

## Quality and Tests

- Validate file paths, formats, writable destinations, input text, and required models before beginning work.
- Keep errors actionable and do not swallow exceptions silently.
- Add focused automated tests for non-inference logic and background state management.
- Avoid running costly inference or downloading models during normal tests unless explicitly authorized.
- Report what was tested, what was not, and any outstanding limitations.

## Repository Rules

- Never commit `.cenv/`, downloaded model weights, reference recordings, generated audio, caches, or secrets.
- Keep `models/`, `samples/`, and `output/` tracked using their `.gitkeep` placeholders.
- Update `README.md` whenever install, launch, model setup, supported features, or directory layout changes.
- Once an application entry point exists, document the exact, tested launch command in `README.md`.
- Keep the source MIT-licensed with `Copyright (c) 2026 Nendis`.
- Maintain `THIRD_PARTY_NOTICES.md`; verify relevant dependency and model licenses before packaging or redistributing third-party software.
- Do not remove upstream copyright and license notices from redistributed third-party components.

## Delivery

After each completed change, summarize the files changed, behavior implemented, verification performed, and any remaining risks. Avoid claiming a successful build or test without executing it.
