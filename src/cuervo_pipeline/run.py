"""Per-shot jobs: cache, approval, review, render, and assembly.

Dialogue, acting, and camera changes miss the cache for that shot. An asset
version is rebuilt only for shots the caller opts in.
"""

from __future__ import annotations

import array
import hashlib
import json
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from cuervo_ir.models import Episode, Shot
from cuervo_ir.providers.router import ModelRequest, ProviderRouter, ProviderUnavailable
from cuervo_runtime.draw import render_png
from cuervo_voice.dub import VoiceProfile, dub_episode
from cuervo_voice.takes import SAMPLE_RATE, read_pcm


class PipelineError(RuntimeError):
    pass


class ShotReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_id: str
    status: str
    cache_key: str
    attempts: int
    cost_frames: int
    render_hash: str | None
    review_note: str
    error: str | None = None


@dataclass
class PipelineResult:
    reports: list[ShotReport]
    master: Path | None
    cache: dict[str, dict]


def fingerprint(shot: Shot, poses: dict | None, generations: dict[str, str]) -> str:
    body = shot.model_dump(mode="json")
    for ref in body["asset_refs"]:
        if ref["asset_id"] in generations:
            ref["version"] = generations[ref["asset_id"]]
    blob = {"shot": body, "poses": poses or {}}
    return hashlib.sha256(json.dumps(blob, sort_keys=True).encode("utf-8")).hexdigest()


def adopt_asset(episode: Episode, asset_id: str, version: str) -> Episode:
    """Opt every shot that pins this asset into a new version. Unrelated shots stay cached."""

    data = episode.model_dump(mode="json")
    library_hit = False
    for group in ("characters", "rigs", "backgrounds", "props"):
        for item in data["assets"][group]:
            if item["asset_id"] == asset_id:
                item["version"] = version
                library_hit = True
    if not library_hit:
        raise PipelineError(f"unknown asset {asset_id}")
    for character in data["assets"]["characters"]:
        if character["rig_id"] == asset_id:
            character["rig_version"] = version
    for scene in data["scenes"]:
        for shot in scene["shots"]:
            for ref in shot["asset_refs"]:
                if ref["asset_id"] == asset_id:
                    ref["version"] = version
    return Episode.model_validate(data)


def run_episode(
    episode: Episode,
    out_dir: Path,
    *,
    router: ProviderRouter,
    approved: set[str],
    poses: dict | None = None,
    profiles: list[VoiceProfile] | None = None,
    cache: dict[str, dict] | None = None,
    generations: dict[str, str] | None = None,
    render_frame=render_png,
    max_attempts: int = 2,
    takes_dir: Path | None = None,
    review: bool = True,
    progress=None,
) -> PipelineResult:
    """Render the approved shots and join them.

    With `takes_dir`, each line's recorded take is laid on the soundtrack at
    the frame the line starts, and the master carries that audio. The cache is
    also kept in `out_dir/cache.json`, so a later run only redraws what changed.
    """

    if profiles:
        episode, _takes = dub_episode(episode, profiles, router=router)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_file = out_dir / "cache.json"
    if cache is not None:
        store = cache
    else:
        try:
            store = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            store = {}
    total = sum(len(scene.shots) for scene in episode.scenes)
    done = 0
    sound: list[tuple[int, bytes]] = []
    generations = generations if generations is not None else {}
    reports: list[ShotReport] = []
    segments: list[Path] = []
    for scene in episode.scenes:
        for shot in scene.shots:
            key = fingerprint(shot, poses, generations)
            done += 1
            if progress and (done % 25 == 0 or done == total):
                progress(done, total)
            if shot.shot_id not in approved:
                reports.append(
                    ShotReport(
                        shot_id=shot.shot_id,
                        status="awaiting_approval",
                        cache_key=key,
                        attempts=0,
                        cost_frames=0,
                        render_hash=None,
                        review_note="",
                    )
                )
                continue
            cached = store.get(key)
            cached_path = Path(cached["mp4"]) if cached is not None else None
            if cached is not None and cached_path is not None and cached_path.is_file():
                reports.append(
                    ShotReport(
                        shot_id=shot.shot_id,
                        status="cached",
                        cache_key=key,
                        attempts=0,
                        cost_frames=0,
                        render_hash=cached["hash"],
                        review_note=cached["review_note"],
                    )
                )
                segments.append(cached_path)
                sound.append((shot.duration_frames, shot_audio(shot, episode.fps, takes_dir)))
                continue
            note = _review(router, shot) if review else ""
            pngs, attempts, error = _render_with_retry(
                episode, shot, poses, render_frame, max_attempts
            )
            if error or not pngs:
                reports.append(
                    ShotReport(
                        shot_id=shot.shot_id,
                        status="failed",
                        cache_key=key,
                        attempts=attempts,
                        cost_frames=0,
                        render_hash=None,
                        review_note=note,
                        error=error or "no frames",
                    )
                )
                continue
            digest = hashlib.sha256(b"".join(pngs)).hexdigest()
            try:
                mp4 = _encode_shot(out_dir / _safe(shot.shot_id), pngs, episode.fps)
            except PipelineError as exc:
                reports.append(
                    ShotReport(
                        shot_id=shot.shot_id,
                        status="failed",
                        cache_key=key,
                        attempts=attempts,
                        cost_frames=0,
                        render_hash=None,
                        review_note=note,
                        error=str(exc),
                    )
                )
                continue
            store[key] = {"hash": digest, "mp4": str(mp4), "review_note": note}
            reports.append(
                ShotReport(
                    shot_id=shot.shot_id,
                    status="rendered",
                    cache_key=key,
                    attempts=attempts,
                    cost_frames=len(pngs),
                    render_hash=digest,
                    review_note=note,
                )
            )
            segments.append(mp4)
            sound.append((shot.duration_frames, shot_audio(shot, episode.fps, takes_dir)))
    master = _concat(out_dir / "episode.mp4", segments) if segments else None
    if master is not None and takes_dir is not None and any(pcm.strip(b"\x00") for _frames, pcm in sound):
        _add_soundtrack(master, b"".join(pcm for _frames, pcm in sound))
    cache_file.write_text(json.dumps(store), encoding="utf-8")
    return PipelineResult(reports=reports, master=master, cache=store)


def shot_audio(shot: Shot, fps: int, takes_dir: Path | None) -> bytes:
    """16-bit mono PCM for one shot, exactly as long as its frames."""

    length = shot.duration_frames * SAMPLE_RATE // fps
    track = array.array("h", bytes(length * 2))
    if takes_dir is None:
        return track.tobytes()
    for line in shot.dialogue_tracks:
        pcm = read_pcm(takes_dir, line.voice_take_id) if line.voice_take_id else None
        if not pcm:
            continue
        take = array.array("h", pcm)
        start = line.start_frame * SAMPLE_RATE // fps
        room = min(len(take), length - start)
        if room <= 0:
            continue
        # Lines in one shot do not overlap, so a take is copied in, not summed.
        track[start : start + room] = take[:room]
    return track.tobytes()


def _add_soundtrack(master: Path, pcm: bytes) -> None:
    """Mux one continuous soundtrack onto the joined picture. One encode keeps it in sync end to end."""

    sound = master.with_suffix(".wav")
    with wave.open(str(sound), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm)
    silent = master.with_name("picture.mp4")
    master.replace(silent)
    _ffmpeg(["-i", str(silent), "-i", str(sound), "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", str(master)])
    silent.unlink(missing_ok=True)


def _review(router: ProviderRouter, shot: Shot) -> str:
    try:
        response = router.complete(
            ModelRequest(
                step="review",
                system="One short advisory note about this shot. You do not approve it.",
                user=json.dumps(
                    {
                        "shot_id": shot.shot_id,
                        "duration_frames": shot.duration_frames,
                        "lines": [line.text for line in shot.dialogue_tracks],
                    }
                ),
            )
        )
    except ProviderUnavailable:
        return ""
    return response.text.strip()


def _render_with_retry(episode, shot, poses, render_frame, max_attempts: int):
    error = "render failed"
    for attempt in range(1, max_attempts + 1):
        try:
            pngs = [render_frame(episode, shot, frame, poses) for frame in range(shot.duration_frames)]
            return pngs, attempt, None
        except Exception as exc:
            error = str(exc)
    return [], max_attempts, error


def _encode_shot(directory: Path, pngs: list[bytes], fps: int) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for index, png in enumerate(pngs):
        (directory / f"frame_{index:04d}.png").write_bytes(png)
    mp4 = directory / "shot.mp4"
    _ffmpeg(
        [
            "-framerate",
            str(fps),
            "-i",
            str(directory / "frame_%04d.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(mp4),
        ]
    )
    return mp4


def _concat(master: Path, segments: list[Path]) -> Path:
    if len(segments) == 1:
        master.write_bytes(segments[0].read_bytes())
        return master
    listing = master.with_suffix(".txt")
    listing.write_text("".join(f"file '{path}'\n" for path in segments), encoding="utf-8")
    _ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(master)])
    return master


def _ffmpeg(args: list[str]) -> None:
    completed = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise PipelineError(completed.stderr.strip() or "ffmpeg failed")


def _safe(shot_id: str) -> str:
    return "".join(character if character.isalnum() or character == "_" else "_" for character in shot_id)
