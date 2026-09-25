"""Потоковая обработка речи (ТЗ §10, §15, §23).

Whisper — оффлайновая модель, потокового режима у неё нет. Потоковость строится
вокруг неё так:

* звук накапливается в буфере **текущего высказывания**, с его начала;
* раз в ~1 с буфер распознаётся целиком в быстром режиме → промежуточный текст;
* когда в конце буфера набирается пауза, буфер распознаётся точным проходом,
  текст **подтверждается**, а буфер обрезается.

Промежуточный текст не дописывается, а заменяет предыдущий промежуточный
(см. `ui.transcript_inserter`), поэтому дублирование строк вида
«я хочу / я хочу сделать / я хочу сделать приложение» невозможно в принципе.

Распознаётся всегда целое высказывание, а не отдельный кусок: модели нужен
контекст, иначе точность на русском падает заметно.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from . import postprocess
from .types import SpeechEngine
from .vad import VadConfig, VoiceActivityTracker

logger = logging.getLogger(__name__)


class AudioSource(Protocol):
    """Источник блоков моно-звука 16 кГц."""

    def read(self, timeout: float = 0.1) -> np.ndarray | None: ...

    def drain(self, limit: int = 256) -> list[np.ndarray]: ...


@dataclass(frozen=True)
class StreamConfig:
    """Параметры потоковой обработки."""

    sample_rate: int = 16_000
    commit_silence_ms: int = 700
    """Пауза, после которой высказывание считается законченным."""

    max_utterance_seconds: float = 20.0
    """Предел непрерывной речи: дальше фрагмент фиксируется принудительно,
    чтобы и объём буфера, и стоимость одного прохода оставались ограниченными."""

    partial_interval_ms: int = 900
    """Минимальный интервал между промежуточными проходами."""

    min_partial_seconds: float = 0.8
    """Слишком короткий фрагмент распознавать бессмысленно."""

    min_commit_seconds: float = 0.35
    """Не подтверждать фрагменты короче — это почти наверняка щелчок, а не слово."""

    keep_tail_seconds: float = 0.2
    """Сколько звука оставить после подтверждения, чтобы не срезать начало следующего слова."""

    hard_backlog_seconds: float = 45.0
    """Аварийный предел отставания: старый звук отбрасывается, память не растёт."""

    draft_time_budget: float = 0.3
    """Доля реального времени, которую разрешено тратить на черновые проходы.

    Один проход распознавания стоит одинаково независимо от длины фразы, поэтому
    черновики способны съесть всё процессорное время и не дать подтверждать фразы.
    Ограничение гарантирует, что подтверждение всегда получает большую часть
    ресурсов, а отставание не накапливается в длинном сеансе (ТЗ §22).
    """

    context_chars: int = 180
    """Сколько подтверждённого текста передавать модели как контекст."""

    silence_trim_seconds: float = 2.0
    """Буфер без речи длиннее этого значения подрезается, чтобы не копить тишину."""

    emit_partial: bool = True

    @property
    def commit_silence_seconds(self) -> float:
        return self.commit_silence_ms / 1000.0

    @property
    def partial_interval_seconds(self) -> float:
        return self.partial_interval_ms / 1000.0


@dataclass
class WorkerCallbacks:
    """Точки выхода потока распознавания.

    Вызываются из рабочего потока; получатель обязан быть потокобезопасным
    (в приложении это объект Qt, сигналы которого ставятся в очередь main-потока).
    """

    on_partial: Callable[[str], None]
    on_commit: Callable[[str], None]
    on_error: Callable[[str], None]
    on_finished: Callable[[], None] = lambda: None


class TranscriptionWorker(threading.Thread):
    """Читает звук, распознаёт его и сообщает промежуточные/подтверждённые результаты."""

    def __init__(
        self,
        engine: SpeechEngine,
        source: AudioSource,
        callbacks: WorkerCallbacks,
        config: StreamConfig | None = None,
    ) -> None:
        super().__init__(name="TranscriptionWorker", daemon=True)
        self._engine = engine
        self._source = source
        self._callbacks = callbacks
        self._config = config or StreamConfig()
        self._vad = VoiceActivityTracker(VadConfig(sample_rate=self._config.sample_rate))

        self._blocks: list[np.ndarray] = []
        self._buffer_samples = 0
        self._context = ""
        self._partial_text = ""
        self._last_partial_at = 0.0
        self._min_partial_interval = self._config.partial_interval_seconds
        self._stop_requested = threading.Event()
        self._backlog_warned = False
        self._started_at = time.monotonic()
        self._draft_seconds_used = 0.0

    # ---------------------------------------------------------------- #
    # Управление
    # ---------------------------------------------------------------- #

    def request_stop(self) -> None:
        """Просит поток обработать остаток звука и завершиться (ТЗ §33)."""
        self._stop_requested.set()

    def set_context(self, text: str) -> None:
        """Задаёт начальный контекст — текст, стоящий перед курсором в документе."""
        self._context = text[-self._config.context_chars :]

    # ---------------------------------------------------------------- #
    # Основной цикл
    # ---------------------------------------------------------------- #

    def run(self) -> None:
        logger.info("Поток распознавания запущен")
        try:
            while not self._stop_requested.is_set():
                self._ingest(blocking=True)
                self._step()
            self._ingest(blocking=False)
            self._finalize()
        except Exception as error:
            logger.exception("Сбой в потоке распознавания")
            self._safe_error(f"Ошибка распознавания речи: {error}")
        finally:
            logger.info("Поток распознавания завершён")
            try:
                self._callbacks.on_finished()
            except Exception:
                logger.exception("Ошибка в обработчике завершения")

    def _ingest(self, *, blocking: bool) -> None:
        """Переносит накопленный звук из источника в буфер высказывания."""
        if blocking:
            block = self._source.read(timeout=0.05)
            if block is not None:
                self._append(block)
        for block in self._source.drain():
            self._append(block)

    def _append(self, block: np.ndarray) -> None:
        self._blocks.append(block)
        self._buffer_samples += block.size
        self._vad.feed(block)
        self._enforce_backlog_limit()

    def _step(self) -> None:
        """Одно решение: промолчать, выдать промежуточный результат или подтвердить."""
        duration = self._buffer_seconds
        if duration <= 0.0:
            return

        if not self._vad.has_speech:
            # В буфере только тишина: накапливать её незачем.
            if duration > self._config.silence_trim_seconds:
                self._trim_to_tail(self._config.keep_tail_seconds)
            self._clear_partial()
            return

        if self._vad.trailing_silence_seconds >= self._config.commit_silence_seconds:
            self._commit(self._cut_after_trailing_silence())
            return

        if duration >= self._config.max_utterance_seconds:
            logger.debug("Принудительная фиксация: речь без пауз %.1f с", duration)
            # Режем в самом тихом месте конца фрагмента; если кадров для оценки
            # не хватило, фиксируем фрагмент целиком.
            cut = self._vad.quietest_cut_sample()
            self._commit(self._buffer_samples if cut is None else cut)
            return

        if not self._config.emit_partial or duration < self._config.min_partial_seconds:
            return
        if time.monotonic() - self._last_partial_at < self._min_partial_interval:
            return
        if not self._draft_budget_available():
            return
        self._emit_partial()

    def _draft_budget_available(self) -> bool:
        """Не израсходована ли доля времени, отведённая на черновые проходы."""
        elapsed = time.monotonic() - self._started_at
        if elapsed < 1.0:
            return True
        return self._draft_seconds_used / elapsed < self._config.draft_time_budget

    def _finalize(self) -> None:
        """Завершающая обработка остатка звука при остановке записи."""
        if self._vad.has_speech and self._buffer_seconds >= self._config.min_commit_seconds:
            self._commit(self._buffer_samples)
        else:
            self._clear_partial()
        self._reset_buffer(np.zeros(0, dtype=np.float32))

    # ---------------------------------------------------------------- #
    # Распознавание
    # ---------------------------------------------------------------- #

    def _emit_partial(self) -> None:
        started = time.monotonic()
        text = self._transcribe(self._buffer_audio(), fast=True)
        elapsed = time.monotonic() - started
        self._last_partial_at = time.monotonic()
        self._draft_seconds_used += elapsed

        # Саморегулирование: если проход занял больше интервала, следующий
        # откладывается. Промежуточные результаты не должны мешать подтверждению.
        self._min_partial_interval = max(self._config.partial_interval_seconds, elapsed * 1.2)

        if text != self._partial_text:
            self._partial_text = text
            self._safe_partial(text)

    def _commit(self, cut_sample: int) -> None:
        """Подтверждает текст до `cut_sample`; остаток звука остаётся в буфере."""
        audio = self._buffer_audio()
        cut = max(0, min(int(cut_sample), audio.size))
        head, tail = audio[:cut], audio[cut:]

        if head.size >= self._config.min_commit_seconds * self._config.sample_rate:
            text = self._transcribe(head, fast=False)
        else:
            text = ""

        if text:
            addition = postprocess.join_with_previous(self._context, text)
            self._context = (self._context + addition)[-self._config.context_chars :]
            self._partial_text = ""
            self._safe_commit(text)
        else:
            # Ничего достоверного не распознано — убираем показанный ранее черновик.
            self._clear_partial()

        self._reset_buffer(tail)

    def _transcribe(self, audio: np.ndarray, *, fast: bool) -> str:
        if audio.size == 0:
            return ""
        try:
            segments = self._engine.transcribe(audio, prompt=self._context or None, fast=fast)
        except Exception as error:
            logger.exception("Ошибка распознавания фрагмента")
            self._safe_error(f"Ошибка распознавания: {error}")
            return ""
        return postprocess.clean_segments(segments)

    # ---------------------------------------------------------------- #
    # Буфер
    # ---------------------------------------------------------------- #

    @property
    def _buffer_seconds(self) -> float:
        return self._buffer_samples / self._config.sample_rate

    def _buffer_audio(self) -> np.ndarray:
        if not self._blocks:
            return np.zeros(0, dtype=np.float32)
        if len(self._blocks) > 1:
            self._blocks = [np.concatenate(self._blocks)]
        return self._blocks[0]

    def _cut_after_trailing_silence(self) -> int:
        """Точка реза: конец буфера минус небольшой «хвост» тишины."""
        keep = int(self._config.keep_tail_seconds * self._config.sample_rate)
        return max(0, self._buffer_samples - keep)

    def _reset_buffer(self, tail: np.ndarray) -> None:
        """Начинает новое высказывание, сохраняя хвост звука."""
        self._vad.reset()
        self._blocks = []
        self._buffer_samples = 0
        if tail.size:
            self._append(np.ascontiguousarray(tail))

    def _trim_to_tail(self, seconds: float) -> None:
        audio = self._buffer_audio()
        keep = int(seconds * self._config.sample_rate)
        self._reset_buffer(audio[-keep:] if keep else np.zeros(0, dtype=np.float32))

    def _enforce_backlog_limit(self) -> None:
        """Ограничивает буфер, если распознавание не успевает за речью (ТЗ §22)."""
        limit = self._config.hard_backlog_seconds
        if self._buffer_seconds <= limit:
            return
        if not self._backlog_warned:
            self._backlog_warned = True
            logger.warning(
                "Распознавание не успевает за речью, часть звука отброшена. "
                "Выберите модель меньшего размера в настройках."
            )
            self._safe_error(
                "Распознавание не успевает за речью — часть записи может быть потеряна. "
                "Выберите в настройках модель меньшего размера."
            )
        audio = self._buffer_audio()
        keep = int(self._config.max_utterance_seconds * self._config.sample_rate)
        # Пересобираем разметку речи: часть кадров относилась к отброшенному звуку.
        self._vad.reset()
        self._blocks = []
        self._buffer_samples = 0
        tail = np.ascontiguousarray(audio[-keep:])
        self._blocks.append(tail)
        self._buffer_samples = tail.size
        self._vad.feed(tail)

    # ---------------------------------------------------------------- #
    # Уведомления
    # ---------------------------------------------------------------- #

    def _clear_partial(self) -> None:
        if self._partial_text:
            self._partial_text = ""
            self._safe_partial("")

    def _safe_partial(self, text: str) -> None:
        try:
            self._callbacks.on_partial(text)
        except Exception:
            logger.exception("Ошибка в обработчике промежуточного результата")

    def _safe_commit(self, text: str) -> None:
        try:
            self._callbacks.on_commit(text)
        except Exception:
            logger.exception("Ошибка в обработчике подтверждённого результата")

    def _safe_error(self, message: str) -> None:
        try:
            self._callbacks.on_error(message)
        except Exception:
            logger.exception("Ошибка в обработчике ошибок")
