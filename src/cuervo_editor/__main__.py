"""Series editor API.

    python3 -m cuervo_editor [episode.json ...] [--poses poses.json]

Episodes named on the command line open as projects. The editor ships none.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import uvicorn

from cuervo_ir.models import Episode


def main() -> None:
    parser = argparse.ArgumentParser(prog="cuervo_editor", description="Cuervo series editor API")
    parser.add_argument("episodes", nargs="*", type=Path, help="episode JSON files to open as projects")
    parser.add_argument("--poses", type=Path, help="series pose table for those episodes")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    from cuervo_editor.api import app

    poses = json.loads(args.poses.read_text(encoding="utf-8")) if args.poses else None
    store = app.state.store
    already = {session.episode.episode_id for session in store.all()}
    for path in args.episodes:
        episode = Episode.model_validate(json.loads(path.read_text(encoding="utf-8")))
        if episode.episode_id not in already:
            store.open(episode, poses)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
