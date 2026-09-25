"""Проверка отбора устройств ввода (ТЗ §17)."""

from __future__ import annotations

import pytest

from voicetext_ru.audio.devices import AudioDevice, is_virtual_device


@pytest.mark.parametrize(
    "name",
    [
        "Переназначение звуковых устр. - Input",
        "Microsoft Sound Mapper - Input",
        "Первичный драйвер записи звука",
        "Primary Sound Capture Driver",
    ],
)
def test_system_mappers_are_hidden(name: str) -> None:
    """Виртуальные «переназначители» дублируют пункт «По умолчанию»."""
    assert is_virtual_device(name)


@pytest.mark.parametrize(
    "name",
    [
        "Микрофон (USB MIC PRO)",
        "Микрофон (Realtek(R) Audio)",
        "Headset Microphone (Bluetooth)",
    ],
)
def test_real_microphones_are_kept(name: str) -> None:
    assert not is_virtual_device(name)


def test_device_key_survives_index_changes() -> None:
    """Ключ устройства не должен зависеть от номера: номера меняются при подключении гарнитур."""
    first = AudioDevice(index=3, name="Микрофон (USB MIC PRO)", host_api="Windows WASAPI",
                        default_samplerate=48_000.0, max_input_channels=2)
    second = AudioDevice(index=27, name="Микрофон (USB MIC PRO)", host_api="Windows WASAPI",
                         default_samplerate=48_000.0, max_input_channels=2)

    assert first.key == second.key
    assert first.key == "Windows WASAPI|Микрофон (USB MIC PRO)"
