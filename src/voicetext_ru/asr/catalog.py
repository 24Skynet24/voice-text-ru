"""Каталог моделей распознавания речи (ТЗ §19).

Отделён от движка: описание моделей нужно интерфейсу настроек, а реализация
движка — только идентификатор. Замена движка не требует изменения интерфейса.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelDescriptor:
    """Описание модели в понятных обычному пользователю терминах."""

    model_id: str
    """Идентификатор для faster-whisper (псевдоним или repo id на Hugging Face)."""

    title: str
    summary: str
    """Одна строка: чем эта модель отличается от остальных."""

    approx_download_mb: int
    """Приблизительный размер загрузки, чтобы пользователь понимал стоимость выбора."""

    recommended: bool = False

    @property
    def display_name(self) -> str:
        suffix = " — рекомендуется" if self.recommended else ""
        return f"{self.title}{suffix}"

    def describe(self) -> str:
        return f"{self.summary}\nРазмер загрузки: примерно {self.approx_download_mb} МБ."


MODELS: tuple[ModelDescriptor, ...] = (
    ModelDescriptor(
        model_id="small",
        title="Small",
        summary=(
            "Быстрая модель с невысокой точностью. Подходит для слабых компьютеров "
            "и для диктовки короткими простыми фразами."
        ),
        approx_download_mb=490,
    ),
    ModelDescriptor(
        model_id="medium",
        title="Medium",
        summary=(
            "Заметно точнее Small при умеренной нагрузке на процессор. "
            "Разумный выбор, если Large-v3-turbo работает медленно."
        ),
        approx_download_mb=1530,
    ),
    ModelDescriptor(
        model_id="large-v3-turbo",
        title="Large-v3-turbo",
        summary=(
            "Точность почти как у Large-v3, но в несколько раз быстрее: "
            "используется полный кодировщик Large-v3 и облегчённый декодер. "
            "Лучший баланс точности и задержки для русской речи."
        ),
        approx_download_mb=1620,
        recommended=True,
    ),
    ModelDescriptor(
        model_id="large-v3",
        title="Large-v3",
        summary=(
            "Максимальная точность. Требует мощного процессора или видеокарты NVIDIA: "
            "без ускорения распознавание может не успевать за речью."
        ),
        approx_download_mb=3090,
    ),
)

DEFAULT_MODEL_ID = "large-v3-turbo"


# --------------------------------------------------------------------------- #
# Быстрая модель для черновиков
# --------------------------------------------------------------------------- #
#
# Кодировщик Whisper всегда обрабатывает окно в 30 секунд, поэтому один проход
# стоит одинаково независимо от длины фразы: на Ryzen 5 7500F это около 3 секунд
# для Large-v3-turbo. Ждать столько ради чернового текста бессмысленно, поэтому
# черновики считает отдельная маленькая модель, а точная модель подтверждает
# фразу после паузы. Подробности — в docs/ARCHITECTURE.md §3.

DRAFT_MODELS: tuple[ModelDescriptor, ...] = (
    ModelDescriptor(
        model_id="tiny",
        title="Tiny",
        summary="Самый быстрый черновик. Много ошибок, но текст виден почти сразу.",
        approx_download_mb=75,
    ),
    ModelDescriptor(
        model_id="base",
        title="Base",
        summary="Черновик чуть точнее Tiny при близкой скорости.",
        approx_download_mb=145,
    ),
    ModelDescriptor(
        model_id="small",
        title="Small",
        summary="Разборчивый черновик. Заметно нагружает процессор сильнее Tiny.",
        approx_download_mb=490,
        recommended=True,
    ),
)

DEFAULT_DRAFT_MODEL_ID = "small"
DRAFT_DISABLED = ""
"""Значение настройки, при котором черновой текст появляется только от основной модели."""


def get_draft_model(model_id: str) -> ModelDescriptor | None:
    """Описание черновой модели; None — черновая модель отключена."""
    for descriptor in DRAFT_MODELS:
        if descriptor.model_id == model_id:
            return descriptor
    return None


def draft_model_ids() -> tuple[str, ...]:
    return tuple(descriptor.model_id for descriptor in DRAFT_MODELS)


def get_model(model_id: str) -> ModelDescriptor:
    """Возвращает описание модели; для неизвестного идентификатора — модель по умолчанию."""
    for descriptor in MODELS:
        if descriptor.model_id == model_id:
            return descriptor
    return get_model(DEFAULT_MODEL_ID) if model_id != DEFAULT_MODEL_ID else MODELS[2]


def model_ids() -> tuple[str, ...]:
    return tuple(descriptor.model_id for descriptor in MODELS)
