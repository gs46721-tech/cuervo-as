"""Stage 2, storyboard. Cut each scene into shots and decide who each shot is on.

The `direction` route proposes the cut. Its answer must cover every line once
and in order. If it does not, that scene is boarded by a plain shot grammar
instead, so a long episode never stalls on one bad reply.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cuervo_ir.models import CameraPreset, Id
from cuervo_ir.providers.router import ModelRequest, ProviderError, ProviderRouter
from cuervo_pipeline.screenplay import Script, ScriptScene
from cuervo_pipeline.series import SeriesKit

# The most characters one scene stages at once.
MAX_CAST = 4


class BoardLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_id: Id
    character_id: Id
    text: str = Field(min_length=1)
    direction: str = ""


class BoardShot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_id: Id
    preset: CameraPreset
    framing: str = Field(min_length=1)
    # The character the camera favors. None frames the whole cast.
    focus: Id | None = None
    lines: list[BoardLine] = Field(default_factory=list)
    action: str = ""


class BoardScene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: Id
    title: str
    set_id: Id
    objective: str
    emotional_trajectory: str
    cast: list[Id]
    # Who cut this scene: the model, or the fallback grammar.
    source: Literal["director", "grammar"]
    shots: list[BoardShot] = Field(min_length=1)


class Storyboard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["storyboard"] = "storyboard"
    title: str
    script_digest: str = ""
    scenes: list[BoardScene]

    def shot_count(self) -> int:
        return sum(len(scene.shots) for scene in self.scenes)


BOARD_SYSTEM = (
    "You storyboard one scene of a 2D animated sitcom. Cut it into shots. Return only JSON "
    '{"objective": string, "emotional_trajectory": string, "shots": [{"preset": string, "framing": string, '
    '"focus": string or null, "lines": [integer], "action": string}]}. '
    "preset is one of wide, two_shot, over_the_shoulder, close_up, reaction, insert. `lines` holds indexes "
    "from the given lines. Every line index appears exactly once, in order. A shot may have no lines: an "
    "establishing wide, or a silent reaction. `focus` is a character_id from the cast, or null for a wide or "
    "two_shot. Open on a wide. Cut to a close_up for a punchline. Give a joke a silent reaction after it. "
    "Keep one to three lines in a shot. Do not hold one shot longer than about ten seconds of talk."
)


def board_script(script: Script, kit: SeriesKit, router: ProviderRouter | None, *, log=None) -> Storyboard:
    scenes: list[BoardScene] = []
    counter = 0
    line_counter = 0
    for scene in script.scenes:
        cast = _cast(scene, kit)
        lines = [beat for beat in scene.beats if beat.kind == "line"]
        actions = [beat.text for beat in scene.beats if beat.kind == "action"]
        drafted = None
        note = ""
        if router is not None:
            try:
                drafted = _ask_director(scene, cast, kit, router)
            except (ProviderError, BoardError) as exc:
                note = str(exc)
        source: Literal["director", "grammar"] = "director" if drafted else "grammar"
        if drafted is None:
            drafted = {
                "objective": actions[0] if actions else scene.heading,
                "emotional_trajectory": "steady",
                "shots": _grammar(lines, cast, actions),
            }
            if log and note:
                log(f"  {scene.scene_id}: boarded by grammar ({note})")
        shots: list[BoardShot] = []
        for item in drafted["shots"]:
            counter += 1
            shot_lines = []
            for index in item["lines"]:
                line_counter += 1
                beat = lines[index]
                shot_lines.append(
                    BoardLine(
                        line_id=f"ln_{line_counter:04d}",
                        character_id=beat.character_id or cast[0],
                        text=beat.text,
                        direction=beat.direction,
                    )
                )
            shots.append(
                BoardShot(
                    shot_id=f"sh_{counter:04d}",
                    preset=item["preset"],
                    framing=item["framing"],
                    focus=item["focus"],
                    lines=shot_lines,
                    action=item.get("action", ""),
                )
            )
        scenes.append(
            BoardScene(
                scene_id=scene.scene_id,
                title=scene.heading,
                set_id=scene.set_id,
                objective=str(drafted["objective"]) or scene.heading,
                emotional_trajectory=str(drafted["emotional_trajectory"]) or "steady",
                cast=cast,
                source=source,
                shots=shots,
            )
        )
    return Storyboard(title=script.title, scenes=scenes)


class BoardError(ValueError):
    pass


def _cast(scene: ScriptScene, kit: SeriesKit) -> list[str]:
    seen: list[str] = []
    for beat in scene.beats:
        if beat.kind == "line" and beat.character_id and beat.character_id not in seen:
            seen.append(beat.character_id)
    if not seen:
        # A silent scene still needs someone on stage: whoever the action names, else the lead.
        text = " ".join(beat.text for beat in scene.beats).lower()
        seen = [item.asset_id for item in kit.characters if item.display_name.split()[0].lower() in text]
        seen = seen or [kit.characters[0].asset_id]
    # Kit order, so a character stands on the same side in every scene.
    order = [item.asset_id for item in kit.characters]
    return sorted(seen[:MAX_CAST], key=order.index)


def _ask_director(scene: ScriptScene, cast: list[str], kit: SeriesKit, router: ProviderRouter) -> dict:
    lines = [beat for beat in scene.beats if beat.kind == "line"]
    response = router.complete(
        ModelRequest(
            step="direction",
            system=BOARD_SYSTEM,
            user=json.dumps(
                {
                    "heading": scene.heading,
                    "cast": [{"character_id": item, "name": kit.character(item).display_name} for item in cast],
                    "beats": _numbered(scene),
                    "bible": kit.bible,
                }
            ),
        )
    )
    text = response.text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        body = json.loads(text)
        reply = _Reply.model_validate(body)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise BoardError(f"{response.provider} did not return a board") from exc
    covered = [index for shot in reply.shots for index in shot.lines]
    if covered != list(range(len(lines))):
        raise BoardError(f"{response.provider} did not cover every line once and in order")
    shots = []
    for shot in reply.shots:
        focus = shot.focus if shot.focus in cast else None
        if focus is None and shot.preset in ("close_up", "reaction", "insert", "over_the_shoulder"):
            # A tight shot has to be on someone. Take the speaker, else the lead.
            focus = lines[shot.lines[0]].character_id if shot.lines else cast[0]
        shots.append({"preset": shot.preset, "framing": shot.framing, "focus": focus, "lines": shot.lines, "action": shot.action})
    if not shots:
        raise BoardError(f"{response.provider} returned no shots")
    return {"objective": reply.objective, "emotional_trajectory": reply.emotional_trajectory, "shots": shots}


def _numbered(scene: ScriptScene) -> list[dict]:
    rows: list[dict] = []
    number = 0
    for beat in scene.beats:
        row: dict = {"kind": beat.kind, "text": beat.text}
        if beat.kind == "line":
            row.update({"line": number, "character_id": beat.character_id, "direction": beat.direction})
            number += 1
        rows.append(row)
    return rows


class _ReplyShot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    preset: CameraPreset
    framing: str = Field(min_length=1)
    focus: str | None = None
    lines: list[int] = Field(default_factory=list)
    action: str = ""


class _Reply(BaseModel):
    model_config = ConfigDict(extra="ignore")

    objective: str = ""
    emotional_trajectory: str = ""
    shots: list[_ReplyShot]


def _grammar(lines: list, cast: list[str], actions: list[str]) -> list[dict]:
    """A safe default cut: establish, cover the exchange, go close for emphasis, react, button."""

    group = "the cast" if len(cast) > 2 else "both" if len(cast) == 2 else "single"
    shots: list[dict] = [
        {"preset": "wide", "framing": f"establishing, {group}", "focus": None, "lines": [], "action": actions[0] if actions else ""}
    ]
    index = 0
    since_master = 0
    while index < len(lines):
        speaker = lines[index].character_id
        emphatic = lines[index].text.rstrip().endswith(("!", "?"))
        nxt = lines[index + 1] if index + 1 < len(lines) else None
        if len(cast) > 1 and (index == 0 or since_master >= 3) and nxt is not None and nxt.character_id != speaker:
            # Re-establish the pair with an exchange.
            shots.append({"preset": "two_shot", "framing": "exchange", "focus": None, "lines": [index, index + 1], "action": ""})
            index += 2
            since_master = 0
            continue
        take = [index]
        if nxt is not None and nxt.character_id == speaker and not emphatic:
            take.append(index + 1)
        shots.append({"preset": "close_up", "framing": "on the speaker", "focus": speaker, "lines": take, "action": ""})
        index += len(take)
        since_master += 1
        last = lines[take[-1]]
        if len(cast) > 1 and last.text.rstrip().endswith("!"):
            listener = next(item for item in cast if item != speaker)
            shots.append({"preset": "reaction", "framing": "silent reaction", "focus": listener, "lines": [], "action": ""})
    if lines and len(cast) > 1:
        listener = next(item for item in cast if item != lines[-1].character_id)
        if shots[-1]["preset"] != "reaction":
            shots.append({"preset": "reaction", "framing": "button", "focus": listener, "lines": [], "action": ""})
    return shots
