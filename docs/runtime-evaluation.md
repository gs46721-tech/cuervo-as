# Runtime evaluation

Phase 0 does not integrate a 2D runtime. The blueprint asks for a benchmark before any lock-in. This note is the comparison to run, not a result.

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
