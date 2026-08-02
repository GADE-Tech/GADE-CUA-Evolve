# GADE CUA Evolve

A composable runtime for computer-use agents.

## Architecture

The package has four independent layers:

1. `AgentLoop`: schedules one or more agents and owns the task lifecycle.
2. `Agent`: owns prompts, the internal conversation loop, and action generation.
3. `Client`: hides OpenAI-compatible and Google GenAI SDK differences.
4. `EnvAdapter`: normalizes environments; OSWorld and a safe no-op adapter are included.

`GTA15Agent` ports the tool protocol and closed-loop behavior from OSWorld's
`mm_agents/gta1/gta15_agent.py`. It uses Google GenAI `generateContent` for both
planning and GUI grounding. Grounding points use Gemini's normalized 1000x1000
coordinate system. Each decision attempt makes one planning request; GTA1's
multi-action sampling and judge selection are intentionally not included.

## Install

```bash
pip install -e ".[google,dev]"
cp .env.example .env
```

Install OSWorld separately so the core package stays light:

```bash
pip install -e "/Users/bofeizhang/Documents/GADE Projects/OSWorld"
```

## CLI

```bash
gade-cua config show --config configs/default.yaml
gade-cua list agents
gade-cua env probe --config configs/osworld_qwen3vl.yaml
gade-cua run --config configs/volcengine_gta15_gemini.yaml \
  --instruction "Open Firefox and visit example.com"
gade-cua run --config configs/openrouter_qwen35.yaml --instruction "..."
gade-cua run --config configs/osworld_qwen3vl.yaml \
  --instruction "Open Firefox and visit example.com"
```

Override any non-secret setting with dotted keys:

```bash
gade-cua run --config configs/default.yaml --instruction "..." \
  --set loop.max_steps=5 --set agent.coordinate_type=absolute
```

YAML contains only non-sensitive settings. API keys and cloud credentials belong
in `.env`. Runs write `result.json`, `traj.jsonl`, and screenshots under `results/`.

For GTA15, set `GEMINI_AK` and optionally override `GEMINI_MODEL` in `.env`.
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
