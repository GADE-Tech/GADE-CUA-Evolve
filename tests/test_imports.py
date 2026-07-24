"""Import smoke tests for the package scaffold."""


def test_package_import() -> None:
    import gade_cua_evolve

    assert gade_cua_evolve.__version__ == "0.1.0"


def test_cli_import() -> None:
    from gade_cua_evolve.cli import main

    assert callable(main)
