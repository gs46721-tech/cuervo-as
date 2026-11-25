"""Deterministic flat 2D frames. No window, no series palette."""

from __future__ import annotations

import hashlib
from io import BytesIO

from PIL import Image, ImageDraw

from cuervo_ir.models import Episode, Shot

from cuervo_runtime.mixer import controls_at

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
    image = Image.new("RGB", (WIDTH, HEIGHT), _swatch(shot_background(episode, shot)))
    draw = ImageDraw.Draw(image)
    _camera_frame(draw, shot)
    for actor in sorted(shot.actors, key=lambda item: item.depth):
        if not actor.visible:
            continue
        controls = controls_at(shot, actor.actor_id, frame, library)
        _draw_actor(draw, actor, controls)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def shot_background(episode: Episode, shot: Shot) -> str:
    for ref in shot.asset_refs:
        if ref.role == "background":
            return ref.asset_id
    return episode.scenes[0].setting_id


def _swatch(key: str) -> tuple[int, int, int]:
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return tuple(48 + byte % 160 for byte in digest[:3])


def _camera_frame(draw: ImageDraw.ImageDraw, shot: Shot) -> None:
    scale = shot.camera.transform.scale
    left = int(WIDTH * (1 - min(scale, 2.4) / 2.4) / 2)
    top = int(40 + (scale - 1) * 30)
    draw.rectangle((left, top, WIDTH - left - 1, HEIGHT - 20), outline=(255, 255, 255))


def _draw_actor(draw: ImageDraw.ImageDraw, actor, controls: dict[str, float]) -> None:
    origin_x = int(WIDTH / 2 + actor.stage.x * 0.7 + controls["root"] * 20)
    origin_y = int(HEIGHT * 0.72 - actor.stage.y * 0.4 - controls["torso"] * 16)
    color = _swatch(actor.character_id)
    facing = -1 if "left" in actor.facing else 1
    leg = 28 + int(controls["leg_l"] * 10)
    draw.line((origin_x - 10, origin_y, origin_x - 10, origin_y + leg), fill=color, width=4)
    draw.line((origin_x + 10, origin_y, origin_x + 10, origin_y + leg), fill=color, width=4)
    torso_box = (origin_x - 16, origin_y - 48, origin_x + 16, origin_y)
    draw.rectangle(torso_box, fill=color)
    arm_y = origin_y - 36
    draw.line(
        (origin_x - 16, arm_y, origin_x - 16 - facing * int(18 + controls["arm_l"] * 24), arm_y - int(controls["hand_l"] * 20)),
        fill=color,
        width=3,
    )
    draw.line(
        (origin_x + 16, arm_y, origin_x + 16 + facing * int(18 + controls["arm_r"] * 24), arm_y - int(controls["hand_r"] * 20)),
        fill=color,
        width=3,
    )
    head_y = origin_y - 70 - int(controls["head"] * 8)
    draw.ellipse((origin_x - 14, head_y - 14, origin_x + 14, head_y + 14), fill=color)
    eye_h = max(1, int(4 * (1 - controls["blink"])))
    gaze = int(controls["gaze_yaw"] * 4)
    for side in (-5, 5):
        draw.rectangle((origin_x + side + gaze - 2, head_y - eye_h, origin_x + side + gaze + 2, head_y + eye_h), fill=(250, 250, 250))
    mouth_h = 2 + int(controls["mouth"] * 8) + int(controls["jaw"] * 6)
    draw.rectangle((origin_x - 5, head_y + 4, origin_x + 5, head_y + 4 + mouth_h), fill=(30, 30, 30))


class FramePlayer:
    """Frame-steppable preview. `step` returns the current frame, then advances."""

    def __init__(self, episode: Episode, shot_id: str, library: dict[str, dict[str, float]] | None = None):
        self.episode = episode
        self.shot = next(shot for scene in episode.scenes for shot in scene.shots if shot.shot_id == shot_id)
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
