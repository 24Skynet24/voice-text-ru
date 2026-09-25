"""Проверка вставки распознанного текста в документ (ТЗ §15, §16)."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QPlainTextEdit

from voicetext_ru.ui.transcript_inserter import TranscriptInserter


@pytest.fixture()
def editor(qt_app):  # noqa: ANN001, ANN201
    widget = QPlainTextEdit()
    yield widget
    widget.deleteLater()


def place_cursor(widget: QPlainTextEdit, position: int) -> None:
    cursor = widget.textCursor()
    cursor.setPosition(position)
    widget.setTextCursor(cursor)


def test_text_is_inserted_at_cursor_not_at_the_end(editor: QPlainTextEdit) -> None:
    """Ключевое требование ТЗ §16: текст идёт с позиции курсора."""
    editor.setPlainText("Первый абзац.\n\nТретий абзац.")
    place_cursor(editor, len("Первый абзац.\n"))

    inserter = TranscriptInserter(editor)
    inserter.begin()
    inserter.commit("вставленный текст")
    inserter.end()

    assert editor.toPlainText() == "Первый абзац.\nвставленный текст\nТретий абзац."


def test_existing_text_is_preserved(editor: QPlainTextEdit) -> None:
    editor.setPlainText("начало конец")
    place_cursor(editor, len("начало"))

    inserter = TranscriptInserter(editor)
    inserter.begin()
    inserter.commit("середина")
    inserter.end()

    text = editor.toPlainText()
    assert text.startswith("начало")
    assert text.endswith("конец")
    assert "середина" in text


def test_partial_text_is_replaced_not_appended(editor: QPlainTextEdit) -> None:
    """Уточнение черновика не должно порождать «лесенку» из повторов."""
    inserter = TranscriptInserter(editor)
    inserter.begin()

    inserter.set_partial("я хочу")
    inserter.set_partial("я хочу сделать")
    inserter.set_partial("я хочу сделать приложение")

    assert editor.toPlainText() == "я хочу сделать приложение"


def test_commit_replaces_the_draft(editor: QPlainTextEdit) -> None:
    inserter = TranscriptInserter(editor)
    inserter.begin()
    inserter.set_partial("я хочу сделать")
    inserter.commit("я хочу сделать приложение для Windows")
    inserter.end()

    assert editor.toPlainText() == "я хочу сделать приложение для Windows"


def test_several_confirmations_are_separated_by_spaces(editor: QPlainTextEdit) -> None:
    inserter = TranscriptInserter(editor)
    inserter.begin()
    inserter.commit("первая фраза")
    inserter.set_partial("вторая")
    inserter.commit("вторая фраза")
    inserter.end()

    assert editor.toPlainText() == "первая фраза вторая фраза"


def test_draft_is_removed_when_recognition_yields_nothing(editor: QPlainTextEdit) -> None:
    inserter = TranscriptInserter(editor)
    inserter.begin()
    inserter.set_partial("сомнительный черновик")
    inserter.set_partial("")
    inserter.end()

    assert editor.toPlainText() == ""


def test_draft_left_over_is_cleared_on_end(editor: QPlainTextEdit) -> None:
    """При остановке записи неподтверждённый текст не должен остаться в файле."""
    editor.setPlainText("основа")
    place_cursor(editor, len("основа"))

    inserter = TranscriptInserter(editor)
    inserter.begin()
    inserter.set_partial("черновик")
    inserter.end()

    assert editor.toPlainText() == "основа"


def test_user_edits_above_do_not_shift_the_insertion_point(editor: QPlainTextEdit) -> None:
    """Правка текста выше по документу не должна ломать точку вставки."""
    editor.setPlainText("строка A\nстрока B")
    place_cursor(editor, len("строка A\nстрока B"))

    inserter = TranscriptInserter(editor)
    inserter.begin()
    inserter.commit("распознано")

    # Пользователь дописывает текст в начало документа.
    cursor = QTextCursor(editor.document())
    cursor.setPosition(0)
    cursor.insertText("НАЧАЛО ")

    inserter.commit("продолжение")
    inserter.end()

    assert editor.toPlainText() == "НАЧАЛО строка A\nстрока B распознано продолжение"


def test_context_text_returns_characters_before_insertion_point(editor: QPlainTextEdit) -> None:
    editor.setPlainText("Предыдущий текст документа")
    place_cursor(editor, len("Предыдущий текст документа"))

    inserter = TranscriptInserter(editor)
    inserter.begin()

    assert inserter.context_text().endswith("документа")


def test_undo_removes_one_utterance_at_a_time(editor: QPlainTextEdit) -> None:
    """Обновление черновика раз в секунду не должно засорять историю отмены (ТЗ §3)."""
    inserter = TranscriptInserter(editor)
    inserter.begin()
    for draft in ("пер", "перв", "первая", "первая фраза"):
        inserter.set_partial(draft)
    inserter.commit("первая фраза")
    inserter.commit("вторая фраза")
    inserter.end()

    assert editor.toPlainText() == "первая фраза вторая фраза"
    editor.undo()
    assert editor.toPlainText() == "первая фраза"
    editor.undo()
    assert editor.toPlainText() == ""


def test_insertion_is_ignored_before_begin(editor: QPlainTextEdit) -> None:
    inserter = TranscriptInserter(editor)
    inserter.commit("не должно появиться")
    inserter.set_partial("и это тоже")

    assert editor.toPlainText() == ""
