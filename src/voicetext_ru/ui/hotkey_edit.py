"""Поле ввода сочетания клавиш для настроек (ТЗ §7).

Пользователь не набирает сочетание текстом, а нажимает его — так исключены
опечатки и сочетания, которые система заведомо не примет.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import QLineEdit, QWidget

from ..core.hotkey import format_hotkey, parse_hotkey

_MODIFIER_KEYS = {
    Qt.Key.Key_Control,
    Qt.Key.Key_Shift,
    Qt.Key.Key_Alt,
    Qt.Key.Key_Meta,
    Qt.Key.Key_AltGr,
    Qt.Key.Key_CapsLock,
    Qt.Key.Key_NumLock,
    Qt.Key.Key_unknown,
}


class HotkeyEdit(QLineEdit):
    """Поле, которое записывает нажатое сочетание клавиш."""

    hotkeyChanged = Signal(str)

    def __init__(self, sequence: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText("Нажмите сочетание клавиш…")
        self.setToolTip(
            "Нажмите нужное сочетание, например Ctrl+Shift+Space.\n"
            "Требуется хотя бы один модификатор (Ctrl, Alt, Shift или Win)."
        )
        self._sequence = ""
        self.set_hotkey(sequence)

    def hotkey(self) -> str:
        return self._sequence

    def set_hotkey(self, sequence: str) -> None:
        self._sequence = format_hotkey(sequence) if sequence else ""
        self.setText(self._sequence)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 — имя задано Qt
        key = Qt.Key(event.key())
        if key in _MODIFIER_KEYS:
            # Ждём основную клавишу: пока нажаты только модификаторы, сочетания нет.
            return
        if key == Qt.Key.Key_Escape:
            self.set_hotkey(self._sequence)
            return

        candidate = QKeySequence(event.keyCombination()).toString(QKeySequence.SequenceFormat.PortableText)
        if parse_hotkey(candidate) is None:
            self.setText("Нужен модификатор: Ctrl, Alt, Shift или Win")
            return

        self.set_hotkey(candidate)
        self.hotkeyChanged.emit(self._sequence)
