"""Cut-out animation: move a character's approved parts, never redraw the character.

Each controller turns or slides a part about its pivot. The same head, the
same hands, and the same eight mouths appear in every frame, so the character
stays on model for the whole series.
"""

from __future__ import annotations

import math

from PIL import Image

from cuervo_world.house import PLATE_FLOOR, PLATE_SIZE, PLATE_UNIT, SPRITE_SCALE

# Degrees a controller at 1.0 turns its part.
ARM_SWING = 100
ELBOW_BEND = 95
LEG_SWING = 90
TORSO_LEAN = 12
HEAD_TILT = 14
ARM_REST = 8
# Screen pixels per rig unit at camera scale 1, in a frame 640 wide.
UNIT = 0.5

assert PLATE_FLOOR and PLATE_UNIT  # The plate and the stage share these numbers.


class CharacterArt:
    """One character's parts and rig, with a cache of parts already turned and sized."""

    def __init__(self, parts: dict[str, Image.Image], rig: dict):
        self.parts = parts
        self.rig = rig
        self._placed: dict[tuple, tuple[Image.Image, float, float]] = {}

    def placed(self, name: str, scale: float, angle: float, flip: bool) -> tuple[Image.Image, float, float]:
        """The part sized and turned, and where its pivot landed inside that image."""

        key = (name, round(scale, 3), round(angle), flip)
        hit = self._placed.get(key)
        if hit is not None:
            return hit
        sprite = self.parts[name]
        pivot_x, pivot_y = self.rig["parts"][name]["pivot"]
        if flip:
            sprite = sprite.transpose(Image.FLIP_LEFT_RIGHT)
            pivot_x = self.rig["parts"][name]["size"][0] - pivot_x
        ratio = scale / SPRITE_SCALE
        width = max(1, round(sprite.width * ratio))
        height = max(1, round(sprite.height * ratio))
        sized = sprite.resize((width, height), Image.LANCZOS)
        turn = round(angle)
        turned = sized.rotate(-turn, resample=Image.BICUBIC, expand=True) if turn else sized
        offset_x, offset_y = _turn(pivot_x * scale - width / 2, pivot_y * scale - height / 2, turn)
        result = (turned, turned.width / 2 + offset_x, turned.height / 2 + offset_y)
        if len(self._placed) > 4000:
            self._placed.clear()
        self._placed[key] = result
        return result


def _turn(x: float, y: float, degrees: float) -> tuple[float, float]:
    """Rotate clockwise on screen, where y runs down."""

    radians = math.radians(degrees)
    return x * math.cos(radians) - y * math.sin(radians), x * math.sin(radians) + y * math.cos(radians)


def mouth_for(controls: dict[str, float], viseme: str | None) -> str:
    """The drawn mouth to show: the spoken shape, else one that matches how open the pose is."""

    if viseme is not None:
        return viseme
    openness = controls.get("mouth", 0.0) + controls.get("jaw", 0.0) * 0.5
    if openness < 0.12:
        return "rest"
    if openness < 0.35:
        return "EE"
    if openness < 0.6:
        return "OH"
    return "AA"


def draw_character(
    frame: Image.Image,
    art: CharacterArt,
    controls: dict[str, float],
    viseme: str | None,
    hips: tuple[float, float],
    scale: float,
    faces_left: bool,
) -> None:
    """Composite one character. `hips` is in frame pixels and `scale` is pixels per rig unit."""

    rig = art.rig
    side = -1 if faces_left else 1

    def paste(name: str, at: tuple[float, float], angle: float) -> None:
        image, pivot_x, pivot_y = art.placed(name, scale, angle * side, faces_left)
        frame.alpha_composite(image, (round(at[0] - pivot_x), round(at[1] - pivot_y))) if _inside(frame, image, at, pivot_x, pivot_y) else None

    def from_point(origin: tuple[float, float], local: tuple[float, float], angle: float) -> tuple[float, float]:
        x, y = _turn(local[0], local[1], angle)
        return origin[0] + side * x * scale, origin[1] + y * scale

    # A bent leg is shorter, so the hips drop to keep the feet on the floor.
    thigh = rig["knee"][1]
    swing = max(abs(controls.get("leg_l", 0.0)), abs(controls.get("leg_r", 0.0)))
    drop = thigh * (1 - math.cos(math.radians(swing * LEG_SWING))) * _bend(swing)
    root = (hips[0] + side * controls.get("root", 0.0) * 20 * scale, hips[1] + drop * scale)
    lean = controls.get("torso", 0.0) * TORSO_LEAN
    tilt = lean * 0.5 + controls.get("head", 0.0) * HEAD_TILT + controls.get("neck", 0.0) * 6
    shoulder_x, shoulder_y = rig["shoulder"]
    hip_x, hip_y = rig["hip"]

    def arm(which: str, sign: int) -> None:
        shoulder = from_point(root, (sign * shoulder_x, shoulder_y), lean)
        upper = lean - sign * (ARM_REST + controls.get(f"arm_{which}", 0.0) * ARM_SWING)
        paste("upper_arm", shoulder, upper)
        elbow = from_point(shoulder, tuple(rig["elbow"]), upper)
        paste("forearm", elbow, upper - sign * controls.get(f"hand_{which}", 0.0) * ELBOW_BEND)

    def leg(which: str, sign: int) -> None:
        value = controls.get(f"leg_{which}", 0.0)
        hip = from_point(root, (sign * hip_x, hip_y), 0)
        upper = value * LEG_SWING
        paste("thigh", hip, upper)
        # Past a walking stride the knee bends and the shin hangs: that is a sit.
        paste("shin", from_point(hip, tuple(rig["knee"]), upper), upper * (1 - 0.92 * _bend(abs(value))))

    # Far side first, then the body, then the near side.
    arm("l", -1)
    leg("l", -1)
    paste("torso", root, lean)
    leg("r", 1)
    neck = from_point(root, tuple(rig["neck"]), lean)
    paste("head", neck, tilt)
    face = rig["face"]
    look = (controls.get("gaze_yaw", 0.0) * 3, controls.get("gaze_pitch", 0.0) * 2)
    eye = "eye_closed" if controls.get("blink", 0.0) > 0.5 else "eye_open"
    for which in ("l", "r"):
        spot = face[f"eye_{which}"]
        paste(eye, from_point(neck, (spot[0] + look[0], spot[1] + look[1]), tilt), tilt)
        raise_ = controls.get(f"brow_{which}", 0.0)
        brow = face[f"brow_{which}"]
        paste("brow", from_point(neck, (brow[0], brow[1] - raise_ * 5), tilt), tilt - raise_ * 8)
    paste(f"mouth_{mouth_for(controls, viseme)}", from_point(neck, tuple(face["mouth"]), tilt), tilt)
    arm("r", 1)


def _bend(amount: float) -> float:
    """0 for a straight leg, 1 for a seated one."""

    return min(1.0, max(0.0, (amount - 0.42) / 0.15))


def _inside(frame: Image.Image, image: Image.Image, at, pivot_x: float, pivot_y: float) -> bool:
    left, top = at[0] - pivot_x, at[1] - pivot_y
    return left < frame.width and top < frame.height and left + image.width > 0 and top + image.height > 0


def backdrop(plate: Image.Image, size: tuple[int, int], pan: tuple[float, float], zoom: float) -> Image.Image:
    """The part of the set plate the camera sees."""

    width, height = size
    per_pixel = PLATE_SIZE[0] / width  # plate pixels per frame pixel at zoom 1
    view_w, view_h = width / zoom, height / zoom
    left = (width / 2 - view_w / 2 + pan[0]) * per_pixel
    top = (height / 2 - view_h / 2 - pan[1]) * per_pixel
    box_w, box_h = view_w * per_pixel, view_h * per_pixel
    # Keep the view on the plate. A pan past the edge stops at the edge.
    left = min(max(0.0, left), max(0.0, plate.width - box_w))
    top = min(max(0.0, top), max(0.0, plate.height - box_h))
    return plate.resize(size, Image.BILINEAR, box=(left, top, min(plate.width, left + box_w), min(plate.height, top + box_h))).convert("RGBA")
