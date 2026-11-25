import argparse
import json
from pathlib import Path

from cuervo_ir.models import Episode
from cuervo_ir.providers.router import build_default_router
from cuervo_voice.dub import VoiceProfile
from cuervo_pipeline.plan import plan_script
from cuervo_pipeline.run import run_episode


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
    args = parser.parse_args()
    router = build_default_router()
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
