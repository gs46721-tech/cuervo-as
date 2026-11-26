"""One agent turn. The agent works the episode by writing cues, like a person at a command line.

Each round it sends cues. Read cues come back with what they show. Edit cues
run against a working copy, and an edit that fails comes back as an error the
agent can fix. Nothing touches the real episode: the edits that held are
staged, one change per shot, with a sentence for each. The page shows those
sentences. It never shows a cue.
"""

from __future__ import annotations

import json
import time

from cuervo_ir.models import Episode
from cuervo_ir.providers.router import ModelRequest, ProviderError, ProviderRouter
from cuervo_edit import cues as cue_language
from cuervo_edit.cues import Cue, CueError
from cuervo_editor.store import (
    Change,
    EditorError,
    Session,
    SessionStore,
    Step,
    Thread,
    Turn,
    accept_change,
    cue_context,
    new_id,
)

MAX_ROUNDS = 6

SYSTEM = (
    "You are the crew of a 2D animation studio. A director gives you a note about an episode and you carry "
    "it out by typing cues into the studio's command line. Reply with cues only, one per line, and nothing "
    "else.\n\n"
    + cue_language.__doc__.split("\n\n", 1)[1]
    + "\n"
    "Frames in a shot start at 0. Use ids exactly as `show` prints them. Look before you change: `show` a "
    "shot before editing it unless it was already shown to you. A track or camera marked LOCKED cannot be "
    "changed, so do not try. Change only what the note asks for. If the director pinned shots, change only "
    "those. If a cue comes back with an error, fix it or leave it. If the note is a question, answer it in "
    "`done` and change nothing.\n\n"
    "End your last reply with `done \"...\"`: one or two plain sentences to the director about what you did "
    "or found. Speak as a colleague. Never mention cues, ids, tracks, or frames by number in that message; "
    "say shot numbers, character names, and seconds."
)


class Stopped(Exception):
    pass


def run_turn(session: Session, thread: Thread, turn: Turn, router: ProviderRouter, store: SessionStore) -> None:
    """Run a turn to the end. Model calls happen outside the session lock so the page can poll."""

    def check() -> None:
        if turn.turn_id in session.stop_requests:
            raise Stopped()

    def step(label: str, status: str = "done", detail: str = "") -> None:
        with session.lock:
            turn.steps.append(Step(label=label, detail=detail, status=status))  # type: ignore[arg-type]
            store.save(session)

    try:
        with session.lock:
            base = session.episode
            context = cue_context(session)
        working = base
        pinned = set(turn.shot_ids)
        focus = turn.focus_shot_id if _has_shot(base, turn.focus_shot_id) else None
        focus = next(iter(turn.shot_ids), focus) or base.scenes[0].shots[0].shot_id
        transcript: list[str] = []
        kept: dict[str, list[tuple[Cue, str]]] = {}
        failures: list[str] = []
        message = ""

        for round_number in range(MAX_ROUNDS):
            check()
            step("Thinking it through" if round_number == 0 else "Working on it", "running")
            try:
                response = router.complete(
                    ModelRequest(
                        step="editor_assist",
                        system=SYSTEM,
                        user=json.dumps(_brief(base, working, thread, turn, focus, transcript)),
                    ),
                    only=turn.provider,
                )
            except ProviderError as exc:
                _finish_step(session, turn, store, "failed", _plain(str(exc)))
                raise
            with session.lock:
                turn.steps.pop()
            try:
                cues = cue_language.parse(response.text)
            except CueError as exc:
                transcript.append(f"error: {exc}")
                continue
            if not cues:
                transcript.append('error: reply with cues only, and end with done "..."')
                continue
            finished = False
            looked = False
            for cue in cues:
                check()
                if cue.verb == "done":
                    message = " ".join(cue.args).strip()
                    finished = True
                    break
                if cue.verb in cue_language.READS:
                    looked = True
                    try:
                        shown = cue_language.read(working, cue)
                        step(_read_label(working, cue))
                    except CueError as exc:
                        shown = f"error: {exc}"
                    transcript.append(f"> {cue.text}\n{shown}")
                    continue
                shot_id = cue.shot_id or ""
                try:
                    if pinned and shot_id not in pinned:
                        raise CueError("The director pinned other shots. Change only those.")
                    label = cue_language.shot_label(working, shot_id).capitalize()
                    working, sentence = cue_language.apply(working, cue, context)
                    kept.setdefault(shot_id, []).append((cue, sentence))
                    step(sentence.rstrip("."), detail=label)
                    transcript.append(f"> {cue.text}\nok: {sentence}")
                except CueError as exc:
                    failures.append(str(exc))
                    step(str(exc).rstrip("."), "failed")
                    transcript.append(f"> {cue.text}\nerror: {exc}")
            if finished or not looked:
                break

        with session.lock:
            for shot_id, items in kept.items():
                change = Change(
                    change_id=new_id("chg"),
                    shot_id=shot_id,
                    instruction=turn.instruction,
                    cues=[cue.text for cue, _sentence in items],
                    summary=[sentence for _cue, sentence in items],
                    provider=response.provider,
                    model=response.model,
                )
                try:
                    before = _shot(base, shot_id)
                    change.base_revision = before.provenance.revision
                    after = _shot(working, shot_id) if _has_shot(working, shot_id) else None
                    change.grow = (after.duration_frames - before.duration_frames) if after else 0
                except EditorError as exc:
                    change.status = "failed"
                    change.error = str(exc)
                turn.changes.append(change)
            if turn.mode == "auto":
                for change in turn.changes:
                    if change.status != "pending":
                        continue
                    try:
                        accept_change(session, change)
                    except EditorError as exc:
                        change.status = "failed"
                        change.error = str(exc)
            turn.reply = message or _summary(turn, failures)
            if failures and not kept:
                # Nothing held, so the crew's sign-off would be wrong. Say what stopped it.
                turn.reply = failures[0]
            turn.status = "done"
    except Stopped:
        with session.lock:
            turn.status = "stopped"
            for item in turn.steps:
                if item.status == "running":
                    item.status = "failed"
    except Exception as exc:  # A turn must always end, whatever the provider did.
        with session.lock:
            turn.status = "failed"
            turn.error = _plain(str(exc))
    finally:
        with session.lock:
            turn.finished_at = time.time()
            session.stop_requests.discard(turn.turn_id)
            store.save(session)


def _brief(base: Episode, working: Episode, thread: Thread, turn: Turn, focus: str, transcript: list[str]) -> dict:
    """What the agent is handed each round: the note, where the director is looking, and the session so far."""

    shots = [shot for scene in base.scenes for shot in scene.shots]
    frames = sum(shot.duration_frames for shot in shots)
    scene = next(scene for scene in working.scenes if any(shot.shot_id == focus for shot in scene.shots)) if _has_shot(working, focus) else working.scenes[0]
    return {
        "note": turn.instruction,
        "pinned_shots": turn.shot_ids,
        "on_screen": focus,
        "episode": {
            "title": base.title,
            "fps": base.fps,
            "scenes": len(base.scenes),
            "shots": len(shots),
            "seconds": round(frames / base.fps, 1),
        },
        "earlier_notes": [
            {"note": earlier.instruction, "reply": earlier.reply}
            for earlier in thread.turns[-6:]
            if earlier.turn_id != turn.turn_id
        ],
        # Shown up front so a simple note takes one round.
        "current_scene": cue_language.read(working, Cue("shots", [scene.scene_id])),
        "current_shot": cue_language.describe(working, focus) if _has_shot(working, focus) else "",
        "session": "\n".join(transcript),
    }


def _read_label(episode: Episode, cue: Cue) -> str:
    if cue.verb == "show" and cue.args:
        return f"Looked at {cue_language.shot_label(episode, cue.args[0])}"
    if cue.verb == "find":
        return f'Searched the script for "{" ".join(cue.args)}"'
    if cue.verb == "shots":
        return "Looked through a scene"
    return "Looked over the episode"


def _summary(turn: Turn, failures: list[str]) -> str:
    drafted = [change for change in turn.changes if change.status in ("pending", "applied")]
    if not drafted:
        return failures[0] if failures else "Nothing to change."
    count = sum(len(change.summary) for change in drafted)
    verb = "Made" if turn.mode == "auto" else "Drafted"
    shots = "one shot" if len(drafted) == 1 else f"{len(drafted)} shots"
    return f"{verb} {count} {'change' if count == 1 else 'changes'} across {shots}."


def _plain(error: str) -> str:
    if "no provider completed" in error:
        return "No model account answered. Connect one in Accounts and keys."
    return error


def _finish_step(session: Session, turn: Turn, store: SessionStore, status: str, detail: str) -> None:
    with session.lock:
        if turn.steps:
            turn.steps[-1].status = status  # type: ignore[assignment]
            turn.steps[-1].detail = detail
        store.save(session)


def _has_shot(episode: Episode, shot_id: str | None) -> bool:
    return any(shot.shot_id == shot_id for scene in episode.scenes for shot in scene.shots)


def _shot(episode: Episode, shot_id: str):
    for scene in episode.scenes:
        for shot in scene.shots:
            if shot.shot_id == shot_id:
                return shot
    raise EditorError(f"unknown shot {shot_id}")
