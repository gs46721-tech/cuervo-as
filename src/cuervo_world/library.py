"""The asset library on disk.

    world/
      world.json                          what exists, at which version, and whether it is approved
      characters/<id>/<version>/*.png     the parts, with rig.json and a model sheet
      sets/<id>/<version>/plate.png

An approved asset is frozen. A new look is a new version, and shots move to it
only when someone repins them, so finished shots never change by accident.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw

from cuervo_runtime.poses import CONTRACT_POSES, clamp_controls
from cuervo_runtime.puppet import CharacterArt, draw_character
from cuervo_world.design import CharacterDesign, SetDesign, digest
from cuervo_world.house import VISEMES, character_parts, rgb, set_plate


class WorldError(RuntimeError):
    pass


class World:
    def __init__(self, path: Path):
        self.path = path
        self._characters: dict[tuple[str, str], CharacterArt | None] = {}
        self._plates: dict[tuple[str, str], Image.Image | None] = {}
        try:
            self.manifest = json.loads((path / "world.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.manifest = {"kind": "world", "assets": {}}

    # -- reading ------------------------------------------------------------

    def entry(self, asset_id: str) -> dict | None:
        return self.manifest["assets"].get(asset_id)

    def character(self, asset_id: str, version: str) -> CharacterArt | None:
        key = (asset_id, version)
        if key not in self._characters:
            folder = self.path / "characters" / asset_id / version
            art = None
            if (folder / "rig.json").is_file():
                rig = json.loads((folder / "rig.json").read_text(encoding="utf-8"))
                try:
                    parts = {name: Image.open(folder / f"{name}.png").convert("RGBA") for name in rig["parts"]}
                    art = CharacterArt(parts, rig)
                except OSError:
                    art = None
            self._characters[key] = art
        return self._characters[key]

    def plate(self, asset_id: str, version: str) -> Image.Image | None:
        key = (asset_id, version)
        if key not in self._plates:
            path = self.path / "sets" / asset_id / version / "plate.png"
            self._plates[key] = Image.open(path).convert("RGB") if path.is_file() else None
        return self._plates[key]

    def sheet_path(self, asset_id: str) -> Path | None:
        entry = self.entry(asset_id)
        if entry is None:
            return None
        folder = "characters" if entry["kind"] == "character" else "sets"
        name = "sheet.png" if entry["kind"] == "character" else "plate.png"
        path = self.path / folder / asset_id / entry["version"] / name
        return path if path.is_file() else None

    def stamp(self, asset_ids: list[str]) -> str:
        """Changes when the art a shot uses changes, so the render cache can tell."""

        rows = [[asset_id, (self.entry(asset_id) or {}).get("version"), (self.entry(asset_id) or {}).get("digest")] for asset_id in sorted(asset_ids)]
        return hashlib.sha256(json.dumps(rows).encode("utf-8")).hexdigest()[:16]

    def view(self) -> list[dict]:
        return [{"asset_id": asset_id, **entry} for asset_id, entry in self.manifest["assets"].items()]

    # -- building -----------------------------------------------------------

    def build(self, kit, *, log=None, painters: list | None = None, engines: dict | None = None) -> list[str]:
        """Make the art the kit asks for and does not have yet. Returns the ids that were built.

        `painters` is the image role: `(provider, model)` pairs. With one or more, each paints
        every new set from the same prompt. The first picture that arrives is used until someone
        picks another. With none, sets are drawn in the house style.
        """

        built: list[str] = []
        for character in kit.characters:
            design = character.design or default_character_design(character.asset_id)
            if self._claim(character.asset_id, "character", character.version, digest(design), character.display_name):
                folder = self.path / "characters" / character.asset_id / character.version
                folder.mkdir(parents=True, exist_ok=True)
                parts, rig = character_parts(design)
                for name, image in parts.items():
                    image.save(folder / f"{name}.png")
                (folder / "rig.json").write_text(json.dumps(rig, indent=2), encoding="utf-8")
                self._characters.pop((character.asset_id, character.version), None)
                extra = {pose: kit.poses[pose] for pose in character.extension_poses if pose in kit.poses}
                model_sheet(CharacterArt(parts, rig), character.display_name, extra).save(folder / "sheet.png")
                built.append(character.asset_id)
        for item in kit.sets:
            design = item.design or SetDesign()
            if self._claim(item.asset_id, "set", item.version, digest(design), item.display_name):
                folder = self.path / "sets" / item.asset_id / item.version
                folder.mkdir(parents=True, exist_ok=True)
                # The house plate is always kept, as the fallback and as one of the choices.
                set_plate(design).save(folder / "house.png")
                candidates = [{"file": "house.png", "by": "house style"}]
                candidates += self._paint(folder, item.display_name, design, kit.bible, painters or [], engines, log)
                entry = self.manifest["assets"][item.asset_id]
                entry["candidates"] = candidates
                # A painted picture is preferred over the house plate when there is one.
                entry["chosen"] = 1 if len(candidates) > 1 else 0
                entry["source"] = candidates[entry["chosen"]]["by"]
                Image.open(folder / candidates[entry["chosen"]]["file"]).save(folder / "plate.png")
                self._plates.pop((item.asset_id, item.version), None)
                built.append(item.asset_id)
        if built:
            self._save()
            if log:
                log(f"  built {', '.join(built)}")
        return built

    def _paint(self, folder: Path, name: str, design, bible, painters, engines, log) -> list[dict]:
        from cuervo_world.imagegen import ImageError, default_engines, set_prompt, to_plate

        engines = engines if engines is not None else default_engines()
        prompt = set_prompt(name, design, bible)
        made: list[dict] = []
        for provider, model in painters:
            engine = engines.get(provider)
            if engine is None or not engine.available():
                if log:
                    log(f"  {name}: {provider} is not connected, so it did not paint")
                continue
            try:
                picture = to_plate(engine.paint(prompt, model or None))
            except ImageError as exc:
                if log:
                    log(f"  {name}: {provider} could not paint it ({exc})")
                continue
            file = f"painted-{len(made) + 1}.png"
            picture.save(folder / file)
            made.append({"file": file, "by": f"{provider} {model or engine.default_model}"})
        return made

    def choose(self, asset_id: str, index: int) -> None:
        """Use another candidate as the set's plate. Only while the set is a draft."""

        entry = self.entry(asset_id)
        if entry is None or entry["kind"] != "set":
            raise WorldError(f"{asset_id} is not a set in the world")
        if entry["status"] == "approved":
            raise WorldError(f"{entry['name']} is approved. Reopen it to pick another picture.")
        candidates = entry.get("candidates") or []
        if not 0 <= index < len(candidates):
            raise WorldError("there is no such picture")
        folder = self.path / "sets" / asset_id / entry["version"]
        Image.open(folder / candidates[index]["file"]).save(folder / "plate.png")
        entry["chosen"] = index
        entry["source"] = candidates[index]["by"]
        # A different picture is a different look, so shots that use it are drawn again.
        entry["digest"] = f"{entry['digest'].split('+')[0]}+{index}"
        self._plates.pop((asset_id, entry["version"]), None)
        self._save()

    def candidate_path(self, asset_id: str, index: int) -> Path | None:
        entry = self.entry(asset_id)
        candidates = (entry or {}).get("candidates") or []
        if entry is None or not 0 <= index < len(candidates):
            return None
        path = self.path / "sets" / asset_id / entry["version"] / candidates[index]["file"]
        return path if path.is_file() else None

    def approve(self, asset_id: str, approved: bool = True) -> None:
        entry = self.entry(asset_id)
        if entry is None:
            raise WorldError(f"{asset_id} is not in the world")
        entry["status"] = "approved" if approved else "draft"
        self._save()

    def _claim(self, asset_id: str, kind: str, version: str, look: str, name: str) -> bool:
        """Decide whether to build. An approved asset is never drawn over."""

        entry = self.entry(asset_id)
        if entry is not None and entry["version"] == version:
            if entry["digest"].split("+")[0] == look:
                return False
            if entry["status"] == "approved":
                raise WorldError(
                    f"{name} is approved at version {version} and its design changed. "
                    "Give the new look a new version in the series kit."
                )
        self.manifest["assets"][asset_id] = {
            "kind": kind,
            "name": name,
            "version": version,
            "digest": look,
            "status": "draft",
            "source": "house style",
        }
        return True

    def _save(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / "world.json").write_text(json.dumps(self.manifest, indent=2), encoding="utf-8")


def default_character_design(asset_id: str) -> CharacterDesign:
    """A distinct, repeatable look for a character whose kit entry has no design yet."""

    seed = hashlib.sha256(asset_id.encode("utf-8")).digest()
    skins = ["#f1c9a5", "#e0a878", "#c68a5c", "#9a6340", "#6e4630"]
    hairs = ["#2b2118", "#4a3222", "#8a5a2c", "#c9a66b", "#1c1c22", "#7d3b2a"]
    tops = ["#3f6fb5", "#b5533f", "#3f9a72", "#8a57b0", "#c79a2e", "#3a8fa3"]
    styles = ["short", "bob", "bun", "curly", "flat"]
    return CharacterDesign(
        skin=skins[seed[0] % len(skins)],
        hair=hairs[seed[1] % len(hairs)],
        hair_style=styles[seed[2] % len(styles)],  # type: ignore[arg-type]
        top=tops[seed[3] % len(tops)],
        build=["slim", "average", "broad"][seed[4] % 3],  # type: ignore[arg-type]
        height=0.92 + (seed[5] % 5) * 0.04,
    )


SHEET_POSES = ("idle", "shrug", "point", "sit", "react", "recoil", "look_at", "blink")


def model_sheet(art: CharacterArt, name: str, extra_poses: dict[str, dict[str, float]] | None = None) -> Image.Image:
    """The character in the standard poses, facing both ways, with the mouth chart. This is what gets approved."""

    poses = {pose: CONTRACT_POSES[pose] for pose in SHEET_POSES}
    poses.update(extra_poses or {})
    cell_w, cell_h, top = 190, 300, 46
    columns = len(poses)
    sheet = Image.new("RGBA", (columns * cell_w, top + cell_h + 150), (244, 240, 232, 255))
    draw = ImageDraw.Draw(sheet)
    draw.text((16, 14), f"{name}  ·  model sheet", fill=(40, 34, 36))
    for index, (pose, values) in enumerate(poses.items()):
        controls = clamp_controls(values)
        left = index * cell_w
        draw_character(sheet, art, controls, None, (left + cell_w / 2, top + cell_h * 0.62), 0.95, faces_left=index % 2 == 1 and pose == "idle")
        draw.text((left + 12, top + cell_h - 18), pose.replace("_", " "), fill=(90, 84, 86))
    # The eight mouths, at twice size, under the poses.
    base = top + cell_h + 20
    draw.text((16, base), "mouths", fill=(40, 34, 36))
    for index, viseme in enumerate(VISEMES):
        image, pivot_x, pivot_y = art.placed(f"mouth_{viseme}", 4.0, 0, False)
        center = (150 + index * 150, base + 60)
        draw.rounded_rectangle((center[0] - 60, center[1] - 44, center[0] + 60, center[1] + 44), 12, fill=rgb("#e7c4a2")[:3])
        sheet.alpha_composite(image, (round(center[0] - pivot_x), round(center[1] - pivot_y)))
        draw.text((center[0] - 12, center[1] + 50), viseme, fill=(90, 84, 86))
    return sheet.convert("RGB")
