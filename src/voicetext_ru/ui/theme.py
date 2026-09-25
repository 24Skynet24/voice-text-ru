"""Вспомогательные функции оформления.

Второстепенные подписи (имя модели, время сохранения, пояснения в настройках)
должны быть приглушёнными, но читаемыми. Фиксированный серый цвет для этого не
годится: он теряется либо на светлой, либо на тёмной теме Windows. Поэтому цвет
вычисляется смешиванием цвета текста с цветом фона текущей палитры.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QWidget

_TEXT_WEIGHT = 0.62
"""Доля цвета текста в смеси: подпись заметно тише основного текста, но читается."""


def dim_color(widget: QWidget) -> QColor:
    """Приглушённый цвет подписи, подходящий и к светлой, и к тёмной теме."""
    palette = widget.palette()
    text = palette.color(QPalette.ColorRole.WindowText)
    background = palette.color(QPalette.ColorRole.Window)
    return QColor(
        _mix(text.red(), background.red()),
        _mix(text.green(), background.green()),
        _mix(text.blue(), background.blue()),
    )


def apply_dim(*widgets: QWidget) -> None:
    """Делает подписи приглушёнными."""
    for widget in widgets:
        widget.setStyleSheet(f"color: {dim_color(widget).name()};")


def _mix(foreground: int, background: int) -> int:
    return int(round(foreground * _TEXT_WEIGHT + background * (1.0 - _TEXT_WEIGHT)))
