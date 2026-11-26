"""Editor projects. A project is one uploaded episode, its history, and its agent threads.

Nothing here knows a series. With a home directory, every project is also a
JSON file there, so a restart does not lose the conversation.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from cuervo_ir.models import Episode, LockProperty
from cuervo_edit.edits import EditPatch, affected, apply_edit


class EditorError(ValueError):
    pass


ChangeStatus = Literal["pending", "applied", "rejected", "failed", "discarded"]
TurnStatus = Literal["running", "done", "failed", "stopped"]
TurnMode = Literal["review", "auto"]


class Change(BaseModel):
    """One typed patch for one shot, proposed inside a turn."""

    change_id: str
    shot_id: str
    instruction: str
    status: ChangeStatus = "pending"
    patch: dict | None = None
    diff: list[dict] = Field(default_factory=list)
    affected: list[str] = Field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    error: str | None = None
    # Length of the undo stack right after this change was applied.
    snapshot_index: int | None = None


class Step(BaseModel):
    label: str
    detail: str = ""
    status: Literal["running", "done", "failed"] = "running"


class Turn(BaseModel):
    turn_id: str
    instruction: str
    shot_ids: list[str] = Field(default_factory=list)
    focus_shot_id: str | None = None
    provider: str | None = None
    mode: TurnMode = "review"
    status: TurnStatus = "running"
    reply: str = ""
    error: str | None = None
    steps: list[Step] = Field(default_factory=list)
    changes: list[Change] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    finished_at: float | None = None


class Thread(BaseModel):
    thread_id: str
    title: str = "New thread"
    created_at: float = Field(default_factory=time.time)
    turns: list[Turn] = Field(default_factory=list)


class Session:
    def __init__(
        self,
        session_id: str,
        episode: Episode,
        poses: dict[str, dict[str, float]] | None = None,
    ) -> None:
        self.session_id = session_id
        self.episode = episode
        self.poses = poses
        # Folder of recorded voice takes, when the episode came from the pipeline.
        self.takes_dir: str | None = None
        self.past: list[dict] = []
        self.future: list[dict] = []
        # Goes up every time the episode changes, so a frame URL can be cached.
        self.version = 0
        self.threads: list[Thread] = []
        self.created_at = time.time()
        self.updated_at = self.created_at
        self.lock = threading.RLock()
        self.stop_requests: set[str] = set()

    def thread(self, thread_id: str) -> Thread:
        for thread in self.threads:
            if thread.thread_id == thread_id:
                return thread
        raise EditorError("unknown thread")

    def turn(self, turn_id: str) -> Turn:
        for thread in self.threads:
            for turn in thread.turns:
                if turn.turn_id == turn_id:
                    return turn
        raise EditorError("unknown turn")

    def change(self, change_id: str) -> Change:
        for thread in self.threads:
            for turn in thread.turns:
                for change in turn.changes:
                    if change.change_id == change_id:
                        return change
        raise EditorError("unknown change")

    def running(self) -> bool:
        return any(turn.status == "running" for thread in self.threads for turn in thread.turns)

    def to_json(self) -> dict:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "episode": self.episode.model_dump(mode="json"),
            "poses": self.poses,
            "takes_dir": self.takes_dir,
            "past": self.past,
            "future": self.future,
            "version": self.version,
            "threads": [thread.model_dump(mode="json") for thread in self.threads],
        }

    @classmethod
    def from_json(cls, data: dict) -> Session:
        session = cls(data["session_id"], Episode.model_validate(data["episode"]), data.get("poses"))
        session.created_at = data.get("created_at", session.created_at)
        session.updated_at = data.get("updated_at", session.created_at)
        session.takes_dir = data.get("takes_dir")
        session.past = list(data.get("past", []))
        session.future = list(data.get("future", []))
        session.version = int(data.get("version", 0))
        session.threads = [Thread.model_validate(item) for item in data.get("threads", [])]
        # A turn cannot still be running after a restart.
        for thread in session.threads:
            for turn in thread.turns:
                if turn.status == "running":
                    turn.status = "stopped"
                    turn.error = "The editor restarted before this turn finished."
                    for step in turn.steps:
                        if step.status == "running":
                            step.status = "failed"
        return session


class SessionStore:
    def __init__(self, home: Path | None = None) -> None:
        self._sessions: dict[str, Session] = {}
        self._home = home
        if home is None:
            return
        home.mkdir(parents=True, exist_ok=True)
        for path in sorted(home.glob("*.json")):
            try:
                session = Session.from_json(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                # A file this version cannot read stays on disk and out of the list.
                continue
            self._sessions[session.session_id] = session

    def open(self, episode: Episode, poses: dict | None = None) -> tuple[str, Session]:
        session = Session(uuid.uuid4().hex, episode, poses)
        self._sessions[session.session_id] = session
        self.save(session)
        return session.session_id, session

    def get(self, session_id: str) -> Session:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise EditorError("unknown session") from exc

    def all(self) -> list[Session]:
        return sorted(self._sessions.values(), key=lambda item: item.updated_at, reverse=True)

    def delete(self, session_id: str) -> None:
        self.get(session_id)
        del self._sessions[session_id]
        if self._home is not None:
            (self._home / f"{session_id}.json").unlink(missing_ok=True)

    def save(self, session: Session) -> None:
        with session.lock:
            session.updated_at = time.time()
            if self._home is None:
                return
            target = self._home / f"{session.session_id}.json"
            scratch = target.with_suffix(".tmp")
            scratch.write_text(json.dumps(session.to_json()), encoding="utf-8")
            scratch.replace(target)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Views


def session_view(session: Session) -> dict:
    return {
        "session_id": session.session_id,
        "episode": summarize(session.episode),
        "has_poses": bool(session.poses),
        "has_takes": bool(session.takes_dir),
        "version": session.version,
        "undo": len(session.past),
        "redo": len(session.future),
        "threads": [thread_view(session, thread) for thread in session.threads],
    }


def session_card(session: Session) -> dict:
    pending = sum(
        1
        for thread in session.threads
        for turn in thread.turns
        for change in turn.changes
        if change.status == "pending"
    )
    return {
        "session_id": session.session_id,
        "episode_id": session.episode.episode_id,
        "title": session.episode.title,
        "updated_at": session.updated_at,
        "threads": len(session.threads),
        "pending": pending,
        "running": session.running(),
    }


def thread_view(session: Session, thread: Thread) -> dict:
    return {
        "thread_id": thread.thread_id,
        "title": thread.title,
        "created_at": thread.created_at,
        "turns": [turn_view(session, turn) for turn in thread.turns],
    }


def turn_view(session: Session, turn: Turn) -> dict:
    data = turn.model_dump(mode="json")
    data["changes"] = [change_view(session, change) for change in turn.changes]
    return data


def change_view(session: Session, change: Change) -> dict:
    """`state` is what the page shows: an applied change that was undone reads `undone`."""

    data = change.model_dump(mode="json")
    state: str = change.status
    stale = False
    if change.status == "applied" and (change.snapshot_index or 0) > len(session.past):
        state = "undone"
    if change.status == "pending" and change.patch is not None:
        try:
            current = _find(session.episode, change.shot_id).provenance.revision
            stale = current != change.patch.get("base_revision")
        except EditorError:
            stale = True
    data["state"] = state
    data["stale"] = stale
    return data


def summarize(episode: Episode) -> dict:
    # Shot frames are local to their scene. The page wants one episode clock.
    shots = []
    scenes = []
    offset = 0
    for scene in episode.scenes:
        length = max((shot.start_frame + shot.duration_frames for shot in scene.shots), default=0)
        scenes.append(
            {
                "scene_id": scene.scene_id,
                "title": scene.title,
                "objective": scene.objective,
                "start_frame": offset,
                "duration_frames": length,
            }
        )
        for shot in scene.shots:
            summary = _shot_summary(shot)
            summary["start_frame"] += offset
            shots.append(summary)
        offset += length
    return {
        "episode_id": episode.episode_id,
        "title": episode.title,
        "fps": episode.fps,
        "total_frames": max((shot["start_frame"] + shot["duration_frames"] for shot in shots), default=0),
        "scenes": scenes,
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
        "shots": shots,
        "lines": [
            {**line, "shot_id": shot["shot_id"]} for shot in shots for line in shot["lines"]
        ],
    }


def _shot_summary(shot) -> dict:
    locks: dict[str, list[str]] = {}
    for lock in shot.locks:
        merged = locks.setdefault(lock.target_track_id, [])
        merged.extend(item for item in lock.properties if item not in merged)
    return {
        "shot_id": shot.shot_id,
        "scene_id": shot.scene_id,
        "start_frame": shot.start_frame,
        "duration_frames": shot.duration_frames,
        "revision": shot.provenance.revision,
        "note": shot.provenance.note,
        "camera_preset": shot.camera.preset,
        "camera_x": shot.camera.transform.x,
        "camera_y": shot.camera.transform.y,
        "camera_locked": any("camera" in properties for properties in locks.values()),
        "has_voice": any(line.voice_take_id for line in shot.dialogue_tracks),
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
                "actor_id": track.target_actor_id,
                "start_frame": track.start_frame,
                "end_frame": track.end_frame,
                "pose": track.keyframes[0].pose,
                "locks": locks.get(track.track_id, []),
            }
            for track in shot.action_tracks
        ],
        "lines": [
            {
                "track_id": line.track_id,
                "speaker_actor_id": line.speaker_actor_id,
                "text": line.text,
                "start_frame": line.start_frame,
                "end_frame": line.end_frame,
                "locks": locks.get(line.track_id, []),
            }
            for line in shot.dialogue_tracks
        ],
    }


# ---------------------------------------------------------------------------
# Diffs


def diff_rows(before: Episode, after: Episode, shot_id: str) -> list[dict]:
    """What a patch would change, as `{target, field, before, after}` rows."""

    previous = _find(before, shot_id)
    revised = _find(after, shot_id)
    rows: list[dict] = []

    def row(target: str, name: str, old, new) -> None:
        if old != new:
            rows.append({"target": target, "field": name, "before": str(old), "after": str(new)})

    row(shot_id, "duration", f"{previous.duration_frames}f", f"{revised.duration_frames}f")
    row("camera", "preset", previous.camera.preset, revised.camera.preset)
    row("camera", "x", _number(previous.camera.transform.x), _number(revised.camera.transform.x))
    row("camera", "y", _number(previous.camera.transform.y), _number(revised.camera.transform.y))
    before_tracks = {track.track_id: track for track in previous.action_tracks}
    for track in revised.action_tracks:
        old = before_tracks.get(track.track_id)
        if old is None:
            continue
        row(track.track_id, "pose", old.keyframes[0].pose, track.keyframes[0].pose)
        row(
            track.track_id,
            "frames",
            f"{old.start_frame}–{old.end_frame}",
            f"{track.start_frame}–{track.end_frame}",
        )
    starts = {shot.shot_id: shot.start_frame for scene in before.scenes for shot in scene.shots}
    for scene in after.scenes:
        for shot in scene.shots:
            if shot.shot_id != shot_id and shot.shot_id in starts:
                row(shot.shot_id, "start", f"f{starts[shot.shot_id]}", f"f{shot.start_frame}")
    return rows


def _number(value: float) -> str:
    return f"{value:g}"


# ---------------------------------------------------------------------------
# History


def set_locks(episode: Episode, shot_id: str, track_id: str, properties: list[LockProperty]) -> Episode:
    """Replace the locks on one track. An empty list unlocks it."""

    data = episode.model_dump(mode="json")
    shot = _find_data(data, shot_id)
    known = {track["track_id"] for track in shot["action_tracks"]}
    known.update(track["track_id"] for track in shot["dialogue_tracks"])
    if track_id not in known:
        raise EditorError(f"unknown track {track_id}")
    shot["locks"] = [lock for lock in shot["locks"] if lock["target_track_id"] != track_id]
    if properties:
        taken = {lock["lock_id"] for lock in shot["locks"]}
        lock_id = f"lock_{track_id}"
        while lock_id in taken:
            lock_id += "_x"
        shot["locks"].append(
            {"lock_id": lock_id[:64], "target_track_id": track_id, "properties": list(dict.fromkeys(properties))}
        )
    shot["provenance"]["parent_revision"] = shot["provenance"]["revision"]
    shot["provenance"]["revision"] = _next_revision(shot["provenance"]["revision"])
    shot["provenance"]["source"] = "editor"
    shot["provenance"]["note"] = f"{'lock' if properties else 'unlock'} {track_id}"
    try:
        return Episode.model_validate(data)
    except Exception as exc:
        raise EditorError(str(exc)) from exc


def snapshot_push(session: Session, revised: Episode) -> None:
    # A new edit drops the redo stack, so changes waiting there can never come back.
    for thread in session.threads:
        for turn in thread.turns:
            for change in turn.changes:
                if change.status == "applied" and (change.snapshot_index or 0) > len(session.past):
                    change.status = "discarded"
    session.past.append(session.episode.model_dump(mode="json"))
    session.future.clear()
    session.episode = revised
    session.version += 1


def undo(session: Session) -> None:
    if not session.past:
        raise EditorError("nothing to undo")
    session.future.append(session.episode.model_dump(mode="json"))
    session.episode = Episode.model_validate(session.past.pop())
    session.version += 1


def redo(session: Session) -> None:
    if not session.future:
        raise EditorError("nothing to redo")
    session.past.append(session.episode.model_dump(mode="json"))
    session.episode = Episode.model_validate(session.future.pop())
    session.version += 1


def dry_apply(session: Session, patch: EditPatch) -> tuple[Episode, list[dict]]:
    try:
        revised = apply_edit(session.episode, patch)
    except Exception as exc:
        raise EditorError(str(exc)) from exc
    return revised, diff_rows(session.episode, revised, patch.target_shot_id)


def stage_change(session: Session, change: Change, patch: EditPatch) -> None:
    """Record a patch on a change after checking that it applies. Nothing is written yet."""

    _revised, rows = dry_apply(session, patch)
    change.patch = patch.model_dump(mode="json")
    change.diff = rows
    change.affected = sorted(affected(patch))


def accept_change(session: Session, change: Change) -> None:
    if change.status != "pending" or change.patch is None:
        raise EditorError("this change is not waiting for review")
    revised, _rows = dry_apply(session, EditPatch.model_validate(change.patch))
    snapshot_push(session, revised)
    change.status = "applied"
    change.snapshot_index = len(session.past)


def reject_change(change: Change) -> None:
    if change.status != "pending":
        raise EditorError("this change is not waiting for review")
    change.status = "rejected"


def revert_turn(session: Session, turn: Turn) -> int:
    """Undo back to the state before this turn's first applied change. Redo brings it back."""

    marks = [
        change.snapshot_index
        for change in turn.changes
        if change.status == "applied" and change.snapshot_index and change.snapshot_index <= len(session.past)
    ]
    if not marks:
        raise EditorError("this turn has nothing applied")
    steps = 0
    while len(session.past) >= min(marks):
        undo(session)
        steps += 1
    return steps


def find_shot(episode: Episode, shot_id: str):
    return _find(episode, shot_id)


def _find(episode: Episode, shot_id: str):
    matches = [shot for scene in episode.scenes for shot in scene.shots if shot.shot_id == shot_id]
    if len(matches) != 1:
        raise EditorError(f"unknown shot {shot_id}")
    return matches[0]


def _find_data(data: dict, shot_id: str) -> dict:
    matches = [shot for scene in data["scenes"] for shot in scene["shots"] if shot["shot_id"] == shot_id]
    if len(matches) != 1:
        raise EditorError(f"unknown shot {shot_id}")
    return matches[0]


def _next_revision(revision: str) -> str:
    number = int(revision.removeprefix("rev-")) + 1
    width = max(4, len(revision.removeprefix("rev-")))
    return f"rev-{number:0{width}d}"
