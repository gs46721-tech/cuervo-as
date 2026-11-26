# Cues: the command line of the animation

An agent changes an episode the way a person drives a command line. It writes cues, one per line. Read cues look around. Edit cues change one shot each and answer with a sentence a director can read.

```
scenes                         list the scenes
shots <scene>                  list the shots in a scene
show <shot>                    the camera, cast, tracks, and lines of a shot
find "<text>"                  lines that contain the text

hold <shot> <frames>           let the shot run longer
trim <shot> <frames>           take frames off the end
camera <shot> [preset] [--on <actor>] [--zoom <n>] [--x <n>] [--y <n>]
pose <shot> <track> <pose>     change the pose on a track
act <shot> <actor> <pose> [<start>..<end>]    add a gesture, look, or expression
move <shot> <track> <start>..<end>            retime a track
drop <shot> <track>            remove a track
say <shot> <line> "<text>"     rewrite a line of dialogue
cut <shot>                     remove the shot
```

Run them yourself:

```bash
python3 -m cuervo_edit cue examples/reference-scene.json "show sh_reaction"
python3 -m cuervo_edit cue examples/reference-scene.json "hold sh_reaction 12" \
  "camera sh_reaction close_up --on act_nia" -o /tmp/revised.json
```

## What each edit does

- `hold` and `trim` change the shot's length. Tracks that ran to the end of the shot still do. Later shots in the scene slide. `trim` will not cut into a line.
- `camera` sets the shot size and its matching zoom. `--on` centers on a character.
- `act` adds a track masked to the controllers its pose sets, so a gesture never fights the body or the mouth.
- `say` rewrites a line. When the project has its takes, the line is recorded again in the same voice, lip sync is rebuilt, and the shot is retimed around the new length. Without takes the line is marked as needing one.
- `cut` removes a shot and closes the gap. The last shot of a scene stays.

A locked track, camera, or line refuses the cue that would change it, in words the director can read. Every edit bumps the shot's revision. A pose must be one the character has.

## Typed patches

The older `edit_patch` path is still here for a single shot: `propose` asks the `ir_patch` route for one patch, and `apply` writes it. The editor uses cues.

```bash
python3 -m cuervo_edit propose examples/reference-scene.json --shot sh_reaction \
  --instruction "Hold the reaction 12 more frames."
```
