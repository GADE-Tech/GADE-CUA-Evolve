"""GADE CUA Evolve package."""

__all__ = ["RunConfig", "dry_run_task", "load_config", "run_task"]


def __getattr__(name: str):
    if name in __all__:
        from . import cli

        return getattr(cli, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
