from pathlib import Path

from cuervo_ir.models import Episode, Lock
from cuervo_ir.patch import PatchError, apply_timing_patch
from tests.fixtures import hold_patch, solo_episode

SRC = Path(__file__).resolve().parents[1] / "src"


def test_engine_source_does_not_name_the_sample_series():
    banned = ("nia", "cole", "adeyemi", "living_room", "five_minutes")
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for word in banned:
            assert word not in text, f"{path} contains {word}"


def test_generic_episode_accepts_a_timing_hold():
    episode = solo_episode()
    revised = apply_timing_patch(episode, hold_patch())
    shot = revised.scenes[0].shots[0]
    assert shot.duration_frames == 36
    assert shot.action_tracks[0].end_frame == 36
    assert shot.provenance.revision == "rev-0002"
    assert shot.actors[0].character_id == "char_a"
    assert revised.scenes[0].target_runtime_frames == 36


def test_generic_lock_rejects_a_timing_patch():
    episode = solo_episode()
    episode.scenes[0].shots[0].locks.append(
        Lock(lock_id="lock_hold", target_track_id="tr_hold", properties=["timing"])
    )
    episode = Episode.model_validate(episode.model_dump())
    try:
        apply_timing_patch(episode, hold_patch())
    except PatchError as exc:
        assert "locked" in str(exc)
    else:
        raise AssertionError("locked timing was applied")
