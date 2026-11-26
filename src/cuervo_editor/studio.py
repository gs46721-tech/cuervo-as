"""The production side of the editor: start an episode from a script, check it, and render it.

Long work runs as a job. A job has a log in plain words that the page shows
while it runs, and a result when it ends.
"""

from __future__ import annotations

import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from cuervo_ir.providers.router import ModelRequest, ProviderError
from cuervo_ir.roles import ROLES
from cuervo_edit import cues as cue_language
from cuervo_editor.store import EditorError, Session
from cuervo_pipeline.polish import check_episode
from cuervo_pipeline.produce import ProduceError, produce
from cuervo_pipeline.run import run_episode
from cuervo_pipeline.screenplay import ScriptError, parse_screenplay, write_script
from cuervo_pipeline.series import SeriesKit
from cuervo_voice.synth import VoiceError, default_synths
from cuervo_world import World


@dataclass
class Job:
    job_id: str
    kind: str
    status: str = "running"  # running, done, failed
    log: list[str] = field(default_factory=list)
    result: dict = field(default_factory=dict)
    error: str | None = None
    started: float = field(default_factory=time.time)

    def say(self, line: str) -> None:
        self.log.append(str(line).strip())
        del self.log[:-200]

    def view(self) -> dict:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "status": self.status,
            "log": self.log,
            "result": self.result,
            "error": self.error,
            "seconds": round(time.time() - self.started, 1),
        }


class StartBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    script: str = Field(min_length=1, max_length=400_000)
    kit: dict


class WriteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    premise: str = Field(min_length=1, max_length=8000)
    kit: dict
    minutes: float = Field(default=5, ge=0.5, le=45)


class RenderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: int = Field(default=1280, ge=320, le=1920)
    height: int = Field(default=720, ge=180, le=1080)


class SceneBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool


# What each pipeline line means to a director.
STAGE_WORDS = {
    "world": "Building the cast and sets",
    "script": "Reading the script",
    "storyboard": "Storyboarding",
    "animation": "Recording voices and animating",
    "polish": "Checking and rendering",
}


def install(app: FastAPI, *, session_of, state_of, background: bool) -> None:
    jobs: dict[str, Job] = {}
    app.state.jobs = jobs

    def start(kind: str, work) -> Job:
        job = Job(job_id=uuid.uuid4().hex[:12], kind=kind)
        jobs[job.job_id] = job

        def run() -> None:
            try:
                job.result = work(job) or {}
                job.status = "done"
            except (ProduceError, ScriptError, EditorError, ProviderError, VoiceError, ValueError) as exc:
                job.status = "failed"
                job.error = _plain(str(exc))
            except Exception as exc:  # A job must always end.
                job.status = "failed"
                job.error = _plain(str(exc)) or exc.__class__.__name__

        if background:
            threading.Thread(target=run, daemon=True, name=f"job-{job.job_id}").start()
        else:
            run()
        return job

    def kit_of(data: dict) -> SeriesKit:
        try:
            return SeriesKit.model_validate(data)
        except ValueError as exc:
            raise HTTPException(422, f"The series file does not load: {_first(exc)}") from exc

    def painters() -> list[tuple[str, str]]:
        roles = app.state.roles
        choice = roles.choices.get("image") if roles is not None else None
        return [(item.provider, item.model) for item in choice.entries] if choice else []

    def build_root() -> Path:
        home = getattr(app.state.store, "_home", None)
        root = (home.parent if home is not None else Path(tempfile.gettempdir()) / "cuervo") / "productions"
        root.mkdir(parents=True, exist_ok=True)
        return root

    @app.get("/api/jobs/{job_id}")
    def read_job(job_id: str):
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "unknown job")
        return job.view()

    @app.post("/api/productions/write")
    def write(body: WriteBody):
        """Draft a screenplay from a premise, through the screenwriting role."""

        kit = kit_of(body.kit)

        def work(job: Job) -> dict:
            job.say(f"Outlining about {body.minutes:g} minutes, then writing it scene by scene.")
            text = write_script(body.premise, kit, body.minutes, app.state.router)
            job.say(f"Wrote {len(text.split())} words.")
            return {"script": text}

        return start("write", work).view()

    @app.post("/api/productions")
    def start_production(body: StartBody):
        """Script and series in, an animated episode open in the editor out."""

        kit = kit_of(body.kit)
        try:
            script = parse_screenplay(body.script, kit)
        except ScriptError as exc:
            raise HTTPException(422, str(exc)) from exc
        out = build_root() / uuid.uuid4().hex[:12]
        out.mkdir(parents=True)
        (out / "script.txt").write_text(body.script, encoding="utf-8")
        (out / "series.json").write_text(kit.model_dump_json(indent=2), encoding="utf-8")

        def work(job: Job) -> dict:
            job.say(f"{len(script.scenes)} scenes and {len(script.lines())} lines to animate.")

            def log(line: str) -> None:
                word = str(line).split(" ", 1)[0]
                job.say(STAGE_WORDS[word] + "…" if word in STAGE_WORDS and not str(line).startswith(" ") else _plain(str(line)))

            made = produce(body.script, kit, out, router=app.state.router, through="animation", painters=painters(), log=log)
            assert made.episode is not None
            _session_id, session = app.state.store.open(made.episode, kit.poses)
            session.takes_dir = str(out / "takes")
            session.world_dir = str(out / "world")
            session.build_dir = str(out)
            app.state.store.save(session)
            job.say("Ready. Opening the episode.")
            return {"session_id": session.session_id}

        return start("production", work).view()

    @app.get("/api/sessions/{session_id}/notes")
    def notes(session_id: str):
        """What a careful watch of the cut would catch, by shot."""

        session: Session = session_of(session_id)
        episode = session.episode
        found = check_episode(episode, Path(session.takes_dir) if session.takes_dir else None)
        numbers = cue_language.names(episode)["shots"]
        rows = [
            {"shot_id": note.shot_id, "shot": f"Shot {numbers[note.shot_id]}" if note.shot_id in numbers else "", "severity": note.severity, "text": note.text}
            for note in found
        ]
        if session.world_dir:
            for entry in World(Path(session.world_dir)).view():
                if entry["status"] != "approved":
                    rows.append({"shot_id": "", "shot": "World", "severity": "look", "text": f"The design for {entry['name']} is not approved yet."})
        return {"notes": rows}

    @app.post("/api/sessions/{session_id}/scenes/{scene_id}")
    def approve_scene(session_id: str, scene_id: str, body: SceneBody):
        session: Session = session_of(session_id)
        if not any(scene.scene_id == scene_id for scene in session.episode.scenes):
            raise HTTPException(404, "unknown scene")
        with session.lock:
            if body.approved:
                session.approved_scenes.add(scene_id)
            else:
                session.approved_scenes.discard(scene_id)
            app.state.store.save(session)
        return state_of(session)

    @app.post("/api/sessions/{session_id}/render")
    def render(session_id: str, body: RenderBody | None = None):
        """Render the episode as it stands now. Shots that did not change are not drawn again."""

        session: Session = session_of(session_id)
        size = (body.width, body.height) if body else (1280, 720)
        with session.lock:
            if not session.build_dir:
                session.build_dir = str(build_root() / uuid.uuid4().hex[:12])
                app.state.store.save(session)
            out = Path(session.build_dir)
            episode = session.episode
            poses = session.poses
            takes = Path(session.takes_dir) if session.takes_dir else None
            world = World(Path(session.world_dir)) if session.world_dir else None
        out.mkdir(parents=True, exist_ok=True)

        def work(job: Job) -> dict:
            (out / "episode.json").write_text(episode.model_dump_json(indent=2), encoding="utf-8")
            every = {shot.shot_id for scene in episode.scenes for shot in scene.shots}
            job.say(f"Rendering {len(every)} shots at {size[0]}×{size[1]}.")
            result = run_episode(
                episode,
                out / "shots",
                router=app.state.router,
                approved=every,
                poses=poses,
                takes_dir=takes,
                world=world,
                size=size,
                review=False,
                workers=None if background else 1,
                progress=lambda done, total: job.say(f"Drew {done} of {total} shots that changed."),
            )
            failed = [report for report in result.reports if report.status == "failed"]
            if result.master is None:
                raise EditorError(failed[0].error if failed else "nothing was rendered")
            final = out / "episode.mp4"
            result.master.replace(final)
            reused = sum(1 for report in result.reports if report.status == "cached")
            frames = sum(shot.duration_frames for scene in episode.scenes for shot in scene.shots)
            job.say(f"Done. {reused} shots were reused from the last render.")
            return {"seconds": round(frames / episode.fps, 1), "failed": len(failed), "reused": reused, "shots": len(every)}

        return start("render", work).view()

    @app.get("/api/sessions/{session_id}/master.mp4")
    def master(session_id: str):
        session: Session = session_of(session_id)
        path = Path(session.build_dir) / "episode.mp4" if session.build_dir else None
        if path is None or not path.is_file():
            raise HTTPException(404, "this episode has not been rendered yet")
        name = f"{session.episode.episode_id}.mp4"
        return FileResponse(path, media_type="video/mp4", filename=name, headers={"cache-control": "no-store"})

    @app.post("/api/settings/livecheck")
    def livecheck():
        """One small real request per job, so a person knows their accounts work before a long run.

        It spends a few tokens per model and about three words of speech. It paints nothing.
        """

        def work(job: Job) -> dict:
            rows = []
            router = app.state.router
            for role, spec in ROLES.items():
                if role == "image":
                    continue
                for entry in router.entries(spec["step"]):
                    if not router.usable(entry):
                        continue
                    name = entry.label()
                    began = time.time()
                    try:
                        reply = router.providers[entry.provider].complete(
                            ModelRequest(step=spec["step"], system="Reply with exactly one word: ready", user="Are you there?", model=entry.model)
                        )
                        ok, detail = True, f"{reply.model} answered"
                    except ProviderError as exc:
                        ok, detail = False, _plain(str(exc))
                    rows.append({"job": spec["label"], "who": name, "ok": ok, "detail": detail, "seconds": round(time.time() - began, 1)})
                    job.say(f"{spec['label']}: {name} {'works' if ok else 'failed'}.")
            engine = default_synths().get("elevenlabs")
            if engine is None:
                rows.append({"job": "Voices", "who": "elevenlabs", "ok": False, "detail": "Not connected. Voices use the test tone.", "seconds": 0})
            else:
                from cuervo_ir.credentials import check

                began = time.time()
                listed = check("elevenlabs")
                voices = listed.get("voices") or []
                if not listed["ok"] or not voices:
                    rows.append({"job": "Voices", "who": "elevenlabs", "ok": False, "detail": listed["message"], "seconds": round(time.time() - began, 1)})
                else:
                    try:
                        speech = engine.speak("Testing, one two.", voices[0]["voice_id"])  # type: ignore[attr-defined]
                        timed = "with timing for lip sync" if speech.chars else "but without timing, so lip sync would be estimated"
                        rows.append({"job": "Voices", "who": f"elevenlabs {voices[0]['name']}", "ok": True, "detail": f"Spoke {speech.seconds:.1f} seconds {timed}", "seconds": round(time.time() - began, 1)})
                    except VoiceError as exc:
                        rows.append({"job": "Voices", "who": "elevenlabs", "ok": False, "detail": str(exc), "seconds": round(time.time() - began, 1)})
            if not any(row["ok"] for row in rows if row["job"] != "Voices"):
                job.say("No model account is connected.")
            return {"checks": rows}

        return start("livecheck", work).view()


def _plain(text: str) -> str:
    if "no provider completed" in text:
        return "No model account answered. Connect one in Accounts and models."
    return text.strip()


def _first(exc: Exception) -> str:
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            first = errors()[0]
            where = ".".join(str(part) for part in first.get("loc", ()))
            return f"{where}: {first['msg']}" if where else str(first["msg"])
        except Exception:
            pass
    return str(exc).splitlines()[0]

