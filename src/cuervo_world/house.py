"""The house style: flat color, one even line, drawn from a design spec.

This builds every part of a character and a plate for every set with no model
call. Art from another source (an illustrator, an image model) can replace any
part, as long as it keeps the part's size and pivot in `rig.json`.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from cuervo_world.design import CharacterDesign, SetDesign

# Sprite pixels per rig unit, and how much larger parts are drawn before being smoothed down.
SPRITE_SCALE = 2
OVERSAMPLE = 3
LINE = 2.2
INK = (38, 30, 34, 255)

VISEMES = ("rest", "MBP", "FV", "TH", "AA", "EE", "OH", "L")
BUILD_WIDTH = {"slim": 0.86, "average": 1.0, "broad": 1.16}


def rgb(color: str, shade: float = 1.0) -> tuple[int, int, int, int]:
    value = color.lstrip("#")
    parts = [int(value[index : index + 2], 16) for index in (0, 2, 4)]
    return (*(max(0, min(255, int(part * shade))) for part in parts), 255)


class _Canvas:
    """Draw in rig units on an oversampled transparent image."""

    def __init__(self, width: float, height: float):
        self.k = SPRITE_SCALE * OVERSAMPLE
        self.size = (int(width * SPRITE_SCALE), int(height * SPRITE_SCALE))
        self.image = Image.new("RGBA", (self.size[0] * OVERSAMPLE, self.size[1] * OVERSAMPLE), (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.image)

    def _box(self, box):
        return tuple(int(value * self.k) for value in box)

    def rounded(self, box, radius, fill, line: bool = True):
        self.draw.rounded_rectangle(self._box(box), int(radius * self.k), fill=fill, outline=INK if line else None, width=int(LINE * self.k) if line else 0)

    def ellipse(self, box, fill, line: bool = True):
        self.draw.ellipse(self._box(box), fill=fill, outline=INK if line else None, width=int(LINE * self.k) if line else 0)

    def stroke(self, points, width=LINE, fill=INK):
        self.draw.line([(int(x * self.k), int(y * self.k)) for x, y in points], fill=fill, width=int(width * self.k), joint="curve")

    def arc(self, box, start, end, width=LINE):
        self.draw.arc(self._box(box), start, end, fill=INK, width=int(width * self.k))

    def chord(self, box, start, end, fill):
        self.draw.chord(self._box(box), start, end, fill=fill, outline=INK, width=int(LINE * self.k))

    def done(self) -> Image.Image:
        return self.image.resize(self.size, Image.LANCZOS)


def character_parts(design: CharacterDesign) -> tuple[dict[str, Image.Image], dict]:
    """Every part of one character, and the rig that says where each part hangs.

    Sizes and pivots are in rig units. A pivot is the point a part turns about,
    measured from the part's top-left corner.
    """

    wide = BUILD_WIDTH[design.build]
    tall = design.height
    skin, hair = rgb(design.skin), rgb(design.hair)
    top, bottom, shoes = rgb(design.top), rgb(design.bottom), rgb(design.shoes)
    sleeve = top if design.long_sleeves else skin
    parts: dict[str, Image.Image] = {}
    rig: dict = {"units": "rig", "sprite_scale": SPRITE_SCALE, "parts": {}, "face": {}}

    def keep(name: str, canvas: _Canvas, pivot: tuple[float, float], width: float, height: float) -> None:
        parts[name] = canvas.done()
        rig["parts"][name] = {"size": [width, height], "pivot": [pivot[0], pivot[1]]}

    # Torso: turns about the hips, at the bottom center.
    width, height = 72 * wide, 104 * tall
    canvas = _Canvas(width + 8, height + 8)
    canvas.rounded((4, 4, 4 + width, 4 + height), 20, top)
    canvas.rounded((4, 4 + height - 20, 4 + width, 4 + height), 8, bottom)
    keep("torso", canvas, ((width + 8) / 2, height + 2), width + 8, height + 8)
    rig["shoulder"] = [width / 2 - 8, -(height - 14)]
    rig["neck"] = [0, -(height - 4)]
    rig["hip"] = [width / 2 - 20, -4]

    # Head: turns about the neck, at the bottom center. Three-quarter view, facing right.
    width, height = 86, 94
    pad = 14
    canvas = _Canvas(width + pad * 2, height + pad * 2)
    left, upper = pad, pad
    if design.hair_style in ("bob", "curly"):
        canvas.rounded((left - 8, upper + 4, left + width + 2, upper + height - 6), 34, hair)
    if design.hair_style == "bun":
        canvas.ellipse((left + 6, upper - 12, left + 40, upper + 20), hair)
    canvas.rounded((left + 12, upper + height - 20, left + width - 22, upper + height + 8), 6, skin)  # neck
    canvas.rounded((left, upper, left + width, upper + height - 8), 36, skin)
    canvas.ellipse((left - 4, upper + 40, left + 12, upper + 62), skin)  # ear
    if design.hair_style != "bald":
        depth = {"short": 30, "flat": 22, "bob": 34, "bun": 30, "curly": 38}[design.hair_style]
        canvas.chord((left - 2, upper - 4, left + width + 2, upper + depth * 2), 180, 360, hair)
        if design.hair_style == "curly":
            for offset in range(0, 80, 20):
                canvas.ellipse((left + offset - 4, upper - 10, left + offset + 22, upper + 16), hair)
    canvas.stroke([(left + width - 6, upper + 50), (left + width + 4, upper + 60), (left + width - 6, upper + 62)])  # nose
    if design.glasses:
        for center in (left + 40, left + 68):
            canvas.arc((center - 13, upper + 36, center + 13, upper + 60), 0, 360, 1.8)
        canvas.stroke([(left + 53, upper + 47), (left + 55, upper + 47)], 1.8)
    keep("head", canvas, (pad + width / 2 - 4, pad + height + 4), width + pad * 2, height + pad * 2)
    # Where the features sit, from the neck pivot. The face is turned a little toward the far side.
    rig["face"] = {"eye_l": [-10, -52], "eye_r": [22, -52], "brow_l": [-10, -66], "brow_r": [22, -66], "mouth": [10, -26]}

    canvas = _Canvas(20, 22)
    canvas.ellipse((2, 2, 18, 20), (250, 250, 248, 255))
    canvas.ellipse((7, 6, 16, 17), INK, line=False)
    keep("eye_open", canvas, (10, 11), 20, 22)
    canvas = _Canvas(20, 22)
    canvas.arc((2, 4, 18, 18), 20, 160, 2.4)
    keep("eye_closed", canvas, (10, 11), 20, 22)
    canvas = _Canvas(24, 10)
    canvas.stroke([(3, 6), (21, 4)], 3.2, rgb(design.hair, 0.8) if design.hair_style != "bald" else INK)
    keep("brow", canvas, (12, 5), 24, 10)

    for name in VISEMES:
        canvas = _Canvas(40, 30)
        _mouth(canvas, name)
        keep(f"mouth_{name}", canvas, (20, 15), 40, 30)

    # Arms: an upper arm from the shoulder, and a forearm with the hand from the elbow.
    width, height = 24 * wide, 58 * tall
    canvas = _Canvas(width + 6, height + 6)
    canvas.rounded((3, 3, 3 + width, 3 + height), 11, top if design.long_sleeves else sleeve)
    keep("upper_arm", canvas, ((width + 6) / 2, 12), width + 6, height + 6)
    rig["elbow"] = [0, height - 16]
    width, height = 21 * wide, 54 * tall
    canvas = _Canvas(width + 12, height + 24)
    canvas.rounded((6, 3, 6 + width, 3 + height), 10, sleeve)
    canvas.ellipse((2, height - 6, width + 10, height + 20), skin)
    keep("forearm", canvas, ((width + 12) / 2, 10), width + 12, height + 24)

    # Legs: a thigh from the hip, and a shin with the shoe from the knee.
    width, height = 28 * wide, 54 * tall
    canvas = _Canvas(width + 6, height + 6)
    canvas.rounded((3, 3, 3 + width, 3 + height), 13, bottom)
    keep("thigh", canvas, ((width + 6) / 2, 12), width + 6, height + 6)
    rig["knee"] = [0, height - 14]
    width, height = 26 * wide, 52 * tall
    canvas = _Canvas(width + 26, height + 22)
    canvas.rounded((3, 3, 3 + width, 3 + height), 12, bottom)
    canvas.rounded((1, height - 4, width + 22, height + 16), 9, shoes)
    keep("shin", canvas, (3 + width / 2, 10), width + 26, height + 22)
    return parts, rig


def _mouth(canvas: _Canvas, viseme: str) -> None:
    """One drawn mouth per viseme. They share a width so the face does not jump between them."""

    dark, tongue, teeth = (60, 22, 30, 255), (214, 110, 120, 255), (250, 250, 246, 255)
    if viseme == "rest":
        canvas.arc((8, 4, 32, 20), 20, 160, 2.4)
    elif viseme == "MBP":
        canvas.stroke([(9, 15), (31, 15)], 2.8)
    elif viseme == "FV":
        canvas.rounded((10, 11, 30, 21), 4, dark)
        canvas.rounded((12, 11, 28, 15), 2, teeth, line=False)
    elif viseme == "TH":
        canvas.rounded((9, 10, 31, 22), 5, dark)
        canvas.ellipse((14, 14, 26, 23), tongue, line=False)
    elif viseme == "AA":
        canvas.ellipse((8, 3, 32, 28), dark)
        canvas.ellipse((13, 17, 27, 27), tongue, line=False)
    elif viseme == "EE":
        canvas.rounded((6, 9, 34, 21), 6, dark)
        canvas.rounded((9, 10, 31, 15), 2, teeth, line=False)
    elif viseme == "OH":
        canvas.ellipse((12, 5, 28, 26), dark)
    else:  # L
        canvas.rounded((9, 8, 31, 23), 6, dark)
        canvas.ellipse((14, 9, 26, 17), tongue, line=False)


PLATE_SIZE = (1920, 1080)
# Stage units to plate pixels, and where the floor line sits. The renderer uses the same numbers.
PLATE_UNIT = 2.1
PLATE_FLOOR = 0.80


def set_plate(design: SetDesign) -> Image.Image:
    """A background plate. Wider than the frame, so the camera can pan and push in."""

    width, height = PLATE_SIZE
    shade = {"day": 1.0, "evening": 0.82, "night": 0.6}[design.time]
    image = Image.new("RGB", PLATE_SIZE, rgb(design.wall, shade)[:3])
    draw = ImageDraw.Draw(image)
    floor = int(height * PLATE_FLOOR)
    if design.kind == "exterior":
        draw.rectangle((0, 0, width, floor), fill=rgb(design.wall, shade)[:3])
        draw.ellipse((width * 0.72, 90, width * 0.72 + 150, 240), fill=rgb("#fff2c2" if design.time != "night" else "#dfe6f2", shade + 0.1)[:3])
    else:
        draw.rectangle((0, floor - 34, width, floor), fill=rgb(design.wall, shade * 0.86)[:3])  # baseboard
    draw.rectangle((0, floor, width, height), fill=rgb(design.floor, shade)[:3])
    draw.line((0, floor, width, floor), fill=INK[:3], width=4)

    def at(x: float) -> int:
        return int(width / 2 + x * PLATE_UNIT)

    for item in design.furniture:
        color = rgb(item.color or design.accent, shade)[:3]
        dark = rgb(item.color or design.accent, shade * 0.8)[:3]
        left, right = at(item.x - item.width / 2), at(item.x + item.width / 2)
        if item.kind == "sofa":
            draw.rounded_rectangle((left, floor - 330, right, floor - 60), 46, fill=dark, outline=INK[:3], width=5)
            draw.rounded_rectangle((left - 30, floor - 220, right + 30, floor + 20), 40, fill=color, outline=INK[:3], width=5)
            draw.line((left + 20, floor - 110, right - 20, floor - 110), fill=INK[:3], width=4)
        elif item.kind in ("table", "counter"):
            top_y = floor - (150 if item.kind == "table" else 260)
            draw.rounded_rectangle((left, top_y, right, top_y + 34), 10, fill=color, outline=INK[:3], width=5)
            draw.rectangle((left + 24, top_y + 34, left + 54, floor + 30), fill=dark, outline=INK[:3], width=4)
            draw.rectangle((right - 54, top_y + 34, right - 24, floor + 30), fill=dark, outline=INK[:3], width=4)
        elif item.kind == "window":
            draw.rounded_rectangle((left, 150, right, 520), 12, fill=rgb("#bcd9ee" if design.time == "day" else "#f0c48a" if design.time == "evening" else "#2c3a5c")[:3], outline=INK[:3], width=6)
            draw.line(((left + right) // 2, 150, (left + right) // 2, 520), fill=INK[:3], width=5)
        elif item.kind == "door":
            draw.rounded_rectangle((left, 190, right, floor), 8, fill=color, outline=INK[:3], width=6)
            draw.ellipse((right - 44, floor - 330, right - 22, floor - 308), fill=dark, outline=INK[:3], width=3)
        elif item.kind == "lamp":
            middle = (left + right) // 2
            draw.line((middle, floor, middle, floor - 420), fill=INK[:3], width=8)
            draw.polygon([(middle - 70, floor - 420), (middle + 70, floor - 420), (middle + 44, floor - 540), (middle - 44, floor - 540)], fill=color, outline=INK[:3])
        elif item.kind == "frame":
            draw.rectangle((left, 220, right, 220 + int((right - left) * 0.7)), fill=color, outline=INK[:3], width=8)
        elif item.kind == "rug":
            draw.ellipse((left, floor + 40, right, floor + 150), fill=color, outline=INK[:3], width=4)
        elif item.kind == "screen":
            draw.rounded_rectangle((left, floor - 360, right, floor - 110), 10, fill=(22, 24, 30), outline=INK[:3], width=6)
            draw.rectangle(((left + right) // 2 - 40, floor - 110, (left + right) // 2 + 40, floor - 60), fill=dark, outline=INK[:3], width=4)
        else:  # tree
            middle = (left + right) // 2
            draw.rectangle((middle - 22, floor - 300, middle + 22, floor), fill=rgb("#6b4a33", shade)[:3], outline=INK[:3], width=5)
            draw.ellipse((left, floor - 620, right, floor - 240), fill=color, outline=INK[:3], width=5)
    return image
