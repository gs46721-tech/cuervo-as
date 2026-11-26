export type LockProperty = "timing" | "pose" | "camera" | "dialogue"

export type Track = {
  track_id: string
  kind: string
  actor_id: string
  /** The character's name, and what this track is in plain words. */
  who: string
  what: string
  start_frame: number
  end_frame: number
  pose: string
  locks: LockProperty[]
}

export type Line = {
  track_id: string
  speaker_actor_id: string
  speaker: string
  text: string
  start_frame: number
  end_frame: number
  locks: LockProperty[]
}

export type Shot = {
  shot_id: string
  scene_id: string
  /** Position in the episode, and the names the page shows: "Shot 12", "Close-up". */
  number: number
  label: string
  size: string
  start_frame: number
  duration_frames: number
  revision: string
  note: string
  camera_preset: string
  camera_x: number
  camera_y: number
  camera_locked: boolean
  has_voice: boolean
  framing: string
  actors: { actor_id: string; character_id: string; facing: string; name: string }[]
  assets: { role: string; asset_id: string; version: string }[]
  tracks: Track[]
  lines: Line[]
}

export type EpisodeView = {
  episode_id: string
  title: string
  fps: number
  total_frames: number
  scenes: { scene_id: string; title: string; objective: string; start_frame: number; duration_frames: number }[]
  characters: { asset_id: string; display_name: string }[]
  backgrounds: { asset_id: string; display_name: string }[]
  props: { asset_id: string; display_name: string }[]
  shots: Shot[]
  lines: (Line & { shot_id: string })[]
}

export type ChangeState = "pending" | "applied" | "undone" | "rejected" | "failed" | "discarded"

export type Change = {
  change_id: string
  shot_id: string
  instruction: string
  state: ChangeState
  stale: boolean
  /** What the change does, one sentence each. */
  summary: string[]
  grow: number
  provider: string | null
  model: string | null
  error: string | null
}

export type Step = { label: string; detail: string; status: "running" | "done" | "failed" }

export type TurnMode = "review" | "auto"

export type Turn = {
  turn_id: string
  instruction: string
  shot_ids: string[]
  provider: string | null
  mode: TurnMode
  status: "running" | "done" | "failed" | "stopped"
  reply: string
  error: string | null
  contests: string[]
  steps: Step[]
  changes: Change[]
  created_at: number
  finished_at: number | null
}

export type Thread = { thread_id: string; title: string; created_at: number; turns: Turn[] }

export type SessionState = {
  session_id: string
  episode: EpisodeView
  has_poses: boolean
  has_takes: boolean
  has_world: boolean
  approved_scenes: string[]
  rendered: boolean
  version: number
  undo: number
  redo: number
  threads: Thread[]
}

export type SessionCard = {
  session_id: string
  episode_id: string
  title: string
  updated_at: number
  threads: number
  pending: number
  running: boolean
}

export type ProviderInfo = { name: string; available: boolean; model: string | null }
export type Providers = { providers: ProviderInfo[]; routes: Record<string, string[]> }

export type ServiceKey = {
  name: string
  label: string
  role: string
  /** "local" is an agent signed in on this computer. "key" is an account with an API key. */
  kind: "local" | "key"
  version?: string
  login_hint?: string
  connected: boolean
  key_hint: string
  key_source: "" | "saved" | "environment"
  model: string
  base_url: string
  needs_base: boolean
  key_url: string
}

export type Job = {
  job_id: string
  kind: string
  status: "running" | "done" | "failed"
  log: string[]
  result: Record<string, unknown>
  error: string | null
  seconds: number
}

export type Note = { shot_id: string; shot: string; severity: "fix" | "look"; text: string }

export type LiveCheck = { job: string; who: string; ok: boolean; detail: string; seconds: number }

export type WorldAsset = {
  asset_id: string
  kind: "character" | "set"
  name: string
  version: string
  digest: string
  status: "draft" | "approved"
  source: string
  /** Pictures different models painted for a set. One of them is in use. */
  candidates?: { file: string; by: string }[]
  chosen?: number
}

export type KeyCheck = { ok: boolean; message: string; models?: string[]; voices?: { voice_id: string; name: string }[] }

export type RoleEntry = { provider: string; model: string }

export type Role = {
  role: string
  label: string
  help: string
  custom: boolean
  entries: RoleEntry[]
  compete: boolean
  judge: RoleEntry | null
  choices: { name: string; available: boolean; model?: string }[]
}

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body.detail === "string") {
      return body.detail
    }
    if (Array.isArray(body.detail) && body.detail.length) {
      const first = body.detail[0] as { msg?: string }
      return first.msg ?? response.statusText
    }
  } catch {
    // Not JSON. Fall through to the status line.
  }
  if (response.status >= 500) {
    return "The editor API is not answering. Start it with: python3 -m cuervo_editor"
  }
  return response.statusText || `HTTP ${response.status}`
}

async function call<T>(method: string, url: string, body?: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch(url, {
      method,
      headers: body === undefined ? undefined : { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new Error("The editor API is not reachable. Start it with: python3 -m cuervo_editor")
  }
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  return response.json() as Promise<T>
}

export const api = {
  providers: () => call<Providers>("GET", "/api/providers"),
  world: (id: string) => call<{ assets: WorldAsset[] }>("GET", `/api/sessions/${id}/world`),
  worldVerdict: (id: string, asset: string, verdict: "approve" | "reopen") =>
    call<{ assets: WorldAsset[] }>("POST", `/api/sessions/${id}/world/${asset}/${verdict}`),
  job: (id: string) => call<Job>("GET", `/api/jobs/${id}`),
  startProduction: (script: string, kit: unknown) => call<Job>("POST", "/api/productions", { script, kit }),
  writeScript: (premise: string, kit: unknown, minutes: number) => call<Job>("POST", "/api/productions/write", { premise, kit, minutes }),
  notes: (id: string) => call<{ notes: Note[] }>("GET", `/api/sessions/${id}/notes`),
  approveScene: (id: string, scene: string, approved: boolean) =>
    call<SessionState>("POST", `/api/sessions/${id}/scenes/${scene}`, { approved }),
  render: (id: string, width: number, height: number) => call<Job>("POST", `/api/sessions/${id}/render`, { width, height }),
  livecheck: () => call<Job>("POST", "/api/settings/livecheck"),
  roles: () => call<{ roles: Role[] }>("GET", "/api/settings/roles"),
  saveRole: (role: string, body: { entries: RoleEntry[]; compete: boolean; judge: RoleEntry | null }) =>
    call<{ roles: Role[] }>("PUT", `/api/settings/roles/${role}`, body),
  worldChoose: (id: string, asset: string, index: number) =>
    call<{ assets: WorldAsset[] }>("POST", `/api/sessions/${id}/world/${asset}/choose/${index}`),
  keys: () => call<{ services: ServiceKey[] }>("GET", "/api/settings/keys"),
  saveKey: (name: string, body: { api_key?: string; model?: string; base_url?: string }) =>
    call<{ services: ServiceKey[] }>("PUT", `/api/settings/keys/${name}`, body),
  removeKey: (name: string) => call<{ services: ServiceKey[] }>("DELETE", `/api/settings/keys/${name}`),
  testKey: (name: string) => call<KeyCheck>("POST", `/api/settings/keys/${name}/test`),
  sessions: () => call<{ sessions: SessionCard[] }>("GET", "/api/sessions"),
  open: (episode: unknown, poses: unknown | null) => call<SessionState>("POST", "/api/sessions", { episode, poses }),
  read: (id: string) => call<SessionState>("GET", `/api/sessions/${id}`),
  remove: (id: string) => call<unknown>("DELETE", `/api/sessions/${id}`),
  newThread: (id: string) => call<SessionState & { thread_id: string }>("POST", `/api/sessions/${id}/threads`),
  renameThread: (id: string, thread: string, title: string) =>
    call<SessionState>("PATCH", `/api/sessions/${id}/threads/${thread}`, { title }),
  removeThread: (id: string, thread: string) => call<SessionState>("DELETE", `/api/sessions/${id}/threads/${thread}`),
  turn: (
    id: string,
    thread: string,
    body: { instruction: string; shot_ids: string[]; focus_shot_id: string | null; provider: string | null; mode: TurnMode },
  ) => call<SessionState>("POST", `/api/sessions/${id}/threads/${thread}/turns`, body),
  turnAction: (id: string, turn: string, action: "stop" | "accept" | "reject" | "revert") =>
    call<SessionState>("POST", `/api/sessions/${id}/turns/${turn}/${action}`),
  changeAction: (id: string, change: string, action: "accept" | "reject") =>
    call<SessionState>("POST", `/api/sessions/${id}/changes/${change}/${action}`),
  history: (id: string, action: "undo" | "redo") => call<SessionState>("POST", `/api/sessions/${id}/${action}`),
  lock: (id: string, shot_id: string, track_id: string, properties: LockProperty[]) =>
    call<SessionState>("POST", `/api/sessions/${id}/lock`, { shot_id, track_id, properties }),
}

export function frameUrl(state: SessionState, shotId: string, frame: number): string {
  return `/api/sessions/${state.session_id}/frames/${shotId}/${frame}.png?v=${state.version}`
}

export function changeFrameUrl(state: SessionState, changeId: string, frame: number): string {
  return `/api/sessions/${state.session_id}/changes/${changeId}/frames/${frame}.png?v=${state.version}`
}

export function audioUrl(state: SessionState, shotId: string): string {
  return `/api/sessions/${state.session_id}/audio/${shotId}.wav?v=${state.version}`
}

export function masterUrl(sessionId: string): string {
  return `/api/sessions/${sessionId}/master.mp4`
}

export function exportUrl(sessionId: string): string {
  return `/api/sessions/${sessionId}/episode.json`
}

export function timecode(frame: number, fps: number): string {
  const seconds = Math.floor(frame / fps)
  const pad = (value: number) => String(value).padStart(2, "0")
  return `${pad(Math.floor(seconds / 60))}:${pad(seconds % 60)}:${pad(frame % fps)}`
}

export function threadStatus(thread: Thread): "running" | "review" | "failed" | "idle" {
  if (thread.turns.some((turn) => turn.status === "running")) {
    return "running"
  }
  if (thread.turns.some((turn) => turn.changes.some((change) => change.state === "pending"))) {
    return "review"
  }
  const last = thread.turns[thread.turns.length - 1]
  return last && last.status === "failed" ? "failed" : "idle"
}
