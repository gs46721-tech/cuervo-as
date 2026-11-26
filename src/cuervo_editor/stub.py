"""Dev stand-in used only when CUERVO_EDITOR_STUB=1.

It is a router provider for the editor_assist step and answers in cues, the
way a model does. It reads keywords, not meaning, so the page can be tried
without an account. It is not a series.
"""

from __future__ import annotations

import json
import re

from cuervo_ir.providers.router import ModelRequest, ModelResponse, ProviderError

CAMERA_WORDS = {
    "close": "close_up",
    "wide": "wide",
    "two shot": "two_shot",
    "two-shot": "two_shot",
    "over the shoulder": "over_the_shoulder",
    "reaction shot": "reaction",
    "insert": "insert",
}
POSE_HOMES = {"shrug": "gesture", "point": "gesture", "look_at": "gaze", "nod": "gaze", "react": "expression", "recoil": "expression"}


class DevStub:
    name = "devstub"
    model = "keywords"

    def available(self) -> bool:
        return True

    def complete(self, request: ModelRequest) -> ModelResponse:
        if request.step != "editor_assist":
            raise ProviderError(f"devstub does not do {request.step}")
        return ModelResponse(provider=self.name, model=self.model, text=_cues(json.loads(request.user)))


def _cues(brief: dict) -> str:
    note = str(brief["note"])
    lowered = note.lower()
    episode = brief["episode"]
    if lowered.rstrip().endswith("?"):
        minutes, rest = divmod(round(episode["seconds"]), 60)
        length = f"{minutes} min {rest} s" if minutes else f"{rest} seconds"
        return f'done "{episode["title"]} has {episode["shots"]} shots in {episode["scenes"]} scenes and runs {length}."'
    scene_shots = [row.split()[0] for row in brief["current_scene"].splitlines() if row.strip()]
    if brief["pinned_shots"]:
        targets = list(brief["pinned_shots"])
    elif re.search(r"\b(every|all|each)\b", lowered):
        targets = scene_shots
    else:
        targets = [brief["on_screen"]]
    # The stub can only see the shot on screen, so it asks to see the others first.
    unseen = [shot for shot in targets if shot != brief["on_screen"] and f"> show {shot}" not in brief["session"]]
    if unseen and _needs_tracks(lowered):
        return "\n".join(f"show {shot}" for shot in unseen)
    rows = []
    for shot in targets:
        shown = brief["current_shot"] if shot == brief["on_screen"] else _shown(brief["session"], shot)
        rows.append(_one(lowered, note, shot, shown))
    rows.append('done "Done. Have a look and tell me if it reads."')
    return "\n".join(rows)


def _needs_tracks(lowered: str) -> bool:
    return "hold" not in lowered and not any(words in lowered for words in CAMERA_WORDS)


def _shown(session: str, shot: str) -> str:
    marker = f"> show {shot}\n"
    if marker not in session:
        return ""
    return session.split(marker, 1)[1].split("\n> ", 1)[0]


def _one(lowered: str, note: str, shot: str, shown: str) -> str:
    if "hold" in lowered:
        number = re.search(r"(\d+)", lowered)
        return f"hold {shot} {int(number.group(1)) if number else 12}"
    if "trim" in lowered:
        number = re.search(r"(\d+)", lowered)
        return f"trim {shot} {int(number.group(1)) if number else 12}"
    for words, preset in CAMERA_WORDS.items():
        if words in lowered:
            return f"camera {shot} {preset}"
    actors = re.findall(r"^\s+(act_\w+)\s+.*poses:\s*(.*)$", shown, re.MULTILINE)
    tracks = re.findall(r"^\s+(tr_\w+)\s+(\w+)\s+(act_\w+)\s+(\w+)\s+\d+\.\.\d+", shown, re.MULTILINE)
    rewrite = re.search(r'say[^"“]*["“]([^"”]+)["”]', note, re.IGNORECASE)
    line = re.search(r"^\s+(ln_\w+)\s", shown, re.MULTILINE)
    if rewrite and line:
        return f'say {shot} {line.group(1)} "{rewrite.group(1)}"'
    spoken = lowered.replace("_", " ")
    for actor, poses in actors:
        for pose in poses.split():
            if not re.search(rf"\b{re.escape(pose.replace('_', ' '))}\b", spoken):
                continue
            home = POSE_HOMES.get(pose, "expression")
            existing = next((item for item in tracks if item[2] == actor and item[1] == home and item[3] != pose), None)
            if existing and home == "expression":
                return f"pose {shot} {existing[0]} {pose}"
            return f"act {shot} {actor} {pose}"
    expression = next((item for item in tracks if item[1] == "expression" and item[3] != "react"), None)
    if expression:
        return f"pose {shot} {expression[0]} react"
    if actors:
        return f"act {shot} {actors[0][0]} react"
    return f"camera {shot} close_up"
