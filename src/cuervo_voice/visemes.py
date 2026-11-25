"""Map aligned phonemes to a small viseme set with a coarticulation hold.

Mouth shape does not follow volume. The first frame of a new shape is a
partial weight so the jaw does not snap.
"""

from __future__ import annotations

from cuervo_ir.frame_time import sample_to_frame
from cuervo_ir.models import AlignmentSpan, DialogueTrack, Shot, VisemeKey

VISEMES = ("rest", "MBP", "FV", "TH", "AA", "EE", "OH", "L")

VISEME_MOUTH = {
    "rest": {"mouth": 0.05, "jaw": 0.0},
    "MBP": {"mouth": 0.0, "jaw": 0.0},
    "FV": {"mouth": 0.25, "jaw": 0.1},
    "TH": {"mouth": 0.35, "jaw": 0.15},
    "AA": {"mouth": 0.9, "jaw": 0.8},
    "EE": {"mouth": 0.45, "jaw": 0.25},
    "OH": {"mouth": 0.7, "jaw": 0.55},
    "L": {"mouth": 0.3, "jaw": 0.2},
}

COARTICULATION_WEIGHT = 0.45


def viseme_for(phoneme: str) -> str:
    return phoneme if phoneme in VISEME_MOUTH else "rest"


def viseme_keys(
    track: DialogueTrack,
    spans: list[AlignmentSpan],
    *,
    sample_rate: int,
    fps: int,
) -> list[VisemeKey]:
    keys: list[VisemeKey] = []
    previous: str | None = None
    for span in spans:
        local = sample_to_frame(span.start_sample, sample_rate, fps)
        frame = min(track.end_frame - 1, track.start_frame + local)
        viseme = viseme_for(span.phoneme)
        weight = COARTICULATION_WEIGHT if previous not in (None, viseme) else 1.0
        if keys and keys[-1].frame == frame:
            keys[-1] = VisemeKey(frame=frame, viseme=viseme, weight=weight)
        else:
            keys.append(VisemeKey(frame=frame, viseme=viseme, weight=weight))
        previous = viseme
    return keys


def viseme_at(shot: Shot, actor_id: str, frame: int):
    chosen = None
    for track in shot.dialogue_tracks:
        if track.speaker_actor_id != actor_id:
            continue
        if frame < track.start_frame or frame >= track.end_frame:
            continue
        for key in track.visemes:
            if key.frame <= frame:
                chosen = (key.viseme, key.weight)
    return chosen
