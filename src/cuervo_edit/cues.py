"""Cues: the command line of the animation.

An agent works on an episode by writing cues, one per line, the way a person
would drive a CLI. Read cues look around. Edit cues change one shot each. Every
edit comes back with a sentence a director can read, so the page never has to
show a cue, an id, or a patch.

    scenes                         list the scenes
    shots <scene>                  list the shots in a scene
    show <shot>                    the camera, cast, tracks, and lines of a shot
    find "<text>"                  lines that contain the text

    hold <shot> <frames>           let the shot run longer (whatever ran to its end still does)
    trim <shot> <frames>           take frames off the end
    camera <shot> [preset] [--on <actor>] [--zoom <n>] [--x <n>] [--y <n>]
    pose <shot> <track> <pose>     change the pose on a track
    act <shot> <actor> <pose> [<start>..<end>]    add a gesture, look, or expression
    move <shot> <track> <start>..<end>            retime a track
    drop <shot> <track>            remove a track
    say <shot> <line> "<text>"     rewrite a line of dialogue
    cut <shot>                     remove the shot

    done "<message>"               finish, with a note for the director
"""

from __future__ import annotations

import math
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import get_args

from pydantic import ValidationError

from cuervo_ir.contract import allowed_poses
from cuervo_ir.models import CameraPreset, DialogueTrack, Episode
from cuervo_runtime.poses import CONTRACT_POSES

READS = ("scenes", "shots", "show", "find")
EDITS = ("hold", "trim", "camera", "pose", "act", "move", "drop", "say", "cut")
PRESETS = get_args(CameraPreset)

PRESET_WORDS = {
    "wide": "wide shot",
    "two_shot": "two-shot",
    "over_the_shoulder": "over-the-shoulder shot",
    "close_up": "close-up",
    "reaction": "reaction shot",
    "insert": "insert",
}
PRESET_SCALE = {"wide": 1.0, "two_shot": 1.5, "over_the_shoulder": 1.8, "close_up": 2.4, "reaction": 2.2, "insert": 2.6}

ARMS = {"arm_l", "arm_r", "hand_l", "hand_r"}
LOOK = {"gaze_yaw", "gaze_pitch", "head", "neck"}
BODY = {"root", "torso", "leg_l", "leg_r"}
KIND_PRIORITY = {"pose": 12, "gesture": 22, "gaze": 32, "expression": 42}
KIND_WORDS = {"pose": "body", "gesture": "gesture", "gaze": "look", "expression": "expression", "secondary": "blink", "locomotion": "walk"}


class CueError(ValueError):
    """A cue that cannot run. The text is written for the director."""


@dataclass
class CueContext:
    """What a cue may need besides the episode."""

    poses: dict[str, dict[str, float]] | None = None
    takes_dir: Path | None = None
    # Voice engines by provider name. Without them a rewritten line waits for a take.
    engines: dict | None = None


@dataclass
class Cue:
    verb: str
    args: list[str]
    options: dict[str, str] = field(default_factory=dict)
    text: str = ""

    @property
    def shot_id(self) -> str | None:
        return self.args[0] if self.verb in EDITS and self.args else None


def parse(script: str) -> list[Cue]:
    """Read cues from text. Blank lines, comments, and code fences are skipped."""

    cues: list[Cue] = []
    for raw in script.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("```"):
            continue
        try:
            words = shlex.split(line)
        except ValueError as exc:
            raise CueError(f"could not read: {line}") from exc
        verb, rest = words[0].lower(), words[1:]
        if verb not in READS + EDITS + ("done",):
            raise CueError(f"unknown cue: {verb}")
        args: list[str] = []
        options: dict[str, str] = {}
        index = 0
        while index < len(rest):
            word = rest[index]
            if word.startswith("--") and len(word) > 2 and not word[2:3].isdigit():
                if index + 1 >= len(rest):
                    raise CueError(f"{word} needs a value")
                options[word[2:]] = rest[index + 1]
                index += 2
            else:
                args.append(word)
                index += 1
        cues.append(Cue(verb=verb, args=args, options=options, text=line))
    return cues


# ---------------------------------------------------------------------------
# Names a director would use


def names(episode: Episode) -> dict:
    """Shot numbers and character names, for sentences."""

    characters = {item.asset_id: item.display_name.split()[0] for item in episode.assets.characters}
    shots: dict[str, int] = {}
    for scene in episode.scenes:
        for shot in scene.shots:
            shots[shot.shot_id] = len(shots) + 1
    return {"characters": characters, "shots": shots}


def shot_label(episode: Episode, shot_id: str) -> str:
    number = names(episode)["shots"].get(shot_id)
    return f"shot {number}" if number else "that shot"


def actor_name(episode: Episode, shot, actor_id: str) -> str:
    for actor in shot.actors:
        if actor.actor_id == actor_id:
            return names(episode)["characters"].get(actor.character_id, actor_id)
    return actor_id


def track_phrase(episode: Episode, shot, track) -> str:
    """`Ada's shrug`, `Bo's expression`."""

    who = actor_name(episode, shot, track.target_actor_id)
    pose = track.keyframes[0].pose.replace("_", " ")
    what = pose if track.kind in ("gesture", "gaze") else KIND_WORDS.get(track.kind, track.kind)
    return f"{who}'s {what}"


def seconds(frames: int, fps: int) -> str:
    value = frames / fps
    return f"{value:.1f} s" if value != int(value) else f"{int(value)} s"


# ---------------------------------------------------------------------------
# Reading


def read(episode: Episode, cue: Cue) -> str:
    """Run a read cue and return what the agent sees."""

    if cue.verb == "scenes":
        rows = []
        for scene in episode.scenes:
            frames = sum(shot.duration_frames for shot in scene.shots)
            rows.append(
                f"{scene.scene_id}  {len(scene.shots)} shots  {seconds(frames, episode.fps)}  "
                f"{scene.shots[0].shot_id}..{scene.shots[-1].shot_id}  {scene.title}"
            )
        return "\n".join(rows)
    if cue.verb == "shots":
        if not cue.args:
            raise CueError("shots needs a scene id")
        scene = next((item for item in episode.scenes if item.scene_id == cue.args[0]), None)
        if scene is None:
            raise CueError(f"unknown scene {cue.args[0]}")
        return "\n".join(_shot_row(episode, shot) for shot in scene.shots)
    if cue.verb == "show":
        if not cue.args:
            raise CueError("show needs a shot id")
        return describe(episode, cue.args[0])
    if cue.verb == "find":
        if not cue.args:
            raise CueError("find needs some text")
        needle = " ".join(cue.args).lower()
        rows = [
            f'{shot.shot_id} {line.line_id} {line.speaker_actor_id}: "{line.text}"'
            for scene in episode.scenes
            for shot in scene.shots
            for line in shot.dialogue_tracks
            if needle in line.text.lower()
        ]
        return "\n".join(rows[:40]) or "no line contains that"
    raise CueError(f"{cue.verb} is not a read cue")


def _shot_row(episode: Episode, shot) -> str:
    line = f'  "{shot.dialogue_tracks[0].text}"' if shot.dialogue_tracks else ""
    return f"{shot.shot_id}  {shot.camera.preset}  {shot.duration_frames}f{line}"


def describe(episode: Episode, shot_id: str) -> str:
    """Everything about one shot an agent needs to change it."""

    shot = _find(episode, shot_id)
    characters = {item.asset_id: item for item in episode.assets.characters}
    locks: dict[str, list[str]] = {}
    for lock in shot.locks:
        locks.setdefault(lock.target_track_id, []).extend(lock.properties)
    camera_locked = any("camera" in items for items in locks.values())
    transform = shot.camera.transform
    rows = [
        f"shot {shot.shot_id}  scene {shot.scene_id}  {shot.duration_frames} frames at {shot.fps} fps",
        f"camera {shot.camera.preset} zoom {transform.scale:g} x {transform.x:g} y {transform.y:g}"
        f"{'  LOCKED' if camera_locked else ''}  ({shot.camera.framing})",
        "actors:",
    ]
    for actor in shot.actors:
        character = characters[actor.character_id]
        rows.append(
            f"  {actor.actor_id}  {character.display_name}  poses: {' '.join(sorted(allowed_poses(character.extension_poses)))}"
        )
    rows.append("tracks:")
    for track in shot.action_tracks:
        held = f"  LOCKED {'/'.join(locks[track.track_id])}" if track.track_id in locks else ""
        rows.append(
            f"  {track.track_id}  {track.kind}  {track.target_actor_id}  {track.keyframes[0].pose}  "
            f"{track.start_frame}..{track.end_frame}{held}"
        )
    rows.append("lines:")
    for line in shot.dialogue_tracks:
        held = "  LOCKED" if "dialogue" in locks.get(line.track_id, []) else ""
        rows.append(f'  {line.line_id}  {line.speaker_actor_id}  {line.start_frame}..{line.end_frame}  "{line.text}"{held}')
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Editing


def apply(episode: Episode, cue: Cue, context: CueContext | None = None) -> tuple[Episode, str]:
    """Run one edit cue. Returns the new episode and a sentence that says what changed."""

    if cue.verb not in EDITS:
        raise CueError(f"{cue.verb} does not change anything")
    if not cue.args:
        raise CueError(f"{cue.verb} needs a shot id")
    context = context or CueContext()
    shot_id = cue.args[0]
    before = _find(episode, shot_id)
    data = episode.model_dump(mode="json")
    scene, shot = _find_data(data, shot_id)
    label = shot_label(episode, shot_id)
    locks: dict[str, set[str]] = {}
    for lock in shot["locks"]:
        locks.setdefault(lock["target_track_id"], set()).update(lock["properties"])
    fps = episode.fps

    def track_of(track_id: str) -> dict:
        for track in shot["action_tracks"]:
            if track["track_id"] == track_id:
                return track
        raise CueError(f"{label} has no track {track_id}")

    def phrase(track_id: str) -> str:
        return track_phrase(episode, before, next(item for item in before.action_tracks if item.track_id == track_id))

    def refuse_if_locked(track_id: str, what: str) -> None:
        if what in locks.get(track_id, set()):
            raise CueError(f"{phrase(track_id).capitalize()} is locked, so its {what} cannot change.")

    if cue.verb == "hold":
        frames = _frames(cue, 1)
        for track in shot["action_tracks"]:
            # Whatever was held to the end of the shot keeps holding.
            if track["end_frame"] == shot["duration_frames"] and "timing" not in locks.get(track["track_id"], set()):
                track["end_frame"] += frames
        _grow(scene, shot, frames)
        sentence = f"Hold {label} for {frames} more frames ({seconds(frames, fps)})."

    elif cue.verb == "trim":
        frames = _frames(cue, 1)
        floor = max((line["end_frame"] for line in shot["dialogue_tracks"]), default=0)
        length = shot["duration_frames"] - frames
        if length < max(1, floor):
            raise CueError(f"{label.capitalize()} cannot lose {frames} frames without cutting into a line.")
        kept = []
        for track in shot["action_tracks"]:
            if track["start_frame"] >= length:
                continue
            if track["end_frame"] > length:
                refuse_if_locked(track["track_id"], "timing")
                track["end_frame"] = length
            kept.append(track)
        shot["action_tracks"] = kept
        _grow(scene, shot, -frames)
        sentence = f"Trim {frames} frames ({seconds(frames, fps)}) off the end of {label}."

    elif cue.verb == "camera":
        if any("camera" in items for items in locks.values()):
            raise CueError(f"The camera is locked on {label}.")
        preset = cue.args[1] if len(cue.args) > 1 else None
        if preset is not None and preset not in PRESETS:
            raise CueError(f"{preset} is not a shot size. Use one of: {', '.join(PRESETS)}.")
        camera = shot["camera"]
        parts: list[str] = []
        if preset is not None and preset != camera["preset"]:
            parts.append(f"from a {PRESET_WORDS[camera['preset']]} to a {PRESET_WORDS[preset]}")
            camera["preset"] = preset
            camera["transform"]["scale"] = PRESET_SCALE[preset]
            if preset in ("wide", "two_shot") and "on" not in cue.options:
                camera["transform"]["x"] = 0.0
        if "on" in cue.options:
            actor = next((item for item in shot["actors"] if item["actor_id"] == cue.options["on"]), None)
            if actor is None:
                raise CueError(f"{cue.options['on']} is not in {label}.")
            camera["transform"]["x"] = round(actor["stage"]["x"] * 1.4, 2)
            parts.append(f"on {actor_name(episode, before, actor['actor_id'])}")
        for option, key, word in (("zoom", "scale", "zoom"), ("x", "x", "pan"), ("y", "y", "tilt")):
            if option in cue.options:
                value = _number(cue.options[option], option)
                if option == "zoom" and not 0.5 <= value <= 4:
                    raise CueError("zoom runs from 0.5 to 4")
                camera["transform"][key] = value
                if option == "zoom":
                    parts.append(f"at {value:g}× zoom")
                elif not any(part.startswith("on ") for part in parts):
                    parts.append(f"with a new {word}")
        if not parts:
            raise CueError(f"The camera on {label} is already like that.")
        sentence = f"Reframe {label} {' '.join(parts)}."

    elif cue.verb == "pose":
        track_id, pose = _args(cue, 3)[1:]
        track = track_of(track_id)
        refuse_if_locked(track_id, "pose")
        old = track["keyframes"][0]["pose"]
        if old == pose:
            raise CueError(f"{phrase(track_id).capitalize()} is already {pose}.")
        _check_pose(episode, before, track["target_actor_id"], pose)
        for key in track["keyframes"]:
            key["pose"] = pose
        who = actor_name(episode, before, track["target_actor_id"])
        sentence = f"Change {who}'s {KIND_WORDS.get(track['kind'], track['kind'])} from {_word(old)} to {_word(pose)} in {label}."

    elif cue.verb == "act":
        if len(cue.args) < 3:
            raise CueError("act needs a shot, an actor, and a pose")
        actor_id, pose = cue.args[1], cue.args[2]
        if not any(item["actor_id"] == actor_id for item in shot["actors"]):
            raise CueError(f"{actor_id} is not in {label}.")
        _check_pose(episode, before, actor_id, pose)
        start, end = _span(cue.args[3], shot["duration_frames"]) if len(cue.args) > 3 else (0, shot["duration_frames"])
        values = (context.poses or {}).get(pose) or CONTRACT_POSES.get(pose) or {}
        mask = [name for name in values if name not in ("mouth", "jaw")] or ["brow_l", "brow_r"]
        kind = "gesture" if set(mask) <= ARMS else "gaze" if set(mask) <= LOOK else "pose" if set(mask) <= BODY else "expression"
        priority = KIND_PRIORITY[kind]
        # Sit just above anything this would otherwise tie with.
        while any(
            item["target_actor_id"] == actor_id
            and item["priority"] == priority
            and item["start_frame"] < end
            and start < item["end_frame"]
            and set(item["mask"]) & set(mask)
            for item in shot["action_tracks"]
        ):
            priority += 1
        taken = {item["track_id"] for item in shot["action_tracks"]} | {item["track_id"] for item in shot["dialogue_tracks"]}
        base = f"tr_{shot_id.removeprefix('sh_')}_{actor_id.removeprefix('act_')}_{pose}"[:58]
        track_id, count = base, 2
        while track_id in taken:
            track_id, count = f"{base}_{count}", count + 1
        shot["action_tracks"].append(
            {
                "track_id": track_id,
                "kind": kind,
                "target_actor_id": actor_id,
                "start_frame": start,
                "end_frame": end,
                "interpolation": "ease_in_out" if kind == "gesture" else "stepped",
                "mask": mask,
                "priority": min(priority, 100),
                "blend_mode": "override",
                "keyframes": [{"frame": start, "pose": pose, "weight": 1.0}],
            }
        )
        who = actor_name(episode, before, actor_id)
        when = "for the whole shot" if (start, end) == (0, shot["duration_frames"]) else f"from {seconds(start, fps)} to {seconds(end, fps)}"
        sentence = f"Add {_article(pose)} {_word(pose)} for {who} in {label}, {when}."

    elif cue.verb == "move":
        track_id, span = _args(cue, 3)[1:]
        track = track_of(track_id)
        refuse_if_locked(track_id, "timing")
        start, end = _span(span, shot["duration_frames"])
        if (start, end) == (track["start_frame"], track["end_frame"]):
            raise CueError(f"{phrase(track_id).capitalize()} already runs from {seconds(start, fps)} to {seconds(end, fps)}.")
        shift = start - track["start_frame"]
        track["start_frame"], track["end_frame"] = start, end
        for key in track["keyframes"]:
            key["frame"] = min(end - 1, max(start, key["frame"] + shift))
        sentence = f"Move {phrase(track_id)} in {label} to run from {seconds(start, fps)} to {seconds(end, fps)}."

    elif cue.verb == "drop":
        track_id = _args(cue, 2)[1]
        track_of(track_id)
        if locks.get(track_id):
            raise CueError(f"{phrase(track_id).capitalize()} is locked.")
        sentence = f"Remove {phrase(track_id)} from {label}."
        shot["action_tracks"] = [item for item in shot["action_tracks"] if item["track_id"] != track_id]

    elif cue.verb == "say":
        if len(cue.args) < 3:
            raise CueError('say needs a shot, a line, and the new text in quotes')
        line_id, text = cue.args[1], " ".join(cue.args[2:]).strip()
        line = next((item for item in shot["dialogue_tracks"] if item["line_id"] == line_id), None)
        if line is None:
            raise CueError(f"{label.capitalize()} has no line {line_id}.")
        if "dialogue" in locks.get(line["track_id"], set()):
            raise CueError("That line is locked.")
        if not text:
            raise CueError("the new line is empty")
        if text == line["text"]:
            raise CueError("The line already reads that way.")
        who = actor_name(episode, before, line["speaker_actor_id"])
        recorded = _retake(line, text, shot, scene, fps, context)
        line["text"] = text
        tail = "It is recorded again and the shot is retimed to it." if recorded else "It needs a new voice take."
        sentence = f'Rewrite {who}\'s line in {label} to "{text}". {tail}'

    else:  # cut
        if len(scene["shots"]) == 1:
            raise CueError(f"{label.capitalize()} is the only shot in its scene.")
        if shot["locks"]:
            raise CueError(f"{label.capitalize()} has locked tracks, so it cannot be removed.")
        sentence = f"Remove {label}."
        length = shot["duration_frames"]
        end = shot["start_frame"] + length
        scene["shots"] = [item for item in scene["shots"] if item["shot_id"] != shot_id]
        for later in scene["shots"]:
            if later["start_frame"] >= end:
                later["start_frame"] -= length
        scene["target_runtime_frames"] = max(1, scene["target_runtime_frames"] - length)

    if cue.verb != "cut":
        shot["provenance"]["parent_revision"] = shot["provenance"]["revision"]
        shot["provenance"]["revision"] = _next_revision(shot["provenance"]["revision"])
        shot["provenance"]["source"] = "cue"
        shot["provenance"]["note"] = sentence
    try:
        return Episode.model_validate(data), sentence
    except ValidationError as exc:
        problem = exc.errors()[0]["msg"].removeprefix("Value error, ")
        raise CueError(f"That would break the shot: {problem}") from exc


def run(episode: Episode, cues: list[Cue], context: CueContext | None = None) -> tuple[Episode, list[str]]:
    """Apply edit cues in order. The first one that fails stops the run."""

    sentences: list[str] = []
    for cue in cues:
        episode, sentence = apply(episode, cue, context)
        sentences.append(sentence)
    return episode, sentences


def _retake(line: dict, text: str, shot: dict, scene: dict, fps: int, context: CueContext) -> bool:
    """Record the rewritten line in the same voice and retime the shot around it."""

    from cuervo_voice.dub import VoiceProfile
    from cuervo_voice.takes import load_take, record_take
    from cuervo_voice.visemes import viseme_keys

    old = load_take(context.takes_dir, line["voice_take_id"]) if context.takes_dir and line.get("voice_take_id") else None
    if old is None or not context.engines or old.provider not in context.engines:
        line["voice_take_id"] = None
        line["voice_take_version"] = None
        line["alignment"] = []
        line["visemes"] = []
        return False
    profile = VoiceProfile(
        character_id=old.character_id,
        provider=old.provider,  # type: ignore[arg-type]
        provider_voice_id=old.provider_voice_id,
        consent=old.consent,
        model_id=old.model if old.provider != "fixture" else None,
    )
    try:
        take, _fresh = record_take(text, profile, context.engines, context.takes_dir)
    except Exception as exc:
        raise CueError(f"The new line could not be recorded: {exc}") from exc
    old_end = line["end_frame"]
    length = max(2, math.ceil(take.sample_count * fps / take.sample_rate))
    delta = line["start_frame"] + length - old_end
    # Everything after the line slides with it. Whatever spans it stretches.
    for track in [*shot["action_tracks"], *shot["dialogue_tracks"]]:
        if track is line:
            continue
        if track["start_frame"] >= old_end:
            track["start_frame"] += delta
            track["end_frame"] += delta
            for key in track.get("keyframes", []):
                key["frame"] += delta
            for key in track.get("visemes", []):
                key["frame"] += delta
        elif track["end_frame"] >= old_end:
            track["end_frame"] = max(track["start_frame"] + 1, track["end_frame"] + delta)
            for key in track.get("keyframes", []):
                key["frame"] = min(key["frame"], track["end_frame"] - 1)
    line["end_frame"] = line["start_frame"] + length
    line["text"] = text
    line["voice_take_id"] = take.take_id
    line["voice_take_version"] = "1.0.0"
    line["alignment"] = [span.model_dump(mode="json") for span in take.alignment]
    line["visemes"] = []
    keys = viseme_keys(DialogueTrack.model_validate(line), take.alignment, sample_rate=take.sample_rate, fps=fps)
    line["visemes"] = [key.model_dump(mode="json") for key in keys]
    _grow(scene, shot, delta)
    return True


def _grow(scene: dict, shot: dict, frames: int) -> None:
    """Change a shot's length and slide the later shots of its scene."""

    end = shot["start_frame"] + shot["duration_frames"]
    shot["duration_frames"] += frames
    if shot["duration_frames"] < 1:
        raise CueError("That would leave the shot with no frames.")
    for later in scene["shots"]:
        if later is not shot and later["start_frame"] >= end:
            later["start_frame"] += frames
    scene["target_runtime_frames"] = max(1, scene["target_runtime_frames"] + frames)


def _check_pose(episode: Episode, shot, actor_id: str, pose: str) -> None:
    actor = next(item for item in shot.actors if item.actor_id == actor_id)
    character = next(item for item in episode.assets.characters if item.asset_id == actor.character_id)
    allowed = allowed_poses(character.extension_poses)
    if pose not in allowed:
        raise CueError(f"{character.display_name.split()[0]} has no pose called {pose}. Theirs are: {', '.join(sorted(allowed))}.")


def _args(cue: Cue, count: int) -> list[str]:
    if len(cue.args) != count:
        raise CueError(f"{cue.verb} takes {count - 1} more words after the shot" if count > 2 else f"{cue.verb} takes a shot and one more word")
    return cue.args


def _frames(cue: Cue, index: int) -> int:
    if len(cue.args) <= index:
        raise CueError(f"{cue.verb} needs a number of frames")
    try:
        frames = int(cue.args[index].lstrip("+"))
    except ValueError as exc:
        raise CueError(f"{cue.args[index]} is not a number of frames") from exc
    if not 1 <= frames <= 2400:
        raise CueError("frames run from 1 to 2400")
    return frames


def _number(text: str, name: str) -> float:
    try:
        return float(text)
    except ValueError as exc:
        raise CueError(f"{name} needs a number") from exc


def _span(text: str, duration: int) -> tuple[int, int]:
    try:
        left, right = text.split("..")
        start, end = int(left), int(right)
    except ValueError as exc:
        raise CueError(f"{text} is not a frame range like 12..48") from exc
    if not 0 <= start < end <= duration:
        raise CueError(f"{text} does not fit in a shot of {duration} frames")
    return start, end


def _word(pose: str) -> str:
    return pose.replace("_", " ")


def _article(pose: str) -> str:
    return "an" if pose[:1] in "aeiou" else "a"


def _find(episode: Episode, shot_id: str):
    for scene in episode.scenes:
        for shot in scene.shots:
            if shot.shot_id == shot_id:
                return shot
    raise CueError(f"There is no shot {shot_id}.")


def _find_data(data: dict, shot_id: str) -> tuple[dict, dict]:
    for scene in data["scenes"]:
        for shot in scene["shots"]:
            if shot["shot_id"] == shot_id:
                return scene, shot
    raise CueError(f"There is no shot {shot_id}.")


def _next_revision(revision: str) -> str:
    number = int(revision.removeprefix("rev-")) + 1
    width = max(4, len(revision.removeprefix("rev-")))
    return f"rev-{number:0{width}d}"
