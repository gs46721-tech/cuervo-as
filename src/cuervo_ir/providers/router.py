"""Route each pipeline step to a provider, with fallbacks."""

from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
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
    # A model to use instead of the provider's own default.
    model: str | None = None
    # Says whether a reply is usable at all. A contest drops the replies that are not.
    check: Callable[[str], bool] | None = field(default=None, compare=False)


@dataclass(frozen=True)
class Contest:
    """How a reply was chosen when several models answered the same request."""

    entrants: tuple[str, ...]
    winner: str
    judge: str
    reason: str

    def sentence(self) -> str:
        others = [name for name in self.entrants if name != self.winner]
        if not others:
            return f"{self.winner} was the only one with a usable answer."
        why = f": {self.reason}" if self.reason else "."
        return f"{self.winner} was picked over {', '.join(others)} by {self.judge}{why}"


@dataclass(frozen=True)
class ModelResponse:
    provider: str
    model: str
    text: str
    contest: Contest | None = None


@dataclass(frozen=True)
class Entry:
    """One model that may do a step: a provider, and optionally which of its models."""

    provider: str
    model: str | None = None

    def label(self) -> str:
        return f"{self.provider} {self.model}" if self.model else self.provider


@dataclass(frozen=True)
class StepPlan:
    """Who does a step. In order, or all at once with a judge to pick."""

    entries: tuple[Entry, ...]
    compete: bool = False
    judge: Entry | None = None


JUDGE_SYSTEM = (
    "You are judging answers from several models to the same task. Pick the one that best does what the "
    "task asks: correct, complete, and following every stated rule and format. Do not reward length. "
    'Return only JSON {"winner": <number of the best answer>, "reason": "<one short sentence>"}.'
)


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
        # A plan, when a step has one, replaces its route: it can name models and hold a contest.
        self.plans: dict[str, StepPlan] = {}
        # Every contest this router has held, newest last.
        self.contests: list[Contest] = []

    def register(self, provider: Provider, *, steps: dict[str, tuple[str, ...]] | None = None) -> None:
        """Add a provider. `steps` replaces the route for those steps, so a new vendor can take a job."""

        self.providers[provider.name] = provider
        if steps:
            self.routes.update({step: tuple(order) for step, order in steps.items()})

    def entries(self, step: str) -> tuple[Entry, ...]:
        """The models that may do a step, in order."""

        plan = self.plans.get(step)
        if plan is not None and plan.entries:
            return plan.entries
        return tuple(Entry(name) for name in self.routes.get(step, ()))

    def usable(self, entry: Entry) -> bool:
        provider = self.providers.get(entry.provider)
        return provider is not None and provider.available()

    def complete(self, request: ModelRequest, *, only: str | None = None) -> ModelResponse:
        plan = self.plans.get(request.step)
        if only is not None:
            order: tuple[Entry, ...] = (Entry(only),)
        else:
            if plan is None and request.step not in self.routes:
                raise UnknownStep(f"unknown step {request.step}")
            order = self.entries(request.step)
            ready = [entry for entry in order if self.usable(entry)]
            if plan is not None and plan.compete and len(ready) > 1:
                return self._contest(request, ready, plan)
        attempts: list[str] = []
        for entry in order:
            if not self.usable(entry):
                attempts.append(f"{entry.provider}: unavailable")
                continue
            try:
                return self._ask(request, entry)
            except ProviderError as exc:
                attempts.append(f"{entry.provider}: {exc}")
        raise ProviderUnavailable(request.step, attempts)

    def _ask(self, request: ModelRequest, entry: Entry) -> ModelResponse:
        model = entry.model or request.model
        asked = request if model == request.model else ModelRequest(
            step=request.step,
            system=request.system,
            user=request.user,
            response_schema=request.response_schema,
            model=model,
            check=request.check,
        )
        return self.providers[entry.provider].complete(asked)

    def _contest(self, request: ModelRequest, entrants: list[Entry], plan: StepPlan) -> ModelResponse:
        """Every entrant answers at once. Unusable answers drop out, and a judge picks among the rest."""

        def answer(entry: Entry):
            try:
                return self._ask(request, entry)
            except ProviderError as exc:
                return exc

        with ThreadPoolExecutor(max_workers=len(entrants)) as pool:
            results = list(pool.map(answer, entrants))
        attempts = [f"{entry.provider}: {result}" for entry, result in zip(entrants, results) if isinstance(result, Exception)]
        answers = [(entry, result) for entry, result in zip(entrants, results) if isinstance(result, ModelResponse)]
        if not answers:
            raise ProviderUnavailable(request.step, attempts)
        names = tuple(_name(result) for _entry, result in answers)
        if request.check is not None:
            passing = [(entry, result) for entry, result in answers if _passes(request.check, result.text)]
            if len(passing) == 1:
                kept = passing[0][1]
                return self._record(kept, Contest(names, _name(kept), "the format check", "it was the only answer in the right form"))
            answers = passing or answers
        if len(answers) == 1:
            kept = answers[0][1]
            return self._record(kept, Contest(names, _name(kept), "nobody", ""))
        index, judge, reason = self._judge(request, [result for _entry, result in answers], plan)
        kept = answers[index][1]
        return self._record(kept, Contest(names, _name(kept), judge, reason))

    def _record(self, kept: ModelResponse, contest: Contest) -> ModelResponse:
        self.contests.append(contest)
        del self.contests[:-500]
        return ModelResponse(kept.provider, kept.model, kept.text, contest)

    def _judge(self, request: ModelRequest, answers: list[ModelResponse], plan: StepPlan) -> tuple[int, str, str]:
        """Ask the judge for a winner. If no judge can answer, the first entrant stands."""

        candidates = [plan.judge] if plan.judge is not None else []
        # A judge that did not write an answer is fairer, so those go first.
        writers = {answer.provider for answer in answers}
        fallback = [Entry(name) for name in self.routes.get("review", ())] + list(plan.entries)
        candidates += sorted(fallback, key=lambda entry: entry.provider in writers)
        body = json.dumps(
            {
                "task_instructions": request.system,
                "task_input": request.user,
                "answers": [{"number": number + 1, "answer": answer.text} for number, answer in enumerate(answers)],
            }
        )
        for entry in candidates:
            if not self.usable(entry):
                continue
            try:
                verdict = self.providers[entry.provider].complete(
                    ModelRequest(step="review", system=JUDGE_SYSTEM, user=body, model=entry.model)
                )
                text = verdict.text.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1].rsplit("```", 1)[0]
                parsed = json.loads(text)
                winner = int(parsed["winner"]) - 1
                if 0 <= winner < len(answers):
                    return winner, _name(verdict), str(parsed.get("reason", "")).strip()
            except (ProviderError, ValueError, KeyError, TypeError):
                continue
        return 0, "nobody", "no judge could answer, so the first entrant stands"


def _name(response: ModelResponse) -> str:
    return f"{response.provider} {response.model}".strip()


def _passes(check: Callable[[str], bool], text: str) -> bool:
    try:
        return bool(check(text))
    except Exception:
        return False


def build_default_router(roles: bool = True) -> ProviderRouter:
    """Every provider, with the person's saved choice of who does what."""

    from cuervo_ir.providers.claude import ClaudeProvider
    from cuervo_ir.providers.cursor import CursorProvider, OpenAIProvider
    from cuervo_ir.providers.gemini import GeminiProvider

    router = ProviderRouter()
    router.register(ClaudeProvider())
    router.register(GeminiProvider())
    router.register(CursorProvider())
    router.register(OpenAIProvider())
    if roles:
        from cuervo_ir.roles import ModelRoles

        ModelRoles().apply(router)
    return router
