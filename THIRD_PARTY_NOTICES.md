# Third-Party Licenses and Notices

Qwen3 TTS Studio's original source code is licensed under the MIT License (Copyright (c) 2026 Nendis). The dependencies and model weights listed below are **not relicensed** under that license.

This file identifies the initial core technologies. The current Git repository does not bundle their libraries or model weights. This is **not** yet a complete license inventory for an executable distribution.

## Qwen3-TTS — Python Library

- Project: [QwenLM/Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS)
- License: **Apache License, Version 2.0**
- License text: https://github.com/QwenLM/Qwen3-TTS/blob/main/LICENSE
- Upstream attribution: Alibaba Qwen Team / Alibaba Cloud (see the upstream repository and its copyright notices)

When distributing the covered code or derivative works, follow the terms of Apache-2.0, including providing the license text, retaining applicable notices, identifying modified files, and including applicable upstream `NOTICE` notices if present.

## Qwen3-TTS-12Hz-1.7B-Base — Model Weights

- Model: [Qwen/Qwen3-TTS-12Hz-1.7B-Base](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base)
- License shown on model card: **Apache License, Version 2.0**
- Source of license: https://www.apache.org/licenses/LICENSE-2.0

Model weights are downloaded separately and are not committed to this repository. Follow the model's applicable license and attribution requirements if redistributing them.

## Faster Whisper — Python Library

- Project: [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- License: **MIT License**
- Upstream copyright: **Copyright (c) 2023 SYSTRAN**
- License text: https://github.com/SYSTRAN/faster-whisper/blob/master/LICENSE

When redistributing this library or substantial portions of it, preserve the upstream copyright and permission notice.

## Faster Whisper Small — ASR Model

- Model: [Systran/faster-whisper-small](https://huggingface.co/Systran/faster-whisper-small)
- License shown on model card: **MIT License**
- Original model: [openai/whisper-small](https://huggingface.co/openai/whisper-small)
- Original Whisper repository: https://github.com/openai/whisper
- Original Whisper license: https://github.com/openai/whisper/blob/main/LICENSE

The Faster Whisper Small model is a converted Whisper Small model. Keep applicable model and source attribution and notices if distributing its weights.

## PySide6 / Shiboken6 / Qt — Desktop UI

- Project: [Qt for Python](https://doc.qt.io/qtforpython-6/)
- Verified desktop version: **PySide6 / Qt 6.12.0**. PySide6, PySide6 Essentials, and Shiboken6 package metadata identify the open-source license alternatives as `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`.
- Qt for Python is available under open-source and commercial terms; see [Qt for Python licensing](https://doc.qt.io/qtforpython-6/commercial/index.html). Qt modules have their own applicable terms; see [Qt licensing](https://doc.qt.io/qt-6/licensing.html).
- Upstream attribution: The Qt Company Ltd. and contributors; retain the exact shipped components' upstream copyright notices.
- Third-party components: [Licenses used in Qt for Python](https://doc.qt.io/qtforpython-6/licenses.html).

The application currently imports Qt Core, GUI, Widgets, and Multimedia; focused checks also use Qt Test. Playback uses the supported `QMediaPlayer` and `QAudioOutput` APIs. See [Qt Multimedia licenses and attributions](https://doc.qt.io/qt-6/qtmultimedia-index.html#licenses-and-attributions) for the module and its backend components, including FFmpeg. The exact backend libraries and codec licenses must be inventoried for the binaries shipped in any future package.

No Qt binaries are bundled in this repository. The application's MIT license does not replace Qt's license. Before packaging, identify the exact shipped modules, select applicable license terms, and include their required notices and license texts. For LGPL distribution, address the [official LGPL obligations](https://www.qt.io/development/open-source-lgpl-obligations), including replacement/relinking rights and required source availability. A source-only desktop application is not a completed binary redistribution audit.

## SoundFile / libsndfile — Reference Audio Decoding

- Project: [python-soundfile](https://python-soundfile.readthedocs.io/)
- Verified version: **SoundFile 0.14.0**, using **libsndfile 1.2.2** in the existing environment.
- SoundFile license: **BSD 3-Clause**, Copyright (c) 2013, Bastian Bechtold. Retain the [upstream license](https://github.com/bastibe/python-soundfile/blob/master/LICENSE) and notices when redistributing it.
- libsndfile license: **LGPL-2.1-or-later**; the installed binary includes an LGPL 2.1 `COPYING` file. See [libsndfile licensing](https://libsndfile.github.io/libsndfile/#licensing).
- SoundFile also depends on CFFI and NumPy. The installed **CFFI 2.1.1** package identifies **MIT No Attribution (MIT-0)** in its metadata and license file; retain applicable component-specific notices. See [CFFI source](https://github.com/python-cffi/cffi).

No decoder binaries are bundled in this repository. Before redistribution, include SoundFile's license, libsndfile's license/source obligations, and the exact decoder build's codec notices. The installed SoundFile distribution provides `licensing/license_notes.md` for its linked media libraries; preserve and review those notices when packaging.

## NumPy — Waveform Envelope Preparation

- Project: [NumPy](https://numpy.org/)
- Verified version: **2.5.3**.
- Core license: **BSD 3-Clause**; see the [NumPy license](https://numpy.org/doc/stable/license.html).
- The installed distribution's license expression is `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0`. Its license directory contains additional third-party component notices.

Retain the exact shipped distribution's license texts, copyright notices, conditions, and disclaimers. No NumPy binaries are bundled here.

## Other Runtime Dependencies

Additional dependencies may include PyTorch, TorchAudio, CTranslate2, PyAV, and packaging libraries chosen later. **Do not assume they all have the same license.**

Before packaging and distributing a Windows application, produce a complete inventory of **the exact shipped versions and assets** and include all license texts, required copyright notices, and attribution files. Check optional GPU libraries separately, where relevant.

## Voice Rights

Open-source licenses for these tools do not grant rights to recordings, performances, speaker identities, trademarks, game content, or other third-party material. Users are responsible for permissions relating to their reference voices and generated content.
