"""Who does what: which models write, direct, review, run the editor, and make pictures.

Each role has its own list of models. A role can run them in order, taking
the first that answers, or run them all at once and let a judge pick the best.
The choice is saved beside the keys, in the user's home.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from cuervo_ir.providers.router import Entry, ProviderRouter, StepPlan

# Role, the router step behind it, and what the settings page says about it.
ROLES: dict[str, dict] = {
    "orchestration": {
        "step": "editor_assist",
        "label": "Orchestration",
        "help": "Runs the editor: reads your notes, looks through the episode, and makes the changes.",
    },
    "screenwriting": {
        "step": "writing",
        "label": "Screenwriting",
        "help": "Outlines an episode and writes its scenes from a premise.",
    },
    "direction": {
        "step": "direction",
        "label": "Direction",
        "help": "Storyboards each scene into shots and chooses the acting.",
    },
    "review": {
        "step": "review",
        "label": "Review",
        "help": "Gives notes on finished scenes. Also judges contests unless a role names its own judge.",
    },
    "voice": {
        "step": "voice_prep",
        "label": "Voice direction",
        "help": "Chooses the emotion and pronunciation for a line before it is recorded.",
    },
    "image": {
        "step": "image",
        "label": "Image generation",
        "help": "Paints set backgrounds from their designs. In a contest, every model paints one and you pick.",
    },
}


class RoleEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=40)
    model: str = Field(default="", max_length=120)


class RoleChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[RoleEntry] = Field(default_factory=list, max_length=6)
    compete: bool = False
    judge: RoleEntry | None = None


def default_path() -> Path:
    configured = os.environ.get("CUERVO_MODELS_FILE")
    return Path(configured).expanduser() if configured else Path.home() / ".cuervo" / "models.json"


class ModelRoles:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_path()
        self.choices: dict[str, RoleChoice] = {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for role, choice in data.items():
                if role in ROLES:
                    self.choices[role] = RoleChoice.model_validate(choice)
        except (OSError, ValueError):
            pass

    def set(self, role: str, choice: RoleChoice) -> None:
        if role not in ROLES:
            raise KeyError(role)
        if choice.entries:
            self.choices[role] = choice
        else:
            # No entries means "use the defaults again".
            self.choices.pop(role, None)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({name: item.model_dump(mode="json") for name, item in self.choices.items()}, indent=2),
            encoding="utf-8",
        )

    def plan(self, role: str) -> StepPlan | None:
        choice = self.choices.get(role)
        if choice is None or not choice.entries:
            return None
        return StepPlan(
            entries=tuple(Entry(item.provider, item.model or None) for item in choice.entries),
            compete=choice.compete,
            judge=Entry(choice.judge.provider, choice.judge.model or None) if choice.judge else None,
        )

    def apply(self, router: ProviderRouter) -> None:
        """Give the router a plan for every role the person has set."""

        for role, spec in ROLES.items():
            plan = self.plan(role)
            if plan is not None:
                router.plans[spec["step"]] = plan
            else:
                router.plans.pop(spec["step"], None)

    def view(self, router: ProviderRouter) -> list[dict]:
        """What the settings page shows: the saved choice, or the defaults when there is none."""

        rows = []
        for role, spec in ROLES.items():
            choice = self.choices.get(role)
            defaults = [{"provider": name, "model": ""} for name in router.routes.get(spec["step"], ())]
            rows.append(
                {
                    "role": role,
                    "label": spec["label"],
                    "help": spec["help"],
                    "custom": choice is not None,
                    "entries": [item.model_dump() for item in choice.entries] if choice else defaults,
                    "compete": choice.compete if choice else False,
                    "judge": choice.judge.model_dump() if choice and choice.judge else None,
                }
            )
        return rows
