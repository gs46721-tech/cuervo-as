import { useEffect, useRef, useState } from "react"
import { type Job, type SessionState, type Shot, api, frameUrl, masterUrl } from "./api"
import { Spinner, icons } from "./icons"

/** Follow a long job: its log while it runs, and its result when it ends. */
export function useJob(): { job: Job | null; start: (begin: Promise<Job>) => void; clear: () => void } {
  const [job, setJob] = useState<Job | null>(null)
  const running = job?.status === "running" ? job.job_id : null
  useEffect(() => {
    if (!running) {
      return
    }
    const timer = window.setInterval(() => {
      api.job(running).then(setJob).catch(() => undefined)
    }, 700)
    return () => window.clearInterval(timer)
  }, [running])
  return {
    job,
    start: (begin) => {
      begin.then(setJob).catch((reason: Error) =>
        setJob({ job_id: "", kind: "", status: "failed", log: [], result: {}, error: reason.message, seconds: 0 }),
      )
    },
    clear: () => setJob(null),
  }
}

function JobLog({ job }: { job: Job }) {
  const end = useRef<HTMLLIElement>(null)
  useEffect(() => {
    // Newer browsers return a promise from scrollIntoView, and an effect must not return one.
    void end.current?.scrollIntoView({ block: "nearest" })
  }, [job.log.length])
  return (
    <div className="joblog" role="status">
      <ol>
        {job.log.map((line, index) => (
          <li key={index}>{line}</li>
        ))}
        <li ref={end} className="joblog-now">
          {job.status === "running" ? (
            <>
              <Spinner /> Working… {Math.round(job.seconds)} s
            </>
          ) : job.status === "failed" ? (
            <span className="joblog-error">{job.error}</span>
          ) : null}
        </li>
      </ol>
    </div>
  )
}

function Dialog({ title, sub, wide, onClose, children }: { title: string; sub?: string; wide?: boolean; onClose: () => void; children: React.ReactNode }) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [onClose])
  return (
    <div className="scrim" onMouseDown={onClose}>
      <div className={wide ? "settings world" : "settings"} role="dialog" aria-label={title} onMouseDown={(event) => event.stopPropagation()}>
        <header className="pane-head">
          <div className="pane-title">
            <strong>{title}</strong>
            {sub ? <span className="muted">{sub}</span> : null}
          </div>
          <button className="icon-btn" aria-label="Close" onClick={onClose}>
            {icons.close}
          </button>
        </header>
        <div className="settings-body">{children}</div>
      </div>
    </div>
  )
}

type Kit = { title?: string; characters?: { display_name: string }[]; sets?: { display_name: string }[] }

/** Script and series in, an animated episode out. */
export function NewEpisode({ onClose, onOpened }: { onClose: () => void; onOpened: (sessionId: string) => void }) {
  const [kit, setKit] = useState<Kit | null>(() => {
    try {
      return JSON.parse(localStorage.getItem("cuervo.kit") ?? "null") as Kit | null
    } catch {
      return null
    }
  })
  const [script, setScript] = useState("")
  const [premise, setPremise] = useState("")
  const [minutes, setMinutes] = useState(5)
  const [mode, setMode] = useState<"paste" | "write">("paste")
  const [error, setError] = useState<string | null>(null)
  const build = useJob()
  const writing = useJob()

  useEffect(() => {
    const sessionId = build.job?.status === "done" ? (build.job.result.session_id as string | undefined) : undefined
    if (sessionId) {
      onOpened(sessionId)
    }
  }, [build.job, onOpened])
  useEffect(() => {
    if (writing.job?.status === "done" && typeof writing.job.result.script === "string") {
      setScript(writing.job.result.script)
      setMode("paste")
      writing.clear()
    }
  }, [writing])

  const readKit = async (file: File | undefined) => {
    if (!file) {
      return
    }
    try {
      const parsed = JSON.parse(await file.text()) as Kit
      if (!Array.isArray(parsed.characters) || !Array.isArray(parsed.sets)) {
        throw new Error("That file has no cast or sets, so it is not a series file.")
      }
      setKit(parsed)
      setError(null)
      try {
        localStorage.setItem("cuervo.kit", JSON.stringify(parsed))
      } catch {
        // Too large to remember. It still works for this episode.
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "That file could not be read.")
    }
  }

  const busy = build.job?.status === "running" || writing.job?.status === "running"
  const cast = kit?.characters?.map((item) => item.display_name.split(" ")[0]) ?? []

  return (
    <Dialog title="New episode" sub="from a script" onClose={onClose}>
      <section className="service">
        <div className="service-head">
          <div>
            <strong>1. The series</strong>
            <span className="muted">
              {kit
                ? `${kit.title ?? "Untitled"} · ${cast.join(", ")} · ${kit.sets?.map((item) => item.display_name).join(", ")}`
                : "The series file holds the cast, their voices and looks, and the sets."}
            </span>
          </div>
          <label className="btn small">
            {kit ? "Change" : "Choose series file"}
            <input type="file" accept="application/json,.json" hidden onChange={(event) => void readKit(event.target.files?.[0])} />
          </label>
        </div>
      </section>

      <section className="service">
        <div className="service-head">
          <div>
            <strong>2. The script</strong>
            <span className="muted">Scene headings, a speaker's name in capitals on its own line, then what they say.</span>
          </div>
          <div className="segmented" role="group" aria-label="Where the script comes from">
            <button type="button" aria-pressed={mode === "paste"} onClick={() => setMode("paste")}>
              I have one
            </button>
            <button type="button" aria-pressed={mode === "write"} onClick={() => setMode("write")}>
              Write it for me
            </button>
          </div>
        </div>
        {mode === "paste" ? (
          <>
            <textarea
              className="script-box"
              value={script}
              aria-label="Script"
              spellCheck={false}
              placeholder={`INT. ${(kit?.sets?.[0]?.display_name ?? "LIVING ROOM").toUpperCase()} - DAY\n\n${(cast[0] ?? "ADA").toUpperCase()}\nYou said five minutes.\n\n${(cast[1] ?? "BO").toUpperCase()}\n(dry)\nI said five minutes of quiet.`}
              onChange={(event) => setScript(event.target.value)}
            />
            <label className="link">
              Load a text file
              <input
                type="file"
                accept=".txt,.fountain,.md,text/plain"
                hidden
                onChange={(event) => {
                  void event.target.files?.[0]?.text().then(setScript)
                }}
              />
            </label>
          </>
        ) : (
          <>
            <textarea
              className="script-box short"
              value={premise}
              aria-label="Premise"
              placeholder="What happens in this episode? A few sentences is enough."
              onChange={(event) => setPremise(event.target.value)}
            />
            <div className="service-foot">
              <label className="muted">
                About{" "}
                <input className="minutes" type="number" min={1} max={45} value={minutes} onChange={(event) => setMinutes(Number(event.target.value) || 5)} /> minutes
              </label>
              <button
                type="button"
                className="btn small primary"
                disabled={!kit || !premise.trim() || busy}
                onClick={() => writing.start(api.writeScript(premise, kit, minutes))}
              >
                Write the script
              </button>
            </div>
            {writing.job ? <JobLog job={writing.job} /> : null}
          </>
        )}
      </section>

      {error ? <p className="note error">{error}</p> : null}
      {build.job ? <JobLog job={build.job} /> : null}
      <div className="service-foot">
        <button
          className="btn primary"
          disabled={!kit || !script.trim() || busy || mode !== "paste"}
          onClick={() => build.start(api.startProduction(script, kit))}
        >
          {build.job?.status === "running" ? <Spinner /> : null} Make the episode
        </button>
        <span className="muted">Builds the cast and sets, storyboards it, records the voices, and animates it.</span>
      </div>
    </Dialog>
  )
}

function boardFrame(shot: Shot): number {
  const line = shot.lines[0]
  return line ? Math.floor((line.start_frame + line.end_frame) / 2) : Math.floor(shot.duration_frames / 2)
}

/** Every shot of every scene, as panels. The director signs off scene by scene. */
export function Storyboard({
  state,
  current,
  onClose,
  onShot,
  onState,
}: {
  state: SessionState
  current: Shot
  onClose: () => void
  onShot: (shotId: string) => void
  onState: (state: SessionState) => void
}) {
  const episode = state.episode
  const [open, setOpen] = useState<string>(current.scene_id)
  const approved = new Set(state.approved_scenes)
  return (
    <Dialog title="Storyboard" sub={`${approved.size} of ${episode.scenes.length} scenes approved`} wide onClose={onClose}>
      {episode.scenes.map((scene, index) => {
        const shots = episode.shots.filter((item) => item.scene_id === scene.scene_id)
        const isOpen = open === scene.scene_id
        const done = approved.has(scene.scene_id)
        return (
          <section key={scene.scene_id} className="board-scene">
            <header>
              <button className="board-title" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? "" : scene.scene_id)}>
                <span className={isOpen ? "caret open" : "caret"}>{icons.chevron}</span>
                <span>
                  <strong>
                    Scene {index + 1} · {scene.title}
                  </strong>
                  <small className="muted">
                    {shots.length} shots · {(scene.duration_frames / episode.fps).toFixed(0)} seconds · {scene.objective}
                  </small>
                </span>
              </button>
              <button
                className={done ? "btn small ghost" : "btn small primary"}
                onClick={() => void api.approveScene(state.session_id, scene.scene_id, !done).then(onState)}
              >
                {done ? "Approved · reopen" : "Approve scene"}
              </button>
            </header>
            {isOpen ? (
              <div className="board-grid">
                {shots.map((shot) => (
                  <button
                    key={shot.shot_id}
                    className={shot.shot_id === current.shot_id ? "board-panel current" : "board-panel"}
                    title="Show this shot on the stage"
                    onClick={() => {
                      onShot(shot.shot_id)
                      onClose()
                    }}
                  >
                    <img src={frameUrl(state, shot.shot_id, boardFrame(shot))} alt={`${shot.label}, ${shot.size}`} loading="lazy" />
                    <span className="board-meta">
                      <strong>{shot.label}</strong> · {shot.size} · {(shot.duration_frames / episode.fps).toFixed(1)} s
                    </span>
                    <span className="board-line">{shot.lines[0] ? `${shot.lines[0].speaker}: “${shot.lines[0].text}”` : shot.framing}</span>
                  </button>
                ))}
              </div>
            ) : null}
          </section>
        )
      })}
    </Dialog>
  )
}

const SIZES: [string, number, number][] = [
  ["Preview · 640 × 360", 640, 360],
  ["HD · 1280 × 720", 1280, 720],
  ["Full HD · 1920 × 1080", 1920, 1080],
]

/** Render the cut as it stands and watch it. */
export function Render({ state, onClose, onState }: { state: SessionState; onClose: () => void; onState: () => void }) {
  const [size, setSize] = useState(1)
  const [stamp, setStamp] = useState(0)
  const render = useJob()
  const status = render.job?.status
  useEffect(() => {
    if (status === "done") {
      setStamp(Date.now())
      onState()
    }
  }, [status, onState])
  const ready = state.rendered || status === "done"
  const result = status === "done" ? (render.job?.result as { reused?: number; shots?: number; failed?: number }) : null

  return (
    <Dialog title="Render" sub={state.episode.title} onClose={onClose}>
      <div className="service-foot">
        <label className="select boxed">
          <select aria-label="Picture size" value={size} onChange={(event) => setSize(Number(event.target.value))}>
            {SIZES.map(([label], index) => (
              <option key={label} value={index}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <button
          className="btn primary"
          disabled={status === "running"}
          onClick={() => render.start(api.render(state.session_id, SIZES[size][1], SIZES[size][2]))}
        >
          {status === "running" ? <Spinner /> : icons.film} {ready ? "Render again" : "Render the episode"}
        </button>
        <span className="muted">Only shots that changed are drawn again.</span>
      </div>
      {render.job ? <JobLog job={render.job} /> : null}
      {result?.failed ? <p className="note error">{result.failed} shots could not be drawn and are missing from the video.</p> : null}
      {ready && status !== "running" ? (
        <>
          <video className="master" controls src={`${masterUrl(state.session_id)}?t=${stamp}`} />
          <a className="btn" href={masterUrl(state.session_id)} download>
            {icons.download} Download the video
          </a>
        </>
      ) : null}
    </Dialog>
  )
}
