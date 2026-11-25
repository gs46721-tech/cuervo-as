# Cuervo

Phase 0 foundation for an AI-native 2D sitcom studio. This repository is the animation intermediate representation (Animation IR), the rig contract, and one reference scene. It does not render frames, synthesize voice, or apply natural-language direction.

The technical blueprint is [`docs/ai-animation-studio-blueprint.pdf`](docs/ai-animation-studio-blueprint.pdf). This slice is the blueprint's Phase 0 and the first week of its engineering checklist:

- style constraints, two characters, one living-room set, and a 32-second script
- Animation IR v0 as JSON Schema and Pydantic models
- acceptance tests, including a timing patch that holds one reaction for 12 more frames

Later phases (rig runtime, visemes, AI edits, the timeline editor, episode rendering) are out of scope here.

## Layout

| Path | Contents |
| --- | --- |
| `docs/` | Blueprint PDF, style guide, rig contract, IR notes, series bible |
| `schemas/animation-ir-v0.schema.json` | Checked-in JSON Schema, generated from the models |
| `src/cuervo_ir/` | Models, invariants, timing-patch apply, sample-to-frame conversion |
| `examples/` | Reference episode and the 12-frame hold patch |
| `tests/test_ir_acceptance.py` | Schema, scene, patch, and time-base tests |

## Validate

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
python3 -m cuervo_ir examples/reference-scene.json
```

`cuervo-validate examples/reference-scene.json` is the same check. Regenerate the schema and the example JSON after model changes:

```bash
python3 -c "from cuervo_ir.schema import write_schema; write_schema()"
python3 -m examples.reference_scene
```
