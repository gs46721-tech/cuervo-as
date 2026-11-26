# Cuervo

Software for producing editable 2D sitcom episodes. A series bible, characters, sets, and scripts are data a project supplies. The engine, the Animation IR schema, and the APIs do not embed one show.

Phase 0 is the intermediate representation, the rig contract, and a provider router. `examples/reference-scene.json` and `examples/sample-series/` are one sample episode used by tests. They are not the product.

The technical blueprint is [`docs/ai-animation-studio-blueprint.pdf`](docs/ai-animation-studio-blueprint.pdf).

## Layout

| Path | Contents |
| --- | --- |
| `docs/` | Blueprint, product style guide, rig contract, IR notes, provider routes |
| `schemas/animation-ir-v0.schema.json` | JSON Schema generated from the models |
| `src/cuervo_ir/` | IR models, timing patches, and the Claude / Cursor / Gemini router |
| `src/cuervo_runtime/` | Headless flat 2D preview. Not a permanent runtime choice |
| `src/cuervo_voice/` | Voice profiles, alignment, visemes. Vendor ids stay outside the IR |
| `src/cuervo_edit/` | Typed natural-language shot edits through the model router |
| `editor/` | React editor: agent threads, reviewable changes, stage, timeline |
| `src/cuervo_editor/` | Editor API: projects, threads, agent turns, undo history |
| `src/cuervo_pipeline/` | Shot jobs, cache, approvals, and FFmpeg assembly |
| `examples/` | Sample episode and sample series notes |
| `tests/` | Engine tests on a generic fixture, plus sample-episode tests |

## Validate

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
python3 -m cuervo_ir examples/reference-scene.json
python3 -m cuervo_runtime examples/reference-scene.json --shot sh_establish --frame 0 \
  --poses examples/sample-series/poses.json -o /tmp/frame.png
python3 -m cuervo_voice examples/reference-scene.json examples/sample-series/voices.json \
  -o /tmp/dubbed.json --wav-dir /tmp/takes
```

## Editor

```bash
cd editor && npm install && npm run build && cd ..
python3 -m cuervo_editor examples/reference-scene.json --poses examples/sample-series/poses.json
```

Open http://127.0.0.1:8000, type a direction, and review what the agent drafts. See [`docs/editor.md`](docs/editor.md).

Provider keys stay in the environment. See [`docs/providers.md`](docs/providers.md).
