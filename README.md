# GADE CUA Evolve

GADE CUA Evolve provides a lightweight command-line interface and Python API for running computer-use tasks with configurable LLM and computer providers.

## CLI usage

Run a task with a YAML or JSON configuration file:

```bash
gade-cua run --task "Open the example page and summarize it" --config examples/config.openai.yaml
```

Validate a task and configuration without executing the run:

```bash
gade-cua dry-run --task "Open the example page and summarize it"
```

Configuration files may be YAML or JSON and can define the LLM provider, model name, computer provider, maximum steps, and trajectory output directory. See [`examples/config.openai.yaml`](examples/config.openai.yaml):

```yaml
llm:
  provider: openai
  model: gpt-4.1-mini-example
computer:
  provider: local_stub
max_steps: 10
trajectory:
  output_dir: trajectories/openai-example
```

## Python API usage

Use `RunConfig` and `run_task` directly from Python:

```python
from gade_cua_evolve import RunConfig, run_task

config = RunConfig(
    llm_provider="openai",
    model_name="gpt-4.1-mini-example",
    computer_provider="local_stub",
    max_steps=5,
    trajectory_output_dir="trajectories/basic-example",
)

run_task("Open the example page and summarize it", config)
```

A complete script is available at [`examples/run_basic.py`](examples/run_basic.py).
