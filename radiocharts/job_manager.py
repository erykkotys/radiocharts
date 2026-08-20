from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

from radiocharts.db import DB_PATH

JOB_DIR = DB_PATH.parent / "jobs"
JOB_DIR.mkdir(parents=True, exist_ok=True)


def _path(job_id: str) -> Path:
    return JOB_DIR / f"{job_id}.json"


def log_path(job_id: str) -> Path:
    """Resolve a job log, supporting both dated 0.3.14+ and legacy names."""
    meta = _read(_path(job_id)) if _path(job_id).exists() else {}
    name = str(meta.get("log_file") or "").strip()
    if name:
        return JOB_DIR / Path(name).name
    legacy = JOB_DIR / f"{job_id}.log"
    if legacy.exists():
        return legacy
    matches = sorted(JOB_DIR.glob(f"*_{job_id}.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else legacy


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_job_log(job_id: str, *, max_bytes: int | None = None) -> str:
    """Read a persisted human-readable job log.

    ``max_bytes`` reads only the tail, which keeps the Streamlit status fragment
    cheap even for long backfills. The complete file remains on disk.
    """
    path = log_path(job_id)
    if not path.exists():
        return ""
    if not max_bytes or path.stat().st_size <= max_bytes:
        return path.read_text(encoding="utf-8", errors="replace")
    with path.open("rb") as fh:
        fh.seek(-max_bytes, os.SEEK_END)
        data = fh.read()
    text = data.decode("utf-8", errors="replace")
    # The seek can start in the middle of a line; omit that partial line.
    if "\n" in text:
        text = text.split("\n", 1)[1]
    return "… wcześniejsze wpisy są w pełnym pliku .log …\n" + text


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def latest_job() -> dict | None:
    files = sorted(JOB_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return None
    data = _read(files[0])
    if data.get("state") in {"running", "stopping"} and not _pid_alive(data.get("pid")):
        data["state"] = "failed"
        data["message"] = data.get("message") or "Proces zakończył się bez poprawnego statusu."
        data["finished_at"] = time.time()
        _write(files[0], data)
    return data


def active_job() -> dict | None:
    job = latest_job()
    if job and job.get("state") in {"running", "stopping"} and _pid_alive(job.get("pid")):
        return job
    return None


def start_job(kind: str, source: str | None = None, count: int | None = None, params: dict | None = None) -> dict:
    current = active_job()
    if current:
        raise RuntimeError(f"Inny proces już działa: {current.get('label') or current.get('job_id')}")

    job_id = uuid.uuid4().hex[:12]
    cmd = [sys.executable, "-m", "radiocharts.job_runner", "--job-id", job_id, "--kind", kind]
    if source:
        cmd += ["--source", source.upper()]
    if count is not None:
        cmd += ["--count", str(int(count))]
    if params:
        cmd += ["--params-json", json.dumps(params, separators=(",", ":"))]

    started_local = datetime.now(ZoneInfo("Europe/Warsaw"))
    # The filename uses the same local clock as the application/operator, so a
    # log can be matched to a clicked process without converting from UTC.
    file_stamp = started_local.strftime("%Y-%m-%d_%H-%M-%S")
    safe_kind = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(kind))
    job_log = JOB_DIR / f"{file_stamp}_{safe_kind}_{job_id}.log"
    created_stamp = started_local.isoformat(timespec="seconds")
    job_log.write_text(
        f"{created_stamp} [MANAGER] utworzono job {job_id} kind={kind}\n",
        encoding="utf-8",
    )
    data = {
        "job_id": job_id,
        "kind": kind,
        "source": source.upper() if source else None,
        "count": count,
        "state": "starting",
        "message": "Uruchamiam…",
        "started_at": time.time(),
        "progress": 0.0,
        "done": 0,
        "total": 0,
        "messages": [],
        "params": params or {},
        "log_file": job_log.name,
        "log_path": str(job_log),
    }
    path = _path(job_id)
    _write(path, data)

    # Keep stdout/stderr as a last-resort diagnostic channel. The runner also
    # appends structured entries to the same file, so even import/startup errors
    # are not silently lost in /dev/null.
    with job_log.open("a", encoding="utf-8") as log_stream:
        proc = subprocess.Popen(
            cmd,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
    data["pid"] = proc.pid
    data["state"] = "running"
    _write(path, data)
    return data


def stop_job(job_id: str) -> dict:
    path = _path(job_id)
    data = _read(path)
    pid = data.get("pid")
    if data.get("state") not in {"running", "starting", "stopping"}:
        return data
    data["state"] = "stopping"
    data["message"] = "Zatrzymuję proces…"
    _write(path, data)
    child_pid = data.get("child_pid")
    if child_pid:
        try:
            os.killpg(int(child_pid), signal.SIGTERM)
        except Exception:
            try:
                os.kill(int(child_pid), signal.SIGTERM)
            except Exception:
                pass
    if pid:
        try:
            os.killpg(int(pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        except Exception:
            try:
                os.kill(int(pid), signal.SIGTERM)
            except Exception:
                pass
    return data
