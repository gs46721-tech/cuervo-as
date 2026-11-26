import argparse
import json
from pathlib import Path

from cuervo_ir.credentials import Credentials
from cuervo_ir.models import Episode
from cuervo_ir.providers.router import build_default_router
from cuervo_voice.dub import VoiceProfile
from cuervo_pipeline.plan import plan_script
from cuervo_pipeline.produce import STAGES, ProduceError, produce
from cuervo_pipeline.run import run_episode
from cuervo_pipeline.screenplay import ScriptError, write_script
from cuervo_pipeline.series import load_kit


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan or render a user-supplied episode.")
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("script", type=Path)
    plan.add_argument("--bible", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("episode", type=Path)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--approve", action="append", default=[])
    run.add_argument("--profiles", type=Path)
    write = sub.add_parser("write", help="draft a screenplay from a premise")
    write.add_argument("premise", type=Path)
    write.add_argument("--series", type=Path, required=True)
    write.add_argument("--minutes", type=float, default=22)
    write.add_argument("-o", "--output", type=Path, required=True)
    make = sub.add_parser("produce", help="script to finished episode: script, storyboard, animation, polish")
    make.add_argument("script", type=Path)
    make.add_argument("--series", type=Path, required=True)
    make.add_argument("--out", type=Path, required=True)
    make.add_argument("--through", choices=STAGES, default="polish", help="stop after this stage")
    make.add_argument("--rebuild", action="store_true", help="redo the storyboard and episode even if their files exist")
    make.add_argument("--approve", action="append", default=[], help="render only these shots (default: all)")
    make.add_argument("--no-director", action="store_true", help="cut and act by the built-in rules, with no model calls")
    make.add_argument("--no-review", action="store_true", help="skip the model's review notes")
    make.add_argument("--world", type=Path, help="the asset library to draw from (default: <out>/world)")
    make.add_argument("--size", default="640x360", help="frame size, such as 1280x720")
    args = parser.parse_args()
    # Keys saved in the editor's settings work here too.
    Credentials()
    router = build_default_router()
    if args.command == "write":
        try:
            text = write_script(args.premise.read_text(encoding="utf-8"), load_kit(args.series), args.minutes, router)
        except ScriptError as exc:
            raise SystemExit(str(exc)) from exc
        args.output.write_text(text, encoding="utf-8")
        print(f"{args.output}: {len(text.split())} words")
        return
    if args.command == "produce":
        try:
            result = produce(
                args.script.read_text(encoding="utf-8"),
                load_kit(args.series),
                args.out,
                router=router,
                through=args.through,
                rebuild=args.rebuild,
                approved=set(args.approve) or None,
                director=not args.no_director,
                review=not args.no_review,
                world_dir=args.world,
                size=tuple(int(part) for part in args.size.lower().split("x")),  # type: ignore[arg-type]
            )
        except (ProduceError, ScriptError) as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(result.summary(), indent=2))
        return
    if args.command == "plan":
        bible = [line for line in args.bible.read_text(encoding="utf-8").splitlines() if line.strip()]
        print(plan_script(args.script.read_text(encoding="utf-8"), bible, router).model_dump_json(indent=2))
        return
    episode = Episode.model_validate(json.loads(args.episode.read_text(encoding="utf-8")))
    profiles = None
    if args.profiles:
        profiles = [VoiceProfile.model_validate(item) for item in json.loads(args.profiles.read_text(encoding="utf-8"))]
    result = run_episode(
        episode,
        args.out,
        router=router,
        approved=set(args.approve),
        profiles=profiles,
    )
    for report in result.reports:
        print(f"{report.shot_id} {report.status} frames={report.cost_frames} hash={report.render_hash}")
    if result.master:
        print(result.master)


if __name__ == "__main__":
    main()
