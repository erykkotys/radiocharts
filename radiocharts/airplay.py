from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from filelock import FileLock

from radiocharts.db import (
    airplay_window_exists,
    list_airplay_stations,
    store_airplay_window,
    upsert_airplay_stations,
)

BASE_URL = "https://www.odsluchane.eu"
DIRECTORY_URL = f"{BASE_URL}/radio"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36 RadioChartsResearch/0.3",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.7",
}
LOCK_PATH = Path("/app/data/airplay.lock") if Path("/app").exists() else Path(__file__).resolve().parent.parent / "data" / "airplay.lock"


def _get(url: str, timeout: int = 12) -> str:
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.text


def parse_station_directory(html: str, base_url: str = BASE_URL) -> list[dict]:
    """Return station profile links from odSluchane's public /radio directory."""
    soup = BeautifulSoup(html or "", "lxml")
    found: dict[str, dict] = {}
    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        absolute = urljoin(base_url + "/", href)
        if not re.search(r"/radio/[^/?#]+$", absolute):
            continue
        slug = absolute.rstrip("/").rsplit("/", 1)[-1]
        name = a.get_text(" ", strip=True)
        if not slug or not name:
            continue
        found[slug] = {"name": name, "slug": slug, "source_url": absolute}
    return sorted(found.values(), key=lambda x: (str(x["name"]).casefold(), str(x["slug"])))


def parse_station_id(html: str) -> int | None:
    soup = BeautifulSoup(html or "", "lxml")
    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "")
        match = re.search(r"(?:^|[?&])r=(\d+)(?:&|$)", href)
        if match and "szukaj.php" in href:
            return int(match.group(1))
    match = re.search(r"szukaj\.php\?[^\"']*\br=(\d+)", html or "", flags=re.I)
    return int(match.group(1)) if match else None


def discover_stations(
    *,
    timeout: int = 10,
    pause_seconds: float = 0.08,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> list[dict]:
    """Discover every station currently listed in odSluchane's radio directory."""
    directory = parse_station_directory(_get(DIRECTORY_URL, timeout=timeout))
    stations: list[dict] = []
    total = len(directory)
    for idx, item in enumerate(directory, start=1):
        station_id = None
        try:
            station_id = parse_station_id(_get(str(item["source_url"]), timeout=timeout))
        except Exception as exc:
            if progress_callback:
                progress_callback(idx, total, f"{item['name']}: błąd identyfikacji ({type(exc).__name__})")
        if station_id is not None:
            station = dict(item)
            station["station_id"] = int(station_id)
            station["active"] = True
            stations.append(station)
            if progress_callback:
                progress_callback(idx, total, f"{item['name']}: ID {station_id}")
        elif progress_callback:
            progress_callback(idx, total, f"{item['name']}: brak ID playlisty")
        if idx < total and pause_seconds > 0:
            time.sleep(pause_seconds)
    upsert_airplay_stations(stations)
    return stations


def playlist_url(station_id: int, play_date: date, start_hour: int) -> str:
    start_hour = int(start_hour) % 24
    end_hour = (start_hour + 2) % 24
    return (
        f"{BASE_URL}/szukaj.php?date={play_date.strftime('%d-%m-%Y')}"
        f"&r={int(station_id)}&time_from={start_hour}&time_to={end_hour}"
    )


def split_artist_title(text: str) -> tuple[str, str] | None:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if " - " not in value:
        return None
    artist, title = value.split(" - ", 1)
    artist, title = artist.strip(), title.strip()
    if not artist or not title:
        return None
    return artist, title


def parse_playlist_html(html: str, play_date: date, start_hour: int, source_url: str = "") -> list[dict]:
    """Parse the public two-hour playlist table into exact local timestamps."""
    soup = BeautifulSoup(html or "", "lxml")
    plays: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        time_text = cells[0].get_text(" ", strip=True)
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", time_text)
        if not m:
            continue
        hour, minute = int(m.group(1)), int(m.group(2))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            continue
        song_text = cells[1].get_text(" ", strip=True)
        parts = split_artist_title(song_text)
        if not parts:
            continue
        artist, title = parts
        d = play_date
        # The public UI represents 22→0 as the final two hours of play_date;
        # there should be no 00:xx rows in that response, but handle it safely.
        if int(start_hour) >= 22 and hour < int(start_hour):
            d = play_date + timedelta(days=1)
        played_at = datetime(d.year, d.month, d.day, hour, minute).isoformat(timespec="minutes")
        key = (played_at, artist.casefold(), title.casefold())
        if key in seen:
            continue
        seen.add(key)
        plays.append({
            "played_at": played_at,
            "artist": artist,
            "title": title,
            "source_url": source_url,
        })
    plays.sort(key=lambda x: x["played_at"])
    return plays


def fetch_window(
    station: dict,
    play_date: date,
    start_hour: int,
    *,
    timeout: int = 12,
) -> tuple[list[dict], str]:
    url = playlist_url(int(station["station_id"]), play_date, start_hour)
    text = _get(url, timeout=timeout)
    return parse_playlist_html(text, play_date, start_hour, url), url


def _stations_or_discover(progress_callback=None) -> list[dict]:
    stations = list_airplay_stations(active_only=True)
    if stations:
        return stations
    return discover_stations(progress_callback=progress_callback)


def completed_window(now: datetime | None = None, tz_name: str = "Europe/Warsaw") -> tuple[date, int]:
    tz = ZoneInfo(tz_name)
    local = now.astimezone(tz) if now and now.tzinfo else (now.replace(tzinfo=tz) if now else datetime.now(tz))
    boundary = local.replace(minute=0, second=0, microsecond=0)
    boundary = boundary.replace(hour=(boundary.hour // 2) * 2)
    start = boundary - timedelta(hours=2)
    return start.date(), int(start.hour)


def completed_windows_in_range(
    start_date: date,
    end_date: date,
    *,
    now: datetime | None = None,
    tz_name: str = "Europe/Warsaw",
) -> list[tuple[date, int]]:
    """Return every *finished* public 2-hour block in an inclusive date range.

    odSluchane exposes a day as 12 blocks: 00-02, 02-04, …, 22-24.
    Never include the current/future block: older builds could save those empty
    responses as successful and then incorrectly skip them later.
    """
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    tz = ZoneInfo(tz_name)
    local_now = now.astimezone(tz) if now and now.tzinfo else (now.replace(tzinfo=tz) if now else datetime.now(tz))
    out: list[tuple[date, int]] = []
    days = (end_date - start_date).days + 1
    for day_idx in range(days):
        d = start_date + timedelta(days=day_idx)
        for start_hour in range(0, 24, 2):
            end_local = datetime(d.year, d.month, d.day, start_hour, 0, tzinfo=tz) + timedelta(hours=2)
            if end_local <= local_now:
                out.append((d, start_hour))
    return out


def recent_completed_windows(
    hours: int = 24,
    *,
    now: datetime | None = None,
    tz_name: str = "Europe/Warsaw",
) -> list[tuple[date, int]]:
    """Return the last N hours as finished 2-hour blocks, newest last."""
    block_count = max(1, (max(1, int(hours)) + 1) // 2)
    latest_date, latest_hour = completed_window(now, tz_name)
    tz = ZoneInfo(tz_name)
    cursor = datetime(latest_date.year, latest_date.month, latest_date.day, latest_hour, tzinfo=tz)
    rows = []
    for offset in range(block_count - 1, -1, -1):
        dt = cursor - timedelta(hours=2 * offset)
        rows.append((dt.date(), int(dt.hour)))
    return rows


def collect_latest_window(
    *,
    progress_callback: Callable[[int, int, str], None] | None = None,
    pause_seconds: float = 0.08,
    now: datetime | None = None,
    catch_up_hours: int = 24,
) -> dict:
    """Fill missing completed 2-hour blocks from the recent catch-up horizon.

    Historically this function fetched only one block.  That was fragile on a
    frequently redeployed single-container installation: one manual run could
    leave a whole day represented by only ~20-30 songs.  We now inspect the
    last 24h by default and only download blocks that are missing or were
    fetched prematurely.
    """
    stations = _stations_or_discover()
    windows = recent_completed_windows(catch_up_hours, now=now)
    total = len(stations) * len(windows)
    ok = errors = skipped = plays_total = done = 0
    messages: list[str] = []
    with FileLock(str(LOCK_PATH), timeout=1):
        for play_date, start_hour in windows:
            for station in stations:
                done += 1
                station_id = int(station["station_id"])
                name = str(station.get("name") or station_id)
                if airplay_window_exists(
                    station_id, play_date, start_hour, require_completed_capture=True
                ):
                    skipped += 1
                    msg = f"{name} {play_date} {start_hour:02d}-{(start_hour+2)%24:02d}: już jest"
                else:
                    try:
                        plays, url = fetch_window(station, play_date, start_hour)
                        stored = store_airplay_window(
                            station_id, name, play_date, start_hour, plays, url, success=True,
                        )
                        ok += 1
                        plays_total += stored
                        msg = f"{name} {play_date} {start_hour:02d}-{(start_hour+2)%24:02d}: OK ({stored})"
                    except Exception as exc:
                        errors += 1
                        msg = f"{name} {play_date} {start_hour:02d}-{(start_hour+2)%24:02d}: {type(exc).__name__}: {exc}"
                messages.append(msg)
                if progress_callback:
                    progress_callback(done, total, msg)
                if done < total and pause_seconds > 0 and "już jest" not in msg:
                    time.sleep(pause_seconds)
    return {
        "ok": ok, "errors": errors, "skipped": skipped, "plays": plays_total,
        "total": total, "messages": messages, "windows_per_station": len(windows),
    }


def backfill_airplay(
    station_ids: Iterable[int],
    start_date: date,
    end_date: date,
    *,
    progress_callback: Callable[[int, int, str], None] | None = None,
    pause_seconds: float = 0.10,
    max_windows: int = 100_000,
    now: datetime | None = None,
) -> dict:
    """Exact, resumable backfill over all finished public 2-hour windows.

    A full historical day means exactly 12 requests per station.  Current and
    future blocks are never requested before they finish.  Existing rows are
    skipped only if they were themselves fetched after the end of the block,
    which repairs premature empty rows created by older builds.
    """
    ids = sorted({int(x) for x in station_ids})
    if not ids:
        raise ValueError("Nie wybrano stacji")
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    windows = completed_windows_in_range(start_date, end_date, now=now)
    total = len(windows) * len(ids)
    if total > int(max_windows):
        raise ValueError(
            f"Zakres to {total:,} zakończonych okien 2h; limit jednego procesu to {int(max_windows):,}. "
            "Podziel backfill na mniejsze zakresy dat lub mniej stacji."
        )
    if total == 0:
        return {"ok": 0, "errors": 0, "skipped": 0, "plays": 0, "total": 0, "messages": []}
    stations_by_id = {int(s["station_id"]): s for s in _stations_or_discover()}
    missing = [x for x in ids if x not in stations_by_id]
    if missing:
        raise ValueError(f"Brak stacji o ID: {', '.join(map(str, missing[:10]))}")

    ok = errors = skipped = plays_total = done = 0
    messages: list[str] = []
    with FileLock(str(LOCK_PATH), timeout=1):
        for d, start_hour in windows:
            for station_id in ids:
                done += 1
                station = stations_by_id[station_id]
                name = str(station.get("name") or station_id)
                if airplay_window_exists(
                    station_id, d, start_hour, require_completed_capture=True
                ):
                    skipped += 1
                    msg = f"{name} {d} {start_hour:02d}-{(start_hour+2)%24:02d}: już jest"
                else:
                    try:
                        plays, url = fetch_window(station, d, start_hour)
                        stored = store_airplay_window(
                            station_id, name, d, start_hour, plays, url, success=True,
                        )
                        ok += 1
                        plays_total += stored
                        msg = f"{name} {d} {start_hour:02d}-{(start_hour+2)%24:02d}: OK ({stored})"
                    except Exception as exc:
                        errors += 1
                        msg = f"{name} {d} {start_hour:02d}-{(start_hour+2)%24:02d}: {type(exc).__name__}: {exc}"
                messages.append(msg)
                if progress_callback:
                    progress_callback(done, total, msg)
                if done < total and pause_seconds > 0 and "już jest" not in msg:
                    time.sleep(pause_seconds)
    return {
        "ok": ok, "errors": errors, "skipped": skipped, "plays": plays_total,
        "total": total, "messages": messages,
    }

