# Natural-language edits

A direction line becomes one typed patch for one shot. The `ir_patch` step sends the instruction and that shot's tracks to the model router. Claude is first, then Gemini, then Cursor. The reply is an `edit_patch`. It is not applied until you accept it.

A patch may do only these things:

- move the frame bounds of named action tracks, and grow the shot
- set the pose on a named track
- change the camera preset or its position

When the shot grows, later shots in the same scene keep their contents and start later. No other shot changes. A track locked for `timing` or `pose` rejects that part of the patch. The previous episode object is left as it was, so declining the preview is the undo.

`preview_frame` re-renders one frame of the changed shot after a dry apply. The five checks in `tests/test_edits.py` each start from the same generic episode and revise timing, expression, gesture, eyeline, or camera without touching the other tracks.

```bash
python3 -m cuervo_edit propose examples/reference-scene.json --shot sh_reaction \
  --instruction "Hold the reaction 12 more frames."
python3 -m cuervo_edit apply examples/reference-scene.json patch.json -o /tmp/revised.json
```

`propose` needs whichever provider is first available. See `docs/providers.md`.
