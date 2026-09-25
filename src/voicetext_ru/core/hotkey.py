"""Глобальная горячая клавиша Windows (ТЗ §7).

Используется `RegisterHotKey` — системный механизм, который работает независимо
от фокуса окна и не требует перехвата всей клавиатуры (в отличие от низкоуровневого
клавиатурного хука, который антивирусы справедливо считают подозрительным).

Сообщение `WM_HOTKEY` приходит в очередь окна и перехватывается фильтром
нативных событий Qt.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

logger = logging.getLogger(__name__)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
_HOTKEY_ID = 0xA17C

_MODIFIER_NAMES: dict[str, int] = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "meta": MOD_WIN,
}

_NAMED_KEYS: dict[str, int] = {
    "space": 0x20,
    "пробел": 0x20,
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "esc": 0x1B,
    "escape": 0x1B,
    "backspace": 0x08,
    "insert": 0x2D,
    "delete": 0x2E,
    "del": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "pause": 0x13,
    "scrolllock": 0x91,
    "`": 0xC0,
    "~": 0xC0,
    "-": 0xBD,
    "=": 0xBB,
    "[": 0xDB,
    "]": 0xDD,
    "\\": 0xDC,
    ";": 0xBA,
    "'": 0xDE,
    ",": 0xBC,
    ".": 0xBE,
    "/": 0xBF,
}


def parse_hotkey(sequence: str) -> tuple[int, int] | None:
    """Разбирает строку вида «Ctrl+Shift+Space» в (модификаторы, виртуальный код).

    Возвращает None, если сочетание не распознано или не содержит модификаторов
    (глобальная клавиша без модификаторов перехватывала бы обычный ввод).
    """
    if not sequence:
        return None

    parts = [part.strip().lower() for part in sequence.split("+") if part.strip()]
    if len(parts) < 2:
        return None

    modifiers = 0
    key_code: int | None = None
    for part in parts:
        if part in _MODIFIER_NAMES:
            modifiers |= _MODIFIER_NAMES[part]
            continue
        if key_code is not None:
            return None  # более одной основной клавиши
        key_code = _key_code(part)
        if key_code is None:
            return None

    if key_code is None or modifiers == 0:
        return None
    return modifiers | MOD_NOREPEAT, key_code


def _key_code(name: str) -> int | None:
    if name in _NAMED_KEYS:
        return _NAMED_KEYS[name]
    if len(name) == 1 and name.isalnum() and name.isascii():
        return ord(name.upper())
    if name.startswith("f") and name[1:].isdigit():
        number = int(name[1:])
        if 1 <= number <= 24:
            return 0x70 + number - 1
    return None


def format_hotkey(sequence: str) -> str:
    """Приводит сочетание к каноническому виду для отображения и хранения."""
    parsed = parse_hotkey(sequence)
    if parsed is None:
        return sequence
    modifiers, key_code = parsed
    parts: list[str] = []
    if modifiers & MOD_CONTROL:
        parts.append("Ctrl")
    if modifiers & MOD_ALT:
        parts.append("Alt")
    if modifiers & MOD_SHIFT:
        parts.append("Shift")
    if modifiers & MOD_WIN:
        parts.append("Win")
    parts.append(_key_name(key_code))
    return "+".join(parts)


def _key_name(key_code: int) -> str:
    for name, code in _NAMED_KEYS.items():
        if code == key_code and name.isascii() and name.isalpha():
            return name.capitalize()
    if 0x70 <= key_code <= 0x87:
        return f"F{key_code - 0x70 + 1}"
    if 0x30 <= key_code <= 0x5A:
        return chr(key_code)
    return f"0x{key_code:02X}"


class GlobalHotkeyManager(QObject, QAbstractNativeEventFilter):
    """Регистрирует системное сочетание и превращает `WM_HOTKEY` в сигнал Qt."""

    activated = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        QObject.__init__(self, parent)
        QAbstractNativeEventFilter.__init__(self)
        self._registered_hwnd: int | None = None
        self._sequence = ""
        self._supported = sys.platform == "win32"

    @property
    def is_supported(self) -> bool:
        return self._supported

    @property
    def is_registered(self) -> bool:
        return self._registered_hwnd is not None

    @property
    def sequence(self) -> str:
        return self._sequence

    # ---------------------------------------------------------------- #

    def register(self, hwnd: int, sequence: str) -> str | None:
        """Регистрирует сочетание для окна `hwnd`.

        :returns: None при успехе либо текст ошибки для пользователя.
        """
        if not self._supported:
            return "Глобальные сочетания клавиш поддерживаются только в Windows."

        self.unregister()

        parsed = parse_hotkey(sequence)
        if parsed is None:
            return (
                f"Сочетание «{sequence}» не распознано. "
                "Укажите хотя бы один модификатор, например Ctrl+Shift+Space."
            )

        modifiers, key_code = parsed
        try:
            ok = ctypes.windll.user32.RegisterHotKey(
                wintypes.HWND(hwnd), _HOTKEY_ID, wintypes.UINT(modifiers), wintypes.UINT(key_code)
            )
        except Exception as error:
            logger.exception("Ошибка регистрации горячей клавиши")
            return f"Не удалось зарегистрировать сочетание: {error}"

        if not ok:
            logger.warning("RegisterHotKey не выполнен для %s", sequence)
            return (
                f"Сочетание «{sequence}» уже занято другой программой. "
                "Выберите другое сочетание в настройках."
            )

        self._registered_hwnd = hwnd
        self._sequence = format_hotkey(sequence)
        logger.info("Глобальное сочетание зарегистрировано: %s", self._sequence)
        return None

    def unregister(self) -> None:
        """Снимает регистрацию (обязательно перед выходом — ТЗ §36)."""
        if self._registered_hwnd is None:
            return
        try:
            ctypes.windll.user32.UnregisterHotKey(wintypes.HWND(self._registered_hwnd), _HOTKEY_ID)
            logger.info("Глобальное сочетание снято: %s", self._sequence)
        except Exception:
            logger.exception("Ошибка снятия горячей клавиши")
        finally:
            self._registered_hwnd = None

    # ---------------------------------------------------------------- #

    def nativeEventFilter(self, event_type: object, message: object) -> tuple[bool, int]:
        """Перехватывает WM_HOTKEY до обработки сообщения Qt."""
        if self._registered_hwnd is None:
            return False, 0
        try:
            if bytes(event_type) != b"windows_generic_MSG":
                return False, 0
            msg = wintypes.MSG.from_address(int(message))  # type: ignore[arg-type]
            if msg.message == WM_HOTKEY and msg.wParam == _HOTKEY_ID:
                self.activated.emit()
                return True, 0
        except Exception:
            logger.exception("Ошибка обработки нативного события")
        return False, 0
