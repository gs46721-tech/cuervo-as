"""One agent turn: decide which shots a direction touches, then draft a typed patch per shot.

The agent never writes the episode on its own in review mode. It stages
changes on the turn and the person accepts or rejects each one.
"""

from __future__ import annotations

import json
import time

from pydantic import BaseModel, ConfigDict, Field

from cuervo_ir.models import Episode
from cuervo_ir.providers.router import ModelRequest, ProviderError, ProviderRouter
from cuervo_edit.propose import _strip_fence, request_edit
from cuervo_editor.store import (
    Change,
    EditorError,
    Session,
    SessionStore,
    Step,
    Thread,
    Turn,
    accept_change,
    new_id,
    stage_change,
    summarize,
)

PLAN_SYSTEM = (
    "You assist a director in a 2D animation editor. Read the direction and the episode. "
    "Decide which shots it applies to and write one concrete instruction per shot. Each "
    "instruction may change timing, the pose on an existing track, or the camera of that "
    "shot. Nothing else can be edited. If the direction is a question, or needs no edit, "
    "answer it in `reply` and return no edits. Never invent shot ids. A long episode lists only the "
    "current scene in full. `other_scenes` names the rest, and their shot ids are valid targets. Return only JSON: "
    '{"reply": string, "edits": [{"shot_id": string, "instruction": string}]}. '
    "`reply` is one or two plain sentences for the director."
)


LARGE_EPISODE_SHOTS = 60


class PlannedEdit(BaseModel):
    model_config = ConfigDict(extra="ignore")

    shot_id: str
    instruction: str = Field(min_length=1)


class TurnPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reply: str = ""
    edits: list[PlannedEdit] = Field(default_factory=list)


class Stopped(Exception):
    pass


def plan_turn(
    episode: Episode,
    thread: Thread,
    turn: Turn,
    router: ProviderRouter,
) -> tuple[TurnPlan, str]:
    """Ask the `editor_assist` route where the direction lands. Returns the plan and who wrote it."""

    view = summarize(episode)
    shots = view["shots"]
    elsewhere: list[dict] = []
    if len(shots) > LARGE_EPISODE_SHOTS:
        # A full episode does not fit in one request. Send the scene on screen in full and the rest as an index.
        focus = next((shot["scene_id"] for shot in shots if shot["shot_id"] == turn.focus_shot_id), shots[0]["scene_id"])
        elsewhere = [
            {
                "scene_id": scene["scene_id"],
                "title": scene["title"],
                "shot_ids": [shot["shot_id"] for shot in shots if shot["scene_id"] == scene["scene_id"]],
            }
            for scene in view["scenes"]
            if scene["scene_id"] != focus
        ]
        shots = [shot for shot in shots if shot["scene_id"] == focus]
    history = [
        {"direction": earlier.instruction, "reply": earlier.reply}
        for earlier in thread.turns[-6:]
        if earlier.turn_id != turn.turn_id
    ]
    response = router.complete(
        ModelRequest(
            step="editor_assist",
            system=PLAN_SYSTEM,
            user=json.dumps(
                {
                    "instruction": turn.instruction,
                    "focus_shot_id": turn.focus_shot_id,
                    "history": history,
                    "episode": {
                        "title": view["title"],
                        "fps": view["fps"],
                        "shots": [
                            {
                                "shot_id": shot["shot_id"],
                                "scene_id": shot["scene_id"],
                                "start_frame": shot["start_frame"],
                                "duration_frames": shot["duration_frames"],
                                "camera_preset": shot["camera_preset"],
                                "framing": shot["framing"],
                                "actors": [actor["actor_id"] for actor in shot["actors"]],
                                "tracks": shot["tracks"],
                                "lines": [
                                    {"speaker": line["speaker_actor_id"], "text": line["text"]}
                                    for line in shot["lines"]
                                ],
                            }
                            for shot in shots
                        ],
                        "other_scenes": elsewhere,
                    },
                }
            ),
            response_schema=TurnPlan.model_json_schema(),
        ),
        only=turn.provider,
    )
    try:
        plan = TurnPlan.model_validate(json.loads(_strip_fence(response.text)))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise EditorError(f"{response.provider} did not return a plan") from exc
    known = {shot["shot_id"] for shot in view["shots"]}
    unknown = [edit.shot_id for edit in plan.edits if edit.shot_id not in known]
    if unknown:
        raise EditorError(f"{response.provider} planned an unknown shot: {', '.join(unknown)}")
    # One patch per shot: a second patch would be drafted against a revision the first one replaces.
    merged: dict[str, str] = {}
    for edit in plan.edits:
        merged[edit.shot_id] = f"{merged[edit.shot_id]} {edit.instruction}" if edit.shot_id in merged else edit.instruction
    plan.edits = [PlannedEdit(shot_id=shot_id, instruction=text) for shot_id, text in merged.items()]
    return plan, f"{response.provider} · {response.model}"


def run_turn(session: Session, thread: Thread, turn: Turn, router: ProviderRouter, store: SessionStore) -> None:
    """Run a turn to the end. Model calls happen outside the session lock so the page can poll."""

    def check() -> None:
        if turn.turn_id in session.stop_requests:
            raise Stopped()

    def begin(label: str, detail: str = "") -> Step:
        with session.lock:
            step = Step(label=label, detail=detail)
            turn.steps.append(step)
            store.save(session)
        return step

    def end(step: Step, status: str = "done", detail: str | None = None) -> None:
        with session.lock:
            step.status = status  # type: ignore[assignment]
            if detail is not None:
                step.detail = detail
            store.save(session)

    try:
        shot_ids = [shot.shot_id for scene in session.episode.scenes for shot in scene.shots]
        if turn.shot_ids:
            targets = [(shot_id, turn.instruction) for shot_id in turn.shot_ids]
        elif len(shot_ids) == 1:
            targets = [(shot_ids[0], turn.instruction)]
        else:
            step = begin("Reading the episode", f"{len(shot_ids)} shots")
            try:
                plan, source = plan_turn(session.episode, thread, turn, router)
            except (ProviderError, EditorError) as exc:
                end(step, "failed", str(exc))
                raise
            targets = [(edit.shot_id, edit.instruction) for edit in plan.edits]
            with session.lock:
                turn.reply = plan.reply
            end(step, detail=f"{source} · {_count(len(targets), 'shot')} to change")

        for shot_id, instruction in targets:
            check()
            step = begin(f"Drafting a patch for {shot_id}", instruction)
            change = Change(change_id=new_id("chg"), shot_id=shot_id, instruction=instruction)
            try:
                patch, response = request_edit(session.episode, shot_id, instruction, router, only=turn.provider)
                with session.lock:
                    change.provider = response.provider
                    change.model = response.model
                    stage_change(session, change, patch)
                end(step, detail=f"{response.provider} · {response.model} · {_count(len(change.diff), 'field')}")
            except (ProviderError, ValueError) as exc:
                change.status = "failed"
                change.error = str(exc)
                end(step, "failed", str(exc))
            with session.lock:
                turn.changes.append(change)
                store.save(session)

        check()
        if turn.mode == "auto":
            with session.lock:
                for change in turn.changes:
                    if change.status != "pending":
                        continue
                    try:
                        accept_change(session, change)
                    except EditorError as exc:
                        change.status = "failed"
                        change.error = str(exc)
        with session.lock:
            turn.status = "done"
            if not turn.reply:
                turn.reply = _summary(turn)
    except Stopped:
        with session.lock:
            turn.status = "stopped"
            for step in turn.steps:
                if step.status == "running":
                    step.status = "failed"
    except Exception as exc:  # A turn must always end, whatever the provider did.
        with session.lock:
            turn.status = "failed"
            turn.error = str(exc)
    finally:
        with session.lock:
            turn.finished_at = time.time()
            session.stop_requests.discard(turn.turn_id)
            store.save(session)


def _summary(turn: Turn) -> str:
    drafted = [change for change in turn.changes if change.status in ("pending", "applied")]
    failed = [change for change in turn.changes if change.status == "failed"]
    if not turn.changes:
        return "Nothing to change."
    parts = []
    if drafted:
        verb = "Applied" if turn.mode == "auto" else "Drafted"
        parts.append(f"{verb} {_count(len(drafted), 'change')} on {', '.join(change.shot_id for change in drafted)}.")
    if failed:
        parts.append(f"{_count(len(failed), 'shot')} could not be changed.")
    return " ".join(parts)


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"
