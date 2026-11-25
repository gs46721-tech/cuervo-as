import json
from pathlib import Path

from cuervo_ir.models import DialogueTrack, Episode
from cuervo_ir.providers.router import ModelRequest, ModelResponse, ProviderRouter
from cuervo_voice.dub import VoiceProfile
from cuervo_pipeline.plan import plan_script
from cuervo_pipeline.run import PipelineError, adopt_asset, fingerprint, run_episode
from tests.fixtures import solo_episode


class Router:
    def __init__(self):
        self.steps: list[str] = []

    name = "claude"

    def available(self) -> bool:
        return True

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.steps.append(request.step)
        if request.step == "writing":
            body = {
                "scenes": [
                    {
                        "scene_id": "sc_open",
                        "objective": "Say the line.",
                        "lines": [{"speaker": "Figure", "text": "Hello there"}],
                    }
                ]
            }
        elif request.step == "direction":
            body = {
                "shots": [
                    {
                        "shot_id": "sh_open",
                        "scene_id": "sc_open",
                        "preset": "wide",
                        "duration_frames": 12,
                        "framing": "single figure",
                    }
                ]
            }
        elif request.step == "review":
            body = "hold the pause"
            return ModelResponse(provider="claude", model="stub", text=body)
        elif request.step == "voice_prep":
            body = {"emotion": "calm", "pronunciations": {}}
        else:
            raise AssertionError(request.step)
        return ModelResponse(provider="claude", model="stub", text=json.dumps(body))


def _router() -> tuple[ProviderRouter, Router]:
    provider = Router()
    return ProviderRouter({"claude": provider}), provider


def _brief() -> Episode:
    episode = solo_episode()
    shot = episode.scenes[0].shots[0]
    shot.duration_frames = 2
    shot.action_tracks[0].end_frame = 2
    episode.scenes[0].target_runtime_frames = 4
    other = shot.model_copy(deep=True)
    other.shot_id = "sh_b"
    other.start_frame = 2
    other.action_tracks[0].track_id = "tr_hold_b"
    episode.scenes[0].shots = [shot, other]
    return Episode.model_validate(episode.model_dump())


def test_plan_uses_writing_then_direction():
    router, provider = _router()
    plan = plan_script("Figure: Hello there", ["One figure on an empty stage."], router)
    assert provider.steps == ["writing", "direction"]
    assert plan.scenes[0].lines[0].text == "Hello there"
    assert plan.shots[0].preset == "wide"


def test_cache_approval_and_asset_opt_in(tmp_path: Path):
    episode = _brief()
    router, provider = _router()
    first = run_episode(episode, tmp_path / "one", router=router, approved={"sh_a"})
    assert first.master is not None and first.master.stat().st_size > 0
    by_id = {report.shot_id: report for report in first.reports}
    assert by_id["sh_a"].status == "rendered"
    assert by_id["sh_a"].cost_frames == 2
    assert by_id["sh_a"].review_note == "hold the pause"
    assert by_id["sh_b"].status == "awaiting_approval"
    assert provider.steps == ["review"]

    second = run_episode(
        episode,
        tmp_path / "two",
        router=router,
        approved={"sh_a", "sh_b"},
        cache=first.cache,
    )
    statuses = {report.shot_id: report.status for report in second.reports}
    assert statuses["sh_a"] == "cached"
    assert statuses["sh_b"] == "rendered"
    assert provider.steps == ["review", "review"]

    acted = episode.model_copy(deep=True)
    acted.scenes[0].shots[0].action_tracks[0].keyframes[0].pose = "react"
    acted = Episode.model_validate(acted.model_dump())
    assert fingerprint(acted.scenes[0].shots[0], None, {}) != fingerprint(episode.scenes[0].shots[0], None, {})
    assert fingerprint(acted.scenes[0].shots[1], None, {}) == fingerprint(episode.scenes[0].shots[1], None, {})

    before = fingerprint(episode.scenes[0].shots[0], None, {})
    opted = adopt_asset(episode, "char_a", "1.1.0")
    assert opted.scenes[0].shots[0].asset_refs[0].version == "1.1.0"
    assert fingerprint(opted.scenes[0].shots[0], None, {}) != before
    cached_mp4 = Path(first.cache[by_id["sh_a"].cache_key]["mp4"])
    cached_mp4.unlink()
    rerun = run_episode(episode, tmp_path / "three", router=router, approved={"sh_a"}, cache=first.cache)
    assert {report.shot_id: report.status for report in rerun.reports}["sh_a"] == "rendered"


def test_dialogue_dubs_through_voice_prep_and_render_retries(tmp_path: Path):
    episode = _brief()
    episode.scenes[0].shots[0].dialogue_tracks = [
        DialogueTrack(
            track_id="tr_line",
            speaker_actor_id="act_a",
            line_id="ln_hi",
            text="Hello",
            start_frame=0,
            end_frame=2,
        )
    ]
    episode = Episode.model_validate(episode.model_dump())
    router, provider = _router()
    calls = {"sh_a": 0}

    def flaky(episode, shot, frame, poses):
        if shot.shot_id == "sh_a":
            calls["sh_a"] += 1
            if calls["sh_a"] == 1:
                raise RuntimeError("transient")
        from cuervo_runtime.draw import render_png

        return render_png(episode, shot, frame, poses)

    result = run_episode(
        episode,
        tmp_path / "dub",
        router=router,
        approved={"sh_a"},
        profiles=[
            VoiceProfile(
                character_id="char_a",
                provider="fixture",
                provider_voice_id="voice-a",
                consent="Test consent.",
            )
        ],
        render_frame=flaky,
    )
    assert provider.steps[0] == "voice_prep"
    assert "review" in provider.steps
    report = result.reports[0]
    assert report.status == "rendered"
    assert report.attempts == 2
    assert result.master is not None


def test_one_shot_encode_failure_keeps_the_other(tmp_path: Path, monkeypatch):
    episode = _brief()
    router, _provider = _router()

    def encode(directory: Path, pngs: list[bytes], fps: int):
        if directory.name == "sh_a":
            raise PipelineError("encode failed")
        return original(directory, pngs, fps)

    original = __import__("cuervo_pipeline.run", fromlist=["_encode_shot"])._encode_shot
    monkeypatch.setattr("cuervo_pipeline.run._encode_shot", encode)
    result = run_episode(episode, tmp_path / "encode", router=router, approved={"sh_a", "sh_b"})
    by_id = {report.shot_id: report for report in result.reports}
    assert by_id["sh_a"].status == "failed"
    assert by_id["sh_a"].error == "encode failed"
    assert by_id["sh_b"].status == "rendered"
    assert result.master is not None
