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


# Letters with no shape of their own still open the mouth a little. `L` is the
# nearest shape in the eight: tongue up, teeth apart. Closing to `rest` on every
# t, s, or n would make the mouth chatter.
TIMED_LETTERS = {
    **FALLBACK_LETTERS,
    "y": "EE",
    "w": "OH",
    **{letter: "L" for letter in "cdghjknqrstxz"},
}

# A silence this long between two sounds closes the mouth.
PAUSE_SECONDS = 0.12


def align_timed(
    chars: list[tuple[str, float, float]],
    sample_rate: int,
    sample_count: int,
    dictionary: dict[str, str] | None = None,
) -> list[AlignmentSpan]:
    """Alignment from measured character times, as a voice vendor reports them.

    `chars` is `(character, start_seconds, end_seconds)` in spoken order. A
    dictionary word takes one shape for its whole length.
    """

    if sample_count < 1:
        raise ValueError("sample_count must be positive")
    dictionary = dictionary or {}
    pieces: list[tuple[str, str, float, float, float]] = []
    index = 0
    while index < len(chars):
        char, start, end = chars[index]
        lowered = char.lower()
        if not lowered.isalpha():
            index += 1
            continue
        # Read ahead to the end of the word so the dictionary and digraphs can see it.
        stop = index
        while stop < len(chars) and chars[stop][0].isalpha():
            stop += 1
        word = "".join(item[0].lower() for item in chars[index:stop])
        if word in dictionary:
            pieces.append((word, dictionary[word], start, chars[stop - 1][2], 0.95))
            index = stop
            continue
        position = index
        while position < stop:
            letter = chars[position][0].lower()
            begin, finish = chars[position][1], chars[position][2]
            following = chars[position + 1][0].lower() if position + 1 < stop else ""
            if letter == "t" and following == "h":
                pieces.append(("th", "TH", begin, chars[position + 1][2], 0.9))
                position += 2
                continue
            if letter == "e" and position == stop - 1 and stop - index > 2:
                # A final e is usually silent. Let the shape before it hold.
                position += 1
                continue
            pieces.append((letter, TIMED_LETTERS.get(letter, "rest"), begin, finish, 0.85))
            position += 1
        index = stop

    spans: list[AlignmentSpan] = []

    def push(label: str, phoneme: str, start: float, end: float, confidence: float) -> None:
        first = max(0, min(sample_count - 1, int(start * sample_rate)))
        last = max(first + 1, min(sample_count, int(end * sample_rate)))
        if spans and spans[-1].end_sample > first:
            first = spans[-1].end_sample
            if first >= sample_count:
                return
            last = max(first + 1, last)
        if spans and spans[-1].phoneme == phoneme and spans[-1].end_sample == first:
            merged = spans.pop()
            spans.append(merged.model_copy(update={"end_sample": last, "text": merged.text + label}))
            return
        spans.append(
            AlignmentSpan(start_sample=first, end_sample=last, text=label, phoneme=phoneme, confidence=confidence)
        )

    cursor = 0.0
    for label, phoneme, start, end, confidence in pieces:
        if start - cursor >= PAUSE_SECONDS:
            push("-", "rest", cursor, start, 1.0)
        push(label, phoneme, start, max(end, start + 1 / sample_rate), confidence)
        cursor = max(cursor, end)
    total = sample_count / sample_rate
    if total - cursor >= PAUSE_SECONDS / 2 or not spans:
        push("-", "rest", cursor, total, 1.0)
    return spans
