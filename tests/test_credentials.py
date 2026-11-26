import os

from fastapi.testclient import TestClient

from cuervo_ir.credentials import Credentials, check
from cuervo_editor.api import create_app


def test_a_saved_key_connects_the_provider_and_is_never_returned(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    path = tmp_path / "keys.json"
    client = TestClient(create_app(background=False, credentials=Credentials(path)))
    listed = client.get("/api/providers").json()["providers"]
    assert next(item for item in listed if item["name"] == "claude")["available"] is False

    saved = client.put("/api/settings/keys/claude", json={"api_key": "sk-test-abcd1234", "model": "claude-test"})
    assert saved.status_code == 200
    row = next(item for item in saved.json()["services"] if item["name"] == "claude")
    assert row["connected"] is True
    assert row["key_hint"] == "…1234"
    assert row["key_source"] == "saved"
    assert "sk-test" not in saved.text
    assert oct(path.stat().st_mode & 0o777) == "0o600"

    # The running router picks the key up without a restart.
    claude = next(item for item in client.get("/api/providers").json()["providers"] if item["name"] == "claude")
    assert claude == {"name": "claude", "available": True, "model": "claude-test"}
    # A later process reads the same file.
    assert Credentials(path).view()[0]["connected"] is True

    removed = client.delete("/api/settings/keys/claude").json()
    assert next(item for item in removed["services"] if item["name"] == "claude")["connected"] is False
    assert "ANTHROPIC_API_KEY" not in os.environ


def test_cursor_needs_a_base_url_and_rejects_a_bad_one(tmp_path):
    client = TestClient(create_app(background=False, credentials=Credentials(tmp_path / "keys.json")))
    only_key = client.put("/api/settings/keys/cursor", json={"api_key": "key-12345678"}).json()
    assert next(item for item in only_key["services"] if item["name"] == "cursor")["connected"] is False
    assert client.put("/api/settings/keys/cursor", json={"base_url": "ftp://nope"}).status_code == 422
    both = client.put("/api/settings/keys/cursor", json={"base_url": "https://example.test/v1"}).json()
    assert next(item for item in both["services"] if item["name"] == "cursor")["connected"] is True
    client.delete("/api/settings/keys/cursor")


def test_checking_elevenlabs_lists_the_account_voices(tmp_path):
    keys = Credentials(tmp_path / "keys.json")
    assert check("elevenlabs")["ok"] is False
    keys.set("elevenlabs", key="xi-12345678")
    seen = {}

    def fetch(url, headers):
        seen.update(url=url, headers=headers)
        return {"voices": [{"voice_id": "v1", "name": "Narrator"}]}

    result = check("elevenlabs", fetch)
    assert seen == {"url": "https://api.elevenlabs.io/v1/voices", "headers": {"xi-api-key": "xi-12345678"}}
    assert result["voices"] == [{"voice_id": "v1", "name": "Narrator"}]
    keys.remove("elevenlabs")
