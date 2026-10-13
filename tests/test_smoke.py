"""Smoke tests for the project skeleton."""

import app


def test_package_is_importable() -> None:
    assert isinstance(app.__version__, str)
    assert app.__version__
