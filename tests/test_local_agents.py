"""Agents on this computer, driven through stand-in programs that behave like the real ones."""

import json
import os
import stat
import sys
import textwrap

import pytest
from fastapi.testclient import TestClient

from cuervo_ir.credentials import Credentials
from cuervo_ir.providers.local import AntigravityAgent, ClaudeCodeAgent, CodexAgent, CursorAgent
from cuervo_ir.providers.router import ModelRequest, ProviderError, build_default_router
from cuervo_editor.api import create_app

REQUEST = ModelRequest("writing", "Be brief.", "Write one line.")


def _program(folder, name: str, body: str) -> str:
    """A fake agent: a Python script that records how it was called and answers like the real CLI."""

    path = folder / name
    path.write_text(f"#!{sys.executable}\nimport json, os, sys\nLOG = {str(folder / (name + '.log'))!r}\n" + textwrap.dedent(body))
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def _log(folder, name: str) -> dict:
    return json.loads((folder / f"{name}.log").read_text())


def test_claude_code_runs_headless_with_tools_off(tmp_path):
    binary = _program(
        tmp_path,
        "claude",
        """
        json.dump({"args": sys.argv[1:], "stdin": sys.stdin.read(), "cwd": os.getcwd(), "nested": os.environ.get("CLAUDECODE")}, open(LOG, "w"))
        print(json.dumps({"type": "result", "is_error": False, "result": "A line."}))
        """,
    )
    os.environ["CLAUDECODE"] = "1"
    try:
        reply = ClaudeCodeAgent(binary=binary, model="opus").complete(REQUEST)
    finally:
        del os.environ["CLAUDECODE"]
    assert (reply.provider, reply.model, reply.text) == ("claude-code", "opus", "A line.")
    seen = _log(tmp_path, "claude")
    args = seen["args"]
    assert args[:3] == ["-p", "--output-format", "json"]
    assert args[args.index("--system-prompt") + 1] == "Be brief."
    assert args[args.index("--tools") + 1] == "" and args[args.index("--model") + 1] == "opus"
    assert "--no-session-persistence" in args and "--strict-mcp-config" in args
    assert seen["stdin"] == "Write one line."
    # It ran in a scratch folder, not the project, and not as a child of another agent session.
    assert seen["cwd"] != os.getcwd() and seen["nested"] is None


def test_codex_reads_the_last_message_file_and_runs_read_only(tmp_path):
    binary = _program(
        tmp_path,
        "codex",
        """
        args = sys.argv[1:]
        json.dump({"args": args, "stdin": sys.stdin.read()}, open(LOG, "w"))
        open(args[args.index("--output-last-message") + 1], "w").write("From codex.")
        """,
    )
    reply = CodexAgent(binary=binary).complete(REQUEST)
    assert reply.text == "From codex." and reply.model == "default"
    seen = _log(tmp_path, "codex")
    assert seen["args"][:6] == ["exec", "--ephemeral", "--skip-git-repo-check", "-s", "read-only", "--config"]
    assert seen["args"][-1] == "-" and "--model" not in seen["args"]
    assert seen["stdin"].startswith("Be brief.") and seen["stdin"].endswith("Write one line.")


def test_cursor_prints_the_answer(tmp_path):
    binary = _program(tmp_path, "agent", 'json.dump({"args": sys.argv[1:]}, open(LOG, "w"))\nprint("From cursor.")\n')
    assert CursorAgent(binary=binary, model="gpt-x").complete(REQUEST).text.strip() == "From cursor."
    args = _log(tmp_path, "agent")["args"]
    assert args[:5] == ["-p", "--output-format", "text", "--model", "gpt-x"] and args[-1].endswith("Write one line.")


def test_antigravity_speaks_the_agent_client_protocol_and_is_refused_tools(tmp_path):
    binary = _program(
        tmp_path,
        "agy",
        """
        seen = {"args": sys.argv[1:], "methods": [], "permission": None}
        def send(message):
            sys.stdout.write(json.dumps(message) + "\\n"); sys.stdout.flush()
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            message = json.loads(line)
            seen["methods"].append(message["method"])
            if message["method"] == "initialize":
                seen["client"] = message["params"]
                send({"jsonrpc": "2.0", "id": message["id"], "result": {"protocolVersion": 1}})
            elif message["method"] == "session/new":
                send({"jsonrpc": "2.0", "id": message["id"], "result": {"sessionId": "s1"}})
            elif message["method"] == "session/prompt":
                seen["prompt"] = message["params"]["prompt"][0]["text"]
                send({"jsonrpc": "2.0", "id": 99, "method": "session/request_permission", "params": {}})
                seen["permission"] = json.loads(sys.stdin.readline()).get("result")
                for word in ("From ", "antigravity."):
                    send({"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": word}}}})
                send({"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "agent_thought_chunk", "content": {"type": "text", "text": "thinking"}}}})
                with open(LOG, "w") as handle:
                    json.dump(seen, handle)
                send({"jsonrpc": "2.0", "id": message["id"], "result": {"stopReason": "end_turn"}})
        """,
    )
    assert AntigravityAgent(binary=binary).complete(REQUEST).text == "From antigravity."
    seen = _log(tmp_path, "agy")
    assert seen["args"] == ["acp"]
    assert seen["methods"] == ["initialize", "session/new", "session/prompt"]
    assert seen["client"]["clientCapabilities"]["fs"] == {"readTextFile": False, "writeTextFile": False}
    assert seen["permission"] == {"outcome": {"outcome": "cancelled"}}
    assert seen["prompt"].endswith("Write one line.")


def test_a_signed_out_agent_says_how_to_sign_in(tmp_path):
    binary = _program(tmp_path, "codex", 'sys.stderr.write("error: not logged in, 401 Unauthorized")\nsys.exit(1)\n')
    with pytest.raises(ProviderError, match="Codex is not signed in. Run `codex login`"):
        CodexAgent(binary=binary).complete(REQUEST)
    with pytest.raises(ProviderError, match="not installed"):
        CursorAgent(binary=str(tmp_path / "missing")).complete(REQUEST)


def test_local_agents_join_every_route_after_the_keyed_providers():
    router = build_default_router(roles=False)
    assert router.routes["writing"] == ("claude", "gemini", "cursor", "claude-code", "codex", "cursor-agent", "antigravity")
    assert {"claude-code", "codex", "cursor-agent", "antigravity"} <= set(router.providers)


def test_settings_show_what_is_installed_and_take_a_path_but_no_key(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    client = TestClient(create_app(background=False, credentials=Credentials(tmp_path / "keys.json")))
    rows = {row["name"]: row for row in client.get("/api/settings/keys").json()["services"]}
    assert rows["codex"]["kind"] == "local" and rows["codex"]["connected"] is False
    assert rows["claude"]["kind"] == "key"
    assert client.put("/api/settings/keys/codex", json={"api_key": "sk-nope"}).status_code == 422

    binary = _program(
        tmp_path,
        "my-codex",
        """
        args = sys.argv[1:]
        if args == ["--version"]:
            print("codex-cli 9.9.9"); sys.exit(0)
        open(args[args.index("--output-last-message") + 1], "w").write("ready")
        """,
    )
    saved = client.put("/api/settings/keys/codex", json={"base_url": binary, "model": "gpt-test"}).json()
    row = next(item for item in saved["services"] if item["name"] == "codex")
    assert row["connected"] is True and row["version"] == "codex-cli 9.9.9" and row["model"] == "gpt-test"
    assert client.post("/api/settings/keys/codex/test").json() == {"ok": True, "message": "Connected. It answered: ready", "models": []}
    # The running editor can now use it.
    listed = {item["name"]: item for item in client.get("/api/providers").json()["providers"]}
    assert listed["codex"] == {"name": "codex", "available": True, "model": "gpt-test"}
    client.delete("/api/settings/keys/codex")
