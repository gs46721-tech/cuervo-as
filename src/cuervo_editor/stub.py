"""Dev stand-in used only when CUERVO_EDITOR_STUB=1.

It is still a router provider for the editor_assist and ir_patch steps. It
reads keywords, not meaning, so the page can be tried without API keys. It is
not a series.
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


class DevStub:
    name = "devstub"
    model = "keywords"

    def available(self) -> bool:
        return True

    def complete(self, request: ModelRequest) -> ModelResponse:
        payload = json.loads(request.user)
        if request.step == "editor_assist":
            body = _plan(payload)
        elif request.step == "ir_patch":
            body = _patch(payload)
        else:
            raise ProviderError(f"devstub does not do {request.step}")
        return ModelResponse(provider=self.name, model=self.model, text=json.dumps(body))


def _plan(payload: dict) -> dict:
    instruction = str(payload["instruction"])
    lowered = instruction.lower()
    shots = payload["episode"]["shots"]
    if lowered.rstrip().endswith("?"):
        frames = sum(shot["duration_frames"] for shot in shots)
        seconds = frames / payload["episode"]["fps"]
        return {
            "reply": f"{payload['episode']['title']} has {len(shots)} shots and runs {frames} frames, {seconds:.1f} seconds.",
            "edits": [],
        }
    named = [shot["shot_id"] for shot in shots if shot["shot_id"] in lowered]
    if named:
        chosen = named
    elif re.search(r"\b(every|all|each)\b", lowered):
        chosen = [shot["shot_id"] for shot in shots]
    elif payload.get("focus_shot_id"):
        chosen = [payload["focus_shot_id"]]
    else:
        chosen = [shots[0]["shot_id"]]
    return {
        "reply": f"I'll change {', '.join(chosen)}.",
        "edits": [{"shot_id": shot_id, "instruction": instruction} for shot_id in chosen],
    }


def _patch(payload: dict) -> dict:
    instruction = str(payload["instruction"]).lower()
    tracks = payload["tracks"]
    base: dict = {
        "kind": "edit_patch",
        "patch_id": "patch_devstub",
        "target_shot_id": payload["target_shot_id"],
        "base_revision": payload["base_revision"],
        "reason": payload["instruction"],
    }
    if "hold" in instruction and tracks:
        number = re.search(r"(\d+)", instruction)
        frames = int(number.group(1)) if number else 12
        track = next((item for item in tracks if item["kind"] == "expression"), tracks[0])
        base["timing"] = [{"track_id": track["track_id"], "end_delta_frames": frames}]
        base["extend_shot_frames"] = frames
        return base
    for words, preset in CAMERA_WORDS.items():
        if words in instruction:
            base["camera"] = {"preset": preset}
            return base
    for track in tracks:
        for pose in track["allowed_poses"]:
            if re.search(rf"\b{re.escape(pose.replace('_', ' '))}\b", instruction.replace("_", " ")) and pose != track.get("pose"):
                if _fits(track["kind"], pose):
                    base["poses"] = [{"track_id": track["track_id"], "pose": pose}]
                    return base
    track = next((item for item in tracks if item["kind"] == "expression"), tracks[0] if tracks else None)
    if track is None:
        base["camera"] = {"preset": "close_up"}
    else:
        pose = "react" if "react" in track["allowed_poses"] else track["allowed_poses"][0]
        base["poses"] = [{"track_id": track["track_id"], "pose": pose}]
    return base


def _fits(kind: str, pose: str) -> bool:
    """Keep a gesture word off a body track and the other way round."""

    homes = {
        "sit": "pose",
        "stand": "pose",
        "walk": "locomotion",
        "shrug": "gesture",
        "point": "gesture",
        "look_at": "gaze",
        "blink": "secondary",
    }
    return homes.get(pose, kind) == kind or kind == "expression" and pose not in homes
