"""In-memory editor sessions. An episode is whatever JSON the caller uploaded."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from cuervo_ir.models import Episode, LockProperty
from cuervo_edit.edits import EditError, EditPatch, affected, apply_edit


class EditorError(ValueError):
    pass


@dataclass
class Session:
    episode: Episode
    past: list[dict] = field(default_factory=list)
    future: list[dict] = field(default_factory=list)
    pending: EditPatch | None = None
    poses: dict[str, dict[str, float]] | None = None


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def open(self, episode: Episode, poses: dict | None = None) -> tuple[str, Session]:
        session_id = uuid.uuid4().hex
        session = Session(episode=episode, poses=poses)
        self._sessions[session_id] = session
        return session_id, session

    def get(self, session_id: str) -> Session:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise EditorError("unknown session") from exc


def summarize(episode: Episode) -> dict:
    return {
        "episode_id": episode.episode_id,
        "title": episode.title,
        "fps": episode.fps,
        "characters": [
            {"asset_id": item.asset_id, "display_name": item.display_name}
            for item in episode.assets.characters
        ],
        "backgrounds": [
            {"asset_id": item.asset_id, "display_name": item.display_name}
            for item in episode.assets.backgrounds
        ],
        "props": [
            {"asset_id": item.asset_id, "display_name": item.display_name} for item in episode.assets.props
        ],
        "shots": [_shot_summary(shot) for scene in episode.scenes for shot in scene.shots],
        "lines": [
            {
                "shot_id": shot.shot_id,
                "speaker_actor_id": line.speaker_actor_id,
                "text": line.text,
                "start_frame": line.start_frame,
                "end_frame": line.end_frame,
            }
            for scene in episode.scenes
            for shot in scene.shots
            for line in shot.dialogue_tracks
        ],
    }


def diff_lines(before: Episode, after: Episode, shot_id: str) -> list[str]:
    previous = _find(before, shot_id)
    revised = _find(after, shot_id)
    lines: list[str] = []
    if previous.duration_frames != revised.duration_frames:
        lines.append(f"duration {previous.duration_frames} -> {revised.duration_frames}")
    if previous.camera.model_dump() != revised.camera.model_dump():
        lines.append(f"camera {previous.camera.preset} -> {revised.camera.preset}")
    before_tracks = {track.track_id: track.model_dump() for track in previous.action_tracks}
    for track in revised.action_tracks:
        if before_tracks.get(track.track_id) != track.model_dump():
            lines.append(f"{track.track_id} changed")
    if len(before.scenes) == len(after.scenes):
        for left, right in zip(before.scenes, after.scenes):
            for old, new in zip(left.shots, right.shots):
                if old.shot_id == shot_id:
                    continue
                if old.start_frame != new.start_frame:
                    lines.append(f"{new.shot_id} starts at {new.start_frame}")
    return lines


def lock_track(episode: Episode, shot_id: str, track_id: str, properties: list[LockProperty]) -> Episode:
    if not properties:
        raise EditorError("lock needs a property")
    data = episode.model_dump(mode="json")
    shot = _find_data(data, shot_id)
    known = {track["track_id"] for track in shot["action_tracks"]}
    known.update(track["track_id"] for track in shot["dialogue_tracks"])
    if track_id not in known:
        raise EditorError(f"unknown track {track_id}")
    shot["locks"].append(
        {
            "lock_id": f"lock_{track_id}_{len(shot['locks'])}",
            "target_track_id": track_id,
            "properties": properties,
        }
    )
    shot["provenance"]["parent_revision"] = shot["provenance"]["revision"]
    shot["provenance"]["revision"] = _next_revision(shot["provenance"]["revision"])
    shot["provenance"]["source"] = "editor"
    shot["provenance"]["note"] = f"lock {track_id}"
    try:
        return Episode.model_validate(data)
    except Exception as exc:
        raise EditorError(str(exc)) from exc


def snapshot_push(session: Session, revised: Episode) -> None:
    session.past.append(session.episode.model_dump(mode="json"))
    session.future.clear()
    session.episode = revised
    session.pending = None


def undo(session: Session) -> None:
    if not session.past:
        raise EditorError("nothing to undo")
    session.future.append(session.episode.model_dump(mode="json"))
    session.episode = Episode.model_validate(session.past.pop())
    session.pending = None


def redo(session: Session) -> None:
    if not session.future:
        raise EditorError("nothing to redo")
    session.past.append(session.episode.model_dump(mode="json"))
    session.episode = Episode.model_validate(session.future.pop())
    session.pending = None


def dry_apply(session: Session, patch: EditPatch) -> tuple[Episode, list[str]]:
    try:
        revised = apply_edit(session.episode, patch)
    except Exception as exc:
        raise EditorError(str(exc)) from exc
    return revised, diff_lines(session.episode, revised, patch.target_shot_id)


def accept(session: Session) -> set[str]:
    if session.pending is None:
        raise EditorError("nothing to accept")
    names = affected(session.pending)
    revised, _lines = dry_apply(session, session.pending)
    snapshot_push(session, revised)
    return names


def _shot_summary(shot) -> dict:
    locks = {lock.target_track_id: lock.properties for lock in shot.locks}
    return {
        "shot_id": shot.shot_id,
        "scene_id": shot.scene_id,
        "start_frame": shot.start_frame,
        "duration_frames": shot.duration_frames,
        "revision": shot.provenance.revision,
        "camera_preset": shot.camera.preset,
        "framing": shot.camera.framing,
        "actors": [
            {"actor_id": actor.actor_id, "character_id": actor.character_id, "facing": actor.facing}
            for actor in shot.actors
        ],
        "assets": [
            {"role": ref.role, "asset_id": ref.asset_id, "version": ref.version} for ref in shot.asset_refs
        ],
        "tracks": [
            {
                "track_id": track.track_id,
                "kind": track.kind,
                "start_frame": track.start_frame,
                "end_frame": track.end_frame,
                "pose": track.keyframes[0].pose,
                "locks": locks.get(track.track_id, []),
            }
            for track in shot.action_tracks
        ],
    }


def _find(episode: Episode, shot_id: str):
    matches = [shot for scene in episode.scenes for shot in scene.shots if shot.shot_id == shot_id]
    if len(matches) != 1:
        raise EditorError(f"expected one shot {shot_id}")
    return matches[0]


def _find_data(data: dict, shot_id: str) -> dict:
    matches = [shot for scene in data["scenes"] for shot in scene["shots"] if shot["shot_id"] == shot_id]
    if len(matches) != 1:
        raise EditorError(f"expected one shot {shot_id}")
    return matches[0]


def _next_revision(revision: str) -> str:
    number = int(revision.removeprefix("rev-")) + 1
    width = max(4, len(revision.removeprefix("rev-")))
    return f"rev-{number:0{width}d}"
