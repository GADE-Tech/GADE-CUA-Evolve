<div align="center">

# GADE CUA Evolve

### A Self-Evolving Multi-Agent System for Computer Use

**Planner reasons · Grounder locates · Coder executes · ARM verifies and evolves**

[![Project Website](https://img.shields.io/badge/Project-Website-557fa3?style=for-the-badge)](https://gade-tech.github.io/GADE-CUA-Evolve/)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![OSWorld 1.0](https://img.shields.io/badge/Benchmark-OSWorld%201.0-77779b?style=for-the-badge)](https://github.com/GADE-Tech/OSWorld)

**79.6% OSWorld 1.0 success rate** with Gemini 3.1 Pro Self-Evolve, up from a 76.0% baseline.<br>
**GUI + Coding reaches 76.0%**, compared with 72.5% for GUI-only execution.

<sub>Project Q2 experiment summary (2026). These are project experiment results, not claims about a live official leaderboard.</sub>

</div>

GADE CUA Evolve is a composable runtime for agents that act on a real desktop, inspect the
result, and improve through evidence-backed feedback. The supported production profile runs
**OSWorld v1 on disposable Volcengine Ubuntu VMs**; model-generated GUI actions and code never
execute on the host machine.

## System at a glance

| Agent | Responsibility |
| --- | --- |
| **Planner** | Reasons from the task, screenshot, action history, and verifier feedback; selects one next tool. |
| **Grounder** | Resolves visual descriptions onto a normalized coordinate plane and confirms target locations. |
| **Coder** | Handles bounded Python/Bash subtasks inside the disposable VM and returns execution evidence. |
| **ARM** | Plans end-state checks, inspects the live GUI and persisted artifacts, then stops or feeds a concrete fix into the next episode. |

```mermaid
flowchart LR
    CLI["CLI / TUI"] --> CONFIG["RunConfig"]
    CONFIG --> LOOP["AgentLoop"]
    LOOP --> PLANNER["Planner"]
    PLANNER --> GROUND["Grounder"]
    PLANNER --> CODER["Coder"]
    GROUND --> ENV["OSWorld EnvAdapter"]
    CODER --> ENV
    PLANNER --> ENV
    ENV --> EVIDENCE["Screenshot + files + trajectory"]
    EVIDENCE --> ARM["Agentic Reward Model"]
    ARM -->|feedback| PLANNER
    ARM -->|verified| DONE["Stop"]
```

The runtime keeps five boundaries explicit:

1. `AgentLoop` owns scheduling, episodes, recording, evaluation, and cleanup.
2. `Agent` owns prompts, task-local history, and normalized decisions.
3. `Client` hides Google GenAI and OpenAI-compatible SDK differences.
4. `EnvAdapter` is the only path to the isolated desktop and VM code execution.
5. `TrajectoryRecorder` writes screenshots, JSONL events, results, and optional video.

## Installation

Python 3.12 is recommended for the pinned OSWorld checkout.

```bash
git clone https://github.com/GADE-Tech/OSWorld.git
git -C OSWorld checkout b7db4d8c85d9e95e0b1db44de5bec954cf37f0cf

git clone https://github.com/GADE-Tech/GADE-CUA-Evolve.git
cd GADE-CUA-Evolve
uv sync --extra google --extra dev
uv pip install -e ../OSWorld
export OSWORLD_ROOT="$(cd ../OSWorld && pwd)"
cp .env.example .env
```

[`GADE-Tech/OSWorld`](https://github.com/GADE-Tech/OSWorld) is pinned for reproducibility. At
the commit above it contains no GADE-specific source changes; it is an unmodified upstream
OSWorld commit. OSWorld stays a separate editable dependency so this package remains focused on
the agent runtime.

For a reproducible Volcengine guest image, network rules, Coder dependencies, sanitization,
smoke tests, and the no-EIP + Squid scaling topology for training rollouts, follow the
**[hosted Volcengine OSWorld v1 Image Guide](https://gade-tech.github.io/GADE-CUA-Evolve/volcengine-osworld-v1.html)**
or read its [Markdown source](docs/volcengine-osworld-v1.md).

## Quickstart

Run a benchmark task by domain and task ID:

```bash
gadecua --env osworldv1 \
  --task chrome/2ae9ba84-3a0d-4d4c-8338-3a1478dc5fe3
```

Useful variants:

```bash
gadecua --env osworldv1 --task chrome/TASK_ID --verbose
gadecua --env osworldv1 --task chrome/TASK_ID --arm --evaluate
gadecua --env osworldv1 --task chrome/TASK_ID --set loop.max_steps=20

gadecua exec "Open Chrome and visit example.com"
gadecua exec "Open Chrome and visit example.com" --arm

gade-cua config show --config configs/volcengine_gta15_gemini.yaml
gade-cua env probe --config configs/volcengine_gta15_gemini.yaml \
  --check-code --check-services
gade-cua list agents
gade-cua list envs
```

With no subcommand, `gadecua` opens the Textual interface. Normal messages steer the Planner
before its next decision; `/pause`, `/resume`, and `/stop` control the session. The runtime asks
for human confirmation when it believes a task is complete. `--arm` adds automatic reward-agent
feedback without removing human control.

`--evaluate` is separate from ARM. It is accepted only for OSWorld task JSON containing a native
evaluator, is computed once at the end, and is never exposed to the Planner, Coder, or ARM.

## Self-evolution and GUI + Coding

The default `osworldv1` profile composes independent Planner, Grounder, Coder, and ARM model
sections. They currently use the same Gemini environment variables, but each client can be
changed independently through YAML.

The Planner may call `call_code_agent` for one clear backend subtask. The Coder then performs a
bounded tool loop using `run_python`, `run_bash`, or `finish`. Every command is executed through
`EnvAdapter` inside the disposable VM; failures and truncated, redacted evidence return to the
Coder, and the final report returns to the Planner. The Planner must inspect the refreshed
desktop or files before treating the delegated work as complete.

ARM works at the episode boundary. It checks the requested end state against the current GUI,
the trajectory, and optional read-only VM inspection. A failed check becomes input to the next
Planner episode; success or infeasibility stops the loop.

## Batch OSWorld runs

`gadecua batch` reads a standard OSWorld domain-to-task manifest and runs every task in an
isolated child process. `test_nogdrive.json` contains 361 tasks; `test_all.json` adds eight tasks
that require Google Drive state.

Start with a small smoke run:

```bash
gadecua batch --env osworldv1 \
  --domain chrome,gimp --limit 10 --workers 1 \
  --evaluate --output-dir results/batch/smoke
```

Run the no-Google-Drive suite with bounded concurrency:

```bash
gadecua batch \
  --manifest "$OSWORLD_ROOT/evaluation_examples/test_nogdrive.json" \
  --env osworldv1 --workers 2 --evaluate --resume \
  --output-dir results/batch/nogdrive-baseline
```

Add `--arm` for self-evolving episodes. Use `--shard-index N --num-shards M` to split the
deterministic task order and `--infra-retries` to retry infrastructure failures only. A valid
native score of zero is never retried. Each worker owns one disposable VM, so keep concurrency
within ECS, EIP, model API, and budget quotas.

Batch output includes per-task trajectories, `attempts.jsonl`, `batch_config.json`, logs, and
`summary.json`. Individual runs write `initial_screenshot.png`, action screenshots, `traj.jsonl`,
`result.json`, ARM evidence, and optional `recording.mp4` under `results/`.

## Configuration

YAML contains non-sensitive values only. Model API keys, cloud credentials, and the VM password
belong in `.env` or the process environment. The default Volcengine profile allocates an ECS
instance from `VOLCENGINE_IMAGE_ID` and deletes it during cleanup; set `env.path_to_vm` only when
intentionally targeting an existing instance.

Override any non-secret setting with dotted keys:

```bash
gade-cua run --config configs/volcengine_gta15_gemini.yaml \
  --instruction "Open Firefox and visit example.com" \
  --set loop.max_steps=5 \
  --set coder.max_rounds=10
```

The CLI resolves OSWorld in this order: `--osworld-root`, `OSWORLD_ROOT`, then a sibling
`../OSWorld` checkout. Missing dependencies produce an installation hint rather than falling back
to a machine-specific path.

## Extending

- Add an environment by implementing `EnvAdapter`; keep provider imports lazy and cleanup safe
  after partial initialization.
- Add a UI actor by implementing `Agent.predict()` and returning only normalized `AgentStep`
  values.
- Add a model provider behind `Client.complete()` and keep its SDK in an optional dependency.
- Add a scheduler by subclassing `AgentLoop`; environment lifecycle stays at the loop boundary.

## Safety

Model-generated actions and Coder programs are untrusted. Run them only in an isolated,
disposable OSWorld VM. Host-side action or code execution is intentionally unsupported.

Coder execution may modify files and run arbitrary Python or Bash inside the guest. ARM's
`inspect_with_code` remains a separate read-only verification tool. Neither capability should
be enabled against a personal machine, a persistent desktop, or an image containing real
credentials. After interrupted cloud runs, always verify that temporary instances and EIPs were
deleted.

## Acknowledgements

We thank the creators of GTA for the action-agent design that informed the Planner and Grounder,
OSWorld for its real-computer environment and benchmark, and WindowsAgentArena for its Windows
computer-use evaluation work.

## Project links

- [Interactive project website and experiment details](https://gade-tech.github.io/GADE-CUA-Evolve/)
- [Scalable rollout infrastructure overview](https://gade-tech.github.io/GADE-CUA-Evolve/#infra)
- [Hosted Volcengine image and infrastructure guide](https://gade-tech.github.io/GADE-CUA-Evolve/volcengine-osworld-v1.html)
- [Pinned GADE-Tech OSWorld fork](https://github.com/GADE-Tech/OSWorld)
- [OSWorld benchmark](https://github.com/xlang-ai/OSWorld)
