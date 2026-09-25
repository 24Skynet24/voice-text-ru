"""Проверка определения речевой активности."""

from __future__ import annotations

import numpy as np

from voicetext_ru.asr.vad import VadConfig, VoiceActivityTracker

RATE = 16_000
rng = np.random.default_rng(20240501)


def _noise(seconds: float, amplitude: float) -> np.ndarray:
    return (rng.standard_normal(int(seconds * RATE)) * amplitude).astype(np.float32)


def _silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * RATE), dtype=np.float32)


def test_silence_is_not_speech() -> None:
    tracker = VoiceActivityTracker()
    tracker.feed(_silence(2.0))
    assert not tracker.has_speech
    assert tracker.trailing_silence_seconds >= 1.9


def test_loud_signal_is_detected_as_speech() -> None:
    tracker = VoiceActivityTracker()
    tracker.feed(_silence(0.5))
    tracker.feed(_noise(1.0, 0.25))
    assert tracker.has_speech
    assert tracker.trailing_silence_seconds < 0.1


def test_trailing_silence_is_measured_after_speech() -> None:
    tracker = VoiceActivityTracker()
    tracker.feed(_noise(1.0, 0.25))
    tracker.feed(_silence(0.8))
    assert tracker.has_speech
    assert 0.7 <= tracker.trailing_silence_seconds <= 0.9


def test_quiet_room_noise_does_not_count_as_speech() -> None:
    """Постоянный фоновый шум должен «впитаться» в оценку шума, а не считаться речью."""
    tracker = VoiceActivityTracker()
    tracker.feed(_noise(5.0, 0.012))
    # Отдельные всплески допустимы, но непрерывной речи быть не должно.
    assert tracker.speech_frame_count < tracker.frame_count * 0.2


def test_speech_detected_over_background_noise() -> None:
    """Речь громче фона распознаётся даже в шумной комнате."""
    tracker = VoiceActivityTracker()
    tracker.feed(_noise(3.0, 0.01))
    tracker.feed(_noise(1.0, 0.18))
    assert tracker.has_speech


def test_reset_keeps_noise_estimate() -> None:
    tracker = VoiceActivityTracker()
    tracker.feed(_noise(3.0, 0.02))
    noise_before = tracker.noise_floor
    tracker.reset()

    assert tracker.frame_count == 0
    assert not tracker.has_speech
    assert tracker.noise_floor == noise_before


def test_quietest_cut_point_lands_in_the_pause() -> None:
    """Принудительный разрыв должен приходиться на паузу, а не на середину слова."""
    tracker = VoiceActivityTracker()
    tracker.feed(_noise(3.0, 0.25))
    tracker.feed(_silence(0.4))
    tracker.feed(_noise(0.4, 0.25))

    cut = tracker.quietest_cut_sample(tail_fraction=0.4)
    assert cut is not None
    pause_start, pause_end = 3.0 * RATE, 3.4 * RATE
    assert pause_start <= cut <= pause_end


def test_absolute_floor_prevents_detection_in_digital_silence() -> None:
    """В абсолютной тишине порог не должен «сползти» до нуля и ловить шум квантования."""
    tracker = VoiceActivityTracker(VadConfig(absolute_floor=0.0035))
    tracker.feed(_silence(3.0))
    tracker.feed(_noise(0.5, 0.0005))
    assert not tracker.has_speech
