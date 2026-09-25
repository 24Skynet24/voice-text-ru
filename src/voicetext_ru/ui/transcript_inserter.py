"""Вставка распознанного текста в документ (ТЗ §15, §16).

Ключевая идея: промежуточный («черновой») текст — это не дописанная строка,
а **область документа**. Каждое уточнение заменяет эту область целиком, а
подтверждение заменяет её окончательным текстом и сдвигает точку вставки.
Поэтому дублирование вида «я хочу / я хочу сделать / я хочу сделать приложение»
структурно невозможно.

Точка вставки хранится в `QTextCursor`: Qt сам сдвигает такие курсоры при
изменениях документа, поэтому правки пользователя выше по тексту не ломают
позицию вставки.
"""

from __future__ import annotations

import logging

from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit

from ..asr.postprocess import join_with_previous

logger = logging.getLogger(__name__)

_CONTEXT_CHARS = 180
_PARTIAL_COLOR = QColor(128, 128, 128)


class TranscriptInserter:
    """Управляет областью распознанного текста внутри редактора."""

    def __init__(self, editor: QPlainTextEdit) -> None:
        self._editor = editor
        self._anchor: QTextCursor | None = None
        self._partial_length = 0
        self._block_open = False
        self._revision = -1

    # ---------------------------------------------------------------- #

    @property
    def is_active(self) -> bool:
        return self._anchor is not None

    def begin(self) -> None:
        """Запоминает позицию курсора — с неё пойдёт вставка (ТЗ §16).

        Позиция определяется один раз, в момент начала записи; в конец документа
        текст не переносится.
        """
        cursor = QTextCursor(self._editor.document())
        cursor.setPosition(self._editor.textCursor().selectionEnd())
        # Курсор не должен сдвигаться, когда мы вставляем текст в его позицию:
        # иначе точка вставки «убежит» за черновик.
        cursor.setKeepPositionOnInsert(True)
        self._anchor = cursor
        self._partial_length = 0
        self._block_open = False
        self._revision = self._editor.document().revision()

    def end(self) -> None:
        """Завершает сеанс вставки, убирая оставшийся черновик."""
        if self._anchor is None:
            return
        if self._partial_length:
            self._replace_region("", partial=True)
        self._close_block()
        self._anchor = None
        self._partial_length = 0

    def context_text(self) -> str:
        """Текст перед точкой вставки — контекст для модели."""
        if self._anchor is None:
            return ""
        end = self._anchor.position()
        start = max(0, end - _CONTEXT_CHARS)
        cursor = QTextCursor(self._editor.document())
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        return cursor.selectedText().replace(" ", "\n")

    # ---------------------------------------------------------------- #

    def set_partial(self, text: str) -> None:
        """Показывает неподтверждённый текст, заменяя предыдущий черновик."""
        if self._anchor is None:
            return
        prepared = join_with_previous(self._text_before(), text) if text else ""
        if prepared == self._current_region_text():
            return
        self._replace_region(prepared, partial=True)
        self._partial_length = len(prepared)

    def commit(self, text: str) -> None:
        """Заменяет черновик окончательным текстом и сдвигает точку вставки."""
        if self._anchor is None or not text:
            return
        prepared = join_with_previous(self._text_before(), text)
        self._replace_region(prepared, partial=False)
        self._anchor.setPosition(self._anchor.position() + len(prepared))
        self._partial_length = 0
        self._close_block()

    # ---------------------------------------------------------------- #
    # Работа с документом
    # ---------------------------------------------------------------- #

    def _replace_region(self, text: str, *, partial: bool) -> None:
        """Заменяет текущую область черновика на `text`."""
        assert self._anchor is not None
        document = self._editor.document()
        start = self._anchor.position()
        end = min(start + self._partial_length, max(0, document.characterCount() - 1))

        cursor = QTextCursor(document)
        self._open_block(cursor)
        try:
            cursor.setPosition(start)
            if end > start:
                cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText(text, _partial_format() if partial else QTextCharFormat())
        finally:
            cursor.endEditBlock()
            self._revision = document.revision()

        self._follow_cursor(start + len(text))

    def _open_block(self, cursor: QTextCursor) -> None:
        """Объединяет правки одного высказывания в один шаг отмены (ТЗ §3).

        Без этого обновление черновика раз в секунду засоряло бы историю отмены.
        Объединение выполняется только если после нашей последней правки документ
        никто не менял — иначе правка пользователя попала бы в тот же шаг отмены.
        """
        if self._block_open and self._editor.document().revision() == self._revision:
            cursor.joinPreviousEditBlock()
        else:
            cursor.beginEditBlock()
            self._block_open = True

    def _close_block(self) -> None:
        self._block_open = False

    def _current_region_text(self) -> str:
        if self._anchor is None or self._partial_length == 0:
            return ""
        document = self._editor.document()
        start = self._anchor.position()
        end = min(start + self._partial_length, max(0, document.characterCount() - 1))
        cursor = QTextCursor(document)
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        return cursor.selectedText().replace(" ", "\n")

    def _text_before(self, length: int = 2) -> str:
        """Несколько символов перед точкой вставки — чтобы решить, нужен ли пробел."""
        if self._anchor is None:
            return ""
        end = self._anchor.position()
        start = max(0, end - length)
        if start == end:
            return ""
        cursor = QTextCursor(self._editor.document())
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        return cursor.selectedText().replace(" ", "\n")

    def _follow_cursor(self, position: int) -> None:
        """Ведёт видимый курсор за распознанным текстом, не мешая правке.

        Если пользователь выделил фрагмент (правит текст), выделение сохраняется.
        """
        visible = self._editor.textCursor()
        if visible.hasSelection():
            return
        visible.setPosition(min(position, max(0, self._editor.document().characterCount() - 1)))
        self._editor.setTextCursor(visible)
        self._editor.ensureCursorVisible()


def _partial_format() -> QTextCharFormat:
    """Оформление чернового текста: серый курсив — видно, что текст уточняется."""
    fmt = QTextCharFormat()
    fmt.setForeground(_PARTIAL_COLOR)
    fmt.setFontItalic(True)
    return fmt
