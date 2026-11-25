"""HTTP API for the series editor. The episode is the request body, not a built-in show."""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict

from cuervo_ir.models import Episode, LockProperty
from cuervo_ir.providers.router import ProviderRouter, ProviderUnavailable, build_default_router
from cuervo_runtime.draw import render_png
from cuervo_edit.edits import EditPatch
from cuervo_edit.propose import propose_edit
from cuervo_editor.store import (
    EditorError,
    SessionStore,
    accept,
    dry_apply,
    lock_track,
    redo,
    snapshot_push,
    summarize,
    undo,
)
from cuervo_editor.stub import DevStub


class OpenBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    episode: dict
    poses: dict[str, dict[str, float]] | None = None


class ProposeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_id: str
    instruction: str


class LockBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_id: str
    track_id: str
    properties: list[LockProperty]


def create_app(router: ProviderRouter | None = None) -> FastAPI:
    app = FastAPI(title="Cuervo editor")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.store = SessionStore()
    app.state.router = router if router is not None else default_router()

    @app.post("/api/sessions")
    def open_session(body: OpenBody):
        try:
            episode = Episode.model_validate(body.episode)
        except Exception as exc:
            raise HTTPException(422, str(exc)) from exc
        session_id, session = app.state.store.open(episode, body.poses)
        return {"session_id": session_id, "episode": summarize(session.episode), "snapshots": 0}

    @app.get("/api/sessions/{session_id}")
    def read_session(session_id: str):
        session = _session(app, session_id)
        return _state(session)

    @app.get("/api/sessions/{session_id}/frames/{shot_id}/{frame}.png")
    def frame(session_id: str, shot_id: str, frame: int):
        session = _session(app, session_id)
        try:
            shot = next(
                shot
                for scene in session.episode.scenes
                for shot in scene.shots
                if shot.shot_id == shot_id
            )
            png = render_png(session.episode, shot, frame, session.poses)
        except StopIteration as exc:
            raise HTTPException(404, "unknown shot") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(422, str(exc)) from exc
        return Response(content=png, media_type="image/png")

    @app.post("/api/sessions/{session_id}/propose")
    def propose(session_id: str, body: ProposeBody):
        session = _session(app, session_id)
        try:
            patch = propose_edit(session.episode, body.shot_id, body.instruction, app.state.router)
            _revised, lines = dry_apply(session, patch)
        except ProviderUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except (EditorError, Exception) as exc:
            raise HTTPException(422, str(exc)) from exc
        session.pending = patch
        return {"patch": patch.model_dump(mode="json"), "affected": sorted(affected_safe(patch)), "diff": lines}

    @app.post("/api/sessions/{session_id}/accept")
    def accept_pending(session_id: str):
        session = _session(app, session_id)
        try:
            names = accept(session)
        except EditorError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {**_state(session), "affected": sorted(names)}

    @app.post("/api/sessions/{session_id}/reject")
    def reject_pending(session_id: str):
        session = _session(app, session_id)
        session.pending = None
        return _state(session)

    @app.post("/api/sessions/{session_id}/undo")
    def undo_session(session_id: str):
        session = _session(app, session_id)
        try:
            undo(session)
        except EditorError as exc:
            raise HTTPException(422, str(exc)) from exc
        return _state(session)

    @app.post("/api/sessions/{session_id}/redo")
    def redo_session(session_id: str):
        session = _session(app, session_id)
        try:
            redo(session)
        except EditorError as exc:
            raise HTTPException(422, str(exc)) from exc
        return _state(session)

    @app.post("/api/sessions/{session_id}/lock")
    def lock(session_id: str, body: LockBody):
        session = _session(app, session_id)
        try:
            revised = lock_track(session.episode, body.shot_id, body.track_id, body.properties)
        except EditorError as exc:
            raise HTTPException(422, str(exc)) from exc
        snapshot_push(session, revised)
        return _state(session)

    return app


def default_router() -> ProviderRouter:
    router = build_default_router()
    if os.environ.get("CUERVO_EDITOR_STUB") == "1":
        router.register(DevStub(), steps={"ir_patch": ("devstub", "claude", "gemini", "cursor")})
    return router


def _session(app: FastAPI, session_id: str):
    try:
        return app.state.store.get(session_id)
    except EditorError as exc:
        raise HTTPException(404, str(exc)) from exc


def _state(session) -> dict:
    return {
        "episode": summarize(session.episode),
        "snapshots": len(session.past),
        "can_redo": bool(session.future),
        "pending": session.pending is not None,
    }


def affected_safe(patch: EditPatch) -> set[str]:
    from cuervo_edit.edits import affected

    return affected(patch)


app = create_app()
