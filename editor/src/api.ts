export type Track = {
  track_id: string
  kind: string
  start_frame: number
  end_frame: number
  pose: string
  locks: string[]
}

export type Shot = {
  shot_id: string
  scene_id: string
  start_frame: number
  duration_frames: number
  revision: string
  camera_preset: string
  framing: string
  actors: { actor_id: string; character_id: string; facing: string }[]
  assets: { role: string; asset_id: string; version: string }[]
  tracks: Track[]
}

export type EpisodeView = {
  episode_id: string
  title: string
  fps: number
  characters: { asset_id: string; display_name: string }[]
  backgrounds: { asset_id: string; display_name: string }[]
  props: { asset_id: string; display_name: string }[]
  shots: Shot[]
  lines: { shot_id: string; speaker_actor_id: string; text: string; start_frame: number; end_frame: number }[]
}

export type SessionState = {
  episode: EpisodeView
  snapshots: number
  can_redo: boolean
  pending: boolean
}

export type Proposal = {
  patch: Record<string, unknown>
  affected: string[]
  diff: string[]
}

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string }
    return body.detail ?? response.statusText
  } catch {
    return response.statusText
  }
}

export async function openSession(episode: unknown, poses: unknown | null): Promise<{ session_id: string } & SessionState> {
  const response = await fetch("/api/sessions", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ episode, poses }),
  })
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  return response.json()
}

export async function postJson<T>(url: string, body?: unknown): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  return response.json()
}
