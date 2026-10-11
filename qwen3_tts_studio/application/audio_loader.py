"""Cancellable reference preparation with rejection of obsolete completions."""

# Copyright (c) 2026 Nendis. SPDX-License-Identifier: MIT

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot

from ..audio.decoding import DecodeCancelled, prepare_waveform


class DecodeThread(QThread):
    decoded = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, request_id: int, path: Path, parent: QObject):
        super().__init__(parent)
        self.request_id = request_id
        self.path = path

    def run(self) -> None:
        try:
            recording = prepare_waveform(self.path, self.isInterruptionRequested)
        except DecodeCancelled:
            return
        except Exception as error:
            self.failed.emit(self.request_id, f"{type(error).__name__}: {error}")
        else:
            self.decoded.emit(self.request_id, recording)


class AudioLoader(QObject):
    ready = Signal(object)
    failed = Signal(str)
    drained = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._request_id = 0
        self._workers: set[DecodeThread] = set()
        self._closing = False

    @property
    def has_workers(self) -> bool:
        return bool(self._workers)

    def cancel(self) -> None:
        self._request_id += 1
        for worker in self._workers:
            worker.requestInterruption()

    def load(self, path: Path) -> None:
        if self._closing:
            return
        self.cancel()
        worker = DecodeThread(self._request_id, path, self)
        self._workers.add(worker)
        worker.decoded.connect(self._decoded)
        worker.failed.connect(self._failed)
        worker.finished.connect(self._finished)
        worker.start()

    @Slot(int, object)
    def _decoded(self, request_id: int, recording) -> None:
        if not self._closing and request_id == self._request_id:
            self.ready.emit(recording)

    @Slot(int, str)
    def _failed(self, request_id: int, message: str) -> None:
        if not self._closing and request_id == self._request_id:
            self.failed.emit(message)

    @Slot()
    def _finished(self) -> None:
        worker = self.sender()
        self._workers.discard(worker)
        worker.deleteLater()
        if self._closing and not self._workers:
            self.drained.emit()

    def shutdown(self) -> None:
        self._closing = True
        self.cancel()

    def wait_for_shutdown(self) -> None:
        """Used only after the application's UI event loop has exited."""
        self.shutdown()
        for worker in tuple(self._workers):
            worker.wait()
