"""Проверка файлов сборки.

Windows PowerShell 5.1 и Inno Setup читают файлы без BOM в системной кодировке
ANSI. Кириллица в таком файле превращается в мусор: скрипт сборки перестаёт
разбираться, а установщик показывает нечитаемые строки. Ошибка проявляется
только при сборке, поэтому наличие BOM проверяется тестом.
"""

from __future__ import annotations

from pathlib import Path

import pytest

BUILD_DIR = Path(__file__).resolve().parent.parent / "build"
UTF8_BOM = b"\xef\xbb\xbf"

FILES_REQUIRING_BOM = ("build.ps1", "installer.iss")


@pytest.mark.parametrize("name", FILES_REQUIRING_BOM)
def test_build_file_starts_with_utf8_bom(name: str) -> None:
    path = BUILD_DIR / name
    assert path.is_file(), f"Файл сборки отсутствует: {path}"

    head = path.read_bytes()[:3]
    assert head == UTF8_BOM, (
        f"{name} должен быть сохранён в UTF-8 с BOM, иначе кириллица в нём "
        "будет прочитана как ANSI и сборка сломается."
    )


@pytest.mark.parametrize("name", FILES_REQUIRING_BOM)
def test_build_file_is_valid_utf8(name: str) -> None:
    (BUILD_DIR / name).read_text(encoding="utf-8-sig")


def test_pyinstaller_spec_uses_the_absolute_import_entry_point() -> None:
    """PyInstaller запускает стартовый файл как скрипт, без пакета-родителя.

    Относительный импорт из `voicetext_ru/__main__.py` в такой сборке падает
    ещё до настройки журнала, поэтому у сборки отдельная точка входа.
    """
    spec = (BUILD_DIR / "voicetext_ru.spec").read_text(encoding="utf-8")
    assert "entrypoint.py" in spec
    assert 'name="VoiceTextRU"' in spec

    entrypoint = (BUILD_DIR / "entrypoint.py").read_text(encoding="utf-8")
    assert "from voicetext_ru.app import main" in entrypoint
    assert "from ." not in entrypoint
