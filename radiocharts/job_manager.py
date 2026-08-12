from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

from radiocharts.db import DB_PATH

JOB_DIR = DB_PATH.parent / "jobs"
JOB_DIR.mkdir(parents=True, exist_ok=True)


def _path(job_id: str) -> Path:
    return JOB_DIR / f"{job_id}.json"


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


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
    }
    path = _path(job_id)
    _write(path, data)
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
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
            try: os.kill(int(child_pid), signal.SIGTERM)
            except Exception: pass
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
