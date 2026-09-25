"""Проверка разбора сочетаний клавиш (ТЗ §7)."""

from __future__ import annotations

import pytest

from voicetext_ru.core.hotkey import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_SHIFT,
    MOD_WIN,
    format_hotkey,
    parse_hotkey,
)


def test_default_combination_is_parsed() -> None:
    parsed = parse_hotkey("Ctrl+Shift+Space")
    assert parsed is not None
    modifiers, key = parsed
    assert modifiers & MOD_CONTROL
    assert modifiers & MOD_SHIFT
    assert key == 0x20


@pytest.mark.parametrize(
    ("sequence", "expected_modifier"),
    [("Alt+R", MOD_ALT), ("Win+R", MOD_WIN), ("Ctrl+F9", MOD_CONTROL)],
)
def test_modifiers_are_recognised(sequence: str, expected_modifier: int) -> None:
    parsed = parse_hotkey(sequence)
    assert parsed is not None
    assert parsed[0] & expected_modifier


def test_function_keys_are_supported() -> None:
    parsed = parse_hotkey("Ctrl+F12")
    assert parsed is not None
    assert parsed[1] == 0x7B


@pytest.mark.parametrize("sequence", ["", "Space", "F5", "Ctrl", "Ctrl+A+B", "Ctrl+Неизвестно"])
def test_invalid_combinations_are_rejected(sequence: str) -> None:
    """Без модификатора сочетание перехватывало бы обычный ввод текста."""
    assert parse_hotkey(sequence) is None


def test_format_normalises_order_and_case() -> None:
    assert format_hotkey("shift+ctrl+space") == "Ctrl+Shift+Space"
    assert format_hotkey("ALT+r") == "Alt+R"
