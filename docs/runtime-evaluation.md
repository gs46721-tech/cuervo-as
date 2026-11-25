# Runtime evaluation

The blueprint says to benchmark at least two runtimes before locking in, and not to pick one yet. `cuervo_runtime` is the first headless adapter: flat shapes, integer frames, same bytes for the same episode. It is the preview called for in week 2. Rive, Spine, and PixiJS are still unscored.

Candidates named by the blueprint: Rive, Spine, and a custom PixiJS/WebGL adapter.

Score each candidate on the same reference scene once a rig exists:

| Question | What to record |
| --- | --- |
| Export | Can the master rig and the IR tracks round-trip without a private editor session? |
| License | Can we redistribute the runtime in a headless render worker and in the editor? |
| Control | Can code set every `cuervo.rig.v0` controller per frame, including holds on twos? |
| Deformation | Do face and limb poses match the approved model sheet at the extremes? |
| Determinism | Does the same shot JSON produce the same frames on two machines? |
| Headless | Can a worker step one frame at a time with no window? |

Do not pick a runtime in this slice. Integrating one is the next slice after this foundation.
