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

## Other Runtime Dependencies

Additional dependencies may include PyTorch, TorchAudio, CTranslate2, PyAV, SoundFile, and GUI or packaging libraries chosen later. **Do not assume they all have the same license.**

Before packaging and distributing a Windows application, produce a complete inventory of **the exact shipped versions and assets** and include all license texts, required copyright notices, and attribution files. Check optional GPU libraries separately, where relevant.

## Voice Rights

Open-source licenses for these tools do not grant rights to recordings, performances, speaker identities, trademarks, game content, or other third-party material. Users are responsible for permissions relating to their reference voices and generated content.
