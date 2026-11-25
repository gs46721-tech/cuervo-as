import argparse
import json
from pathlib import Path

from cuervo_ir.models import Episode

from cuervo_runtime.draw import render_png


def main() -> None:
    parser = argparse.ArgumentParser(description="Render one frame of any Animation IR shot.")
    parser.add_argument("episode")
    parser.add_argument("--shot", required=True)
    parser.add_argument("--frame", type=int, default=0)
    parser.add_argument("--poses", type=Path, help="Optional series pose table, JSON object of pose name to controllers.")
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()
    episode = Episode.model_validate(json.loads(Path(args.episode).read_text(encoding="utf-8")))
    matches = [shot for scene in episode.scenes for shot in scene.shots if shot.shot_id == args.shot]
    if len(matches) != 1:
        raise SystemExit(f"expected one shot {args.shot}, found {len(matches)}")
    shot = matches[0]
    library = json.loads(args.poses.read_text(encoding="utf-8")) if args.poses else None
    args.output.write_bytes(render_png(episode, shot, args.frame, library))


if __name__ == "__main__":
    main()
