"""Cursor adapter.

There is no default host. Set CURSOR_API_BASE to an OpenAI-compatible
`/chat/completions` endpoint (the base URL, without the path). The router
skips this provider until both the base and CURSOR_API_KEY are set.
"""

from __future__ import annotations

import os

from cuervo_ir.providers.base import finish, post_json, schema_note
from cuervo_ir.providers.router import ModelRequest, ModelResponse, ProviderError


class CursorProvider:
    name = "cursor"

    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None, transport=None):
        self.api_key = os.environ.get("CURSOR_API_KEY", "") if api_key is None else api_key
        self.model = model or os.environ.get("CURSOR_MODEL", "composer-2.5")
        configured = os.environ.get("CURSOR_API_BASE", "") if base_url is None else base_url
        self.base_url = configured.rstrip("/")
        self.transport = transport

    def available(self) -> bool:
        return bool(self.api_key and self.base_url)

    def complete(self, request: ModelRequest) -> ModelResponse:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": schema_note(request)},
            ],
        }
        headers = {"authorization": f"Bearer {self.api_key}"}
        url = f"{self.base_url}/chat/completions"
        payload = self.transport(url, headers, body) if self.transport else post_json(url, headers, body)
        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("cursor response had no text") from exc
        return finish(self.name, self.model, text)
