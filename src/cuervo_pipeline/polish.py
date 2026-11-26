"""Stage 4, perfecting. Checks a person would otherwise find by watching the whole cut.

The checks are plain rules over the episode. They flag. They never change a
shot. A note names the shot, so it can be fixed in the editor and re-rendered.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from cuervo_ir.models import Episode
from cuervo_ir.providers.router import ModelRequest, ProviderError, ProviderRouter
from cuervo_voice.takes import load_take

LONG_SHOT_SECONDS = 12
SHORT_SHOT_FRAMES = 12


class Note(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_id: str
    severity: Literal["fix", "look"]
    source: Literal["check", "review"]
    text: str


def check_episode(episode: Episode, takes_dir: Path | None = None) -> list[Note]:
    notes: list[Note] = []

    def note(shot_id: str, severity: str, text: str) -> None:
        notes.append(Note(shot_id=shot_id, severity=severity, source="check", text=text))  # type: ignore[arg-type]

    fps = episode.fps
    for scene in episode.scenes:
        previous = None
        run = 0
        for shot in scene.shots:
            seconds = shot.duration_frames / fps
            if seconds > LONG_SHOT_SECONDS:
                note(shot.shot_id, "look", f"Runs {seconds:.0f} seconds without a cut.")
            if shot.duration_frames < SHORT_SHOT_FRAMES:
                note(shot.shot_id, "look", f"Only {shot.duration_frames} frames. It may read as a flash.")
            framing = (shot.camera.preset, round(shot.camera.transform.x))
            run = run + 1 if framing == previous else 1
            if run == 2 and shot.camera.preset != "wide":
                note(shot.shot_id, "look", "Same framing as the shot before. The cut may jump.")
            previous = framing
            for line in shot.dialogue_tracks:
                if not line.voice_take_id:
                    note(shot.shot_id, "fix", f'No voice take for "{_clip(line.text)}".')
                    continue
                if not line.visemes:
                    note(shot.shot_id, "fix", f'No lip sync for "{_clip(line.text)}".')
                if takes_dir is None:
                    continue
                take = load_take(takes_dir, line.voice_take_id)
                if take is None:
                    note(shot.shot_id, "fix", f'The take for "{_clip(line.text)}" is not in the takes folder.')
                    continue
                frames = line.end_frame - line.start_frame
                if take.seconds * fps > frames + 1:
                    note(shot.shot_id, "fix", f'"{_clip(line.text)}" is cut off: the take is longer than the line.')
                if take.timing == "estimated":
                    note(shot.shot_id, "look", f'Lip sync for "{_clip(line.text)}" is estimated, not measured from the audio.')
                if take.text != line.text:
                    note(shot.shot_id, "fix", f'The line now reads "{_clip(line.text)}" and the take says something else. Record it again.')
            speakers = {line.speaker_actor_id for line in shot.dialogue_tracks}
            gazing = {track.target_actor_id for track in shot.action_tracks if track.kind == "gaze"}
            if speakers and len(shot.actors) > 1 and not gazing:
                note(shot.shot_id, "look", "Nobody has an eyeline while someone talks.")
    return notes


def review_scenes(episode: Episode, router: ProviderRouter, *, log=None) -> list[Note]:
    """One advisory pass per scene through the `review` route. A scene it cannot read is skipped."""

    notes: list[Note] = []
    for scene in episode.scenes:
        payload = {
            "objective": scene.objective,
            "shots": [
                {
                    "shot_id": shot.shot_id,
                    "preset": shot.camera.preset,
                    "seconds": round(shot.duration_frames / episode.fps, 1),
                    "lines": [line.text for line in shot.dialogue_tracks],
                    "poses": sorted({track.keyframes[0].pose for track in shot.action_tracks if track.kind != "secondary"}),
                }
                for shot in scene.shots
            ],
        }
        try:
            response = router.complete(
                ModelRequest(
                    step="review",
                    system=(
                        "You review one scene of a 2D animated sitcom for pacing, shot choice, and acting. Return "
                        'only JSON {"notes": [{"shot_id": string, "text": string}]}. At most one short, concrete '
                        "note per shot, and only where something should change. You do not approve anything."
                    ),
                    user=json.dumps(payload),
                )
            )
            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            known = {shot.shot_id for shot in scene.shots}
            for item in json.loads(text)["notes"]:
                if item["shot_id"] in known and str(item["text"]).strip():
                    notes.append(Note(shot_id=item["shot_id"], severity="look", source="review", text=str(item["text"]).strip()))
        except (ProviderError, json.JSONDecodeError, KeyError, TypeError) as exc:
            if log:
                log(f"  {scene.scene_id}: no review ({exc})")
    return notes


def _clip(text: str) -> str:
    return text if len(text) <= 48 else text[:45].rstrip() + "…"
