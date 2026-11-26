"""Dialogue to a voice take, alignment, and viseme track.

Provider voice ids and consent live on the profile the caller passes in.
The episode only stores the take id, the timing, and the visemes.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cuervo_ir.frame_time import frame_to_sample_start
from cuervo_ir.models import DialogueTrack, Episode
from cuervo_ir.providers.router import ModelRequest, ProviderRouter, ProviderUnavailable
from cuervo_voice.align import align_line
from cuervo_voice.synth import VoiceError, VoiceSynth, default_synths
from cuervo_voice.visemes import VISEMES, viseme_keys

SAMPLE_RATE = 48_000


class VoiceProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_id: str
    provider: Literal["fixture", "elevenlabs"]
    provider_voice_id: str = Field(min_length=1)
    consent: str = Field(min_length=1)
    pronunciation: dict[str, str] = Field(default_factory=dict)
    # Vendor model and voice settings (ElevenLabs: stability, similarity_boost, style, speed).
    model_id: str | None = None
    settings: dict[str, float | bool] = Field(default_factory=dict)


class TakeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    take_id: str
    line_id: str
    speaker_actor_id: str
    character_id: str
    provider: str
    provider_voice_id: str
    emotion: str
    prep: Literal["router", "fallback"]
    sample_rate: int
    consent: str
    wav: bytes


class DubError(ValueError):
    pass


def dub_episode(
    episode: Episode,
    profiles: list[VoiceProfile],
    *,
    router: ProviderRouter | None = None,
    synths: dict[str, VoiceSynth] | None = None,
) -> tuple[Episode, list[TakeRecord]]:
    by_character = {profile.character_id: profile for profile in profiles}
    if len(by_character) != len(profiles):
        raise DubError("duplicate voice profile")
    engines: dict[str, VoiceSynth] = default_synths()
    if synths:
        engines.update(synths)
    data = episode.model_dump(mode="json")
    takes: list[TakeRecord] = []
    for scene in data["scenes"]:
        fps = episode.fps
        for shot in scene["shots"]:
            actors = {actor["actor_id"]: actor for actor in shot["actors"]}
            locked = {
                lock["target_track_id"]
                for lock in shot["locks"]
                if "dialogue" in lock["properties"]
            }
            changed = False
            for track in shot["dialogue_tracks"]:
                if track["track_id"] in locked:
                    raise DubError(f"{track['track_id']} dialogue is locked")
                actor = actors[track["speaker_actor_id"]]
                profile = by_character.get(actor["character_id"])
                if profile is None:
                    raise DubError(f"no voice profile for {actor['character_id']}")
                engine = engines.get(profile.provider)
                if engine is None:
                    hint = ": set ELEVENLABS_API_KEY" if profile.provider == "elevenlabs" else ""
                    raise DubError(f"no synth named {profile.provider}{hint}")
                sample_count = frame_to_sample_start(track["end_frame"] - track["start_frame"], SAMPLE_RATE, fps)
                emotion, extra, prep = _prepare(track["text"], router)
                dictionary = {**profile.pronunciation, **extra}
                try:
                    wav = engine.synthesize(track["text"], profile.provider_voice_id, SAMPLE_RATE, sample_count)
                except VoiceError as exc:
                    raise DubError(str(exc)) from exc
                spans = align_line(track["text"], sample_count, dictionary)
                draft = DialogueTrack.model_validate({**track, "alignment": [span.model_dump() for span in spans]})
                keys = viseme_keys(draft, spans, sample_rate=SAMPLE_RATE, fps=fps)
                take_id = "take_" + hashlib.sha256(wav).hexdigest()[:8]
                track["voice_take_id"] = take_id
                track["voice_take_version"] = "1.0.0"
                track["alignment"] = [span.model_dump(mode="json") for span in spans]
                track["visemes"] = [key.model_dump(mode="json") for key in keys]
                takes.append(
                    TakeRecord(
                        take_id=take_id,
                        line_id=track["line_id"],
                        speaker_actor_id=track["speaker_actor_id"],
                        character_id=actor["character_id"],
                        provider=profile.provider,
                        provider_voice_id=profile.provider_voice_id,
                        emotion=emotion,
                        prep=prep,
                        sample_rate=SAMPLE_RATE,
                        consent=profile.consent,
                        wav=wav,
                    )
                )
                changed = True
            if changed:
                shot["provenance"]["parent_revision"] = shot["provenance"]["revision"]
                shot["provenance"]["revision"] = _next_revision(shot["provenance"]["revision"])
                shot["provenance"]["source"] = "voice"
                shot["provenance"]["note"] = "voice take, alignment, and visemes"
    try:
        return Episode.model_validate(data), takes
    except ValidationError as exc:
        raise DubError(str(exc)) from exc


def _prepare(text: str, router: ProviderRouter | None) -> tuple[str, dict[str, str], str]:
    if router is None:
        return "neutral", {}, "fallback"
    request = ModelRequest(
        step="voice_prep",
        system=(
            "Return JSON with emotion (a short word) and pronunciations "
            "(an object of lowercase word to viseme: rest, MBP, FV, TH, AA, EE, OH, L). "
            "Do not invent series facts."
        ),
        user=text,
    )
    try:
        response = router.complete(request)
    except ProviderUnavailable:
        return "neutral", {}, "fallback"
    try:
        payload = json.loads(response.text)
        emotion = str(payload.get("emotion") or "neutral")
        raw = payload.get("pronunciations") or {}
        pronunciations = {
            str(word).lower(): str(phoneme)
            for word, phoneme in raw.items()
            if str(phoneme) in VISEMES
        }
    except (json.JSONDecodeError, AttributeError, TypeError):
        return "neutral", {}, "fallback"
    return emotion, pronunciations, "router"


def _next_revision(revision: str) -> str:
    number = int(revision.removeprefix("rev-")) + 1
    width = max(4, len(revision.removeprefix("rev-")))
    return f"rev-{number:0{width}d}"
