"""Voice adapters. Vendor ids stay on the profile, not in the episode."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import struct
from dataclasses import dataclass, field
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class VoiceError(RuntimeError):
    pass


class VoiceSynth(Protocol):
    name: str

    def synthesize(self, text: str, voice_id: str, sample_rate: int, sample_count: int) -> bytes: ...


@dataclass(frozen=True)
class CharTime:
    """One character of the spoken text and when it sounds, in seconds from the start."""

    char: str
    start: float
    end: float


@dataclass(frozen=True)
class Speech:
    """A performance at its natural length. `pcm` is 16-bit mono little-endian."""

    pcm: bytes
    sample_rate: int
    chars: list[CharTime] = field(default_factory=list)
    model: str = ""

    @property
    def sample_count(self) -> int:
        return len(self.pcm) // 2

    @property
    def seconds(self) -> float:
        return self.sample_count / self.sample_rate

    def wav(self) -> bytes:
        return _wav(self.sample_rate, self.pcm)


# Speaking rate for the fixture voice. Close to an unhurried read.
FIXTURE_CHARS_PER_SECOND = 14.0


class FixtureSynth:
    """Deterministic tone. Used when a project has no external voice provider."""

    name = "fixture"

    def synthesize(self, text: str, voice_id: str, sample_rate: int, sample_count: int) -> bytes:
        digest = hashlib.sha256(f"{voice_id}:{text}".encode("utf-8")).digest()
        frequency = 180 + digest[0]
        frames = bytearray()
        for index in range(sample_count):
            sample = int(6000 * math.sin(2 * math.pi * frequency * index / sample_rate))
            frames += struct.pack("<h", sample)
        return _wav(sample_rate, bytes(frames))

    def speak(self, text: str, voice_id: str, *, model_id: str | None = None, settings: dict | None = None) -> Speech:
        """A tone as long as the line would take to say, with a timing for every character."""

        sample_rate = 48_000
        speed = float((settings or {}).get("speed", 1.0)) or 1.0
        step = 1.0 / (FIXTURE_CHARS_PER_SECOND * speed)
        chars: list[CharTime] = []
        cursor = 0.0
        for char in text:
            # Punctuation is a breath. Everything else takes one beat.
            width = step * (2.5 if char in ".?!" else 1.5 if char in ",;:" else 1.0)
            chars.append(CharTime(char, cursor, cursor + width))
            cursor += width
        seconds = max(0.4, cursor)
        digest = hashlib.sha256(f"{voice_id}:{text}".encode("utf-8")).digest()
        frequency = 180 + digest[0]
        count = int(seconds * sample_rate)
        frames = bytearray()
        for index in range(count):
            # Fade the ends so lines butt together without a click.
            edge = min(1.0, index / 480, (count - index) / 480)
            frames += struct.pack("<h", int(5000 * edge * math.sin(2 * math.pi * frequency * index / sample_rate)))
        return Speech(pcm=bytes(frames), sample_rate=sample_rate, chars=chars, model="fixture")


class ElevenLabsSynth:
    name = "elevenlabs"

    def __init__(self, api_key: str | None = None, transport=None, base_url: str | None = None, speech_transport=None):
        self.api_key = os.environ.get("ELEVENLABS_API_KEY", "") if api_key is None else api_key
        self.transport = transport
        # Tests pass `speech_transport(url, body) -> dict` in place of the network.
        self.speech_transport = speech_transport
        self.base_url = (base_url or os.environ.get("ELEVENLABS_BASE_URL", "https://api.elevenlabs.io")).rstrip("/")

    def available(self) -> bool:
        return bool(self.api_key) or self.transport is not None

    def synthesize(self, text: str, voice_id: str, sample_rate: int, sample_count: int) -> bytes:
        if self.transport is not None:
            return self.transport(text, voice_id, sample_rate, sample_count)
        if not self.api_key:
            raise VoiceError("elevenlabs is not configured")
        if sample_rate not in (16_000, 22_050, 24_000, 44_100, 48_000):
            raise VoiceError(f"elevenlabs has no pcm format for {sample_rate} Hz")
        url = f"{self.base_url}/v1/text-to-speech/{voice_id}?output_format=pcm_{sample_rate}"
        request = Request(
            url,
            data=json.dumps({"text": text, "model_id": "eleven_multilingual_v2"}).encode("utf-8"),
            headers={"xi-api-key": self.api_key, "content-type": "application/json", "accept": "audio/pcm"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=60) as response:
                pcm = response.read()
        except (HTTPError, URLError) as exc:
            raise VoiceError(str(getattr(exc, "reason", exc))) from exc
        if not pcm:
            raise VoiceError("elevenlabs returned no audio")
        return _wav(sample_rate, fit_pcm(pcm, sample_count))

    def speak(self, text: str, voice_id: str, *, model_id: str | None = None, settings: dict | None = None) -> Speech:
        """The line at its natural length, with the character timings ElevenLabs measured.

        Uses the with-timestamps endpoint. Those timings drive lip sync, so the
        mouth follows the recording and not an even spread of letters.
        """

        if not self.api_key:
            raise VoiceError("elevenlabs is not configured: set ELEVENLABS_API_KEY")
        model = model_id or os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2")
        rate = int(os.environ.get("ELEVENLABS_PCM_RATE", "24000"))
        body: dict = {"text": text, "model_id": model}
        if settings:
            body["voice_settings"] = settings
        url = f"{self.base_url}/v1/text-to-speech/{voice_id}/with-timestamps?output_format=pcm_{rate}"
        if self.speech_transport is not None:
            payload = self.speech_transport(url, body)
        else:
            request = Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers={"xi-api-key": self.api_key, "content-type": "application/json"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=120) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:300]
                raise VoiceError(f"elevenlabs HTTP {exc.code}: {detail}") from exc
            except (URLError, json.JSONDecodeError) as exc:
                raise VoiceError(f"elevenlabs: {getattr(exc, 'reason', exc)}") from exc
        try:
            pcm = base64.b64decode(payload["audio_base64"])
        except (KeyError, TypeError, ValueError) as exc:
            raise VoiceError("elevenlabs returned no audio") from exc
        if not pcm:
            raise VoiceError("elevenlabs returned no audio")
        if len(pcm) % 2:
            pcm += b"\x00"
        alignment = payload.get("alignment") or payload.get("normalized_alignment") or {}
        chars = [
            CharTime(str(char), float(start), float(end))
            for char, start, end in zip(
                alignment.get("characters") or [],
                alignment.get("character_start_times_seconds") or [],
                alignment.get("character_end_times_seconds") or [],
            )
        ]
        return Speech(pcm=pcm, sample_rate=rate, chars=chars, model=model)


def default_synths() -> dict[str, VoiceSynth]:
    """Every voice engine this process can use. ElevenLabs joins when its key is set."""

    engines: dict[str, VoiceSynth] = {"fixture": FixtureSynth()}
    eleven = ElevenLabsSynth()
    if eleven.api_key:
        engines["elevenlabs"] = eleven
    return engines


def fit_pcm(pcm: bytes, sample_count: int) -> bytes:
    """Force 16-bit mono PCM to the line length the alignment clock uses."""

    if len(pcm) % 2:
        pcm += b"\x00"
    need = sample_count * 2
    if len(pcm) < need:
        return pcm + b"\x00" * (need - len(pcm))
    return pcm[:need]


def _wav(sample_rate: int, pcm: bytes) -> bytes:
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(pcm),
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        sample_rate,
        sample_rate * 2,
        2,
        16,
        b"data",
        len(pcm),
    )
    return header + pcm
