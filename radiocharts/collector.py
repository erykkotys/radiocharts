from __future__ import annotations

import argparse
from datetime import date, timedelta
import time
from pathlib import Path
from typing import Callable

from filelock import FileLock, Timeout

from radiocharts.config import load_config
from radiocharts.db import init_db, record_source_check, upsert_issue
from radiocharts.sources.rmf import fetch_rmf
from radiocharts.sources.olis import fetch_olis, iter_olis_history
from radiocharts.sources.eska import fetch_eska
from radiocharts.sources.uk import fetch_uk
from radiocharts.sources.billboard import fetch_billboard
from radiocharts.sources.zet import fetch_zet

LOCK_PATH = Path("/app/data/collector.lock") if Path("/app").exists() else Path(__file__).resolve().parent.parent / "data" / "collector.lock"


def store(data: dict) -> int:
    return upsert_issue(
        source=data["source"], chart_date=data["chart_date"], issue_key=data["issue_key"],
        chart_size=data["chart_size"], entries=data["entries"], source_url=data.get("source_url")
    )


def _enabled(cfg: dict, name: str, default: bool = False) -> bool:
    return bool(cfg.get("sources", {}).get(name, {}).get("enabled", default))


def _source_jobs(cfg: dict) -> list[tuple[str, Callable[[], dict]]]:
    jobs: list[tuple[str, Callable[[], dict]]] = []
    if _enabled(cfg, "rmf", True): jobs.append(("RMF", fetch_rmf))
    if _enabled(cfg, "zet"): jobs.append(("ZET", fetch_zet))
    if _enabled(cfg, "olia"): jobs.append(("OLIA", lambda: fetch_olis("OLIA")))
    if _enabled(cfg, "olis"): jobs.append(("OLIS", lambda: fetch_olis("OLIS")))
    if _enabled(cfg, "eska"): jobs.append(("ESKA", fetch_eska))
    if _enabled(cfg, "uk"): jobs.append(("UK", fetch_uk))
    if _enabled(cfg, "billboard"): jobs.append(("BILLBOARD", fetch_billboard))
    return jobs


def _store_job(name: str, fn: Callable[[], dict]) -> str:
    data = fn()
    store(data)
    msg = f"✅ {name}: {len(data['entries'])} pozycji, notowanie {data['issue_key']} ({data['chart_date']})"
    record_source_check(name, True, msg, str(data.get("chart_date") or ""), str(data.get("issue_key") or ""))
    return msg


def collect_source(source: str) -> str:
    source = source.upper()
    cfg = load_config()
    jobs = dict(_source_jobs(cfg))
    if source not in jobs:
        raise ValueError(f"Źródło {source} jest wyłączone albo nieznane")
    init_db()
    with FileLock(str(LOCK_PATH), timeout=1):
        try:
            return _store_job(source, jobs[source])
        except Exception as exc:
            record_source_check(source, False, f"{type(exc).__name__}: {exc}")
            raise


def collect_current(progress_callback: Callable[[int, int, str], None] | None = None) -> list[str]:
    """Collect every enabled automatic source, without one failure blocking the rest."""
    cfg = load_config()
    messages: list[str] = []
    init_db()
    with FileLock(str(LOCK_PATH), timeout=1):
        jobs = _source_jobs(cfg)
        total = len(jobs)
        for idx, (name, fn) in enumerate(jobs, start=1):
            try:
                msg = _store_job(name, fn)
            except Exception as exc:
                msg = f"⚠️ {name}: {type(exc).__name__}: {exc}"
                record_source_check(name, False, msg)
            messages.append(msg)
            if progress_callback:
                progress_callback(idx, total, msg)
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



def backfill_weekly_source(
    source: str,
    count: int = 26,
    progress_callback: Callable[[int, int, str], None] | None = None,
    pause_seconds: float = 0.35,
) -> list[str]:
    """Backfill stable weekly archives for UK or Billboard.

    OLiA/OLiS/ESKA need separate archive navigation logic and are intentionally
    not routed through this helper yet.
    """
    source = source.upper()
    if source not in {"UK", "BILLBOARD"}:
        raise ValueError("Backfill tygodniowy obsługuje obecnie UK i BILLBOARD")
    count = max(1, min(int(count), 260))
    current = fetch_uk() if source == "UK" else fetch_billboard()
    if source == "UK":
        start = date.fromisoformat(str(current["issue_key"]).split("_")[0])
        fetcher = fetch_uk
    else:
        start = date.fromisoformat(str(current["chart_date"]))
        fetcher = fetch_billboard

    messages: list[str] = []
    with FileLock(str(LOCK_PATH), timeout=1):
        for idx in range(count):
            target = start - timedelta(days=7 * idx)
            try:
                data = current if idx == 0 else fetcher(target)
                store(data)
                msg = f"{source} {target.isoformat()}: OK ({data['chart_date']})"
            except Exception as exc:
                msg = f"{source} {target.isoformat()}: {type(exc).__name__}: {exc}"
            messages.append(msg)
            if progress_callback:
                progress_callback(idx + 1, count, msg)
            if idx + 1 < count and pause_seconds > 0:
                time.sleep(pause_seconds)
    return messages


def backfill_olis_source(
    source: str,
    count: int = 12,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> list[str]:
    """Experimental archive walker for OLiA/OLiS.

    The official site keeps historical weeks behind an in-page previous-week
    control, so one browser session walks backwards and tries the official CSV
    for each selected week. Failed weeks are skipped instead of stalling the job.
    """
    source = source.upper()
    if source not in {"OLIA", "OLIS"}:
        raise ValueError("Backfill OLiA/OLiS obsługuje tylko OLIA i OLIS")
    count = max(1, min(int(count), 104))
    messages: list[str] = []
    with FileLock(str(LOCK_PATH), timeout=1):
        for done, total, data, error in iter_olis_history(source, count):
            if data is not None:
                try:
                    store(data)
                    msg = f"{source} {data['issue_key']}: OK ({len(data['entries'])} pozycji)"
                except Exception as exc:
                    msg = f"{source}: {type(exc).__name__}: {exc}"
            else:
                msg = f"{source}: {error or 'nie udało się odczytać tygodnia'}"
            messages.append(msg)
            if progress_callback:
                progress_callback(done, total, msg)
    return messages



_ZET_SEED_DATE = date(2026, 3, 20)
_ZET_SEED_ID = 22801
_ZET_ID_PER_DAY = 7.2832

def _zet_predicted_archive_id(target: date) -> int:
    return int(round(_ZET_SEED_ID + (target - _ZET_SEED_DATE).days * _ZET_ID_PER_DAY))

def _zet_candidate_offsets(radius: int = 12):
    yield 0
    for n in range(1, radius + 1):
        yield -n
        yield n

def backfill_zet(
    count: int = 30,
    progress_callback: Callable[[int, int, str], None] | None = None,
    pause_seconds: float = 0.06,
) -> list[str]:
    """Best-effort ZET backfill using public archived issue URLs.

    Radio ZET archive pages use numeric content IDs rather than dates. A few
    stable public archive points give a very regular ID/day slope, so each target
    day is searched only in a small neighborhood around the predicted ID.
    Failed days are skipped and the job remains stoppable in the UI.
    """
    count = max(1, min(int(count), 180))
    messages: list[str] = []
    current = fetch_zet()
    current_date = date.fromisoformat(current["chart_date"])
    with FileLock(str(LOCK_PATH), timeout=1):
        store(current)
        msg = f"ZET {current_date.isoformat()}: OK (bieżące, 20 pozycji)"
        messages.append(msg)
        if progress_callback:
            progress_callback(1, count, msg)
        if count == 1:
            return messages

        last_found_id: int | None = None
        done = 1
        target = current_date - timedelta(days=1)
        while done < count:
            center = (last_found_id - 7) if last_found_id is not None else _zet_predicted_archive_id(target)
            found = None
            found_id = None
            tried: set[int] = set()
            for off in _zet_candidate_offsets(12):
                archive_id = max(1, center + off)
                if archive_id in tried:
                    continue
                tried.add(archive_id)
                try:
                    data = fetch_zet(archive_id=archive_id, timeout=5)
                    d = date.fromisoformat(data["chart_date"])
                    if d == target:
                        found, found_id = data, archive_id
                        break
                except Exception:
                    pass
                if pause_seconds > 0:
                    time.sleep(pause_seconds)
            done += 1
            if found is not None:
                store(found)
                last_found_id = found_id
                msg = f"ZET {target.isoformat()}: OK (archive {found_id})"
            else:
                last_found_id = None
                msg = f"ZET {target.isoformat()}: nie znaleziono publicznego archiwum w przewidywanym zakresie"
            messages.append(msg)
            if progress_callback:
                progress_callback(done, count, msg)
            target -= timedelta(days=1)
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
