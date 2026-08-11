from __future__ import annotations

import os

VERSION = os.getenv("RADIOCHARTS_VERSION", "dev")
GIT_SHA = os.getenv("RADIOCHARTS_GIT_SHA", "unknown")
BUILD_DATE = os.getenv("RADIOCHARTS_BUILD_DATE", "unknown")


def short_sha() -> str:
    if not GIT_SHA or GIT_SHA == "unknown":
        return "unknown"
    return GIT_SHA[:7]


def display_version() -> str:
    return f"{VERSION} · {short_sha()}"
