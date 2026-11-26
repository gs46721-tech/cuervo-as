import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  type Change,
  type LockProperty,
  type Providers,
  type SessionCard,
  type SessionState,
  type Shot,
  type Turn,
  api,
  exportUrl,
  threadStatus,
} from "./api"
import { Mark, icons } from "./icons"
import { type Command, Palette } from "./Palette"
import { Settings } from "./Settings"
import { Sidebar } from "./Sidebar"
import { Stage } from "./Stage"
import { type Draft, ThreadView } from "./ThreadView"
import { WorldView } from "./World"

type Toast = { text: string; tone: "error" | "info"; key: number }

function readHash(): { sessionId: string | null; threadId: string | null } {
  const [, sessionId, threadId] = window.location.hash.split("/")
  return { sessionId: sessionId || null, threadId: threadId || null }
}

// Below these widths a pane floats over the thread, so it starts closed.
const SIDEBAR_FLOATS = 720
const STAGE_FLOATS = 1080

function stored(key: string, floatsBelow: number): boolean {
  if (window.innerWidth <= floatsBelow) {
    return false
  }
  return localStorage.getItem(key) !== "0"
}

function remember(key: string, open: boolean, floatsBelow: number): void {
  if (window.innerWidth > floatsBelow) {
    localStorage.setItem(key, open ? "1" : "0")
  }
}

export function App() {
  const [cards, setCards] = useState<SessionCard[]>([])
  const [state, setState] = useState<SessionState | null>(null)
  const [threadId, setThreadId] = useState<string | null>(null)
  const [providers, setProviders] = useState<Providers | null>(null)
  const [shotId, setShotId] = useState<string | null>(null)
  const [frame, setFrame] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [previewId, setPreviewId] = useState<string | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(() => stored("cuervo.sidebar", SIDEBAR_FLOATS))
  const [stageOpen, setStageOpen] = useState(() => stored("cuervo.stage", STAGE_FLOATS))
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [worldOpen, setWorldOpen] = useState(false)
  const [dropping, setDropping] = useState(false)
  const [booted, setBooted] = useState(false)
  const [toast, setToast] = useState<Toast | null>(null)
  const picker = useRef<HTMLInputElement>(null)

  const say = useCallback((text: string, tone: Toast["tone"] = "error") => {
    setToast({ text, tone, key: Date.now() })
  }, [])
  useEffect(() => {
    if (!toast) {
      return
    }
    const timer = window.setTimeout(() => setToast(null), toast.tone === "error" ? 7000 : 3000)
    return () => window.clearTimeout(timer)
  }, [toast])

  const refreshCards = useCallback(() => {
    api.sessions().then((body) => setCards(body.sessions)).catch(() => undefined)
  }, [])

  /** Run one API call that returns the project, and show whatever it says went wrong. */
  const run = useCallback(
    async (work: Promise<SessionState>): Promise<SessionState | null> => {
      try {
        const next = await work
        setState(next)
        refreshCards()
        return next
      } catch (error) {
        say(error instanceof Error ? error.message : "That did not work.")
        return null
      }
    },
    [refreshCards, say],
  )

  const showProject = useCallback(
    async (sessionId: string, wantedThread: string | null = null) => {
      const next = await run(api.read(sessionId))
      if (!next) {
        return
      }
      setPlaying(false)
      setPreviewId(null)
      setFrame(0)
      setShotId(next.episode.shots[0]?.shot_id ?? null)
      const fallback = next.threads[next.threads.length - 1]?.thread_id ?? null
      setThreadId(wantedThread && next.threads.some((item) => item.thread_id === wantedThread) ? wantedThread : fallback)
    },
    [run],
  )

  // Boot: providers, the project list, then whichever project the address names.
  useEffect(() => {
    api.providers().then(setProviders).catch(() => undefined)
    api
      .sessions()
      .then(async (body) => {
        setCards(body.sessions)
        const wanted = readHash()
        const target = body.sessions.find((card) => card.session_id === wanted.sessionId) ?? body.sessions[0]
        if (target) {
          await showProject(target.session_id, wanted.threadId)
        }
      })
      .catch((error: Error) => say(error.message))
      .finally(() => setBooted(true))
  }, [showProject, say])

  useEffect(() => {
    const next = state ? `#/${state.session_id}/${threadId ?? ""}` : ""
    if (window.location.hash !== next) {
      window.history.replaceState(null, "", next || window.location.pathname)
    }
  }, [state?.session_id, threadId])

  useEffect(() => remember("cuervo.sidebar", sidebarOpen, SIDEBAR_FLOATS), [sidebarOpen])
  useEffect(() => remember("cuervo.stage", stageOpen, STAGE_FLOATS), [stageOpen])
  const tuckSidebar = () => {
    if (window.innerWidth <= SIDEBAR_FLOATS) {
      setSidebarOpen(false)
    }
  }

  // While a turn runs, poll so the work log fills in as the agent goes.
  const sessionId = state?.session_id ?? null
  const working = state?.threads.some((thread) => threadStatus(thread) === "running") ?? false
  useEffect(() => {
    if (!sessionId || !working) {
      return
    }
    const timer = window.setInterval(() => {
      api
        .read(sessionId)
        .then((next) => setState((current) => (current?.session_id === next.session_id ? next : current)))
        .catch(() => undefined)
    }, 450)
    return () => {
      window.clearInterval(timer)
      refreshCards()
    }
  }, [sessionId, working, refreshCards])

  const episode = state?.episode ?? null
  const shot: Shot | null = episode?.shots.find((item) => item.shot_id === shotId) ?? episode?.shots[0] ?? null
  const thread = state?.threads.find((item) => item.thread_id === threadId) ?? null
  const preview: Change | null = useMemo(() => {
    if (!state || !previewId) {
      return null
    }
    for (const item of state.threads) {
      for (const turn of item.turns) {
        const found = turn.changes.find((change) => change.change_id === previewId)
        if (found) {
          return found
        }
      }
    }
    return null
  }, [state, previewId])

  // When a turn lands, put its first changed shot on the stage.
  const seen = useRef<string | null>(null)
  const expecting = useRef(false)
  const lastTurn = thread?.turns[thread.turns.length - 1]
  useEffect(() => {
    if (!lastTurn || lastTurn.status === "running" || seen.current === lastTurn.turn_id) {
      return
    }
    const fresh = expecting.current || seen.current === `running:${lastTurn.turn_id}`
    expecting.current = false
    seen.current = lastTurn.turn_id
    if (fresh && lastTurn.changes[0]) {
      setShotId(lastTurn.changes[0].shot_id)
      setFrame(0)
    }
  }, [lastTurn])
  useEffect(() => {
    if (lastTurn?.status === "running") {
      seen.current = `running:${lastTurn.turn_id}`
    }
  }, [lastTurn])

  const seek = useCallback((nextShot: string, nextFrame: number) => {
    setShotId((current) => {
      if (current !== nextShot) {
        setPreviewId(null)
      }
      return nextShot
    })
    setFrame(nextFrame)
  }, [])

  const openFiles = useCallback(
    async (files: FileList | File[]) => {
      let episodeJson: unknown = null
      let poses: unknown = null
      for (const file of Array.from(files)) {
        let parsed: unknown
        try {
          parsed = JSON.parse(await file.text())
        } catch {
          say(`${file.name} is not JSON.`)
          return
        }
        if (parsed && typeof parsed === "object" && (parsed as { kind?: string }).kind === "episode") {
          episodeJson = parsed
        } else {
          poses = parsed
        }
      }
      if (!episodeJson) {
        say('None of those files is an episode. An episode JSON has "kind": "episode".')
        return
      }
      const next = await run(api.open(episodeJson, poses))
      if (next) {
        setThreadId(null)
        setShotId(next.episode.shots[0]?.shot_id ?? null)
        setFrame(0)
        setPlaying(false)
        setPreviewId(null)
        say(poses ? `Opened ${next.episode.title} with its pose table.` : `Opened ${next.episode.title}.`, "info")
      }
    },
    [run, say],
  )

  const send = useCallback(
    async (draft: Draft) => {
      if (!state) {
        return
      }
      let target = threadId
      if (!target) {
        try {
          const created = await api.newThread(state.session_id)
          target = created.thread_id
          setThreadId(target)
        } catch (error) {
          say(error instanceof Error ? error.message : "Could not start a thread.")
          return
        }
      }
      expecting.current = true
      await run(api.turn(state.session_id, target, { ...draft, focus_shot_id: shot?.shot_id ?? null }))
    },
    [state, threadId, shot?.shot_id, run, say],
  )

  const onTurn = useCallback(
    (turn: Turn, action: "stop" | "accept" | "reject" | "revert") => {
      if (state) {
        void run(api.turnAction(state.session_id, turn.turn_id, action))
      }
    },
    [state, run],
  )
  const onChange = useCallback(
    (change: Change, action: "accept" | "reject") => {
      if (!state) {
        return
      }
      if (previewId === change.change_id) {
        setPreviewId(null)
        setPlaying(false)
      }
      void run(api.changeAction(state.session_id, change.change_id, action))
    },
    [state, previewId, run],
  )
  const onPreview = useCallback(
    (change: Change) => {
      if (previewId === change.change_id) {
        setPreviewId(null)
        setPlaying(false)
        return
      }
      setStageOpen(true)
      setShotId(change.shot_id)
      setFrame(0)
      setPreviewId(change.change_id)
      setPlaying(true)
    },
    [previewId],
  )
  const history = useCallback(
    (action: "undo" | "redo") => {
      if (state && (action === "undo" ? state.undo : state.redo)) {
        void run(api.history(state.session_id, action))
      }
    },
    [state, run],
  )
  const onLock = useCallback(
    (target: Shot, trackId: string, properties: LockProperty[]) => {
      if (state) {
        void run(api.lock(state.session_id, target.shot_id, trackId, properties))
      }
    },
    [state, run],
  )
  const onCameraLock = useCallback(
    async (target: Shot) => {
      if (!state) {
        return
      }
      const rows = [...target.tracks, ...target.lines]
      if (target.camera_locked) {
        // The camera lock rides on a track, so clear it from every track that carries it.
        for (const row of rows.filter((item) => item.locks.includes("camera"))) {
          await run(api.lock(state.session_id, target.shot_id, row.track_id, row.locks.filter((item) => item !== "camera")))
        }
      } else if (rows[0]) {
        await run(api.lock(state.session_id, target.shot_id, rows[0].track_id, [...rows[0].locks, "camera"]))
      } else {
        say("There is nothing in this shot to pin the camera to.")
      }
    },
    [state, run, say],
  )

  const toggleTheme = useCallback(() => {
    const root = document.documentElement
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches
    root.dataset.theme = dark ? "light" : "dark"
    localStorage.setItem("cuervo.theme", root.dataset.theme)
  }, [])

  const deleteProject = useCallback(
    async (card: SessionCard) => {
      if (!window.confirm(`Close "${card.title}" and delete its threads and history? Download the episode first if you need the edits.`)) {
        return
      }
      try {
        await api.remove(card.session_id)
      } catch (error) {
        say(error instanceof Error ? error.message : "Could not close that project.")
        return
      }
      if (state?.session_id === card.session_id) {
        setState(null)
        setThreadId(null)
        setShotId(null)
      }
      refreshCards()
    },
    [state, refreshCards, say],
  )

  // Keyboard. Typing in a field keeps every key except the palette shortcut.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const mod = event.metaKey || event.ctrlKey
      const key = event.key.toLowerCase()
      if (mod && key === "k") {
        event.preventDefault()
        setPaletteOpen((open) => !open)
        return
      }
      if (mod && key === "b") {
        event.preventDefault()
        setSidebarOpen((open) => !open)
        return
      }
      if (mod && key === "j") {
        event.preventDefault()
        setStageOpen((open) => !open)
        return
      }
      const target = event.target as HTMLElement
      if (target.closest("input, textarea, select, [contenteditable]") || paletteOpen) {
        return
      }
      if (mod && key === "z") {
        event.preventDefault()
        history(event.shiftKey ? "redo" : "undo")
      } else if (event.key === " " && shot && !target.closest("button, a")) {
        event.preventDefault()
        setPlaying((value) => !value)
      } else if ((event.key === "ArrowLeft" || event.key === "ArrowRight") && shot) {
        event.preventDefault()
        setPlaying(false)
        setFrame((value) => Math.max(0, Math.min(shot.duration_frames - 1, value + (event.key === "ArrowLeft" ? -1 : 1))))
      } else if (event.key === "Escape" && previewId) {
        setPreviewId(null)
        setPlaying(false)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [history, shot, paletteOpen, previewId])

  const commands: Command[] = useMemo(() => {
    const list: Command[] = [
      { id: "open", group: "Project", label: "Open episode…", run: () => picker.current?.click() },
      { id: "sidebar", group: "View", label: "Toggle sidebar", hint: "⌘B", run: () => setSidebarOpen((open) => !open) },
      { id: "stage", group: "View", label: "Toggle stage", hint: "⌘J", run: () => setStageOpen((open) => !open) },
      { id: "theme", group: "View", label: "Switch between dark and light", run: toggleTheme },
      { id: "keys", group: "Project", label: "Accounts and keys…", run: () => setSettingsOpen(true) },
    ]
    if (!state) {
      return list
    }
    list.unshift(
      { id: "new", group: "Project", label: "New thread", run: () => setThreadId(null) },
      { id: "world", group: "Project", label: "World: cast and sets", run: () => setWorldOpen(true) },
      { id: "export", group: "Project", label: "Download episode JSON", run: () => window.location.assign(exportUrl(state.session_id)) },
      { id: "undo", group: "Project", label: "Undo", hint: "⌘Z", run: () => history("undo") },
      { id: "redo", group: "Project", label: "Redo", hint: "⇧⌘Z", run: () => history("redo") },
      { id: "play", group: "Project", label: playing ? "Pause" : "Play", hint: "Space", run: () => setPlaying((value) => !value) },
    )
    for (const item of state.episode.shots) {
      list.push({
        id: `shot:${item.shot_id}`,
        group: "Shots",
        label: `${item.label} · ${item.size}${item.lines[0] ? ` · “${item.lines[0].text}”` : ""}`,
        run: () => {
          setStageOpen(true)
          seek(item.shot_id, 0)
        },
      })
    }
    for (const item of state.threads) {
      list.push({ id: `thread:${item.thread_id}`, group: "Threads", label: item.title, run: () => setThreadId(item.thread_id) })
    }
    for (const card of cards) {
      if (card.session_id !== state.session_id) {
        list.push({ id: `project:${card.session_id}`, group: "Projects", label: card.title, run: () => void showProject(card.session_id) })
      }
    }
    return list
  }, [state, cards, playing, history, seek, showProject, toggleTheme])

  return (
    <div
      className={`app${sidebarOpen ? "" : " no-sidebar"}${stageOpen && state ? "" : " no-stage"}`}
      onDragOver={(event) => {
        if (event.dataTransfer.types.includes("Files")) {
          event.preventDefault()
          setDropping(true)
        }
      }}
      onDragLeave={(event) => {
        if (event.currentTarget === event.target) {
          setDropping(false)
        }
      }}
      onDrop={(event) => {
        event.preventDefault()
        setDropping(false)
        if (event.dataTransfer.files.length) {
          void openFiles(event.dataTransfer.files)
        }
      }}
    >
      <input
        ref={picker}
        type="file"
        accept="application/json,.json"
        multiple
        hidden
        aria-label="Episode and pose table files"
        onChange={(event) => {
          if (event.target.files?.length) {
            void openFiles(event.target.files)
          }
          event.target.value = ""
        }}
      />

      {sidebarOpen ? (
        <Sidebar
          cards={cards}
          state={state}
          threadId={threadId}
          providers={providers}
          onProject={(id) => {
            tuckSidebar()
            void showProject(id)
          }}
          onThread={(id) => {
            tuckSidebar()
            setThreadId(id)
          }}
          onOpen={() => picker.current?.click()}
          onPalette={() => setPaletteOpen(true)}
          onTheme={toggleTheme}
          onSettings={() => setSettingsOpen(true)}
          onWorld={() => setWorldOpen(true)}
          onRename={(item, title) => state && void run(api.renameThread(state.session_id, item.thread_id, title))}
          onDeleteThread={(item) => {
            if (state && window.confirm(`Delete the thread "${item.title}"? Changes it already applied stay in the episode.`)) {
              if (item.thread_id === threadId) {
                setThreadId(null)
              }
              void run(api.removeThread(state.session_id, item.thread_id))
            }
          }}
          onDeleteProject={(card) => void deleteProject(card)}
        />
      ) : null}

      <div className="center">
        <header className="pane-head">
          <div className="row">
            <button className="icon-btn" title="Toggle sidebar (⌘B)" aria-pressed={sidebarOpen} onClick={() => setSidebarOpen(!sidebarOpen)}>
              {icons.sidebar}
            </button>
            <div className="pane-title">
              <strong className="clip">{state ? (thread?.title ?? "New thread") : "Cuervo"}</strong>
              {state ? <span className="muted clip">{state.episode.title}</span> : null}
            </div>
          </div>
          {state ? (
            <button className="btn small ghost" title="Toggle stage (⌘J)" aria-pressed={stageOpen} onClick={() => setStageOpen(!stageOpen)}>
              {icons.stage} Stage
            </button>
          ) : null}
        </header>

        {state ? (
          <ThreadView
            state={state}
            thread={thread}
            providers={providers}
            focus={shot}
            previewId={previewId}
            onSend={(draft) => void send(draft)}
            onTurn={onTurn}
            onChange={onChange}
            onPreview={onPreview}
            onSettings={() => setSettingsOpen(true)}
            onJump={(id) => {
              setStageOpen(true)
              seek(id, 0)
            }}
          />
        ) : booted ? (
          <Welcome onOpen={() => picker.current?.click()} />
        ) : null}
      </div>

      {state && shot && stageOpen ? (
        <Stage
          state={state}
          shot={shot}
          frame={frame}
          playing={playing}
          preview={preview}
          onSeek={seek}
          onPlaying={setPlaying}
          onClearPreview={() => {
            setPreviewId(null)
            setPlaying(false)
          }}
          onReview={onChange}
          onLock={onLock}
          onCameraLock={(target) => void onCameraLock(target)}
          onHistory={history}
          onClose={() => setStageOpen(false)}
        />
      ) : null}

      {worldOpen && state ? <WorldView state={state} onClose={() => setWorldOpen(false)} onChanged={() => undefined} /> : null}
      {settingsOpen ? (
        <Settings
          onClose={() => setSettingsOpen(false)}
          onChanged={() => {
            api.providers().then(setProviders).catch(() => undefined)
          }}
        />
      ) : null}
      {paletteOpen ? <Palette commands={commands} onClose={() => setPaletteOpen(false)} /> : null}
      {dropping ? (
        <div className="dropzone">
          <div>
            {icons.folder}
            <strong>Drop an episode JSON</strong>
            <span>Drop its pose table with it if the series has one.</span>
          </div>
        </div>
      ) : null}
      {toast ? (
        <div className={`toast ${toast.tone}`} role={toast.tone === "error" ? "alert" : "status"} key={toast.key}>
          <span>{toast.text}</span>
          <button className="icon-btn" aria-label="Dismiss" onClick={() => setToast(null)}>
            {icons.close}
          </button>
        </div>
      ) : null}
    </div>
  )
}

function Welcome({ onOpen }: { onOpen: () => void }) {
  return (
    <main className="welcome">
      <div className="welcome-card">
        <span className="welcome-mark">
          <Mark size={36} />
        </span>
        <h1>Direct your episode in plain words</h1>
        <p className="muted">
          Open an episode and tell the agent what should change. It drafts typed edits to timing, poses, and camera. You
          see each one as a diff and a frame before it is written.
        </p>
        <button className="btn primary" onClick={onOpen}>
          {icons.folder} Open episode JSON
        </button>
        <p className="muted small">
          Or drop the file anywhere on this page. If the series has a pose table, select it together with the episode.
        </p>
        <ol className="how">
          <li>
            <strong>Direct</strong>
            <span>Type a note. Pin it to shots with @, or let the agent choose.</span>
          </li>
          <li>
            <strong>Review</strong>
            <span>Each change shows what moves and how the frame looks after.</span>
          </li>
          <li>
            <strong>Keep or revert</strong>
            <span>Accept, undo, or roll a whole turn back. Lock what must not move.</span>
          </li>
        </ol>
        <p className="muted small mono">python3 -m cuervo_editor path/to/episode.json</p>
      </div>
    </main>
  )
}
