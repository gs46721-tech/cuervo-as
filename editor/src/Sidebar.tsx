import { useState } from "react"
import { type Providers, type SessionCard, type SessionState, type Thread, threadStatus } from "./api"
import { Mark, Spinner, icons } from "./icons"

type Props = {
  cards: SessionCard[]
  state: SessionState | null
  threadId: string | null
  providers: Providers | null
  onProject: (sessionId: string) => void
  onThread: (threadId: string | null) => void
  onOpen: () => void
  onPalette: () => void
  onTheme: () => void
  onSettings: () => void
  onRename: (thread: Thread, title: string) => void
  onDeleteThread: (thread: Thread) => void
  onDeleteProject: (card: SessionCard) => void
}

export function Sidebar(props: Props) {
  const { cards, state } = props
  return (
    <nav className="sidebar" aria-label="Projects">
      <div className="brand">
        <Mark />
        <strong>Cuervo</strong>
        <button className="icon-btn push" title="Search and commands (⌘K)" onClick={props.onPalette}>
          {icons.search}
        </button>
      </div>

      <button className="btn wide" onClick={props.onOpen}>
        {icons.folder} Open episode
      </button>

      <div className="side-scroll">
        <h2>Projects</h2>
        {cards.length === 0 ? <p className="empty-note">No episode is open yet.</p> : null}
        {cards.map((card) => {
          const active = state?.session_id === card.session_id
          return (
            <div key={card.session_id} className={active ? "project active" : "project"}>
              <div className="project-row">
                <button className="project-name" onClick={() => props.onProject(card.session_id)} aria-current={active}>
                  <span className={active ? "caret open" : "caret"}>{icons.chevron}</span>
                  <span className="clip">{card.title}</span>
                  {!active && card.running ? <Spinner /> : null}
                  {!active && !card.running && card.pending ? <i className="pip review" title={`${card.pending} waiting for review`} /> : null}
                </button>
                {active ? (
                  <button className="icon-btn hover-only" title="New thread" onClick={() => props.onThread(null)}>
                    {icons.plus}
                  </button>
                ) : null}
                <button className="icon-btn hover-only" title="Close this project and delete its threads" onClick={() => props.onDeleteProject(card)}>
                  {icons.trash}
                </button>
              </div>
              {active && state ? (
                <ul className="threads">
                  {[...state.threads].reverse().map((thread) => (
                    <ThreadRow key={thread.thread_id} thread={thread} active={thread.thread_id === props.threadId} {...props} />
                  ))}
                  <li>
                    <button className={props.threadId === null ? "thread-row draft active" : "thread-row draft"} onClick={() => props.onThread(null)}>
                      {icons.plus}
                      <span>New thread</span>
                    </button>
                  </li>
                </ul>
              ) : null}
            </div>
          )
        })}
      </div>

      <footer className="side-foot">
        <button className="providers" title="Accounts and keys" onClick={props.onSettings}>
          {props.providers?.providers.map((item) => (
            <span key={item.name} className={item.available ? "provider on" : "provider"} title={item.available ? `${item.name} · ${item.model ?? ""}` : `${item.name}: no key in the API's environment`}>
              <i />
              {item.name}
            </span>
          ))}
          {props.providers && !props.providers.providers.some((item) => item.available) ? <span className="link">Connect an account</span> : null}
        </button>
        <button className="icon-btn" title="Switch between dark and light" onClick={props.onTheme}>
          {icons.sun}
        </button>
      </footer>
    </nav>
  )
}

function ThreadRow({ thread, active, onThread, onRename, onDeleteThread }: Props & { thread: Thread; active: boolean }) {
  const [editing, setEditing] = useState<string | null>(null)
  const status = threadStatus(thread)
  if (editing !== null) {
    const done = (save: boolean) => {
      if (save && editing.trim() && editing.trim() !== thread.title) {
        onRename(thread, editing.trim())
      }
      setEditing(null)
    }
    return (
      <li>
        <input
          className="thread-edit"
          autoFocus
          value={editing}
          aria-label="Thread title"
          onChange={(event) => setEditing(event.target.value)}
          onBlur={() => done(true)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              done(true)
            } else if (event.key === "Escape") {
              done(false)
            }
          }}
        />
      </li>
    )
  }
  return (
    <li className="thread-item">
      <button
        className={active ? "thread-row active" : "thread-row"}
        onClick={() => onThread(thread.thread_id)}
        onDoubleClick={() => setEditing(thread.title)}
        title="Double-click to rename"
      >
        {status === "running" ? <Spinner /> : <i className={`pip ${status}`} title={status === "review" ? "Changes waiting for review" : undefined} />}
        <span className="clip">{thread.title}</span>
        <time className="muted">{ago(thread.turns[thread.turns.length - 1]?.created_at ?? thread.created_at)}</time>
      </button>
      <button className="icon-btn hover-only" title="Delete this thread" onClick={() => onDeleteThread(thread)}>
        {icons.trash}
      </button>
    </li>
  )
}

function ago(seconds: number): string {
  const elapsed = Math.max(0, Date.now() / 1000 - seconds)
  if (elapsed < 60) {
    return "now"
  }
  if (elapsed < 3600) {
    return `${Math.floor(elapsed / 60)}m`
  }
  if (elapsed < 86400) {
    return `${Math.floor(elapsed / 3600)}h`
  }
  return `${Math.floor(elapsed / 86400)}d`
}
