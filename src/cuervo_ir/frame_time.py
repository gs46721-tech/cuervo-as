"""Convert sample-accurate audio time to integer frame time.

Frame F covers the half-open sample range
[frame_to_sample_start(F), frame_to_sample_start(F + 1)).
Conversion uses integer arithmetic so it does not depend on binary floats.
"""

from __future__ import annotations


def sample_to_frame(sample_index: int, sample_rate: int, fps: int) -> int:
    if sample_index < 0:
        raise ValueError("sample_index must be >= 0")
    if sample_rate <= 0 or fps <= 0:
        raise ValueError("sample_rate and fps must be positive")
    return (sample_index * fps) // sample_rate


def frame_to_sample_start(frame: int, sample_rate: int, fps: int) -> int:
    if frame < 0:
        raise ValueError("frame must be >= 0")
    if sample_rate <= 0 or fps <= 0:
        raise ValueError("sample_rate and fps must be positive")
    return (frame * sample_rate) // fps
