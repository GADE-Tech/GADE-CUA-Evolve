# GADE CUA Evolve

A composable runtime for computer-use agents.

## Architecture

The package has six independent layers:

1. `AgentLoop`: schedules one or more agents and owns the task lifecycle.
2. `Agent`: owns prompts, the internal conversation loop, and action generation.
3. `Client`: hides OpenAI-compatible and Google GenAI SDK differences.
4. `EnvAdapter`: normalizes environments; OSWorld and a safe no-op adapter are included.
5. `Grounder`: resolves visual descriptions through a provider-neutral locate/confirm protocol.
6. `AgenticRewardModel`: plans end-state checks and verifies actor episodes without evaluator GT.

`GTA15Agent` ports the tool protocol and closed-loop behavior from OSWorld's
`mm_agents/gta1/gta15_agent.py`. Actor, grounder, and ARM models are independently
configured and may use Google GenAI or an OpenAI-compatible endpoint. Grounding
uses normalized 1000x1000 coordinates and verifies each point against a red-circle
crop. Each valid actor decision still makes one planning request.

## Install

```bash
pip install -e ".[google,dev]"
cp .env.example .env
```

Install OSWorld separately so the core package stays light:

```bash
pip install -e "/Users/bofeizhang/Documents/GADE Projects/OSWorld"
```

The current OSWorld checkout requires Python 3.12 or newer. Python 3.12 is the
recommended Volcengine runtime for this repository.

## CLI

```bash
gadecua
gadecua --arm
gadecua --task chrome/TASK_ID --arm
gadecua exec "Open Chrome and visit example.com"
gadecua exec "Open Chrome and visit example.com" --arm
gadecua exec --env osworldv1 --task chrome/TASK_ID --arm --evaluate
gade-cua config show --config configs/default.yaml
gade-cua list agents
gade-cua env probe --config configs/osworld_qwen3vl.yaml
gade-cua run --config configs/volcengine_gta15_gemini.yaml \
  --instruction "Open Firefox and visit example.com"
gade-cua run --config configs/openrouter_qwen35.yaml --instruction "..."
gade-cua run --config configs/osworld_qwen3vl.yaml \
  --instruction "Open Firefox and visit example.com"
```

With no subcommand, `gadecua` starts the Textual interface. Normal messages steer
the agent before its next decision; `/pause`, `/resume`, and `/stop` control the
session. The agent pauses for human confirmation when it believes the task is
complete. `--arm` adds automatic reward-agent feedback but does not prevent human
intervention.

`--evaluate` is separate from ARM and is accepted only for an OSWorld task JSON
that contains a native evaluator. The native score is computed once at the end
and is never sent to the actor or reward model. Free-form prompts have no native
score.

### Batch OSWorld runs

`gadecua batch` reads the standard OSWorld domain-to-task manifest and runs each
task in an isolated child process. `test_nogdrive.json` is the default manifest
(361 tasks); `test_all.json` contains 369 tasks including eight tasks that need
Google Drive state.

Start with a small smoke run:

```bash
gadecua batch --env osworldv1 \
  --domain chrome,gimp --limit 10 --workers 1 \
  --evaluate --output-dir results/batch/smoke
```

Run the no-Google-Drive suite with bounded concurrency:

```bash
gadecua batch \
  --manifest "/path/to/OSWorld/evaluation_examples/test_nogdrive.json" \
  --env osworldv1 --workers 2 --evaluate --resume \
  --output-dir results/batch/nogdrive-baseline
```

Add `--arm` for the feedback loop. Use `--shard-index N --num-shards M` to split
the deterministic task order across machines, and `--infra-retries` to retry
only child-process/infrastructure failures. A valid zero native score is never
retried. `--resume` skips tasks with a valid prior `result.json`, except when the
latest recorded attempt ended in an infrastructure failure.

Batch output contains per-domain task trajectories plus `attempts.jsonl`,
`batch_config.json`, per-attempt logs, and `summary.json`. Each worker owns one
disposable VM, so `--workers` must stay within ECS, EIP, and model API quotas.

Override any non-secret setting with dotted keys:

```bash
gade-cua run --config configs/default.yaml --instruction "..." \
  --set loop.max_steps=5 --set agent.coordinate_type=absolute
```

YAML contains only non-sensitive settings. API keys and cloud credentials belong
in `.env`. Runs write `result.json`, `traj.jsonl`, and screenshots under `results/`.

For GTA15, set `GEMINI_AK` and optionally override `GEMINI_MODEL` in `.env`.
The production profile contains separate `llm`, `grounder`, and `arm.llm`
sections. Set a section's provider to `openai` plus its `base_url`/environment
variable names to use an OpenAI-compatible service.
For Volcengine, the local OSWorld checkout accepts either `VOLCENGINE_*` or its
legacy `VOLCANO_ENGINE_*` credential names. The
`configs/volcengine_gta15_gemini.yaml` allocates a disposable ECS instance for each
run and deletes it during environment cleanup. Set `env.path_to_vm` only when a run
must target an existing instance.

## Extending

- Implement `EnvAdapter` and register it in `registry.py` to add an environment.
- Implement `Agent.predict` to add an agent.
- Override `AgentLoop.select_agent` for round-robin or router scheduling.

## Safety

Model-generated actions are untrusted. Execute them only in an isolated,
disposable environment such as an OSWorld VM. Host-side action execution is
intentionally unsupported.

ARM's optional `inspect_with_code` executes model-generated Python or Bash
directly inside the disposable VM. The verifier prompt requires read-only code,
and execution is timed out and audited, but there is deliberately no static
deny-list. Do not enable it against a personal or persistent machine.
