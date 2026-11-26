"""The series kit: the cast, their voices, the sets, and the pose table.

It is a document the project supplies. Nothing here names a show.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cuervo_ir.contract import allowed_poses
from cuervo_ir.models import Id, Version
from cuervo_voice.dub import VoiceProfile
from cuervo_world.design import CharacterDesign, SetDesign


class KitVoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["fixture", "elevenlabs"]
    provider_voice_id: str = Field(min_length=1)
    consent: str = Field(min_length=1)
    pronunciation: dict[str, str] = Field(default_factory=dict)
    model_id: str | None = None
    settings: dict[str, float | bool] = Field(default_factory=dict)


class KitCharacter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: Id
    display_name: str = Field(min_length=1)
    # Other names a script may use in a speaker cue.
    aliases: list[str] = Field(default_factory=list)
    version: Version = "1.0.0"
    rig_id: Id
    rig_version: Version = "1.0.0"
    extension_poses: list[Id] = Field(default_factory=list)
    # The body pose held when nothing else is happening.
    rest_pose: Id = "stand"
    voice: KitVoice
    # What the character looks like. Their art is built from this once and reused in every frame.
    design: CharacterDesign | None = None

    def profile(self) -> VoiceProfile:
        return VoiceProfile(character_id=self.asset_id, **self.voice.model_dump())

    def names(self) -> list[str]:
        first = self.display_name.split()[0]
        return [self.display_name, first, *self.aliases]


class KitSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: Id
    display_name: str = Field(min_length=1)
    location_id: Id
    version: Version = "1.0.0"
    aliases: list[str] = Field(default_factory=list)
    design: SetDesign | None = None


class SeriesKit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["series_kit"] = "series_kit"
    title: str = Field(min_length=1)
    fps: int = Field(default=24, ge=1, le=60)
    bible: list[str] = Field(default_factory=list)
    characters: list[KitCharacter] = Field(min_length=1)
    sets: list[KitSet] = Field(min_length=1)
    # Controller values for the series' own poses.
    poses: dict[str, dict[str, float]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def poses_resolve(self) -> SeriesKit:
        for character in self.characters:
            if character.rest_pose not in allowed_poses(character.extension_poses):
                raise ValueError(f"{character.asset_id} rest pose {character.rest_pose} is not one of its poses")
            for pose in character.extension_poses:
                if pose not in self.poses:
                    raise ValueError(f"{character.asset_id} pose {pose} is missing from the kit's pose table")
        return self

    def character(self, asset_id: str) -> KitCharacter:
        for character in self.characters:
            if character.asset_id == asset_id:
                return character
        raise KeyError(asset_id)


def load_kit(path: Path) -> SeriesKit:
    return SeriesKit.model_validate(json.loads(path.read_text(encoding="utf-8")))


def slug(text: str, prefix: str) -> str:
    body = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "x"
    return f"{prefix}_{body}"[:48].rstrip("_")
