"""Cuervo Animation IR v0."""

from cuervo_ir.frame_time import frame_to_sample_start, sample_to_frame
from cuervo_ir.models import Episode, TimingPatch
from cuervo_ir.patch import PatchError, apply_timing_patch

__all__ = [
    "Episode",
    "PatchError",
    "TimingPatch",
    "apply_timing_patch",
    "frame_to_sample_start",
    "sample_to_frame",
]

__version__ = "0.1.0"
