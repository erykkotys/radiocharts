from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from radiocharts.collector import backfill_olis_source, backfill_rmf, backfill_weekly_source
from radiocharts.db import DB_PATH

JOB_DIR = DB_PATH.parent / "jobs"
_CURRENT: dict = {}
_PATH: Path | None = None
_CHILD_PID: int | None = None

SOURCE_TIMEOUTS = {
    "RMF": 15,
    "OLIA": 14,
    "OLIS": 14,
    "ESKA": 15,
    "UK": 18,
    "BILLBOARD": 22,
}
AUTO_SOURCES = ["RMF", "OLIA", "OLIS", "ESKA", "UK", "BILLBOARD"]


def _write(**updates) -> None:
    global _CURRENT
    if _PATH is None:
        return
    _CURRENT.update(updates)
    tmp = _PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(_CURRENT, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_PATH)


def _kill_child() -> None:
    global _CHILD_PID
    if not _CHILD_PID:
        return
    try:
        os.killpg(int(_CHILD_PID), signal.SIGTERM)
        time.sleep(0.15)
        try:
            os.killpg(int(_CHILD_PID), signal.SIGKILL)
        except Exception:
            pass
    except Exception:
        try:
            os.kill(int(_CHILD_PID), signal.SIGKILL)
        except Exception:
            pass
    _CHILD_PID = None
    _write(child_pid=None)


def _cancel(signum, frame):
    _kill_child()
    _write(state="cancelled", message="Zatrzymano przez użytkownika.", finished_at=time.time())
    raise SystemExit(143)


def _collect_source_guarded(source: str) -> str:
    """Run one collector in a killable subprocess with a hard wall-clock timeout."""
    global _CHILD_PID
    source = source.upper()
    timeout = int(SOURCE_TIMEOUTS.get(source, 20))
    cmd = [sys.executable, "-m", "radiocharts.source_runner", source]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    _CHILD_PID = proc.pid
    _write(child_pid=proc.pid, message=f"{source}: pobieranie… (limit {timeout}s)")
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_child()
        raise TimeoutError(f"{source}: przekroczono limit {timeout}s — spróbuj ponownie")
    finally:
        if _CHILD_PID == proc.pid:
            _CHILD_PID = None
            _write(child_pid=None)
    if proc.returncode != 0:
        detail = (err or out or "collector zakończył się błędem").strip().splitlines()[-1]
        raise RuntimeError(detail)
    lines = [x.strip() for x in (out or "").splitlines() if x.strip()]
    return lines[-1] if lines else f"✅ {source}: zakończono"


def main() -> int:
    global _CURRENT, _PATH
    p = argparse.ArgumentParser()
    p.add_argument("--job-id", required=True)
    p.add_argument("--kind", required=True, choices=["collect-all", "collect-source", "backfill", "backfill-all"])
    p.add_argument("--source")
    p.add_argument("--count", type=int, default=0)
    p.add_argument("--params-json", default="{}")
    args = p.parse_args()

    try:
        params = json.loads(args.params_json or "{}")
    except Exception:
        params = {}

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
            total = len(AUTO_SOURCES)
            for idx, src in enumerate(AUTO_SOURCES, start=1):
                _write(done=idx - 1, total=total, message=f"{src}: start…")
                try:
                    msg = _collect_source_guarded(src)
                except Exception as exc:
                    msg = f"⚠️ {src}: {type(exc).__name__}: {exc}"
                progress(idx, total, msg)
            messages.append("ℹ️ ZET: import ręczny")
        elif args.kind == "collect-source":
            if not args.source:
                raise ValueError("Brak źródła")
            msg = _collect_source_guarded(args.source)
            messages.append(msg)
            progress(1, 1, msg)
        elif args.kind == "backfill-all":
            rmf_count = max(1, int(params.get("rmf_count", 130)))
            uk_count = max(1, int(params.get("uk_count", 26)))
            bb_count = max(1, int(params.get("billboard_count", 26)))
            total = rmf_count + uk_count + bb_count
            offset = 0

            def cb(done: int, subtotal: int, message: str):
                progress(offset + done, total, message)

            part = backfill_rmf(rmf_count, progress_callback=cb)
            messages.extend([m for m in part if m not in messages])
            offset += rmf_count
            part = backfill_weekly_source("UK", uk_count, progress_callback=cb)
            messages.extend([m for m in part if m not in messages])
            offset += uk_count
            part = backfill_weekly_source("BILLBOARD", bb_count, progress_callback=cb)
            messages.extend([m for m in part if m not in messages])
        else:
            src = (args.source or "").upper()
            count = max(1, int(args.count or 1))
            if src == "RMF":
                messages = backfill_rmf(count, progress_callback=progress)
            elif src in {"UK", "BILLBOARD"}:
                messages = backfill_weekly_source(src, count, progress_callback=progress)
            elif src in {"OLIA", "OLIS"}:
                messages = backfill_olis_source(src, count, progress_callback=progress)
            else:
                raise ValueError(f"Brak backfillu dla {src}")
        _write(state="done", progress=1.0, message="Zakończono.", messages=messages[-50:], finished_at=time.time())
        return 0
    except SystemExit:
        raise
    except Exception as exc:
        _kill_child()
        _write(state="failed", message=f"{type(exc).__name__}: {exc}", messages=messages[-50:], finished_at=time.time())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
