"""Поиск устройств ввода звука (ТЗ §17).

PortAudio показывает одно и то же физическое устройство через несколько host API.
Приоритет отдаётся WASAPI: он отдаёт полные имена устройств (MME обрезает их до
31 символа) и работает с текущим системным микшером.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import sounddevice as sd

logger = logging.getLogger(__name__)

_PREFERRED_HOST_APIS = ("Windows WASAPI", "Windows DirectSound", "MME")

# Windows показывает среди устройств ввода виртуальные «переназначители»,
# которые лишь перенаправляют звук на устройство по умолчанию. Показывать их
# пользователю бессмысленно: этот выбор уже есть отдельным пунктом списка.
# Имена локализованы, поэтому перечислены варианты для русской и английской систем.
_VIRTUAL_DEVICE_MARKERS = (
    "sound mapper",
    "переназначение звуковых",
    "primary sound capture",
    "первичный драйвер записи",
    "основной звуковой драйвер",
)


@dataclass(frozen=True)
class AudioDevice:
    """Устройство ввода звука."""

    index: int
    name: str
    host_api: str
    default_samplerate: float
    max_input_channels: int

    @property
    def key(self) -> str:
        """Устойчивый идентификатор для настроек.

        Индексы PortAudio меняются при подключении/отключении устройств,
        поэтому выбор пользователя сохраняется по имени и host API.
        """
        return f"{self.host_api}|{self.name}"

    @property
    def display_name(self) -> str:
        return self.name


def is_virtual_device(name: str) -> bool:
    """Является ли устройство системным «переназначателем», а не микрофоном."""
    lowered = name.strip().lower()
    return any(marker in lowered for marker in _VIRTUAL_DEVICE_MARKERS)


def _host_api_priority(name: str) -> int:
    try:
        return _PREFERRED_HOST_APIS.index(name)
    except ValueError:
        return len(_PREFERRED_HOST_APIS)


def list_input_devices() -> list[AudioDevice]:
    """Возвращает устройства ввода, по одному на физический микрофон.

    При ошибке обращения к звуковой подсистеме возвращает пустой список —
    вызывающий код обязан корректно обработать этот случай.
    """
    try:
        devices = sd.query_devices()
        host_apis = sd.query_hostapis()
    except Exception:
        logger.exception("Не удалось получить список звуковых устройств")
        return []

    candidates: list[AudioDevice] = []
    for index, info in enumerate(devices):
        if int(info.get("max_input_channels", 0)) <= 0:
            continue
        if is_virtual_device(str(info.get("name", ""))):
            continue
        host_index = int(info.get("hostapi", 0))
        host_name = str(host_apis[host_index]["name"]) if host_index < len(host_apis) else "?"
        if _host_api_priority(host_name) >= len(_PREFERRED_HOST_APIS):
            # WDM-KS даёт эксклюзивный доступ и часто конфликтует с другими
            # приложениями — такие устройства пользователю не показываем.
            continue
        candidates.append(
            AudioDevice(
                index=index,
                name=str(info.get("name", f"Устройство {index}")).strip(),
                host_api=host_name,
                default_samplerate=float(info.get("default_samplerate", 44100.0)),
                max_input_channels=int(info["max_input_channels"]),
            )
        )

    # Одно физическое устройство видно через несколько host API: оставляем
    # вариант с наиболее приоритетным API, сравнивая по нормализованному имени.
    best: dict[str, AudioDevice] = {}
    for device in candidates:
        fingerprint = _fingerprint(device.name)
        current = best.get(fingerprint)
        if current is None or _host_api_priority(device.host_api) < _host_api_priority(current.host_api):
            best[fingerprint] = device

    result = sorted(best.values(), key=lambda d: d.display_name.lower())
    logger.debug("Найдено устройств ввода: %d", len(result))
    return result


def _fingerprint(name: str) -> str:
    """Нормализует имя для сопоставления одного устройства между host API.

    MME обрезает имена до 31 символа, поэтому сравниваем по общему префиксу.
    """
    return name.strip().lower()[:31]


def default_input_device() -> AudioDevice | None:
    """Системное устройство ввода по умолчанию, приведённое к приоритетному host API."""
    try:
        default_index = sd.default.device[0]
    except Exception:
        return None
    if default_index is None or default_index < 0:
        return None

    try:
        info = sd.query_devices(default_index)
    except Exception:
        logger.exception("Не удалось получить устройство по умолчанию")
        return None

    target = _fingerprint(str(info.get("name", "")))
    for device in list_input_devices():
        if _fingerprint(device.name) == target:
            return device
    return None


def resolve_device(key: str | None) -> AudioDevice | None:
    """Находит устройство по сохранённому ключу.

    Возвращает None, если ключ не задан или устройство сейчас недоступно —
    вызывающий код решает, переключиться ли на устройство по умолчанию.
    """
    if not key:
        return None
    for device in list_input_devices():
        if device.key == key:
            return device
    logger.warning("Сохранённый микрофон недоступен: %s", key)
    return None
