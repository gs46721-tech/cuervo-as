"""Deterministic flat 2D frames. No window, no series palette."""

from __future__ import annotations

import hashlib
from io import BytesIO

from PIL import Image, ImageDraw

from cuervo_ir.models import Episode, Shot

from cuervo_runtime.mixer import controls_at
from cuervo_voice.visemes import VISEME_MOUTH, viseme_at

WIDTH = 640
HEIGHT = 360


def render_png(
    episode: Episode,
    shot: Shot,
    frame: int,
    library: dict[str, dict[str, float]] | None = None,
) -> bytes:
    if frame < 0 or frame >= shot.duration_frames:
        raise ValueError(f"frame {frame} is outside shot {shot.shot_id}")
    backdrop = _swatch(shot_background(episode, shot))
    image = Image.new("RGB", (WIDTH, HEIGHT), backdrop)
    draw = ImageDraw.Draw(image)
    _ground(draw, shot, backdrop)
    for actor in sorted(shot.actors, key=lambda item: item.depth):
        if not actor.visible:
            continue
        controls = controls_at(shot, actor.actor_id, frame, library)
        viseme = viseme_at(shot, actor.actor_id, frame)
        if viseme is not None:
            name, weight = viseme
            for controller, value in VISEME_MOUTH[name].items():
                controls[controller] = value * weight
        _draw_actor(draw, actor, controls, _camera_pan(shot), shot.camera.transform.scale)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def shot_background(episode: Episode, shot: Shot) -> str:
    for ref in shot.asset_refs:
        if ref.role == "background":
            return ref.asset_id
    for scene in episode.scenes:
        if scene.scene_id == shot.scene_id:
            return scene.setting_id
    raise ValueError(f"{shot.shot_id} has no background")


def _camera_pan(shot: Shot) -> tuple[int, int]:
    transform = shot.camera.transform
    return (int(transform.x * 0.5), int(transform.y * 0.25))


def _swatch(key: str) -> tuple[int, int, int]:
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return tuple(48 + byte % 160 for byte in digest[:3])


def _ground(draw: ImageDraw.ImageDraw, shot: Shot, base: tuple[int, int, int]) -> None:
    """A floor under the cast, so a zoom reads as a zoom."""

    scale = shot.camera.transform.scale
    pan_y = _camera_pan(shot)[1]
    line = int(HEIGHT / 2 + (HEIGHT * 0.72 + 30 + pan_y - HEIGHT / 2) * scale)
    if line < HEIGHT:
        draw.rectangle((0, max(0, line), WIDTH, HEIGHT), fill=tuple(max(0, value - 28) for value in base))


def _draw_actor(draw: ImageDraw.ImageDraw, actor, controls: dict[str, float], pan: tuple[int, int], scale: float = 1.0) -> None:
    """Draw one figure. The camera scale zooms about the middle of the frame."""

    base_x = WIDTH / 2 + actor.stage.x * 0.7 + controls["root"] * 20 - pan[0]
    base_y = HEIGHT * 0.72 - actor.stage.y * 0.4 - controls["torso"] * 16 + pan[1]

    def at(dx: float, dy: float) -> tuple[int, int]:
        return (
            int(WIDTH / 2 + (base_x + dx - WIDTH / 2) * scale),
            int(HEIGHT / 2 + (base_y + dy - HEIGHT / 2) * scale),
        )

    def thick(value: float) -> int:
        return max(1, int(round(value * scale)))

    color = _swatch(actor.character_id)
    facing = -1 if "left" in actor.facing else 1
    draw.line((*at(-10, 0), *at(-10, 28 + int(controls["leg_l"] * 10))), fill=color, width=thick(4))
    draw.line((*at(10, 0), *at(10, 28 + int(controls["leg_r"] * 10))), fill=color, width=thick(4))
    draw.rectangle((*at(-16, -48), *at(16, 0)), fill=color)
    draw.line(
        (*at(-16, -36), *at(-16 - facing * int(18 + controls["arm_l"] * 24), -36 - int(controls["hand_l"] * 20))),
        fill=color,
        width=thick(3),
    )
    draw.line(
        (*at(16, -36), *at(16 + facing * int(18 + controls["arm_r"] * 24), -36 - int(controls["hand_r"] * 20))),
        fill=color,
        width=thick(3),
    )
    head = -70 - int(controls["head"] * 8)
    draw.ellipse((*at(-14, head - 14), *at(14, head + 14)), fill=color)
    eye_h = max(1, int(4 * (1 - controls["blink"])))
    gaze = int(controls["gaze_yaw"] * 4)
    brow = int((controls["brow_l"] + controls["brow_r"]) * 2)
    for side in (-5, 5):
        draw.rectangle((*at(side + gaze - 2, head - eye_h), *at(side + gaze + 2, head + eye_h)), fill=(250, 250, 250))
        if scale >= 1.4:
            draw.line((*at(side - 3, head - 8 - brow), *at(side + 3, head - 8 - brow)), fill=(30, 30, 30), width=thick(1))
    mouth_h = 2 + int(controls["mouth"] * 8) + int(controls["jaw"] * 6)
    draw.rectangle((*at(-5, head + 4), *at(5, head + 4 + mouth_h)), fill=(30, 30, 30))


class FramePlayer:
    """Frame-steppable preview. `step` returns the current frame, then advances."""

    def __init__(self, episode: Episode, shot_id: str, library: dict[str, dict[str, float]] | None = None):
        self.episode = episode
        matches = [shot for scene in episode.scenes for shot in scene.shots if shot.shot_id == shot_id]
        if len(matches) != 1:
            raise ValueError(f"expected one shot {shot_id}, found {len(matches)}")
        self.shot = matches[0]
        self.library = library
        self.frame = 0

    def seek(self, frame: int) -> None:
        if frame < 0 or frame >= self.shot.duration_frames:
            raise ValueError(f"frame {frame} is outside shot {self.shot.shot_id}")
        self.frame = frame

    def png(self) -> bytes:
        return render_png(self.episode, self.shot, self.frame, self.library)

    def step(self) -> bytes:
        image = self.png()
        if self.frame + 1 < self.shot.duration_frames:
            self.frame += 1
        return image
