"""Типы, не зависящие от конкретного движка распознавания.

Всё, что выше уровня `asr`, работает только с этими типами, поэтому движок
заменяем без изменения интерфейса и ядра приложения (ТЗ §35).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class TranscribedSegment:
    """Фрагмент распознанного текста с показателями достоверности."""

    text: str
    start: float
    end: float
    no_speech_prob: float = 0.0
    avg_logprob: float = 0.0
    compression_ratio: float = 1.0


@dataclass(frozen=True)
class EngineInfo:
    """Сведения о загруженном движке для строки состояния."""

    model_id: str
    device: str
    compute_type: str
    draft_model_id: str | None = None
    """Быстрая модель для черновиков, если она используется."""

    @property
    def summary(self) -> str:
        device_label = "GPU (CUDA)" if self.device == "cuda" else "ЦП"
        text = f"{self.model_id} · {device_label} · {self.compute_type}"
        if self.draft_model_id:
            text += f" · черновик: {self.draft_model_id}"
        return text


class SpeechEngine(Protocol):
    """Контракт движка распознавания речи."""

    @property
    def info(self) -> EngineInfo: ...

    def transcribe(
        self,
        audio: np.ndarray,
        *,
        prompt: str | None = None,
        fast: bool = False,
    ) -> list[TranscribedSegment]:
        """Распознаёт моно-сигнал 16 кГц float32.

        :param prompt: ранее подтверждённый текст — контекст для согласования окончаний.
        :param fast: экономичный режим для промежуточного результата.
        """
        ...

    def close(self) -> None:
        """Освобождает ресурсы модели."""
        ...


class ModelLoadError(RuntimeError):
    """Модель не удалось загрузить (нет файлов, нет сети, мало памяти)."""
