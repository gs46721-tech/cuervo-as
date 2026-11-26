"""Turn one painted picture of a character into parts that can be animated.

An image model paints the character once: standing, facing the viewer, arms
held away from the body, legs apart, on a plain background. This module finds
the figure, finds where the arms and legs separate from the body, and cuts it
at the neck, shoulders, elbows, hips, and knees. The result is the same kind
of parts and rig the house style builds, so the renderer treats both alike.

The painted face is kept. A blink and a spoken mouth are drawn over it on a
patch of the character's own skin color.
"""

from __future__ import annotations

from statistics import median

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from cuervo_world.design import CharacterDesign
from cuervo_world.house import SPRITE_SCALE, VISEMES, _Canvas, _mouth

# A figure this many rig units tall matches the house style at height 1.0.
FIGURE_UNITS = 290.0
SENTINEL = (1, 254, 3)
BACKGROUND_TOLERANCE = 60


class CutError(ValueError):
    """The picture cannot be cut. The text says why, for whoever asked for it."""


def remove_background(picture: Image.Image) -> Image.Image:
    """Clear everything connected to the border that is close to the border's color.

    Filling in from the edges keeps a white shirt or the whites of the eyes
    even when the background is also light.
    """

    rgb = picture.convert("RGB")
    work = rgb.copy()
    width, height = work.size
    seeds = [(x, y) for x in (0, width // 2, width - 1) for y in (0, height // 2, height - 1) if (x, y) != (width // 2, height // 2)]
    for seed in seeds:
        if work.getpixel(seed) != SENTINEL:
            ImageDraw.floodfill(work, seed, SENTINEL, thresh=BACKGROUND_TOLERANCE)
    marked = work.point(lambda value: value)  # copy
    red, green, blue = marked.split()
    background = ImageChops.multiply(
        ImageChops.multiply(red.point(lambda v: 255 if v == SENTINEL[0] else 0), green.point(lambda v: 255 if v == SENTINEL[1] else 0)),
        blue.point(lambda v: 255 if v == SENTINEL[2] else 0),
    )
    # Pull the edge in a pixel so no background-colored fringe is left on the outline.
    alpha = ImageChops.invert(background).filter(ImageFilter.MinFilter(3))
    figure = rgb.convert("RGBA")
    figure.putalpha(alpha)
    box = alpha.getbbox()
    if box is None:
        raise CutError("The picture is all background. There is no character in it.")
    figure = figure.crop(box)
    if figure.height < 200 or figure.width < 60:
        raise CutError("The character is too small in the picture to cut out.")
    return figure


def _runs(row: bytes, low: int, high: int) -> list[tuple[int, int]]:
    """Stretches of the figure along one row, between two columns."""

    found: list[tuple[int, int]] = []
    start = None
    for x in range(low, high):
        solid = row[x] > 96
        if solid and start is None:
            start = x
        elif not solid and start is not None:
            if x - start >= 3:
                found.append((start, x))
            start = None
    if start is not None and high - start >= 3:
        found.append((start, high))
    return found


def cut_character(picture: Image.Image, design: CharacterDesign) -> tuple[dict[str, Image.Image], dict]:
    """Parts and rig from a painted reference. Raises CutError when the pose cannot be read."""

    figure = remove_background(picture)
    width, height = figure.size
    alpha = figure.getchannel("A")
    data = alpha.tobytes()
    rows = [data[y * width : (y + 1) * width] for y in range(height)]
    all_runs = [_runs(row, 0, width) for row in rows]

    # The arms: rows where the figure is in three pieces, between the head and the hips.
    upper = range(int(height * 0.18), int(height * 0.62))
    three = [y for y in upper if len(all_runs[y]) >= 3]
    if len(three) < height * 0.08:
        raise CutError("The arms touch the body in this picture, so they cannot be cut free. Ask for arms held away from the sides.")
    gap_left = int(median((all_runs[y][0][1] + all_runs[y][1][0]) / 2 for y in three))
    gap_right = int(median((all_runs[y][-2][1] + all_runs[y][-1][0]) / 2 for y in three))
    if gap_right - gap_left < width * 0.15:
        raise CutError("The body could not be told apart from the arms in this picture.")

    # The body between the arms: one piece is torso, two pieces are legs.
    middle = [_runs(row, gap_left, gap_right) for row in rows]
    lower = range(int(height * 0.40), height - 2)
    two = [y for y in lower if len(middle[y]) == 2]
    if len(two) < height * 0.15:
        raise CutError("The legs are together in this picture, so they cannot be cut apart. Ask for legs set apart.")
    crotch = two[0]
    leg_gap = int(median((middle[y][0][1] + middle[y][1][0]) / 2 for y in two))

    # The neck: the narrowest row between the widest part of the head and the shoulders.
    widths = [sum(end - start for start, end in middle[y]) for y in range(height)]
    head_rows = range(0, max(4, int(height * 0.22)))
    widest = max(head_rows, key=lambda y: widths[y])
    neck_rows = range(widest, max(widest + 2, min(three[0] + 1, int(height * 0.40))))
    neck = min(neck_rows, key=lambda y: (widths[y] if widths[y] else 10**6, -y))
    if not 0.08 * height < neck < 0.40 * height:
        raise CutError("The head and shoulders could not be found in this picture.")

    def box_of(left: int, top: int, right: int, bottom: int) -> tuple[int, int, int, int]:
        region = alpha.crop((left, top, right, bottom)).getbbox()
        if region is None:
            raise CutError("A part of the character came out empty. The pose may be too far from standing straight.")
        return left + region[0], top + region[1], left + region[2], top + region[3]

    overlap = max(4, height // 60)
    # The torso is as wide as the body is where the arms hang free, so no stub of shoulder sticks out past it.
    body_left = int(median(all_runs[y][1][0] for y in three)) - 1
    body_right = int(median(all_runs[y][-2][1] for y in three)) + 1
    torso_box = box_of(max(gap_left, body_left), neck, min(gap_right, body_right), min(height, crotch + overlap))
    head_box = box_of(0, 0, width, neck + overlap)
    # The arm starts where it comes free of the body. What joins it to the shoulder stays with the torso.
    # Its inner edge is the arm's own edge, so no sliver of the shoulder comes with it.
    arm_left = min(all_runs[y][-1][0] for y in three) - 1
    arm_box = box_of(max(gap_right, arm_left), max(neck, three[0] - overlap * 2), width, height)
    leg_box = box_of(leg_gap, max(0, crotch - overlap), gap_right, height)
    if arm_box[3] - arm_box[1] < height * 0.15 or leg_box[3] - leg_box[1] < height * 0.25:
        raise CutError("An arm or a leg came out too short. The pose may be too far from standing straight.")
    elbow_y = (arm_box[1] + arm_box[3]) // 2
    knee_y = (leg_box[1] + leg_box[3]) // 2 - (leg_box[3] - leg_box[1]) // 20

    units_per_pixel = FIGURE_UNITS * design.height / height
    parts: dict[str, Image.Image] = {}
    rig: dict = {"units": "rig", "sprite_scale": SPRITE_SCALE, "source": "painted", "face_mode": "painted", "parts": {}, "face": {}}

    def keep(name: str, box: tuple[int, int, int, int], pivot: tuple[float, float], blank: tuple = ()) -> None:
        """Save a slice. `pivot` is in picture pixels. `blank` lists rectangles that belong to another part."""

        piece = figure.crop(box)
        for left, top, right, bottom in blank:
            if right > left and bottom > top:
                piece.paste(Image.new("RGBA", (right - left, bottom - top), (0, 0, 0, 0)), (left - box[0], top - box[1]))
        size = (max(1, round(piece.width * units_per_pixel * SPRITE_SCALE)), max(1, round(piece.height * units_per_pixel * SPRITE_SCALE)))
        # Resize with color weighted by coverage, so the cleared background cannot tint the outline.
        parts[name] = piece.convert("RGBa").resize(size, Image.LANCZOS).convert("RGBA")
        rig["parts"][name] = {
            "size": [size[0] / SPRITE_SCALE, size[1] / SPRITE_SCALE],
            "pivot": [(pivot[0] - box[0]) * units_per_pixel, (pivot[1] - box[1]) * units_per_pixel],
        }

    def units(dx: float, dy: float) -> list[float]:
        return [round(dx * units_per_pixel, 2), round(dy * units_per_pixel, 2)]

    hips = ((torso_box[0] + torso_box[2]) / 2, float(crotch))
    keep("torso", torso_box, hips)
    neck_x = sum(sum(run) / 2 for run in middle[neck]) / max(1, len(middle[neck])) if middle[neck] else hips[0]
    # Below the neck line the head keeps only the neck itself, not the tops of the shoulders.
    neck_run = middle[neck][0] if middle[neck] else (int(neck_x) - 4, int(neck_x) + 4)
    keep(
        "head",
        head_box,
        (neck_x, float(neck)),
        blank=((0, neck, neck_run[0] - 1, neck + overlap + 1), (neck_run[1] + 1, neck, width, neck + overlap + 1)),
    )
    rig["neck"] = units(neck_x - hips[0], neck - crotch)

    arm_width = arm_box[2] - arm_box[0]
    shoulder = ((arm_box[0] + arm_box[2]) / 2, arm_box[1] + arm_width * 0.5)
    # Above where the arm comes free, whatever lies inside its own edge is shoulder and stays with the torso.
    free = three[: max(3, len(three) // 8)]
    arm_edge = int(median(all_runs[y][-1][0] for y in free))
    keep("upper_arm", (arm_box[0], arm_box[1], arm_box[2], elbow_y + overlap), shoulder, blank=((arm_box[0], arm_box[1], arm_edge, three[0]),))
    keep("forearm", (arm_box[0], elbow_y - overlap, arm_box[2], arm_box[3]), (shoulder[0], float(elbow_y)))
    rig["shoulder"] = units(shoulder[0] - hips[0], shoulder[1] - crotch)
    rig["elbow"] = units(0, elbow_y - shoulder[1])

    leg_width = leg_box[2] - leg_box[0]
    hip = ((leg_box[0] + leg_box[2]) / 2, crotch + leg_width * 0.3)
    keep("thigh", (leg_box[0], leg_box[1], leg_box[2], knee_y + overlap), hip)
    keep("shin", (leg_box[0], knee_y - overlap, leg_box[2], leg_box[3]), (hip[0], float(knee_y)))
    rig["hip"] = units(hip[0] - hips[0], hip[1] - crotch)
    rig["knee"] = units(0, knee_y - hip[1])

    # The face. Features sit where a face drawn straight-on usually has them.
    head_w, head_h = head_box[2] - head_box[0], neck - head_box[1]
    head_cx = (head_box[0] + head_box[2]) / 2
    eye_y, mouth_y = head_box[1] + head_h * 0.52, head_box[1] + head_h * 0.76
    rig["face"] = {
        "eye_l": units(head_cx - head_w * 0.17 - neck_x, eye_y - neck),
        "eye_r": units(head_cx + head_w * 0.17 - neck_x, eye_y - neck),
        "mouth": units(head_cx - neck_x, mouth_y - neck),
    }
    cheek = figure.crop((int(head_cx + head_w * 0.10), int(head_box[1] + head_h * 0.62), int(head_cx + head_w * 0.24), int(head_box[1] + head_h * 0.70)))
    skin = _median_color(cheek)
    face_scale = head_w * units_per_pixel / 86  # the house head is 86 units wide

    def feature(name: str, canvas_size: tuple[float, float], draw) -> None:
        canvas = _Canvas(*canvas_size)
        draw(canvas)
        image = canvas.done()
        size = (max(1, round(image.width * face_scale)), max(1, round(image.height * face_scale)))
        parts[name] = image.resize(size, Image.LANCZOS)
        rig["parts"][name] = {"size": [size[0] / SPRITE_SCALE, size[1] / SPRITE_SCALE], "pivot": [size[0] / SPRITE_SCALE / 2, size[1] / SPRITE_SCALE / 2]}

    feature("eye_patch", (26, 20), lambda canvas: canvas.ellipse((1, 1, 25, 19), skin, line=False))
    feature("eye_closed", (20, 22), lambda canvas: canvas.arc((2, 4, 18, 18), 20, 160, 2.4))
    # Just large enough to hide a closed painted mouth, and small enough to stay inside the chin.
    feature("mouth_patch", (36, 18), lambda canvas: canvas.ellipse((1, 1, 35, 17), skin, line=False))
    mouth_scale = face_scale
    for viseme in VISEMES:
        face_scale = mouth_scale * 0.8
        feature(f"mouth_{viseme}", (40, 30), lambda canvas, name=viseme: _mouth(canvas, name))
    return parts, rig


def _median_color(patch: Image.Image) -> tuple[int, int, int, int]:
    raw = patch.convert("RGBA").tobytes()
    pixels = [raw[index : index + 4] for index in range(0, len(raw), 4) if raw[index + 3] > 200]
    if not pixels:
        return (224, 172, 132, 255)
    return (*(int(median(pixel[channel] for pixel in pixels)) for channel in range(3)), 255)
