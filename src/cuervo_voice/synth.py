"""Voice adapters. Vendor ids stay on the profile, not in the episode."""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class VoiceError(RuntimeError):
    pass


class VoiceSynth(Protocol):
    name: str

    def synthesize(self, text: str, voice_id: str, sample_rate: int, sample_count: int) -> bytes: ...


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


class ElevenLabsSynth:
    name = "elevenlabs"

    def __init__(self, api_key: str | None = None, transport=None, base_url: str | None = None):
        self.api_key = os.environ.get("ELEVENLABS_API_KEY", "") if api_key is None else api_key
        self.transport = transport
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
