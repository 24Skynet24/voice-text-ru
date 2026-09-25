"""Непрерывный захват звука с микрофона.

Захват идёт в callback-потоке PortAudio и не зависит от фокуса окна (ТЗ §6, §32).
Callback выполняет только дешёвые операции: сведение в моно, измерение уровня,
пересчёт частоты и постановку блока в очередь. Всё тяжёлое — в потоке распознавания.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable

import numpy as np
import sounddevice as sd

from .devices import AudioDevice
from .resample import Resampler

logger = logging.getLogger(__name__)

TARGET_SAMPLE_RATE = 16_000
"""Частота, которую требует Whisper."""

_BLOCK_SECONDS = 0.032
_QUEUE_SECONDS = 120.0
"""Предел буферизации в очереди. Ограничивает расход памяти, если распознавание
временно не успевает за речью (ТЗ §22)."""


class AudioCaptureError(RuntimeError):
    """Микрофон недоступен или не поддерживает требуемый режим."""


class AudioCapture:
    """Открывает поток ввода и отдаёт блоки моно-звука 16 кГц float32."""

    def __init__(
        self,
        device: AudioDevice | None,
        on_stream_error: Callable[[str], None] | None = None,
    ) -> None:
        self._device = device
        self._on_stream_error = on_stream_error
        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        self._stream: sd.InputStream | None = None
        self._resampler: Resampler | None = None
        self._channels = 1
        self._level = 0.0
        self._dropped_blocks = 0
        self._overflow_count = 0
        self._failed = False
        self._lock = threading.Lock()
        self._max_queue_blocks = int(_QUEUE_SECONDS / _BLOCK_SECONDS)

    # ---------------------------------------------------------------- #
    # Жизненный цикл
    # ---------------------------------------------------------------- #

    def start(self) -> None:
        """Открывает и запускает поток захвата.

        :raises AudioCaptureError: если устройство недоступно.
        """
        if self._stream is not None:
            return

        device_index = self._device.index if self._device else None
        sample_rate, channels = self._negotiate_format(device_index)
        self._resampler = Resampler(sample_rate, TARGET_SAMPLE_RATE)
        self._channels = channels

        try:
            self._stream = sd.InputStream(
                device=device_index,
                samplerate=sample_rate,
                channels=channels,
                dtype="float32",
                blocksize=max(64, int(sample_rate * _BLOCK_SECONDS)),
                callback=self._callback,
                finished_callback=self._on_finished,
            )
            self._stream.start()
        except Exception as error:  # PortAudioError и производные
            self._stream = None
            logger.exception("Не удалось открыть микрофон")
            raise AudioCaptureError(_describe_open_error(self._device, error)) from error

        logger.info(
            "Микрофон запущен: %s (%d Гц, каналов: %d)",
            self._device.name if self._device else "системный по умолчанию",
            sample_rate,
            channels,
        )

    def stop(self) -> None:
        """Останавливает поток и освобождает устройство (ТЗ §36)."""
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            stream.stop()
        except Exception:
            logger.exception("Ошибка при остановке потока захвата")
        finally:
            try:
                stream.close()
            except Exception:
                logger.exception("Ошибка при закрытии потока захвата")
        logger.info(
            "Микрофон остановлен (переполнений очереди: %d, переполнений ввода: %d)",
            self._dropped_blocks,
            self._overflow_count,
        )

    def __enter__(self) -> AudioCapture:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()

    # ---------------------------------------------------------------- #
    # Данные
    # ---------------------------------------------------------------- #

    def read(self, timeout: float = 0.1) -> np.ndarray | None:
        """Возвращает следующий блок звука или None, если за `timeout` ничего не пришло."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self, limit: int = 256) -> list[np.ndarray]:
        """Забирает все накопленные блоки без ожидания."""
        blocks: list[np.ndarray] = []
        for _ in range(limit):
            try:
                blocks.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return blocks

    @property
    def level(self) -> float:
        """Текущий уровень сигнала в диапазоне 0..1 (ТЗ §18)."""
        return self._level

    @property
    def is_active(self) -> bool:
        stream = self._stream
        try:
            return bool(stream is not None and stream.active)
        except Exception:
            return False

    @property
    def has_failed(self) -> bool:
        """Поток прервался сам (например, микрофон отключили) — ТЗ §31, тест 8."""
        return self._failed

    # ---------------------------------------------------------------- #
    # Внутреннее
    # ---------------------------------------------------------------- #

    def _negotiate_format(self, device_index: int | None) -> tuple[int, int]:
        """Подбирает частоту и число каналов, которые примет устройство.

        WASAPI в разделяемом режиме принимает только текущий формат микшера,
        поэтому 16 кГц/моно доступны далеко не всегда.
        """
        default_rate = int(self._device.default_samplerate) if self._device else 48_000
        max_channels = self._device.max_input_channels if self._device else 2

        rates = [TARGET_SAMPLE_RATE, default_rate, 48_000, 44_100]
        channel_options = [1, min(2, max_channels), max_channels]

        tried: set[tuple[int, int]] = set()
        first_error: Exception | None = None
        for rate in rates:
            for channels in channel_options:
                if rate <= 0 or channels <= 0 or (rate, channels) in tried:
                    continue
                tried.add((rate, channels))
                try:
                    sd.check_input_settings(
                        device=device_index, samplerate=rate, channels=channels, dtype="float32"
                    )
                    return rate, channels
                except Exception as error:
                    first_error = first_error or error

        raise AudioCaptureError(
            _describe_open_error(self._device, first_error or RuntimeError("формат не поддерживается"))
        )

    def _callback(self, indata: np.ndarray, frames: int, time_info: object, status: sd.CallbackFlags) -> None:
        """Вызывается потоком PortAudio в реальном времени."""
        # Прочие флаги PortAudio не фатальны: звук продолжает поступать.
        if status and status.input_overflow:
            self._overflow_count += 1

        try:
            mono = indata[:, 0] if indata.shape[1] == 1 else indata.mean(axis=1)
            mono = np.ascontiguousarray(mono, dtype=np.float32)

            peak = float(np.max(np.abs(mono))) if mono.size else 0.0
            # Быстрая атака, плавный спад — индикатор не «дёргается».
            self._level = peak if peak > self._level else self._level * 0.82

            assert self._resampler is not None
            block = self._resampler.process(mono)
            if block.size == 0:
                return

            if self._queue.qsize() >= self._max_queue_blocks:
                # Распознавание не успевает: жертвуем самым старым звуком,
                # чтобы расход памяти оставался ограниченным.
                try:
                    self._queue.get_nowait()
                    self._dropped_blocks += 1
                except queue.Empty:
                    pass
            self._queue.put_nowait(block)
        except Exception:
            # Исключение из callback останавливает поток PortAudio — гасим и логируем.
            logger.exception("Сбой в callback захвата звука")

    def _on_finished(self) -> None:
        """PortAudio сообщает, что поток завершился."""
        if self._stream is None:
            return  # штатная остановка
        with self._lock:
            if self._failed:
                return
            self._failed = True
        logger.error("Поток захвата звука прерван (устройство отключено?)")
        if self._on_stream_error is not None:
            self._on_stream_error(
                "Микрофон перестал отвечать. Проверьте, что устройство подключено и доступно."
            )


def _describe_open_error(device: AudioDevice | None, error: Exception) -> str:
    """Понятное пользователю сообщение об ошибке (ТЗ §31)."""
    name = device.name if device else "микрофон по умолчанию"
    text = str(error).lower()
    if "device unavailable" in text or "invalid device" in text or "-9996" in text:
        return f"Устройство «{name}» недоступно. Возможно, оно отключено или занято другой программой."
    if "access" in text or "denied" in text:
        return (
            f"Нет доступа к устройству «{name}». Разрешите доступ к микрофону в параметрах "
            "конфиденциальности Windows."
        )
    return f"Не удалось открыть микрофон «{name}»: {error}"
