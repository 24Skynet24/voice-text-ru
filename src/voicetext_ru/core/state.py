"""Явные состояния приложения (ТЗ §31)."""

from __future__ import annotations

from enum import Enum


class AppState(Enum):
    """Состояние сеанса. Определяет доступность кнопки записи и текст в строке статуса."""

    NO_DOCUMENT = "no_document"
    READY = "ready"
    LOADING_MODEL = "loading_model"
    RECORDING = "recording"
    PROCESSING = "processing"
    ERROR = "error"

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def can_start_recording(self) -> bool:
        return self in (AppState.READY, AppState.ERROR)

    @property
    def is_busy(self) -> bool:
        """Идёт работа с микрофоном или моделью — закрытие требует аккуратного завершения."""
        return self in (AppState.RECORDING, AppState.PROCESSING, AppState.LOADING_MODEL)


_LABELS: dict[AppState, str] = {
    AppState.NO_DOCUMENT: "Документ не открыт",
    AppState.READY: "Готово",
    AppState.LOADING_MODEL: "Загрузка модели…",
    AppState.RECORDING: "● Идёт запись",
    AppState.PROCESSING: "Обработка…",
    AppState.ERROR: "Ошибка",
}
