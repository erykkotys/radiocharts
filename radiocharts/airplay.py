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


def collect_latest_window(
    *,
    progress_callback: Callable[[int, int, str], None] | None = None,
    pause_seconds: float = 0.08,
    now: datetime | None = None,
) -> dict:
    """Fetch the last completed 2-hour block for every discovered station."""
    stations = _stations_or_discover()
    play_date, start_hour = completed_window(now)
    total = len(stations)
    ok = errors = plays_total = 0
    messages: list[str] = []
    with FileLock(str(LOCK_PATH), timeout=1):
        for idx, station in enumerate(stations, start=1):
            name = str(station.get("name") or station.get("station_id"))
            try:
                plays, url = fetch_window(station, play_date, start_hour)
                stored = store_airplay_window(
                    int(station["station_id"]), name, play_date, start_hour, plays, url,
                    success=True,
                )
                ok += 1
                plays_total += stored
                msg = f"{name}: OK · {stored} emisji ({play_date} {start_hour:02d}-{(start_hour+2)%24:02d})"
            except Exception as exc:
                errors += 1
                msg = f"{name}: {type(exc).__name__}: {exc}"
            messages.append(msg)
            if progress_callback:
                progress_callback(idx, total, msg)
            if idx < total and pause_seconds > 0:
                time.sleep(pause_seconds)
    return {"ok": ok, "errors": errors, "plays": plays_total, "total": total, "messages": messages}


def backfill_airplay(
    station_ids: Iterable[int],
    start_date: date,
    end_date: date,
    *,
    progress_callback: Callable[[int, int, str], None] | None = None,
    pause_seconds: float = 0.10,
    max_windows: int = 100_000,
) -> dict:
    """Exact, resumable backfill over public 2-hour windows.

    Already-successful windows are skipped, so a stopped job can be restarted
    with the same range without downloading completed work again.
    """
    ids = sorted({int(x) for x in station_ids})
    if not ids:
        raise ValueError("Nie wybrano stacji")
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    days = (end_date - start_date).days + 1
    total = days * 12 * len(ids)
    if total > int(max_windows):
        raise ValueError(
            f"Zakres to {total:,} okien 2h; limit jednego procesu to {int(max_windows):,}. "
            "Podziel backfill na mniejsze zakresy dat lub mniej stacji."
        )
    stations_by_id = {int(s["station_id"]): s for s in _stations_or_discover()}
    missing = [x for x in ids if x not in stations_by_id]
    if missing:
        raise ValueError(f"Brak stacji o ID: {', '.join(map(str, missing[:10]))}")

    ok = errors = skipped = plays_total = done = 0
    messages: list[str] = []
    with FileLock(str(LOCK_PATH), timeout=1):
        for day_idx in range(days):
            d = start_date + timedelta(days=day_idx)
            for start_hour in range(0, 24, 2):
                for station_id in ids:
                    done += 1
                    station = stations_by_id[station_id]
                    name = str(station.get("name") or station_id)
                    if airplay_window_exists(station_id, d, start_hour):
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
        "ok": ok,
        "errors": errors,
        "skipped": skipped,
        "plays": plays_total,
        "total": total,
        "messages": messages,
    }
