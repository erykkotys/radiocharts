from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path

from radiocharts.collector import backfill_rmf, backfill_weekly_source, collect_current, collect_source
from radiocharts.db import DB_PATH

JOB_DIR = DB_PATH.parent / "jobs"
_CURRENT: dict = {}
_PATH: Path | None = None


def _write(**updates) -> None:
    global _CURRENT
    if _PATH is None:
        return
    _CURRENT.update(updates)
    tmp = _PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(_CURRENT, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_PATH)


def _cancel(signum, frame):
    _write(state="cancelled", message="Zatrzymano przez użytkownika.", finished_at=time.time())
    raise SystemExit(143)


def main() -> int:
    global _CURRENT, _PATH
    p = argparse.ArgumentParser()
    p.add_argument("--job-id", required=True)
    p.add_argument("--kind", required=True, choices=["collect-all", "collect-source", "backfill"])
    p.add_argument("--source")
    p.add_argument("--count", type=int, default=0)
    args = p.parse_args()

    JOB_DIR.mkdir(parents=True, exist_ok=True)
    _PATH = JOB_DIR / f"{args.job_id}.json"
    try:
        _CURRENT = json.loads(_PATH.read_text(encoding="utf-8"))
    except Exception:
        _CURRENT = {"job_id": args.job_id}
    _write(pid=os.getpid(), state="running", message="Pracuję…")
    signal.signal(signal.SIGTERM, _cancel)
    signal.signal(signal.SIGINT, _cancel)

    messages: list[str] = []

    def progress(done: int, total: int, message: str):
        messages.append(message)
        _write(
            done=done,
            total=total,
            progress=(done / total if total else 0.0),
            message=message,
            messages=messages[-30:],
        )

    try:
        if args.kind == "collect-all":
            result = collect_current(progress_callback=progress)
            messages.extend([x for x in result if x not in messages])
        elif args.kind == "collect-source":
            if not args.source:
                raise ValueError("Brak źródła")
            msg = collect_source(args.source)
            messages.append(msg)
            progress(1, 1, msg)
        else:
            src = (args.source or "").upper()
            count = max(1, int(args.count or 1))
            if src == "RMF":
                messages = backfill_rmf(count, progress_callback=progress)
            elif src in {"UK", "BILLBOARD"}:
                messages = backfill_weekly_source(src, count, progress_callback=progress)
            else:
                raise ValueError(f"Brak backfillu dla {src}")
        _write(state="done", progress=1.0, message="Zakończono.", messages=messages[-50:], finished_at=time.time())
        return 0
    except SystemExit:
        raise
    except Exception as exc:
        _write(state="failed", message=f"{type(exc).__name__}: {exc}", messages=messages[-50:], finished_at=time.time())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
