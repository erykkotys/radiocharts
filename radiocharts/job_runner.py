from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import traceback
from datetime import date, datetime, timezone
from pathlib import Path

from radiocharts.collector import backfill_olis_source, backfill_rmf, backfill_weekly_source, backfill_zet
from radiocharts.airplay import backfill_airplay, collect_latest_window, discover_stations
from radiocharts.db import DB_PATH, record_source_check

JOB_DIR = DB_PATH.parent / "jobs"
_CURRENT: dict = {}
_PATH: Path | None = None
_LOG_PATH: Path | None = None
_CHILD_PID: int | None = None

SOURCE_TIMEOUTS = {
    "RMF": 15,
    "ZET": 15,
    "OLIA": 55,
    "OLIS": 35,
    "ESKA": 15,
    "UK": 18,
    "BILLBOARD": 22,
}
AUTO_SOURCES = ["RMF", "ZET", "OLIA", "OLIS", "ESKA", "UK", "BILLBOARD"]


def _write(**updates) -> None:
    global _CURRENT
    if _PATH is None:
        return
    _CURRENT.update(updates)
    tmp = _PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(_CURRENT, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_PATH)


def _append_log(level: str, message: str) -> None:
    """Append one durable, human-readable entry to the per-job log."""
    if _LOG_PATH is None:
        return
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    text = str(message or "")
    lines = text.splitlines() or [""]
    rendered = [f"{stamp} [{level}] {lines[0]}"]
    rendered.extend(f"    {line}" for line in lines[1:])
    try:
        with _LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(rendered) + "\n")
            fh.flush()
    except Exception:
        # Logging must never break the actual collector/backfill.
        pass


def _source_summary(messages: list[str], requested: int) -> dict:
    ok = sum(1 for m in messages if ": OK" in m)
    errors = max(0, int(requested) - ok)
    return {
        "requested": int(requested),
        "ok": ok,
        "errors": errors,
        "reported_messages": len(messages),
    }


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
    _append_log("CANCEL", f"signal={signum} — zatrzymano przez użytkownika")
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
    _append_log("SOURCE", f"{source}: start collector pid={proc.pid}, timeout={timeout}s")
    _write(child_pid=proc.pid, message=f"{source}: pobieranie… (limit {timeout}s)")
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_child()
        msg = f"{source}: przekroczono limit {timeout}s — spróbuj ponownie"
        _append_log("ERROR", msg)
        try: record_source_check(source, False, msg)
        except Exception: pass
        raise TimeoutError(msg)
    finally:
        if _CHILD_PID == proc.pid:
            _CHILD_PID = None
            _write(child_pid=None)
    if out and out.strip():
        _append_log("STDOUT", f"{source}:\n{out.rstrip()}")
    if err and err.strip():
        _append_log("STDERR", f"{source}:\n{err.rstrip()}")
    if proc.returncode != 0:
        detail = (err or out or "collector zakończył się błędem").strip().splitlines()[-1]
        _append_log("ERROR", f"{source}: collector exit={proc.returncode}: {detail}")
        try: record_source_check(source, False, detail)
        except Exception: pass
        raise RuntimeError(detail)
    lines = [x.strip() for x in (out or "").splitlines() if x.strip()]
    result = lines[-1] if lines else f"✅ {source}: zakończono"
    _append_log("SOURCE", f"{source}: collector zakończony exit=0")
    return result


def main() -> int:
    global _CURRENT, _PATH, _LOG_PATH
    p = argparse.ArgumentParser()
    p.add_argument("--job-id", required=True)
    p.add_argument(
        "--kind",
        required=True,
        choices=[
            "collect-all", "collect-source", "backfill", "backfill-all",
            "airplay-discover", "airplay-latest", "airplay-backfill",
        ],
    )
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
    _LOG_PATH = JOB_DIR / f"{args.job_id}.log"
    try:
        _CURRENT = json.loads(_PATH.read_text(encoding="utf-8"))
    except Exception:
        _CURRENT = {"job_id": args.job_id}
    _write(
        pid=os.getpid(), state="running", message="Pracuję…",
        log_file=_LOG_PATH.name, log_path=str(_LOG_PATH),
    )
    _append_log(
        "START",
        f"job_id={args.job_id} kind={args.kind} source={args.source or '-'} count={args.count} params={json.dumps(params, ensure_ascii=False, sort_keys=True)}",
    )
    signal.signal(signal.SIGTERM, _cancel)
    signal.signal(signal.SIGINT, _cancel)

    messages: list[str] = []
    source_summary: dict[str, dict] = {}

    def progress(done: int, total: int, message: str):
        messages.append(message)
        _append_log("PROGRESS", f"{done}/{total} {message}")
        _write(
            done=done,
            total=total,
            progress=(done / total if total else 0.0),
            message=message,
            messages=messages[-30:],
        )

    try:
        if args.kind == "airplay-discover":
            stations = discover_stations(progress_callback=progress)
            final_message = f"Odkryto {len(stations)} stacji odSluchane.eu."
            _append_log("FINISH", f"state=done — {final_message}")
            _write(
                state="done", progress=1.0,
                message=final_message,
                messages=messages, finished_at=time.time(),
            )
            return 0
        elif args.kind == "airplay-latest":
            result = collect_latest_window(progress_callback=progress)
            state = "partial" if int(result.get("errors") or 0) else "done"
            _write(
                state=state, progress=1.0,
                message=(
                    f"Emisje 24h: pobrano {result.get('ok', 0)} brakujących okien 2h, "
                    f"pominięto {result.get('skipped', 0)} już zapisanych, błędy {result.get('errors', 0)}, "
                    f"zapisano {result.get('plays', 0)} emisji."
                ),
                messages=list(result.get("messages") or messages), finished_at=time.time(),
            )
            _append_log("FINISH", f"state={state} — {_CURRENT.get('message', '')}")
            return 0
        elif args.kind == "airplay-backfill":
            station_ids = [int(x) for x in params.get("station_ids", [])]
            start_date = date.fromisoformat(str(params.get("start_date")))
            end_date = date.fromisoformat(str(params.get("end_date")))
            result = backfill_airplay(station_ids, start_date, end_date, progress_callback=progress)
            errors = int(result.get("errors") or 0)
            state = "partial" if errors else "done"
            _write(
                state=state, progress=1.0,
                message=(
                    f"Emisje backfill: pobrano {result.get('ok', 0)} okien, pominięto {result.get('skipped', 0)} już zapisanych, "
                    f"błędy {errors}, zapisano {result.get('plays', 0)} emisji."
                ),
                messages=list(result.get("messages") or messages), finished_at=time.time(),
            )
            _append_log("FINISH", f"state={state} — {_CURRENT.get('message', '')}")
            return 0
        elif args.kind == "collect-all":
            total = len(AUTO_SOURCES)
            for idx, src in enumerate(AUTO_SOURCES, start=1):
                _write(done=idx - 1, total=total, message=f"{src}: start…")
                try:
                    msg = _collect_source_guarded(src)
                except Exception as exc:
                    msg = f"⚠️ {src}: {type(exc).__name__}: {exc}"
                progress(idx, total, msg)
        elif args.kind == "collect-source":
            if not args.source:
                raise ValueError("Brak źródła")
            _write(done=0, total=1, progress=0.0, message=f"{args.source.upper()}: start…")
            msg = _collect_source_guarded(args.source)
            progress(1, 1, msg)
        elif args.kind == "backfill-all":
            rmf_count = max(0, int(params.get("rmf_count", 0)))
            uk_count = max(0, int(params.get("uk_count", 0)))
            bb_count = max(0, int(params.get("billboard_count", 0)))
            olia_count = max(0, int(params.get("olia_count", 0)))
            olis_count = max(0, int(params.get("olis_count", 0)))
            zet_count = max(0, int(params.get("zet_count", 0)))
            total = rmf_count + uk_count + bb_count + olia_count + olis_count + zet_count
            if total <= 0:
                raise ValueError("Nie wybrano żadnego backfillu")
            _write(done=0, total=total, progress=0.0, message="Backfill: start…")
            offset = 0

            def cb(done: int, subtotal: int, message: str):
                progress(offset + done, total, message)

            jobs = [
                ("RMF", rmf_count),
                ("ZET", zet_count),
                ("UK", uk_count),
                ("BILLBOARD", bb_count),
                ("OLIA", olia_count),
                ("OLIS", olis_count),
            ]
            for src, cnt in jobs:
                if cnt <= 0:
                    continue
                if src == "RMF":
                    part = backfill_rmf(cnt, progress_callback=cb)
                elif src == "ZET":
                    part = backfill_zet(cnt, progress_callback=cb)
                elif src in {"UK", "BILLBOARD"}:
                    part = backfill_weekly_source(src, cnt, progress_callback=cb)
                else:
                    part = backfill_olis_source(src, cnt, progress_callback=cb)
                messages.extend([m for m in part if m not in messages])
                source_summary[src] = _source_summary(part, cnt)
                summary = source_summary[src]
                _append_log(
                    "SUMMARY",
                    f"{src}: requested={summary['requested']} ok={summary['ok']} errors={summary['errors']} reported_messages={summary['reported_messages']}",
                )
                offset += cnt
        else:
            src = (args.source or "").upper()
            count = max(1, int(args.count or 1))
            _write(done=0, total=count, progress=0.0, message=f"{src}: backfill start…")
            if src == "RMF":
                messages = backfill_rmf(count, progress_callback=progress)
            elif src == "ZET":
                messages = backfill_zet(count, progress_callback=progress)
            elif src in {"UK", "BILLBOARD"}:
                messages = backfill_weekly_source(src, count, progress_callback=progress)
            elif src in {"OLIA", "OLIS"}:
                messages = backfill_olis_source(src, count, progress_callback=progress)
            else:
                raise ValueError(f"Brak backfillu dla {src}")
            source_summary[src] = _source_summary(messages, count)
            summary = source_summary[src]
            _append_log(
                "SUMMARY",
                f"{src}: requested={summary['requested']} ok={summary['ok']} errors={summary['errors']} reported_messages={summary['reported_messages']}",
            )

        if args.kind.startswith("backfill"):
            ok_count = sum(1 for m in messages if ": OK" in m)
            expected = int(_CURRENT.get("total") or len(messages))
            error_count = max(0, expected - ok_count)
            if ok_count == 0 and messages:
                state = "failed"
                final_message = f"Backfill zakończony bez zapisanych notowań ({error_count} błędów)."
            elif error_count:
                state = "partial"
                final_message = f"Backfill: zapisano {ok_count}, błędy {error_count}."
            else:
                state = "done"
                final_message = f"Backfill: zapisano {ok_count}."
            _append_log("FINISH", f"state={state} — {final_message}")
            _write(
                state=state, progress=1.0, message=final_message,
                messages=messages, source_summary=source_summary, finished_at=time.time(),
            )
        else:
            final_message = "Zakończono."
            _append_log("FINISH", f"state=done — {final_message}")
            _write(state="done", progress=1.0, message=final_message, messages=messages, finished_at=time.time())
        return 0
    except SystemExit:
        raise
    except Exception as exc:
        _kill_child()
        tb = traceback.format_exc()
        _append_log("EXCEPTION", tb.rstrip())
        _write(
            state="failed", message=f"{type(exc).__name__}: {exc}", messages=messages,
            source_summary=source_summary, error_traceback=tb, finished_at=time.time(),
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
