"""Stage 1, script. Read a screenplay into scenes and beats, or draft one from a premise.

Reading is plain parsing, so a thirty-page script costs no model calls and
loses no lines. Drafting goes through the `writing` route, one scene at a time.
"""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from cuervo_ir.models import Id
from cuervo_ir.providers.router import ModelRequest, ProviderRouter
from cuervo_pipeline.series import SeriesKit, slug


class ScriptError(ValueError):
    pass


class Beat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["line", "action"]
    text: str = Field(min_length=1)
    character_id: Id | None = None
    # The parenthetical under a speaker cue.
    direction: str = ""


class ScriptScene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: Id
    heading: str
    set_id: Id
    beats: list[Beat]


class Script(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["script"] = "script"
    title: str
    scenes: list[ScriptScene]
    warnings: list[str] = Field(default_factory=list)

    def lines(self) -> list[Beat]:
        return [beat for scene in self.scenes for beat in scene.beats if beat.kind == "line"]


HEADING = re.compile(r"^(INT\.?/EXT\.?|INT\.?|EXT\.?|SCENE\b)[\s.:\-]", re.IGNORECASE)
TRANSITION = re.compile(r"^(FADE (IN|OUT)|CUT TO|DISSOLVE TO|SMASH CUT|THE END)\b.*$", re.IGNORECASE)
CUE_NOTE = re.compile(r"\s*\((V\.?O\.?|O\.?S\.?|O\.?C\.?|CONT'?D|CONTINUED)\)\s*", re.IGNORECASE)
# A sentence end to split a long speech on.
SENTENCE = re.compile(r"(?<=[.!?…])\s+")
MAX_LINE_CHARS = 220


def parse_screenplay(text: str, kit: SeriesKit) -> Script:
    """Scene headings, speaker cues, parentheticals, and action lines, in script order."""

    names: dict[str, str] = {}
    for character in kit.characters:
        for name in character.names():
            names.setdefault(name.strip().lower(), character.asset_id)
    scenes: list[ScriptScene] = []
    warnings: list[str] = []
    used: set[str] = set()

    def open_scene(heading: str) -> ScriptScene:
        set_id = _match_set(heading, kit)
        if set_id is None:
            set_id = kit.sets[0].asset_id
            if heading:
                warnings.append(f'No set in the kit matches "{heading}". Using {set_id}.')
        base = slug(heading or f"scene {len(scenes) + 1}", "sc")
        scene_id = base
        count = 2
        while scene_id in used:
            scene_id = f"{base[:44]}_{count}"
            count += 1
        used.add(scene_id)
        scene = ScriptScene(scene_id=scene_id, heading=heading or "Scene", set_id=set_id, beats=[])
        scenes.append(scene)
        return scene

    blocks = [block for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")) if block.strip()]
    current: ScriptScene | None = None
    for block in blocks:
        rows = [row.strip() for row in block.split("\n") if row.strip()]
        first = rows[0]
        if HEADING.match(first):
            current = open_scene(first)
            rows = rows[1:]
            if not rows:
                continue
            first = rows[0]
        if all(TRANSITION.match(row) for row in rows):
            continue
        if current is None:
            current = open_scene("")
        speaker, inline = _cue(first, names)
        if speaker is None and _looks_like_cue(first) and len(rows) > 1:
            raise ScriptError(f'Speaker "{first}" is not in the series kit. Add the character or an alias.')
        if speaker is None:
            current.beats.append(Beat(kind="action", text=" ".join(rows)))
            continue
        direction: list[str] = []
        spoken: list[str] = [inline] if inline else []
        for row in rows[1:]:
            if row.startswith("(") and row.endswith(")"):
                direction.append(row[1:-1].strip())
            else:
                spoken.append(row)
        speech = " ".join(spoken).strip()
        if not speech:
            warnings.append(f"{first} has a cue and no line in {current.scene_id}.")
            continue
        for index, part in enumerate(_split_speech(speech)):
            current.beats.append(
                Beat(kind="line", character_id=speaker, text=part, direction="; ".join(direction) if index == 0 else "")
            )
    scenes = [scene for scene in scenes if scene.beats]
    if not scenes:
        raise ScriptError("the script has no scenes with action or dialogue")
    return Script(title=kit.title, scenes=scenes, warnings=warnings)


def _match_set(heading: str, kit: SeriesKit) -> str | None:
    lowered = heading.lower()
    best: tuple[int, str] | None = None
    for item in kit.sets:
        for name in [item.display_name, *item.aliases]:
            if name.lower() in lowered and (best is None or len(name) > best[0]):
                best = (len(name), item.asset_id)
    return best[1] if best else None


def _cue(row: str, names: dict[str, str]) -> tuple[str | None, str]:
    """`ALEX`, `Alex:`, or `ALEX: the line` when the name is in the kit."""

    head, colon, rest = row.partition(":")
    candidate = CUE_NOTE.sub(" ", head).strip()
    speaker = names.get(candidate.lower())
    if speaker is None:
        return None, ""
    if colon:
        return speaker, rest.strip()
    if candidate.upper() == candidate and not rest:
        return speaker, ""
    return None, ""


def _looks_like_cue(row: str) -> bool:
    stripped = CUE_NOTE.sub(" ", row).strip().rstrip(":")
    letters = [char for char in stripped if char.isalpha()]
    return bool(letters) and stripped.upper() == stripped and len(stripped) <= 30 and len(stripped.split()) <= 3


def _split_speech(speech: str) -> list[str]:
    """Break a long speech at sentence ends so each line is one breath and one take."""

    if len(speech) <= MAX_LINE_CHARS:
        return [speech]
    parts: list[str] = []
    current = ""
    for sentence in SENTENCE.split(speech):
        if current and len(current) + len(sentence) + 1 > MAX_LINE_CHARS:
            parts.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        parts.append(current)
    return parts


# -- drafting ---------------------------------------------------------------

# Dialogue runs near this pace once pauses and silent shots are counted.
WORDS_PER_MINUTE = 130


def write_script(premise: str, kit: SeriesKit, minutes: float, router: ProviderRouter) -> str:
    """Draft a screenplay of about `minutes` from a premise. Outline first, then one scene per call."""

    if not premise.strip():
        raise ScriptError("the premise is empty")
    cast = [{"name": item.display_name.split()[0].upper(), "full_name": item.display_name} for item in kit.characters]
    sets = [item.display_name for item in kit.sets]
    outline = _json(
        router,
        "You outline one episode of an animated sitcom. Return only JSON "
        '{"scenes": [{"set": string, "summary": string, "seconds": integer}]}. '
        "Use only the listed cast and sets. Scenes run 60 to 240 seconds and their seconds sum to the target. "
        "Build a clear beginning, escalation, and ending.",
        {"premise": premise, "target_seconds": int(minutes * 60), "cast": cast, "sets": sets, "bible": kit.bible},
    )
    try:
        planned = [
            (str(item["set"]), str(item["summary"]), max(30, int(item["seconds"]))) for item in outline["scenes"]
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise ScriptError("the writing route did not return an outline") from exc
    if not planned:
        raise ScriptError("the outline has no scenes")
    pages: list[str] = []
    for index, (place, summary, seconds) in enumerate(planned):
        response = router.complete(
            ModelRequest(
                step="writing",
                system=(
                    "You write one scene of an animated sitcom as a screenplay. Start with a heading line "
                    "'INT. <SET> - DAY'. Put each speaker's name alone in capitals on its own line, with the line "
                    "below it. Put action in its own paragraphs. Separate every block with a blank line. Use only "
                    "the listed cast, by the given names. Keep speeches short. Return only the scene text."
                ),
                user=json.dumps(
                    {
                        "scene_number": index + 1,
                        "of": len(planned),
                        "set": place,
                        "summary": summary,
                        "target_words": int(seconds / 60 * WORDS_PER_MINUTE),
                        "cast": cast,
                        "bible": kit.bible,
                        "earlier_scenes": [item[1] for item in planned[:index]],
                    }
                ),
            )
        )
        pages.append(response.text.strip())
    return "\n\n".join(pages) + "\n"


def _json(router: ProviderRouter, system: str, payload: dict) -> dict:
    response = router.complete(ModelRequest(step="writing", system=system, user=json.dumps(payload)))
    text = response.text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        body = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ScriptError(f"{response.provider} returned non-JSON for the outline") from exc
    if not isinstance(body, dict):
        raise ScriptError(f"{response.provider} returned a list for the outline")
    return body
