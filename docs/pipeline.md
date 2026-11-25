# Episode pipeline

Jobs run per shot. The episode, script, bible, pose table, voice profiles, and approval list are all inputs. None of them are built into the runner.

`plan` sends the script to `writing`, then that outline to `direction`. Both go through the model router: Claude, then Gemini, then Cursor. The result is a shot plan. It is not applied until you build an episode from it.

`run` dubs lines when you pass voice profiles (`voice_prep` on the same router), asks `review` for an advisory note, and renders each approved shot. A shot that is not approved stays out of the master. Rendered frames are cached by a hash of the shot and the pose table. The same hash on a later run does not draw again.

A dialogue, acting, or camera change changes that shot's hash. A new asset version is written onto a shot only when you opt that shot in with `adopt_asset`. Other shots keep the pin and the cached frames.

Failed draws retry once. FFmpeg encodes each shot, then concatenates the approved shots.

```bash
python3 -m cuervo_pipeline plan script.txt --bible bible.txt
python3 -m cuervo_pipeline run episode.json --approve sh_a --out build/
```
