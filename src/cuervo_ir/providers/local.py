"""Agents already installed and signed in on this computer.

No API key is involved. Each adapter runs the vendor's own command-line agent
the way a person would, in its non-interactive mode, and reads back the
answer. The agent uses whatever account its owner signed in with.

    Claude Code    claude -p --output-format json            (prompt on stdin)
    Codex          codex exec --output-last-message <file> -  (prompt on stdin)
    Cursor         agent -p --output-format text <prompt>
    Antigravity    agy acp                                    (Agent Client Protocol on stdio)

Every run happens in an empty scratch folder with the agent's tools turned
off or read-only, because here the agent is only asked for text.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from cuervo_ir.providers.base import finish, schema_note
from cuervo_ir.providers.router import ModelRequest, ModelResponse, ProviderError

TIMEOUT_SECONDS = 600
# Set by a host agent session. A child agent must not think it is that session.
INHERITED = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT")


class LocalAgent:
    """Shared plumbing: find the binary, run it in a scratch folder, turn failures into plain words."""

    name = ""
    label = ""
    binaries: tuple[str, ...] = ()
    bin_env = ""
    model_env = ""
    login_hint = ""
    install_url = ""

    def __init__(self, binary: str | None = None, model: str | None = None):
        self._binary = binary
        self._model = model

    @property
    def model(self) -> str:
        return self._model or os.environ.get(self.model_env, "")

    def binary(self) -> str | None:
        """The executable to run: the configured path, else the first one found on PATH."""

        configured = self._binary or os.environ.get(self.bin_env, "")
        if configured:
            found = shutil.which(configured) or (configured if Path(configured).is_file() else None)
            return found
        for candidate in self.binaries:
            found = shutil.which(candidate)
            if found:
                return found
        return None

    def available(self) -> bool:
        return self.binary() is not None

    def version(self) -> str:
        binary = self.binary()
        if binary is None:
            return ""
        try:
            done = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=15, env=_environment())
        except (OSError, subprocess.SubprocessError):
            return ""
        return (done.stdout or done.stderr).strip().splitlines()[0][:80] if (done.stdout or done.stderr).strip() else ""

    def complete(self, request: ModelRequest) -> ModelResponse:
        binary = self.binary()
        if binary is None:
            raise ProviderError(f"{self.label} is not installed on this computer")
        model = request.model or self.model
        with tempfile.TemporaryDirectory(prefix="cuervo-agent-") as scratch:
            text = self.ask(binary, request, model, Path(scratch))
        return finish(self.name, model or "default", text)

    def ask(self, binary: str, request: ModelRequest, model: str, scratch: Path) -> str:
        raise NotImplementedError

    def _run(self, command: list[str], scratch: Path, stdin: str | None) -> subprocess.CompletedProcess:
        try:
            done = subprocess.run(
                command, input=stdin, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, cwd=scratch, env=_environment()
            )
        except subprocess.TimeoutExpired as exc:
            raise ProviderError(f"{self.label} did not answer in {TIMEOUT_SECONDS // 60} minutes") from exc
        except OSError as exc:
            raise ProviderError(f"{self.label} could not be started: {exc}") from exc
        if done.returncode != 0:
            raise ProviderError(self._explain(done.stderr or done.stdout))
        return done

    def _explain(self, detail: str) -> str:
        detail = detail.strip()
        lowered = detail.lower()
        if any(word in lowered for word in ("log in", "login", "logged in", "unauthorized", "authenticate", "sign in", "401")):
            return f"{self.label} is not signed in. {self.login_hint}"
        return f"{self.label} failed: {detail[-300:] or 'no message'}"


def _environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key not in INHERITED}


def _one_prompt(request: ModelRequest) -> str:
    """For agents with no separate system prompt: instructions first, then the task."""

    return f"{request.system}\n\n---\n\n{schema_note(request)}"


class ClaudeCodeAgent(LocalAgent):
    name = "claude-code"
    label = "Claude Code"
    binaries = ("claude",)
    bin_env = "CUERVO_CLAUDE_CODE_BIN"
    model_env = "CUERVO_CLAUDE_CODE_MODEL"
    login_hint = "Run `claude auth login` in a terminal."
    install_url = "https://claude.com/product/claude-code"

    def ask(self, binary: str, request: ModelRequest, model: str, scratch: Path) -> str:
        command = [
            binary,
            "-p",
            "--output-format",
            "json",
            "--system-prompt",
            request.system,
            # Text only: no tools, no project settings, no MCP servers, nothing saved.
            "--tools",
            "",
            "--disable-slash-commands",
            "--no-session-persistence",
            "--strict-mcp-config",
            "--permission-mode",
            "dontAsk",
        ]
        if model:
            command += ["--model", model]
        done = self._run(command, scratch, schema_note(request))
        try:
            payload = json.loads(done.stdout)
        except json.JSONDecodeError as exc:
            raise ProviderError("Claude Code did not return JSON") from exc
        if isinstance(payload, list):
            payload = next((item for item in reversed(payload) if isinstance(item, dict) and item.get("type") == "result"), {})
        if payload.get("is_error"):
            raise ProviderError(self._explain(str(payload.get("result") or payload.get("subtype") or "")))
        return str(payload.get("result") or "")


class CodexAgent(LocalAgent):
    name = "codex"
    label = "Codex"
    binaries = ("codex",)
    bin_env = "CUERVO_CODEX_BIN"
    model_env = "CUERVO_CODEX_MODEL"
    login_hint = "Run `codex login` in a terminal."
    install_url = "https://developers.openai.com/codex/cli"

    def ask(self, binary: str, request: ModelRequest, model: str, scratch: Path) -> str:
        answer = scratch / "answer.txt"
        command = [binary, "exec", "--ephemeral", "--skip-git-repo-check", "-s", "read-only", "--config", "features.hooks=false"]
        if model:
            command += ["--model", model]
        command += ["--output-last-message", str(answer), "-"]
        self._run(command, scratch, _one_prompt(request))
        try:
            return answer.read_text(encoding="utf-8")
        except OSError as exc:
            raise ProviderError("Codex finished without an answer") from exc


class CursorAgent(LocalAgent):
    name = "cursor-agent"
    label = "Cursor"
    binaries = ("agent", "cursor-agent")
    bin_env = "CUERVO_CURSOR_BIN"
    model_env = "CUERVO_CURSOR_MODEL"
    login_hint = "Run `agent login` in a terminal."
    install_url = "https://cursor.com/cli"

    def ask(self, binary: str, request: ModelRequest, model: str, scratch: Path) -> str:
        command = [binary, "-p", "--output-format", "text"]
        if model:
            command += ["--model", model]
        command.append(_one_prompt(request))
        return self._run(command, scratch, None).stdout


class AcpAgent(LocalAgent):
    """Any agent that speaks the Agent Client Protocol on its standard input and output."""

    arguments: tuple[str, ...] = ()

    def ask(self, binary: str, request: ModelRequest, model: str, scratch: Path) -> str:
        try:
            process = subprocess.Popen(
                [binary, *self.arguments],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=scratch,
                env=_environment(),
            )
        except OSError as exc:
            raise ProviderError(f"{self.label} could not be started: {exc}") from exc
        chunks: list[str] = []
        errors: list[str] = []
        timer = threading.Timer(TIMEOUT_SECONDS, process.kill)
        timer.start()
        threading.Thread(target=lambda: errors.append(process.stderr.read() if process.stderr else ""), daemon=True).start()
        try:
            self._call(process, 1, "initialize", {"protocolVersion": 1, "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}}}, chunks)
            session = self._call(process, 2, "session/new", {"cwd": str(scratch), "mcpServers": []}, chunks)
            session_id = session.get("sessionId")
            if not session_id:
                raise ProviderError(f"{self.label} did not open a session")
            self._call(process, 3, "session/prompt", {"sessionId": session_id, "prompt": [{"type": "text", "text": _one_prompt(request)}]}, chunks)
        except (BrokenPipeError, OSError) as exc:
            raise ProviderError(self._explain("".join(errors) or str(exc))) from exc
        finally:
            timer.cancel()
            # Let the agent close its session, then make sure it is gone.
            try:
                if process.stdin is not None:
                    process.stdin.close()
                process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
                process.wait()
        return "".join(chunks)

    def _call(self, process: subprocess.Popen, number: int, method: str, params: dict, chunks: list[str]) -> dict:
        """Send one request and read until its reply. Messages the agent sends meanwhile are handled here."""

        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": number, "method": method, "params": params}) + "\n")
        process.stdin.flush()
        for line in process.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue
            if message.get("id") == number and "method" not in message:
                if "error" in message:
                    detail = message["error"]
                    raise ProviderError(self._explain(str(detail.get("message") if isinstance(detail, dict) else detail)))
                result = message.get("result")
                return result if isinstance(result, dict) else {}
            if message.get("method") == "session/update":
                update = (message.get("params") or {}).get("update") or {}
                content = update.get("content") or {}
                if update.get("sessionUpdate") == "agent_message_chunk" and content.get("type") == "text":
                    chunks.append(str(content.get("text", "")))
            elif "id" in message and "method" in message:
                # The agent wants to use a tool or a file. It is only here to write text, so say no.
                if message["method"] == "session/request_permission":
                    reply = {"result": {"outcome": {"outcome": "cancelled"}}}
                else:
                    reply = {"error": {"code": -32601, "message": "not available"}}
                process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": message["id"], **reply}) + "\n")
                process.stdin.flush()
        raise ProviderError(self._explain(f"it closed before answering {method}"))


class AntigravityAgent(AcpAgent):
    name = "antigravity"
    label = "Antigravity"
    binaries = ("agy",)
    arguments = ("acp",)
    bin_env = "CUERVO_ANTIGRAVITY_BIN"
    model_env = "CUERVO_ANTIGRAVITY_MODEL"
    login_hint = "Open Antigravity and sign in with Google, or run `agy` once in a terminal."
    install_url = "https://antigravity.google/docs/getting-started"


def local_agents() -> list[LocalAgent]:
    return [ClaudeCodeAgent(), CodexAgent(), CursorAgent(), AntigravityAgent()]
