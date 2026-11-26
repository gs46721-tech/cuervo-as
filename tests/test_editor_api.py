import json

from fastapi.testclient import TestClient

from cuervo_ir.providers.router import ModelRequest, ModelResponse, ProviderRouter
from cuervo_editor.api import create_app
from cuervo_editor.stub import DevStub
from tests.fixtures import solo_episode, stage_episode


class Stub:
    """Plans whatever shots the test names, and always cuts closer."""

    name = "claude"
    model = "stub"

    def __init__(self, plan: dict | None = None):
        self.plan = plan
        self.steps: list[str] = []

    def available(self) -> bool:
        return True

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.steps.append(request.step)
        payload = json.loads(request.user)
        if request.step == "editor_assist":
            assert self.plan is not None
            return ModelResponse(provider="claude", model="stub", text=json.dumps(self.plan))
        assert request.step == "ir_patch"
        return ModelResponse(
            provider="claude",
            model="stub",
            text=json.dumps(
                {
                    "kind": "edit_patch",
                    "patch_id": "patch_editor",
                    "target_shot_id": payload["target_shot_id"],
                    "base_revision": payload["base_revision"],
                    "reason": payload["instruction"],
                    "camera": {"preset": "close_up", "x": 30},
                }
            ),
        )


def _client(stub: Stub | None = None, **options) -> TestClient:
    router = ProviderRouter({"claude": stub or Stub()})
    return TestClient(create_app(router, background=False, **options))


def _open(client: TestClient, episode, poses=None) -> dict:
    response = client.post("/api/sessions", json={"episode": episode.model_dump(mode="json"), "poses": poses})
    assert response.status_code == 200
    return response.json()


def _turn(client: TestClient, session_id: str, **body) -> dict:
    """Start a thread, send one turn, and return that turn."""

    thread_id = client.post(f"/api/sessions/{session_id}/threads").json()["thread_id"]
    response = client.post(f"/api/sessions/{session_id}/threads/{thread_id}/turns", json=body)
    assert response.status_code == 200, response.text
    state = response.json()
    thread = next(item for item in state["threads"] if item["thread_id"] == thread_id)
    return thread["turns"][-1]


def _shot(state: dict, shot_id: str) -> dict:
    return next(shot for shot in state["episode"]["shots"] if shot["shot_id"] == shot_id)


def test_two_unrelated_episodes_edit_and_undo():
    client = _client()
    first = _open(client, stage_episode())
    second = _open(client, solo_episode())
    assert second["episode"]["episode_id"] == "ep_a"
    assert first["episode"]["shots"][0]["shot_id"] == "sh_main"
    session_id = first["session_id"]
    frame = client.get(f"/api/sessions/{session_id}/frames/sh_main/0.png")
    assert frame.status_code == 200
    assert frame.content.startswith(b"\x89PNG")

    turn = _turn(client, session_id, instruction="cut closer", shot_ids=["sh_main"])
    assert turn["status"] == "done"
    change = turn["changes"][0]
    assert change["state"] == "pending"
    assert "camera" in change["affected"]
    assert {"target": "camera", "field": "preset", "before": "wide", "after": "close_up"} in change["diff"]
    # Nothing is written until the change is accepted.
    assert _shot(client.get(f"/api/sessions/{session_id}").json(), "sh_main")["camera_preset"] == "wide"
    preview = client.get(f"/api/sessions/{session_id}/changes/{change['change_id']}/frames/0.png")
    assert preview.status_code == 200
    assert preview.content != frame.content

    accepted = client.post(f"/api/sessions/{session_id}/changes/{change['change_id']}/accept").json()
    assert _shot(accepted, "sh_main")["camera_preset"] == "close_up"
    assert accepted["threads"][0]["turns"][0]["changes"][0]["state"] == "applied"
    undone = client.post(f"/api/sessions/{session_id}/undo").json()
    assert _shot(undone, "sh_main")["camera_preset"] == "wide"
    assert undone["threads"][0]["turns"][0]["changes"][0]["state"] == "undone"
    redone = client.post(f"/api/sessions/{session_id}/redo").json()
    assert _shot(redone, "sh_main")["camera_preset"] == "close_up"
    # The other project is still the untouched fixture.
    other = client.get(f"/api/sessions/{second['session_id']}").json()
    assert other["episode"]["shots"][0]["shot_id"] == "sh_a"
    assert other["undo"] == 0


def test_series_pose_table_is_required_to_preview_an_extension():
    client = _client()
    episode = solo_episode()
    episode.assets.characters[0].extension_poses = ["deadpan"]
    episode.scenes[0].shots[0].action_tracks[0].keyframes[0].pose = "deadpan"
    missing = _open(client, episode)
    assert client.get(f"/api/sessions/{missing['session_id']}/frames/sh_a/0.png").status_code == 422
    opened = _open(client, episode, {"deadpan": {"mouth": 0.2}})
    assert opened["redo"] == 0
    assert opened["has_poses"] is True
    framed = client.get(f"/api/sessions/{opened['session_id']}/frames/sh_a/0.png")
    assert framed.status_code == 200
    assert framed.content.startswith(b"\x89PNG")


def test_lock_blocks_the_next_camera_change_until_unlocked():
    client = _client()
    session_id = _open(client, stage_episode())["session_id"]
    lock = {"shot_id": "sh_main", "track_id": "tr_body", "properties": ["camera"]}
    locked = client.post(f"/api/sessions/{session_id}/lock", json=lock)
    assert locked.status_code == 200
    assert _shot(locked.json(), "sh_main")["camera_locked"] is True
    blocked = _turn(client, session_id, instruction="cut closer", shot_ids=["sh_main"])
    assert blocked["changes"][0]["state"] == "failed"
    assert "camera" in blocked["changes"][0]["error"].lower()
    unlocked = client.post(f"/api/sessions/{session_id}/lock", json={**lock, "properties": []}).json()
    assert _shot(unlocked, "sh_main")["camera_locked"] is False
    assert _turn(client, session_id, instruction="cut closer", shot_ids=["sh_main"])["changes"][0]["state"] == "pending"


def test_agent_picks_the_shots_when_none_are_pinned():
    plan = {
        "reply": "Both shots get a closer camera.",
        "edits": [
            {"shot_id": "sh_main", "instruction": "cut to a close up"},
            {"shot_id": "sh_next", "instruction": "cut to a close up"},
        ],
    }
    stub = Stub(plan)
    client = _client(stub)
    session_id = _open(client, stage_episode())["session_id"]
    turn = _turn(client, session_id, instruction="everything closer", focus_shot_id="sh_main")
    assert stub.steps == ["editor_assist", "ir_patch", "ir_patch"]
    assert turn["reply"] == "Both shots get a closer camera."
    assert [change["shot_id"] for change in turn["changes"]] == ["sh_main", "sh_next"]
    assert [step["status"] for step in turn["steps"]] == ["done", "done", "done"]

    accepted = client.post(f"/api/sessions/{session_id}/turns/{turn['turn_id']}/accept").json()
    assert accepted["undo"] == 2
    assert _shot(accepted, "sh_next")["camera_preset"] == "close_up"
    reverted = client.post(f"/api/sessions/{session_id}/turns/{turn['turn_id']}/revert").json()
    assert reverted["undo"] == 0
    assert _shot(reverted, "sh_main")["camera_preset"] == "wide"
    assert _shot(reverted, "sh_next")["camera_preset"] == "two_shot"


def test_a_question_gets_a_reply_and_no_changes():
    stub = Stub({"reply": "Two shots, 72 frames.", "edits": []})
    client = _client(stub)
    session_id = _open(client, stage_episode())["session_id"]
    turn = _turn(client, session_id, instruction="how long is this?")
    assert turn["reply"] == "Two shots, 72 frames."
    assert turn["changes"] == []
    assert stub.steps == ["editor_assist"]


def test_a_plan_for_an_unknown_shot_fails_the_turn():
    client = _client(Stub({"reply": "", "edits": [{"shot_id": "sh_missing", "instruction": "closer"}]}))
    session_id = _open(client, stage_episode())["session_id"]
    turn = _turn(client, session_id, instruction="closer")
    assert turn["status"] == "failed"
    assert "sh_missing" in turn["error"]


def test_auto_mode_applies_and_a_later_edit_discards_what_was_undone():
    client = _client()
    session_id = _open(client, stage_episode())["session_id"]
    first = _turn(client, session_id, instruction="cut closer", shot_ids=["sh_main"], mode="auto")
    assert first["changes"][0]["state"] == "applied"
    client.post(f"/api/sessions/{session_id}/undo")
    _turn(client, session_id, instruction="cut closer", shot_ids=["sh_next"], mode="auto")
    state = client.get(f"/api/sessions/{session_id}").json()
    assert state["threads"][0]["turns"][0]["changes"][0]["state"] == "discarded"
    assert state["redo"] == 0
    assert _shot(state, "sh_main")["camera_preset"] == "wide"
    assert _shot(state, "sh_next")["camera_preset"] == "close_up"


def test_a_waiting_change_goes_stale_when_its_shot_moves_on():
    client = _client()
    session_id = _open(client, stage_episode())["session_id"]
    waiting = _turn(client, session_id, instruction="cut closer", shot_ids=["sh_main"])
    _turn(client, session_id, instruction="cut closer", shot_ids=["sh_main"], mode="auto")
    state = client.get(f"/api/sessions/{session_id}").json()
    assert state["threads"][0]["turns"][0]["changes"][0]["stale"] is True
    refused = client.post(f"/api/sessions/{session_id}/changes/{waiting['changes'][0]['change_id']}/accept")
    assert refused.status_code == 422


def test_projects_and_threads_survive_a_restart(tmp_path):
    client = _client(home=tmp_path)
    session_id = _open(client, stage_episode())["session_id"]
    turn = _turn(client, session_id, instruction="cut closer", shot_ids=["sh_main"])
    client.post(f"/api/sessions/{session_id}/changes/{turn['changes'][0]['change_id']}/accept")

    again = _client(home=tmp_path)
    cards = again.get("/api/sessions").json()["sessions"]
    assert [card["session_id"] for card in cards] == [session_id]
    state = again.get(f"/api/sessions/{session_id}").json()
    assert state["threads"][0]["title"] == "cut closer"
    assert _shot(state, "sh_main")["camera_preset"] == "close_up"
    assert _shot(again.post(f"/api/sessions/{session_id}/undo").json(), "sh_main")["camera_preset"] == "wide"
    exported = again.get(f"/api/sessions/{session_id}/episode.json")
    assert exported.json()["kind"] == "episode"
    assert again.delete(f"/api/sessions/{session_id}").status_code == 200
    assert _client(home=tmp_path).get("/api/sessions").json()["sessions"] == []


def test_dev_stub_runs_a_whole_turn_without_keys():
    router = ProviderRouter(
        {"devstub": DevStub()},
        {"editor_assist": ("devstub",), "ir_patch": ("devstub",)},
    )
    client = TestClient(create_app(router, background=False))
    listed = client.get("/api/providers").json()
    assert listed["providers"] == [{"name": "devstub", "available": True, "model": "keywords"}]
    session_id = _open(client, stage_episode())["session_id"]
    turn = _turn(client, session_id, instruction="hold every shot 6 more frames", mode="auto")
    assert [change["state"] for change in turn["changes"]] == ["applied", "applied"]
    state = client.get(f"/api/sessions/{session_id}").json()
    assert _shot(state, "sh_main")["duration_frames"] == 54
    assert _shot(state, "sh_next")["start_frame"] == 54
    assert state["episode"]["total_frames"] == 84
