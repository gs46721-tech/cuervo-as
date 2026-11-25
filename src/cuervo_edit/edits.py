"""Typed edits for one shot.

The model proposes one of these patches. Applying it changes only the named
tracks, the camera, and, when the shot grows, the start time of later shots.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from cuervo_ir.models import CameraPreset, Episode, Id, Revision, TimingDelta, TimingPatch
from cuervo_ir.patch import PatchError, apply_timing_patch
from cuervo_runtime.draw import render_png


class EditError(ValueError):
    pass


class PoseEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    track_id: Id
    pose: Id


class CameraEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: CameraPreset | None = None
    x: float | None = None
    y: float | None = None

    @model_validator(mode="after")
    def not_empty(self) -> CameraEdit:
        if self.preset is None and self.x is None and self.y is None:
            raise ValueError("camera edit sets nothing")
        return self


class EditPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["edit_patch"]
    patch_id: Id
    target_shot_id: Id
    base_revision: Revision
    reason: str = Field(min_length=1)
    timing: list[TimingDelta] = Field(default_factory=list)
    extend_shot_frames: int = Field(default=0, ge=0)
    poses: list[PoseEdit] = Field(default_factory=list)
    camera: CameraEdit | None = None

    @model_validator(mode="after")
    def changes_something(self) -> EditPatch:
        if not self.timing and not self.poses and self.camera is None:
            raise ValueError("edit patch changes nothing")
        if self.extend_shot_frames and not self.timing:
            raise ValueError("extend_shot_frames requires a timing edit")
        return self


def affected(patch: EditPatch) -> set[str]:
    names = {f"track:{edit.track_id}" for edit in patch.poses}
    if patch.timing:
        names.update(f"track:{delta.track_id}" for delta in patch.timing)
        names.add("shot_duration")
        if patch.extend_shot_frames:
            names.add("later_shots")
    if patch.camera is not None:
        names.add("camera")
    return names


def apply_edit(episode: Episode, patch: EditPatch) -> Episode:
    current = episode
    if patch.poses or patch.camera is not None:
        current = _apply_posed_and_camera(current, patch)
    if not patch.timing:
        return _bump(current, patch)
    try:
        return apply_timing_patch(
            current,
            TimingPatch(
                kind="timing_patch",
                patch_id=patch.patch_id,
                target_shot_id=patch.target_shot_id,
                base_revision=patch.base_revision,
                reason=patch.reason,
                timing=patch.timing,
                extend_shot_frames=patch.extend_shot_frames,
            ),
        )
    except PatchError as exc:
        raise EditError(str(exc)) from exc


def preview_frame(
    episode: Episode,
    patch: EditPatch,
    frame: int,
    library: dict[str, dict[str, float]] | None = None,
) -> bytes:
    revised = apply_edit(episode, patch)
    shot = _shot(revised, patch.target_shot_id)
    return render_png(revised, shot, frame, library)


def _apply_posed_and_camera(episode: Episode, patch: EditPatch) -> Episode:
    data = episode.model_dump(mode="json")
    found = _find(data, patch.target_shot_id)
    if found is None:
        raise EditError(f"unknown shot {patch.target_shot_id}")
    _scene, shot = found
    if shot["provenance"]["revision"] != patch.base_revision:
        raise EditError(f"{patch.target_shot_id} is at {shot['provenance']['revision']}, not {patch.base_revision}")
    locks = {lock["target_track_id"]: set(lock["properties"]) for lock in shot["locks"]}
    tracks = {track["track_id"]: track for track in shot["action_tracks"]}
    for edit in patch.poses:
        track = tracks.get(edit.track_id)
        if track is None:
            raise EditError(f"{edit.track_id} is not an action track on {patch.target_shot_id}")
        if "pose" in locks.get(edit.track_id, set()):
            raise EditError(f"{edit.track_id} pose is locked")
        for key in track["keyframes"]:
            key["pose"] = edit.pose
    if patch.camera is not None:
        if patch.camera.preset is not None:
            shot["camera"]["preset"] = patch.camera.preset
        if patch.camera.x is not None:
            shot["camera"]["transform"]["x"] = patch.camera.x
        if patch.camera.y is not None:
            shot["camera"]["transform"]["y"] = patch.camera.y
    try:
        return Episode.model_validate(data)
    except ValidationError as exc:
        raise EditError(str(exc)) from exc


def _bump(episode: Episode, patch: EditPatch) -> Episode:
    data = episode.model_dump(mode="json")
    found = _find(data, patch.target_shot_id)
    if found is None:
        raise EditError(f"unknown shot {patch.target_shot_id}")
    _scene, shot = found
    shot["provenance"]["parent_revision"] = shot["provenance"]["revision"]
    shot["provenance"]["revision"] = _next_revision(shot["provenance"]["revision"])
    shot["provenance"]["source"] = patch.patch_id
    shot["provenance"]["note"] = patch.reason
    return Episode.model_validate(data)


def _shot(episode: Episode, shot_id: str):
    matches = [shot for scene in episode.scenes for shot in scene.shots if shot.shot_id == shot_id]
    if len(matches) != 1:
        raise EditError(f"expected one shot {shot_id}, found {len(matches)}")
    return matches[0]


def _find(data: dict, shot_id: str):
    matches = [
        (scene, shot)
        for scene in data["scenes"]
        for shot in scene["shots"]
        if shot["shot_id"] == shot_id
    ]
    if len(matches) > 1:
        raise EditError(f"duplicate shot id {shot_id}")
    return matches[0] if matches else None


def _next_revision(revision: str) -> str:
    number = int(revision.removeprefix("rev-")) + 1
    width = max(4, len(revision.removeprefix("rev-")))
    return f"rev-{number:0{width}d}"
