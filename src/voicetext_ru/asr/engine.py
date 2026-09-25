"""Движок распознавания на основе faster-whisper (CTranslate2).

Выбор обоснован в docs/ARCHITECTURE.md §1. Весь код, специфичный для Whisper,
сосредоточен здесь и скрыт за протоколом `SpeechEngine`.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import replace

import numpy as np

from ..paths import models_dir
from .types import EngineInfo, ModelLoadError, SpeechEngine, TranscribedSegment

logger = logging.getLogger(__name__)

_MAX_CPU_THREADS = 16


def resolve_backend(preference: str = "auto") -> tuple[str, str]:
    """Подбирает вычислительное устройство и тип вычислений.

    CTranslate2 поддерживает только CPU и CUDA, поэтому на видеокартах AMD
    и Intel распознавание идёт на процессоре — см. docs/ARCHITECTURE.md §6.
    """
    if preference == "cpu":
        return "cpu", "int8"
    if preference == "cuda":
        return "cuda", "float16"

    if cuda_device_count() > 0:
        return "cuda", "float16"
    return "cpu", "int8"


def cuda_device_count() -> int:
    """Число доступных видеокарт NVIDIA; 0 при любой ошибке определения."""
    try:
        import ctranslate2

        return int(ctranslate2.get_cuda_device_count())
    except Exception:
        logger.debug("CUDA недоступна", exc_info=True)
        return 0


def default_cpu_threads() -> int:
    """Число потоков для инференса на процессоре.

    Измерения на Ryzen 5 7500F (6 ядер / 12 потоков) показали, что все
    логические потоки дают примерно на четверть меньшую задержку, чем только
    физические ядра (3.2 с против 4.2 с на один проход). Задержка — приоритет
    №2 технического задания, поэтому используются все логические процессоры.
    """
    logical = os.cpu_count() or 4
    return max(1, min(_MAX_CPU_THREADS, logical))


class FasterWhisperEngine:
    """Обёртка над `faster_whisper.WhisperModel`.

    Экземпляр потокобезопасен для последовательных вызовов: `transcribe`
    защищён блокировкой, поскольку один и тот же объект используется
    и для промежуточных, и для окончательных проходов.
    """

    def __init__(
        self,
        model_id: str,
        *,
        device_preference: str = "auto",
        language: str = "ru",
        local_files_only: bool = False,
    ) -> None:
        from faster_whisper import WhisperModel  # импорт здесь: ускоряет старт приложения

        device, compute_type = resolve_backend(device_preference)
        self._language = language
        self._lock = threading.Lock()
        self._closed = False

        logger.info(
            "Загрузка модели %s (устройство: %s, тип: %s, потоков ЦП: %d)",
            model_id,
            device,
            compute_type,
            default_cpu_threads(),
        )
        try:
            self._model = WhisperModel(
                model_id,
                device=device,
                compute_type=compute_type,
                cpu_threads=default_cpu_threads(),
                download_root=str(models_dir()),
                local_files_only=local_files_only,
            )
        except Exception as error:
            raise ModelLoadError(_describe_load_error(model_id, error)) from error

        self._info = EngineInfo(model_id=model_id, device=device, compute_type=compute_type)
        logger.info("Модель загружена: %s", self._info.summary)

    @property
    def info(self) -> EngineInfo:
        return self._info

    # ---------------------------------------------------------------- #

    def transcribe(
        self,
        audio: np.ndarray,
        *,
        prompt: str | None = None,
        fast: bool = False,
    ) -> list[TranscribedSegment]:
        """Распознаёт фрагмент моно-сигнала 16 кГц.

        В быстром режиме (`fast`) используется жадный поиск без перебора
        температур: результат промежуточный и всё равно будет уточнён.
        """
        samples = np.asarray(audio, dtype=np.float32).reshape(-1)
        if samples.size == 0:
            return []

        with self._lock:
            if self._closed:
                return []
            segments, _info = self._model.transcribe(
                samples,
                language=self._language,
                task="transcribe",
                beam_size=1 if fast else 5,
                temperature=0.0 if fast else [0.0, 0.2, 0.4],
                # Контекст передаётся явно через initial_prompt: так он ограничен
                # последними подтверждёнными словами и не может «раскрутиться»
                # в самоподдерживающийся цикл.
                condition_on_previous_text=False,
                initial_prompt=prompt or None,
                compression_ratio_threshold=2.4,
                log_prob_threshold=-1.0,
                no_speech_threshold=0.6,
                # Модель не должна дописывать за пользователя литературный текст (ТЗ §12).
                suppress_blank=True,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300},
            )
            return [
                TranscribedSegment(
                    text=segment.text,
                    start=float(segment.start),
                    end=float(segment.end),
                    no_speech_prob=float(getattr(segment, "no_speech_prob", 0.0)),
                    avg_logprob=float(getattr(segment, "avg_logprob", 0.0)),
                    compression_ratio=float(getattr(segment, "compression_ratio", 1.0)),
                )
                for segment in segments
            ]

    def close(self) -> None:
        """Освобождает модель (ТЗ §33, §36)."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            model, self._model = self._model, None
        del model
        logger.info("Движок распознавания остановлен")


class TieredEngine:
    """Две модели: быстрая для черновиков и точная для подтверждения.

    Кодировщик Whisper всегда обрабатывает окно в 30 секунд, поэтому стоимость
    прохода не зависит от длины фразы. Ждать полный проход большой модели ради
    чернового текста незачем: черновики считает маленькая модель за доли
    секунды, а подтверждённый текст — точная. Для вызывающего кода это по-прежнему
    один `SpeechEngine`.
    """

    def __init__(self, accurate: SpeechEngine, draft: SpeechEngine | None = None) -> None:
        self._accurate = accurate
        self._draft = draft
        self._info = replace(
            accurate.info,
            draft_model_id=draft.info.model_id if draft is not None else None,
        )

    @property
    def info(self) -> EngineInfo:
        return self._info

    def transcribe(
        self,
        audio: np.ndarray,
        *,
        prompt: str | None = None,
        fast: bool = False,
    ) -> list[TranscribedSegment]:
        engine = self._draft if (fast and self._draft is not None) else self._accurate
        return engine.transcribe(audio, prompt=prompt, fast=fast)

    def close(self) -> None:
        for engine in (self._draft, self._accurate):
            if engine is None:
                continue
            try:
                engine.close()
            except Exception:
                logger.exception("Ошибка при остановке движка распознавания")


def _describe_load_error(model_id: str, error: Exception) -> str:
    """Понятное пользователю объяснение, почему модель не загрузилась (ТЗ §31)."""
    text = str(error).lower()
    if any(marker in text for marker in ("connection", "network", "resolve", "timed out", "offline")):
        return (
            f"Не удалось загрузить модель «{model_id}»: нет соединения с интернетом.\n"
            "Модель скачивается один раз; после этого распознавание работает полностью офлайн."
        )
    if "no such file" in text or "not found" in text or "does not appear" in text:
        return (
            f"Файлы модели «{model_id}» не найдены. Откройте «Настройки» и загрузите модель заново."
        )
    if "memory" in text or "alloc" in text:
        return (
            f"Недостаточно памяти для модели «{model_id}». "
            "Выберите в настройках модель меньшего размера."
        )
    if "cuda" in text or "cublas" in text or "cudnn" in text:
        return (
            "Не удалось использовать видеокарту NVIDIA. "
            "Выберите в настройках вычисления на процессоре."
        )
    return f"Не удалось загрузить модель «{model_id}»: {error}"
