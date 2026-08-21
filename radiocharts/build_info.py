from __future__ import annotations

import os
from pathlib import Path


def _version_from_file() -> str:
    # VERSION is copied to /app in Docker. Keeping a package-relative fallback
    # also makes local runs display the real release instead of "dev".
    candidates = [
        Path(__file__).resolve().parents[1] / "VERSION",
        Path("/app/VERSION"),
    ]
    for path in candidates:
        try:
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
        except OSError:
            pass
    return "dev"


_env_version = (os.getenv("RADIOCHARTS_VERSION") or "").strip()
VERSION = _env_version if _env_version not in {"", "dev", "unknown"} else _version_from_file()
GIT_SHA = os.getenv("RADIOCHARTS_GIT_SHA", "unknown")
BUILD_DATE = os.getenv("RADIOCHARTS_BUILD_DATE", "unknown")


def short_sha() -> str:
    if not GIT_SHA or GIT_SHA == "unknown":
        return ""
    return GIT_SHA[:7]


def display_version() -> str:
    sha = short_sha()
    return f"v{VERSION}" + (f" · {sha}" if sha else "")
