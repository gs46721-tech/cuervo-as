import json

from cuervo_ir.models import DialogueTrack, Episode, Lock
from cuervo_ir.providers.router import ModelRequest, ModelResponse, ProviderRouter
from cuervo_runtime.draw import render_png
from cuervo_voice.dub import DubError, VoiceProfile, dub_episode
from cuervo_voice.synth import ElevenLabsSynth, fit_pcm
from tests.fixtures import solo_episode


class Prep:
    name = "claude"

    def available(self) -> bool:
        return True

    def complete(self, request: ModelRequest) -> ModelResponse:
        assert request.step == "voice_prep"
        return ModelResponse(
            provider="claude",
            model="stub",
            text=json.dumps({"emotion": "dry", "pronunciations": {"papa": "AA"}}),
        )


def _line_episode():
    episode = solo_episode()
    episode.scenes[0].shots[0].dialogue_tracks.append(
        DialogueTrack(
            track_id="tr_line",
            speaker_actor_id="act_a",
            line_id="ln_papa",
            text="papa",
            start_frame=0,
            end_frame=24,
        )
    )
    return episode


def _profile(**overrides) -> VoiceProfile:
    data = {
        "character_id": "char_a",
        "provider": "fixture",
        "provider_voice_id": "voice-a",
        "consent": "Recorded with permission.",
    }
    data.update(overrides)
    return VoiceProfile.model_validate(data)


def test_fixture_dub_writes_visemes_and_a_wav():
    episode = _line_episode()
    dubbed, takes = dub_episode(episode, [_profile()])
    assert episode.scenes[0].shots[0].dialogue_tracks[0].visemes == []
    track = dubbed.scenes[0].shots[0].dialogue_tracks[0]
    assert track.voice_take_id == takes[0].take_id
    assert takes[0].wav.startswith(b"RIFF")
    assert takes[0].prep == "fallback"
    assert takes[0].emotion == "neutral"
    assert takes[0].provider_voice_id == "voice-a"
    names = [key.viseme for key in track.visemes]
    assert "MBP" in names and "AA" in names
    assert any(key.weight == 0.45 for key in track.visemes)
    assert dubbed.scenes[0].shots[0].provenance.source == "voice"
    quiet = render_png(episode, episode.scenes[0].shots[0], 0)
    open_mouth = render_png(dubbed, dubbed.scenes[0].shots[0], 6)
    assert quiet != open_mouth


def test_router_preps_emotion_without_naming_a_series():
    router = ProviderRouter({"claude": Prep(), "gemini": Prep(), "cursor": Prep()})
    _dubbed, takes = dub_episode(_line_episode(), [_profile()], router=router)
    assert takes[0].emotion == "dry"
    assert takes[0].prep == "router"


def test_missing_consent_and_missing_profile_fail():
    try:
        VoiceProfile.model_validate(
            {"character_id": "char_a", "provider": "fixture", "provider_voice_id": "voice-a", "consent": ""}
        )
    except Exception:
        pass
    else:
        raise AssertionError("empty consent was accepted")
    try:
        dub_episode(_line_episode(), [])
    except DubError as exc:
        assert "char_a" in str(exc)
    else:
        raise AssertionError("missing profile was dubbed")


def test_locked_dialogue_is_not_replaced():
    episode = _line_episode()
    episode.scenes[0].shots[0].locks.append(
        Lock(lock_id="lock_line", target_track_id="tr_line", properties=["dialogue"])
    )
    episode = Episode.model_validate(episode.model_dump())
    try:
        dub_episode(episode, [_profile()])
    except DubError as exc:
        assert "locked" in str(exc)
    else:
        raise AssertionError("locked dialogue was dubbed")


def test_pcm_is_forced_to_the_line_length():
    assert fit_pcm(b"\x01\x02", 2) == b"\x01\x02\x00\x00"
    assert fit_pcm(b"\x01\x02\x03\x04\x05\x06", 2) == b"\x01\x02\x03\x04"


def test_elevenlabs_adapter_uses_the_profile_voice_id():
    seen = {}

    def transport(text, voice_id, sample_rate, sample_count):
        seen["voice_id"] = voice_id
        return b"RIFF" + b"\x00" * 40

    synth = ElevenLabsSynth(api_key="", transport=transport)
    dubbed, takes = dub_episode(
        _line_episode(),
        [_profile(provider="elevenlabs", provider_voice_id="vendor-voice-9")],
        synths={"elevenlabs": synth},
    )
    assert seen["voice_id"] == "vendor-voice-9"
    assert takes[0].provider == "elevenlabs"
    assert dubbed.scenes[0].shots[0].dialogue_tracks[0].alignment
