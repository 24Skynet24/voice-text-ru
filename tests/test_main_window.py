"""Проверка главного окна без микрофона и модели распознавания.

Окно создаётся целиком, но контроллер не запускается: проверяется связывание
сигналов, переходы состояний и работа с документом.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from voicetext_ru.core.state import AppState
from voicetext_ru.settings import Settings


@pytest.fixture()
def window(qt_app, tmp_path, monkeypatch):  # noqa: ANN001, ANN201
    """Главное окно с настройками, которые не попадают в профиль пользователя."""
    from voicetext_ru.ui.main_window import MainWindow

    monkeypatch.setattr(Settings, "save", lambda self, path=None: None)

    settings = Settings(hotkey_enabled=False, preload_model=False, last_directory=str(tmp_path))
    main_window = MainWindow(settings)
    yield main_window
    main_window._controller.shutdown()
    main_window.deleteLater()


def open_document(window, path: Path, text: str = "") -> None:  # noqa: ANN001
    """Создаёт документ в обход файловых диалогов."""
    window._document.create(path)
    window._editor.set_document_text(text)
    window._after_document_opened()


def test_window_starts_without_document(window) -> None:  # noqa: ANN001
    assert window._controller.state is AppState.NO_DOCUMENT
    assert not window._record_button.isEnabled()
    assert window._state_label.text() == AppState.NO_DOCUMENT.label


def test_recording_is_enabled_after_document_is_created(window, tmp_path: Path) -> None:  # noqa: ANN001
    open_document(window, tmp_path / "заметки.txt")

    assert window._record_button.isEnabled()
    assert window._state_label.text() == AppState.READY.label
    assert "заметки.txt" in window.windowTitle()


def test_recording_cannot_start_without_document(window, monkeypatch) -> None:  # noqa: ANN001
    """ТЗ §4: без документа запись не начинается, пользователь получает сообщение."""
    warnings: list[str] = []
    monkeypatch.setattr(window, "_show_warning", warnings.append)

    window._start_recording()

    assert warnings == ["Сначала создайте или откройте документ."]
    assert window._controller.state is AppState.NO_DOCUMENT


def test_hotkey_without_document_warns_instead_of_recording(window, monkeypatch) -> None:  # noqa: ANN001
    """ТЗ §7: то же правило действует и для глобального сочетания клавиш."""
    warnings: list[str] = []
    monkeypatch.setattr(window, "_show_warning", warnings.append)
    monkeypatch.setattr(window, "_activate_window", lambda: None)

    window._on_hotkey()

    assert warnings == ["Сначала создайте или откройте документ."]


def test_confirmed_text_lands_in_the_document_and_is_saved(window, tmp_path: Path) -> None:  # noqa: ANN001
    target = tmp_path / "диктовка.txt"
    open_document(window, target)

    window._inserter.begin()
    window._on_partial("сегодня я")
    window._on_commit("сегодня я тестирую приложение")
    window._on_recording_finished()

    assert window._editor.toPlainText() == "сегодня я тестирую приложение"
    assert target.read_text(encoding="utf-8").strip() == "сегодня я тестирую приложение"


def test_text_is_inserted_at_the_cursor_position(window, tmp_path: Path) -> None:  # noqa: ANN001
    """ТЗ §16: продолжение диктовки с места курсора, а не с конца документа."""
    open_document(window, tmp_path / "текст.txt", "Первый абзац.\n\nТретий абзац.")

    cursor = window._editor.textCursor()
    cursor.setPosition(len("Первый абзац.\n"))
    window._editor.setTextCursor(cursor)

    window._inserter.begin()
    window._on_commit("второй абзац")
    window._on_recording_finished()

    assert window._editor.toPlainText() == "Первый абзац.\nвторой абзац\nТретий абзац."


def test_editing_marks_the_document_as_modified(window, tmp_path: Path) -> None:  # noqa: ANN001
    open_document(window, tmp_path / "правка.txt")
    window._editor.setPlainText("новый текст")

    assert window._document.is_modified
    assert window.windowTitle().startswith("правка.txt *")


def test_autosave_clears_the_modified_mark(window, tmp_path: Path) -> None:  # noqa: ANN001
    target = tmp_path / "автосохранение.txt"
    open_document(window, target)
    window._editor.setPlainText("текст для автосохранения")

    assert window._autosave.save_now()
    assert not window._document.is_modified
    assert target.read_text(encoding="utf-8") == "текст для автосохранения"
    assert "Сохранено" in window._saved_label.text()


def test_document_buttons_are_blocked_while_recording(window, tmp_path: Path) -> None:  # noqa: ANN001
    """Менять документ во время записи нельзя: текст вставляется по курсору."""
    open_document(window, tmp_path / "запись.txt")

    window._apply_state(AppState.RECORDING)
    assert not window._new_button.isEnabled()
    assert not window._open_button.isEnabled()
    assert not window._device_combo.isEnabled()
    assert window._record_button.text().startswith("■")

    window._apply_state(AppState.READY)
    assert window._new_button.isEnabled()
    assert window._record_button.text().startswith("●")


def test_closing_saves_the_document(window, tmp_path: Path, qt_app) -> None:  # noqa: ANN001
    from PySide6.QtGui import QCloseEvent

    target = tmp_path / "закрытие.txt"
    open_document(window, target)
    window._editor.setPlainText("текст перед закрытием")

    event = QCloseEvent()
    window.closeEvent(event)

    assert event.isAccepted()
    assert target.read_text(encoding="utf-8") == "текст перед закрытием"


def test_copy_all_puts_the_whole_text_on_the_clipboard(window, tmp_path: Path, qt_app) -> None:  # noqa: ANN001
    open_document(window, tmp_path / "копия.txt", "весь текст документа")

    window._on_copy_all()

    assert qt_app.clipboard().text() == "весь текст документа"
