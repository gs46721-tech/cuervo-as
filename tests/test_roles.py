"""A model per job, and contests between models."""

import base64
import json
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from cuervo_ir.providers.router import Entry, ModelRequest, ModelResponse, ProviderError, ProviderRouter, StepPlan
from cuervo_ir.roles import ModelRoles, RoleChoice, RoleEntry
from cuervo_editor.api import create_app
from cuervo_pipeline.produce import produce
from cuervo_world import World
from cuervo_world.imagegen import GeminiImage, OpenAIImage, set_prompt
from tests.fixtures import stage_episode
from tests.test_production import SCRIPT, _designed_kit


class Model:
    """Answers with fixed text, and remembers which model name it was asked to be."""

    def __init__(self, name: str, text: str = "", judge: dict | None = None, fail: bool = False):
        self.name = name
        self.model = f"{name}-default"
        self.text = text
        self.judge = judge
        self.fail = fail
        self.asked: list[tuple[str, str | None]] = []

    def available(self) -> bool:
        return True

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.asked.append((request.step, request.model))
        if self.fail:
            raise ProviderError("down")
        if request.system.startswith("You are judging"):
            return ModelResponse(self.name, request.model or self.model, json.dumps(self.judge))
        return ModelResponse(self.name, request.model or self.model, self.text)


def test_each_job_can_use_its_own_model():
    claude, gemini = Model("claude", "a scene"), Model("gemini", "a board")
    router = ProviderRouter({"claude": claude, "gemini": gemini})
    router.plans["writing"] = StepPlan((Entry("claude", "big-writer"),))
    router.plans["direction"] = StepPlan((Entry("gemini", "fast-director"), Entry("claude")))
    assert router.complete(ModelRequest("writing", "s", "u")).model == "big-writer"
    assert router.complete(ModelRequest("direction", "s", "u")).model == "fast-director"
    # A step with no plan still follows its default route and the provider's own model.
    assert router.complete(ModelRequest("review", "s", "u")).model == "gemini-default"
    # Taking turns: the second model steps in only when the first fails.
    gemini.fail = True
    assert router.complete(ModelRequest("direction", "s", "u")).provider == "claude"


def test_a_contest_drops_bad_answers_and_a_judge_picks_the_best():
    claude = Model("claude", "good answer")
    gemini = Model("gemini", "better answer")
    openai = Model("openai", "not json at all")
    judge = Model("cursor", judge={"winner": 2, "reason": "It keeps the joke."})
    router = ProviderRouter({"claude": claude, "gemini": gemini, "openai": openai, "cursor": judge})
    router.plans["writing"] = StepPlan(
        (Entry("claude"), Entry("gemini"), Entry("openai", "o-test")), compete=True, judge=Entry("cursor", "judge-model")
    )
    response = router.complete(ModelRequest("writing", "write", "premise", check=lambda text: "answer" in text))
    assert response.text == "better answer"
    assert response.contest.entrants == ("claude claude-default", "gemini gemini-default", "openai o-test")
    assert response.contest.sentence() == (
        "gemini gemini-default was picked over claude claude-default, openai o-test by cursor judge-model: It keeps the joke."
    )
    # The judge was asked once, with its own model, and only saw the answers that passed the check.
    assert judge.asked == [("review", "judge-model")]

    # One usable answer wins without a judge.
    judge.asked.clear()
    lone = router.complete(ModelRequest("writing", "write", "premise", check=lambda text: text.startswith("better")))
    assert lone.provider == "gemini" and judge.asked == []
    # A judge that cannot answer leaves the first entrant standing.
    judge.judge = {"winner": 99}
    router.routes["review"] = ()
    kept = router.complete(ModelRequest("writing", "write", "premise"))
    assert kept.provider == "claude" and "first entrant" in kept.contest.reason
    # A model that is down does not sink the contest.
    claude.fail = True
    assert router.complete(ModelRequest("writing", "write", "premise", check=lambda text: "better" in text)).provider == "gemini"


def test_roles_are_saved_and_change_the_running_editor(tmp_path):
    claude = Model("claude", 'camera sh_main close_up\ndone "Closer."')
    gemini = Model("gemini", 'hold sh_main 12\ndone "Held."', judge={"winner": 1, "reason": "The note asked for a closer shot."})
    router = ProviderRouter({"claude": claude, "gemini": gemini})
    roles = ModelRoles(tmp_path / "models.json")
    client = TestClient(create_app(router, background=False, roles=roles))

    listed = {row["role"]: row for row in client.get("/api/settings/roles").json()["roles"]}
    assert listed["orchestration"]["custom"] is False
    assert [item["name"] for item in listed["image"]["choices"]] == ["gemini", "openai"]
    assert client.put("/api/settings/roles/orchestration", json={"entries": [{"provider": "nobody", "model": ""}]}).status_code == 422

    saved = client.put(
        "/api/settings/roles/orchestration",
        json={
            "entries": [{"provider": "claude", "model": "claude-orchestrator"}, {"provider": "gemini", "model": ""}],
            "compete": True,
            "judge": {"provider": "gemini", "model": "gemini-judge"},
        },
    )
    assert saved.status_code == 200
    assert ModelRoles(tmp_path / "models.json").choices["orchestration"].compete is True

    session_id = client.post("/api/sessions", json={"episode": stage_episode().model_dump(mode="json")}).json()["session_id"]
    thread_id = client.post(f"/api/sessions/{session_id}/threads").json()["thread_id"]
    state = client.post(f"/api/sessions/{session_id}/threads/{thread_id}/turns", json={"instruction": "closer"}).json()
    turn = state["threads"][0]["turns"][0]
    assert turn["changes"][0]["summary"] == ["Reframe shot 1 from a wide shot to a close-up."]
    assert turn["contests"] == [
        "claude claude-orchestrator was picked over gemini gemini-default by gemini gemini-judge: The note asked for a closer shot."
    ]
    assert ("editor_assist", "claude-orchestrator") in claude.asked

    # Back to default removes the plan.
    cleared = client.put("/api/settings/roles/orchestration", json={"entries": []}).json()
    assert next(row for row in cleared["roles"] if row["role"] == "orchestration")["custom"] is False
    assert "editor_assist" not in router.plans


def _png(color: tuple[int, int, int]) -> str:
    buffer = BytesIO()
    Image.new("RGB", (1536, 1024), color).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def test_image_models_each_paint_a_set_and_a_person_picks(tmp_path):
    seen = {}

    def gemini(url, headers, body):
        seen["gemini"] = (url, body["contents"][0]["parts"][0]["text"])
        return {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": _png((200, 30, 30))}}]}}]}

    def openai(url, headers, body):
        seen["openai"] = (url, body["model"])
        return {"data": [{"b64_json": _png((30, 30, 200))}]}

    engines = {"gemini": GeminiImage(api_key="k", transport=gemini), "openai": OpenAIImage(api_key="k", transport=openai)}
    kit = _designed_kit()
    world = World(tmp_path / "world")
    world.build(kit, painters=[("gemini", ""), ("openai", "image-test")], engines=engines)
    assert seen["gemini"][0].endswith("/v1beta/models/gemini-2.5-flash-image:generateContent")
    assert seen["openai"] == ("https://api.openai.com/v1/images/generations", "image-test")
    # Both models got the same prompt, built from the design.
    assert seen["gemini"][1] == set_prompt("Yard", kit.sets[1].design or type(kit.sets[0].design)(), kit.bible)
    assert "a sofa in the center" in set_prompt("Workshop", kit.sets[0].design)

    entry = world.entry("bg_workshop")
    assert [item["by"] for item in entry["candidates"]] == ["house style", "gemini gemini-2.5-flash-image", "openai image-test"]
    assert entry["chosen"] == 1 and world.plate("bg_workshop", "1.0.0").getpixel((10, 10)) == (200, 30, 30)
    before = world.stamp(["bg_workshop"])
    world.choose("bg_workshop", 2)
    assert world.plate("bg_workshop", "1.0.0").getpixel((10, 10)) == (30, 30, 200)
    assert world.stamp(["bg_workshop"]) != before  # shots on this set will be drawn again
    # Characters are never painted: they stay parts.
    assert "candidates" not in world.entry("char_ada")
    # A second build keeps the pick.
    assert World(tmp_path / "world").build(kit, painters=[("gemini", "")], engines=engines) == []
    assert World(tmp_path / "world").entry("bg_workshop")["chosen"] == 2


def test_a_painter_that_is_not_connected_leaves_the_house_style(tmp_path):
    logs: list[str] = []
    result = produce(SCRIPT, _designed_kit(), tmp_path, router=None, through="script", painters=[("openai", "")], log=logs.append)
    assert result.world.entry("bg_workshop")["source"] == "house style"
    assert any("openai is not connected" in line for line in logs)
