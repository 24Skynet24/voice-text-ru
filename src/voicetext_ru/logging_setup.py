"""Настройка журналирования (ТЗ §37).

Журнал пишется в файл с ротацией, поэтому не может расти бесконечно.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys

from . import APP_NAME, APP_VERSION
from .paths import log_file

_MAX_BYTES = 1024 * 1024  # 1 МБ на файл
_BACKUP_COUNT = 3  # итого не более ~4 МБ журналов
_FORMAT = "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"

_configured = False


def setup_logging(verbose: bool = False) -> None:
    """Инициализирует корневой журнал. Повторные вызовы игнорируются."""
    global _configured
    if _configured:
        return

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    formatter = logging.Formatter(_FORMAT)

    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file(), maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:  # нет доступа к каталогу — работаем без файла журнала
        pass

    # В собранном GUI-приложении stderr может отсутствовать.
    if sys.stderr is not None:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    # Сторонние библиотеки не должны забивать журнал.
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)
    logging.getLogger("huggingface_hub").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    _configured = True
    logging.getLogger(__name__).info("Приложение запущено: %s %s", APP_NAME, APP_VERSION)


def install_excepthook() -> None:
    """Записывает необработанные исключения в журнал вместо тихого падения."""

    def _hook(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logging.getLogger("voicetext_ru").critical(
            "Необработанное исключение", exc_info=(exc_type, exc_value, exc_tb)
        )

    sys.excepthook = _hook
