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

OpenAI is a fourth provider: `OPENAI_API_KEY`, and optionally `OPENAI_BASE_URL`. It has no default model, so give it one in each role you put it on, or set `OPENAI_MODEL`.

## Agents on this computer

Cuervo can use the coding agents a person already has installed and signed in to. No API key is involved. The agent runs under the account its owner signed in with.

| Agent | Program | How it is run | Sign in with |
| --- | --- | --- | --- |
| Claude Code | `claude` | `claude -p --output-format json`, prompt on standard input | `claude auth login` |
| Codex | `codex` | `codex exec --output-last-message <file> -`, prompt on standard input | `codex login` |
| Cursor | `agent` or `cursor-agent` | `agent -p --output-format text <prompt>` | `agent login` |
| Antigravity | `agy` | `agy acp`, the Agent Client Protocol on standard input and output | Sign in with Google in Antigravity |

They are provider names `claude-code`, `codex`, `cursor-agent`, and `antigravity`. Each joins the end of every route, so a saved API key is still used first, and a person with no key can work from a signed-in agent alone. Give them their own jobs on the **Who does what** tab like any other provider.

The editor's **Accounts and models** screen lists them under **On this computer**, shows which are installed, and has a **Test** button that sends one short real request. Set a model there, or a path to the program when it is not on `PATH`. The same settings are `CUERVO_CLAUDE_CODE_BIN`, `CUERVO_CODEX_BIN`, `CUERVO_CURSOR_BIN`, `CUERVO_ANTIGRAVITY_BIN`, and the matching `..._MODEL` variables.

Each request runs in an empty scratch folder, never in the project. Here an agent is asked only for text, so its tools are off: Claude Code runs with no tools, no MCP servers, and no saved session. Codex runs in its read-only sandbox. An Antigravity request for a tool or a file is refused.

The Claude Code path has been run against the real program, including whole editor turns. Codex, Cursor, and Antigravity are tested against stand-in programs that take the same arguments. They have not been run against the real programs from this repo.

This follows how T3 Code drives the same agents for text: headless `claude -p` and `codex exec`, and ACP for Antigravity.

## A model for each job

The routes above are the defaults. Each person can change them in the editor under **Accounts and models**, on the **Who does what** tab. The choice is saved to `~/.cuervo/models.json` (`CUERVO_MODELS_FILE` moves it), and the pipeline commands read the same file.

| Role | Step | What it does |
| --- | --- | --- |
| Orchestration | `editor_assist` | Runs the editor: reads notes, looks through the episode, makes the changes |
| Screenwriting | `writing` | Outlines an episode and writes its scenes |
| Direction | `direction` | Storyboards scenes and chooses the acting |
| Review | `review` | Gives notes on scenes, and judges contests by default |
| Voice direction | `voice_prep` | Emotion and pronunciation for a line |
| Image generation | `image` | Paints set backgrounds |

A role holds a list of entries. An entry is a provider and, optionally, one of its models. The same provider can appear twice with two different models.

## Taking turns, or competing

**Take turns** uses the first entry that is connected. The next one steps in only if it fails.

**Compete** sends the request to every connected entry at once.

1. An answer in the wrong form is dropped. The editor checks that a reply parses as cues. The storyboard checks that every line is covered once and in order.
2. If one answer is left, it wins.
3. Otherwise a judge reads the task and the answers and names the best one, with a one-sentence reason. The judge is the role's own judge if it has one, else the review model. A judge that did not write an answer is tried first.
4. If no judge can answer, the first entry stands.

A contest costs one call per entry, plus one for the judge. In the editor, a turn shows who won each round and why. `produce` prints how many contests each model won.

For images there is no judge. Every image model paints each new set from the same prompt, and a person picks one on the World screen.
