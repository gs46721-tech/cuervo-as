"""Turn a user script into a shot plan. The text is an argument, not a built-in show."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cuervo_ir.models import CameraPreset, Id
from cuervo_ir.providers.router import ModelRequest, ProviderRouter


class PlanError(ValueError):
    pass


class PlannedLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker: str = Field(min_length=1)
    text: str = Field(min_length=1)


class PlannedScene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: Id
    objective: str = Field(min_length=1)
    lines: list[PlannedLine]


class PlannedShot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_id: Id
    scene_id: Id
    preset: CameraPreset
    duration_frames: int = Field(ge=1)
    framing: str = Field(min_length=1)


class ScriptPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["script_plan"] = "script_plan"
    scenes: list[PlannedScene]
    shots: list[PlannedShot]


def plan_script(script: str, bible: list[str], router: ProviderRouter) -> ScriptPlan:
    if not script.strip():
        raise PlanError("script is empty")
    outline = _ask(
        router,
        "writing",
        "Turn the script into JSON {scenes: [{scene_id, objective, lines: [{speaker, text}]}]}. "
        "Use only facts from the script and the bible. Do not add a character who is not in them.",
        {"script": script, "bible": bible},
    )
    shots = _ask(
        router,
        "direction",
        "Turn the scenes into JSON {shots: [{shot_id, scene_id, preset, duration_frames, framing}]}. "
        "preset is one of wide, two_shot, over_the_shoulder, close_up, reaction, insert.",
        {"scenes": outline},
    )
    try:
        plan = ScriptPlan.model_validate({"scenes": outline["scenes"], "shots": shots["shots"]})
    except (KeyError, TypeError, ValidationError) as exc:
        raise PlanError("the router did not return a script plan") from exc
    known = {scene.scene_id for scene in plan.scenes}
    for shot in plan.shots:
        if shot.scene_id not in known:
            raise PlanError(f"{shot.shot_id} names unknown scene {shot.scene_id}")
    return plan


def _ask(router: ProviderRouter, step: str, system: str, payload: dict) -> dict:
    response = router.complete(ModelRequest(step=step, system=system, user=json.dumps(payload)))
    try:
        body = json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise PlanError(f"{response.provider} returned non-JSON for {step}") from exc
    if not isinstance(body, dict):
        raise PlanError(f"{response.provider} returned a list for {step}")
    return body
