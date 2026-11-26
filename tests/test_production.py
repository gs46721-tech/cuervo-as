"""Script to master, on a generic kit. Not a series."""

import base64
import json
import struct
import subprocess

import pytest
from fastapi.testclient import TestClient

from cuervo_ir.models import Episode
from cuervo_ir.providers.router import ModelRequest, ModelResponse, ProviderRouter
from cuervo_editor.api import create_app
from cuervo_pipeline.board import board_script
from cuervo_pipeline.polish import check_episode
from cuervo_pipeline.produce import ProduceError, produce
from cuervo_pipeline.run import run_episode
from cuervo_pipeline.screenplay import ScriptError, parse_screenplay, write_script
from cuervo_pipeline.series import SeriesKit
from cuervo_voice.align import align_timed
from cuervo_voice.synth import ElevenLabsSynth, VoiceError
from cuervo_voice.takes import load_take, record_take

SCRIPT = """
INT. WORKSHOP - DAY

Ada sorts bolts. Bo watches.

ADA
Hand me the small one.

BO
(squinting)
They are all small!

Bo: Is this it?

FADE OUT.

EXT. YARD - NIGHT

ADA
That was the wrong one.
"""


def _kit(provider: str = "fixture") -> SeriesKit:
    def character(name: str) -> dict:
        return {
            "asset_id": f"char_{name.lower()}",
            "display_name": name,
            "rig_id": f"rig_{name.lower()}",
            "extension_poses": ["squint"] if name == "Bo" else [],
            "voice": {"provider": provider, "provider_voice_id": f"voice-{name.lower()}", "consent": "Test data."},
        }

    return SeriesKit.model_validate(
        {
            "title": "Bolts",
            "characters": [character("Ada"), character("Bo")],
            "sets": [
                {"asset_id": "bg_workshop", "display_name": "Workshop", "location_id": "loc_workshop"},
                {"asset_id": "bg_yard", "display_name": "Yard", "location_id": "loc_yard"},
            ],
            "poses": {"squint": {"eye_l": -0.5, "eye_r": -0.5}},
        }
    )


class Director:
    """Answers the direction, review, and writing routes the way a model would."""

    name = "claude"
    model = "stub"

    def __init__(self, board: dict | None = None):
        self.board = board
        self.steps: list[str] = []

    def available(self) -> bool:
        return True

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.steps.append(request.step)
        payload = json.loads(request.user)
        if request.step == "direction" and "beats" in payload:
            lines = [beat["line"] for beat in payload["beats"] if beat["kind"] == "line"]
            body = self.board or {
                "objective": "Find the bolt.",
                "emotional_trajectory": "patience running out",
                "shots": [
                    {"preset": "wide", "framing": "the bench", "focus": None, "lines": [], "action": "Ada sorts."},
                    *(
                        {"preset": "close_up", "framing": "on the speaker", "focus": None, "lines": [index]}
                        for index in lines
                    ),
                ],
            }
        elif request.step == "direction":
            body = {"lines": {line["line_id"]: {"expression": "squint", "gesture": "point"} for line in payload["lines"]}}
        elif request.step == "review":
            body = {"notes": [{"shot_id": payload["shots"][0]["shot_id"], "text": "Open tighter."}]}
        elif request.step == "writing" and "premise" in payload:
            body = {"scenes": [{"set": "Workshop", "summary": "They look for a bolt.", "seconds": 60}]}
        else:
            return ModelResponse(provider="claude", model="stub", text="INT. WORKSHOP - DAY\n\nADA\nWhere is it?\n\nBO\nHere.")
        return ModelResponse(provider="claude", model="stub", text=json.dumps(body))


def test_screenplay_reads_cues_parentheticals_inline_cues_and_sets():
    script = parse_screenplay(SCRIPT, _kit())
    assert [scene.set_id for scene in script.scenes] == ["bg_workshop", "bg_yard"]
    first = script.scenes[0].beats
    assert [beat.kind for beat in first] == ["action", "line", "line", "line"]
    assert first[2].character_id == "char_bo"
    assert first[2].direction == "squinting"
    assert first[3].text == "Is this it?"
    assert script.warnings == []


def test_an_unknown_speaker_stops_the_script_instead_of_dropping_the_line():
    with pytest.raises(ScriptError, match="ZED"):
        parse_screenplay("INT. WORKSHOP\n\nZED\nI am not in the kit.\n", _kit())


def test_a_long_speech_is_split_into_takes_at_sentence_ends():
    speech = " ".join(["This sentence is about forty characters long."] * 9)
    script = parse_screenplay(f"INT. WORKSHOP\n\nADA\n{speech}\n", _kit())
    lines = script.lines()
    assert len(lines) > 1
    assert all(len(line.text) <= 220 for line in lines)
    assert " ".join(line.text for line in lines) == speech


def test_a_board_that_drops_a_line_falls_back_to_the_grammar():
    bad = {"objective": "x", "emotional_trajectory": "y", "shots": [{"preset": "wide", "framing": "all", "lines": [0]}]}
    kit = _kit()
    script = parse_screenplay(SCRIPT, kit)
    board = board_script(script, kit, ProviderRouter({"claude": Director(bad)}))
    workshop = board.scenes[0]
    assert workshop.source == "grammar"
    assert [line.text for shot in workshop.shots for line in shot.lines] == [
        "Hand me the small one.",
        "They are all small!",
        "Is this it?",
    ]
    # One line in the yard: the same reply covers it, so the director keeps that scene.
    assert board.scenes[1].source == "director"


def test_elevenlabs_timestamps_drive_the_mouth():
    calls = []

    def transport(url: str, body: dict) -> dict:
        calls.append((url, body))
        pcm = struct.pack("<h", 1200) * 24_000  # one second at 24 kHz
        return {
            "audio_base64": base64.b64encode(pcm).decode(),
            "alignment": {
                "characters": list("Ma  pa"),
                "character_start_times_seconds": [0.0, 0.1, 0.3, 0.5, 0.6, 0.7],
                "character_end_times_seconds": [0.1, 0.3, 0.5, 0.6, 0.7, 1.0],
            },
        }

    engine = ElevenLabsSynth(api_key="test", speech_transport=transport)
    speech = engine.speak("Ma  pa", "voice-x", model_id="eleven_v3", settings={"stability": 0.4})
    url, body = calls[0]
    assert url.endswith("/v1/text-to-speech/voice-x/with-timestamps?output_format=pcm_24000")
    assert body == {"text": "Ma  pa", "model_id": "eleven_v3", "voice_settings": {"stability": 0.4}}
    assert speech.seconds == 1.0
    spans = align_timed([(c.char, c.start, c.end) for c in speech.chars], 48_000, 48_000)
    assert [(span.phoneme, span.start_sample) for span in spans] == [
        ("MBP", 0),
        ("AA", 4_800),
        ("rest", 14_400),  # the measured pause closes the mouth
        ("MBP", 28_800),
        ("AA", 33_600),
    ]


def test_elevenlabs_without_a_key_says_what_to_set(tmp_path):
    kit = _kit("elevenlabs")
    with pytest.raises(VoiceError, match="ELEVENLABS_API_KEY"):
        record_take("Hello.", kit.characters[0].profile(), {}, tmp_path)


def test_a_take_is_recorded_once_and_resampled_to_the_pipeline_clock(tmp_path):
    count = []

    def transport(url: str, body: dict) -> dict:
        count.append(body["text"])
        return {"audio_base64": base64.b64encode(struct.pack("<h", 900) * 12_000).decode(), "alignment": None}

    engines = {"elevenlabs": ElevenLabsSynth(api_key="test", speech_transport=transport)}
    profile = _kit("elevenlabs").characters[0].profile()
    take, fresh = record_take("Hello there.", profile, engines, tmp_path)
    again, fresh_again = record_take("Hello there.", profile, engines, tmp_path)
    assert (fresh, fresh_again) == (True, False)
    assert count == ["Hello there."]
    assert again.take_id == take.take_id
    assert take.sample_rate == 48_000
    assert abs(take.seconds - 0.5) < 0.01
    assert take.timing == "estimated"  # no alignment came back, so the letters were spread
    assert load_take(tmp_path, take.take_id) is not None


def _streams(path) -> dict[str, float]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return {kind: float(duration) for kind, duration in (row.split(",") for row in out.split())}


def test_script_to_master_with_sound_and_stage_files(tmp_path):
    director = Director()
    logs: list[str] = []
    result = produce(SCRIPT, _kit(), tmp_path, router=ProviderRouter({"claude": director}), log=logs.append)
    for name in ("script.json", "storyboard.json", "episode.json", "poses.json", "notes.json", "episode.mp4"):
        assert (tmp_path / name).is_file(), name
    assert (tmp_path / "boards" / f"{result.board.scenes[0].scene_id}.png").is_file()

    episode = result.episode
    shots = [shot for scene in episode.scenes for shot in scene.shots]
    spoken = [line for shot in shots for line in shot.dialogue_tracks]
    assert len(spoken) == 4
    for line in spoken:
        take = load_take(tmp_path / "takes", line.voice_take_id)
        # The line is exactly as long as its take, rounded up to a frame.
        frames = line.end_frame - line.start_frame
        assert 0 <= frames - take.seconds * episode.fps < 1
        assert line.visemes and line.visemes[0].frame == line.start_frame
    # The director's acting is on the timeline, and a tight shot is on its speaker.
    assert any(track.keyframes[0].pose == "squint" for shot in shots for track in shot.action_tracks)
    close = next(shot for shot in shots if shot.dialogue_tracks and shot.camera.preset == "close_up")
    assert close.camera.transform.scale > 2

    streams = _streams(tmp_path / "episode.mp4")
    total = sum(shot.duration_frames for shot in shots) / episode.fps
    assert abs(streams["video"] - total) < 0.05
    assert abs(streams["audio"] - total) < 0.05
    assert "review" in {note.source for note in result.notes}
    assert result.summary()["render"] == {"rendered": len(shots)}


def test_a_second_run_keeps_edits_and_only_redraws_the_changed_shot(tmp_path):
    kit = _kit()
    first = produce(SCRIPT, kit, tmp_path, router=None, log=lambda _line: None)
    assert first.new_takes == 4
    data = json.loads((tmp_path / "episode.json").read_text())
    data["scenes"][0]["shots"][1]["camera"]["preset"] = "insert"
    (tmp_path / "episode.json").write_text(json.dumps(data))

    second = produce(SCRIPT, kit, tmp_path, router=None, log=lambda _line: None)
    assert second.episode.scenes[0].shots[1].camera.preset == "insert"
    statuses = [report.status for report in second.render.reports]
    assert statuses.count("rendered") == 1
    assert statuses.count("cached") == len(statuses) - 1

    with pytest.raises(ProduceError, match="different script"):
        produce(SCRIPT + "\nADA\nOne more.\n", kit, tmp_path, router=None, log=lambda _line: None)
    rebuilt = produce(SCRIPT + "\nADA\nOne more.\n", kit, tmp_path, router=None, rebuild=True, through="animation", log=lambda _line: None)
    assert rebuilt.new_takes == 1 and rebuilt.reused_takes == 4


def test_checks_flag_a_line_that_no_longer_matches_its_take(tmp_path):
    result = produce(SCRIPT, _kit(), tmp_path, router=None, through="animation", log=lambda _line: None)
    assert check_episode(result.episode, tmp_path / "takes") == []
    data = result.episode.model_dump(mode="json")
    line = next(shot for shot in data["scenes"][0]["shots"] if shot["dialogue_tracks"])["dialogue_tracks"][0]
    line["text"] = "Hand me the big one."
    notes = check_episode(Episode.model_validate(data), tmp_path / "takes")
    assert [note.severity for note in notes] == ["fix"]
    assert "Record it again" in notes[0].text


def test_unapproved_shots_stay_out_of_the_master(tmp_path):
    result = produce(SCRIPT, _kit(), tmp_path, router=None, approved={"sh_0002"}, log=lambda _line: None)
    statuses = {report.shot_id: report.status for report in result.render.reports}
    assert statuses["sh_0002"] == "rendered"
    assert statuses["sh_0001"] == "awaiting_approval"
    shot = next(s for scene in result.episode.scenes for s in scene.shots if s.shot_id == "sh_0002")
    assert abs(_streams(tmp_path / "episode.mp4")["video"] - shot.duration_frames / 24) < 0.05


def test_write_drafts_a_script_the_parser_accepts():
    kit = _kit()
    text = write_script("They lose a bolt.", kit, 1, ProviderRouter({"claude": Director()}))
    assert len(parse_screenplay(text, kit).lines()) == 2


def test_editor_serves_the_voice_track_for_a_shot(tmp_path):
    result = produce(SCRIPT, _kit(), tmp_path, router=None, through="animation", log=lambda _line: None)
    app = create_app(ProviderRouter({}), background=False)
    client = TestClient(app)
    opened = client.post("/api/sessions", json={"episode": result.episode.model_dump(mode="json")}).json()
    shot = next(item for item in opened["episode"]["shots"] if item["has_voice"])
    url = f"/api/sessions/{opened['session_id']}/audio/{shot['shot_id']}.wav"
    assert client.get(url).status_code == 404
    app.state.store.get(opened["session_id"]).takes_dir = str(tmp_path / "takes")
    wav = client.get(url)
    assert wav.status_code == 200
    assert len(wav.content) - 44 == shot["duration_frames"] * 48_000 // 24 * 2
    assert wav.content[44:].strip(b"\x00")
    # The second scene starts where the first one ends on the episode clock.
    yard = [item for item in opened["episode"]["shots"] if item["scene_id"] == opened["episode"]["scenes"][1]["scene_id"]]
    assert yard[0]["start_frame"] == opened["episode"]["scenes"][0]["duration_frames"]
