import argparse
import json
from pathlib import Path

from cuervo_ir.models import Episode
from cuervo_ir.providers.router import build_default_router
from cuervo_edit import cues
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
    cue = sub.add_parser("cue", help="run cues, the command line of the animation, on an episode")
    cue.add_argument("episode", type=Path)
    cue.add_argument("cues", nargs="*", help='cues such as "show sh_a" or "hold sh_a 12"; reads a file with --file')
    cue.add_argument("--file", type=Path, help="a file of cues, one per line")
    cue.add_argument("--poses", type=Path)
    cue.add_argument("-o", "--output", type=Path, help="where to write the episode if a cue changed it")
    args = parser.parse_args()
    episode = Episode.model_validate(json.loads(args.episode.read_text(encoding="utf-8")))
    if args.command == "cue":
        script = args.file.read_text(encoding="utf-8") if args.file else "\n".join(args.cues)
        poses = json.loads(args.poses.read_text(encoding="utf-8")) if args.poses else None
        changed = False
        try:
            for item in cues.parse(script):
                if item.verb in cues.READS:
                    print(cues.read(episode, item))
                elif item.verb in cues.EDITS:
                    episode, sentence = cues.apply(episode, item, cues.CueContext(poses=poses))
                    changed = True
                    print(sentence)
        except cues.CueError as exc:
            raise SystemExit(str(exc)) from exc
        if changed and args.output:
            args.output.write_text(episode.model_dump_json(indent=2) + "\n", encoding="utf-8")
        elif changed:
            print("Nothing was saved. Pass -o to write the episode.")
        return
    if args.command == "propose":
        patch = propose_edit(episode, args.shot, args.instruction, build_default_router())
        print(patch.model_dump_json(indent=2))
        return
    patch = EditPatch.model_validate(json.loads(args.patch.read_text(encoding="utf-8")))
    revised = apply_edit(episode, patch)
    args.output.write_text(revised.model_dump_json(indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
