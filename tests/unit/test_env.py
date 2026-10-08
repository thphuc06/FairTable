"""P0-1: the environment matches the versions pinned in pyproject.toml and constraints.txt."""
from importlib.metadata import version

import pytest

PINS = {
    "fastmcp": "3.4.7",
    "mcp": "1.30.0",
    "cedarpy": "4.12.1",
}


@pytest.mark.parametrize("package,expected", PINS.items())
def test_pinned_versions(package, expected):
    assert version(package) == expected


def test_core_libs_import():
    import cedarpy  # noqa: F401
    import fastmcp  # noqa: F401
    import joserfc  # noqa: F401
    import mcp  # noqa: F401
