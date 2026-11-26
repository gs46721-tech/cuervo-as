"""Design specs: what a character or a set looks like, as data.

A spec is written once in the series kit. Art is built from it once, and every
frame of every episode reuses that art, so a character cannot drift off model.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Color = str  # "#rrggbb"


class CharacterDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = ""
    skin: Color = "#e0a878"
    hair: Color = "#2b2118"
    hair_style: Literal["short", "bob", "bun", "curly", "flat", "bald"] = "short"
    top: Color = "#3f6fb5"
    bottom: Color = "#2f3542"
    shoes: Color = "#1d1d21"
    long_sleeves: bool = True
    build: Literal["slim", "average", "broad"] = "average"
    # 1.0 is the house height. Keep the cast within about 0.85 to 1.15.
    height: float = Field(default=1.0, ge=0.7, le=1.3)
    glasses: bool = False


class Furniture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["sofa", "table", "counter", "window", "door", "lamp", "frame", "rug", "tree", "screen"]
    # Stage position in the same units as an actor's stage x. 0 is center.
    x: float = 0
    width: float = 200
    color: Color | None = None


class SetDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = ""
    kind: Literal["interior", "exterior"] = "interior"
    wall: Color = "#cdbfa9"
    floor: Color = "#8a6f57"
    accent: Color = "#7a8f8a"
    time: Literal["day", "evening", "night"] = "day"
    furniture: list[Furniture] = Field(default_factory=list)


def digest(spec: BaseModel) -> str:
    """Changes when the look changes. A new look needs a new asset version."""

    return hashlib.sha256(json.dumps(spec.model_dump(mode="json"), sort_keys=True).encode("utf-8")).hexdigest()[:16]
