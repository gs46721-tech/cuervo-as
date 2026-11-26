"""HTTP API for the series editor. The episode is the request body, not a built-in show.

A project holds one episode and any number of agent threads. A turn in a
thread asks the model router for typed patches. In review mode they wait on
the turn until someone accepts them.
"""

from __future__ import annotations

import os
import threading
import wave
from io import BytesIO
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from cuervo_ir.credentials import CredentialError, Credentials, check
from cuervo_ir.models import Episode, LockProperty
from cuervo_ir.roles import ModelRoles, RoleChoice
from cuervo_ir.providers.router import ProviderRouter, build_default_router
from cuervo_runtime.draw import render_png
from cuervo_pipeline.run import shot_audio
from cuervo_voice.takes import SAMPLE_RATE
from cuervo_world import World, WorldError
from cuervo_world.imagegen import default_engines
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
    preview_change,
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

AGENT_STEPS = ("editor_assist",)


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


class KeyBody(BaseModel):
    """Fields left out are kept. An empty string clears that field."""

    model_config = ConfigDict(extra="forbid")

    api_key: str | None = Field(default=None, max_length=400)
    model: str | None = Field(default=None, max_length=120)
    base_url: str | None = Field(default=None, max_length=300)


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
    credentials: Credentials | None = None,
    roles: ModelRoles | None = None,
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
    # Saved keys are applied before the providers read the environment.
    app.state.credentials = credentials
    app.state.router = router if router is not None else default_router()
    rebuild_router = router is None
    app.state.roles = roles
    if roles is not None:
        roles.apply(app.state.router)

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

    def keys() -> Credentials:
        if app.state.credentials is None:
            raise HTTPException(404, "this editor was started without a keys file")
        return app.state.credentials

    def changed() -> dict:
        if rebuild_router:
            app.state.router = default_router()
        if app.state.roles is not None:
            app.state.roles.apply(app.state.router)
        return {"services": keys().view()}

    def roles_view() -> dict:
        if app.state.roles is None:
            raise HTTPException(404, "this editor was started without a models file")
        router_: ProviderRouter = app.state.router
        writers = [{"name": name, "available": provider.available()} for name, provider in router_.providers.items()]
        painters = [{"name": name, "available": engine.available(), "model": engine.default_model} for name, engine in default_engines().items()]
        rows = app.state.roles.view(router_)
        for row in rows:
            row["choices"] = painters if row["role"] == "image" else writers
        return {"roles": rows}

    @app.get("/api/settings/roles")
    def list_roles():
        return roles_view()

    @app.put("/api/settings/roles/{role}")
    def save_role(role: str, body: RoleChoice):
        view = roles_view()
        known = {item["name"] for row in view["roles"] if row["role"] == role for item in row["choices"]}
        if not known:
            raise HTTPException(404, "unknown role")
        for entry in [*body.entries, *([body.judge] if body.judge else [])]:
            allowed = known if entry in body.entries else set(app.state.router.providers)
            if entry.provider not in allowed:
                raise HTTPException(422, f"{entry.provider} cannot do that")
        app.state.roles.set(role, body)
        app.state.roles.apply(app.state.router)
        return roles_view()

    @app.get("/api/settings/keys")
    def list_keys():
        return {"services": keys().view()}

    @app.put("/api/settings/keys/{name}")
    def save_key(name: str, body: KeyBody):
        try:
            keys().set(name, key=body.api_key, model=body.model, base=body.base_url)
        except CredentialError as exc:
            raise HTTPException(422, str(exc)) from exc
        return changed()

    @app.delete("/api/settings/keys/{name}")
    def remove_key(name: str):
        try:
            keys().remove(name)
        except CredentialError as exc:
            raise HTTPException(404, str(exc)) from exc
        return changed()

    @app.post("/api/settings/keys/{name}/test")
    def test_key(name: str):
        keys()
        try:
            return check(name)
        except CredentialError as exc:
            raise HTTPException(404, str(exc)) from exc

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
        return _png(session.episode, shot_id, frame, session.poses, cache=v == session.version, world=world_of(session))

    @app.get("/api/sessions/{session_id}/changes/{change_id}/frames/{frame}.png")
    def change_frame(session_id: str, change_id: str, frame: int):
        """The shot as it would look with a waiting change applied."""

        session = _session(app, session_id)
        try:
            change = session.change(change_id)
        except EditorError as exc:
            raise HTTPException(404, str(exc)) from exc
        try:
            revised = preview_change(session, change)
        except EditorError as exc:
            raise HTTPException(409, str(exc)) from exc
        return _png(revised, change.shot_id, frame, session.poses, world=world_of(session))

    worlds: dict[str, World] = {}

    def world_of(session: Session) -> World | None:
        if not session.world_dir:
            return None
        if session.world_dir not in worlds:
            worlds[session.world_dir] = World(Path(session.world_dir))
        return worlds[session.world_dir]

    @app.get("/api/sessions/{session_id}/world")
    def world_assets(session_id: str):
        """The cast and sets this project draws from, and whether each look is approved."""

        world = world_of(_session(app, session_id))
        return {"assets": world.view() if world else []}

    @app.get("/api/sessions/{session_id}/world/{asset_id}.png")
    def world_sheet(session_id: str, asset_id: str):
        world = world_of(_session(app, session_id))
        path = world.sheet_path(asset_id) if world else None
        if path is None:
            raise HTTPException(404, "no art for that asset")
        return Response(content=path.read_bytes(), media_type="image/png", headers={"cache-control": "no-store"})

    @app.get("/api/sessions/{session_id}/world/{asset_id}/candidates/{index}.png")
    def world_candidate(session_id: str, asset_id: str, index: int):
        world = world_of(_session(app, session_id))
        path = world.candidate_path(asset_id, index) if world else None
        if path is None:
            raise HTTPException(404, "no such picture")
        return Response(content=path.read_bytes(), media_type="image/png", headers={"cache-control": "no-store"})

    @app.post("/api/sessions/{session_id}/world/{asset_id}/choose/{index}")
    def world_choose(session_id: str, asset_id: str, index: int):
        session = _session(app, session_id)
        world = world_of(session)
        if world is None:
            raise HTTPException(404, "this project has no world")
        try:
            world.choose(asset_id, index)
        except WorldError as exc:
            raise HTTPException(422, str(exc)) from exc
        with session.lock:
            # The picture behind every shot on this set changed, so the page must fetch frames again.
            session.version += 1
            app.state.store.save(session)
        return {"assets": world.view()}

    @app.post("/api/sessions/{session_id}/world/{asset_id}/{verdict}")
    def world_approve(session_id: str, asset_id: str, verdict: str):
        world = world_of(_session(app, session_id))
        if world is None or verdict not in ("approve", "reopen"):
            raise HTTPException(404, "unknown asset or action")
        try:
            world.approve(asset_id, verdict == "approve")
        except WorldError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"assets": world.view()}

    @app.get("/api/sessions/{session_id}/audio/{shot_id}.wav")
    def audio(session_id: str, shot_id: str):
        """The shot's voice takes, laid at their line starts. As long as the shot."""

        session = _session(app, session_id)
        if not session.takes_dir:
            raise HTTPException(404, "this project has no voice takes")
        try:
            shot = find_shot(session.episode, shot_id)
        except EditorError as exc:
            raise HTTPException(404, "unknown shot") from exc
        pcm = shot_audio(shot, session.episode.fps, Path(session.takes_dir))
        buffer = BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(SAMPLE_RATE)
            handle.writeframes(pcm)
        return Response(content=buffer.getvalue(), media_type="audio/wav", headers={"cache-control": "no-store"})

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
    # Roles are applied by the app, from its own models file.
    router = build_default_router(roles=False)
    if os.environ.get("CUERVO_EDITOR_STUB") == "1":
        router.register(
            DevStub(),
            steps={"editor_assist": ("devstub", "cursor", "claude", "gemini")},
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


def _png(episode: Episode, shot_id: str, frame: int, poses, cache: bool = False, world=None) -> Response:
    try:
        shot = find_shot(episode, shot_id)
    except EditorError as exc:
        raise HTTPException(404, "unknown shot") from exc
    try:
        png = render_png(episode, shot, frame, poses, world=world)
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc
    policy = "private, max-age=86400, immutable" if cache else "no-store"
    return Response(content=png, media_type="image/png", headers={"cache-control": policy})


def __getattr__(name: str):
    # `cuervo_editor.api:app` is built on first use, so importing this module reads no disk.
    if name == "app":
        application = create_app(home=default_home(), credentials=Credentials(), roles=ModelRoles())
        globals()["app"] = application
        return application
    raise AttributeError(name)
