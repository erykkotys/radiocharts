from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta
from typing import Callable, Iterable
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from radiocharts.db import (
    airplay_window_done,
    list_airplay_stations,
    record_airplay_fetch,
    save_airplay_plays,
    upsert_airplay_stations,
)

BASE = "https://www.odsluchane.eu"
SEARCH_URL = f"{BASE}/szukaj.php"
TZ = ZoneInfo("Europe/Warsaw")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.7",
}
# Three modest windows cover a full day and match ranges that the public site
# demonstrably serves. Keeping them bounded also prevents giant responses.
DAY_WINDOWS = [(0, 10, "00-10"), (10, 20, "10-20"), (20, 0, "20-24")]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def parse_station_catalog(html: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "lxml")
    found: dict[int, str] = {}

    # Prefer the station selector itself. Parsing *all* numeric options would
    # accidentally interpret hour/date selectors as radio IDs.
    selects = list(soup.find_all("select"))
    preferred = [x for x in selects if str(x.get("name") or "").casefold() == "r" or str(x.get("id") or "").casefold() == "r"]
    if not preferred:
        scored: list[tuple[int, object]] = []
        for sel in selects:
            options = []
            for opt in sel.find_all("option"):
                raw = str(opt.get("value") or "").strip()
                label = opt.get_text(" ", strip=True)
                if raw.isdigit() and label:
                    options.append((raw, label))
            alpha = sum(1 for _, label in options if re.search(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]", label))
            if len(options) >= 10 and alpha >= max(5, len(options) // 2):
                scored.append((len(options), sel))
        if scored:
            preferred = [max(scored, key=lambda x: x[0])[1]]

    for sel in preferred:
        for opt in sel.find_all("option"):
            raw = str(opt.get("value") or "").strip()
            if raw.isdigit():
                name = opt.get_text(" ", strip=True)
                if name and len(name) <= 120:
                    found[int(raw)] = name

    # Fallback/augmentation for alternate layouts containing links with ?r=<id>.
    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "")
        m = re.search(r"(?:[?&])r=(\d+)(?:&|$)", href)
        if not m:
            continue
        name = a.get_text(" ", strip=True)
        if name and len(name) <= 120 and re.search(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]", name):
            found.setdefault(int(m.group(1)), name)

    return [{"id": sid, "name": name} for sid, name in sorted(found.items(), key=lambda x: x[1].casefold())]


def discover_stations(session: requests.Session | None = None) -> list[dict]:
    sess = session or _session()
    # szukaj.php is preferred because it exposes the numeric IDs required by
    # playlist requests. r=2 is only a harmless seed station for the form.
    r = sess.get(SEARCH_URL, params={"r": 2}, timeout=18)
    r.raise_for_status()
    stations = parse_station_catalog(r.text)
    if len(stations) < 10:
        # Some layouts expose the full search form at the root instead.
        r2 = sess.get(BASE + "/", timeout=18)
        r2.raise_for_status()
        stations = parse_station_catalog(r2.text)
    if len(stations) < 10:
        raise ValueError(f"odSluchane: wykryto tylko {len(stations)} stacji — nie zapisuję niepełnego katalogu")
    upsert_airplay_stations(stations)
    return stations


def _split_artist_title(text: str) -> tuple[str, str] | None:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean or " - " not in clean:
        return None
    artist, title = clean.split(" - ", 1)
    artist, title = artist.strip(), title.strip()
    if not artist or not title:
        return None
    if artist.casefold() in {"nazwa utworu", "godzina", "playlista"}:
        return None
    return artist, title


def parse_playlist_html(html: str, play_date: date | str) -> list[dict]:
    d = date.fromisoformat(str(play_date)[:10]) if not isinstance(play_date, date) else play_date
    soup = BeautifulSoup(html or "", "lxml")
    rows: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        time_text = cells[0].get_text(" ", strip=True)
        if not re.fullmatch(r"\d{1,2}:\d{2}", time_text):
            continue
        hh, mm = [int(x) for x in time_text.split(":")]
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            continue
        song_text = cells[1].get_text(" ", strip=True)
        pair = _split_artist_title(song_text)
        if not pair:
            continue
        artist, title = pair
        played_at = f"{d.isoformat()}T{hh:02d}:{mm:02d}:00"
        key = (played_at, artist.casefold(), title.casefold())
        if key in seen:
            continue
        seen.add(key)
        rows.append({"played_at": played_at, "artist": artist, "title": title})
    return rows


def _window_url(station_id: int, day: date, start_hour: int, end_hour: int) -> str:
    return SEARCH_URL + "?" + urlencode({
        "date": day.strftime("%d-%m-%Y"),
        "r": int(station_id),
        "time_from": int(start_hour),
        "time_to": int(end_hour),
    })


def fetch_window(
    station_id: int,
    station_name: str,
    day: date,
    start_hour: int,
    end_hour: int,
    window_key: str,
    *,
    session: requests.Session | None = None,
    timeout: int = 20,
    attempts: int = 2,
) -> tuple[int, int]:
    sess = session or _session()
    params = {
        "date": day.strftime("%d-%m-%Y"),
        "r": int(station_id),
        "time_from": int(start_hour),
        "time_to": int(end_hour),
    }
    last_exc: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            resp = sess.get(SEARCH_URL, params=params, timeout=timeout)
            resp.raise_for_status()
            text = resp.text
            # A valid empty interval can happen for dormant/new stations, so
            # presence of the playlist page is enough to record a successful window.
            if "Playlista" not in text and "playlist" not in text.casefold():
                raise ValueError("odSluchane: odpowiedź nie wygląda jak strona playlisty")
            plays = parse_playlist_html(text, day)
            return save_airplay_plays(
                station_id, station_name, day, plays,
                source_url=resp.url or _window_url(station_id, day, start_hour, end_hour),
                window_key=window_key,
            )
        except Exception as exc:
            last_exc = exc
            if attempt < attempts:
                time.sleep(1.0 * attempt)
    assert last_exc is not None
    record_airplay_fetch(station_id, day, window_key, False, 0, f"{type(last_exc).__name__}: {last_exc}")
    raise last_exc


def _catalog_or_discover(session: requests.Session) -> list[dict]:
    stations = list_airplay_stations()
    if len(stations) >= 10:
        return stations
    return discover_stations(session)


def collect_airplay_recent(
    *,
    station_ids: Iterable[int] | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
    request_delay: float = 0.20,
) -> dict:
    """Collect a rolling recent window for all known stations.

    Scheduled every two hours. The request interval deliberately overlaps the
    previous run; UNIQUE(station,time,song) makes this idempotent.
    """
    sess = _session()
    catalog = _catalog_or_discover(sess)
    wanted = {int(x) for x in station_ids} if station_ids is not None else None
    stations = [x for x in catalog if wanted is None or int(x["id"]) in wanted]
    now = datetime.now(TZ)

    tasks: list[tuple[dict, date, int, int, str]] = []
    # Pull roughly the previous 3 hours. Around midnight this becomes two days.
    if now.hour >= 2:
        start = max(0, now.hour - 2)
        end = (now.hour + 1) % 24
        tasks.extend((st, now.date(), start, end, f"recent-{start:02d}-{end:02d}") for st in stations)
    else:
        prev = now.date() - timedelta(days=1)
        tasks.extend((st, prev, 21, 0, "recent-21-24") for st in stations)
        end = min(3, now.hour + 1)
        tasks.extend((st, now.date(), 0, end, f"recent-00-{end:02d}") for st in stations)

    ok = failed = parsed = inserted = 0
    total = len(tasks)
    for idx, (st, day, start, end, key) in enumerate(tasks, start=1):
        sid, name = int(st["id"]), str(st["name"])
        try:
            n, new = fetch_window(sid, name, day, start, end, key, session=sess, timeout=12, attempts=1)
            ok += 1; parsed += n; inserted += new
            msg = f"{name} {day} {key}: OK ({n}, nowych {new})"
        except Exception as exc:
            failed += 1
            msg = f"{name} {day} {key}: {type(exc).__name__}: {exc}"
        if progress_callback:
            progress_callback(idx, total, msg)
        if request_delay > 0 and idx < total:
            time.sleep(request_delay)
    return {"ok": ok, "failed": failed, "parsed": parsed, "inserted": inserted, "total": total}


def backfill_airplay(
    station_ids: Iterable[int],
    start_date: date | str,
    end_date: date | str,
    *,
    progress_callback: Callable[[int, int, str], None] | None = None,
    request_delay: float = 0.25,
    skip_completed: bool = True,
) -> dict:
    """Resumable historical backfill for selected stations/date range."""
    start = date.fromisoformat(str(start_date)[:10]) if not isinstance(start_date, date) else start_date
    end = date.fromisoformat(str(end_date)[:10]) if not isinstance(end_date, date) else end_date
    if end < start:
        start, end = end, start
    if (end - start).days > 366 * 5 + 5:
        raise ValueError("Zakres backfillu Emisji jest ograniczony do 5 lat")

    sess = _session()
    catalog = _catalog_or_discover(sess)
    by_id = {int(x["id"]): x for x in catalog}
    ids = [int(x) for x in station_ids if int(x) in by_id]
    if not ids:
        raise ValueError("Nie wybrano żadnej znanej stacji")

    days = (end - start).days + 1
    tasks: list[tuple[int, date, int, int, str]] = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        for sid in ids:
            for sh, eh, key in DAY_WINDOWS:
                tasks.append((sid, day, sh, eh, key))

    ok = failed = skipped = parsed = inserted = 0
    total = len(tasks)
    for idx, (sid, day, sh, eh, key) in enumerate(tasks, start=1):
        name = str(by_id[sid]["name"])
        if skip_completed and airplay_window_done(sid, day, key):
            skipped += 1
            msg = f"{name} {day} {key}: pominięto (już pobrane)"
        else:
            try:
                n, new = fetch_window(sid, name, day, sh, eh, key, session=sess)
                ok += 1; parsed += n; inserted += new
                msg = f"{name} {day} {key}: OK ({n}, nowych {new})"
            except Exception as exc:
                failed += 1
                msg = f"{name} {day} {key}: {type(exc).__name__}: {exc}"
            if request_delay > 0:
                time.sleep(request_delay)
        if progress_callback:
            progress_callback(idx, total, msg)

    return {
        "ok": ok, "failed": failed, "skipped": skipped, "parsed": parsed,
        "inserted": inserted, "total": total, "stations": len(ids),
        "start_date": start.isoformat(), "end_date": end.isoformat(),
    }
