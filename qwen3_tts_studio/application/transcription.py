"""Serial background model work with cancellation and obsolete-result protection."""

# Copyright (c) 2026 Nendis. SPDX-License-Identifier: MIT

from pathlib import Path
import logging

from PySide6.QtCore import QObject, QThread, Signal, Slot

from ..integrations.faster_whisper import FasterWhisperTranscriber, TranscriptionCancelled


class TranscriptionThread(QThread):
    ready = Signal(int, object)
    failed = Signal(int, str)
    phase = Signal(int, str)

    def __init__(self, adapter, request_id: int, reference: Path | None, parent=None):
        super().__init__(parent)
        self.adapter = adapter
        self.request_id = request_id
        self.reference = reference

    def run(self) -> None:
        try:
            if self.reference is None:
                self.adapter.release()
            else:
                result = self.adapter.transcribe(
                    self.reference, self.isInterruptionRequested,
                    lambda text: self.phase.emit(self.request_id, text),
                )
                if not self.isInterruptionRequested():
                    self.ready.emit(self.request_id, result)
        except TranscriptionCancelled:
            pass
        except Exception as error:
            self.failed.emit(self.request_id, f"{type(error).__name__}: {error}")


class TranscriptionController(QObject):
    ready = Signal(object)
    failed = Signal(str)
    phase = Signal(str)
    busy_changed = Signal(bool)
    drained = Signal()

    def __init__(self, models: Path, parent=None):
        super().__init__(parent)
        self._adapter = FasterWhisperTranscriber(models)
        self._worker = None
        self._request_id = 0
        self._closing = False
        self._released = False

    @property
    def busy(self) -> bool:
        return self._worker is not None

    @property
    def has_workers(self) -> bool:
        return self.busy

    def start(self, reference: Path) -> bool:
        if self._closing or self.busy:
            return False
        self._request_id += 1
        self._start_worker(reference)
        return True

    def _start_worker(self, reference: Path | None) -> None:
        worker = TranscriptionThread(self._adapter, self._request_id, reference, self)
        worker.ready.connect(self._ready)
        worker.failed.connect(self._failed)
        worker.phase.connect(self._phase)
        worker.finished.connect(self._finished)
        self._worker = worker
        self.busy_changed.emit(True)
        worker.start()

    def cancel(self) -> None:
        self._request_id += 1
        if self._worker is not None:
            self._worker.requestInterruption()

    @Slot(int, object)
    def _ready(self, request_id, result) -> None:
        if not self._closing and request_id == self._request_id:
            self.ready.emit(result)

    @Slot(int, str)
    def _failed(self, request_id, message) -> None:
        if not self._closing and request_id == self._request_id:
            self.failed.emit(message)
        elif self._closing:
            logging.getLogger(__name__).error("Background transcription shutdown: %s", message)

    @Slot(int, str)
    def _phase(self, request_id, message) -> None:
        if not self._closing and request_id == self._request_id:
            self.phase.emit(message)

    @Slot()
    def _finished(self) -> None:
        worker = self._worker
        self._worker = None
        worker.deleteLater()
        if self._closing and not self._released:
            self._released = True
            self._start_worker(None)
        else:
            self.busy_changed.emit(False)
            if self._closing:
                self.drained.emit()

    def shutdown(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.cancel()
        if not self.busy:
            self._released = True
            if self._adapter.loaded:
                self._start_worker(None)
            else:
                self.drained.emit()

    def wait_for_shutdown(self) -> None:
        """Fallback after the application event loop has ended."""
        if self._worker is not None:
            self._worker.wait()
        # No operation can still be using the adapter here.
        self._adapter.release()
