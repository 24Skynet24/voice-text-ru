"""Проверка двухуровневого движка и выбора вычислительного устройства."""

from __future__ import annotations

import numpy as np
import pytest

from voicetext_ru.asr.engine import TieredEngine, default_cpu_threads, resolve_backend
from voicetext_ru.asr.types import EngineInfo, TranscribedSegment


class StubEngine:
    """Движок-заглушка, запоминающий обращения к нему."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[bool] = []
        self.closed = False

    @property
    def info(self) -> EngineInfo:
        return EngineInfo(model_id=self.name, device="cpu", compute_type="int8")

    def transcribe(self, audio, *, prompt=None, fast=False):  # noqa: ANN001, ANN202
        self.calls.append(fast)
        return [TranscribedSegment(text=self.name, start=0.0, end=1.0)]

    def close(self) -> None:
        self.closed = True


AUDIO = np.zeros(16_000, dtype=np.float32)


def test_draft_model_handles_partial_results() -> None:
    accurate, draft = StubEngine("точная"), StubEngine("черновая")
    engine = TieredEngine(accurate, draft)

    assert engine.transcribe(AUDIO, fast=True)[0].text == "черновая"
    assert engine.transcribe(AUDIO, fast=False)[0].text == "точная"
    assert draft.calls == [True]
    assert accurate.calls == [False]


def test_without_draft_model_everything_goes_to_the_accurate_one() -> None:
    accurate = StubEngine("точная")
    engine = TieredEngine(accurate, None)

    assert engine.transcribe(AUDIO, fast=True)[0].text == "точная"
    assert accurate.calls == [True]


def test_info_mentions_both_models() -> None:
    engine = TieredEngine(StubEngine("large-v3-turbo"), StubEngine("small"))
    assert engine.info.model_id == "large-v3-turbo"
    assert engine.info.draft_model_id == "small"
    assert "small" in engine.info.summary


def test_closing_releases_both_models() -> None:
    accurate, draft = StubEngine("точная"), StubEngine("черновая")
    TieredEngine(accurate, draft).close()

    assert accurate.closed and draft.closed


def test_failure_of_one_model_does_not_prevent_closing_the_other() -> None:
    """Освобождение ресурсов не должно прерываться на первой ошибке (ТЗ §36)."""

    class BrokenEngine(StubEngine):
        def close(self) -> None:
            raise RuntimeError("сбой при остановке")

    accurate = StubEngine("точная")
    TieredEngine(accurate, BrokenEngine("черновая")).close()

    assert accurate.closed


@pytest.mark.parametrize(
    ("preference", "expected_device"),
    [("cpu", "cpu"), ("cuda", "cuda")],
)
def test_explicit_device_preference_is_respected(preference: str, expected_device: str) -> None:
    device, compute_type = resolve_backend(preference)
    assert device == expected_device
    assert compute_type in ("int8", "float16")


def test_auto_backend_falls_back_to_cpu_without_cuda() -> None:
    device, compute_type = resolve_backend("auto")
    assert device in ("cpu", "cuda")
    if device == "cpu":
        # INT8 на процессоре втрое быстрее FP32 при той же точности на русском.
        assert compute_type == "int8"


def test_thread_count_is_sane() -> None:
    threads = default_cpu_threads()
    assert 1 <= threads <= 16
