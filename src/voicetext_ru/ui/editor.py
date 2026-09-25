"""Текстовый редактор документа (ТЗ §3).

`QPlainTextEdit` уже обеспечивает весь требуемый набор операций — курсор,
выделение, буфер обмена, отмену и повтор, — поэтому здесь только настройка
внешнего вида и мелкие удобства.
"""

from __future__ import annotations

from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QPlainTextEdit, QWidget


class DocumentEditor(QPlainTextEdit):
    """Редактор простого текста с настройками, удобными для диктовки."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setPlaceholderText(
            "Создайте новый документ или откройте существующий, поставьте курсор "
            "в нужное место и нажмите «Запись»."
        )
        self.setTabChangesFocus(False)
        self.setUndoRedoEnabled(True)

        font = QFont("Segoe UI", 12)
        font.setStyleHint(QFont.StyleHint.SansSerif)
        self.setFont(font)
        self.setTabStopDistance(QFontMetrics(font).horizontalAdvance(" ") * 4)

        # Поле ввода занимает основную часть окна, поэтому поля делают текст читаемее.
        self.document().setDocumentMargin(16)

    def set_document_text(self, text: str) -> None:
        """Заменяет содержимое документа, сбрасывая историю отмены.

        Используется при открытии файла: отменять «открытие» до предыдущего
        документа пользователь не должен.
        """
        self.setPlainText(text)
        self.document().clearUndoRedoStacks()
        self.moveCursor(self.textCursor().MoveOperation.Start)

    @property
    def has_selection(self) -> bool:
        return self.textCursor().hasSelection()
