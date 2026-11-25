# Series data

Cuervo is software for any series. A series bible, characters, sets, and scripts are documents the user supplies. They are not part of the engine, the JSON Schema, or the HTTP API.

The sample show under `examples/sample-series/` and the episode at `examples/reference-scene.json` exist so tests and demos have something to load. Nothing in `src/` names those characters, that set, or that script.

A project is an Animation IR episode plus whatever notes the user keeps beside it. Asset ids, actor ids, and line text are fields on that document.
