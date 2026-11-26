"""Build and approve the world.

    python3 -m cuervo_world build series.json --out world/
    python3 -m cuervo_world list world/
    python3 -m cuervo_world approve world/ <asset_id> [...]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from cuervo_pipeline.series import load_kit
from cuervo_world import World, WorldError


def main() -> None:
    parser = argparse.ArgumentParser(prog="cuervo_world", description="The 2D asset library for a series.")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="make the art the series kit asks for and does not have yet")
    build.add_argument("series", type=Path)
    build.add_argument("--out", type=Path, required=True)
    listing = sub.add_parser("list", help="show every asset, its version, and whether it is approved")
    listing.add_argument("world", type=Path)
    approve = sub.add_parser("approve", help="freeze an asset so its look cannot change without a new version")
    approve.add_argument("world", type=Path)
    approve.add_argument("assets", nargs="+")
    args = parser.parse_args()
    try:
        if args.command == "build":
            world = World(args.out)
            built = world.build(load_kit(args.series))
            print(f"built {len(built)}: {', '.join(built) or 'nothing new'}")
        else:
            world = World(args.world)
            if args.command == "approve":
                for asset_id in args.assets:
                    world.approve(asset_id)
        for entry in world.view():
            print(f"{entry['asset_id']:24} {entry['kind']:10} {entry['version']:8} {entry['status']:9} {entry['name']}")
    except WorldError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
