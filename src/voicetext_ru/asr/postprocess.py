"""Очистка результата распознавания.

Whisper — генеративная модель, и на тишине или шуме она устойчиво «додумывает»
типовые фразы из субтитров, на которых обучалась: «Продолжение следует…»,
«Субтитры сделал DimaTorzok», «Спасибо за просмотр!». В диктофоне такой текст
недопустим, поэтому фрагменты фильтруются по достоверности и по списку
известных артефактов.

Фильтр намеренно консервативен: под блокировку попадает только фрагмент,
который **целиком** совпал с артефактом. Совпадение по вхождению удаляло бы
настоящую речь.
"""

from __future__ import annotations

import logging
import re
import unicodedata

from .types import TranscribedSegment

logger = logging.getLogger(__name__)

MAX_NO_SPEECH_PROB = 0.9
"""Фрагменты с большей вероятностью «здесь нет речи» отбрасываются."""

MIN_AVG_LOGPROB = -1.2
"""Средняя логарифмическая вероятность ниже этой — модель не уверена в тексте."""

MAX_COMPRESSION_RATIO = 2.6
"""Высокая сжимаемость текста означает зацикливание («и и и и и»)."""

_HALLUCINATIONS: frozenset[str] = frozenset(
    {
        # Русские титры и концовки роликов
        "продолжение следует",
        "продолжение в следующей серии",
        "спасибо за просмотр",
        "спасибо за внимание",
        "спасибо что посмотрели",
        "подписывайтесь на канал",
        "подписывайтесь на наш канал",
        "ставьте лайки и подписывайтесь на канал",
        "ставьте лайк и подписывайтесь",
        "не забудьте подписаться на канал",
        "до новых встреч",
        "всем пока",
        "редактор субтитров а синецкая корректор а кулакова",
        "корректор а кулакова",
        "субтитры и перевод сделал dimatorzok",
        "субтитры сделал dimatorzok",
        "субтитры создавал dimatorzok",
        "субтитры делал dimatorzok",
        # Английские артефакты той же природы
        "thank you",
        "thanks for watching",
        "thank you for watching",
        "subtitles by the amaraorg community",
        "bye",
        "you",
    }
)

# Шаблоны описывают именно титры роликов, а не отдельные слова: «субтитры» и
# «перевод» сами по себе — обычные слова русской речи и блокироваться не должны.
_HALLUCINATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^субтитры\b.*(dimatorzok|дима торзок|amara|subtitles)"),
    re.compile(r"^(субтитры|перевод|перевод и субтитры)\s+(сделал|создавал|делал|подготовил|выполнил)\b"),
    re.compile(r"^редактор субтитров\b"),
    re.compile(r"^(продолжение следует|to be continued)$"),
)

_PUNCTUATION = re.compile(r"[^\w\s]", flags=re.UNICODE)
_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Приводит текст к виду, пригодному для сравнения с артефактами."""
    lowered = unicodedata.normalize("NFKC", text).lower().replace("ё", "е")
    return _SPACES.sub(" ", _PUNCTUATION.sub(" ", lowered)).strip()


def is_hallucination(text: str) -> bool:
    """Совпадает ли фрагмент целиком с известным артефактом модели."""
    normalized = normalize(text)
    if not normalized:
        return True
    if normalized in _HALLUCINATIONS:
        return True
    return any(pattern.match(normalized) for pattern in _HALLUCINATION_PATTERNS)


def is_degenerate(text: str) -> bool:
    """Распознан зацикленный текст вида «и и и и и и»."""
    words = normalize(text).split()
    if len(words) >= 6 and len(set(words)) <= 2:
        return True
    # Повтор одной и той же фразы подряд более четырёх раз.
    for size in (2, 3, 4):
        if len(words) < size * 4:
            continue
        chunks = [tuple(words[i : i + size]) for i in range(0, len(words) - size + 1, size)]
        if len(chunks) >= 4 and len(set(chunks)) == 1:
            return True
    return False


def collapse_repetitions(text: str, max_repeats: int = 3) -> str:
    """Схлопывает подряд идущие одинаковые слова, оставляя не более `max_repeats`.

    Мягкая мера против коротких зацикливаний: текст сохраняется, лишние повторы
    убираются, а пользователь при необходимости поправит результат вручную.
    """
    words = text.split()
    if not words:
        return ""
    result: list[str] = []
    streak = 1
    for word in words:
        if result and normalize(word) == normalize(result[-1]):
            streak += 1
            if streak > max_repeats:
                continue
        else:
            streak = 1
        result.append(word)
    return " ".join(result)


def clean_segments(segments: list[TranscribedSegment]) -> str:
    """Склеивает достоверные фрагменты в одну строку.

    Возвращает пустую строку, если ничего достоверного не осталось.
    """
    accepted: list[str] = []
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        if segment.no_speech_prob > MAX_NO_SPEECH_PROB:
            logger.debug("Отброшен фрагмент (нет речи, p=%.2f): %r", segment.no_speech_prob, text)
            continue
        if segment.avg_logprob < MIN_AVG_LOGPROB:
            logger.debug("Отброшен фрагмент (низкая уверенность, %.2f): %r", segment.avg_logprob, text)
            continue
        if segment.compression_ratio > MAX_COMPRESSION_RATIO:
            logger.debug("Отброшен фрагмент (зацикливание, %.2f): %r", segment.compression_ratio, text)
            continue
        if is_hallucination(text) or is_degenerate(text):
            logger.debug("Отброшен фрагмент (артефакт модели): %r", text)
            continue
        accepted.append(collapse_repetitions(text))

    return re.sub(r"\s+", " ", " ".join(accepted)).strip()


def join_with_previous(previous: str, addition: str) -> str:
    """Определяет разделитель между уже вставленным текстом и новым фрагментом.

    Вызывается перед вставкой в документ, поэтому учитывает и текст, который
    пользователь набрал сам.
    """
    if not addition:
        return ""
    if not previous:
        return addition
    if previous[-1].isspace():
        return addition
    if previous[-1] in "([«“„-—":
        return addition
    return " " + addition
