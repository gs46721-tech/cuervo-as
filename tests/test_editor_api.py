import json

from fastapi.testclient import TestClient

from cuervo_ir.providers.router import ModelRequest, ModelResponse, ProviderRouter
from cuervo_editor.api import create_app
from tests.fixtures import solo_episode, stage_episode


class Stub:
    name = "claude"

    def available(self) -> bool:
        return True

    def complete(self, request: ModelRequest) -> ModelResponse:
        assert request.step == "ir_patch"
        payload = json.loads(request.user)
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


def _client() -> TestClient:
    return TestClient(create_app(ProviderRouter({"claude": Stub()})))


def test_two_unrelated_episodes_edit_and_undo():
    client = _client()
    first = client.post("/api/sessions", json={"episode": stage_episode().model_dump(mode="json")})
    second = client.post("/api/sessions", json={"episode": solo_episode().model_dump(mode="json")})
    assert first.status_code == 200
    assert second.json()["episode"]["episode_id"] == "ep_a"
    assert first.json()["episode"]["shots"][0]["shot_id"] == "sh_main"
    session_id = first.json()["session_id"]
    frame = client.get(f"/api/sessions/{session_id}/frames/sh_main/0.png")
    assert frame.status_code == 200
    assert frame.content.startswith(b"\x89PNG")
    proposed = client.post(
        f"/api/sessions/{session_id}/propose",
        json={"shot_id": "sh_main", "instruction": "cut closer"},
    )
    assert proposed.status_code == 200
    assert "camera" in proposed.json()["affected"]
    assert proposed.json()["diff"]
    accepted = client.post(f"/api/sessions/{session_id}/accept")
    assert accepted.json()["episode"]["shots"][0]["camera_preset"] == "close_up"
    undone = client.post(f"/api/sessions/{session_id}/undo")
    assert undone.json()["episode"]["shots"][0]["camera_preset"] == "wide"
    redone = client.post(f"/api/sessions/{session_id}/redo")
    assert redone.json()["episode"]["shots"][0]["camera_preset"] == "close_up"
    # The other session is still the untouched fixture.
    assert second.json()["episode"]["shots"][0]["shot_id"] == "sh_a"


def test_lock_blocks_the_next_pose_proposal():
    client = _client()
    opened = client.post("/api/sessions", json={"episode": stage_episode().model_dump(mode="json")})
    session_id = opened.json()["session_id"]
    locked = client.post(
        f"/api/sessions/{session_id}/lock",
        json={"shot_id": "sh_main", "track_id": "tr_body", "properties": ["camera"]},
    )
    assert locked.status_code == 200
    blocked = client.post(
        f"/api/sessions/{session_id}/propose",
        json={"shot_id": "sh_main", "instruction": "cut closer"},
    )
    assert blocked.status_code == 422
    assert "camera" in blocked.json()["detail"].lower()
