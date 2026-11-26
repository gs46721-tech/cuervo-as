# Episode pipeline

A script becomes a finished episode in four stages, after the world is built. Each stage writes a file, and that file is the gate for the next stage. The script, the series kit, and the approvals are inputs. None of them are built into the runner.

```bash
python3 -m cuervo_pipeline produce script.txt --series series.json --out build/
```

| Stage | Writes | What happens |
| --- | --- | --- |
| world | `world/` | Every character and set in the kit is built once from its design. See [world.md](world.md). |
| script | `script.json` | The screenplay is read into scenes, lines, and action. No model call, so no line is lost. |
| storyboard | `storyboard.json` | The `direction` route cuts each scene into shots and says who each shot is on. |
| animation | `takes/`, `episode.json`, `poses.json`, `boards/` | Every line is recorded. Shots are timed to the takes. Lip sync, acting, eyelines, and blinks are laid in. |
| polish | `notes.json`, `shots/`, `episode.mp4` | Checks and an advisory review run. Approved shots render and join with the soundtrack. |

`--through storyboard` stops after a stage so you can look at its file. A stage whose file exists is not redone, so hand edits to `storyboard.json` and editor work on `episode.json` are kept. `--rebuild` redoes the storyboard and the episode. A storyboard made from a different script is refused until you pass `--rebuild`.

## The series kit

`series.json` holds the cast, the sets, and the pose table. See `examples/sample-series/series.json`.

Each character has an asset id, a rig id, the names a script may use for them, a rest pose, any poses of their own, and a voice. Each set has an asset id and the names a scene heading may use. A character keeps the same side of the stage in every scene.

## Script

The parser reads scene headings (`INT.`, `EXT.`), speaker cues in capitals, `Name: line`, parentheticals, and action paragraphs. A speaker who is not in the kit stops the run. A long speech is split at sentence ends so each line is one take.

`write` drafts a screenplay from a premise through the `writing` route. It outlines first and then writes one scene per call.

```bash
python3 -m cuervo_pipeline write premise.txt --series series.json --minutes 22 -o script.txt
```

## Storyboard

The director's cut for a scene must cover every line once and in order. If it does not, or no provider is configured, that scene is cut by a fixed grammar: a wide to establish, a two-shot for the exchange, close-ups on the speaker, a silent reaction after an exclamation, and a reaction to end on. `--no-director` uses the grammar for everything.

## Animation

Dialogue is recorded first. A line is as long as its take, rounded up to a frame, and a shot is as long as its lines plus a lead, gaps, and a tail. The camera scale follows the shot size, and a tight shot centers on its character. `boards/` gets one contact sheet per scene.

Acting comes from the `direction` route, one scene per call: a gesture and an expression for the speaker and a reaction for the listener, chosen from that character's poses. Without a provider, a question gets a shrug, an exclamation gets a point and a reaction, and listeners look at the speaker.

## Polish

`notes.json` lists what to fix or look at, by shot: a line with no take, a take that no longer matches its text, a line cut short, estimated lip sync, a shot over 12 seconds, a shot under half a second, and a cut between two identical framings. The `review` route adds advisory notes per scene. Notes never change a shot.

Rendered shots are cached by a hash of the shot and the pose table, in `shots/cache.json`. A later run draws only the shots that changed. `--approve sh_0004` renders only the shots you name. The soundtrack is built as one continuous track and muxed once, so sound and picture stay in step for the whole episode.

## Perfecting in the editor

```bash
python3 -m cuervo_editor build/episode.json --poses build/poses.json --takes build/takes --world build/world
```

Change shots there, download the episode over `build/episode.json`, and run `produce` again. Only the changed shots render.

## Shot jobs

`run` renders an episode you already have. `plan` is the older two-call outline.

```bash
python3 -m cuervo_pipeline run episode.json --approve sh_a --out build/
```

## Picture

Frames are composed from the world's approved art. `--size 1280x720` sets the frame size. Shots are drawn in parallel, one process per core up to eight. A shot whose art is missing from the world falls back to plain stand-in shapes.

## What this does not do

It does not generate art with an image model, add music or sound effects, or draw views other than three-quarter. Characters in a scene stand or sit where the cast order puts them. They do not walk across the set.
