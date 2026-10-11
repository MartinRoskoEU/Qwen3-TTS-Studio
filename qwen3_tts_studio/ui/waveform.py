"""Peak envelope rendering and direct waveform seeking/scrubbing."""

# Copyright (c) 2026 Nendis. SPDX-License-Identifier: MIT

from math import ceil, floor

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QSizePolicy

from .theme import DARK, LIGHT


class WaveformView(QFrame):
    seek_requested = Signal(int)
    scrub_started = Signal()
    scrub_finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("waveformView")
        self.setAccessibleName("Waveform preview: no audio loaded")
        self.setMinimumHeight(80)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.recording = None
        self.duration_ms = 0
        self.position_ms = 0
        self.seekable = False
        self._dragging = False
        self._envelope = QPainterPath()
        self._unplayed_cache = QPixmap()
        self._played_cache = QPixmap()
        self._cache_dirty = True

    def set_recording(self, recording) -> None:
        self.recording = recording
        self.duration_ms = recording.duration_ms if recording else 0
        self.position_ms = 0
        self._dragging = False
        self.setAccessibleName("Audio waveform" if recording else "Waveform preview: no audio loaded")
        self._rebuild_envelope()
        self._cache_dirty = True
        self.update()

    def set_seekable(self, seekable: bool) -> None:
        self.seekable = seekable and self.recording is not None
        if not self.seekable:
            self._dragging = False
        self.setCursor(Qt.CursorShape.SizeHorCursor if self.seekable else Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus if self.seekable else Qt.FocusPolicy.NoFocus)

    def set_position(self, position_ms: float) -> None:
        position_ms = max(0, min(position_ms, self.duration_ms))
        if position_ms == self.position_ms:
            return
        old_x = self._playhead_x()
        self.position_ms = position_ms
        new_x = self._playhead_x()
        # Only this strip changes: old/new playheads and the played boundary.
        area = self._area()
        left, right = floor(min(old_x, new_x)) - 2, ceil(max(old_x, new_x)) + 2
        self.update(QRect(left, area.top(), right - left + 1, area.height()).intersected(self.rect()))

    def _playhead_x(self) -> float:
        area = self._area()
        return area.left() + self.position_ms / max(1, self.duration_ms) * (area.width() - 1)

    def _area(self):
        return self.rect().adjusted(12, 8, -12, -8)

    def _rebuild_envelope(self) -> None:
        self._envelope = QPainterPath()
        if not self.recording:
            return
        area = self._area()
        count = len(self.recording.lower)
        columns = min(count, max(1, area.width()))
        amplitude = max(1, area.height() / 2 - 2)
        # Reduce to display pixels once on load/resize, retaining every peak.
        # Redrawing the playhead must not stroke thousands of overlapping lines.
        for index in range(columns):
            first, last = index * count // columns, (index + 1) * count // columns
            lower = min(self.recording.lower[first:last])
            upper = max(self.recording.upper[first:last])
            x = area.left() + (index + 0.5) * area.width() / columns
            self._envelope.moveTo(x, area.center().y() - max(-1, min(1, upper)) * amplitude)
            self._envelope.lineTo(x, area.center().y() - max(-1, min(1, lower)) * amplitude)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._rebuild_envelope()
        self._cache_dirty = True

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.StyleChange,
                            QEvent.Type.FontChange, QEvent.Type.DevicePixelRatioChange):
            self._cache_dirty = True
            self.update()

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.DevicePixelRatioChange:
            self._cache_dirty = True
            self.update()
        return super().event(event)

    def _colors(self):
        return DARK if self.palette().color(QPalette.ColorRole.Window).lightness() < 128 else LIGHT

    def _rebuild_cache(self) -> None:
        """Rasterize static layers only on source, size, palette, or DPI changes."""
        area = self._area()
        if area.isEmpty():
            return
        ratio = self.devicePixelRatioF()
        colors = self._colors()
        for played in (False, True):
            cache = QPixmap(ceil(area.width() * ratio), ceil(area.height() * ratio))
            cache.setDevicePixelRatio(ratio)
            cache.fill(self.palette().color(QPalette.ColorRole.Base))
            painter = QPainter(cache)
            if played:
                tint = QColor(colors.waveform_played)
                tint.setAlpha(20)
                painter.fillRect(QRectF(0, 0, area.width(), area.height()), tint)
            painter.translate(-area.left(), -area.top())
            grid = QColor(self.palette().color(QPalette.ColorRole.Mid))
            grid.setAlpha(70)
            painter.setPen(grid)
            for x in range(area.left(), area.right(), 80):
                painter.drawLine(x, area.top(), x, area.bottom())
            painter.drawLine(area.left(), area.center().y(), area.right(), area.center().y())
            if self.recording:
                painter.setPen(QColor(colors.waveform_played if played else colors.waveform_unplayed))
                painter.drawPath(self._envelope)
            else:
                text = "No audio loaded"
                text_area = painter.fontMetrics().boundingRect(text).adjusted(-10, -4, 10, 4)
                text_area.moveCenter(area.center())
                painter.fillRect(text_area, self.palette().color(QPalette.ColorRole.Base))
                painter.setPen(self.palette().color(QPalette.ColorRole.PlaceholderText))
                painter.drawText(text_area, Qt.AlignmentFlag.AlignCenter, text)
            painter.end()
            if played:
                self._played_cache = cache
            else:
                self._unplayed_cache = cache
        self._cache_dirty = False

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setClipRegion(event.region())
        area = self._area()
        if self._cache_dirty:
            self._rebuild_cache()
        painter.drawPixmap(area.topLeft(), self._unplayed_cache)
        if self.recording:
            x = self._playhead_x()
            painter.save()
            painter.setClipRect(QRectF(area.left(), area.top(), x - area.left(), area.height()), Qt.ClipOperation.IntersectClip)
            painter.drawPixmap(area.topLeft(), self._played_cache)
            painter.restore()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(self._colors().waveform_played), 1)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))

    def _seek_at(self, x: float) -> None:
        area = self._area()
        fraction = max(0, min(1, (x - area.left()) / max(1, area.width() - 1)))
        self.seek_requested.emit(round(fraction * self.duration_ms))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.seekable:
            self._dragging = True
            self.scrub_started.emit()
            self._seek_at(event.position().x())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self._seek_at(event.position().x())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._seek_at(event.position().x())
            self._dragging = False
            self.scrub_finished.emit()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if self.seekable and event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Home, Qt.Key.Key_End):
            target = round(self.position_ms)
            if event.key() == Qt.Key.Key_Home:
                target = 0
            elif event.key() == Qt.Key.Key_End:
                target = self.duration_ms
            else:
                target += -2000 if event.key() == Qt.Key.Key_Left else 2000
            self.seek_requested.emit(max(0, min(target, self.duration_ms)))
            event.accept()
        else:
            super().keyPressEvent(event)
