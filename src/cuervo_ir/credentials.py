"""Keys a person saved from the editor's settings.

They live in one file in the user's home, readable only by that user, and are
never in the repo or in an episode. A saved value is put in the process
environment, which is where every provider adapter already looks.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Each service, the environment names its adapter reads, and what the settings page shows.
SERVICES: dict[str, dict] = {
    "claude": {
        "label": "Claude",
        "role": "Writing, direction, and shot edits",
        "key": "ANTHROPIC_API_KEY",
        "model": "CLAUDE_MODEL",
        "base": "ANTHROPIC_BASE_URL",
        "default_base": "https://api.anthropic.com",
        "needs_base": False,
        "key_url": "https://console.anthropic.com/settings/keys",
    },
    "gemini": {
        "label": "Gemini",
        "role": "Review and asset help, and a fallback for the rest",
        "key": "GEMINI_API_KEY",
        "model": "GEMINI_MODEL",
        "base": "GEMINI_BASE_URL",
        "default_base": "https://generativelanguage.googleapis.com",
        "needs_base": False,
        "key_url": "https://aistudio.google.com/apikey",
    },
    "cursor": {
        "label": "Cursor",
        "role": "Any OpenAI-compatible chat endpoint you already use",
        "key": "CURSOR_API_KEY",
        "model": "CURSOR_MODEL",
        "base": "CURSOR_API_BASE",
        "default_base": "",
        "needs_base": True,
        "key_url": "",
    },
    "elevenlabs": {
        "label": "ElevenLabs",
        "role": "Character voices and the timing that drives lip sync",
        "key": "ELEVENLABS_API_KEY",
        "model": "ELEVENLABS_MODEL",
        "base": "ELEVENLABS_BASE_URL",
        "default_base": "https://api.elevenlabs.io",
        "needs_base": False,
        "key_url": "https://elevenlabs.io/app/settings/api-keys",
    },
}

FIELDS = ("key", "model", "base")


# What the shell exported, read once before any saved value is applied.
_SHELL = {service[field]: os.environ.get(service[field], "") for service in SERVICES.values() for field in FIELDS}


class CredentialError(ValueError):
    pass


def default_path() -> Path:
    configured = os.environ.get("CUERVO_KEYS_FILE")
    return Path(configured).expanduser() if configured else Path.home() / ".cuervo" / "keys.json"


class Credentials:
    """Saved keys, kept apart from whatever the shell already exported."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_path()
        self._shell = _SHELL
        self._saved: dict[str, dict[str, str]] = {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._saved = {
                    name: {field: str(value) for field, value in entry.items() if field in FIELDS and value}
                    for name, entry in data.items()
                    if name in SERVICES and isinstance(entry, dict)
                }
        except (OSError, json.JSONDecodeError):
            pass
        self.apply()

    def apply(self) -> None:
        """Put saved values in the environment. A saved value wins over the shell's."""

        for name, service in SERVICES.items():
            saved = self._saved.get(name, {})
            for field in FIELDS:
                value = saved.get(field) or self._shell[service[field]]
                if value:
                    os.environ[service[field]] = value
                else:
                    os.environ.pop(service[field], None)

    def set(self, name: str, *, key: str | None = None, model: str | None = None, base: str | None = None) -> None:
        """Change the fields that are not None. An empty string clears that field."""

        service = _service(name)
        entry = dict(self._saved.get(name, {}))
        for field, value in (("key", key), ("model", model), ("base", base)):
            if value is None:
                continue
            value = value.strip()
            if field == "base" and value and not value.startswith(("https://", "http://")):
                raise CredentialError("the base URL must start with https:// or http://")
            if value:
                entry[field] = value
            else:
                entry.pop(field, None)
        if entry:
            self._saved[name] = entry
        else:
            self._saved.pop(name, None)
        del service
        self._write()
        self.apply()

    def remove(self, name: str) -> None:
        _service(name)
        self._saved.pop(name, None)
        self._write()
        self.apply()

    def view(self) -> list[dict]:
        """What the settings page may see. Never a whole key."""

        rows = []
        for name, service in SERVICES.items():
            saved = self._saved.get(name, {})
            key = saved.get("key") or self._shell[service["key"]]
            base = saved.get("base") or self._shell[service["base"]]
            rows.append(
                {
                    "name": name,
                    "label": service["label"],
                    "role": service["role"],
                    "connected": bool(key) and (bool(base) or not service["needs_base"]),
                    "key_hint": f"…{key[-4:]}" if len(key) >= 8 else ("set" if key else ""),
                    "key_source": "saved" if saved.get("key") else "environment" if key else "",
                    "model": saved.get("model") or self._shell[service["model"]],
                    "base_url": base,
                    "needs_base": service["needs_base"],
                    "key_url": service["key_url"],
                }
            )
        return rows

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        scratch = self.path.with_suffix(".tmp")
        scratch.touch(mode=0o600, exist_ok=True)
        scratch.chmod(0o600)
        scratch.write_text(json.dumps(self._saved, indent=2), encoding="utf-8")
        scratch.replace(self.path)


def check(name: str, fetch=None) -> dict:
    """Ask the service whether the current key works. Makes one small read-only request."""

    service = _service(name)
    key = os.environ.get(service["key"], "")
    base = (os.environ.get(service["base"], "") or service["default_base"]).rstrip("/")
    if not key:
        return {"ok": False, "message": "No key is set."}
    if not base:
        return {"ok": False, "message": "Set the base URL of your OpenAI-compatible endpoint."}
    if name == "claude":
        url, headers = f"{base}/v1/models", {"x-api-key": key, "anthropic-version": "2023-06-01"}
    elif name == "gemini":
        url, headers = f"{base}/v1beta/models", {"x-goog-api-key": key}
    elif name == "elevenlabs":
        url, headers = f"{base}/v1/voices", {"xi-api-key": key}
    else:
        url, headers = f"{base}/models", {"authorization": f"Bearer {key}"}
    try:
        body = (fetch or _get)(url, headers)
    except CredentialError as exc:
        return {"ok": False, "message": str(exc)}
    result: dict = {"ok": True, "message": "Connected."}
    if name == "elevenlabs" and isinstance(body, dict):
        voices = [
            {"voice_id": str(item.get("voice_id", "")), "name": str(item.get("name", ""))}
            for item in body.get("voices") or []
            if isinstance(item, dict) and item.get("voice_id")
        ]
        result["voices"] = voices
        result["message"] = f"Connected. {len(voices)} voices on this account."
    return result


def _get(url: str, headers: dict[str, str]) -> dict:
    try:
        with urlopen(Request(url, headers=headers, method="GET"), timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise CredentialError("The service refused this key.") from exc
        raise CredentialError(f"The service answered HTTP {exc.code}.") from exc
    except URLError as exc:
        raise CredentialError(f"Could not reach the service: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise CredentialError("The service did not answer with JSON.") from exc


def _service(name: str) -> dict:
    try:
        return SERVICES[name]
    except KeyError as exc:
        raise CredentialError(f"unknown service {name}") from exc
