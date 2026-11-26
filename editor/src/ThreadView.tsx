import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import {
  type Change,
  type Providers,
  type SessionState,
  type Shot,
  type Thread,
  type Turn,
  type TurnMode,
  changeFrameUrl,
  frameUrl,
} from "./api"
import { Spinner, icons } from "./icons"

export type Draft = { instruction: string; shot_ids: string[]; provider: string | null; mode: TurnMode }

type Props = {
  state: SessionState
  thread: Thread | null
  providers: Providers | null
  focus: Shot | null
  previewId: string | null
  onSend: (draft: Draft) => void
  onTurn: (turn: Turn, action: "stop" | "accept" | "reject" | "revert") => void
  onChange: (change: Change, action: "accept" | "reject") => void
  onPreview: (change: Change) => void
  onSettings: () => void
  onJump: (shotId: string) => void
}

const STARTERS = [
  "Hold on this shot half a second longer",
  "Go to a close-up here",
  "Give her a shrug on this line",
  "How long does the episode run?",
]

export function ThreadView(props: Props) {
  const { state, thread } = props
  const scroller = useRef<HTMLDivElement>(null)
  const pinned = useRef(true)
  const running = thread?.turns.find((turn) => turn.status === "running") ?? null

  // Follow new work unless the person scrolled up to read.
  useLayoutEffect(() => {
    const node = scroller.current
    if (node && pinned.current) {
      node.scrollTop = node.scrollHeight
    }
  })
  useEffect(() => {
    pinned.current = true
  }, [thread?.thread_id])

  const [seed, setSeed] = useState<{ text: string; shots: string[]; key: number }>({ text: "", shots: [], key: 0 })

  return (
    <main className="thread">
      <div
        className="messages"
        ref={scroller}
        onScroll={(event) => {
          const node = event.currentTarget
          pinned.current = node.scrollHeight - node.scrollTop - node.clientHeight < 80
        }}
      >
        {thread && thread.turns.length ? (
          <div className="column">
            {thread.turns.map((turn) => (
              <TurnBlock key={turn.turn_id} {...props} turn={turn} onRetry={(change) =>
                setSeed({ text: change.instruction, shots: [change.shot_id], key: Date.now() })
              } />
            ))}
          </div>
        ) : (
          <div className="column hero">
            <h1>What should change?</h1>
            <p className="muted">
              Give a note on <strong>{state.episode.title}</strong>, the way you would to an editor in the room. Your
              crew finds the shots, makes the change, and shows it to you before it goes in the cut.
            </p>
            <div className="starters">
              {STARTERS.map((text) => (
                <button key={text} className="starter" onClick={() => setSeed({ text, shots: [], key: Date.now() })}>
                  {text}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      <Composer
        key={thread?.thread_id ?? "draft"}
        state={state}
        providers={props.providers}
        focus={props.focus}
        running={running}
        seed={seed}
        onSend={(draft) => {
          pinned.current = true
          props.onSend(draft)
        }}
        onStop={() => running && props.onTurn(running, "stop")}
        onSettings={props.onSettings}
      />
    </main>
  )
}

function TurnBlock(props: Props & { turn: Turn; onRetry: (change: Change) => void }) {
  const { turn, state } = props
  const waiting = turn.changes.filter((change) => change.state === "pending" && !change.stale)
  const applied = turn.changes.filter((change) => change.state === "applied")
  const seconds = turn.finished_at ? Math.max(0.1, turn.finished_at - turn.created_at) : null
  const sources = [...new Set(turn.changes.map((change) => change.provider).filter(Boolean))]

  return (
    <section className="turn">
      <div className="said">
        <div className="bubble">
          {turn.instruction}
          {turn.shot_ids.length ? (
            <div className="chips">
              {turn.shot_ids.map((shotId) => (
                <button key={shotId} className="chip" onClick={() => props.onJump(shotId)}>
                  {state.episode.shots.find((item) => item.shot_id === shotId)?.label ?? "A removed shot"}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </div>

      <div className="reply">
        {turn.steps.length ? (
          <details className="worklog" open={turn.status === "running" || turn.status === "failed"}>
            <summary>
              {turn.status === "running" ? <Spinner /> : icons.chevron}
              <span>
                {turn.status === "running"
                  ? (turn.steps[turn.steps.length - 1]?.label ?? "Working")
                  : `Worked for ${seconds ? seconds.toFixed(1) : "0"}s · ${turn.steps.length} ${turn.steps.length === 1 ? "step" : "steps"}`}
              </span>
            </summary>
            <ol>
              {turn.steps.map((step, index) => (
                <li key={index} className={`step ${step.status}`}>
                  <span className="step-mark">
                    {step.status === "running" ? <Spinner /> : step.status === "done" ? icons.check : icons.close}
                  </span>
                  <span>
                    {step.label}
                    {step.detail ? <small>{step.detail}</small> : null}
                  </span>
                </li>
              ))}
            </ol>
          </details>
        ) : turn.status === "running" ? (
          <div className="worklog-inline">
            <Spinner /> Starting
          </div>
        ) : null}

        {turn.reply ? <p className="reply-text">{turn.reply}</p> : null}
        {turn.contests.length ? (
          <details className="worklog contest">
            <summary>
              {icons.chevron}
              <span>
                {turn.contests.length === 1 ? "Models competed on this note" : `Models competed ${turn.contests.length} times on this note`}
              </span>
            </summary>
            <ol>
              {turn.contests.map((sentence, index) => (
                <li key={index} className="step">
                  <span>{sentence}</span>
                </li>
              ))}
            </ol>
          </details>
        ) : null}
        {turn.status === "stopped" ? <p className="note">{turn.error ?? "Stopped."}</p> : null}
        {turn.status === "failed" ? (
          <div className="note error">
            <strong>The turn failed.</strong> {turn.error}
            {turn.error?.includes("unavailable") ? (
              <small>
                No model account answered.{" "}
                <button type="button" className="link" onClick={props.onSettings}>
                  Connect one in Accounts and keys
                </button>
              </small>
            ) : null}
          </div>
        ) : null}

        {turn.changes.map((change) => (
          <ChangeCard
            key={change.change_id}
            change={change}
            state={state}
            previewing={props.previewId === change.change_id}
            onAction={(action) => props.onChange(change, action)}
            onPreview={() => props.onPreview(change)}
            onJump={() => props.onJump(change.shot_id)}
            onRetry={() => props.onRetry(change)}
          />
        ))}

        {turn.status !== "running" && (waiting.length > 1 || applied.length || sources.length) ? (
          <footer className="turn-foot">
            {waiting.length > 1 ? (
              <>
                <button className="btn small primary" onClick={() => props.onTurn(turn, "accept")}>
                  Accept all {waiting.length}
                </button>
                <button className="btn small" onClick={() => props.onTurn(turn, "reject")}>
                  Reject all
                </button>
              </>
            ) : null}
            {applied.length ? (
              <button
                className="btn small ghost"
                title="Undo back to the episode as it was before this turn. Redo brings it back."
                onClick={() => props.onTurn(turn, "revert")}
              >
                {icons.revert} Revert to before this turn
              </button>
            ) : null}
            <span className="muted spacer">
              {sources.join(", ")}
              {turn.mode === "auto" ? " · applied right away" : ""}
            </span>
          </footer>
        ) : null}
      </div>
    </section>
  )
}

const STATE_LABEL: Record<Change["state"], string> = {
  pending: "Needs review",
  applied: "Applied",
  undone: "Undone",
  rejected: "Rejected",
  failed: "Failed",
  discarded: "Replaced by later edits",
}

function ChangeCard({
  change,
  state,
  previewing,
  onAction,
  onPreview,
  onJump,
  onRetry,
}: {
  change: Change
  state: SessionState
  previewing: boolean
  onAction: (action: "accept" | "reject") => void
  onPreview: () => void
  onJump: () => void
  onRetry: () => void
}) {
  const shot = state.episode.shots.find((item) => item.shot_id === change.shot_id)
  const reviewable = change.state === "pending" && !change.stale
  const label = change.state === "pending" && change.stale ? "Out of date" : STATE_LABEL[change.state]
  // A change of length shows at the end of the shot. Anything else reads fine mid-shot.
  const length = shot?.duration_frames ?? 1
  const sample = change.grow ? length - 1 : Math.floor(length / 2)
  const after = change.grow ? Math.max(0, length + change.grow - 1) : sample

  return (
    <article className={`change ${change.state}${change.stale ? " stale" : ""}${previewing ? " previewing" : ""}`}>
      <header>
        <button className="chip" onClick={onJump} title="Show this shot on the stage" disabled={!shot}>
          {icons.film} {shot?.label ?? "Removed shot"}
        </button>
        <span className="change-text">{shot ? shot.size : ""}</span>
        <span className={`status ${change.stale ? "stale" : change.state}`}>{label}</span>
      </header>

      {change.summary.length ? (
        <ul className="what">
          {change.summary.map((sentence, index) => (
            <li key={index}>{sentence}</li>
          ))}
        </ul>
      ) : null}

      {change.error ? <p className="note error">{change.error}</p> : null}
      {change.state === "pending" && change.stale ? (
        <p className="note">
          This shot changed after the draft was made, so the draft no longer fits.{" "}
          <button className="link" onClick={onRetry}>
            Ask again
          </button>
        </p>
      ) : null}

      {reviewable && shot ? (
        <div className="compare">
          <figure>
            <img src={frameUrl(state, shot.shot_id, sample)} alt={`${shot.label} as it is now`} loading="lazy" />
            <figcaption>Now</figcaption>
          </figure>
          <figure>
            <img src={changeFrameUrl(state, change.change_id, after)} alt={`${shot.label} with the change`} loading="lazy" />
            <figcaption>Proposed</figcaption>
          </figure>
        </div>
      ) : null}

      {reviewable ? (
        <footer>
          <button className="btn small primary" onClick={() => onAction("accept")}>
            {icons.check} Accept
          </button>
          <button className="btn small" onClick={() => onAction("reject")}>
            Reject
          </button>
          <button className="btn small ghost" aria-pressed={previewing} onClick={onPreview}>
            {icons.eye} {previewing ? "Previewing on stage" : "Preview on stage"}
          </button>
        </footer>
      ) : null}
    </article>
  )
}

function Composer({
  state,
  providers,
  focus,
  running,
  seed,
  onSend,
  onStop,
  onSettings,
}: {
  state: SessionState
  providers: Providers | null
  focus: Shot | null
  running: Turn | null
  seed: { text: string; shots: string[]; key: number }
  onSend: (draft: Draft) => void
  onStop: () => void
  onSettings: () => void
}) {
  const [text, setText] = useState("")
  const [shots, setShots] = useState<string[]>([])
  const [provider, setProvider] = useState<string | null>(() => localStorage.getItem("cuervo.provider"))
  const [mode, setMode] = useState<TurnMode>(() => (localStorage.getItem("cuervo.mode") === "auto" ? "auto" : "review"))
  const [menu, setMenu] = useState<{ query: string; index: number } | null>(null)
  const area = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (seed.key) {
      setText(seed.text)
      setShots(seed.shots)
      area.current?.focus()
    }
  }, [seed])
  useEffect(() => {
    area.current?.focus()
  }, [])
  useLayoutEffect(() => {
    const node = area.current
    if (node) {
      node.style.height = "auto"
      node.style.height = `${Math.min(node.scrollHeight, 200)}px`
    }
  }, [text])

  const known = providers?.providers ?? []
  const usable = known.filter((item) => item.available)
  const chosen = provider && usable.some((item) => item.name === provider) ? provider : null
  const first = (step: string) => providers?.routes[step]?.find((name) => usable.some((item) => item.name === name))
  const route = first("editor_assist")

  const matches = useMemo(() => {
    if (!menu) {
      return []
    }
    // Find a shot by its number, its size, or a word from its first line.
    const query = menu.query.toLowerCase()
    return state.episode.shots
      .filter((item) => !shots.includes(item.shot_id))
      .filter((item) => {
        const text = `${item.number} ${item.label} ${item.size} ${item.lines[0]?.text ?? ""}`.toLowerCase()
        return query === "" ? true : /^\d+$/.test(query) ? String(item.number).startsWith(query) : text.includes(query)
      })
      .slice(0, 8)
  }, [menu, state.episode.shots, shots])

  const pick = (shotId: string) => {
    setShots((current) => (current.includes(shotId) ? current : [...current, shotId]))
    setText((current) => current.replace(/(^|\s)@[\w-]*$/, "$1"))
    setMenu(null)
    area.current?.focus()
  }

  const send = () => {
    const instruction = text.trim()
    if (!instruction || running) {
      return
    }
    onSend({ instruction, shot_ids: shots, provider: chosen, mode })
    setText("")
    setShots([])
    setMenu(null)
  }

  return (
    <div className="composer-wrap">
      <form
        className="composer"
        onSubmit={(event) => {
          event.preventDefault()
          send()
        }}
      >
        {shots.length ? (
          <div className="chips">
            {shots.map((shotId) => (
              <span key={shotId} className="chip">
                {state.episode.shots.find((item) => item.shot_id === shotId)?.label ?? "Shot"}
                <button type="button" aria-label="Unpin this shot" onClick={() => setShots(shots.filter((item) => item !== shotId))}>
                  {icons.close}
                </button>
              </span>
            ))}
          </div>
        ) : null}
        {menu && matches.length ? (
          <ul className="mention" role="listbox">
            {matches.map((item, index) => (
              <li key={item.shot_id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={index === menu.index}
                  className={index === menu.index ? "active" : ""}
                  onMouseDown={(event) => {
                    event.preventDefault()
                    pick(item.shot_id)
                  }}
                >
                  <span>
                    {item.label} · {item.size}
                  </span>
                  <span className="muted clip">{item.lines[0] ? `“${item.lines[0].text}”` : "No dialogue"}</span>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        <textarea
          ref={area}
          rows={1}
          value={text}
          aria-label="Direction"
          placeholder={
            shots.length ? "Give your note for the pinned shots" : "Give a note. Type @ to pin it to a shot."
          }
          onChange={(event) => {
            const value = event.target.value
            setText(value)
            const found = /(^|\s)@([\w-]*)$/.exec(value.slice(0, event.target.selectionStart))
            setMenu(found ? { query: found[2], index: 0 } : null)
          }}
          onKeyDown={(event) => {
            if (menu && matches.length) {
              if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                event.preventDefault()
                const delta = event.key === "ArrowDown" ? 1 : -1
                setMenu({ ...menu, index: (menu.index + delta + matches.length) % matches.length })
                return
              }
              if (event.key === "Enter" || event.key === "Tab") {
                event.preventDefault()
                pick(matches[menu.index].shot_id)
                return
              }
              if (event.key === "Escape") {
                setMenu(null)
                return
              }
            }
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault()
              send()
            }
          }}
        />
        <div className="composer-bar">
          <label className="select" title="Which model provider drafts the patches">
            {icons.bolt}
            <select
              aria-label="Provider"
              value={chosen ?? ""}
              onChange={(event) => {
                const value = event.target.value || null
                setProvider(value)
                if (value) {
                  localStorage.setItem("cuervo.provider", value)
                } else {
                  localStorage.removeItem("cuervo.provider")
                }
              }}
            >
              <option value="">{route ? `Auto · ${route}` : "Auto"}</option>
              {known.map((item) => (
                <option key={item.name} value={item.name} disabled={!item.available}>
                  {item.name}
                  {item.model ? ` · ${item.model}` : ""}
                  {item.available ? "" : " (no key)"}
                </option>
              ))}
            </select>
          </label>
          <div className="segmented" role="group" aria-label="How changes are applied">
            {(
              [
                ["review", "Review", "Every change waits for you to accept it"],
                ["auto", "Auto-apply", "Changes are written right away. Undo and Revert still work."],
              ] as const
            ).map(([value, label, hint]) => (
              <button
                key={value}
                type="button"
                title={hint}
                aria-pressed={mode === value}
                onClick={() => {
                  setMode(value)
                  localStorage.setItem("cuervo.mode", value)
                  area.current?.focus()
                }}
              >
                {label}
              </button>
            ))}
          </div>
          {focus && !shots.includes(focus.shot_id) ? (
            <button type="button" className="btn small ghost" title="Limit this direction to the shot on the stage" onClick={() => pick(focus.shot_id)}>
              {icons.at}
              <span>{focus.label}</span>
            </button>
          ) : null}
          <span className="spacer" />
          {running ? (
            <button type="button" className="send stop" title="Stop this turn" onClick={onStop}>
              {icons.stop}
            </button>
          ) : (
            <button type="submit" className="send" title="Send (Enter)" disabled={!text.trim()}>
              {icons.send}
            </button>
          )}
        </div>
      </form>
      {providers && !usable.length ? (
        <p className="composer-hint warn">
          No model account is connected.{" "}
          <button type="button" className="link" onClick={onSettings}>
            Connect Claude, Gemini, or your own endpoint
          </button>
        </p>
      ) : (
        <p className="composer-hint">
          {shots.length ? "Only the pinned shots will change." : "No shot pinned: your crew works out which shots the note is about."}{" "}
          Enter to send · Shift+Enter for a new line
        </p>
      )}
    </div>
  )
}
