"""Grapheme alignment. A series dictionary overrides the fallback letter map."""

from __future__ import annotations

from cuervo_ir.models import AlignmentSpan

# Fallback only. A voice profile can replace any word.
FALLBACK_LETTERS = {
    "a": "AA",
    "e": "EE",
    "i": "EE",
    "o": "OH",
    "u": "OH",
    "m": "MBP",
    "b": "MBP",
    "p": "MBP",
    "f": "FV",
    "v": "FV",
    "l": "L",
}


def align_line(
    text: str,
    sample_count: int,
    dictionary: dict[str, str] | None = None,
) -> list[AlignmentSpan]:
    if sample_count < 1:
        raise ValueError("sample_count must be positive")
    pieces = _pieces(text, dictionary or {})
    if not pieces:
        pieces = [("rest", "rest", 0.5)]
    width = sample_count // len(pieces)
    if width < 1:
        width = 1
    spans: list[AlignmentSpan] = []
    cursor = 0
    for index, (label, phoneme, confidence) in enumerate(pieces):
        end = sample_count if index == len(pieces) - 1 else min(sample_count, cursor + width)
        if end <= cursor:
            break
        spans.append(
            AlignmentSpan(
                start_sample=cursor,
                end_sample=end,
                text=label,
                phoneme=phoneme,
                confidence=confidence,
            )
        )
        cursor = end
    return spans


def _pieces(text: str, dictionary: dict[str, str]) -> list[tuple[str, str, float]]:
    pieces: list[tuple[str, str, float]] = []
    for word in text.lower().split():
        letters = "".join(character for character in word if character.isalpha())
        if not letters:
            continue
        if letters in dictionary:
            pieces.append((letters, dictionary[letters], 0.9))
            continue
        for letter in letters:
            pieces.append((letter, FALLBACK_LETTERS.get(letter, "rest"), 0.6))
    return pieces
