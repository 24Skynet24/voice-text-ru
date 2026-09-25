"""Проверка фильтрации результатов распознавания."""

from __future__ import annotations

import pytest

from voicetext_ru.asr import postprocess
from voicetext_ru.asr.types import TranscribedSegment


def _segment(text: str, **kwargs: float) -> TranscribedSegment:
    defaults = {"start": 0.0, "end": 1.0, "no_speech_prob": 0.1, "avg_logprob": -0.3}
    defaults.update(kwargs)
    return TranscribedSegment(text=text, **defaults)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "text",
    [
        "Продолжение следует...",
        "Субтитры сделал DimaTorzok",
        "Редактор субтитров А.Синецкая Корректор А.Кулакова",
        "Спасибо за просмотр!",
        "Подписывайтесь на канал",
        "Thanks for watching!",
    ],
)
def test_known_hallucinations_are_rejected(text: str) -> None:
    assert postprocess.is_hallucination(text)


@pytest.mark.parametrize(
    "text",
    [
        "Сегодня я тестирую новое приложение",
        "Субтитры к этому фильму мы сделаем завтра",
        "Нужен перевод документа на английский язык",
        "Спасибо за просмотр отчёта, теперь перейдём к следующему пункту",
        "Продолжение этой мысли будет в следующем разделе",
    ],
)
def test_real_speech_is_not_rejected(text: str) -> None:
    """Фильтр не должен удалять настоящую речь, похожую на артефакты."""
    assert not postprocess.is_hallucination(text)


def test_degenerate_repetition_is_detected() -> None:
    assert postprocess.is_degenerate("и и и и и и и")
    assert postprocess.is_degenerate("да да да да да да")
    assert not postprocess.is_degenerate("я хочу рассказать о новом проекте")


def test_collapse_repetitions_keeps_reasonable_text() -> None:
    assert postprocess.collapse_repetitions("очень очень очень очень хорошо") == (
        "очень очень очень хорошо"
    )
    assert postprocess.collapse_repetitions("это очень важно") == "это очень важно"


def test_low_confidence_segments_are_dropped() -> None:
    segments = [
        _segment("надёжный текст"),
        _segment("мусор", no_speech_prob=0.97),
        _segment("ещё мусор", avg_logprob=-2.0),
    ]
    assert postprocess.clean_segments(segments) == "надёжный текст"


def test_segments_are_joined_with_single_spaces() -> None:
    segments = [_segment(" первая часть "), _segment("  вторая часть")]
    assert postprocess.clean_segments(segments) == "первая часть вторая часть"


def test_clean_segments_returns_empty_when_nothing_is_reliable() -> None:
    assert postprocess.clean_segments([_segment("Продолжение следует...")]) == ""
    assert postprocess.clean_segments([]) == ""


@pytest.mark.parametrize(
    ("previous", "addition", "expected"),
    [
        ("", "слово", "слово"),
        ("текст", "слово", " слово"),
        ("текст ", "слово", "слово"),
        ("текст\n", "слово", "слово"),
        ("(", "слово", "слово"),
        ("текст", "", ""),
    ],
)
def test_join_with_previous(previous: str, addition: str, expected: str) -> None:
    assert postprocess.join_with_previous(previous, addition) == expected
