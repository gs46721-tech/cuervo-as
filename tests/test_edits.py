import json

from cuervo_ir.models import Episode, Lock
from cuervo_ir.providers.router import ModelRequest, ModelResponse, ProviderRouter
from cuervo_runtime.draw import render_png
from cuervo_edit.edits import EditError, affected, apply_edit, preview_frame
from cuervo_edit.propose import propose_edit
from tests.fixtures import stage_episode


def _patch(patch_id: str, **fields) -> dict:
    return {
        "kind": "edit_patch",
        "patch_id": patch_id,
        "target_shot_id": "sh_main",
        "base_revision": "rev-0001",
        "reason": patch_id,
        **fields,
    }


ANSWERS = {
    "hold the face 12 more frames": _patch(
        "patch_timing",
        timing=[{"track_id": "tr_face", "end_delta_frames": 12}],
        extend_shot_frames=12,
    ),
    "set the expression to react": _patch("patch_face", poses=[{"track_id": "tr_face", "pose": "react"}]),
    "point instead": _patch("patch_gesture", poses=[{"track_id": "tr_gesture", "pose": "point"}]),
    "look at stage left": _patch("patch_gaze", poses=[{"track_id": "tr_gaze", "pose": "look_at"}]),
    "cut to a close up": _patch("patch_camera", camera={"preset": "close_up", "x": 40}),
}


class IrPatch:
    name = "claude"

    def __init__(self):
        self.steps = []

    def available(self) -> bool:
        return True

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.steps.append(request.step)
        instruction = json.loads(request.user)["instruction"]
        return ModelResponse(provider="claude", model="stub", text=json.dumps(ANSWERS[instruction]))


def _router():
    return ProviderRouter({"claude": IrPatch()})


def _tracks(episode, shot_id):
    shot = next(shot for scene in episode.scenes for shot in scene.shots if shot.shot_id == shot_id)
    return {track.track_id: track.model_dump() for track in shot.action_tracks}


def test_five_revisions_do_not_spill():
    base = stage_episode()
    before = base.model_dump(mode="json")
    router = _router()
    cases = [
        ("hold the face 12 more frames", {"track:tr_face", "shot_duration", "later_shots"}),
        ("set the expression to react", {"track:tr_face"}),
        ("point instead", {"track:tr_gesture"}),
        ("look at stage left", {"track:tr_gaze"}),
        ("cut to a close up", {"camera"}),
    ]
    for instruction, expected in cases:
        patch = propose_edit(base, "sh_main", instruction, router)
        assert affected(patch) == expected
        revised = apply_edit(base, patch)
        assert base.model_dump(mode="json") == before
        original_tracks = _tracks(base, "sh_main")
        revised_tracks = _tracks(revised, "sh_main")
        if instruction.startswith("hold"):
            assert revised_tracks["tr_face"]["end_frame"] == 60
            assert revised.scenes[0].shots[1].start_frame == 60
            assert revised.scenes[0].shots[1].action_tracks == base.scenes[0].shots[1].action_tracks
            del original_tracks["tr_face"]
            del revised_tracks["tr_face"]
        elif instruction.startswith("set"):
            assert revised_tracks["tr_face"]["keyframes"][0]["pose"] == "react"
            del original_tracks["tr_face"]
            del revised_tracks["tr_face"]
            assert revised.scenes[0].shots[1].model_dump() == base.scenes[0].shots[1].model_dump()
        elif instruction.startswith("point"):
            assert revised_tracks["tr_gesture"]["keyframes"][0]["pose"] == "point"
            del original_tracks["tr_gesture"]
            del revised_tracks["tr_gesture"]
            assert revised.scenes[0].shots[1].model_dump() == base.scenes[0].shots[1].model_dump()
        elif instruction.startswith("look"):
            assert revised_tracks["tr_gaze"]["keyframes"][0]["pose"] == "look_at"
            del original_tracks["tr_gaze"]
            del revised_tracks["tr_gaze"]
            assert revised.scenes[0].shots[1].model_dump() == base.scenes[0].shots[1].model_dump()
        else:
            assert revised.scenes[0].shots[0].camera.preset == "close_up"
            assert revised.scenes[0].shots[0].camera.transform.x == 40
            assert revised.scenes[0].shots[1].model_dump() == base.scenes[0].shots[1].model_dump()
            original_png = render_png(base, base.scenes[0].shots[0], 0)
            assert preview_frame(base, patch, 0) != original_png
        assert revised_tracks == original_tracks
    assert router.providers["claude"].steps == ["ir_patch"] * 5


def test_locked_pose_and_wrong_shot_are_rejected():
    episode = stage_episode()
    episode.scenes[0].shots[0].locks.append(Lock(lock_id="lock_face", target_track_id="tr_face", properties=["pose"]))
    episode = Episode.model_validate(episode.model_dump())
    patch = propose_edit(episode, "sh_main", "set the expression to react", _router())
    try:
        apply_edit(episode, patch)
    except EditError as exc:
        assert "locked" in str(exc)
    else:
        raise AssertionError("locked pose was edited")

    class WrongShot:
        name = "claude"

        def available(self) -> bool:
            return True

        def complete(self, request: ModelRequest) -> ModelResponse:
            body = json.loads(request.user)
            body = {
                "kind": "edit_patch",
                "patch_id": "patch_other",
                "target_shot_id": "sh_next",
                "base_revision": body["base_revision"],
                "reason": "no",
                "camera": {"preset": "wide"},
            }
            return ModelResponse(provider="claude", model="stub", text=json.dumps(body))

    locked_camera = stage_episode()
    locked_camera.scenes[0].shots[0].locks.append(
        Lock(lock_id="lock_camera", target_track_id="tr_body", properties=["camera"])
    )
    locked_camera = Episode.model_validate(locked_camera.model_dump())
    camera_patch = propose_edit(locked_camera, "sh_main", "cut to a close up", _router())
    try:
        apply_edit(locked_camera, camera_patch)
    except EditError as exc:
        assert "camera" in str(exc)
    else:
        raise AssertionError("locked camera was edited")

    try:
        propose_edit(episode, "sh_main", "cut to a close up", ProviderRouter({"claude": WrongShot()}))
    except EditError as exc:
        assert "sh_next" in str(exc)
    else:
        raise AssertionError("patch for another shot was accepted")
