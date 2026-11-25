"""JSON Schema for Animation IR v0, generated from the Pydantic models."""

from __future__ import annotations

import json
from pathlib import Path

from cuervo_edit.edits import EditPatch
from cuervo_ir.models import Episode, TimingPatch

SCHEMA_ID = "https://github.com/gs46721-tech/cuervo-as/schemas/animation-ir-v0.schema.json"
REPO_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "animation-ir-v0.schema.json"


def ir_json_schema() -> dict:
    parts = [model.model_json_schema() for model in (Episode, TimingPatch, EditPatch)]
    defs: dict = {}
    for part in parts:
        incoming = part.pop("$defs", {})
        for name, schema in incoming.items():
            if name in defs and defs[name] != schema:
                raise RuntimeError(f"$defs/{name} differs between IR documents")
            defs[name] = schema
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        "title": "AnimationIRv0",
        "description": (
            "An episode, a timing patch, or an edit patch. Timeline fields are integer frames."
        ),
        "oneOf": parts,
        "$defs": defs,
    }


def write_schema(path: Path = REPO_SCHEMA_PATH) -> None:
    path.write_text(json.dumps(ir_json_schema(), indent=2) + "\n", encoding="utf-8")
