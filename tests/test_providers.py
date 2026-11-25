from cuervo_ir.providers.claude import ClaudeProvider
from cuervo_ir.providers.cursor import CursorProvider
from cuervo_ir.providers.gemini import GeminiProvider
from cuervo_ir.providers.router import (
    DEFAULT_ROUTES,
    ModelRequest,
    ModelResponse,
    ProviderError,
    ProviderRouter,
    ProviderUnavailable,
    UnknownStep,
)


class Stub:
    def __init__(self, name: str, *, available: bool = True, fail: bool = False):
        self.name = name
        self._available = available
        self.fail = fail
        self.calls = 0

    def available(self) -> bool:
        return self._available

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        if self.fail:
            raise ProviderError("boom")
        return ModelResponse(provider=self.name, model="stub", text=request.step)


def test_routes_prefer_different_providers_per_step():
    assert DEFAULT_ROUTES["writing"][0] == "claude"
    assert DEFAULT_ROUTES["asset_assist"][0] == "gemini"
    assert DEFAULT_ROUTES["editor_assist"][0] == "cursor"
    assert DEFAULT_ROUTES["review"][0] == "gemini"
    assert DEFAULT_ROUTES["ir_patch"][0] == "claude"


def test_fallback_and_register():
    claude = Stub("claude", fail=True)
    gemini = Stub("gemini")
    router = ProviderRouter({"claude": claude, "gemini": gemini, "cursor": Stub("cursor", available=False)})
    response = router.complete(ModelRequest(step="writing", system="s", user="u"))
    assert response.provider == "gemini"
    assert claude.calls == 1

    extra = Stub("extra")
    router.register(extra, steps={"writing": ("extra",)})
    assert router.complete(ModelRequest(step="writing", system="s", user="u")).provider == "extra"


def test_unknown_step_and_total_miss():
    router = ProviderRouter({"claude": Stub("claude", available=False)})
    try:
        router.complete(ModelRequest(step="nope", system="s", user="u"))
    except UnknownStep:
        pass
    else:
        raise AssertionError("unknown step ran")
    try:
        router.complete(ModelRequest(step="writing", system="s", user="u"))
    except ProviderUnavailable:
        pass
    else:
        raise AssertionError("empty route succeeded")


def test_adapters_parse_vendor_payloads_without_network():
    seen = {}

    def claude_transport(url, headers, body):
        seen["claude"] = (url, headers["x-api-key"], body["model"])
        return {"content": [{"text": "ok"}]}

    def gemini_transport(url, headers, body):
        seen["gemini"] = url
        return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

    def cursor_transport(url, headers, body):
        seen["cursor"] = (url, headers["authorization"])
        return {"choices": [{"message": {"content": "ok"}}]}

    request = ModelRequest(step="review", system="s", user="u")
    assert ClaudeProvider(api_key="k", transport=claude_transport).complete(request).provider == "claude"
    assert GeminiProvider(api_key="k", transport=gemini_transport).complete(request).provider == "gemini"
    assert (
        CursorProvider(api_key="k", base_url="https://cursor.example", transport=cursor_transport).complete(request).provider
        == "cursor"
    )
    assert seen["claude"][0].endswith("/v1/messages")
    assert "models/gemini-2.5-pro:generateContent" in seen["gemini"]
    assert seen["cursor"][0] == "https://cursor.example/chat/completions"
    assert CursorProvider(api_key="k").available() is False
    assert ClaudeProvider(api_key="").available() is False
