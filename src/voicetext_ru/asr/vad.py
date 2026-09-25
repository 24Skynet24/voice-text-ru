"""Определение речевой активности по энергии сигнала.

Задача этого модуля — не отличить речь от шума идеально, а решить, **когда**
резать поток на фрагменты. Ошибка в ту или иную сторону стоит задержки, но не
точности: внутри `transcribe()` дополнительно работает Silero VAD, который
убирает неречевые участки уже перед самой моделью.

Уровень шума оценивается методом минимальной статистики: берётся самый тихий
кадр за последние несколько секунд. В отличие от усреднения, такая оценка не
«затягивается» вверх громкой речью — даже в непрерывной речи есть паузы между
словами, и они на 10–20 дБ тише самих слов.

Отдельно оценка шума ограничена сверху: фоновый шум пригодного для диктовки
микрофона не бывает громче примерно -30 дБFS. Без этого ограничения запись,
начатая посреди громкой фразы, задрала бы порог выше уровня речи, и
распознавание не началось бы вовсе.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class VadConfig:
    sample_rate: int = 16_000
    frame_ms: int = 32
    speech_ratio: float = 3.0
    """Во сколько раз кадр должен быть громче оценки шума, чтобы считаться речью."""
    absolute_floor: float = 0.0035
    """Нижняя граница порога (~-49 дБFS): защищает от срабатывания в полной тишине."""
    max_noise_floor: float = 0.03
    """Верхняя граница оценки шума (~-30 дБFS) — см. пояснение в начале модуля."""
    noise_window_seconds: float = 3.2
    """Окно, по которому ищется самый тихий кадр."""
    min_speech_frames: int = 4
    """Сколько речевых кадров (~128 мс) нужно, чтобы считать фрагмент непустым."""


class VoiceActivityTracker:
    """Накапливает признаки речи по кадрам для текущего фрагмента."""

    def __init__(self, config: VadConfig | None = None) -> None:
        self.config = config or VadConfig()
        self._frame_size = max(1, int(self.config.sample_rate * self.config.frame_ms / 1000))
        self._remainder = np.zeros(0, dtype=np.float32)
        self._rms: list[float] = []
        self._is_speech: list[bool] = []

        # Монотонная очередь (индекс, RMS) с неубывающими значениями:
        # её голова — минимум по окну, обновление амортизированно O(1).
        self._minimum_window: deque[tuple[int, float]] = deque()
        self._window_frames = max(1, int(self.config.noise_window_seconds / self.frame_seconds))
        self._frame_index = 0

    # ---------------------------------------------------------------- #

    @property
    def frame_seconds(self) -> float:
        return self._frame_size / self.config.sample_rate

    @property
    def noise_floor(self) -> float:
        """Оценка уровня фонового шума по самому тихому кадру в окне."""
        return self._minimum_window[0][1] if self._minimum_window else 0.0

    @property
    def threshold(self) -> float:
        """Текущий порог отнесения кадра к речи."""
        limited = min(self.noise_floor, self.config.max_noise_floor)
        return max(limited * self.config.speech_ratio, self.config.absolute_floor)

    @property
    def frame_count(self) -> int:
        return len(self._is_speech)

    @property
    def speech_frame_count(self) -> int:
        return sum(self._is_speech)

    @property
    def has_speech(self) -> bool:
        """Достаточно ли речи в накопленном фрагменте, чтобы его распознавать."""
        return self.speech_frame_count >= self.config.min_speech_frames

    @property
    def trailing_silence_seconds(self) -> float:
        """Длительность тишины в конце фрагмента."""
        silent = 0
        for flag in reversed(self._is_speech):
            if flag:
                break
            silent += 1
        return silent * self.frame_seconds

    # ---------------------------------------------------------------- #

    def feed(self, audio: np.ndarray) -> None:
        """Добавляет очередной блок звука и размечает полные кадры."""
        block = np.asarray(audio, dtype=np.float32).reshape(-1)
        if self._remainder.size:
            block = np.concatenate((self._remainder, block))

        frame_count = block.size // self._frame_size
        if frame_count:
            frames = block[: frame_count * self._frame_size].reshape(frame_count, self._frame_size)
            # RMS устойчивее пикового значения к одиночным щелчкам.
            rms_values = np.sqrt(np.mean(np.square(frames, dtype=np.float32), axis=1))
            for value in rms_values:
                self._push_frame(float(value))

        self._remainder = block[frame_count * self._frame_size :].copy()

    def _push_frame(self, rms: float) -> None:
        # Кадры громче нового уже не могут стать минимумом — убираем их.
        while self._minimum_window and self._minimum_window[-1][1] >= rms:
            self._minimum_window.pop()
        self._minimum_window.append((self._frame_index, rms))
        while self._minimum_window[0][0] <= self._frame_index - self._window_frames:
            self._minimum_window.popleft()

        self._rms.append(rms)
        self._is_speech.append(rms > self.threshold)
        self._frame_index += 1

    # ---------------------------------------------------------------- #

    def quietest_cut_sample(self, tail_fraction: float = 0.25) -> int | None:
        """Индекс отсчёта в самом тихом месте конца фрагмента.

        Используется при принудительной фиксации длинной непрерывной речи:
        резать в паузе между словами гораздо безопаснее, чем в произвольной точке.
        Возвращает None, если кадров слишком мало.
        """
        if len(self._rms) < 8:
            return None
        start = max(1, int(len(self._rms) * (1.0 - tail_fraction)))
        window = self._rms[start:]
        if not window:
            return None
        offset = int(np.argmin(window))
        return (start + offset) * self._frame_size

    def reset(self) -> None:
        """Начинает новый фрагмент, сохраняя накопленную оценку шума."""
        self._remainder = np.zeros(0, dtype=np.float32)
        self._rms.clear()
        self._is_speech.clear()
