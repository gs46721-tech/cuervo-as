import json

from fastapi.testclient import TestClient

from cuervo_ir.providers.router import ModelRequest, ModelResponse, ProviderRouter
from cuervo_editor.api import create_app
from cuervo_editor.stub import DevStub
from cuervo_pipeline.produce import produce
from tests.fixtures import solo_episode, stage_episode
from tests.test_production import SCRIPT, _kit


class Crew:
    """A model that types the cues the test hands it, one reply per round."""

    name = "claude"
    model = "stub"

    def __init__(self, *replies: str):
        self.replies = list(replies) or ['camera {on_screen} close_up\ndone "Cut closer."']
        self.briefs: list[dict] = []

    def available(self) -> bool:
        return True

    def complete(self, request: ModelRequest) -> ModelResponse:
        assert request.step == "editor_assist"
        brief = json.loads(request.user)
        self.briefs.append(brief)
        reply = self.replies[min(len(self.briefs), len(self.replies)) - 1]
        return ModelResponse(provider="claude", model="stub", text=reply.replace("{on_screen}", brief["on_screen"]))


def _client(crew: Crew | None = None, **options) -> TestClient:
    return TestClient(create_app(ProviderRouter({"claude": crew or Crew()}), background=False, **options))


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
    assert first["episode"]["shots"][0]["label"] == "Shot 1"
    session_id = first["session_id"]
    frame = client.get(f"/api/sessions/{session_id}/frames/sh_main/0.png")
    assert frame.status_code == 200
    assert frame.content.startswith(b"\x89PNG")

    turn = _turn(client, session_id, instruction="cut closer", shot_ids=["sh_main"])
    assert turn["status"] == "done"
    assert turn["reply"] == "Cut closer."
    change = turn["changes"][0]
    assert change["state"] == "pending"
    # The page gets a sentence, never the cue behind it.
    assert change["summary"] == ["Reframe shot 1 from a wide shot to a close-up."]
    assert "cues" not in change and "camera sh_main" not in json.dumps(turn)
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


def test_a_locked_camera_is_refused_in_plain_words_until_unlocked():
    client = _client()
    session_id = _open(client, stage_episode())["session_id"]
    lock = {"shot_id": "sh_main", "track_id": "tr_body", "properties": ["camera"]}
    locked = client.post(f"/api/sessions/{session_id}/lock", json=lock)
    assert _shot(locked.json(), "sh_main")["camera_locked"] is True
    blocked = _turn(client, session_id, instruction="cut closer", shot_ids=["sh_main"])
    assert blocked["changes"] == []
    assert blocked["reply"] == "The camera is locked on shot 1."
    assert [step["label"] for step in blocked["steps"] if step["status"] == "failed"] == ["The camera is locked on shot 1"]
    unlocked = client.post(f"/api/sessions/{session_id}/lock", json={**lock, "properties": []}).json()
    assert _shot(unlocked, "sh_main")["camera_locked"] is False
    assert _turn(client, session_id, instruction="cut closer", shot_ids=["sh_main"])["changes"][0]["state"] == "pending"


def test_the_agent_looks_around_then_changes_several_shots():
    crew = Crew(
        "scenes\nshow sh_next",
        'camera sh_main close_up\ncamera sh_next close_up\nact sh_next act_a shrug 0..12\ndone "Both shots are closer, and there is a shrug at the top of shot 2."',
    )
    client = _client(crew)
    session_id = _open(client, stage_episode())["session_id"]
    turn = _turn(client, session_id, instruction="everything closer, and a shrug", focus_shot_id="sh_main")
    assert len(crew.briefs) == 2
    # The second round sees what the read cues printed.
    assert "> show sh_next" in crew.briefs[1]["session"] and "tr_next_body" in crew.briefs[1]["session"]
    assert turn["reply"].startswith("Both shots are closer")
    assert [change["shot_id"] for change in turn["changes"]] == ["sh_main", "sh_next"]
    assert turn["changes"][1]["summary"] == [
        "Reframe shot 2 from a two-shot to a close-up.",
        "Add a shrug for Figure in shot 2, from 0 s to 0.5 s.",
    ]
    assert [step["label"] for step in turn["steps"]][:2] == ["Looked over the episode", "Looked at shot 2"]

    accepted = client.post(f"/api/sessions/{session_id}/turns/{turn['turn_id']}/accept").json()
    assert accepted["undo"] == 2
    assert _shot(accepted, "sh_next")["camera_preset"] == "close_up"
    assert any(track["pose"] == "shrug" and track["who"] == "Figure" for track in _shot(accepted, "sh_next")["tracks"])
    reverted = client.post(f"/api/sessions/{session_id}/turns/{turn['turn_id']}/revert").json()
    assert reverted["undo"] == 0
    assert _shot(reverted, "sh_next")["camera_preset"] == "two_shot"


def test_a_failed_cue_goes_back_to_the_agent_and_pinned_shots_are_enforced():
    crew = Crew("show sh_main\npose sh_main tr_face dance", 'pose sh_main tr_face react\ncamera sh_next wide\ndone "Changed the face."')
    client = _client(crew)
    session_id = _open(client, stage_episode())["session_id"]
    turn = _turn(client, session_id, instruction="make the face react", shot_ids=["sh_main"])
    assert "error: Figure has no pose called dance" in crew.briefs[1]["session"]
    assert [change["shot_id"] for change in turn["changes"]] == ["sh_main"]
    assert turn["changes"][0]["summary"] == ["Change Figure's expression from hold to react in shot 1."]
    assert any("pinned other shots" in step["label"] for step in turn["steps"])


def test_a_question_gets_a_reply_and_no_changes():
    client = _client(Crew('done "Two shots, three seconds."'))
    session_id = _open(client, stage_episode())["session_id"]
    turn = _turn(client, session_id, instruction="how long is this?")
    assert turn["reply"] == "Two shots, three seconds."
    assert turn["changes"] == []


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


def test_hold_trim_move_drop_and_cut_keep_the_scene_in_order():
    crew = Crew('hold sh_main 12\nmove sh_main tr_gesture 6..30\ndrop sh_main tr_gaze\ntrim sh_next 6\ndone "Retimed."', 'cut sh_next\ndone "Cut it."')
    client = _client(crew)
    session_id = _open(client, stage_episode())["session_id"]
    turn = _turn(client, session_id, instruction="retime", mode="auto")
    assert turn["changes"][0]["summary"] == [
        "Hold shot 1 for 12 more frames (0.5 s).",
        "Move Figure's shrug in shot 1 to run from 0.2 s to 1.2 s.",
        "Remove Figure's idle from shot 1.",
    ]
    state = client.get(f"/api/sessions/{session_id}").json()
    main, following = _shot(state, "sh_main"), _shot(state, "sh_next")
    assert main["duration_frames"] == 60 and following["start_frame"] == 60 and following["duration_frames"] == 18
    # Tracks that ran to the end of the shot still do.
    assert {track["track_id"]: track["end_frame"] for track in main["tracks"]} == {"tr_body": 60, "tr_gesture": 30, "tr_face": 60}
    _turn(client, session_id, instruction="lose the second shot", mode="auto")
    state = client.get(f"/api/sessions/{session_id}").json()
    assert [shot["shot_id"] for shot in state["episode"]["shots"]] == ["sh_main"]
    assert state["episode"]["total_frames"] == 60


def test_rewriting_a_line_records_it_again_and_retimes_the_shot(tmp_path):
    built = produce(SCRIPT, _kit(), tmp_path, router=None, through="animation", log=lambda _line: None)
    crew = Crew('find "small one"', 'say sh_0002 ln_0001 "Hand me the very small one, the one by your elbow."\ndone "Rewrote it."')
    app = create_app(ProviderRouter({"claude": crew}), background=False)
    client = TestClient(app)
    opened = _open(client, built.episode)
    session_id = opened["session_id"]
    app.state.store.get(session_id).takes_dir = str(tmp_path / "takes")
    before = _shot(opened, "sh_0002")
    turn = _turn(client, session_id, instruction="make the first line longer", mode="auto")
    assert 'ln_0001 act_ada: "Hand me the small one."' in crew.briefs[1]["session"]
    assert turn["changes"][0]["summary"][0].endswith("It is recorded again and the shot is retimed to it.")
    after = _shot(client.get(f"/api/sessions/{session_id}").json(), "sh_0002")
    line = after["lines"][0]
    assert line["text"].startswith("Hand me the very small one")
    grew = after["duration_frames"] - before["duration_frames"]
    assert grew > 0 and line["end_frame"] - before["lines"][0]["end_frame"] == grew
    # The audio the page plays is the new take, at the new length.
    wav = client.get(f"/api/sessions/{session_id}/audio/sh_0002.wav")
    assert len(wav.content) - 44 == after["duration_frames"] * 48_000 // 24 * 2


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


def test_dev_stub_runs_a_whole_turn_without_an_account():
    router = ProviderRouter({"devstub": DevStub()}, {"editor_assist": ("devstub",)})
    client = TestClient(create_app(router, background=False))
    assert client.get("/api/providers").json()["providers"] == [{"name": "devstub", "available": True, "model": "keywords"}]
    session_id = _open(client, stage_episode())["session_id"]
    turn = _turn(client, session_id, instruction="hold every shot 6 more frames", mode="auto")
    assert [change["state"] for change in turn["changes"]] == ["applied", "applied"]
    state = client.get(f"/api/sessions/{session_id}").json()
    assert _shot(state, "sh_main")["duration_frames"] == 54
    assert _shot(state, "sh_next")["start_frame"] == 54
    assert state["episode"]["total_frames"] == 84
    shrug = _turn(client, session_id, instruction="give them a point", focus_shot_id="sh_next", mode="auto")
    assert shrug["changes"][0]["summary"] == ["Add a point for Figure in shot 2, for the whole shot."]
