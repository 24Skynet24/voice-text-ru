"""Проверка чтения и записи документов (ТЗ §24, §25)."""

from __future__ import annotations

from pathlib import Path

import pytest

from voicetext_ru.core.document import DocumentError, DocumentManager


def test_create_makes_empty_utf8_file(tmp_path: Path) -> None:
    target = tmp_path / "документ.txt"
    manager = DocumentManager()
    manager.create(target)

    assert target.is_file()
    assert target.read_bytes() == b""
    assert manager.is_open
    assert not manager.is_modified


def test_russian_text_round_trip_preserves_characters(tmp_path: Path) -> None:
    target = tmp_path / "речь.txt"
    manager = DocumentManager()
    manager.create(target)

    text = "Сегодня я тестирую новое приложение\nВторая строка — с тире и «кавычками»"
    manager.save(text)

    assert target.read_text(encoding="utf-8").replace("\r\n", "\n") == text
    assert DocumentManager().open(target) == text


def test_open_detects_cp1251_and_saves_without_corruption(tmp_path: Path) -> None:
    """Файл в кодировке Windows-1251 должен открыться без «кракозябр»."""
    target = tmp_path / "старый.txt"
    original = "Текст в старой кодировке"
    target.write_bytes(original.encode("cp1251"))

    manager = DocumentManager()
    assert manager.open(target) == original

    manager.save(original + " и дополнение")
    assert target.read_bytes().decode("cp1251") == original + " и дополнение"


def test_utf8_bom_is_preserved(tmp_path: Path) -> None:
    target = tmp_path / "сbom.txt"
    target.write_bytes(b"\xef\xbb\xbf" + "Текст".encode())

    manager = DocumentManager()
    assert manager.open(target) == "Текст"

    manager.save("Новый текст")
    assert target.read_bytes().startswith(b"\xef\xbb\xbf")


def test_line_endings_of_opened_file_are_preserved(tmp_path: Path) -> None:
    target = tmp_path / "unix.txt"
    target.write_bytes(b"first\nsecond\nthird\n")

    manager = DocumentManager()
    text = manager.open(target)
    assert "\r" not in text

    manager.save(text)
    assert b"\r\n" not in target.read_bytes()


def test_save_is_atomic_and_leaves_no_temporary_files(tmp_path: Path) -> None:
    target = tmp_path / "документ.txt"
    manager = DocumentManager()
    manager.create(target)
    manager.save("Текст" * 1000)

    assert [p.name for p in tmp_path.iterdir()] == ["документ.txt"]


def test_display_name_marks_unsaved_changes(tmp_path: Path) -> None:
    manager = DocumentManager()
    assert manager.display_name == "Документ не открыт"

    manager.create(tmp_path / "заметки.txt")
    assert manager.display_name == "заметки.txt"

    manager.set_modified(True)
    assert manager.display_name == "заметки.txt *"


def test_saving_without_document_reports_error() -> None:
    with pytest.raises(DocumentError):
        DocumentManager().save("текст")


def test_opening_missing_file_reports_readable_error(tmp_path: Path) -> None:
    with pytest.raises(DocumentError) as info:
        DocumentManager().open(tmp_path / "нет.txt")
    assert "не найден" in str(info.value)


def test_save_as_switches_to_utf8_for_new_file(tmp_path: Path) -> None:
    source = tmp_path / "исходный.txt"
    source.write_bytes("Текст".encode("cp1251"))
    manager = DocumentManager()
    manager.open(source)

    destination = tmp_path / "новый.txt"
    manager.save_as(destination, "Текст с ёмкими словами")

    assert destination.read_text(encoding="utf-8") == "Текст с ёмкими словами"
    assert manager.path == destination
