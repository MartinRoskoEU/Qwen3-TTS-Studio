"""Serial voice preparation, profile I/O, generation, and shutdown workers."""

# Copyright (c) 2026 Nendis. SPDX-License-Identifier: MIT

import logging
from PySide6.QtCore import QObject, QThread, Signal, Slot

from .voice_profile import VoiceCancelled, export_wav, load_profile, save_profile
from ..integrations.qwen_tts import QwenVoiceModel
from ..audio.decoding import DecodeCancelled


class VoiceThread(QThread):
    ready = Signal(int, str, object)
    failed = Signal(int, str)
    phase = Signal(int, str)

    def __init__(self, adapter, request_id, operation, arguments, parent):
        super().__init__(parent)
        self.adapter, self.request_id = adapter, request_id
        self.operation, self.arguments = operation, arguments

    def run(self):
        cancelled = self.isInterruptionRequested
        report = lambda text: self.phase.emit(self.request_id, text)
        try:
            if self.operation == "release":
                self.adapter.release()
                return
            if self.operation == "prepare":
                result = self.adapter.prepare(self.arguments[0], cancelled, report)
            elif self.operation == "generate":
                result = self.adapter.generate(*self.arguments, cancelled, report)
            elif self.operation == "load":
                result = load_profile(self.arguments[0], self.adapter.models, cancelled)
            elif self.operation == "save":
                result = save_profile(*self.arguments, cancelled)
            elif self.operation == "export":
                result = export_wav(*self.arguments, cancelled)
            else:
                raise ValueError(f"Unknown voice operation: {self.operation}")
            if not cancelled():
                self.ready.emit(self.request_id, self.operation, result)
        except (VoiceCancelled, DecodeCancelled):
            pass
        except Exception as error:
            logging.getLogger(__name__).exception("Voice %s failed", self.operation)
            self.failed.emit(self.request_id, f"{type(error).__name__}: {error}")


class VoiceController(QObject):
    ready = Signal(str, object)
    failed = Signal(str)
    phase = Signal(str)
    busy_changed = Signal(bool)
    drained = Signal()

    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self._adapter = QwenVoiceModel(paths.models)
        self._worker = None
        self._request_id = 0
        self._closing = False
        self._released = False

    @property
    def busy(self):
        return self._worker is not None

    @property
    def has_workers(self):
        return self.busy

    @property
    def model_loaded(self):
        return self._adapter.loaded

    @property
    def model_description(self):
        return self._adapter.description() if self._adapter.loaded else "Not loaded"

    @property
    def gpu_error(self):
        return self._adapter.gpu_error

    def start(self, operation, *arguments):
        if self.busy or self._closing:
            return False
        self._request_id += 1
        self._start_worker(operation, arguments)
        return True

    def _start_worker(self, operation, arguments):
        worker = VoiceThread(self._adapter, self._request_id, operation, arguments, self)
        worker.ready.connect(self._ready)
        worker.failed.connect(self._failed)
        worker.phase.connect(self._phase)
        worker.finished.connect(self._finished)
        self._worker = worker
        self.busy_changed.emit(True)
        worker.start()

    def cancel(self):
        self._request_id += 1
        if self._worker is not None:
            self._worker.requestInterruption()

    @Slot(int, str, object)
    def _ready(self, request_id, operation, result):
        if not self._closing and request_id == self._request_id:
            self.ready.emit(operation, result)

    @Slot(int, str)
    def _failed(self, request_id, message):
        logging.getLogger(__name__).error("Voice operation: %s", message)
        if not self._closing and request_id == self._request_id:
            self.failed.emit(message)

    @Slot(int, str)
    def _phase(self, request_id, message):
        if not self._closing and request_id == self._request_id:
            self.phase.emit(message)

    @Slot()
    def _finished(self):
        worker, self._worker = self._worker, None
        worker.deleteLater()
        if self._closing and not self._released:
            self._released = True
            self._start_worker("release", ())
        else:
            self.busy_changed.emit(False)
            if self._closing:
                self.drained.emit()

    def shutdown(self):
        if self._closing:
            return
        self._closing = True
        self.cancel()
        if not self.busy:
            self._released = True
            if self._adapter.loaded:
                self._start_worker("release", ())
            else:
                self.drained.emit()

    def wait_for_shutdown(self):
        if self._worker is not None:
            self._worker.wait()
        self._adapter.release()
