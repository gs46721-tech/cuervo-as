"""A stand-in for what an image model returns for a character. Not a series."""

from io import BytesIO

from PIL import Image, ImageDraw

INK = (30, 24, 28)


def painted_character(skin, hair, top, bottom, *, arms_apart: bool = True, legs_apart: bool = True) -> bytes:
    """A front-view figure on a green background, in the pose the character prompt asks for."""

    image = Image.new("RGB", (1024, 1536), (20, 235, 40))
    draw = ImageDraw.Draw(image)
    cx = 512
    draw.rounded_rectangle((cx - 150, 480, cx + 150, 900), 60, fill=top, outline=INK, width=8)
    draw.rounded_rectangle((cx - 150, 840, cx + 150, 930), 20, fill=bottom, outline=INK, width=8)
    for side in (-1, 1):
        arm = cx + side * (235 if arms_apart else 185)
        draw.rounded_rectangle((arm - 42, 500, arm + 42, 880), 40, fill=top, outline=INK, width=8)
        draw.ellipse((arm - 46, 850, arm + 46, 950), fill=skin, outline=INK, width=8)
        draw.polygon([(cx + side * 150, 500), (arm - side * 40, 500), (arm - side * 40, 560), (cx + side * 150, 600)], fill=top, outline=INK)
        leg = cx + side * (80 if legs_apart else 52)
        draw.rounded_rectangle((leg - 58, 900, leg + 58, 1400), 40, fill=bottom, outline=INK, width=8)
        draw.rounded_rectangle((leg - 70, 1370, leg + 80, 1440), 30, fill=(25, 25, 30), outline=INK, width=8)
    draw.rounded_rectangle((cx - 50, 400, cx + 50, 500), 10, fill=skin, outline=INK, width=8)
    draw.ellipse((cx - 170, 90, cx + 170, 440), fill=skin, outline=INK, width=8)
    draw.pieslice((cx - 180, 70, cx + 180, 400), 180, 360, fill=hair, outline=INK, width=8)
    for side in (-1, 1):
        draw.ellipse((cx + side * 60 - 26, 255, cx + side * 60 + 26, 305), fill=(250, 250, 250), outline=INK, width=5)
        draw.ellipse((cx + side * 60 - 10, 268, cx + side * 60 + 10, 296), fill=INK)
    draw.arc((cx - 50, 330, cx + 50, 385), 20, 160, fill=INK, width=7)
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()
