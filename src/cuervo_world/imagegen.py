"""Image models that paint set backgrounds.

A set's design is turned into one prompt. Each model in the image role paints
a candidate from it. The candidates are kept side by side so a person picks.
Characters are not painted this way: they are built from parts so they can be
animated and stay on model.
"""

from __future__ import annotations

import base64
import json
import os
from io import BytesIO
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image

from cuervo_world.design import SetDesign
from cuervo_world.house import PLATE_SIZE


class ImageError(RuntimeError):
    pass


class ImageEngine(Protocol):
    name: str
    default_model: str

    def available(self) -> bool: ...

    def paint(self, prompt: str, model: str | None = None) -> bytes: ...


STYLE = (
    "A background plate for a 2D animated sitcom. Flat local color, one clean even dark outline, no gradients, "
    "no texture, no lighting effects. Straight-on view of the whole room, wide 16:9. No people, no animals, "
    "no text, no logos. The floor meets the back wall along a straight horizontal line about four fifths of "
    "the way down the picture, and the middle of the floor is left clear for characters to stand."
)


def set_prompt(name: str, design: SetDesign, bible: list[str] | None = None) -> str:
    """The one prompt every image model gets for a set, so their pictures can be compared fairly."""

    parts = [STYLE, f"The set: {name}."]
    if design.description:
        parts.append(design.description)
    parts.append(f"{design.kind.capitalize()}, {design.time}. Wall color {design.wall}, floor color {design.floor}, accent color {design.accent}.")
    if design.furniture:
        spots = []
        for item in design.furniture:
            where = "in the center" if abs(item.x) < 90 else "on the left" if item.x < 0 else "on the right"
            spots.append(f"a {item.kind} {where}")
        parts.append("It has " + ", ".join(spots) + ".")
    if bible:
        parts.append("About the show: " + " ".join(bible[:4]))
    return " ".join(parts)


CHARACTER_STYLE = (
    "A full-body character design for a 2D animated sitcom, drawn as a reference to be cut into a paper puppet. "
    "One character only, standing upright and facing the viewer, head level. Both arms hang straight down and are "
    "held clearly away from the body, so empty background shows between each arm and the torso from shoulder to "
    "hand. The legs are straight and set apart, so empty background shows between them from the hips to the shoes. "
    "Hands open, feet flat. Neutral face, mouth closed, eyes open. Flat local color, one clean even dark outline, "
    "no shading, no gradients, no shadow on the ground, no text, no props. The background is one plain solid bright "
    "green and nothing else. The whole figure, from the top of the hair to the soles of the shoes, is inside the "
    "picture with a margin all round."
)


def character_prompt(name: str, design, bible: list[str] | None = None) -> str:
    """The one prompt every image model gets for a character."""

    hair = "a bald head" if design.hair_style == "bald" else f"{design.hair_style} hair, color {design.hair}"
    sleeves = "long sleeves" if design.long_sleeves else "short sleeves"
    parts = [
        CHARACTER_STYLE,
        f"The character: {name}.",
        design.description,
        f"{design.build.capitalize()} build. Skin color {design.skin}, {hair}. A top in {design.top} with {sleeves}, "
        f"trousers in {design.bottom}, shoes in {design.shoes}.{' Wears glasses.' if design.glasses else ''}",
    ]
    if bible:
        parts.append("About the show: " + " ".join(bible[:4]))
    return " ".join(part for part in parts if part)


def to_picture(raw: bytes) -> Image.Image:
    try:
        return Image.open(BytesIO(raw)).convert("RGB")
    except Exception as exc:
        raise ImageError("the image model did not return a picture") from exc


def to_plate(raw: bytes) -> Image.Image:
    """Any picture a model returns, cropped to 16:9 and sized as a plate."""

    try:
        image = Image.open(BytesIO(raw)).convert("RGB")
    except Exception as exc:
        raise ImageError("the image model did not return a picture") from exc
    target = PLATE_SIZE[0] / PLATE_SIZE[1]
    width, height = image.size
    if width / height > target:
        crop = int(height * target)
        left = (width - crop) // 2
        image = image.crop((left, 0, left + crop, height))
    else:
        crop = int(width / target)
        # Keep the floor: take the crop from the bottom of a tall picture.
        image = image.crop((0, height - crop, width, height))
    return image.resize(PLATE_SIZE, Image.LANCZOS)


def _post(url: str, headers: dict[str, str], body: dict) -> dict:
    request = Request(url, data=json.dumps(body).encode("utf-8"), headers={"content-type": "application/json", **headers}, method="POST")
    try:
        with urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ImageError(f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:300]}") from exc
    except (URLError, json.JSONDecodeError) as exc:
        raise ImageError(str(getattr(exc, "reason", exc))) from exc


class GeminiImage:
    name = "gemini"
    default_model = "gemini-2.5-flash-image"

    def __init__(self, api_key: str | None = None, transport=None):
        self.api_key = os.environ.get("GEMINI_API_KEY", "") if api_key is None else api_key
        self.base_url = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com").rstrip("/")
        self.transport = transport

    def available(self) -> bool:
        return bool(self.api_key)

    def paint(self, prompt: str, model: str | None = None) -> bytes:
        chosen = model or os.environ.get("GEMINI_IMAGE_MODEL", self.default_model)
        url = f"{self.base_url}/v1beta/models/{chosen}:generateContent"
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": {"responseModalities": ["IMAGE"]}}
        payload = (self.transport or _post)(url, {"x-goog-api-key": self.api_key}, body)
        try:
            for part in payload["candidates"][0]["content"]["parts"]:
                data = part.get("inlineData") or part.get("inline_data")
                if data and data.get("data"):
                    return base64.b64decode(data["data"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ImageError("gemini returned no picture") from exc
        raise ImageError("gemini returned no picture")


class OpenAIImage:
    name = "openai"
    default_model = "gpt-image-1"

    def __init__(self, api_key: str | None = None, transport=None):
        self.api_key = os.environ.get("OPENAI_API_KEY", "") if api_key is None else api_key
        self.base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.transport = transport

    def available(self) -> bool:
        return bool(self.api_key)

    def paint(self, prompt: str, model: str | None = None) -> bytes:
        chosen = model or os.environ.get("OPENAI_IMAGE_MODEL", self.default_model)
        body = {"model": chosen, "prompt": prompt, "size": "1536x1024", "n": 1}
        payload = (self.transport or _post)(f"{self.base_url}/images/generations", {"authorization": f"Bearer {self.api_key}"}, body)
        try:
            return base64.b64decode(payload["data"][0]["b64_json"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ImageError("openai returned no picture") from exc


def default_engines() -> dict[str, ImageEngine]:
    return {"gemini": GeminiImage(), "openai": OpenAIImage()}
