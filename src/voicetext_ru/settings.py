"""Настройки приложения, сохраняемые между запусками (ТЗ §38).

Хранятся в JSON рядом с журналом. Загрузка устойчива к повреждённому или
устаревшему файлу: неизвестные поля игнорируются, некорректные значения
заменяются значениями по умолчанию.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .asr.catalog import (
    DEFAULT_DRAFT_MODEL_ID,
    DEFAULT_MODEL_ID,
    DRAFT_DISABLED,
    draft_model_ids,
    model_ids,
)
from .paths import settings_file

logger = logging.getLogger(__name__)

DEFAULT_HOTKEY = "Ctrl+Shift+Space"
COMPUTE_DEVICES = ("auto", "cpu", "cuda")


@dataclass
class Settings:
    """Пользовательские предпочтения."""

    # --- Звук ---
    microphone_key: str | None = None
    """Идентификатор устройства вида "<host api>|<имя>"; None — системное по умолчанию.
    Храним имя, а не индекс: индексы устройств меняются при подключении гарнитур."""

    # --- Распознавание ---
    model_id: str = DEFAULT_MODEL_ID
    draft_model_id: str = DEFAULT_DRAFT_MODEL_ID
    """Быстрая модель для чернового текста; пустая строка — не использовать."""

    compute_device: str = "auto"
    language: str = "ru"
    preload_model: bool = False
    """Загружать модель сразу при запуске, а не при первом нажатии «Запись»."""

    show_partial_text: bool = True
    """Показывать неподтверждённый (уточняемый) текст серым цветом."""

    commit_silence_ms: int = 700
    """Длительность паузы, после которой фрагмент считается завершённым."""

    max_utterance_seconds: int = 20
    """Предел непрерывной речи без пауз, после которого фрагмент фиксируется принудительно."""

    # --- Горячая клавиша ---
    hotkey_enabled: bool = True
    hotkey: str = DEFAULT_HOTKEY

    # --- Документ ---
    autosave_interval_ms: int = 1000
    last_directory: str = ""

    # --- Окно ---
    window_geometry: str = ""
    """Геометрия главного окна в шестнадцатеричном виде (QByteArray)."""

    # ------------------------------------------------------------------ #

    def normalized(self) -> Settings:
        """Возвращает копию с приведёнными в допустимый диапазон значениями."""
        data = asdict(self)

        if data["model_id"] not in model_ids():
            logger.warning("Неизвестная модель %r, используется %r", data["model_id"], DEFAULT_MODEL_ID)
            data["model_id"] = DEFAULT_MODEL_ID
        if data["draft_model_id"] not in (*draft_model_ids(), DRAFT_DISABLED):
            data["draft_model_id"] = DEFAULT_DRAFT_MODEL_ID
        if data["compute_device"] not in COMPUTE_DEVICES:
            data["compute_device"] = "auto"
        if not data["language"]:
            data["language"] = "ru"
        if not isinstance(data["microphone_key"], (str, type(None))) or data["microphone_key"] == "":
            data["microphone_key"] = None

        data["commit_silence_ms"] = _clamp(data["commit_silence_ms"], 300, 3000, 700)
        data["max_utterance_seconds"] = _clamp(data["max_utterance_seconds"], 5, 60, 20)
        data["autosave_interval_ms"] = _clamp(data["autosave_interval_ms"], 500, 30_000, 1000)

        if not isinstance(data["hotkey"], str) or not data["hotkey"].strip():
            data["hotkey"] = DEFAULT_HOTKEY

        for flag in ("preload_model", "show_partial_text", "hotkey_enabled"):
            data[flag] = bool(data[flag])

        return Settings(**data)

    def save(self, path: Path | None = None) -> None:
        """Атомарно записывает настройки на диск."""
        target = path or settings_file()
        payload = json.dumps(asdict(self), ensure_ascii=False, indent=2)
        try:
            _atomic_write_text(target, payload)
        except OSError:
            logger.exception("Не удалось сохранить настройки в %s", target)

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        """Читает настройки; при любой ошибке возвращает значения по умолчанию."""
        source = path or settings_file()
        if not source.is_file():
            return cls()
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.exception("Файл настроек повреждён, используются значения по умолчанию")
            return cls()

        if not isinstance(raw, dict):
            return cls()

        known = {f.name for f in fields(cls)}
        filtered = {key: value for key, value in raw.items() if key in known}
        try:
            return cls(**filtered).normalized()
        except TypeError:
            logger.exception("Неподходящие типы в файле настроек")
            return cls()


def _clamp(value: object, low: int, high: int, fallback: int) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, number))


def _atomic_write_text(path: Path, text: str) -> None:
    """Запись через временный файл: при сбое прежняя версия остаётся целой."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
