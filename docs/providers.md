# Model providers

LLM steps go through one router. The pipeline does not call Claude, Cursor, or Gemini directly, and it does not keep a single model for every step.

t3's provider relay was not reachable from this environment (the tunnel returned Cloudflare error 1033), so this router follows that shape: a named provider, a route per step, and `register` to add another. Voice synthesis is a separate adapter. It is not one of these three.

## Routes

| Step | Order | Why this order |
| --- | --- | --- |
| `writing` | Claude, Gemini, Cursor | Long dialogue that has to keep series constraints |
| `direction` | Claude, Gemini, Cursor | Blocking, shot choice, beat timing |
| `ir_patch` | Claude, Gemini, Cursor | A schema-valid patch, with the others as fallback |
| `asset_assist` | Gemini, Claude, Cursor | Image and model-sheet help |
| `editor_assist` | Cursor, Claude, Gemini | Reads a direction in the editor and picks the shots to change |
| `review` | Gemini, Claude, Cursor | A second pass, not the writer that drafted the line |
| `voice_prep` | Claude, Gemini, Cursor | Emotion and pronunciation for a line. Synthesis stays on a voice adapter |

The first available provider in the list runs the step. If it errors, the router tries the next. `register` adds a provider. Pass a new route table to send a step somewhere else. `only` forces one name.

## Credentials

The process environment supplies keys. The repo never stores them.

| Provider | Required | Optional |
| --- | --- | --- |
| Claude | `ANTHROPIC_API_KEY` | `CLAUDE_MODEL` (default `claude-sonnet-4-5`), `ANTHROPIC_BASE_URL` |
| Gemini | `GEMINI_API_KEY` | `GEMINI_MODEL` (default `gemini-2.5-pro`), `GEMINI_BASE_URL` |
| Cursor | `CURSOR_API_KEY` and `CURSOR_API_BASE` | `CURSOR_MODEL` (default `composer-2.5`) |

Cursor has no assumed host. Set `CURSOR_API_BASE` to the OpenAI-compatible chat-completions base you already use. Until both the key and the base are set, that provider is skipped and the route falls through.
