import { useEffect, useRef, useState } from "react"
import { type EpisodeView, type Proposal, type SessionState, type Shot, openSession, postJson } from "./api"

export function App() {
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [episode, setEpisode] = useState<EpisodeView | null>(null)
  const [snapshots, setSnapshots] = useState(0)
  const [canRedo, setCanRedo] = useState(false)
  const [shotId, setShotId] = useState<string | null>(null)
  const [trackId, setTrackId] = useState<string | null>(null)
  const [frame, setFrame] = useState(0)
  const [instruction, setInstruction] = useState("")
  const [proposal, setProposal] = useState<Proposal | null>(null)
  const [message, setMessage] = useState("Open an episode JSON file. The editor does not ship a show.")
  const canvas = useRef<HTMLCanvasElement>(null)

  const shot = episode?.shots.find((item) => item.shot_id === shotId) ?? null

  useEffect(() => {
    if (!sessionId || !shot) {
      return
    }
    const image = new Image()
    image.onload = () => {
      const context = canvas.current?.getContext("2d")
      if (!context || !canvas.current) {
        return
      }
      context.clearRect(0, 0, canvas.current.width, canvas.current.height)
      context.drawImage(image, 0, 0, canvas.current.width, canvas.current.height)
    }
    image.src = `/api/sessions/${sessionId}/frames/${shot.shot_id}/${frame}.png?revision=${shot.revision}`
  }, [sessionId, shot, frame])

  function applyState(state: SessionState, keepShot = true) {
    setEpisode(state.episode)
    setSnapshots(state.snapshots)
    setCanRedo(state.can_redo)
    setShotId((current) => {
      if (keepShot && current && state.episode.shots.some((item) => item.shot_id === current)) {
        return current
      }
      return state.episode.shots[0]?.shot_id ?? null
    })
  }

  async function onFile(file: File | undefined) {
    if (!file) {
      return
    }
    try {
      const episodeJson = JSON.parse(await file.text()) as unknown
      const opened = await openSession(episodeJson, null)
      setSessionId(opened.session_id)
      applyState(opened, false)
      setFrame(0)
      setProposal(null)
      setMessage(opened.episode.title)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not open that file")
    }
  }

  async function propose() {
    if (!sessionId || !shot) {
      return
    }
    try {
      const result = await postJson<Proposal>(`/api/sessions/${sessionId}/propose`, {
        shot_id: shot.shot_id,
        instruction,
      })
      setProposal(result)
      setMessage("Review the diff, then accept or reject.")
    } catch (error) {
      setProposal(null)
      setMessage(error instanceof Error ? error.message : "Propose failed")
    }
  }

  async function mutate(path: string, body?: unknown) {
    if (!sessionId) {
      return
    }
    try {
      const state = await postJson<SessionState>(`/api/sessions/${sessionId}/${path}`, body)
      applyState(state)
      setProposal(null)
      setMessage(path)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : path)
    }
  }

  return (
    <div className="app">
      <header>
        <strong>Cuervo</strong>
        <label>
          Episode
          <input
            aria-label="Episode file"
            type="file"
            accept="application/json"
            onChange={(event) => void onFile(event.target.files?.[0])}
          />
        </label>
        <span>{episode ? `${episode.episode_id} · ${episode.fps} fps` : "No episode"}</span>
        <span>{snapshots} snapshots</span>
      </header>
      <div className="columns">
        <section>
          <h2>Storyboard</h2>
          <ul>
            {episode?.shots.map((item) => (
              <li key={item.shot_id}>
                <button
                  type="button"
                  className={item.shot_id === shotId ? "selected" : ""}
                  onClick={() => {
                    setShotId(item.shot_id)
                    setFrame(0)
                    setTrackId(null)
                  }}
                >
                  {item.shot_id}
                  <small>
                    {item.camera_preset} · {item.duration_frames}f
                  </small>
                </button>
              </li>
            ))}
          </ul>
          <h2>Script</h2>
          <ul>
            {episode?.lines.map((line) => (
              <li key={`${line.shot_id}-${line.start_frame}-${line.text}`}>
                <button type="button" onClick={() => setShotId(line.shot_id)}>
                  <small>{line.speaker_actor_id}</small>
                  {line.text}
                </button>
              </li>
            ))}
            {episode && episode.lines.length === 0 ? <li>No dialogue in this episode.</li> : null}
          </ul>
        </section>
        <section>
          <h2>Preview</h2>
          <canvas ref={canvas} width={640} height={360} aria-label="Shot preview" />
          {shot ? (
            <label className="ruler">
              Frame {frame} / {shot.duration_frames - 1}
              <input
                aria-label="Frame ruler"
                type="range"
                min={0}
                max={Math.max(0, shot.duration_frames - 1)}
                value={Math.min(frame, shot.duration_frames - 1)}
                onChange={(event) => setFrame(Number(event.target.value))}
              />
            </label>
          ) : null}
          <form
            onSubmit={(event) => {
              event.preventDefault()
              void propose()
            }}
          >
            <label>
              Direction
              <input
                aria-label="Direction"
                value={instruction}
                onChange={(event) => setInstruction(event.target.value)}
                placeholder="Describe one change to this shot"
              />
            </label>
            <div className="row">
              <button type="submit">Propose</button>
              <button type="button" onClick={() => void mutate("accept")} disabled={!proposal}>
                Accept
              </button>
              <button type="button" onClick={() => void mutate("reject")} disabled={!proposal}>
                Reject
              </button>
              <button type="button" onClick={() => void mutate("undo")}>
                Undo
              </button>
              <button type="button" onClick={() => void mutate("redo")} disabled={!canRedo}>
                Redo
              </button>
            </div>
          </form>
          {proposal ? (
            <div className="diff">
              <h3>Diff</h3>
              <ul>
                {proposal.diff.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
              <p>Affected: {proposal.affected.join(", ")}</p>
            </div>
          ) : null}
          <p role="status">{message}</p>
        </section>
        <section>
          <h2>Assets</h2>
          {shot ? <AssetList shot={shot} characters={episode?.characters ?? []} /> : <p>Select a shot.</p>}
        </section>
      </div>
      <section className="timeline">
        <h2>Timeline</h2>
        {shot
          ? shot.tracks.map((track) => (
              <button
                key={track.track_id}
                type="button"
                className={track.track_id === trackId ? "bar selected" : "bar"}
                onClick={() => setTrackId(track.track_id)}
              >
                <span>
                  {track.kind} {track.track_id} · {track.pose}
                  {track.locks.length ? ` · locked ${track.locks.join("/")}` : ""}
                </span>
                <span
                  className="span"
                  style={{
                    marginLeft: `${(track.start_frame / shot.duration_frames) * 100}%`,
                    width: `${((track.end_frame - track.start_frame) / shot.duration_frames) * 100}%`,
                  }}
                />
              </button>
            ))
          : null}
        {shot && trackId ? (
          <button
            type="button"
            onClick={() =>
              void mutate("lock", { shot_id: shot.shot_id, track_id: trackId, properties: ["pose"] })
            }
          >
            Lock pose on {trackId}
          </button>
        ) : null}
      </section>
    </div>
  )
}

function AssetList({ shot, characters }: { shot: Shot; characters: EpisodeView["characters"] }) {
  const names = new Map(characters.map((item) => [item.asset_id, item.display_name]))
  return (
    <ul>
      {shot.actors.map((actor) => (
        <li key={actor.actor_id}>
          {actor.actor_id} · {names.get(actor.character_id) ?? actor.character_id} · {actor.facing}
        </li>
      ))}
      {shot.assets.map((asset) => (
        <li key={`${asset.role}-${asset.asset_id}`}>
          {asset.role} {asset.asset_id}@{asset.version}
        </li>
      ))}
    </ul>
  )
}
