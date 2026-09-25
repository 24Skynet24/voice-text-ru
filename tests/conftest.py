"""Общие настройки тестов."""

from __future__ import annotations

import os

import pytest

# Тесты интерфейса выполняются без реального дисплея.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qt_app():
    """Единственный экземпляр QApplication на весь прогон тестов."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
