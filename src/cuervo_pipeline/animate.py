"""Stage 3, animation. Time every shot to its voice takes and lay in the acting.

Dialogue is recorded first. A line is as long as its take, and the shot is as
long as its lines. The mouth follows the take's alignment. Gestures,
expressions, eyelines, and blinks are tracks an editor can change afterwards.
"""

from __future__ import annotations

import hashlib
import json
import math

from pydantic import BaseModel, ConfigDict, ValidationError

from cuervo_ir.contract import allowed_poses
from cuervo_ir.models import DialogueTrack, Episode
from cuervo_ir.providers.router import ModelRequest, ProviderError, ProviderRouter
from cuervo_pipeline.board import BoardScene, BoardShot, Storyboard
from cuervo_pipeline.series import SeriesKit, slug
from cuervo_runtime.poses import CONTRACT_POSES
from cuervo_voice.takes import Take
from cuervo_voice.visemes import viseme_keys

# Frames of air around dialogue. On twos at 24 fps these are 1/3, 1/4, and 1/2 second.
LEAD_FRAMES = 8
GAP_FRAMES = 6
TAIL_FRAMES = 12
ESTABLISH_FRAMES = 48
REACTION_FRAMES = 30
BLINK_FRAMES = 3

# Camera scale for each shot size, and how far the cast spreads across the stage.
CAMERA_SCALE = {"wide": 1.0, "two_shot": 1.5, "over_the_shoulder": 1.8, "close_up": 2.4, "reaction": 2.2, "insert": 2.6}
STAGE_SPAN = 360.0

BODY = ("root", "torso", "leg_l", "leg_r")
ARMS = ("arm_l", "arm_r", "hand_l", "hand_r")
FACE = ("brow_l", "brow_r", "eye_l", "eye_r")
LOOK = ("gaze_yaw", "gaze_pitch", "head", "neck")


class LineActing(BaseModel):
    """Poses for one line. Any of them may be empty."""

    model_config = ConfigDict(extra="ignore")

    gesture: str = ""
    expression: str = ""
    # What the listener does while the line is said.
    reaction: str = ""


ACTING_SYSTEM = (
    "You direct the acting for one scene of a 2D animated sitcom. For each line choose poses from that "
    "character's pose list. Return only JSON {\"lines\": {line_id: {\"gesture\": pose or \"\", "
    "\"expression\": pose or \"\", \"reaction\": pose or \"\"}}}. `gesture` and `expression` are for the "
    "speaker. `reaction` is for the listener and comes from the listener's list. One idea at a time: leave "
    "a field empty rather than fill every line. A joke lands on a held expression, not on more movement."
)


def direct_acting(board: Storyboard, kit: SeriesKit, router: ProviderRouter | None, *, log=None) -> dict[str, LineActing]:
    """Ask the `direction` route for acting, scene by scene. A scene it cannot do gets the default acting."""

    acting: dict[str, LineActing] = {}
    for scene in board.scenes:
        lines = [line for shot in scene.shots for line in shot.lines]
        chosen: dict[str, LineActing] = {}
        if router is not None and lines:
            try:
                chosen = _ask_acting(scene, kit, router)
            except (ProviderError, ValueError) as exc:
                if log:
                    log(f"  {scene.scene_id}: default acting ({exc})")
        for index, line in enumerate(lines):
            acting[line.line_id] = chosen.get(line.line_id) or _default_acting(line.text, index)
    return acting


def _ask_acting(scene: BoardScene, kit: SeriesKit, router: ProviderRouter) -> dict[str, LineActing]:
    poses = {item: sorted(allowed_poses(kit.character(item).extension_poses)) for item in scene.cast}
    response = router.complete(
        ModelRequest(
            step="direction",
            system=ACTING_SYSTEM,
            user=json.dumps(
                {
                    "objective": scene.objective,
                    "emotional_trajectory": scene.emotional_trajectory,
                    "poses": poses,
                    "lines": [
                        {"line_id": line.line_id, "character_id": line.character_id, "text": line.text, "direction": line.direction}
                        for shot in scene.shots
                        for line in shot.lines
                    ],
                }
            ),
        )
    )
    text = response.text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        body = json.loads(text)
        return {line_id: LineActing.model_validate(item) for line_id, item in body["lines"].items()}
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError, ValidationError) as exc:
        raise ValueError(f"{response.provider} did not return acting") from exc


def _default_acting(text: str, index: int) -> LineActing:
    stripped = text.rstrip()
    if stripped.endswith("?"):
        return LineActing(gesture="shrug", reaction="look_at")
    if stripped.endswith("!"):
        return LineActing(gesture="point", expression="react", reaction="recoil")
    if index % 3 == 2:
        return LineActing(reaction="nod")
    return LineActing()


def build_episode(
    board: Storyboard,
    kit: SeriesKit,
    takes: dict[str, Take],
    acting: dict[str, LineActing] | None = None,
) -> Episode:
    """Assemble the Animation IR. `takes` maps each line_id to its recorded take."""

    acting = acting or {}
    episode_id = slug(board.title, "ep")
    characters = {item.asset_id: item for item in kit.characters}
    used_sets = {scene.set_id for scene in board.scenes}
    used_cast = {item for scene in board.scenes for item in scene.cast}
    scenes = []
    for scene in board.scenes:
        shots = []
        cursor = 0
        for index, shot in enumerate(scene.shots):
            last = index == len(scene.shots) - 1
            built = _shot(shot, scene, kit, takes, acting, cursor, last)
            shots.append(built)
            cursor += built["duration_frames"]
        scenes.append(
            {
                "scene_id": scene.scene_id,
                "episode_id": episode_id,
                "title": scene.title,
                "objective": scene.objective,
                "setting_id": scene.set_id,
                "emotional_trajectory": scene.emotional_trajectory,
                "continuity": [],
                "target_runtime_frames": cursor,
                "shots": shots,
            }
        )
    data = {
        "kind": "episode",
        "episode_id": episode_id,
        "version": "0.1.0",
        "title": board.title,
        "fps": kit.fps,
        "assets": {
            "characters": [
                {
                    "asset_id": item.asset_id,
                    "version": item.version,
                    "display_name": item.display_name,
                    "rig_id": item.rig_id,
                    "rig_version": item.rig_version,
                    "extension_poses": item.extension_poses,
                }
                for item in kit.characters
                if item.asset_id in used_cast
            ],
            "rigs": [
                {"asset_id": item.rig_id, "version": item.rig_version, "character_id": item.asset_id}
                for item in kit.characters
                if item.asset_id in used_cast
            ],
            "backgrounds": [
                {"asset_id": item.asset_id, "version": item.version, "display_name": item.display_name, "location_id": item.location_id}
                for item in kit.sets
                if item.asset_id in used_sets
            ],
        },
        "scenes": scenes,
    }
    del characters
    return Episode.model_validate(data)


def _shot(shot: BoardShot, scene: BoardScene, kit: SeriesKit, takes, acting, start: int, last: bool) -> dict:
    fps = kit.fps
    cast = scene.cast
    actor_of = {character_id: f"act_{character_id.removeprefix('char_')}"[:64] for character_id in cast}
    positions = _positions(cast)

    # Timing: lead, each line at the length of its take, a gap, and a tail.
    cursor = LEAD_FRAMES
    timed: list[tuple] = []
    for line in shot.lines:
        take = takes[line.line_id]
        length = max(2, math.ceil(take.sample_count * fps / take.sample_rate))
        timed.append((line, take, cursor, cursor + length))
        cursor += length + GAP_FRAMES
    if timed:
        duration = timed[-1][3] + (TAIL_FRAMES * 2 if last else TAIL_FRAMES)
    else:
        duration = ESTABLISH_FRAMES if shot.preset in ("wide", "two_shot") else REACTION_FRAMES

    tracks: list[dict] = []

    def track(name: str, kind: str, actor: str, begin: int, end: int, pose: str, mask, priority: int, ease: bool = False) -> None:
        end = min(end, duration)
        if end - begin < 1:
            return
        tracks.append(
            {
                "track_id": f"tr_{shot.shot_id.removeprefix('sh_')}_{name}"[:64],
                "kind": kind,
                "target_actor_id": actor,
                "start_frame": begin,
                "end_frame": end,
                "interpolation": "ease_in_out" if ease else "stepped",
                "mask": list(mask),
                "priority": priority,
                "blend_mode": "override",
                "keyframes": [{"frame": begin, "pose": pose, "weight": 1.0}],
            }
        )

    for character_id in cast:
        actor = actor_of[character_id]
        short = actor.removeprefix("act_")
        track(f"{short}_body", "pose", actor, 0, duration, kit.character(character_id).rest_pose, BODY, 10)
        # Blinks on a steady, per-character rhythm, offset so the cast does not blink together.
        seed = int(hashlib.sha256(f"{shot.shot_id}:{actor}".encode()).hexdigest()[:6], 16)
        at = 18 + seed % 40
        count = 0
        while at + BLINK_FRAMES < duration:
            track(f"{short}_blink{count}", "secondary", actor, at, at + BLINK_FRAMES, "blink", ("blink",), 50)
            at += 72 + (seed >> (count % 8)) % 36
            count += 1

    dialogue: list[dict] = []
    for number, (line, take, begin, end) in enumerate(timed):
        speaker = actor_of[line.character_id]
        short = speaker.removeprefix("act_")
        choice = acting.get(line.line_id) or LineActing()
        speaker_poses = allowed_poses(kit.character(line.character_id).extension_poses)
        if choice.gesture in speaker_poses:
            _pose_track(track, f"{short}_g{number}", speaker, begin, end, choice.gesture, kit, 20, "gesture", ARMS)
        if choice.expression in speaker_poses:
            _pose_track(track, f"{short}_e{number}", speaker, begin, end + GAP_FRAMES, choice.expression, kit, 40, "expression", FACE)
        for character_id in cast:
            if character_id == line.character_id:
                continue
            listener = actor_of[character_id]
            name = listener.removeprefix("act_")
            # Listeners look at whoever is speaking.
            track(f"{name}_look{number}", "gaze", listener, begin, end, "look_at", ("gaze_yaw", "head"), 30)
            if choice.reaction in allowed_poses(kit.character(character_id).extension_poses) and choice.reaction != "look_at":
                middle = begin + (end - begin) // 2
                _pose_track(track, f"{name}_r{number}", listener, middle, end + GAP_FRAMES, choice.reaction, kit, 45, "expression", FACE)
        base = {
            "track_id": f"tr_{line.line_id}",
            "speaker_actor_id": speaker,
            "line_id": line.line_id,
            "text": line.text,
            "voice_take_id": take.take_id,
            "voice_take_version": "1.0.0",
            "start_frame": begin,
            "end_frame": end,
            "alignment": [span.model_dump(mode="json") for span in take.alignment],
            "visemes": [],
        }
        keys = viseme_keys(DialogueTrack.model_validate(base), take.alignment, sample_rate=take.sample_rate, fps=fps)
        base["visemes"] = [key.model_dump(mode="json") for key in keys]
        dialogue.append(base)

    focus = shot.focus if shot.focus in cast else None
    if focus is not None:
        camera_x = positions[focus] * 1.4
    elif shot.preset == "two_shot" and timed:
        speakers = list(dict.fromkeys(line.character_id for line, *_ in timed))[:2]
        camera_x = sum(positions[item] for item in speakers) / len(speakers) * 1.4 if len(cast) > 2 else 0.0
    else:
        camera_x = 0.0
    scale = CAMERA_SCALE[shot.preset]
    if focus is None and shot.preset != "wide" and len(cast) > 2:
        scale = min(scale, 1.2)

    return {
        "shot_id": shot.shot_id,
        "scene_id": scene.scene_id,
        "fps": fps,
        "start_frame": start,
        "duration_frames": duration,
        "asset_refs": [
            *({"role": "character", "asset_id": item, "version": kit.character(item).version} for item in cast),
            *({"role": "rig", "asset_id": kit.character(item).rig_id, "version": kit.character(item).rig_version} for item in cast),
            {"role": "background", "asset_id": scene.set_id, "version": next(s.version for s in kit.sets if s.asset_id == scene.set_id)},
        ],
        "camera": {
            "preset": shot.preset,
            "framing": shot.framing,
            "transform": {"space": "camera", "unit": "px", "x": round(camera_x, 2), "y": 0.0, "scale": scale},
        },
        "actors": [
            {
                "actor_id": actor_of[item],
                "character_id": item,
                "rig_id": kit.character(item).rig_id,
                "rig_instance_id": f"riginst_{item.removeprefix('char_')}"[:64],
                "stage": {"space": "stage", "unit": "px", "x": positions[item], "y": 0.0},
                "facing": "front" if len(cast) == 1 else "three_quarter_right" if positions[item] < 0 else "three_quarter_left",
                "depth": 2,
            }
            for item in cast
        ],
        "action_tracks": tracks,
        "dialogue_tracks": dialogue,
        "provenance": {"revision": "rev-0001", "source": "pipeline", "note": shot.action or shot.framing},
    }


def _pose_track(track, name: str, actor: str, begin: int, end: int, pose: str, kit: SeriesKit, priority: int, kind: str, fallback) -> None:
    """Mask a pose to the controllers it sets, so it never fights the body or the mouth."""

    values = kit.poses.get(pose) or CONTRACT_POSES.get(pose) or {}
    touched = [name_ for name_ in values if name_ not in ("mouth", "jaw")]
    if not touched:
        touched = list(fallback)
    if set(touched) <= set(ARMS):
        kind = "gesture"
    elif set(touched) <= set(LOOK):
        kind = "gaze"
    elif set(touched) <= set(BODY):
        kind = "pose"
    track(name, kind, actor, begin, end, pose, touched, priority, kind == "gesture")


def _positions(cast: list[str]) -> dict[str, float]:
    if len(cast) == 1:
        return {cast[0]: 0.0}
    step = STAGE_SPAN / (len(cast) - 1)
    return {item: round(-STAGE_SPAN / 2 + step * index, 2) for index, item in enumerate(cast)}
