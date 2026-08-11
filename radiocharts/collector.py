from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Callable

from filelock import FileLock, Timeout

from radiocharts.config import load_config
from radiocharts.db import init_db, upsert_issue
from radiocharts.sources.rmf import fetch_rmf
from radiocharts.sources.olis import fetch_olis
from radiocharts.sources.eska import fetch_eska

LOCK_PATH = Path("/app/data/collector.lock") if Path("/app").exists() else Path(__file__).resolve().parent.parent / "data" / "collector.lock"


def store(data: dict) -> int:
    return upsert_issue(
        source=data["source"], chart_date=data["chart_date"], issue_key=data["issue_key"],
        chart_size=data["chart_size"], entries=data["entries"], source_url=data.get("source_url")
    )


def _enabled(cfg: dict, name: str, default: bool = False) -> bool:
    return bool(cfg.get("sources", {}).get(name, {}).get("enabled", default))


def collect_current() -> list[str]:
    """Collect every enabled automatic source, without one failure blocking the rest."""
    cfg = load_config()
    messages: list[str] = []
    init_db()
    with FileLock(str(LOCK_PATH), timeout=1):
        jobs = []
        if _enabled(cfg, "rmf", True):
            jobs.append(("RMF", fetch_rmf))
        if _enabled(cfg, "olia"):
            jobs.append(("OLIA", lambda: fetch_olis("OLIA")))
        if _enabled(cfg, "olis"):
            jobs.append(("OLIS", lambda: fetch_olis("OLIS")))
        if _enabled(cfg, "eska"):
            jobs.append(("ESKA", fetch_eska))

        for name, fn in jobs:
            try:
                data = fn()
                store(data)
                messages.append(
                    f"✅ {name}: {len(data['entries'])} pozycji, notowanie {data['issue_key']} ({data['chart_date']})"
                )
            except Exception as exc:
                messages.append(f"⚠️ {name}: {type(exc).__name__}: {exc}")

        zet_cfg = cfg.get("sources", {}).get("zet", {})
        if zet_cfg.get("enabled") and zet_cfg.get("mode") == "manual_import":
            messages.append("ℹ️ ZET: tryb importu ręcznego")
    return messages


def backfill_rmf(
    count: int = 30,
    progress_callback: Callable[[int, int, str], None] | None = None,
    pause_seconds: float = 0.25,
) -> list[str]:
    """Fetch `count` RMF issue numbers backwards from the current issue.

    RMF is normally published on weekdays, so ~30 issues is roughly six weeks.
    A small pause avoids hammering the public site during historical backfill.
    """
    count = max(1, min(int(count), 750))
    current = fetch_rmf()
    start = int(current["issue_key"])
    messages: list[str] = []
    issues = list(range(start, max(0, start - count), -1))
    with FileLock(str(LOCK_PATH), timeout=1):
        for idx, issue in enumerate(issues, start=1):
            try:
                data = current if issue == start else fetch_rmf(issue)
                store(data)
                msg = f"RMF {issue}: OK ({data['chart_date']})"
            except Exception as exc:
                msg = f"RMF {issue}: {type(exc).__name__}: {exc}"
            messages.append(msg)
            if progress_callback:
                progress_callback(idx, len(issues), msg)
            if issue != issues[-1] and pause_seconds > 0:
                time.sleep(pause_seconds)
    return messages


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--rmf-backfill", type=int, default=0, help="Liczba notowań RMF do pobrania wstecz")
    args = p.parse_args()
    try:
        msgs = backfill_rmf(args.rmf_backfill) if args.rmf_backfill else collect_current()
        print("\n".join(msgs))
    except Timeout:
        print("Collector już działa.")


if __name__ == "__main__":
    main()
