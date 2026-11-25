"""JSON Schema for Animation IR v0, generated from the Pydantic models."""

from __future__ import annotations

import json
from pathlib import Path

from cuervo_ir.models import Episode, TimingPatch

SCHEMA_ID = "https://github.com/gs46721-tech/cuervo-as/schemas/animation-ir-v0.schema.json"
REPO_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "animation-ir-v0.schema.json"


def ir_json_schema() -> dict:
    episode = Episode.model_json_schema()
    patch = TimingPatch.model_json_schema()
    defs: dict = {}
    defs.update(episode.pop("$defs", {}))
    incoming = patch.pop("$defs", {})
    for name, schema in incoming.items():
        if name in defs and defs[name] != schema:
            raise RuntimeError(f"$defs/{name} differs between Episode and TimingPatch")
        defs[name] = schema
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        "title": "AnimationIRv0",
        "description": (
            "Phase 0 Animation IR. An episode document or a timing patch. "
            "Timeline fields are integer frames."
        ),
        "oneOf": [episode, patch],
        "$defs": defs,
    }


def write_schema(path: Path = REPO_SCHEMA_PATH) -> None:
    path.write_text(json.dumps(ir_json_schema(), indent=2) + "\n", encoding="utf-8")
