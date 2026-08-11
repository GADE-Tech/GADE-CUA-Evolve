# GADE CUA Evolve repository guide

## Purpose

This repository is a composable computer-use-agent runtime. The production path is:

```text
CLI -> RunConfig -> registry/build_components
    -> AgentLoop -> Agent -> Client
                 -> EnvAdapter
                 -> TrajectoryRecorder
```

The currently validated end-to-end profile is `GTA15Agent + GoogleGenAIClient +
OSWorldEnv + ReActLoop`, running OSWorld on a disposable Volcengine VM.

Keep runtime code under `src/gade_cua_evolve/`. Do not recreate the old top-level
`gade_cua_evolve/` package or the old `providers/` layer: cloud/desktop lifecycle is
owned by OSWorld and wrapped by `EnvAdapter`.

## Module design

### `config.py`

Pydantic models define the complete non-secret run configuration:

- `LLMConfig`: provider, model, generation parameters, and names of secret env vars.
- `AgentConfig`: agent selection, history, grounding, and image settings.
- `EnvConfig`: environment/provider settings passed to the adapter.
- `LoopConfig`: step limits, delays, output directory, and video recording.
- `TaskSpec`: normalized task ID, instruction, and provider-specific raw task data.
- `RunConfig`: top-level composition of the four configuration sections.

YAML must contain only non-sensitive values. `resolve_env()` loads credentials from
the process environment first and `.env` second. Never serialize or log secret values.

### `llm/`: Client boundary

`Client.complete(messages, **overrides) -> LLMResponse` is the provider-neutral,
synchronous generation contract. Neutral responses contain text, reasoning, usage,
and zero or more `ToolCall` objects.

- `GoogleGenAIClient` uses `google-genai` `models.generate_content`.
- `OpenAICompatClient` uses OpenAI-compatible chat completions.
- `factory.py` is the only place that selects an SDK-specific client.

Keep provider SDK imports inside their implementation modules so optional dependencies
remain optional. Google function responses are intentionally encoded as a `user` turn;
the Gemini 3.5 endpoint rejects a literal `tool` role even though the neutral history
uses that role.

### `agents/`: Agent boundary

`Agent` owns prompt construction, task-local context, and conversion of a model response
into one or more environment actions. `AgentState` is cleared by `Agent.reset()` for every
task. `AgentStep` is the only value returned to a loop.

`GTA15Agent` is the Gemini `generateContent` port of OSWorld
`mm_agents/gta1/gta15_agent.py`:

- One planning request is made per valid decision attempt.
- There is no parallel candidate sampling, candidate ranking, or judge model.
- Internal retries are allowed only for no tool call, multiple tool calls, or another
  invalid response. A valid response may contain at most one tool call.
- `TERMINATE` maps to `DONE`; `INFEASIBLE` maps to `FAIL`.
- GUI tools are declared in `gta15_tools.py` and rendered to OSWorld `pyautogui` code.
- Visual tools use `GeminiGrounder`. Grounding output is normalized to a 1000x1000
  coordinate plane and then scaled to the actual screenshot dimensions.
- Grounding calls are separate from the one planning call and are made only when a tool
  needs a visual point.

`Qwen3VLAgent` is a second Agent implementation used to validate that the abstractions
are not Gemini-specific. Its image preprocessing, response parser, and prompts live in
`image.py`, `parsing.py`, and `prompts.py`.

### `envs/`: EnvAdapter boundary

`EnvAdapter` normalizes external desktop runtimes through:

- `reset(task) -> Observation`
- `observe() -> Observation`
- `step(action, pause) -> StepOutcome`
- optional `evaluate()`, recording, and cleanup hooks

`OSWorldEnv` lazily imports `desktop_env.desktop_env.DesktopEnv`, passes through OSWorld
task data, normalizes observations, delegates evaluation, and always owns environment
cleanup. `NoopEnv` is the safe adapter for unit tests and local control-flow checks.

For the current OSWorld image, TCP 5000 is the control API and TCP 9222 proxies Chrome
DevTools for setup/evaluation. Chrome's 1337 port stays inside the VM; do not expose it in
the security group. TCP 5910 is optional noVNC access.

### `loops/`: AgentLoop boundary

`AgentLoop` owns high-level scheduling and the full task lifecycle. It receives a named
mapping of agents so future routers or multi-agent schedulers can override `select_agent`.

`ReActLoop` currently:

1. resets the environment and records the initial screenshot;
2. resets all agents;
3. selects an agent and requests its next `AgentStep`;
4. executes every rendered action through `EnvAdapter`;
5. returns action outcomes to the selected agent;
6. records screenshots and JSONL trajectory entries;
7. evaluates, stops recording, and closes the environment in nested `finally` blocks.

Do not bypass `EnvAdapter` to execute model-generated actions on the host machine.

### `registry.py`, `trajectory.py`, and `cli.py`

- `registry.py` is the explicit composition root for agents, environments, and loops.
- `TrajectoryRecorder` writes `initial_screenshot.png`, one screenshot per action,
  `traj.jsonl`, and `result.json`; the loop writes `recording.mp4` when enabled.
- `cli.py` resolves configuration/task references and exposes both `gadecua` and
  `gade-cua` entry points.

Run output belongs under `results/` and is not source code. Preserve successful runs
unless the user explicitly asks to remove them.

## Installation and configuration

Python 3.10 or newer is required. For the Gemini/OSWorld path:

```bash
uv sync --extra google --extra dev
uv pip install -e "/path/to/OSWorld"
cp .env.example .env
```

Set at least these values in `.env`:

```dotenv
GEMINI_AK=...
GEMINI_MODEL=gemini-3.5-flash-lite
VOLCENGINE_ACCESS_KEY_ID=...
VOLCENGINE_SECRET_ACCESS_KEY=...
VOLCENGINE_IMAGE_ID=...
VOLCENGINE_SUBNET_ID=...
VOLCENGINE_SECURITY_GROUP_ID=...
```

The CLI searches `OSWORLD_ROOT` first. If it is unset, this checkout currently defaults
to `/Users/bofeizhang/Documents/GADE Projects/OSWorld`.

## Usage

Run an OSWorld task by domain and task ID:

```bash
gadecua --env osworldv1 \
  --task chrome/2ae9ba84-3a0d-4d4c-8338-3a1478dc5fe3
```

Useful variants:

```bash
gadecua --env osworldv1 --task chrome/TASK_ID --verbose
gadecua --env osworldv1 --task chrome/TASK_ID --set loop.max_steps=20
gade-cua run --config configs/volcengine_gta15_gemini.yaml \
  --instruction "Open Chrome and complete the requested task"
gade-cua config show --config configs/volcengine_gta15_gemini.yaml
gade-cua list agents
gade-cua list envs
```

`configs/volcengine_gta15_gemini.yaml` uses `env.path_to_vm: null`, so OSWorld allocates
a disposable VM and deletes it during `close()`. Only set `path_to_vm` when intentionally
targeting an existing instance.

## Adding an implementation

### Add an Agent

1. Subclass `Agent` and implement `predict()`.
2. Keep all mutable task context on the agent and clear it from `reset()`.
3. Return only normalized `AgentStep` values.
4. Register the class in `registry.AGENTS`.
5. Add focused parsing/context tests and at least one loop-level test.

### Add a Client

1. Subclass `Client` and translate neutral messages into the provider SDK format.
2. Translate the first provider candidate/choice into `LLMResponse`.
3. Keep retries limited to transient provider failures.
4. Add the provider to `LLMConfig.provider` and `build_llm_client()`.
5. Put the SDK in an optional dependency group and test translation without network calls.

### Add an EnvAdapter

1. Subclass `EnvAdapter` and normalize reset/observe/step results.
2. Make `close()` safe after partial initialization and failures.
3. Keep provider-specific imports lazy.
4. Register it in `registry.ENVS` and add lifecycle tests.

### Add an AgentLoop

1. Subclass `AgentLoop` and implement `run()`.
2. Keep scheduling at this layer; do not move environment lifecycle into agents.
3. Guarantee recording/environment cleanup with `finally` blocks.
4. Register it in `registry.LOOPS` and test terminal and exception paths.

## Validation before handoff

Run all of the following after changing runtime code:

```bash
uv run ruff check .
uv run pytest -q
uv run gadecua --help
uv build
```

For GTA15 changes, explicitly test single tool calls, no tool calls, multiple tool calls,
`TERMINATE`, `INFEASIBLE`, grounding scaling, and function-response history conversion.
Do not reintroduce planning candidates, judge prompts, or judge configuration.

## Repository hygiene and safety

- Do not commit `.env`, credentials, VM passwords, logs, `results/`, `__pycache__`,
  `*.egg-info`, or one-off cloud diagnostics.
- Keep generated output out of `src/` and `tests/`.
- Do not add compatibility aliases without an active external caller and a removal plan.
- Never execute generated `pyautogui` actions on a personal host.
- Prefer disposable VMs; always verify temporary cloud instances are deleted after a run.
- Preserve unrelated user changes in a dirty worktree.
