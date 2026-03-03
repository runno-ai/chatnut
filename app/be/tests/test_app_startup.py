# tests/test_app_startup.py
import asyncio
import logging
from unittest.mock import AsyncMock, patch

import pytest

from chatnut.version_check import VersionInfo


@pytest.mark.anyio
async def test_startup_logs_update_warning(caplog):
    """Version check loop should log a warning when an update is available."""
    mock_info = VersionInfo(current="0.2.0", latest="0.3.0")
    with patch(
        "chatnut.app.get_version_info",
        new_callable=AsyncMock,
        return_value=mock_info,
    ):
        with patch(
            "chatnut.app.asyncio.sleep",
            new_callable=AsyncMock,
            side_effect=asyncio.CancelledError,
        ):
            from chatnut.app import _version_check_loop

            with caplog.at_level(logging.WARNING, logger="chatnut.app"):
                with pytest.raises(asyncio.CancelledError):
                    await _version_check_loop()

    assert any("0.3.0" in r.message and "update" in r.message.lower() for r in caplog.records)


@pytest.mark.anyio
async def test_startup_no_warning_when_current(caplog):
    """No warning logged when already on latest version."""
    mock_info = VersionInfo(current="0.3.0", latest="0.3.0")
    with patch(
        "chatnut.app.get_version_info",
        new_callable=AsyncMock,
        return_value=mock_info,
    ):
        with patch(
            "chatnut.app.asyncio.sleep",
            new_callable=AsyncMock,
            side_effect=asyncio.CancelledError,
        ):
            from chatnut.app import _version_check_loop

            with caplog.at_level(logging.WARNING, logger="chatnut.app"):
                with pytest.raises(asyncio.CancelledError):
                    await _version_check_loop()

    assert not any("update" in r.message.lower() for r in caplog.records)


@pytest.mark.anyio
async def test_startup_silent_on_failure(caplog):
    """No warning or error when GitHub API fails."""
    mock_info = VersionInfo(current="0.3.0", latest=None)
    with patch(
        "chatnut.app.get_version_info",
        new_callable=AsyncMock,
        return_value=mock_info,
    ):
        with patch(
            "chatnut.app.asyncio.sleep",
            new_callable=AsyncMock,
            side_effect=asyncio.CancelledError,
        ):
            from chatnut.app import _version_check_loop

            with caplog.at_level(logging.WARNING, logger="chatnut.app"):
                with pytest.raises(asyncio.CancelledError):
                    await _version_check_loop()

    assert not any("update" in r.message.lower() for r in caplog.records)
