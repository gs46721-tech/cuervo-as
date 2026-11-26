"""HTTP API for the series editor. The episode is the request body, not a built-in show.

A project holds one episode and any number of agent threads. A turn in a
thread asks the model router for typed patches. In review mode they wait on
the turn until someone accepts them.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from cuervo_ir.models import Episode, LockProperty
from cuervo_ir.providers.router import ProviderRouter, build_default_router
from cuervo_runtime.draw import render_png
from cuervo_edit.edits import EditPatch, apply_edit
from cuervo_editor.agent import run_turn
from cuervo_editor.store import (
    EditorError,
    Session,
    SessionStore,
    Thread,
    Turn,
    TurnMode,
    accept_change,
    find_shot,
    new_id,
    redo,
    reject_change,
    revert_turn,
    session_card,
    session_view,
    set_locks,
    snapshot_push,
    undo,
)
from cuervo_editor.stub import DevStub

AGENT_STEPS = ("editor_assist", "ir_patch")


class OpenBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    episode: dict
    poses: dict[str, dict[str, float]] | None = None


class ThreadBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=120)


class TurnBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction: str = Field(min_length=1, max_length=4000)
    # Shots the person pinned. Empty lets the agent choose.
    shot_ids: list[str] = Field(default_factory=list)
    # The shot on screen. A hint for the agent, not a limit.
    focus_shot_id: str | None = None
    provider: str | None = None
    mode: TurnMode = "review"


class LockBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_id: str
    track_id: str
    properties: list[LockProperty]


def create_app(
    router: ProviderRouter | None = None,
    *,
    home: Path | None = None,
    background: bool = True,
    dist: Path | None = None,
) -> FastAPI:
    """`home` keeps projects on disk. `background=False` runs a turn inside the request, for tests."""

    app = FastAPI(title="Cuervo editor")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.store = SessionStore(home)
    app.state.router = router if router is not None else default_router()

    def state(session: Session, **extra) -> dict:
        with session.lock:
            return {**session_view(session), **extra}

    def mutate(session: Session, action) -> None:
        with session.lock:
            try:
                action()
            except EditorError as exc:
                raise HTTPException(422, str(exc)) from exc
            app.state.store.save(session)

    @app.get("/api/providers")
    def providers():
        router_: ProviderRouter = app.state.router
        names = list(dict.fromkeys(name for step in AGENT_STEPS for name in router_.routes.get(step, ())))
        return {
            "providers": [
                {
                    "name": name,
                    "available": name in router_.providers and router_.providers[name].available(),
                    "model": getattr(router_.providers.get(name), "model", None),
                }
                for name in names
            ],
            "routes": {step: list(router_.routes.get(step, ())) for step in AGENT_STEPS},
        }

    @app.get("/api/sessions")
    def list_sessions():
        return {"sessions": [session_card(session) for session in app.state.store.all()]}

    @app.post("/api/sessions")
    def open_session(body: OpenBody):
        try:
            episode = Episode.model_validate(body.episode)
        except Exception as exc:
            raise HTTPException(422, str(exc)) from exc
        _session_id, session = app.state.store.open(episode, body.poses)
        return state(session)

    @app.get("/api/sessions/{session_id}")
    def read_session(session_id: str):
        return state(_session(app, session_id))

    @app.delete("/api/sessions/{session_id}")
    def delete_session(session_id: str):
        session = _session(app, session_id)
        if session.running():
            raise HTTPException(409, "a turn is still running in this project")
        app.state.store.delete(session_id)
        return {"deleted": session_id}

    @app.get("/api/sessions/{session_id}/episode.json")
    def export_episode(session_id: str):
        session = _session(app, session_id)
        name = f"{session.episode.episode_id}.json"
        return JSONResponse(
            session.episode.model_dump(mode="json"),
            headers={"content-disposition": f'attachment; filename="{name}"'},
        )

    @app.get("/api/sessions/{session_id}/frames/{shot_id}/{frame}.png")
    def frame(session_id: str, shot_id: str, frame: int, v: int | None = None):
        session = _session(app, session_id)
        # `v` is the project version the page asked for. That picture never changes.
        return _png(session.episode, shot_id, frame, session.poses, cache=v == session.version)

    @app.get("/api/sessions/{session_id}/changes/{change_id}/frames/{frame}.png")
    def change_frame(session_id: str, change_id: str, frame: int):
        """The shot as it would look with a waiting change applied."""

        session = _session(app, session_id)
        try:
            change = session.change(change_id)
        except EditorError as exc:
            raise HTTPException(404, str(exc)) from exc
        if change.status != "pending" or change.patch is None:
            raise HTTPException(409, "this change is not waiting for review")
        try:
            revised = apply_edit(session.episode, EditPatch.model_validate(change.patch))
        except Exception as exc:
            raise HTTPException(422, str(exc)) from exc
        return _png(revised, change.shot_id, frame, session.poses)

    # -- threads and turns --------------------------------------------------

    @app.post("/api/sessions/{session_id}/threads")
    def create_thread(session_id: str, body: ThreadBody | None = None):
        session = _session(app, session_id)
        thread = Thread(thread_id=new_id("thr"))
        if body and body.title:
            thread.title = body.title
        mutate(session, lambda: session.threads.append(thread))
        return state(session, thread_id=thread.thread_id)

    @app.patch("/api/sessions/{session_id}/threads/{thread_id}")
    def rename_thread(session_id: str, thread_id: str, body: ThreadBody):
        session = _session(app, session_id)
        thread = _lookup(session.thread, thread_id)
        if not body.title or not body.title.strip():
            raise HTTPException(422, "a thread needs a title")

        def rename() -> None:
            thread.title = body.title.strip()

        mutate(session, rename)
        return state(session)

    @app.delete("/api/sessions/{session_id}/threads/{thread_id}")
    def delete_thread(session_id: str, thread_id: str):
        session = _session(app, session_id)
        thread = _lookup(session.thread, thread_id)
        if any(turn.status == "running" for turn in thread.turns):
            raise HTTPException(409, "a turn is still running in this thread")
        mutate(session, lambda: session.threads.remove(thread))
        return state(session)

    @app.post("/api/sessions/{session_id}/threads/{thread_id}/turns")
    def start_turn(session_id: str, thread_id: str, body: TurnBody):
        session = _session(app, session_id)
        thread = _lookup(session.thread, thread_id)
        instruction = body.instruction.strip()
        if not instruction:
            raise HTTPException(422, "say what should change")
        if body.provider is not None and body.provider not in app.state.router.providers:
            raise HTTPException(422, f"unknown provider {body.provider}")
        with session.lock:
            if any(turn.status == "running" for turn in thread.turns):
                raise HTTPException(409, "this thread is still working on the last turn")
            try:
                for shot_id in body.shot_ids:
                    find_shot(session.episode, shot_id)
            except EditorError as exc:
                raise HTTPException(422, str(exc)) from exc
            turn = Turn(
                turn_id=new_id("turn"),
                instruction=instruction,
                shot_ids=list(dict.fromkeys(body.shot_ids)),
                focus_shot_id=body.focus_shot_id,
                provider=body.provider,
                mode=body.mode,
            )
            if not thread.turns:
                thread.title = instruction if len(instruction) <= 60 else instruction[:57].rstrip() + "…"
            thread.turns.append(turn)
            app.state.store.save(session)
        work = (session, thread, turn, app.state.router, app.state.store)
        if background:
            threading.Thread(target=run_turn, args=work, daemon=True, name=turn.turn_id).start()
        else:
            run_turn(*work)
        return state(session, turn_id=turn.turn_id)

    @app.post("/api/sessions/{session_id}/turns/{turn_id}/stop")
    def stop_turn(session_id: str, turn_id: str):
        session = _session(app, session_id)
        turn = _lookup(session.turn, turn_id)
        with session.lock:
            if turn.status == "running":
                session.stop_requests.add(turn_id)
        return state(session)

    @app.post("/api/sessions/{session_id}/turns/{turn_id}/{verdict}")
    def review_turn(session_id: str, turn_id: str, verdict: str):
        session = _session(app, session_id)
        turn = _lookup(session.turn, turn_id)
        if verdict == "revert":
            mutate(session, lambda: revert_turn(session, turn))
            return state(session)
        if verdict not in ("accept", "reject"):
            raise HTTPException(404, "unknown action")
        waiting = [change for change in turn.changes if change.status == "pending"]
        if not waiting:
            raise HTTPException(422, "this turn has nothing waiting for review")

        def review() -> None:
            for change in waiting:
                if verdict == "accept":
                    accept_change(session, change)
                else:
                    reject_change(change)

        mutate(session, review)
        return state(session)

    @app.post("/api/sessions/{session_id}/changes/{change_id}/{verdict}")
    def review_change(session_id: str, change_id: str, verdict: str):
        session = _session(app, session_id)
        change = _lookup(session.change, change_id)
        if verdict == "accept":
            mutate(session, lambda: accept_change(session, change))
        elif verdict == "reject":
            mutate(session, lambda: reject_change(change))
        else:
            raise HTTPException(404, "unknown action")
        return state(session)

    # -- history and locks --------------------------------------------------

    @app.post("/api/sessions/{session_id}/undo")
    def undo_session(session_id: str):
        session = _session(app, session_id)
        mutate(session, lambda: undo(session))
        return state(session)

    @app.post("/api/sessions/{session_id}/redo")
    def redo_session(session_id: str):
        session = _session(app, session_id)
        mutate(session, lambda: redo(session))
        return state(session)

    @app.post("/api/sessions/{session_id}/lock")
    def lock(session_id: str, body: LockBody):
        session = _session(app, session_id)
        mutate(
            session,
            lambda: snapshot_push(
                session, set_locks(session.episode, body.shot_id, body.track_id, body.properties)
            ),
        )
        return state(session)

    built = dist if dist is not None else _default_dist()
    if built is not None and (built / "index.html").is_file():
        app.mount("/", StaticFiles(directory=built, html=True), name="editor")

    return app


def default_router() -> ProviderRouter:
    router = build_default_router()
    if os.environ.get("CUERVO_EDITOR_STUB") == "1":
        router.register(
            DevStub(),
            steps={
                "ir_patch": ("devstub", "claude", "gemini", "cursor"),
                "editor_assist": ("devstub", "cursor", "claude", "gemini"),
            },
        )
    return router


def default_home() -> Path:
    configured = os.environ.get("CUERVO_EDITOR_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".cuervo" / "projects"


def _default_dist() -> Path | None:
    configured = os.environ.get("CUERVO_EDITOR_DIST")
    if configured:
        return Path(configured)
    candidate = Path(__file__).resolve().parents[2] / "editor" / "dist"
    return candidate if candidate.is_dir() else None


def _session(app: FastAPI, session_id: str) -> Session:
    return _lookup(app.state.store.get, session_id)


def _lookup(find, key: str):
    try:
        return find(key)
    except EditorError as exc:
        raise HTTPException(404, str(exc)) from exc


def _png(episode: Episode, shot_id: str, frame: int, poses, cache: bool = False) -> Response:
    try:
        shot = find_shot(episode, shot_id)
    except EditorError as exc:
        raise HTTPException(404, "unknown shot") from exc
    try:
        png = render_png(episode, shot, frame, poses)
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc
    policy = "private, max-age=86400, immutable" if cache else "no-store"
    return Response(content=png, media_type="image/png", headers={"cache-control": policy})


def __getattr__(name: str):
    # `cuervo_editor.api:app` is built on first use, so importing this module reads no disk.
    if name == "app":
        application = create_app(home=default_home())
        globals()["app"] = application
        return application
    raise AttributeError(name)
