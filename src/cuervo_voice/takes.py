"""Record a line once, at the length it takes to say, and keep it on disk.

Animation is timed to these takes. A take is cached by its text, voice,
model, and settings, so a second run does not pay the vendor again.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import wave
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from cuervo_ir.models import AlignmentSpan
from cuervo_voice.align import align_line, align_timed
from cuervo_voice.dub import VoiceProfile
from cuervo_voice.synth import Speech, VoiceError, VoiceSynth

SAMPLE_RATE = 48_000


class Take(BaseModel):
    model_config = ConfigDict(extra="forbid")

    take_id: str
    character_id: str
    provider: str
    provider_voice_id: str
    model: str
    text: str
    consent: str
    sample_rate: int
    sample_count: int
    # "measured" when the vendor timed each character, "estimated" when the letters were spread evenly.
    timing: str
    alignment: list[AlignmentSpan]

    @property
    def seconds(self) -> float:
        return self.sample_count / self.sample_rate


def take_key(text: str, profile: VoiceProfile) -> str:
    blob = json.dumps(
        [text, profile.provider, profile.provider_voice_id, profile.model_id, profile.settings, profile.pronunciation],
        sort_keys=True,
    )
    return "take_" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def wav_path(takes_dir: Path, take_id: str) -> Path:
    return takes_dir / f"{take_id}.wav"


def load_take(takes_dir: Path, take_id: str) -> Take | None:
    record = takes_dir / f"{take_id}.json"
    if not record.is_file() or not wav_path(takes_dir, take_id).is_file():
        return None
    return Take.model_validate_json(record.read_text(encoding="utf-8"))


def record_take(text: str, profile: VoiceProfile, engines: dict[str, VoiceSynth], takes_dir: Path) -> tuple[Take, bool]:
    """Return the take for this line and whether it was newly recorded."""

    take_id = take_key(text, profile)
    cached = load_take(takes_dir, take_id)
    if cached is not None:
        return cached, False
    engine = engines.get(profile.provider)
    if engine is None:
        hint = ": set ELEVENLABS_API_KEY" if profile.provider == "elevenlabs" else ""
        raise VoiceError(f"no voice engine named {profile.provider}{hint}")
    speak = getattr(engine, "speak", None)
    if speak is None:
        raise VoiceError(f"{profile.provider} cannot record a line at its natural length")
    speech: Speech = speak(text, profile.provider_voice_id, model_id=profile.model_id, settings=profile.settings or None)
    takes_dir.mkdir(parents=True, exist_ok=True)
    pcm = _to_rate(speech.pcm, speech.sample_rate, takes_dir)
    sample_count = len(pcm) // 2
    if sample_count < 1:
        raise VoiceError(f"{profile.provider} returned no audio for: {text[:40]}")
    if speech.chars:
        spans = align_timed(
            [(item.char, item.start, item.end) for item in speech.chars], SAMPLE_RATE, sample_count, profile.pronunciation
        )
        timing = "measured"
    else:
        spans = align_line(text, sample_count, profile.pronunciation)
        timing = "estimated"
    with wave.open(str(wav_path(takes_dir, take_id)), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm)
    take = Take(
        take_id=take_id,
        character_id=profile.character_id,
        provider=profile.provider,
        provider_voice_id=profile.provider_voice_id,
        model=speech.model,
        text=text,
        consent=profile.consent,
        sample_rate=SAMPLE_RATE,
        sample_count=sample_count,
        timing=timing,
        alignment=spans,
    )
    (takes_dir / f"{take_id}.json").write_text(take.model_dump_json(), encoding="utf-8")
    return take, True


def read_pcm(takes_dir: Path, take_id: str) -> bytes | None:
    path = wav_path(takes_dir, take_id)
    if not path.is_file():
        return None
    with wave.open(str(path), "rb") as handle:
        if handle.getframerate() != SAMPLE_RATE or handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            return None
        return handle.readframes(handle.getnframes())


def _to_rate(pcm: bytes, rate: int, scratch: Path) -> bytes:
    """Resample vendor audio to the pipeline clock."""

    if rate == SAMPLE_RATE:
        return pcm
    completed = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "s16le", "-ar", str(rate), "-ac", "1", "-i", "pipe:0",
         "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", "pipe:1"],
        input=pcm,
        capture_output=True,
        check=False,
        cwd=scratch,
    )
    if completed.returncode != 0 or not completed.stdout:
        raise VoiceError(completed.stderr.decode("utf-8", errors="replace").strip() or "could not resample the take")
    return completed.stdout
