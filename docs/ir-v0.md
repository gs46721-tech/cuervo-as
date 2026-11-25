# Animation IR v0

The IR is the editable scene description. Agents, later, propose patches against it. This slice validates documents and applies one kind of patch. It does not compile curves or draw frames.

Schema: [`schemas/animation-ir-v0.schema.json`](../schemas/animation-ir-v0.schema.json), generated from `src/cuervo_ir/models.py`. Regenerating is part of the acceptance test, so the file cannot drift from the models.

## Document

An episode pins a library of characters, rigs, backgrounds, and props by id and `major.minor.patch` version. Scenes contain shots. A shot carries:

- `shot_id`, `scene_id`, `fps`, `start_frame`, `duration_frames`
- version-pinned `asset_refs`
- `camera` preset, framing, transform, keyframes, constraints
- `actors` with rig instance, stage transform, facing, depth, visibility
- `action_tracks` for pose, gesture, gaze, expression, locomotion, and secondary motion
- `dialogue_tracks` with speaker, line id, text, and optional voice-take pin
- `locks` and `provenance`

`alignment` and `visemes` start empty. The voice pass fills them and sets the take id and version together. Vendor voice ids stay on the voice profile, not in this document. The sample episode is stored before that pass, so those fields are empty there.

## Time and space

Shot-local track time is a half-open frame interval `[start_frame, end_frame)`. The scene timeline places each shot at `start_frame` for `duration_frames`. Shots in a scene are ordered and do not overlap. The scene's `target_runtime_frames` must cover the placed shots.

Stage and camera coordinates are in pixels. Stage origin is the floor at the center of the set, +x to the right, +y up. Each transform names its space.

Audio sample time converts without floats:

- frame F starts at sample `(F * sample_rate) // fps`
- sample S falls in frame `(S * fps) // sample_rate`

That conversion is `cuervo_ir.frame_time`. The reference mix is 24 fps and 48 kHz when a take arrives. No take is stored yet.

## Invariants the schema objects also enforce

- Episode, shot, character, and rig frame rates agree.
- Every actor's character and rig resolve to the library version pinned on the shot.
- The scene background is pinned on every shot.
- Poses and controller masks stay inside `cuervo.rig.v0` plus that character's extensions.
- Dialogue lines in a shot do not overlap.
- Two action tracks for the same actor cannot share priority, time, and a controller.
- A lock names a track that exists.

## Timing patch

`examples/hold-reaction-12.patch.json` is a sample timing edit against the sample episode: hold one reaction 12 more frames. The same patch shape applies to any shot id and track id.

`apply_timing_patch` requires the shot's current revision, refuses a track whose lock includes `timing`, and then:

- moves only the named action tracks
- grows that shot's duration by `extend_shot_frames`
- moves later shots in the same scene later by the same count, without editing their contents
- grows the scene target by the same count
- records the patch id as the new provenance source

Dialogue text, camera, actors, and unmentioned tracks stay as they were. A track that would end past the shot is rejected.
