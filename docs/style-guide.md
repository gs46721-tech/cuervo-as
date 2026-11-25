# Style guide

Traditional television sitcom animation. Persistent model sheets, limited animation, reusable locations, expressive poses, deliberate pauses. The reference scene is the only picture this slice defines.

## Picture

- 24 frames per second. Timeline fields are integer frames.
- Default motion is on twos: stepped holds, then a new pose. Dialogue boundaries may fall on ones.
- Drawings hold. Anticipation and follow-through are pose changes, not interpolated acting.
- Line is clean and even. Flat local color. No lighting change inside a shot.
- Characters keep the proportions and costume on their model sheet for the whole scene.
- The camera cuts between approved presets. It does not drift unless a shot's camera track says so.

## Acting

- Emotion reads from a small pose library: brow, eyes, mouth, and a gesture. One idea at a time.
- A joke gets a hold. The reference button is a look at a television that never turns on.
- Eyelines are explicit gaze tracks. A character looking at the other, or at the television, says so in the shot.
- Hands do one thing. A shrug and a point do not overlap on the same arm controllers.
- No walk, fight, or character exit in this scene. Both stay seated.

## What this slice does not decide

Typography for titles, a full color script, and music. Stems, dubbing, and visemes belong to the voice slice. The renderer is not chosen; see [runtime-evaluation.md](runtime-evaluation.md).
