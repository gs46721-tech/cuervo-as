"""Starting, checking, and rendering an episode from inside the editor."""

from fastapi.testclient import TestClient

from cuervo_ir.providers.router import ProviderRouter
from cuervo_editor.api import create_app
from tests.test_production import SCRIPT, _designed_kit


def test_script_in_episode_open_notes_and_render_out(tmp_path):
    client = TestClient(create_app(ProviderRouter({}), background=False, home=tmp_path / "projects"))
    kit = _designed_kit().model_dump(mode="json")
    bad = client.post("/api/productions", json={"script": "INT. WORKSHOP\n\nZED\nHello.\n", "kit": kit})
    assert bad.status_code == 422 and "ZED" in bad.json()["detail"]

    job = client.post("/api/productions", json={"script": SCRIPT, "kit": kit}).json()
    assert job["status"] == "done", job
    assert "Recording voices and animating…" in job["log"]
    session_id = job["result"]["session_id"]
    state = client.get(f"/api/sessions/{session_id}").json()
    assert state["has_takes"] and state["has_world"] and state["rendered"] is False
    assert len(state["episode"]["scenes"]) == 2

    notes = client.get(f"/api/sessions/{session_id}/notes").json()["notes"]
    assert {"shot_id": "", "shot": "World", "severity": "look", "text": "The design for Ada is not approved yet."} in notes

    scene = state["episode"]["scenes"][0]["scene_id"]
    approved = client.post(f"/api/sessions/{session_id}/scenes/{scene}", json={"approved": True}).json()
    assert approved["approved_scenes"] == [scene]

    assert client.get(f"/api/sessions/{session_id}/master.mp4").status_code == 404
    first = client.post(f"/api/sessions/{session_id}/render", json={"width": 640, "height": 360}).json()
    assert first["status"] == "done", first
    assert first["result"]["reused"] == 0 and first["result"]["failed"] == 0
    video = client.get(f"/api/sessions/{session_id}/master.mp4")
    assert video.status_code == 200 and video.headers["content-type"] == "video/mp4" and len(video.content) > 10_000
    assert client.get(f"/api/sessions/{session_id}").json()["rendered"] is True
    # Nothing changed, so a second render draws nothing.
    again = client.post(f"/api/sessions/{session_id}/render", json={"width": 640, "height": 360}).json()
    assert again["result"]["reused"] == again["result"]["shots"]


def test_live_check_reports_each_job_in_plain_words():
    client = TestClient(create_app(ProviderRouter({}), background=False))
    job = client.post("/api/settings/livecheck").json()
    assert job["status"] == "done"
    assert job["result"]["checks"] == [
        {"job": "Voices", "who": "elevenlabs", "ok": False, "detail": "Not connected. Voices use the test tone.", "seconds": 0}
    ]
