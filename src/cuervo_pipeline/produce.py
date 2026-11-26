"""Script to finished episode, in four stages with a file after each.

    script      script.json       scenes and beats read from the screenplay
    storyboard  storyboard.json   shots, who each is on, which lines it covers
    animation   takes/, episode.json, boards/   voices, timing, lip sync, acting
    polish      notes.json, episode.mp4         checks, review, render, sound

Each file is the gate for the next stage. Edit `storyboard.json` or
`episode.json` and run again: a stage whose file exists is not redone unless
`rebuild` is set, so hand edits and editor work are kept.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from cuervo_ir.models import Episode
from cuervo_ir.providers.router import ProviderRouter
from cuervo_pipeline.animate import build_episode, direct_acting
from cuervo_pipeline.board import Storyboard, board_script
from cuervo_pipeline.polish import Note, check_episode, review_scenes
from cuervo_pipeline.run import PipelineResult, run_episode
from cuervo_pipeline.screenplay import Script, parse_screenplay
from cuervo_pipeline.series import SeriesKit
from cuervo_runtime.draw import render_png
from cuervo_voice.synth import VoiceError, VoiceSynth, default_synths
from cuervo_voice.takes import Take, record_take
from cuervo_world import World, WorldError

STAGES = ("script", "storyboard", "animation", "polish")


class ProduceError(RuntimeError):
    pass


@dataclass
class Production:
    out_dir: Path
    script: Script | None = None
    board: Storyboard | None = None
    episode: Episode | None = None
    notes: list[Note] = field(default_factory=list)
    render: PipelineResult | None = None
    world: World | None = None
    new_takes: int = 0
    reused_takes: int = 0

    def summary(self) -> dict:
        data: dict = {"out": str(self.out_dir)}
        if self.script:
            data["scenes"] = len(self.script.scenes)
            data["lines"] = len(self.script.lines())
        if self.board:
            data["shots"] = self.board.shot_count()
        if self.episode:
            frames = sum(shot.duration_frames for scene in self.episode.scenes for shot in scene.shots)
            data["frames"] = frames
            data["minutes"] = round(frames / self.episode.fps / 60, 2)
            data["takes_recorded"] = self.new_takes
            data["takes_reused"] = self.reused_takes
        if self.notes:
            data["notes_to_fix"] = sum(1 for note in self.notes if note.severity == "fix")
            data["notes_to_look_at"] = sum(1 for note in self.notes if note.severity == "look")
        if self.render:
            counts: dict[str, int] = {}
            for report in self.render.reports:
                counts[report.status] = counts.get(report.status, 0) + 1
            data["render"] = counts
            data["master"] = str(self.render.master) if self.render.master else None
        return data


def produce(
    script_text: str,
    kit: SeriesKit,
    out_dir: Path,
    *,
    router: ProviderRouter | None,
    through: str = "polish",
    rebuild: bool = False,
    approved: set[str] | None = None,
    director: bool = True,
    review: bool = True,
    synths: dict[str, VoiceSynth] | None = None,
    world_dir: Path | None = None,
    size: tuple[int, int] | None = None,
    log=print,
) -> Production:
    """Run the stages up to `through`. `approved=None` approves every shot for render."""

    if through not in STAGES:
        raise ProduceError(f"unknown stage {through}")
    out_dir.mkdir(parents=True, exist_ok=True)
    result = Production(out_dir=out_dir)
    creative = router if director and _usable(router, "direction") else None
    if director and creative is None:
        log("  note: no model provider is configured, so shots are cut and acted by the built-in rules")
    reviewer = router if review and _usable(router, "review") else None

    # The world comes first: every character and set is built once, before anything is animated.
    started = time.time()
    world = World(world_dir or out_dir / "world")
    try:
        world.build(kit, log=log)
    except WorldError as exc:
        raise ProduceError(str(exc)) from exc
    result.world = world
    drafts = [entry["name"] for entry in world.view() if entry["status"] != "approved"]
    log(f"world       {len(world.view())} assets, {len(drafts)} waiting for approval  ({time.time() - started:.1f}s)")

    # 1. Script
    started = time.time()
    script = parse_screenplay(script_text, kit)
    result.script = script
    _write(out_dir / "script.json", script.model_dump_json(indent=2))
    for warning in script.warnings:
        log(f"  note: {warning}")
    log(f"script      {len(script.scenes)} scenes, {len(script.lines())} lines  ({time.time() - started:.1f}s)")
    if through == "script":
        return result

    # 2. Storyboard
    started = time.time()
    digest = hashlib.sha256(script.model_dump_json().encode("utf-8")).hexdigest()
    board_file = out_dir / "storyboard.json"
    board = None if rebuild else _load(board_file, Storyboard)
    if board is not None and board.script_digest != digest:
        raise ProduceError(
            "storyboard.json was made from a different script. Pass rebuild to board the new script, "
            "or restore the script it was made from."
        )
    kept = board is not None
    if board is None:
        board = board_script(script, kit, creative, log=log)
        board.script_digest = digest
        _write(board_file, board.model_dump_json(indent=2))
    result.board = board
    by_model = sum(1 for scene in board.scenes if scene.source == "director")
    log(
        f"storyboard  {board.shot_count()} shots, {by_model}/{len(board.scenes)} scenes cut by the director"
        f"{' (kept from disk)' if kept else ''}  ({time.time() - started:.1f}s)"
    )
    if through == "storyboard":
        return result

    # 3. Animation: voices first, then timing, lip sync, and acting.
    started = time.time()
    takes_dir = out_dir / "takes"
    episode_file = out_dir / "episode.json"
    episode = None if rebuild else _load(episode_file, Episode)
    kept = episode is not None
    if episode is None:
        engines = dict(default_synths())
        if synths:
            engines.update(synths)
        takes: dict[str, Take] = {}
        lines = [line for scene in board.scenes for shot in scene.shots for line in shot.lines]
        for index, line in enumerate(lines):
            try:
                take, fresh = record_take(line.text, kit.character(line.character_id).profile(), engines, takes_dir)
            except VoiceError as exc:
                raise ProduceError(f"voice for {line.line_id} failed: {exc}") from exc
            takes[line.line_id] = take
            result.new_takes += fresh
            result.reused_takes += not fresh
            if (index + 1) % 50 == 0:
                log(f"  voices {index + 1}/{len(lines)}")
        acting = direct_acting(board, kit, creative, log=log)
        episode = build_episode(board, kit, takes, acting)
        _write(episode_file, episode.model_dump_json(indent=2))
        _write(out_dir / "poses.json", json.dumps(kit.poses, indent=2))
        _contact_sheets(episode, kit, out_dir / "boards", world)
    result.episode = episode
    frames = sum(shot.duration_frames for scene in episode.scenes for shot in scene.shots)
    log(
        f"animation   {frames} frames, {frames / episode.fps / 60:.1f} minutes, "
        f"{result.new_takes} takes recorded, {result.reused_takes} reused"
        f"{' (episode kept from disk)' if kept else ''}  ({time.time() - started:.1f}s)"
    )
    if through == "animation":
        return result

    # 4. Polish: checks, an advisory review, then render what is approved.
    started = time.time()
    notes = check_episode(episode, takes_dir)
    for name in drafts:
        notes.append(Note(shot_id="", severity="look", source="check", text=f"The design for {name} is not approved yet."))
    if reviewer is not None:
        notes.extend(review_scenes(episode, reviewer, log=log))
    result.notes = notes
    _write(out_dir / "notes.json", json.dumps([note.model_dump() for note in notes], indent=2))
    every = {shot.shot_id for scene in episode.scenes for shot in scene.shots}
    result.render = run_episode(
        episode,
        out_dir / "shots",
        router=router or ProviderRouter({}),
        approved=every if approved is None else approved,
        poses=kit.poses,
        takes_dir=takes_dir,
        world=world,
        size=size,
        review=False,
        progress=lambda done, total: log(f"  render {done}/{total}"),
    )
    if result.render.master is not None:
        final = out_dir / "episode.mp4"
        result.render.master.replace(final)
        result.render.master = final
    fixes = sum(1 for note in notes if note.severity == "fix")
    log(f"polish      {fixes} to fix, {len(notes) - fixes} to look at, master: {result.render.master}  ({time.time() - started:.1f}s)")
    return result


def _usable(router: ProviderRouter | None, step: str) -> bool:
    if router is None:
        return False
    return any(name in router.providers and router.providers[name].available() for name in router.routes.get(step, ()))


def _write(path: Path, text: str) -> None:
    path.write_text(text + "\n", encoding="utf-8")


def _load(path: Path, model):
    if not path.is_file():
        return None
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ProduceError(f"{path.name} does not load: {exc}") from exc


def _contact_sheets(episode: Episode, kit: SeriesKit, directory: Path, world=None) -> None:
    """One picture per scene: a panel for every shot, with its number, size, length, and first line."""

    directory.mkdir(parents=True, exist_ok=True)
    columns, width, height, caption = 4, 320, 180, 44
    for scene in episode.scenes:
        rows = (len(scene.shots) + columns - 1) // columns
        sheet = Image.new("RGB", (columns * width, rows * (height + caption)), (24, 24, 26))
        draw = ImageDraw.Draw(sheet)
        for index, shot in enumerate(scene.shots):
            # Board the moment that matters: the middle of the first line, else the middle of the shot.
            if shot.dialogue_tracks:
                first = shot.dialogue_tracks[0]
                frame = (first.start_frame + first.end_frame) // 2
            else:
                frame = shot.duration_frames // 2
            panel = Image.open(BytesIO(render_png(episode, shot, frame, kit.poses, world=world))).resize((width, height))
            left, top = (index % columns) * width, (index // columns) * (height + caption)
            sheet.paste(panel, (left, top))
            draw.rectangle((left, top, left + width - 1, top + height - 1), outline=(60, 60, 64))
            seconds = shot.duration_frames / episode.fps
            draw.text((left + 6, top + height + 4), f"{shot.shot_id}  {shot.camera.preset}  {seconds:.1f}s", fill=(235, 235, 230))
            line = shot.dialogue_tracks[0].text if shot.dialogue_tracks else shot.provenance.note
            draw.text((left + 6, top + height + 22), line[:50], fill=(150, 150, 155))
        sheet.save(directory / f"{scene.scene_id}.png")
