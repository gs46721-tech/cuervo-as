"""Validate an Animation IR JSON file and print a one-line summary."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ValidationError as ModelError

from cuervo_ir.models import Episode
from cuervo_ir.schema import ir_json_schema


def validate_file(path: Path) -> Episode:
    payload = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator(ir_json_schema()).validate(payload)
    return Episode.model_validate(payload)


def summarize(episode: Episode) -> str:
    frames = sum(shot.duration_frames for scene in episode.scenes for shot in scene.shots)
    shots = sum(len(scene.shots) for scene in episode.scenes)
    seconds = frames / episode.fps
    characters = len(episode.assets.characters)
    return (
        f"{episode.episode_id} {episode.version}: "
        f"{characters} characters, {shots} shots, {frames} frames, {seconds:.1f}s at {episode.fps} fps"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a Cuervo Animation IR v0 episode.")
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    try:
        episode = validate_file(args.path)
    except (OSError, json.JSONDecodeError, SchemaError, ModelError) as exc:
        print(f"invalid: {args.path}: {exc}", file=sys.stderr)
        return 1
    print(summarize(episode))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
