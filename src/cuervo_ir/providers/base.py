"""Shared HTTP helper for provider adapters. Tests pass a transport and never hit the network."""

from __future__ import annotations

import json
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from cuervo_ir.providers.router import ModelRequest, ModelResponse, ProviderError

Transport = Callable[[str, dict[str, str], dict], dict]


def post_json(url: str, headers: dict[str, str], body: dict, timeout: float = 60) -> dict:
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json", **headers},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise ProviderError(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ProviderError(str(exc.reason)) from exc
    except json.JSONDecodeError as exc:
        raise ProviderError("response was not JSON") from exc


def finish(provider: str, model: str, text: str) -> ModelResponse:
    if not text.strip():
        raise ProviderError(f"{provider} returned an empty completion")
    return ModelResponse(provider=provider, model=model, text=text)


def schema_note(request: ModelRequest) -> str:
    if request.response_schema is None:
        return request.user
    encoded = json.dumps(request.response_schema, separators=(",", ":"))
    return f"{request.user}\n\nRespond with JSON only, matching this schema: {encoded}"
