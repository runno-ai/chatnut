# tests/test_version_check.py
import json
import time
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest

from chatnut.version_check import (
    VersionInfo,
    get_current_version,
    fetch_latest_version,
    get_version_info,
    get_cached_version_info,
    _clear_cache,
    GITHUB_REPO,
    CACHE_TTL,
)


def test_version_info_update_available():
    info = VersionInfo(current="0.2.0", latest="0.3.0")
    assert info.update_available is True


def test_version_info_up_to_date():
    info = VersionInfo(current="0.3.0", latest="0.3.0")
    assert info.update_available is False


def test_version_info_no_latest():
    info = VersionInfo(current="0.3.0", latest=None)
    assert info.update_available is False


def test_version_info_to_dict_update():
    info = VersionInfo(current="0.2.0", latest="0.3.0")
    d = info.to_dict()
    assert d == {
        "version": "0.2.0",
        "latest": "0.3.0",
        "update_available": True,
    }


def test_version_info_to_dict_current():
    info = VersionInfo(current="0.3.0", latest="0.3.0")
    d = info.to_dict()
    assert d == {"version": "0.3.0"}


def test_version_info_to_dict_no_latest():
    info = VersionInfo(current="0.3.0", latest=None)
    d = info.to_dict()
    assert d == {"version": "0.3.0"}


def test_get_current_version():
    _clear_cache()  # also clears lru_cache on get_current_version
    with patch("chatnut.version_check.importlib.metadata.version", return_value="1.2.3"):
        v = get_current_version()
    assert v == "1.2.3"


def test_get_current_version_fallback():
    import importlib.metadata
    _clear_cache()  # also clears lru_cache on get_current_version
    with patch(
        "chatnut.version_check.importlib.metadata.version",
        side_effect=importlib.metadata.PackageNotFoundError("chatnut"),
    ):
        v = get_current_version()
    assert v == "0.0.0-dev"


def test_github_repo_constant():
    assert GITHUB_REPO == "runno-ai/chatnut"


def test_cache_ttl():
    assert CACHE_TTL == 3600


@pytest.mark.anyio
async def test_fetch_latest_version_success():
    mock_response = httpx.Response(
        200,
        json={"tag_name": "v0.5.0"},
        request=httpx.Request("GET", "https://example.com"),
    )
    with patch("chatnut.version_check.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client
        result = await fetch_latest_version()
    assert result == "0.5.0"
    mock_client.get.assert_called_once()


@pytest.mark.anyio
async def test_fetch_latest_version_strips_v_prefix():
    mock_response = httpx.Response(
        200,
        json={"tag_name": "v1.2.3"},
        request=httpx.Request("GET", "https://example.com"),
    )
    with patch("chatnut.version_check.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client
        result = await fetch_latest_version()
    assert result == "1.2.3"


@pytest.mark.anyio
async def test_fetch_latest_version_network_error():
    with patch("chatnut.version_check.httpx.AsyncClient", side_effect=Exception("network")):
        result = await fetch_latest_version()
    assert result is None


@pytest.mark.anyio
async def test_fetch_latest_version_non_200():
    mock_response = httpx.Response(
        404,
        request=httpx.Request("GET", "https://example.com"),
    )
    with patch("chatnut.version_check.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client
        result = await fetch_latest_version()
    assert result is None


@pytest.mark.anyio
async def test_get_version_info_caches():
    _clear_cache()
    with patch("chatnut.version_check.get_current_version", return_value="0.1.0"):
        with patch(
            "chatnut.version_check.fetch_latest_version",
            new_callable=AsyncMock,
            return_value="0.9.0",
        ) as mock_fetch:
            info1 = await get_version_info()
            info2 = await get_version_info()
            mock_fetch.assert_called_once()
    assert info1.latest == "0.9.0"
    assert info2.latest == "0.9.0"


@pytest.mark.anyio
async def test_get_version_info_returns_none_latest_on_failure():
    _clear_cache()
    with patch("chatnut.version_check.get_current_version", return_value="0.1.0"):
        with patch(
            "chatnut.version_check.fetch_latest_version",
            new_callable=AsyncMock,
            return_value=None,
        ):
            info = await get_version_info()
    assert info.latest is None
    assert info.update_available is False


@pytest.mark.anyio
async def test_get_version_info_returns_stale_on_failure_after_success():
    """After a successful fetch, if the next fetch fails, stale value is returned."""
    _clear_cache()
    with patch("chatnut.version_check.get_current_version", return_value="0.1.0"):
        # First call succeeds and populates cache
        with patch(
            "chatnut.version_check.fetch_latest_version",
            new_callable=AsyncMock,
            return_value="0.5.0",
        ):
            info1 = await get_version_info()
        assert info1.latest == "0.5.0"

        # Expire the cache by manipulating the timestamp
        import chatnut.version_check as vc_mod
        ts, ver = vc_mod._cache["latest"]
        vc_mod._cache["latest"] = (ts - CACHE_TTL - 1, ver)

        # Second call fails — should return stale "0.5.0"
        with patch(
            "chatnut.version_check.fetch_latest_version",
            new_callable=AsyncMock,
            return_value=None,
        ):
            info2 = await get_version_info()
    assert info2.latest == "0.5.0"


@pytest.mark.anyio
async def test_get_version_info_does_not_cache_on_failure():
    """A failed fetch should not overwrite an existing valid cache entry."""
    _clear_cache()
    with patch("chatnut.version_check.get_current_version", return_value="0.1.0"):
        # Populate cache with a fresh entry
        with patch(
            "chatnut.version_check.fetch_latest_version",
            new_callable=AsyncMock,
            return_value="0.5.0",
        ):
            await get_version_info()

        # Simulate a failed fetch — cache should remain "0.5.0"
        import chatnut.version_check as vc_mod
        ts_before = vc_mod._cache["latest"][0]

        with patch(
            "chatnut.version_check.fetch_latest_version",
            new_callable=AsyncMock,
            return_value=None,
        ):
            # Still within TTL so cache is returned directly without re-fetching
            info = await get_version_info()
        assert info.latest == "0.5.0"
        # Timestamp unchanged (no write on failure within TTL)
        assert vc_mod._cache["latest"][0] == ts_before


@pytest.mark.anyio
async def test_get_version_info_ttl_expiry_refetches():
    """After TTL expires, a new fetch is performed."""
    _clear_cache()
    import chatnut.version_check as vc_mod

    with patch("chatnut.version_check.get_current_version", return_value="0.1.0"):
        with patch(
            "chatnut.version_check.fetch_latest_version",
            new_callable=AsyncMock,
            return_value="0.5.0",
        ) as mock_fetch:
            await get_version_info()
            assert mock_fetch.call_count == 1

            # Advance the cached timestamp past TTL
            ts, ver = vc_mod._cache["latest"]
            vc_mod._cache["latest"] = (ts - CACHE_TTL - 1, ver)

            mock_fetch.return_value = "0.6.0"
            info = await get_version_info()
            assert mock_fetch.call_count == 2
        assert info.latest == "0.6.0"


def test_get_cached_version_info_empty_cache():
    _clear_cache()
    with patch("chatnut.version_check.get_current_version", return_value="0.1.0"):
        info = get_cached_version_info()
    assert info.current == "0.1.0"
    assert info.latest is None
    assert info.update_available is False


@pytest.mark.anyio
async def test_get_cached_version_info_after_fetch():
    _clear_cache()
    with patch("chatnut.version_check.get_current_version", return_value="0.1.0"):
        with patch(
            "chatnut.version_check.fetch_latest_version",
            new_callable=AsyncMock,
            return_value="0.5.0",
        ):
            await get_version_info()  # populate cache
        info = get_cached_version_info()
    assert info.current == "0.1.0"
    assert info.latest == "0.5.0"
    assert info.update_available is True
