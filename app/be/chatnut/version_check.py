"""Version checking via GitHub releases API with in-memory TTL cache."""

from __future__ import annotations

import functools
import importlib.metadata
import logging
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

GITHUB_REPO = "runno-ai/chatnut"
CACHE_TTL = 3600  # 1 hour


@dataclass
class VersionInfo:
    current: str
    latest: str | None

    @property
    def update_available(self) -> bool:
        return self.latest is not None and self.latest != self.current

    def to_dict(self) -> dict:
        d: dict = {"version": self.current}
        if self.update_available:
            d["latest"] = self.latest
            d["update_available"] = True
        return d


@functools.lru_cache(maxsize=1)
def get_current_version() -> str:
    try:
        return importlib.metadata.version("chatnut")
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0-dev"


# --- Cache ---
_cache: dict[str, tuple[float, str | None]] = {}


def _clear_cache() -> None:
    _cache.clear()
    get_current_version.cache_clear()


async def fetch_latest_version() -> str | None:
    """Fetch latest release tag from GitHub. Returns None on any failure."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": f"chatnut/{get_current_version()}",
                },
                timeout=10.0,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            tag = data.get("tag_name", "")
            return tag.lstrip("v") if tag else None
    except Exception:
        logger.debug("Failed to fetch latest version", exc_info=True)
        return None


async def get_version_info() -> VersionInfo:
    """Get version info, fetching from GitHub if cache is expired."""
    current = get_current_version()
    cached = _cache.get("latest")
    if cached is not None:
        ts, version = cached
        if time.monotonic() - ts < CACHE_TTL:
            return VersionInfo(current=current, latest=version)

    latest = await fetch_latest_version()
    if latest is not None:
        _cache["latest"] = (time.monotonic(), latest)
        return VersionInfo(current=current, latest=latest)
    # Fetch failed — return stale cached value if available
    stale = cached[1] if cached else None
    return VersionInfo(current=current, latest=stale)


def get_cached_version_info() -> VersionInfo:
    """Read version info from cache only (sync-safe, no network I/O).
    Returns VersionInfo with latest=None if cache is empty or expired."""
    current = get_current_version()
    cached = _cache.get("latest")
    if cached is not None:
        ts, version = cached
        if time.monotonic() - ts < CACHE_TTL:
            return VersionInfo(current=current, latest=version)
    return VersionInfo(current=current, latest=None)
