"""Checks for the sample episode. Engine rules live in test_engine.py."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from cuervo_ir.contract import (
    CONTROLLER_LIMITS,
    EYE_CONTROLLERS,
    MOUTH_CONTROLLERS,
    REQUIRED_POSES,
    STANDARD_CONTROLLERS,
)
from cuervo_ir.frame_time import frame_to_sample_start, sample_to_frame
from cuervo_ir.models import Episode, Lock
from cuervo_ir.patch import PatchError, apply_timing_patch
from cuervo_ir.schema import REPO_SCHEMA_PATH, ir_json_schema
from examples.reference_scene import (
    EPISODE_PATH,
    PATCH_PATH,
    TARGET_FRAMES,
    build_hold_reaction_patch,
    build_reference_episode,
)

ROOT = Path(__file__).resolve().parents[1]


def test_checked_in_schema_matches_models():
    assert json.loads(REPO_SCHEMA_PATH.read_text(encoding="utf-8")) == ir_json_schema()


def test_reference_files_match_builders_and_schema():
    episode_payload = json.loads(EPISODE_PATH.read_text(encoding="utf-8"))
    patch_payload = json.loads(PATCH_PATH.read_text(encoding="utf-8"))
    assert episode_payload == build_reference_episode().model_dump(mode="json")
    assert patch_payload == build_hold_reaction_patch().model_dump(mode="json")
    validator = Draft202012Validator(ir_json_schema())
    validator.validate(episode_payload)
    validator.validate(patch_payload)


def test_reference_scene_is_the_phase0_slice():
    episode = build_reference_episode()
    assert len(episode.assets.characters) == 2
    assert [item.asset_id for item in episode.assets.backgrounds] == ["bg_living_room"]
    scene = episode.scenes[0]
    assert scene.setting_id == "bg_living_room"
    frames = sum(shot.duration_frames for shot in scene.shots)
    assert frames == TARGET_FRAMES
    assert 30 * episode.fps <= frames <= 60 * episode.fps
    assert scene.target_runtime_frames == frames
    assert [track.text for shot in scene.shots for track in shot.dialogue_tracks] == [
        "You said five minutes.",
        "I said five minutes of quiet. You used four of them finding the remote.",
        "It's under you.",
        "Then we watch nothing.",
        "That's the plan I had before I sat down.",
    ]
    for shot in scene.shots:
        assert [(actor.character_id, actor.stage.x, actor.facing) for actor in shot.actors] == [
            ("char_nia", -180, "three_quarter_right"),
            ("char_cole", 180, "three_quarter_left"),
        ]
        assert all(track.voice_take_id is None and track.alignment == [] and track.visemes == [] for track in shot.dialogue_tracks)


def test_hold_reaction_changes_only_timing_dependents():
    episode = build_reference_episode()
    before = episode.model_dump(mode="json")
    revised = apply_timing_patch(episode, build_hold_reaction_patch())
    assert episode.model_dump(mode="json") == before

    original_shot = episode.scenes[0].shots[2]
    revised_shot = revised.scenes[0].shots[2]
    assert original_shot.shot_id == "sh_reaction"
    assert revised_shot.duration_frames == original_shot.duration_frames + 12
    assert revised_shot.provenance.revision == "rev-0002"
    assert revised_shot.provenance.parent_revision == "rev-0001"
    assert revised_shot.provenance.source == "patch_hold_reaction_12"

    original_tracks = {track.track_id: track.model_dump() for track in original_shot.action_tracks}
    revised_tracks = {track.track_id: track.model_dump() for track in revised_shot.action_tracks}
    assert revised_tracks["tr_nia_react"]["end_frame"] == original_tracks["tr_nia_react"]["end_frame"] + 12
    del original_tracks["tr_nia_react"]
    del revised_tracks["tr_nia_react"]
    assert revised_tracks == original_tracks
    assert [track.model_dump() for track in revised_shot.dialogue_tracks] == [
        track.model_dump() for track in original_shot.dialogue_tracks
    ]
    assert revised_shot.camera.model_dump() == original_shot.camera.model_dump()
    assert [actor.model_dump() for actor in revised_shot.actors] == [actor.model_dump() for actor in original_shot.actors]

    assert revised.scenes[0].shots[0].model_dump() == episode.scenes[0].shots[0].model_dump()
    assert revised.scenes[0].shots[1].model_dump() == episode.scenes[0].shots[1].model_dump()
    button = revised.scenes[0].shots[3]
    assert button.start_frame == episode.scenes[0].shots[3].start_frame + 12
    assert button.duration_frames == episode.scenes[0].shots[3].duration_frames
    assert button.action_tracks == episode.scenes[0].shots[3].action_tracks
    assert revised.scenes[0].target_runtime_frames == TARGET_FRAMES + 12
    assert sum(shot.duration_frames for shot in revised.scenes[0].shots) == TARGET_FRAMES + 12


def test_locked_timing_and_stale_revision_are_rejected():
    episode = build_reference_episode()
    shot = episode.scenes[0].shots[2]
    locked = episode.model_copy(deep=True)
    locked.scenes[0].shots[2].locks.append(
        Lock(lock_id="lock_react_timing", target_track_id="tr_nia_react", properties=["timing"])
    )
    locked = Episode.model_validate(locked.model_dump())
    try:
        apply_timing_patch(locked, build_hold_reaction_patch())
    except PatchError as exc:
        assert "locked" in str(exc)
    else:
        raise AssertionError("locked timing was applied")

    stale = build_hold_reaction_patch().model_copy(update={"base_revision": "rev-0009"})
    try:
        apply_timing_patch(episode, stale)
    except PatchError as exc:
        assert "rev-0009" in str(exc)
    else:
        raise AssertionError("stale revision was applied")

    # The reaction track already ends on the shot boundary. Extending it
    # without growing the shot is not a valid document.
    short = build_hold_reaction_patch().model_copy(update={"extend_shot_frames": 0})
    try:
        apply_timing_patch(episode, short)
    except PatchError:
        pass
    else:
        raise AssertionError("track was allowed to leave the shot")
    assert shot.provenance.revision == "rev-0001"


def test_sample_time_maps_to_whole_frames():
    assert sample_to_frame(0, 48_000, 24) == 0
    assert sample_to_frame(47_999, 48_000, 24) == 23
    assert sample_to_frame(48_000, 48_000, 24) == 24
    assert frame_to_sample_start(24, 48_000, 24) == 48_000
    assert sample_to_frame(frame_to_sample_start(10, 48_000, 24), 48_000, 24) == 10


def test_rig_contract_covers_required_library():
    assert CONTROLLER_LIMITS.keys() == set(STANDARD_CONTROLLERS)
    assert set(MOUTH_CONTROLLERS).issubset(STANDARD_CONTROLLERS)
    assert set(EYE_CONTROLLERS).issubset(STANDARD_CONTROLLERS)
    assert REQUIRED_POSES == (
        "idle",
        "blink",
        "nod",
        "look_at",
        "shrug",
        "point",
        "walk",
        "sit",
        "stand",
        "react",
        "recoil",
        "hold",
    )
