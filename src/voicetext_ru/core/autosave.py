"""Автосохранение документа (ТЗ §14).

Стратегия: любое изменение текста помечает документ «грязным», а таймер
записывает его на диск не чаще заданного интервала. Это одновременно
гарантирует, что при аварийном завершении теряются максимум последние
секунды текста, и не превращает диктовку в поток мелких записей на диск.

Сама запись атомарна (`DocumentManager._write`), поэтому прерывание
сохранения не портит файл.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from .document import DocumentError, DocumentManager

logger = logging.getLogger(__name__)


class AutoSaveManager(QObject):
    """Периодически сохраняет документ, если он изменился."""

    saved = Signal()
    failed = Signal(str)

    def __init__(
        self,
        document: DocumentManager,
        text_provider: Callable[[], str],
        interval_ms: int = 1000,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._document = document
        self._text_provider = text_provider
        self._dirty = False
        self._failure_reported = False

        self._timer = QTimer(self)
        self._timer.setInterval(max(250, interval_ms))
        self._timer.timeout.connect(self._on_tick)

    # ---------------------------------------------------------------- #

    def set_interval(self, interval_ms: int) -> None:
        self._timer.setInterval(max(250, interval_ms))

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def mark_dirty(self) -> None:
        """Отмечает, что текст изменился и требует записи."""
        self._dirty = True

    @property
    def has_pending_changes(self) -> bool:
        return self._dirty

    # ---------------------------------------------------------------- #

    def save_now(self, *, force: bool = False) -> bool:
        """Сохраняет немедленно.

        Вызывается при остановке записи и при закрытии приложения (ТЗ §14, §33).

        :param force: записать, даже если изменений не отмечено.
        :returns: True, если файл записан или записывать было нечего.
        """
        if not self._document.is_open:
            return False
        if not (self._dirty or force):
            return True

        try:
            self._document.save(self._text_provider())
        except DocumentError as error:
            logger.error("Автосохранение не удалось: %s", error)
            # Сообщаем один раз на серию ошибок, иначе при недоступном диске
            # пользователь получит поток одинаковых предупреждений.
            if not self._failure_reported:
                self._failure_reported = True
                self.failed.emit(str(error))
            return False

        self._dirty = False
        self._failure_reported = False
        self.saved.emit()
        return True

    def _on_tick(self) -> None:
        if self._dirty:
            self.save_now()
