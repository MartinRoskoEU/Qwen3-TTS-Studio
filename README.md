# Qwen3 TTS Studio

**Offline-first desktop voice cloning, speech synthesis, and transcription.**

Qwen3 TTS Studio is a Windows-focused application project using Qwen3-TTS and Faster Whisper. Its goal is to make it practical to prepare, clone, generate, review, and export voices locally, including voices from short reference recordings.

## Project Status

**Early development / repository scaffold.**

Initial local command-line experiments with Qwen3-TTS 1.7B Base and Faster Whisper have succeeded on CPU and an NVIDIA GPU. Those test scripts have been removed in preparation for building the application. **The desktop frontend and its startup command do not yet exist.** The items described under *Planned Features* are goals, not released functionality.

## Planned Features

- Clone a voice from a short WAV or OGG reference recording.
- Generate speech with Qwen3-TTS 1.7B Base.
- Select reference-text-based or speaker-embedding-only cloning.
- Automatically transcribe speech locally using Faster Whisper, with manual transcript correction.
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
- [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS), initially `Qwen3-TTS-12Hz-1.7B-Base`
- [Faster Whisper](https://github.com/SYSTRAN/faster-whisper), initially Small
- PyTorch, TorchAudio, and SoundFile

The original development environment used an RTX 4070 with PyTorch and TorchAudio `2.11.0+cu130`. This is a record of the tested machine, **not a universal requirement**. Compatible installation instructions and pinned dependencies will be finalized when the application is implemented.

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
├── .gitignore
├── AGENTS.md
├── LICENSE
├── README.md
└── THIRD_PARTY_NOTICES.md
```

The application source layout has not been selected yet.

## Environment Setup

Open the **Qwen3 TTS Studio** directory in Visual Studio Code. In the integrated **PowerShell** terminal, activate the existing project-local environment:

```powershell
conda activate .\.cenv
```

Check that it is active:

```powershell
python --version
```

The intended Python version is 3.12.

If you need to recreate the environment on a different machine, you can first create an empty local environment:

```powershell
conda create --prefix .\.cenv python=3.12 -y
conda activate .\.cenv
```

**This only creates Python, not the application's complete dependencies.** A reproducible dependency manifest and supported installation sequence will be added as part of the implementation. CUDA-enabled PyTorch must be installed from a build appropriate for the target OS, Python version, and GPU driver.

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

The Faster Whisper model directory may contain a downloaded-model cache rather than a single named subfolder. The future application should manage and report actual locations.

## How to Run

**There is no runnable desktop application yet.** The experimental scripts have intentionally been removed, so commands such as `python generate_quest.py` are no longer valid.

When the first application entry point is implemented and tested, this section must be updated with the exact command to start it from the VS Code terminal, along with any necessary model installation steps. Until then, only the environment activation instructions above apply.

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
