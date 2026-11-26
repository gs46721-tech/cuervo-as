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
  "Hold the last beat 12 more frames",
  "Cut to a close up on this shot",
  "Set the expression to react on this shot",
  "How long is this episode?",
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
              Give a direction for <strong>{state.episode.title}</strong>. The agent picks the shots, drafts typed
              patches, and shows you each one before anything is written.
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
                <button key={shotId} className="chip mono" onClick={() => props.onJump(shotId)}>
                  @{shotId}
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
            <span className="muted mono spacer">
              {sources.join(", ")}
              {turn.mode === "auto" ? " · auto-apply" : ""}
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
  // A timing change shows at the end of the shot. Anything else reads fine mid-shot.
  const retimed = change.diff.some((row) => row.field === "frames" || row.field === "duration")
  const length = shot?.duration_frames ?? 1
  const sample = retimed ? length - 1 : Math.floor(length / 2)
  const after = retimed ? length + (change.patch?.extend_shot_frames ?? 0) - 1 : sample

  return (
    <article className={`change ${change.state}${change.stale ? " stale" : ""}${previewing ? " previewing" : ""}`}>
      <header>
        <button className="chip mono" onClick={onJump} title="Show this shot on the stage">
          {icons.film} {change.shot_id}
        </button>
        <span className="change-text">{change.instruction}</span>
        <span className={`status ${change.stale ? "stale" : change.state}`}>{label}</span>
      </header>

      {change.diff.length ? (
        <table className="diff">
          <tbody>
            {change.diff.map((row) => (
              <tr key={`${row.target}.${row.field}`}>
                <th className="mono">
                  {row.target}
                  <span className="muted">.{row.field}</span>
                </th>
                <td className="mono old">{row.before}</td>
                <td className="arrow">→</td>
                <td className="mono new">{row.after}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      {change.error ? <p className="note error">{change.error}</p> : null}
      {change.state === "pending" && change.stale ? (
        <p className="note">
          {change.shot_id} changed after this was drafted, so it can no longer be applied.{" "}
          <button className="link" onClick={onRetry}>
            Ask again
          </button>
        </p>
      ) : null}

      {reviewable && shot ? (
        <div className="compare">
          <figure>
            <img src={frameUrl(state, shot.shot_id, sample)} alt={`${shot.shot_id} now, frame ${sample}`} loading="lazy" />
            <figcaption>Now · f{sample}</figcaption>
          </figure>
          <figure>
            <img src={changeFrameUrl(state, change.change_id, after)} alt={`${shot.shot_id} proposed, frame ${after}`} loading="lazy" />
            <figcaption>Proposed · f{after}</figcaption>
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
  const route = first("ir_patch")

  const matches = useMemo(() => {
    if (!menu) {
      return []
    }
    const query = menu.query.toLowerCase()
    return state.episode.shots.filter((item) => !shots.includes(item.shot_id) && item.shot_id.toLowerCase().includes(query)).slice(0, 8)
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
              <span key={shotId} className="chip mono">
                @{shotId}
                <button type="button" aria-label={`Remove ${shotId}`} onClick={() => setShots(shots.filter((item) => item !== shotId))}>
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
                  <span className="mono">@{item.shot_id}</span>
                  <span className="muted">
                    {item.camera_preset} · {item.duration_frames}f
                  </span>
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
            shots.length ? "Describe the change for the pinned shots" : "Describe a change. Type @ to pin it to a shot."
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
              <span className="mono">{focus.shot_id}</span>
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
          {shots.length ? "Pinned shots get this direction as written." : "No shot pinned: the agent decides which shots change."}{" "}
          Enter to send · Shift+Enter for a new line
        </p>
      )}
    </div>
  )
}
