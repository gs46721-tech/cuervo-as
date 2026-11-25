import json
from pathlib import Path

from cuervo_ir.models import Episode
from cuervo_runtime.draw import FramePlayer, render_png
from cuervo_runtime.poses import UnknownPose
from examples.reference_scene import build_reference_episode
from tests.fixtures import solo_episode

POSES = json.loads((Path(__file__).resolve().parents[1] / "examples" / "sample-series" / "poses.json").read_text())


def test_generic_episode_renders_deterministically():
    episode = solo_episode()
    shot = episode.scenes[0].shots[0]
    first = render_png(episode, shot, 0)
    second = render_png(episode, shot, 0)
    assert first == second
    assert first.startswith(b"\x89PNG")


def test_camera_and_each_leg_change_the_frame():
    episode = solo_episode()
    shot = episode.scenes[0].shots[0]
    base = render_png(episode, shot, 0)
    shot.camera.transform.x = 120
    assert render_png(episode, shot, 0) != base
    shot.camera.transform.x = 0
    shot.action_tracks[0].mask = ["leg_l", "leg_r", "mouth"]
    left = render_png(episode, shot, 0, {"hold": {"leg_l": 1, "leg_r": -1}})
    right = render_png(episode, shot, 0, {"hold": {"leg_l": -1, "leg_r": 1}})
    assert left != right


def test_missing_shot_is_an_error():
    try:
        FramePlayer(solo_episode(), "sh_missing")
    except ValueError as exc:
        assert "sh_missing" in str(exc)
    else:
        raise AssertionError("missing shot was accepted")


def test_player_steps_and_sample_blink_changes_pixels():
    episode = build_reference_episode()
    player = FramePlayer(episode, "sh_establish", POSES)
    before = player.step()
    assert player.frame == 1
    player.seek(10)
    open_eyes = player.png()
    player.seek(40)
    closed = player.png()
    assert open_eyes != closed


def test_extension_pose_requires_series_library():
    episode = build_reference_episode()
    shot = next(shot for scene in episode.scenes for shot in scene.shots if shot.shot_id == "sh_two_shot")
    try:
        render_png(episode, shot, 120)
    except UnknownPose as exc:
        assert "deadpan" in str(exc)
    else:
        raise AssertionError("extension pose rendered without a library")
    assert render_png(episode, shot, 120, POSES).startswith(b"\x89PNG")


def test_sample_episode_round_trips_through_model():
    episode = Episode.model_validate(build_reference_episode().model_dump())
    assert render_png(episode, episode.scenes[0].shots[0], 0, POSES)
