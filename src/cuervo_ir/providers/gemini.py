"""Gemini generateContent adapter."""

from __future__ import annotations

import os

from cuervo_ir.providers.base import finish, post_json, schema_note
from cuervo_ir.providers.router import ModelRequest, ModelResponse, ProviderError


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None, transport=None):
        self.api_key = os.environ.get("GEMINI_API_KEY", "") if api_key is None else api_key
        self.model = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")
        self.base_url = (
            base_url or os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com")
        ).rstrip("/")
        self.transport = transport

    def available(self) -> bool:
        return bool(self.api_key)

    def complete(self, request: ModelRequest) -> ModelResponse:
        body = {
            "systemInstruction": {"parts": [{"text": request.system}]},
            "contents": [{"role": "user", "parts": [{"text": schema_note(request)}]}],
        }
        model = request.model or self.model
        url = f"{self.base_url}/v1beta/models/{model}:generateContent?key={self.api_key}"
        payload = self.transport(url, {}, body) if self.transport else post_json(url, {}, body)
        try:
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("gemini response had no text") from exc
        return finish(self.name, model, text)
