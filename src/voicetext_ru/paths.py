"""Расположение пользовательских данных приложения.

Никаких абсолютных путей в коде: всё вычисляется от системных переменных окружения,
поэтому приложение одинаково работает и из исходников, и из сборки PyInstaller.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_ID


def _local_app_data() -> Path:
    """Каталог данных пользователя (Windows: %LOCALAPPDATA%)."""
    raw = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if raw:
        return Path(raw)
    return Path.home() / ".local" / "share"


def app_data_dir() -> Path:
    """Корневой каталог данных приложения; создаётся при необходимости."""
    path = _local_app_data() / APP_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_file() -> Path:
    return app_data_dir() / "settings.json"


def log_file() -> Path:
    logs = app_data_dir() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return logs / "voicetext.log"


def models_dir() -> Path:
    """Каталог, в который загружаются модели распознавания речи."""
    path = app_data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def documents_dir() -> Path:
    """Каталог по умолчанию для диалогов создания/открытия документов."""
    profile = os.environ.get("USERPROFILE")
    if profile:
        candidate = Path(profile) / "Documents"
        if candidate.is_dir():
            return candidate
    return Path.home()


def is_frozen() -> bool:
    """Запущено ли приложение из сборки PyInstaller."""
    return bool(getattr(sys, "frozen", False))


def resource_path(relative: str) -> Path:
    """Путь к ресурсу, приложенному к сборке (иконки и т. п.)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative
