"""Route each pipeline step to a provider, with fallbacks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

# First name is the preferred provider for that step. The rest are fallbacks.
DEFAULT_ROUTES: dict[str, tuple[str, ...]] = {
    "writing": ("claude", "gemini", "cursor"),
    "direction": ("claude", "gemini", "cursor"),
    "ir_patch": ("claude", "gemini", "cursor"),
    "asset_assist": ("gemini", "claude", "cursor"),
    "editor_assist": ("cursor", "claude", "gemini"),
    "review": ("gemini", "claude", "cursor"),
    "voice_prep": ("claude", "gemini", "cursor"),
}

STEPS: tuple[str, ...] = tuple(DEFAULT_ROUTES)


class ProviderError(RuntimeError):
    pass


class UnknownStep(ProviderError):
    pass


class ProviderUnavailable(ProviderError):
    def __init__(self, step: str, attempts: list[str]):
        self.step = step
        self.attempts = attempts
        super().__init__(f"no provider completed step {step}: {'; '.join(attempts)}")


@dataclass(frozen=True)
class ModelRequest:
    step: str
    system: str
    user: str
    response_schema: dict | None = None


@dataclass(frozen=True)
class ModelResponse:
    provider: str
    model: str
    text: str


class Provider(Protocol):
    name: str

    def available(self) -> bool: ...

    def complete(self, request: ModelRequest) -> ModelResponse: ...


class ProviderRouter:
    def __init__(
        self,
        providers: dict[str, Provider] | None = None,
        routes: dict[str, tuple[str, ...]] | None = None,
    ):
        self.providers: dict[str, Provider] = dict(providers or {})
        self.routes = {step: tuple(order) for step, order in (routes or DEFAULT_ROUTES).items()}

    def register(self, provider: Provider, *, steps: dict[str, tuple[str, ...]] | None = None) -> None:
        """Add a provider. `steps` replaces the route for those steps, so a new vendor can take a job."""

        self.providers[provider.name] = provider
        if steps:
            self.routes.update({step: tuple(order) for step, order in steps.items()})

    def complete(self, request: ModelRequest, *, only: str | None = None) -> ModelResponse:
        if only is not None:
            order = (only,)
        else:
            order = self.routes.get(request.step)
            if order is None:
                raise UnknownStep(f"unknown step {request.step}")
        attempts: list[str] = []
        for name in order:
            provider = self.providers.get(name)
            if provider is None or not provider.available():
                attempts.append(f"{name}: unavailable")
                continue
            try:
                return provider.complete(request)
            except ProviderError as exc:
                attempts.append(f"{name}: {exc}")
        raise ProviderUnavailable(request.step, attempts)


def build_default_router() -> ProviderRouter:
    from cuervo_ir.providers.claude import ClaudeProvider
    from cuervo_ir.providers.cursor import CursorProvider
    from cuervo_ir.providers.gemini import GeminiProvider

    router = ProviderRouter()
    router.register(ClaudeProvider())
    router.register(GeminiProvider())
    router.register(CursorProvider())
    return router
