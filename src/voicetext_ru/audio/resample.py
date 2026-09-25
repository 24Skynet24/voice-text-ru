"""Потоковое приведение частоты дискретизации к 16 кГц.

Микрофон в режиме WASAPI отдаёт звук на своей частоте (обычно 44.1 или 48 кГц),
а модель распознавания работает только с 16 кГц. Простое прореживание отсчётов
даёт наложение спектров и ухудшает распознавание, поэтому применяется
фильтр нижних частот (оконный sinc) с последующей линейной интерполяцией.

Класс хранит состояние между блоками, поэтому на границах блоков нет щелчков.
"""

from __future__ import annotations

import numpy as np

_DEFAULT_TAPS = 64


def _design_lowpass(cutoff_ratio: float, num_taps: int) -> np.ndarray:
    """Оконный sinc-фильтр нижних частот.

    :param cutoff_ratio: частота среза в долях частоты дискретизации источника (0..0.5).
    """
    taps = num_taps | 1  # нечётное число отсчётов — симметричное ядро без сдвига фазы
    positions = np.arange(taps, dtype=np.float64) - (taps - 1) / 2.0
    kernel = 2.0 * cutoff_ratio * np.sinc(2.0 * cutoff_ratio * positions)
    kernel *= np.hamming(taps)
    kernel /= np.sum(kernel)
    return kernel.astype(np.float32)


class Resampler:
    """Преобразует поток float32 из `source_rate` в `target_rate`."""

    def __init__(self, source_rate: int, target_rate: int, num_taps: int = _DEFAULT_TAPS) -> None:
        if source_rate <= 0 or target_rate <= 0:
            raise ValueError("Частота дискретизации должна быть положительной")
        self.source_rate = int(source_rate)
        self.target_rate = int(target_rate)
        self._passthrough = self.source_rate == self.target_rate

        if self._passthrough:
            self._kernel = np.ones(1, dtype=np.float32)
        else:
            # Срез чуть ниже частоты Найквиста приёмника, с запасом на переходную полосу.
            cutoff = 0.45 * min(self.target_rate, self.source_rate) / self.source_rate
            self._kernel = _design_lowpass(cutoff, num_taps)

        self._filter_tail = np.zeros(len(self._kernel) - 1, dtype=np.float32)
        self._previous_sample = np.zeros(1, dtype=np.float32)
        self._position = 0.0
        self._step = self.source_rate / self.target_rate

    def reset(self) -> None:
        """Сбрасывает внутреннее состояние (при перезапуске записи)."""
        self._filter_tail[:] = 0.0
        self._previous_sample[:] = 0.0
        self._position = 0.0

    def process(self, samples: np.ndarray) -> np.ndarray:
        """Преобразует очередной блок. Возвращает новый массив float32."""
        block = np.asarray(samples, dtype=np.float32).reshape(-1)
        if block.size == 0:
            return np.zeros(0, dtype=np.float32)
        if self._passthrough:
            return block.copy()

        # Фильтрация с сохранением «хвоста» предыдущего блока.
        padded = np.concatenate((self._filter_tail, block))
        filtered = np.convolve(padded, self._kernel, mode="valid").astype(np.float32)
        self._filter_tail = padded[-(len(self._kernel) - 1) :].copy()

        if filtered.size == 0:
            return np.zeros(0, dtype=np.float32)

        # Линейная интерполяция с дробной позицией, перенесённой из прошлого блока.
        extended = np.concatenate((self._previous_sample, filtered))
        last_index = extended.size - 1
        if self._position > last_index:
            self._position -= last_index
            self._previous_sample = extended[-1:].copy()
            return np.zeros(0, dtype=np.float32)

        count = int(np.floor((last_index - self._position) / self._step)) + 1
        indices = self._position + self._step * np.arange(count, dtype=np.float64)
        base = indices.astype(np.int64)
        frac = (indices - base).astype(np.float32)
        upper = np.minimum(base + 1, last_index)
        output = extended[base] * (1.0 - frac) + extended[upper] * frac

        # Переносим остаток позиции в систему координат следующего блока.
        self._position = self._position + self._step * count - last_index
        self._previous_sample = extended[-1:].copy()
        return output.astype(np.float32, copy=False)
