import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  type Change,
  type Note,
  api,
  type LockProperty,
  type SessionState,
  type Shot,
  audioUrl,
  changeFrameUrl,
  exportUrl,
  frameUrl,
  timecode,
} from "./api"
import { icons } from "./icons"

type Props = {
  state: SessionState
  shot: Shot
  frame: number
  playing: boolean
  preview: Change | null
  onSeek: (shotId: string, frame: number) => void
  onPlaying: (playing: boolean) => void
  onClearPreview: () => void
  onReview: (change: Change, action: "accept" | "reject") => void
  onLock: (shot: Shot, trackId: string, properties: LockProperty[]) => void
  onCameraLock: (shot: Shot) => void
  onHistory: (action: "undo" | "redo") => void
  onClose: () => void
}

type Tab = "timeline" | "script" | "notes" | "details"

// Decoded frames by URL. A URL carries the project version, so an entry never goes stale.
const images = new Map<string, HTMLImageElement>()

function load(url: string): HTMLImageElement {
  let image = images.get(url)
  if (!image) {
    if (images.size > 2400) {
      images.clear()
    }
    image = new Image()
    image.src = url
    images.set(url, image)
  }
  return image
}

function ready(url: string): boolean {
  const image = load(url)
  return image.complete && image.naturalWidth > 0
}

export function Stage(props: Props) {
  const { state, shot, frame, playing, preview } = props
  const episode = state.episode
  const [tab, setTab] = useState<Tab>("timeline")
  // What a careful watch would catch. Read again whenever the cut changes.
  const [notes, setNotes] = useState<Note[]>([])
  useEffect(() => {
    let live = true
    api
      .notes(state.session_id)
      .then((body) => live && setNotes(body.notes))
      .catch(() => undefined)
    return () => {
      live = false
    }
  }, [state.session_id, state.version])
  const previewing = preview !== null && preview.shot_id === shot.shot_id && preview.state === "pending" && !preview.stale
  const duration = shot.duration_frames + (previewing ? preview.grow : 0)
  const current = Math.min(frame, duration - 1)

  const urlFor = useCallback(
    (index: number) =>
      previewing && preview ? changeFrameUrl(state, preview.change_id, index) : frameUrl(state, shot.shot_id, index),
    [previewing, preview, state, shot.shot_id],
  )

  // Warm the whole shot so playback and scrubbing do not wait on the network.
  useEffect(() => {
    for (let index = 0; index < duration; index += 1) {
      load(urlFor(index))
    }
  }, [urlFor, duration])

  // Playback. The clock only advances once the next picture is decoded.
  const live = useRef({ current, duration, shot, episode, previewing, urlFor })
  live.current = { current, duration, shot, episode, previewing, urlFor }
  const { onSeek, onPlaying } = props

  // Voice takes for this shot. While they play, the sound is the clock, so the mouth stays on the words.
  const sound = useRef<HTMLAudioElement | null>(null)
  const soundUrl = state.has_takes && shot.has_voice && !previewing ? audioUrl(state, shot.shot_id) : null
  useEffect(() => {
    if (!soundUrl) {
      sound.current = null
      return
    }
    const element = new Audio(soundUrl)
    element.preload = "auto"
    sound.current = element
    return () => {
      element.pause()
      sound.current = null
    }
  }, [soundUrl])
  useEffect(() => {
    const element = sound.current
    if (!element) {
      return
    }
    if (playing) {
      element.currentTime = live.current.current / live.current.episode.fps
      element.play().catch(() => undefined)
    } else {
      element.pause()
    }
  }, [playing, soundUrl])

  useEffect(() => {
    if (!playing) {
      return
    }
    const timer = window.setInterval(() => {
      const now = live.current
      const element = sound.current
      if (element && !element.paused && !element.ended) {
        const heard = Math.floor(element.currentTime * now.episode.fps)
        if (heard < now.duration) {
          if (heard !== now.current) {
            onSeek(now.shot.shot_id, heard)
          }
          return
        }
      }
      const next = now.current + 1
      if (next < now.duration) {
        if (ready(now.urlFor(next))) {
          onSeek(now.shot.shot_id, next)
        }
        return
      }
      if (now.previewing) {
        onSeek(now.shot.shot_id, 0)
        return
      }
      const shots = now.episode.shots
      const following = shots[shots.findIndex((item) => item.shot_id === now.shot.shot_id) + 1]
      if (following) {
        onSeek(following.shot_id, 0)
      } else {
        onPlaying(false)
      }
    }, 1000 / episode.fps)
    return () => window.clearInterval(timer)
  }, [playing, episode.fps, onSeek, onPlaying])

  const index = episode.shots.findIndex((item) => item.shot_id === shot.shot_id)
  const jump = (offset: number) => {
    const target = episode.shots[index + offset]
    if (target) {
      props.onSeek(target.shot_id, 0)
    }
  }
  const step = (offset: number) => {
    props.onPlaying(false)
    props.onSeek(shot.shot_id, Math.max(0, Math.min(duration - 1, current + offset)))
  }

  return (
    <aside className="stage" aria-label="Stage">
      <header className="pane-head">
        <div className="pane-title">
          <strong>{episode.title}</strong>
          <span className="muted mono">
            {episode.fps} fps · {timecode(episode.total_frames, episode.fps)}
          </span>
        </div>
        <div className="row">
          <button className="icon-btn" title="Undo (⌘Z)" disabled={!state.undo} onClick={() => props.onHistory("undo")}>
            {icons.undo}
          </button>
          <button className="icon-btn" title="Redo (⇧⌘Z)" disabled={!state.redo} onClick={() => props.onHistory("redo")}>
            {icons.redo}
          </button>
          <a className="icon-btn" title="Download the episode JSON" href={exportUrl(state.session_id)} download>
            {icons.download}
          </a>
          <button className="icon-btn" title="Hide stage (⌘J)" onClick={props.onClose}>
            {icons.close}
          </button>
        </div>
      </header>

      <div className="stage-body">
        <Viewer url={urlFor(current)} label={`${shot.label}, frame ${current + 1}`} hasPoses={state.has_poses}>
          <span className="badge">{shot.label}</span>
          <span className="badge">{shot.size}</span>
          {soundUrl ? <span className="badge">voice</span> : null}
          {previewing && preview ? (
            <div className="preview-bar">
              <span>
                <strong>Proposed</strong> · not applied yet
              </span>
              <span className="row">
                <button className="btn small primary" onClick={() => props.onReview(preview, "accept")}>
                  Accept
                </button>
                <button className="btn small" onClick={() => props.onReview(preview, "reject")}>
                  Reject
                </button>
                <button className="btn small ghost" onClick={props.onClearPreview}>
                  Back to current
                </button>
              </span>
            </div>
          ) : null}
        </Viewer>

        <div className="transport">
          <div className="row">
            <button className="icon-btn" title="Previous shot" disabled={index <= 0} onClick={() => jump(-1)}>
              {icons.prevShot}
            </button>
            <button className="icon-btn" title="Back one frame (←)" onClick={() => step(-1)}>
              {icons.stepBack}
            </button>
            <button
              className="icon-btn play"
              title={playing ? "Pause (Space)" : "Play (Space)"}
              aria-pressed={playing}
              onClick={() => props.onPlaying(!playing)}
            >
              {playing ? icons.pause : icons.play}
            </button>
            <button className="icon-btn" title="Forward one frame (→)" onClick={() => step(1)}>
              {icons.stepForward}
            </button>
            <button
              className="icon-btn"
              title="Next shot"
              disabled={index >= episode.shots.length - 1}
              onClick={() => jump(1)}
            >
              {icons.nextShot}
            </button>
          </div>
          <span className="mono counter">
            <strong>{timecode(shot.start_frame + current, episode.fps)}</strong>
            <span className="muted">
              {" "}
              · frame {current + 1} of {duration}
            </span>
          </span>
        </div>

        <ShotStrip state={state} shot={shot} frame={current} onSeek={props.onSeek} />

        <div className="tabs" role="tablist">
          {(["timeline", "script", "notes", "details"] as Tab[]).map((name) => (
            <button key={name} role="tab" aria-selected={tab === name} onClick={() => setTab(name)}>
              {name}
              {name === "notes" && notes.length ? <span className="count">{notes.length}</span> : null}
            </button>
          ))}
        </div>

        {tab === "timeline" ? (
          <Timeline
            shot={shot}
            fps={episode.fps}
            frame={current}
            duration={duration}
            onScrub={(value) => {
              props.onPlaying(false)
              props.onSeek(shot.shot_id, value)
            }}
            onLock={props.onLock}
            onCameraLock={props.onCameraLock}
          />
        ) : null}
        {tab === "script" ? <Script state={state} shot={shot} onSeek={props.onSeek} /> : null}
        {tab === "notes" ? <Notes notes={notes} shot={shot} onSeek={props.onSeek} /> : null}
        {tab === "details" ? <Details state={state} shot={shot} /> : null}
      </div>
    </aside>
  )
}

function Viewer({
  url,
  label,
  hasPoses,
  children,
}: {
  url: string
  label: string
  hasPoses: boolean
  children: React.ReactNode
}) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const [failed, setFailed] = useState<string | null>(null)

  useEffect(() => {
    const image = load(url)
    let cancelled = false
    const draw = () => {
      const context = canvas.current?.getContext("2d")
      if (cancelled || !context || !canvas.current) {
        return
      }
      context.drawImage(image, 0, 0, canvas.current.width, canvas.current.height)
      setFailed(null)
    }
    const fail = () => {
      if (!cancelled) {
        images.delete(url)
        setFailed(url)
      }
    }
    if (image.complete) {
      if (image.naturalWidth > 0) {
        draw()
      } else {
        fail()
      }
    } else {
      image.addEventListener("load", draw)
      image.addEventListener("error", fail)
    }
    return () => {
      cancelled = true
      image.removeEventListener("load", draw)
      image.removeEventListener("error", fail)
    }
  }, [url])

  return (
    <div className="viewer">
      <canvas ref={canvas} width={640} height={360} role="img" aria-label={label} />
      {failed === url ? (
        <div className="viewer-error">
          <strong>This frame could not be drawn.</strong>
          <span>
            {hasPoses
              ? "A track uses a pose that is not in the pose table."
              : "A track may use a series pose. Open the episode again together with its pose table."}
          </span>
        </div>
      ) : null}
      <div className="viewer-overlay">{children}</div>
    </div>
  )
}

function ShotStrip({
  state,
  shot,
  frame,
  onSeek,
}: {
  state: SessionState
  shot: Shot
  frame: number
  onSeek: (shotId: string, frame: number) => void
}) {
  const episode = state.episode
  // One scene at a time: a half-hour episode has hundreds of shots.
  const sceneIndex = Math.max(0, episode.scenes.findIndex((item) => item.scene_id === shot.scene_id))
  const scene = episode.scenes[sceneIndex]
  const shots = episode.shots.filter((item) => item.scene_id === shot.scene_id)
  const first = episode.shots.findIndex((item) => item.scene_id === shot.scene_id)
  const playhead = ((shot.start_frame - scene.start_frame + frame) / Math.max(1, scene.duration_frames)) * 100
  return (
    <>
    {episode.scenes.length > 1 ? (
      <div className="scene-bar">
        <label className="select">
          <select
            aria-label="Scene"
            value={scene.scene_id}
            onChange={(event) => {
              const target = episode.shots.find((item) => item.scene_id === event.target.value)
              if (target) {
                onSeek(target.shot_id, 0)
              }
            }}
          >
            {episode.scenes.map((item, index) => (
              <option key={item.scene_id} value={item.scene_id}>
                Scene {index + 1} of {episode.scenes.length} · {item.title}
              </option>
            ))}
          </select>
        </label>
        <span className="muted mono">{shots.length} shots</span>
      </div>
    ) : null}
    <div className="strip" aria-label="Shots in this scene">
      {shots.map((item, position) => {
        const index = first + position
        return (
        <button
          key={item.shot_id}
          className={item.shot_id === shot.shot_id ? "strip-shot selected" : "strip-shot"}
          style={{ flexGrow: item.duration_frames, backgroundImage: `url(${frameUrl(state, item.shot_id, 0)})` }}
          title={`${item.label} · ${item.size}${item.lines[0] ? ` · “${item.lines[0].text}”` : ""}`}
          onClick={() => onSeek(item.shot_id, 0)}
        >
          <span>{index + 1}</span>
        </button>
        )
      })}
      <i className="strip-playhead" style={{ left: `${playhead}%` }} />
    </div>
    </>
  )
}

function Timeline({
  shot,
  fps,
  frame,
  duration,
  onScrub,
  onLock,
  onCameraLock,
}: {
  shot: Shot
  fps: number
  frame: number
  duration: number
  onScrub: (frame: number) => void
  onLock: Props["onLock"]
  onCameraLock: Props["onCameraLock"]
}) {
  const lanes = useRef<HTMLDivElement>(null)
  const ticks = useMemo(() => {
    const seconds = Math.floor(duration / fps)
    const every = seconds > 16 ? 4 : seconds > 8 ? 2 : 1
    const marks: number[] = []
    for (let second = 0; second <= seconds; second += every) {
      marks.push(second)
    }
    return marks
  }, [duration, fps])

  const scrub = (event: React.PointerEvent) => {
    const box = lanes.current?.getBoundingClientRect()
    if (!box) {
      return
    }
    const ratio = (event.clientX - box.left) / box.width
    onScrub(Math.max(0, Math.min(duration - 1, Math.floor(ratio * duration))))
  }
  const span = (start: number, end: number) => ({
    left: `${(start / duration) * 100}%`,
    width: `${(Math.min(end, duration) - start) / duration * 100}%`,
  })
  const toggle = (trackId: string, locks: LockProperty[], property: LockProperty) =>
    onLock(shot, trackId, locks.includes(property) ? locks.filter((item) => item !== property) : [...locks, property])

  return (
    <div className="timeline">
      <div className="tl-labels">
        <div className="tl-ruler-pad muted">{(duration / fps).toFixed(1)} s</div>
        <div className="tl-label">
          <i className="dot kind-camera" />
          <span className="tl-name">
            <span>Camera</span>
            <small>{shot.size}</small>
          </span>
          <LockChip label="camera" on={shot.camera_locked} onClick={() => onCameraLock(shot)} />
        </div>
        {shot.tracks.map((track) => (
          <div className="tl-label" key={track.track_id}>
            <i className={`dot kind-${track.kind}`} />
            <span className="tl-name">
              <span>{track.who}</span>
              <small>
                {track.what} · {track.pose.replace(/_/g, " ")}
              </small>
            </span>
            <LockChip label="timing" on={track.locks.includes("timing")} onClick={() => toggle(track.track_id, track.locks, "timing")} />
            <LockChip label="pose" on={track.locks.includes("pose")} onClick={() => toggle(track.track_id, track.locks, "pose")} />
          </div>
        ))}
        {shot.lines.map((line) => (
          <div className="tl-label" key={line.track_id}>
            <i className="dot kind-dialogue" />
            <span className="tl-name" title={line.text}>
              <span>{line.speaker}</span>
              <small>line</small>
            </span>
            <LockChip label="dialogue" on={line.locks.includes("dialogue")} onClick={() => toggle(line.track_id, line.locks, "dialogue")} />
          </div>
        ))}
      </div>
      <div
        className="tl-lanes"
        ref={lanes}
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture(event.pointerId)
          scrub(event)
        }}
        onPointerMove={(event) => {
          if (event.buttons === 1) {
            scrub(event)
          }
        }}
      >
        <div className="tl-ruler">
          {ticks.map((second) => (
            <span key={second} className="mono" style={{ left: `${((second * fps) / duration) * 100}%` }}>
              {second}s
            </span>
          ))}
        </div>
        <div className="tl-lane">
          <span className="bar kind-camera" style={span(0, duration)}>
            {shot.size}
          </span>
        </div>
        {shot.tracks.map((track) => (
          <div className="tl-lane" key={track.track_id}>
            <span className={`bar kind-${track.kind}`} style={span(track.start_frame, track.end_frame)}>
              {track.pose.replace(/_/g, " ")}
            </span>
          </div>
        ))}
        {shot.lines.map((line) => (
          <div className="tl-lane" key={line.track_id}>
            <span className="bar kind-dialogue" style={span(line.start_frame, line.end_frame)}>
              {line.text}
            </span>
          </div>
        ))}
        <i className="tl-playhead" style={{ left: `${((frame + 0.5) / duration) * 100}%` }} />
      </div>
    </div>
  )
}

function LockChip({ label, on, onClick }: { label: string; on: boolean; onClick: () => void }) {
  return (
    <button
      className={on ? "lock on" : "lock"}
      aria-pressed={on}
      title={on ? `${label} is locked. The agent cannot change it. Click to unlock.` : `Lock ${label} so the agent cannot change it`}
      onClick={onClick}
    >
      {icons.lock}
      {label}
    </button>
  )
}

function Script({ state, shot, onSeek }: { state: SessionState; shot: Shot; onSeek: Props["onSeek"] }) {
  const lines = state.episode.lines
  if (!lines.length) {
    return <p className="empty-note">This episode has no dialogue.</p>
  }
  return (
    <ol className="script">
      {lines.map((line) => (
        <li key={`${line.shot_id}-${line.track_id}`}>
          <button className={line.shot_id === shot.shot_id ? "selected" : ""} onClick={() => onSeek(line.shot_id, line.start_frame)}>
            <span className="script-meta">
              {line.speaker}{" "}
              <span className="muted">· {state.episode.shots.find((item) => item.shot_id === line.shot_id)?.label}</span>
            </span>
            <span>{line.text}</span>
          </button>
        </li>
      ))}
    </ol>
  )
}

function Notes({ notes, shot, onSeek }: { notes: Note[]; shot: Shot; onSeek: Props["onSeek"] }) {
  if (!notes.length) {
    return <p className="empty-note">Nothing to fix. The checks found no problems in this cut.</p>
  }
  // Problems first, then things to look at.
  const ordered = [...notes].sort((left, right) => Number(right.severity === "fix") - Number(left.severity === "fix"))
  return (
    <ol className="script notes">
      {ordered.map((note, index) => (
        <li key={index}>
          <button className={note.shot_id === shot.shot_id ? "selected" : ""} disabled={!note.shot_id} onClick={() => onSeek(note.shot_id, 0)}>
            <span className="script-meta">
              <span className={note.severity === "fix" ? "status failed" : "status pending"}>{note.severity === "fix" ? "Fix" : "Look"}</span>{" "}
              <span className="muted">{note.shot}</span>
            </span>
            <span>{note.text}</span>
          </button>
        </li>
      ))}
    </ol>
  )
}

function Details({ state, shot }: { state: SessionState; shot: Shot }) {
  const scene = state.episode.scenes.find((item) => item.scene_id === shot.scene_id)
  const set = state.episode.backgrounds.find((item) => shot.assets.some((asset) => asset.asset_id === item.asset_id))
  const fps = state.episode.fps
  return (
    <dl className="details">
      <dt>Scene</dt>
      <dd>
        {scene?.title ?? "Scene"}
        {scene ? <small>{scene.objective}</small> : null}
      </dd>
      <dt>Set</dt>
      <dd>{set?.display_name ?? "Not set"}</dd>
      <dt>Framing</dt>
      <dd>
        {shot.size}
        <small>{shot.framing}</small>
      </dd>
      <dt>Length</dt>
      <dd>
        {(shot.duration_frames / fps).toFixed(1)} seconds
        <small>{shot.duration_frames} frames</small>
      </dd>
      <dt>On stage</dt>
      <dd>{shot.actors.map((actor) => actor.name).join(", ")}</dd>
      <dt>Last note</dt>
      <dd>{shot.note}</dd>
    </dl>
  )
}
