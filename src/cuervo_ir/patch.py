"""Apply a timing patch to one shot.

The patch may change the named tracks' frame bounds and the shot duration.
When the shot grows, later shots in the same scene keep their contents and
move later by the same frame count. Nothing else changes.
"""

from __future__ import annotations

from pydantic import ValidationError

from cuervo_ir.models import Episode, TimingPatch


class PatchError(ValueError):
    pass


def apply_timing_patch(episode: Episode, patch: TimingPatch) -> Episode:
    data = episode.model_dump(mode="json")
    found = _find_shot(data, patch.target_shot_id)
    if found is None:
        raise PatchError(f"unknown shot {patch.target_shot_id}")
    scene, shot = found
    if shot["provenance"]["revision"] != patch.base_revision:
        raise PatchError(
            f"{patch.target_shot_id} is at {shot['provenance']['revision']}, not {patch.base_revision}"
        )

    tracks = {track["track_id"]: track for track in shot["action_tracks"]}
    locks = {lock["target_track_id"]: set(lock["properties"]) for lock in shot["locks"]}
    for delta in patch.timing:
        track = tracks.get(delta.track_id)
        if track is None:
            raise PatchError(f"{delta.track_id} is not an action track on {patch.target_shot_id}")
        if "timing" in locks.get(delta.track_id, set()):
            raise PatchError(f"{delta.track_id} timing is locked")
        track["start_frame"] += delta.start_delta_frames
        track["end_frame"] += delta.end_delta_frames
        if track["start_frame"] < 0:
            raise PatchError(f"{delta.track_id} start_frame would be negative")

    grow = patch.extend_shot_frames
    original_end = shot["start_frame"] + shot["duration_frames"]
    shot["duration_frames"] += grow
    shot["provenance"]["parent_revision"] = shot["provenance"]["revision"]
    shot["provenance"]["revision"] = _next_revision(shot["provenance"]["revision"])
    shot["provenance"]["source"] = patch.patch_id
    shot["provenance"]["note"] = patch.reason
    if grow:
        scene["target_runtime_frames"] += grow
        for later in scene["shots"]:
            if later["shot_id"] == shot["shot_id"]:
                continue
            if later["start_frame"] >= original_end:
                later["start_frame"] += grow

    try:
        return Episode.model_validate(data)
    except ValidationError as exc:
        raise PatchError(str(exc)) from exc


def _find_shot(data: dict, shot_id: str):
    matches = []
    for scene in data["scenes"]:
        for shot in scene["shots"]:
            if shot["shot_id"] == shot_id:
                matches.append((scene, shot))
    if len(matches) > 1:
        raise PatchError(f"duplicate shot id {shot_id}")
    if not matches:
        return None
    return matches[0]


def _next_revision(revision: str) -> str:
    number = int(revision.removeprefix("rev-")) + 1
    width = max(4, len(revision.removeprefix("rev-")))
    return f"rev-{number:0{width}d}"
