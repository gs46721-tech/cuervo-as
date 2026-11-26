"""Anthropic Messages API adapter."""

from __future__ import annotations

import os

from cuervo_ir.providers.base import finish, post_json, schema_note
from cuervo_ir.providers.router import ModelRequest, ModelResponse, ProviderError


class ClaudeProvider:
    name = "claude"

    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None, transport=None):
        self.api_key = os.environ.get("ANTHROPIC_API_KEY", "") if api_key is None else api_key
        self.model = model or os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5")
        self.base_url = (base_url or os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")).rstrip("/")
        self.transport = transport

    def available(self) -> bool:
        return bool(self.api_key)

    def complete(self, request: ModelRequest) -> ModelResponse:
        model = request.model or self.model
        body = {
            "model": model,
            "max_tokens": 4096,
            "system": request.system,
            "messages": [{"role": "user", "content": schema_note(request)}],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        url = f"{self.base_url}/v1/messages"
        payload = self.transport(url, headers, body) if self.transport else post_json(url, headers, body)
        try:
            text = payload["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("claude response had no text") from exc
        return finish(self.name, model, text)
