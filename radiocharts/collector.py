from __future__ import annotations

import argparse
from pathlib import Path
from filelock import FileLock, Timeout

from radiocharts.config import load_config
from radiocharts.db import init_db, upsert_issue
from radiocharts.sources.rmf import fetch_rmf

LOCK_PATH = Path("/app/data/collector.lock") if Path("/app").exists() else Path(__file__).resolve().parent.parent / "data" / "collector.lock"


def store(data: dict) -> int:
    return upsert_issue(
        source=data["source"], chart_date=data["chart_date"], issue_key=data["issue_key"],
        chart_size=data["chart_size"], entries=data["entries"], source_url=data.get("source_url")
    )


def collect_current() -> list[str]:
    cfg = load_config()
    messages = []
    init_db()
    with FileLock(str(LOCK_PATH), timeout=1):
        rmf_cfg = cfg.get("sources", {}).get("rmf", {})
        if rmf_cfg.get("enabled", True):
            data = fetch_rmf()
            store(data)
            messages.append(f"RMF: zapisano notowanie {data['issue_key']} ({data['chart_date']})")
        for name in ("zet", "olia", "olis", "eska"):
            scfg = cfg.get("sources", {}).get(name, {})
            if scfg.get("enabled") and scfg.get("mode") == "manual_import":
                messages.append(f"{name.upper()}: tryb importu ręcznego")
    return messages


def backfill_rmf(count: int = 30) -> list[str]:
    current = fetch_rmf()
    start = int(current["issue_key"])
    messages = []
    with FileLock(str(LOCK_PATH), timeout=1):
        for issue in range(start, max(0, start-count), -1):
            try:
                data = current if issue == start else fetch_rmf(issue)
                store(data)
                messages.append(f"RMF {issue}: OK")
            except Exception as exc:
                messages.append(f"RMF {issue}: {type(exc).__name__}: {exc}")
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
