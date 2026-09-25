"""Индикатор уровня сигнала микрофона (ТЗ §18).

Индикатор функциональный, а не декоративный: по нему пользователь понимает,
что звук действительно поступает, и видит, не слишком ли тихо он говорит.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QSizePolicy, QWidget

_SEGMENTS = 18
_MIN_DB = -55.0
"""Ниже этого уровня считаем, что сигнала нет."""


def level_to_fraction(level: float) -> float:
    """Переводит линейную амплитуду 0..1 в долю шкалы 0..1.

    Шкала логарифмическая: слух воспринимает громкость именно так, и тихая,
    но разборчивая речь не выглядит на индикаторе «пустой».
    """
    if level <= 0.0:
        return 0.0
    decibels = 20.0 * math.log10(max(level, 1e-6))
    if decibels <= _MIN_DB:
        return 0.0
    return min(1.0, (decibels - _MIN_DB) / (0.0 - _MIN_DB))


class LevelMeter(QWidget):
    """Сегментная шкала уровня входного сигнала."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fraction = 0.0
        self._enabled = False
        self.setMinimumSize(140, 14)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolTip("Уровень сигнала микрофона")

    def set_level(self, level: float) -> None:
        fraction = level_to_fraction(level)
        if abs(fraction - self._fraction) < 0.005:
            return
        self._fraction = fraction
        self.update()

    def set_active(self, active: bool) -> None:
        """Неактивный индикатор рисуется приглушённо и не показывает уровень."""
        if self._enabled == active:
            return
        self._enabled = active
        if not active:
            self._fraction = 0.0
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 — имя задано Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        width = self.width()
        height = self.height()
        gap = 2.0
        segment_width = max(1.0, (width - gap * (_SEGMENTS - 1)) / _SEGMENTS)
        lit_count = int(round(self._fraction * _SEGMENTS))

        palette = self.palette()
        empty_color = palette.mid().color()
        empty_color.setAlpha(90)

        for index in range(_SEGMENTS):
            rect = QRectF(index * (segment_width + gap), 0.0, segment_width, height)
            if self._enabled and index < lit_count:
                painter.fillRect(rect, _segment_color(index))
            else:
                painter.fillRect(rect, empty_color)

        painter.end()


def _segment_color(index: int) -> QColor:
    """Зелёный — рабочий уровень, жёлтый — громко, красный — риск перегрузки."""
    ratio = index / max(1, _SEGMENTS - 1)
    if ratio < 0.7:
        return QColor(58, 170, 88)
    if ratio < 0.88:
        return QColor(214, 178, 48)
    return QColor(206, 74, 62)
