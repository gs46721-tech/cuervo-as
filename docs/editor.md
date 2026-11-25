# Series editor

A React authoring UI for whatever episode you open. It does not load a built-in show.

The page has the script, a storyboard, a 2D preview canvas, an asset inspector, and a multitrack timeline with a frame ruler. Direction goes to `POST /api/sessions/{id}/propose`, which calls the `ir_patch` route (Claude, then Gemini, then Cursor). The reply is a typed patch and a diff. Accept writes a snapshot. Undo and redo walk those snapshots. Lock pose or camera on a track before proposing if that part must not move.

```bash
python3 -m cuervo_editor
cd editor && npm install && npm run dev
```

Open http://127.0.0.1:5173 and choose an episode JSON file. `CUERVO_EDITOR_STUB=1` registers a local `devstub` provider in front of the same route so the edit buttons can be tried without API keys. Leave it unset when Claude, Gemini, or Cursor credentials are available.
