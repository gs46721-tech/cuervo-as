import argparse
import json
from pathlib import Path

from cuervo_ir.models import Episode
from cuervo_ir.providers.router import build_default_router
from cuervo_edit.edits import EditPatch, apply_edit
from cuervo_edit.propose import propose_edit


def main() -> None:
    parser = argparse.ArgumentParser(description="Propose or apply a typed shot edit.")
    sub = parser.add_subparsers(dest="command", required=True)
    propose = sub.add_parser("propose")
    propose.add_argument("episode", type=Path)
    propose.add_argument("--shot", required=True)
    propose.add_argument("--instruction", required=True)
    apply = sub.add_parser("apply")
    apply.add_argument("episode", type=Path)
    apply.add_argument("patch", type=Path)
    apply.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()
    episode = Episode.model_validate(json.loads(args.episode.read_text(encoding="utf-8")))
    if args.command == "propose":
        patch = propose_edit(episode, args.shot, args.instruction, build_default_router())
        print(patch.model_dump_json(indent=2))
        return
    patch = EditPatch.model_validate(json.loads(args.patch.read_text(encoding="utf-8")))
    revised = apply_edit(episode, patch)
    args.output.write_text(revised.model_dump_json(indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
