"""Проверка потоковой обработки речи (ТЗ §10, §15, §23).

Движок заменён детерминированной заглушкой: проверяется именно логика
сегментации и подтверждения, а не качество модели.
"""

from __future__ import annotations

import time
from collections import deque

import numpy as np
import pytest

from voicetext_ru.asr.types import EngineInfo, TranscribedSegment
from voicetext_ru.asr.worker import StreamConfig, TranscriptionWorker, WorkerCallbacks

RATE = 16_000
BLOCK = 512
WORDS = ("один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять", "десять")

rng = np.random.default_rng(1234)


def speech(seconds: float) -> np.ndarray:
    return (rng.standard_normal(int(seconds * RATE)) * 0.25).astype(np.float32)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * RATE), dtype=np.float32)


def to_blocks(audio: np.ndarray) -> list[np.ndarray]:
    return [audio[i : i + BLOCK] for i in range(0, audio.size, BLOCK)]


class FakeEngine:
    """Возвращает по одному слову на каждые 0.5 с громкого звука."""

    def __init__(self) -> None:
        self.calls = 0
        self.fast_calls = 0

    @property
    def info(self) -> EngineInfo:
        return EngineInfo(model_id="fake", device="cpu", compute_type="int8")

    def transcribe(self, audio, *, prompt=None, fast=False):  # noqa: ANN001, ANN202
        self.calls += 1
        if fast:
            self.fast_calls += 1
        loud_seconds = float(np.count_nonzero(np.abs(audio) > 0.05)) / RATE
        count = min(len(WORDS), int(loud_seconds / 0.5))
        if count == 0:
            return []
        return [TranscribedSegment(text=" ".join(WORDS[:count]), start=0.0, end=len(audio) / RATE)]


class TrickleSource:
    """Отдаёт звук маленькими порциями, имитируя поступление в реальном времени."""

    def __init__(self, audio: np.ndarray) -> None:
        self._blocks = deque(to_blocks(audio))

    @property
    def exhausted(self) -> bool:
        return not self._blocks

    def read(self, timeout: float = 0.1):  # noqa: ANN202
        if self._blocks:
            return self._blocks.popleft()
        time.sleep(min(timeout, 0.005))
        return None

    def drain(self, limit: int = 256):  # noqa: ANN202
        # По одному блоку за шаг: иначе вся запись попала бы в буфер разом
        # и разбиение на фразы не проверялось бы.
        return [self._blocks.popleft()] if self._blocks else []


class TextModel:
    """Модель документа по контракту `TranscriptInserter`.

    Черновой текст занимает область в конце и заменяется целиком.
    """

    def __init__(self) -> None:
        self.text = ""
        self._partial_length = 0

    def _base(self) -> str:
        return self.text[: len(self.text) - self._partial_length]

    def set_partial(self, value: str) -> None:
        base = self._base()
        addition = (" " if base and value else "") + value if value else ""
        self.text = base + addition
        self._partial_length = len(addition)

    def commit(self, value: str) -> None:
        base = self._base()
        addition = (" " if base else "") + value
        self.text = base + addition
        self._partial_length = 0


def run_worker(audio: np.ndarray, config: StreamConfig, timeout: float = 20.0):  # noqa: ANN202
    """Прогоняет запись через рабочий поток и возвращает (модель, подтверждения, движок)."""
    engine = FakeEngine()
    source = TrickleSource(audio)
    model = TextModel()
    commits: list[str] = []
    partials: list[str] = []

    def on_commit(text: str) -> None:
        commits.append(text)
        model.commit(text)

    def on_partial(text: str) -> None:
        partials.append(text)
        model.set_partial(text)

    worker = TranscriptionWorker(
        engine=engine,
        source=source,
        callbacks=WorkerCallbacks(
            on_partial=on_partial, on_commit=on_commit, on_error=lambda message: None
        ),
        config=config,
    )
    worker.start()

    deadline = time.monotonic() + timeout
    while not source.exhausted and time.monotonic() < deadline:
        time.sleep(0.01)
    worker.request_stop()
    worker.join(timeout=timeout)
    assert not worker.is_alive(), "Поток распознавания не завершился"

    return model, commits, partials, engine


def test_pauses_split_speech_into_separate_confirmations() -> None:
    """Две фразы, разделённые паузой, дают два подтверждения."""
    audio = np.concatenate([speech(3.0), silence(1.2), speech(2.0), silence(1.2)])
    model, commits, _partials, _engine = run_worker(audio, StreamConfig(partial_interval_ms=1))

    assert len(commits) == 2, commits
    assert all(commit for commit in commits)


def test_partial_results_never_accumulate() -> None:
    """Главное требование ТЗ §15: уточнения заменяют черновик, а не дописываются."""
    audio = np.concatenate([speech(4.0), silence(1.2)])
    model, commits, partials, _engine = run_worker(audio, StreamConfig(partial_interval_ms=1))

    assert partials, "Промежуточные результаты не выдавались"
    assert commits
    # Документ содержит ровно подтверждённый текст — без следов черновиков.
    assert model.text == " ".join(commits)
    assert "один один" not in model.text


def test_no_duplicate_words_across_confirmations() -> None:
    audio = np.concatenate([speech(2.0), silence(1.0), speech(2.0), silence(1.0)])
    _model, commits, _partials, _engine = run_worker(audio, StreamConfig(partial_interval_ms=1))

    for commit in commits:
        words = commit.split()
        assert len(words) == len(set(words)), f"Слова продублированы: {commit}"


def test_silence_alone_produces_no_text() -> None:
    """Тишина не должна порождать текст: это защита от «галлюцинаций» модели."""
    _model, commits, partials, engine = run_worker(silence(6.0), StreamConfig(partial_interval_ms=1))

    assert commits == []
    assert all(text == "" for text in partials)


def test_continuous_speech_is_committed_without_pauses() -> None:
    """Речь без пауз фиксируется принудительно — буфер и задержка не растут (ТЗ §22)."""
    config = StreamConfig(max_utterance_seconds=3.0, partial_interval_ms=1)
    audio = np.concatenate([speech(12.0), silence(1.0)])
    _model, commits, _partials, _engine = run_worker(audio, config)

    assert len(commits) >= 3, f"Ожидалась принудительная фиксация, получено: {commits}"


def test_remaining_audio_is_processed_on_stop() -> None:
    """При остановке записи остаток звука обрабатывается, текст не теряется (ТЗ §33)."""
    config = StreamConfig(partial_interval_ms=1, commit_silence_ms=3000)
    audio = speech(2.0)  # пауза в конце отсутствует
    _model, commits, _partials, _engine = run_worker(audio, config)

    assert commits, "Остаток звука не был распознан при остановке"


def test_fast_mode_is_used_for_partial_results_only() -> None:
    """Черновики считаются экономичным проходом, подтверждения — точным."""
    audio = np.concatenate([speech(3.0), silence(1.2)])
    _model, commits, _partials, engine = run_worker(audio, StreamConfig(partial_interval_ms=1))

    assert engine.fast_calls > 0
    assert engine.calls > engine.fast_calls  # был и точный проход


def test_draft_passes_cannot_starve_confirmations() -> None:
    """Черновики не должны съедать время, нужное для подтверждения фраз (ТЗ §22).

    Проверяется расчёт бюджета напрямую: воспроизводить нехватку времени
    настоящими задержками означало бы сделать тест медленным и неустойчивым.
    """
    worker = TranscriptionWorker(
        engine=FakeEngine(),
        source=TrickleSource(silence(0.1)),
        callbacks=WorkerCallbacks(
            on_partial=lambda text: None, on_commit=lambda text: None, on_error=lambda text: None
        ),
        config=StreamConfig(draft_time_budget=0.3),
    )
    worker._started_at = time.monotonic() - 10.0

    worker._draft_seconds_used = 1.0  # 10% реального времени — в пределах бюджета
    assert worker._draft_budget_available()

    worker._draft_seconds_used = 5.0  # 50% — бюджет исчерпан
    assert not worker._draft_budget_available()


def test_draft_budget_does_not_block_at_session_start() -> None:
    """В первую секунду сеанса статистики ещё нет — черновик должен быть разрешён."""
    worker = TranscriptionWorker(
        engine=FakeEngine(),
        source=TrickleSource(silence(0.1)),
        callbacks=WorkerCallbacks(
            on_partial=lambda text: None, on_commit=lambda text: None, on_error=lambda text: None
        ),
        config=StreamConfig(draft_time_budget=0.0),
    )
    assert worker._draft_budget_available()


@pytest.mark.parametrize("show_partial", [True, False])
def test_partial_output_can_be_disabled(show_partial: bool) -> None:
    audio = np.concatenate([speech(3.0), silence(1.2)])
    config = StreamConfig(partial_interval_ms=1, emit_partial=show_partial)
    _model, commits, partials, engine = run_worker(audio, config)

    assert commits
    if show_partial:
        assert engine.fast_calls > 0
    else:
        assert engine.fast_calls == 0
        assert all(text == "" for text in partials)
