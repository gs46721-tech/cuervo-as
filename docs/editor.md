# Series editor

A chat-first authoring UI for whatever episode you open. It does not load a built-in show.

You give a direction in plain words. An agent turns it into typed patches, one per shot. Each patch shows as a diff and a before and after frame. Nothing is written to the episode until you accept it.

## Run it

```bash
cd editor && npm install && npm run build && cd ..
python3 -m cuervo_editor path/to/episode.json --poses path/to/poses.json
```

Open http://127.0.0.1:8000. Episodes named on the command line open as projects. You can also drop an episode JSON on the page, together with its pose table if the series has one.

For UI work, run `python3 -m cuervo_editor` and `cd editor && npm run dev`, then open http://127.0.0.1:5173. The dev server proxies `/api` to port 8000.

`CUERVO_EDITOR_STUB=1` registers a local `devstub` provider in front of the agent routes, so the page can be tried without API keys. It matches keywords and does not understand the direction. Leave it unset when Claude, Gemini, or Cursor credentials are available.

## The page

| Pane | What it holds |
| --- | --- |
| Sidebar | Projects, and the threads inside the open project. A dot marks a thread with changes waiting for review. |
| Thread | Your directions and the agent's turns: a work log, a reply, and one card per changed shot. |
| Stage | The frame player, the shot strip, and a timeline of the selected shot's tracks. Script and shot details are tabs. |

A project is one episode with its edit history. A thread is one conversation about it. Several threads can work on the same project.

## A turn

1. If you pinned shots with `@`, each pinned shot gets the direction as written.
2. Otherwise the `editor_assist` route reads the episode and returns a reply and one instruction per shot it wants to change. A question gets a reply and no edits.
3. The `ir_patch` route drafts one `edit_patch` per shot. See [edits.md](edits.md) for what a patch may do.
4. Each patch is dry-applied. One that breaks a lock or the schema is marked failed on its card and the rest continue.

The composer chooses the provider and the mode. **Auto** follows the route order in [providers.md](providers.md). **Review** leaves every change waiting for Accept or Reject. **Auto-apply** writes them as soon as they are drafted.

## Review, undo, and locks

- **Preview on stage** plays the shot with the change applied. The episode is not changed.
- **Accept** writes the change and pushes an undo snapshot. Undo and redo walk those snapshots.
- **Revert to before this turn** undoes back to the state before that turn's first change. Redo brings it back.
- A waiting change goes out of date when its shot gets a new revision. It cannot be applied then. Ask again.
- Hover a track in the timeline to lock its timing or pose, or lock the camera. The agent's patch is rejected if it touches a locked part.

The download button in the stage header saves the current episode JSON.

## Keys

| Key | Action |
| --- | --- |
| Enter, Shift+Enter | Send, new line |
| `@` | Pin the direction to a shot |
| ⌘K | Commands, shots, and threads |
| ⌘B, ⌘J | Toggle the sidebar, toggle the stage |
| Space, ←, → | Play or pause, step one frame |
| ⌘Z, ⇧⌘Z | Undo, redo |

Ctrl works in place of ⌘.

## Storage

Projects, threads, and undo history are JSON files under `~/.cuervo/projects`. Set `CUERVO_EDITOR_HOME` to keep them somewhere else. A turn that was running when the API stopped shows as stopped after a restart.

## API

| Route | Does |
| --- | --- |
| `GET /api/providers` | Providers on the agent routes and whether each has a key |
| `GET`, `POST /api/sessions` | List projects, open an episode as a project |
| `GET`, `DELETE /api/sessions/{id}` | Read or close a project |
| `GET /api/sessions/{id}/episode.json` | The current episode |
| `GET /api/sessions/{id}/frames/{shot}/{frame}.png` | One frame of the current episode |
| `GET /api/sessions/{id}/changes/{change}/frames/{frame}.png` | One frame with a waiting change applied |
| `POST /api/sessions/{id}/threads` | New thread. `PATCH` renames it and `DELETE` removes it |
| `POST /api/sessions/{id}/threads/{thread}/turns` | Start a turn. The page polls the project while it runs |
| `POST /api/sessions/{id}/turns/{turn}/stop` | Stop a turn before its next step |
| `POST /api/sessions/{id}/turns/{turn}/accept`, `reject`, `revert` | Review or roll back a whole turn |
| `POST /api/sessions/{id}/changes/{change}/accept`, `reject` | Review one change |
| `POST /api/sessions/{id}/undo`, `redo` | Walk the snapshots |
| `POST /api/sessions/{id}/lock` | Set the locks on one track. An empty list unlocks it |
