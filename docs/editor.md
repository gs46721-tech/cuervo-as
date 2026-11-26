# Series editor

A chat-first authoring UI for whatever episode you open. It does not load a built-in show.

You work as the director, the editor, and the writer. You give a note in plain words. An agent carries it out and shows you each change as a sentence and a before and after frame. Nothing goes in the cut until you accept it. The page never shows code.

## Run it

```bash
cd editor && npm install && npm run build && cd ..
python3 -m cuervo_editor path/to/episode.json --poses path/to/poses.json
```

Open http://127.0.0.1:8000. Episodes named on the command line open as projects. You can also drop an episode JSON on the page, together with its pose table if the series has one.

For UI work, run `python3 -m cuervo_editor` and `cd editor && npm run dev`, then open http://127.0.0.1:5173. The dev server proxies `/api` to port 8000.

`CUERVO_EDITOR_STUB=1` registers a local `devstub` provider in front of the agent routes, so the page can be tried without API keys. It matches keywords and does not understand the direction. Leave it unset when Claude, Gemini, or Cursor credentials are available.

## Accounts and keys

Each person connects their own accounts in the editor: click the provider list at the bottom of the sidebar. Claude, Gemini, any OpenAI-compatible endpoint, and ElevenLabs each take an API key, and optionally a model. **Save and test** makes one small read-only request to check the key.

Keys are saved to `~/.cuervo/keys.json`, readable only by that user. `CUERVO_KEYS_FILE` moves the file. The API never returns a whole key. A saved key wins over one exported in the shell, and the pipeline commands read the same file. These are API keys. Signing in with a vendor account is not supported.

## The page

| Pane | What it holds |
| --- | --- |
| Sidebar | Projects, and the threads inside the open project. A dot marks a thread with changes waiting for review. |
| Thread | Your directions and the agent's turns: a work log, a reply, and one card per changed shot. |
| Stage | The frame player, the shot strip, and a timeline of the selected shot's tracks. Script and shot details are tabs. |

A project is one episode with its edit history. A thread is one conversation about it. Several threads can work on the same project.

## A turn

The person gives a note in plain words. The agent carries it out by writing cues, the command line of the animation. See [edits.md](edits.md). The page never shows a cue, an id, or a patch. It shows sentences: "Reframe shot 4 from a two-shot to a close-up."

1. The agent is handed the note, the shot on screen, and that scene's shot list.
2. Each round it sends cues through the `editor_assist` route. Read cues (`scenes`, `shots`, `show`, `find`) come back with what they print. Edit cues run on a working copy. A cue that fails comes back as an error the agent can fix.
3. It ends with `done` and a short message to the director. A question gets that message and no change.
4. The edits that held are staged as one change per shot, each with its sentences.

Shots pinned with `@` are the only shots that turn may change. The composer chooses the provider and the mode. **Review** leaves every change waiting for Accept or Reject. **Auto-apply** writes them as soon as they are drafted.

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
| `GET /api/settings/keys`, `PUT`, `DELETE /api/settings/keys/{name}` | Read, save, or remove a saved key. `POST .../test` checks it |
| `GET /api/sessions/{id}/audio/{shot}.wav` | The voice takes for one shot, when the project has a takes folder |
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
