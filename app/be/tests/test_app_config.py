"""Test STATIC_DIR default resolves to package-internal static/ directory."""
import os
from pathlib import Path


def test_default_static_dir_is_package_relative():
    """_default_static_dir() returns the package-internal static/ path."""
    import agent_chat_mcp.app as m

    result = m._default_static_dir()
    # Assert structural property without reimplementing the function.
    assert result.endswith(os.path.join("agent_chat_mcp", "static")), (
        f"Expected path ending in agent_chat_mcp/static, got {result!r}"
    )
    # Assert the directory actually exists in the installed package.
    assert Path(result).is_dir(), (
        f"static/ directory does not exist at {result!r} — "
        "check that static/.gitkeep is included in the wheel"
    )
