"""Работа с текстовым документом (ТЗ §4, §24, §25).

Файлы читаются и пишутся в UTF-8. Если открыт файл в другой кодировке или
с другими переводами строк, эти свойства сохраняются при записи — пользователь
не должен обнаружить, что приложение испортило его файл.
"""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_BOM = "﻿"
_READ_ENCODINGS = ("utf-8-sig", "utf-8", "cp1251")
_MAX_OPEN_BYTES = 64 * 1024 * 1024


class DocumentError(RuntimeError):
    """Ошибка чтения или записи документа с текстом для пользователя."""


@dataclass
class DocumentFormat:
    """Как файл был прочитан — чтобы записать его так же."""

    encoding: str = "utf-8"
    newline: str = os.linesep
    has_bom: bool = False


class DocumentManager:
    """Текущий документ: путь, формат, признак несохранённых изменений."""

    def __init__(self) -> None:
        self._path: Path | None = None
        self._format = DocumentFormat()
        self._modified = False

    # ---------------------------------------------------------------- #
    # Состояние
    # ---------------------------------------------------------------- #

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def is_open(self) -> bool:
        return self._path is not None

    @property
    def is_modified(self) -> bool:
        return self._modified

    @property
    def display_name(self) -> str:
        """Имя файла со звёздочкой при несохранённых изменениях (ТЗ §25)."""
        if self._path is None:
            return "Документ не открыт"
        return f"{self._path.name}{' *' if self._modified else ''}"

    def set_modified(self, modified: bool) -> None:
        self._modified = modified

    def close(self) -> None:
        self._path = None
        self._format = DocumentFormat()
        self._modified = False

    # ---------------------------------------------------------------- #
    # Операции
    # ---------------------------------------------------------------- #

    def create(self, path: Path) -> None:
        """Создаёт пустой документ. Файл появляется сразу, до начала записи (ТЗ §4.1)."""
        path = Path(path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        except OSError as error:
            raise DocumentError(_describe_io_error("создать", path, error)) from error

        self._path = path
        self._format = DocumentFormat(encoding="utf-8", newline=os.linesep, has_bom=False)
        self._modified = False
        logger.info("Создан документ: %s", path)

    def open(self, path: Path) -> str:
        """Читает документ и возвращает его текст с переводами строк «\\n»."""
        path = Path(path)
        try:
            size = path.stat().st_size
        except OSError as error:
            raise DocumentError(_describe_io_error("открыть", path, error)) from error

        if size > _MAX_OPEN_BYTES:
            raise DocumentError(
                f"Файл «{path.name}» слишком велик для редактора "
                f"({size / 1024 / 1024:.0f} МБ, предел {_MAX_OPEN_BYTES // 1024 // 1024} МБ)."
            )

        try:
            raw = path.read_bytes()
        except OSError as error:
            raise DocumentError(_describe_io_error("открыть", path, error)) from error

        text, encoding = _decode(raw, path)
        newline = _detect_newline(text)

        self._path = path
        self._format = DocumentFormat(
            encoding=encoding,
            newline=newline,
            has_bom=raw.startswith(b"\xef\xbb\xbf"),
        )
        self._modified = False
        logger.info("Открыт документ: %s (кодировка: %s)", path, encoding)
        return text.replace("\r\n", "\n").replace("\r", "\n")

    def save(self, text: str) -> None:
        """Записывает текст в текущий файл."""
        if self._path is None:
            raise DocumentError("Документ не выбран: сохранять некуда.")
        self._write(self._path, text)
        self._modified = False

    def save_as(self, path: Path, text: str) -> None:
        """Записывает текст в новый файл и делает его текущим."""
        path = Path(path)
        # Новый файл всегда получает UTF-8: это формат, заданный требованиями.
        self._format = DocumentFormat(encoding="utf-8", newline=self._format.newline, has_bom=False)
        self._write(path, text)
        self._path = path
        self._modified = False
        logger.info("Документ сохранён как: %s", path)

    # ---------------------------------------------------------------- #

    def _write(self, path: Path, text: str) -> None:
        """Атомарная запись: при сбое питания прежний файл остаётся целым."""
        payload = text.replace("\r\n", "\n").replace("\n", self._format.newline)
        if self._format.has_bom and not payload.startswith(_BOM):
            payload = _BOM + payload

        encoding = "utf-8" if self._format.encoding == "utf-8-sig" else self._format.encoding
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle, temp_name = tempfile.mkstemp(
                dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
            )
            try:
                with os.fdopen(handle, "w", encoding=encoding, newline="", errors="strict") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp_name, path)
            except BaseException:
                Path(temp_name).unlink(missing_ok=True)
                raise
        except UnicodeEncodeError:
            # Русский текст не помещается в исходную однобайтовую кодировку —
            # переходим на UTF-8, это лучше, чем потерять символы (ТЗ §24).
            logger.warning("Текст не кодируется в %s, файл будет сохранён в UTF-8", encoding)
            self._format.encoding = "utf-8"
            self._write(path, text)
            return
        except OSError as error:
            raise DocumentError(_describe_io_error("сохранить", path, error)) from error


def _decode(raw: bytes, path: Path) -> tuple[str, str]:
    for encoding in _READ_ENCODINGS:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    logger.warning("Кодировка файла %s не определена, часть символов может быть искажена", path)
    return raw.decode("utf-8", errors="replace"), "utf-8"


def _detect_newline(text: str) -> str:
    """Определяет преобладающий перевод строки в исходном файле."""
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    if crlf == 0 and lf == 0:
        return os.linesep
    return "\r\n" if crlf >= lf else "\n"


def _describe_io_error(action: str, path: Path, error: OSError) -> str:
    """Понятное пользователю сообщение об ошибке файловой операции (ТЗ §31)."""
    if isinstance(error, FileNotFoundError):
        return f"Не удалось {action} файл: «{path}» не найден."
    if isinstance(error, PermissionError):
        return (
            f"Не удалось {action} файл «{path.name}»: нет прав доступа. "
            "Возможно, файл открыт в другой программе или защищён от записи."
        )
    return f"Не удалось {action} файл «{path.name}»: {error.strerror or error}"
