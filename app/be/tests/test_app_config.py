"""Test STATIC_DIR default resolves to package-internal static/ directory."""
from pathlib import Path


def test_default_static_dir_is_package_relative():
    """_default_static_dir() returns the package-internal static/ path."""
    import agent_chat_mcp.app as m

    result = m._default_static_dir()
    expected = str(Path(m.__file__).parent / "static")
    assert result == expected, (
        f"Expected package-relative static dir {expected!r}, got {result!r}"
    )
