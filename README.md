# GADE CUA Evolve

GADE CUA Evolve is a Python package scaffold for experimenting with evolutionary loops around computer-use agents. The project is intended to provide a clean foundation for composing agents, LLM adapters, provider integrations, and evaluation or improvement loops.

## Project goals

- Define a standard Python package layout for reusable agent components.
- Keep agent logic, loop orchestration, LLM access, and external providers separated.
- Expose a small command-line entry point for smoke testing and future workflows.
- Provide a testable baseline that can grow into GADE-style computer-use agent experiments.

## Installation

Install the package in editable mode from the repository root:

```bash
python -m pip install -e .
```

For development tools, install the `dev` optional dependencies:

```bash
python -m pip install -e '.[dev]'
```

For LLM provider integrations, install the `llm` optional dependencies:

```bash
python -m pip install -e '.[llm]'
```

## Minimal running example

After installation, run the console script:

```bash
gade-cua
```

You can also invoke the module directly from Python:

```python
from gade_cua_evolve.cli import main

main()
```

Both entry points currently print a short readiness message while the package architecture is being expanded.

## Architecture

```text
src/gade_cua_evolve/
├── agents/      # Agent abstractions and implementations
├── loops/       # Evaluation, evolution, and orchestration loops
├── llm/         # LLM client interfaces and adapters
├── providers/   # External service, environment, and tool providers
└── cli.py       # Console-script entry point
```

The package uses a `src/` layout to avoid accidental imports from the repository root and to keep tests aligned with installed-package behavior.
