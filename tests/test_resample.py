"""Проверка потокового пересчёта частоты дискретизации."""

from __future__ import annotations

import numpy as np
import pytest

from voicetext_ru.audio.resample import Resampler


def _sine(frequency: float, seconds: float, rate: int) -> np.ndarray:
    t = np.arange(int(seconds * rate), dtype=np.float32) / rate
    return np.sin(2.0 * np.pi * frequency * t).astype(np.float32)


def test_passthrough_returns_identical_samples() -> None:
    resampler = Resampler(16_000, 16_000)
    block = _sine(440.0, 0.1, 16_000)
    assert np.array_equal(resampler.process(block), block)


@pytest.mark.parametrize("source_rate", [44_100, 48_000, 32_000])
def test_output_length_matches_ratio(source_rate: int) -> None:
    """Длина результата должна соответствовать отношению частот с точностью до кадра."""
    resampler = Resampler(source_rate, 16_000)
    block = _sine(220.0, 0.032, source_rate)
    blocks = int(1.0 * source_rate) // block.size

    consumed = blocks * block.size
    produced = sum(resampler.process(block).size for _ in range(blocks))

    expected = consumed * 16_000 / source_rate
    assert abs(produced - expected) <= 2, (produced, expected)


def test_block_boundaries_do_not_introduce_discontinuity() -> None:
    """Обработка по блокам должна давать тот же сигнал, что и обработка целиком."""
    source_rate = 48_000
    signal = _sine(300.0, 0.5, source_rate)

    whole = Resampler(source_rate, 16_000).process(signal)

    chunked_resampler = Resampler(source_rate, 16_000)
    block_size = 1536
    chunked = np.concatenate(
        [chunked_resampler.process(signal[i : i + block_size]) for i in range(0, signal.size, block_size)]
    )

    length = min(whole.size, chunked.size)
    assert length > 0
    assert np.max(np.abs(whole[:length] - chunked[:length])) < 1e-5


def test_lowpass_suppresses_frequencies_above_nyquist() -> None:
    """Составляющие выше 8 кГц должны подавляться, иначе возникнет наложение спектров."""
    source_rate = 48_000
    resampler = Resampler(source_rate, 16_000)
    # 15 кГц при пересчёте в 16 кГц без фильтра превратились бы в 1 кГц.
    output = resampler.process(_sine(15_000.0, 0.5, source_rate))

    spectrum = np.abs(np.fft.rfft(output))
    frequencies = np.fft.rfftfreq(output.size, 1.0 / 16_000)
    alias_band = (frequencies > 500) & (frequencies < 1500)

    assert spectrum[alias_band].max() < 0.02 * output.size
