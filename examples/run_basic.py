"""Basic Python API usage for GADE CUA Evolve."""

from gade_cua_evolve import RunConfig, run_task


config = RunConfig(
    llm_provider="openai",
    model_name="gpt-4.1-mini-example",
    computer_provider="local_stub",
    max_steps=5,
    trajectory_output_dir="trajectories/basic-example",
)

run_task("Open the example page and summarize it", config)
