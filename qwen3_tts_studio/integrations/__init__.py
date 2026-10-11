"""Boundary for future local model adapters; no models are imported or loaded.

Future synthesis and transcription adapters belong here. The UI must dispatch
loading, decoding, inference, and export to background workers, with cancellation
and session identity checks before applying results. No such work exists yet.
"""

# Copyright (c) 2026 Nendis. SPDX-License-Identifier: MIT
