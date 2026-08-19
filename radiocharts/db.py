from __future__ import annotations

import os
import re
import sqlite3
import time
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from filelock import FileLock

DB_PATH = Path(os.getenv("RADIOCHARTS_DB", "/app/data/radiocharts.db"))
if str(DB_PATH).startswith("/app/") and not Path("/app").exists():
    DB_PATH = Path(os.getenv("RADIOCHARTS_DB", str(Path(__file__).resolve().parent.parent / "data" / "radiocharts.db")))


_INITIALIZED_DB_PATH: str | None = None

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS songs (
    id INTEGER PRIMARY KEY,
    artist TEXT NOT NULL,
    title TEXT NOT NULL,
    artist_key TEXT NOT NULL,
    title_key TEXT NOT NULL,
    release_date TEXT,
    isrc TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(artist_key, title_key)
);

CREATE TABLE IF NOT EXISTS chart_issues (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    chart_date TEXT NOT NULL,
    issue_key TEXT NOT NULL,
    chart_size INTEGER NOT NULL,
    source_url TEXT,
    retrieved_at TEXT NOT NULL,
    UNIQUE(source, issue_key)
);

CREATE TABLE IF NOT EXISTS chart_entries (
    id INTEGER PRIMARY KEY,
    issue_id INTEGER NOT NULL REFERENCES chart_issues(id) ON DELETE CASCADE,
    song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    previous_position INTEGER,
    reported_weeks INTEGER,
    reported_peak INTEGER,
    UNIQUE(issue_id, song_id),
    UNIQUE(issue_id, position)
);

CREATE TABLE IF NOT EXISTS song_notes (
    song_id INTEGER PRIMARY KEY REFERENCES songs(id) ON DELETE CASCADE,
    heard INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'Nie słuchałem',
    note TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_issue_source_date ON chart_issues(source, chart_date);
CREATE INDEX IF NOT EXISTS idx_entry_song ON chart_entries(song_id);
CREATE INDEX IF NOT EXISTS idx_song_title_key ON songs(title_key);

CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_checks (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    success INTEGER NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    chart_date TEXT,
    issue_key TEXT
);
CREATE INDEX IF NOT EXISTS idx_source_checks_source_time ON source_checks(source, checked_at DESC);

CREATE TABLE IF NOT EXISTS airplay_stations (
    station_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    discovered_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS airplay_plays (
    id INTEGER PRIMARY KEY,
    station_id INTEGER NOT NULL REFERENCES airplay_stations(station_id) ON DELETE CASCADE,
    played_at TEXT NOT NULL,
    artist TEXT NOT NULL,
    title TEXT NOT NULL,
    artist_key TEXT NOT NULL,
    title_key TEXT NOT NULL,
    song_id INTEGER REFERENCES songs(id) ON DELETE SET NULL,
    source_url TEXT,
    retrieved_at TEXT NOT NULL,
    UNIQUE(station_id, played_at, artist_key, title_key)
);

CREATE TABLE IF NOT EXISTS airplay_windows (
    station_id INTEGER NOT NULL REFERENCES airplay_stations(station_id) ON DELETE CASCADE,
    play_date TEXT NOT NULL,
    start_hour INTEGER NOT NULL,
    end_hour INTEGER NOT NULL,
    fetched_at TEXT NOT NULL,
    play_count INTEGER NOT NULL DEFAULT 0,
    source_url TEXT,
    success INTEGER NOT NULL DEFAULT 1,
    message TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(station_id, play_date, start_hour)
);

"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")

def _table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row["name"]) for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:
        return set()


def _ensure_column(con: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if column not in _table_columns(con, table):
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _ensure_airplay_schema(con: sqlite3.Connection) -> None:
    """Make the airplay tables usable even after a partial/older experiment.

    0.3.6 introduced the production airplay schema.  A few development builds
    had tables with the same names but a smaller set of columns.  SQLite's
    ``CREATE TABLE IF NOT EXISTS`` quite correctly leaves such a table alone,
    but then an index on a new column aborts the whole application startup.

    Keep the migration deliberately additive: no existing chart or airplay row
    is dropped.  New databases still get the stricter canonical definitions
    from SCHEMA; old/partial tables merely receive the columns the current code
    needs.
    """
    # SCHEMA above creates these on a clean database.  The calls below are for
    # an existing table with an older shape.
    station_columns = {
        "station_id": "INTEGER",
        "name": "TEXT NOT NULL DEFAULT ''",
        "slug": "TEXT NOT NULL DEFAULT ''",
        "source_url": "TEXT NOT NULL DEFAULT ''",
        "active": "INTEGER NOT NULL DEFAULT 1",
        "discovered_at": "TEXT NOT NULL DEFAULT ''",
        "updated_at": "TEXT NOT NULL DEFAULT ''",
    }
    for column, ddl in station_columns.items():
        _ensure_column(con, "airplay_stations", column, ddl)

    # If station_id had to be added to a legacy table, give legacy rows stable
    # negative IDs.  Positive odSluchane IDs discovered later therefore cannot
    # collide with them.
    try:
        con.execute(
            "UPDATE airplay_stations SET station_id=-rowid "
            "WHERE station_id IS NULL OR station_id=0"
        )
    except sqlite3.OperationalError:
        pass

    play_columns = {
        "station_id": "INTEGER",
        "played_at": "TEXT NOT NULL DEFAULT ''",
        "artist": "TEXT NOT NULL DEFAULT ''",
        "title": "TEXT NOT NULL DEFAULT ''",
        "artist_key": "TEXT NOT NULL DEFAULT ''",
        "title_key": "TEXT NOT NULL DEFAULT ''",
        "song_id": "INTEGER",
        "source_url": "TEXT NOT NULL DEFAULT ''",
        "retrieved_at": "TEXT NOT NULL DEFAULT ''",
    }
    for column, ddl in play_columns.items():
        _ensure_column(con, "airplay_plays", column, ddl)

    window_columns = {
        "station_id": "INTEGER",
        "play_date": "TEXT NOT NULL DEFAULT ''",
        "start_hour": "INTEGER NOT NULL DEFAULT 0",
        "end_hour": "INTEGER NOT NULL DEFAULT 0",
        "fetched_at": "TEXT NOT NULL DEFAULT ''",
        "play_count": "INTEGER NOT NULL DEFAULT 0",
        "source_url": "TEXT NOT NULL DEFAULT ''",
        "success": "INTEGER NOT NULL DEFAULT 1",
        "message": "TEXT NOT NULL DEFAULT ''",
    }
    for column, ddl in window_columns.items():
        _ensure_column(con, "airplay_windows", column, ddl)

    # Create indexes only *after* the additive migration, otherwise a legacy
    # table missing e.g. played_at makes executescript(SCHEMA) fail at startup.
    con.execute("CREATE INDEX IF NOT EXISTS idx_airplay_stations_station_id ON airplay_stations(station_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_airplay_plays_time_station ON airplay_plays(played_at, station_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_airplay_plays_track ON airplay_plays(title_key, artist_key)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_airplay_windows_date ON airplay_windows(play_date, station_id)")


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().replace("&", " and ").replace("`", "'")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def artist_anchor(value: str) -> str:
    """Stable primary-artist key used only to reconcile cross-source credits.

    Examples: ``Martin Garrix x Ed Sheeran`` and ``Martin Garrix, Ed Sheeran``
    share the same anchor. Exact artist/title matching is always preferred.
    """
    raw = unicodedata.normalize("NFKD", value or "")
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch)).lower()
    raw = raw.replace("×", " x ")
    parts = re.split(r"\s+(?:feat\.?|ft\.?|with)\s+|\s+[xX]\s+|,|/|&", raw, maxsplit=1)
    anchor = normalize(parts[0] if parts else raw)
    anchor = re.sub(r"\b20\d{2}\b$", "", anchor).strip()
    return anchor


def _merge_duplicate_songs(con: sqlite3.Connection) -> int:
    """One-time migration for aliases created before artist-anchor matching.

    It only merges records with the same normalized title and the same primary
    artist anchor. Existing chart history and the newest manual note/status are
    preserved.
    """
    rows = con.execute(
        """SELECT s.*, COUNT(e.id) AS entry_count
           FROM songs s LEFT JOIN chart_entries e ON e.song_id=s.id
           GROUP BY s.id ORDER BY s.id"""
    ).fetchall()
    groups: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for row in rows:
        key = (str(row["title_key"]), artist_anchor(str(row["artist"])))
        if not key[0] or not key[1]:
            continue
        groups.setdefault(key, []).append(row)

    merged = 0
    for variants in groups.values():
        if len(variants) < 2:
            continue
        # Prefer the credit already carrying most chart history.
        variants = sorted(variants, key=lambda r: (-int(r["entry_count"] or 0), int(r["id"])))
        canonical = variants[0]
        cid = int(canonical["id"])
        ids = [int(v["id"]) for v in variants]

        notes = con.execute(
            f"SELECT * FROM song_notes WHERE song_id IN ({','.join('?' for _ in ids)}) ORDER BY updated_at DESC",
            ids,
        ).fetchall()
        heard = any(bool(n["heard"]) for n in notes)
        chosen = notes[0] if notes else None
        note_texts = []
        for n in notes:
            txt = str(n["note"] or "").strip()
            if txt and txt not in note_texts:
                note_texts.append(txt)
        if notes:
            status = str(chosen["status"] or "Nie słuchałem")
            con.execute(
                """INSERT INTO song_notes(song_id,heard,status,note,updated_at) VALUES(?,?,?,?,?)
                   ON CONFLICT(song_id) DO UPDATE SET heard=excluded.heard,status=excluded.status,note=excluded.note,updated_at=excluded.updated_at""",
                (cid, int(heard), status, "\n---\n".join(note_texts), chosen["updated_at"]),
            )

        for dup in variants[1:]:
            did = int(dup["id"])
            dup_entries = con.execute("SELECT id,issue_id FROM chart_entries WHERE song_id=?", (did,)).fetchall()
            for ent in dup_entries:
                conflict = con.execute(
                    "SELECT id FROM chart_entries WHERE issue_id=? AND song_id=?",
                    (int(ent["issue_id"]), cid),
                ).fetchone()
                if conflict:
                    con.execute("DELETE FROM chart_entries WHERE id=?", (int(ent["id"]),))
                else:
                    con.execute("UPDATE chart_entries SET song_id=? WHERE id=?", (cid, int(ent["id"])))
            con.execute("DELETE FROM song_notes WHERE song_id=?", (did,))
            con.execute("DELETE FROM songs WHERE id=?", (did,))
            merged += 1
    return merged


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
    except Exception:
        con.rollback()
        raise
    else:
        con.commit()
    finally:
        con.close()


def init_db() -> None:
    global _INITIALIZED_DB_PATH
    current_path = str(DB_PATH)
    required_markers = {
        "song_alias_merge_v1",
        "billboard_metadata_reset_v1",
        "billboard_metadata_reset_v2",
        "source_checks_v1",
        "airplay_schema_v2",
        "airplay_detach_chart_v1",
    }
    if _INITIALIZED_DB_PATH == current_path and DB_PATH.exists():
        # Very cheap fast path. If a migration marker was deliberately removed
        # (tests/maintenance), fall through and run migrations again.
        try:
            con0 = sqlite3.connect(DB_PATH, timeout=2)
            placeholders = ",".join("?" for _ in required_markers)
            keys = {r[0] for r in con0.execute(
                f"SELECT key FROM app_meta WHERE key IN ({placeholders})",
                tuple(sorted(required_markers)),
            ).fetchall()}
            con0.close()
            if required_markers.issubset(keys):
                return
        except Exception:
            pass

    # web + worker start together and share the same SQLite file.  Serialize
    # schema/migration work across processes so a simultaneous deploy cannot
    # make one container fail in executescript().
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    init_lock = FileLock(f"{DB_PATH}.init.lock", timeout=90)
    with init_lock:
        # Another process may have completed the migration while we waited.
        try:
            con0 = sqlite3.connect(DB_PATH, timeout=5)
            con0.row_factory = sqlite3.Row
            tables = {r[0] for r in con0.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='app_meta'"
            ).fetchall()}
            if "app_meta" in tables:
                placeholders = ",".join("?" for _ in required_markers)
                keys = {r[0] for r in con0.execute(
                    f"SELECT key FROM app_meta WHERE key IN ({placeholders})",
                    tuple(sorted(required_markers)),
                ).fetchall()}
                if required_markers.issubset(keys):
                    con0.close()
                    _INITIALIZED_DB_PATH = current_path
                    return
            con0.close()
        except Exception:
            try:
                con0.close()
            except Exception:
                pass

        # A long-running writer can still briefly hold SQLite's write lock.
        # busy_timeout + a few retries turns that into a short startup delay
        # instead of a dead Streamlit page.
        last_exc: Exception | None = None
        for attempt in range(5):
            try:
                with connect() as con:
                    con.execute("PRAGMA busy_timeout=60000")
                    try:
                        con.execute("PRAGMA journal_mode=WAL")
                    except sqlite3.OperationalError as exc:
                        # WAL is an optimisation, not a prerequisite.  If an
                        # existing connection temporarily prevents changing the
                        # journal mode, continue with the current mode.
                        if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                            raise
                    con.executescript(SCHEMA)
                    _ensure_airplay_schema(con)

                    # Lightweight migrations for existing MVP databases.
                    cols = {row["name"] for row in con.execute("PRAGMA table_info(chart_entries)").fetchall()}
                    if "reported_weeks" not in cols:
                        con.execute("ALTER TABLE chart_entries ADD COLUMN reported_weeks INTEGER")
                    if "reported_peak" not in cols:
                        con.execute("ALTER TABLE chart_entries ADD COLUMN reported_peak INTEGER")

                    # Remove incomplete 100-position issues left by early experimental
                    # parsers / failed pre-0.1.9 transactions. They would otherwise make
                    # coverage look complete and distort scores until a valid issue lands.
                    con.execute(
                        """DELETE FROM chart_issues
                           WHERE source IN ('OLIA','OLIS','UK','BILLBOARD')
                             AND chart_size >= 50
                             AND (SELECT COUNT(*) FROM chart_entries e WHERE e.issue_id=chart_issues.id) < 50"""
                    )
                    # Remove the one ZET demonstration issue used by early MVP builds.
                    con.execute(
                        """DELETE FROM chart_issues
                           WHERE source='ZET' AND issue_key='ZET-2026-08-06'
                             AND source_url='manual seed from public chart'"""
                    )

                    migration = con.execute("SELECT value FROM app_meta WHERE key='song_alias_merge_v1'").fetchone()
                    if not migration:
                        merged = _merge_duplicate_songs(con)
                        con.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('song_alias_merge_v1',?)", (str(merged),))

                    bb_reset = con.execute("SELECT value FROM app_meta WHERE key='billboard_metadata_reset_v1'").fetchone()
                    if not bb_reset:
                        con.execute(
                            """UPDATE chart_entries
                               SET previous_position=NULL, reported_weeks=NULL, reported_peak=NULL
                               WHERE issue_id IN (SELECT id FROM chart_issues WHERE source='BILLBOARD')"""
                        )
                        con.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('billboard_metadata_reset_v1','done')")

                    bb_reset_v2 = con.execute("SELECT value FROM app_meta WHERE key='billboard_metadata_reset_v2'").fetchone()
                    if not bb_reset_v2:
                        con.execute(
                            """UPDATE chart_entries
                               SET previous_position=NULL, reported_weeks=NULL, reported_peak=NULL
                               WHERE issue_id IN (SELECT id FROM chart_issues WHERE source='BILLBOARD')"""
                        )
                        con.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('billboard_metadata_reset_v2','done')")

                    con.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('source_checks_v1','done')")
                    con.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('airplay_schema_v2','done')")
                    detach = con.execute("SELECT value FROM app_meta WHERE key='airplay_detach_chart_v1'").fetchone()
                    if not detach:
                        # Emisje are deliberately independent from chart songs. Keep the
                        # nullable legacy column for schema compatibility, but remove every
                        # historical cross-link and never populate it again.
                        con.execute("UPDATE airplay_plays SET song_id=NULL WHERE song_id IS NOT NULL")
                        con.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('airplay_detach_chart_v1','done')")
                last_exc = None
                break
            except sqlite3.OperationalError as exc:
                last_exc = exc
                text = str(exc).lower()
                if "locked" not in text and "busy" not in text:
                    raise
                if attempt >= 4:
                    raise
                time.sleep(0.7 * (attempt + 1))
        if last_exc is not None:
            raise last_exc

    _INITIALIZED_DB_PATH = current_path

def get_or_create_song(con: sqlite3.Connection, artist: str, title: str, release_date: str | None = None) -> int:
    akey, tkey = normalize(artist), normalize(title)
    row = con.execute("SELECT id, release_date FROM songs WHERE artist_key=? AND title_key=?", (akey, tkey)).fetchone()
    if not row:
        anchor = artist_anchor(artist)
        candidates = con.execute("SELECT id,artist,release_date FROM songs WHERE title_key=?", (tkey,)).fetchall()
        matches = [r for r in candidates if artist_anchor(str(r["artist"])) == anchor]
        if len(matches) == 1:
            row = matches[0]
    if row:
        if release_date and not row["release_date"]:
            con.execute("UPDATE songs SET release_date=? WHERE id=?", (release_date, row["id"]))
        return int(row["id"])
    cur = con.execute(
        "INSERT INTO songs(artist,title,artist_key,title_key,release_date,created_at) VALUES (?,?,?,?,?,?)",
        (artist.strip(), title.strip(), akey, tkey, release_date, _utcnow()),
    )
    return int(cur.lastrowid)

def _validated_entries(source: str, entries: Iterable[dict]) -> list[dict]:
    rows = [dict(e) for e in entries]
    if source in {"UK", "BILLBOARD"}:
        meta = {"weeks", "week", "peak", "lw", "last week", "peak pos", "peak pos.", "wks on chart", "weeks on chart"}
        rows = [
            e for e in rows
            if not (normalize(str(e.get("title", ""))) in meta and normalize(str(e.get("artist", ""))) in meta)
        ]
    seen_pos: dict[int, str] = {}
    seen_song: dict[tuple[str, str], int] = {}
    for e in rows:
        if "position" not in e or "artist" not in e or "title" not in e:
            raise ValueError(f"{source}: wpis bez position/artist/title: {e!r}")
        pos = int(e["position"])
        song_key = (artist_anchor(str(e["artist"])), normalize(str(e["title"])))
        if pos in seen_pos:
            raise ValueError(f"{source}: parser zwrócił dwie pozycje #{pos}")
        if song_key in seen_song:
            raise ValueError(
                f"{source}: parser zwrócił ten sam utwór na pozycjach "
                f"#{seen_song[song_key]} i #{pos}: {e['artist']} — {e['title']}"
            )
        seen_pos[pos] = f"{e['artist']} — {e['title']}"
        seen_song[song_key] = pos
    return rows


def upsert_issue(source: str, chart_date: str | date, issue_key: str, chart_size: int, entries: Iterable[dict], source_url: str | None = None) -> int:
    entries = _validated_entries(source.upper(), entries)
    init_db()
    chart_date = chart_date.isoformat() if isinstance(chart_date, date) else str(chart_date)
    source = source.upper()
    with connect() as con:
        row = con.execute("SELECT id FROM chart_issues WHERE source=? AND issue_key=?", (source, str(issue_key))).fetchone()
        if row:
            issue_id = int(row["id"])
            con.execute(
                "UPDATE chart_issues SET chart_date=?, chart_size=?, source_url=?, retrieved_at=? WHERE id=?",
                (chart_date, int(chart_size), source_url, _utcnow(), issue_id),
            )
            con.execute("DELETE FROM chart_entries WHERE issue_id=?", (issue_id,))
        else:
            cur = con.execute(
                "INSERT INTO chart_issues(source,chart_date,issue_key,chart_size,source_url,retrieved_at) VALUES (?,?,?,?,?,?)",
                (source, chart_date, str(issue_key), int(chart_size), source_url, _utcnow()),
            )
            issue_id = int(cur.lastrowid)

        for e in entries:
            song_id = get_or_create_song(con, e["artist"], e["title"], e.get("release_date"))
            con.execute(
                """INSERT INTO chart_entries(
                    issue_id,song_id,position,previous_position,reported_weeks,reported_peak
                ) VALUES (?,?,?,?,?,?)""",
                (
                    issue_id, song_id, int(e["position"]), e.get("previous_position"),
                    e.get("reported_weeks"), e.get("reported_peak"),
                ),
            )
        return issue_id


def update_note(song_id: int, heard: bool, status: str, note: str) -> None:
    init_db()
    with connect() as con:
        con.execute(
            """INSERT INTO song_notes(song_id,heard,status,note,updated_at) VALUES(?,?,?,?,?)
               ON CONFLICT(song_id) DO UPDATE SET heard=excluded.heard,status=excluded.status,note=excluded.note,updated_at=excluded.updated_at""",
            (song_id, int(heard), status, note, _utcnow()),
        )



def chart_revision() -> str:
    """Cache key for chart-derived metrics only; note/status edits do not invalidate it."""
    init_db()
    with connect() as con:
        row = con.execute(
            """SELECT
                 COALESCE((SELECT MAX(retrieved_at) FROM chart_issues),'') AS charts,
                 (SELECT COUNT(*) FROM chart_entries) AS entries,
                 (SELECT COUNT(*) FROM songs) AS songs"""
        ).fetchone()
        return f"{row['charts']}|{row['entries']}|{row['songs']}"


def load_notes() -> list[dict]:
    """Small live overlay for user state; intentionally separate from expensive chart metrics."""
    init_db()
    with connect() as con:
        rows = con.execute(
            "SELECT song_id,heard,status,note,updated_at FROM song_notes"
        ).fetchall()
        return [dict(r) for r in rows]


def db_revision() -> str:
    """Backward-compatible full revision key."""
    init_db()
    with connect() as con:
        row = con.execute(
            """SELECT
                 COALESCE((SELECT MAX(retrieved_at) FROM chart_issues),'') AS charts,
                 COALESCE((SELECT MAX(updated_at) FROM song_notes),'') AS notes,
                 (SELECT COUNT(*) FROM chart_entries) AS entries,
                 (SELECT COUNT(*) FROM songs) AS songs"""
        ).fetchone()
        return f"{row['charts']}|{row['notes']}|{row['entries']}|{row['songs']}"



def record_source_check(source: str, success: bool, message: str = "", chart_date: str | None = None, issue_key: str | None = None) -> None:
    """Record every collector attempt, including failures, for Dashboard freshness warnings."""
    init_db()
    with connect() as con:
        con.execute(
            "INSERT INTO source_checks(source,checked_at,success,message,chart_date,issue_key) VALUES(?,?,?,?,?,?)",
            (source.upper(), _utcnow(), int(bool(success)), str(message or "")[:2000], chart_date, issue_key),
        )
        # Keep the table bounded; a few hundred checks per source is plenty for diagnostics.
        con.execute(
            """DELETE FROM source_checks WHERE id IN (
                   SELECT id FROM source_checks WHERE source=? ORDER BY checked_at DESC LIMIT -1 OFFSET 400
               )""",
            (source.upper(),),
        )


def latest_source_checks() -> list[dict]:
    init_db()
    with connect() as con:
        rows = con.execute(
            """SELECT c.source,c.checked_at,c.success,c.message,c.chart_date,c.issue_key
               FROM source_checks c
               JOIN (SELECT source, MAX(id) AS max_id FROM source_checks GROUP BY source) x
                 ON x.source=c.source AND x.max_id=c.id
               ORDER BY c.source"""
        ).fetchall()
        return [dict(r) for r in rows]



def source_check_day_summary(day: date | None = None, tz_name: str = "Europe/Warsaw") -> list[dict]:
    """Summarize all collector attempts for one local calendar day.

    Freshness is a *day-level* property: once a source has been downloaded
    successfully today, a later failed retry must not make the Dashboard claim
    that today's data is missing. The latest attempt is still returned for
    diagnostics, but ``success_today`` stays true if any attempt succeeded.
    """
    init_db()
    tz = ZoneInfo(tz_name)
    local_day = day or datetime.now(tz).date()
    start_local = datetime.combine(local_day, dt_time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc).isoformat(timespec="microseconds")
    end_utc = end_local.astimezone(timezone.utc).isoformat(timespec="microseconds")
    with connect() as con:
        rows = con.execute(
            """SELECT source,checked_at,success,message,chart_date,issue_key
               FROM source_checks
               WHERE checked_at>=? AND checked_at<?
               ORDER BY source, checked_at ASC, id ASC""",
            (start_utc, end_utc),
        ).fetchall()

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(str(row["source"]), []).append(dict(row))

    out: list[dict] = []
    for source, items in sorted(grouped.items()):
        successes = [x for x in items if bool(x.get("success"))]
        latest = items[-1]
        latest_success = successes[-1] if successes else None
        out.append({
            "source": source,
            "attempted_today": True,
            "success_today": bool(successes),
            "attempts_today": len(items),
            "successes_today": len(successes),
            "latest_checked_at": latest.get("checked_at"),
            "latest_success_at": latest_success.get("checked_at") if latest_success else None,
            "latest_success_message": latest_success.get("message") if latest_success else "",
            "latest_success_chart_date": latest_success.get("chart_date") if latest_success else None,
            "latest_success_issue_key": latest_success.get("issue_key") if latest_success else None,
            "latest_attempt_success": bool(latest.get("success")),
            "latest_attempt_message": latest.get("message") or "",
        })
    return out

def list_issues(source: str | None = None, limit: int = 1000) -> list[dict]:
    """Return stored chart issues newest first for archive browsing."""
    init_db()
    limit = max(1, min(int(limit), 20000))
    with connect() as con:
        if source and source.upper() != "ALL":
            rows = con.execute(
                """SELECT i.id,i.source,i.chart_date,i.issue_key,i.chart_size,i.source_url,i.retrieved_at,
                          COUNT(e.id) AS entries
                   FROM chart_issues i LEFT JOIN chart_entries e ON e.issue_id=i.id
                   WHERE i.source=?
                   GROUP BY i.id
                   ORDER BY i.chart_date DESC,i.id DESC LIMIT ?""",
                (source.upper(), limit),
            ).fetchall()
        else:
            rows = con.execute(
                """SELECT i.id,i.source,i.chart_date,i.issue_key,i.chart_size,i.source_url,i.retrieved_at,
                          COUNT(e.id) AS entries
                   FROM chart_issues i LEFT JOIN chart_entries e ON e.issue_id=i.id
                   GROUP BY i.id
                   ORDER BY i.chart_date DESC,i.source,i.id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


def issue_entries(issue_id: int) -> list[dict]:
    """Return one archived chart issue in rank order."""
    init_db()
    with connect() as con:
        rows = con.execute(
            """SELECT e.position,s.artist,s.title,e.previous_position,e.reported_weeks,e.reported_peak,s.id AS song_id
               FROM chart_entries e JOIN songs s ON s.id=e.song_id
               WHERE e.issue_id=? ORDER BY e.position""",
            (int(issue_id),),
        ).fetchall()
        return [dict(r) for r in rows]


def issue_entries_enriched(issue_id: int) -> list[dict]:
    """Return one issue with useful historical metadata filled locally.

    Some sources do not publish LW/weeks/peak.  For those fields we derive:
    - previous_position from the immediately previous stored issue of the source,
    - weeks from distinct calendar weeks seen up to this issue,
    - peak from the best stored position up to this issue.
    Reported source metadata wins when it is richer.
    """
    init_db()
    with connect() as con:
        issue = con.execute(
            "SELECT id,source,chart_date FROM chart_issues WHERE id=?", (int(issue_id),)
        ).fetchone()
        if not issue:
            return []
        src = str(issue["source"])
        chart_date = str(issue["chart_date"])

        prev_issue = con.execute(
            """SELECT id FROM chart_issues
               WHERE source=? AND (chart_date < ? OR (chart_date=? AND id < ?))
               ORDER BY chart_date DESC,id DESC LIMIT 1""",
            (src, chart_date, chart_date, int(issue_id)),
        ).fetchone()
        prev_map: dict[int, int] = {}
        if prev_issue:
            prev_rows = con.execute(
                "SELECT song_id,position FROM chart_entries WHERE issue_id=?",
                (int(prev_issue["id"]),),
            ).fetchall()
            prev_map = {int(r["song_id"]): int(r["position"]) for r in prev_rows}

        stats = con.execute(
            """SELECT e.song_id, MIN(e.position) AS local_peak,
                      COUNT(DISTINCT strftime('%Y-%W', i.chart_date)) AS local_weeks
               FROM chart_entries e JOIN chart_issues i ON i.id=e.issue_id
               WHERE i.source=? AND i.chart_date<=?
               GROUP BY e.song_id""",
            (src, chart_date),
        ).fetchall()
        stat_map = {int(r["song_id"]): dict(r) for r in stats}

        rows = con.execute(
            """SELECT e.position,s.artist,s.title,e.previous_position,e.reported_weeks,e.reported_peak,
                      s.id AS song_id,
                      COALESCE(n.heard,0) AS heard,
                      COALESCE(n.status,'Nie słuchałem') AS status,
                      COALESCE(n.note,'') AS note
               FROM chart_entries e
               JOIN songs s ON s.id=e.song_id
               LEFT JOIN song_notes n ON n.song_id=s.id
               WHERE e.issue_id=? ORDER BY e.position""",
            (int(issue_id),),
        ).fetchall()

        out: list[dict] = []
        for raw in rows:
            r = dict(raw)
            sid = int(r["song_id"])
            st = stat_map.get(sid, {})
            previous = r.get("previous_position")
            if previous is None:
                previous = prev_map.get(sid)
            local_weeks = int(st.get("local_weeks") or 0)
            reported_weeks = int(r["reported_weeks"]) if r.get("reported_weeks") is not None else 0
            weeks = max(local_weeks, reported_weeks)
            local_peak = int(st.get("local_peak") or r["position"])
            if r.get("reported_peak") is not None:
                peak = min(local_peak, int(r["reported_peak"]))
            else:
                peak = local_peak
            r["previous_position"] = previous
            r["reported_weeks"] = weeks
            r["reported_peak"] = peak
            r["heard"] = bool(r.get("heard"))
            out.append(r)
        return out


def latest_issues() -> list[dict]:
    init_db()
    with connect() as con:
        rows = con.execute(
            """SELECT i.source, i.chart_date, i.issue_key, i.retrieved_at, COUNT(e.id) AS entries
               FROM chart_issues i LEFT JOIN chart_entries e ON e.issue_id=i.id
               WHERE i.chart_date = (
                   SELECT MAX(i2.chart_date) FROM chart_issues i2 WHERE i2.source=i.source
               )
               GROUP BY i.id ORDER BY i.source"""
        ).fetchall()
        return [dict(r) for r in rows]


def upsert_airplay_stations(stations: Iterable[dict]) -> int:
    """Insert/update radio stations discovered on odSluchane.eu."""
    init_db()
    now = _utcnow()
    count = 0
    with connect() as con:
        for station in stations:
            try:
                station_id = int(station["station_id"])
            except Exception:
                continue
            name = str(station.get("name") or f"Stacja {station_id}").strip()
            slug = str(station.get("slug") or "").strip()
            source_url = str(station.get("source_url") or "").strip()
            active = int(bool(station.get("active", True)))
            cur = con.execute(
                """UPDATE airplay_stations
                   SET name=?,slug=?,source_url=?,active=?,updated_at=?
                   WHERE station_id=?""",
                (name, slug, source_url, active, now, station_id),
            )
            if int(cur.rowcount or 0) == 0:
                con.execute(
                    """INSERT INTO airplay_stations(station_id,name,slug,source_url,active,discovered_at,updated_at)
                       VALUES(?,?,?,?,?,?,?)""",
                    (station_id, name, slug, source_url, active, now, now),
                )
            count += 1
    return count


def list_airplay_stations(active_only: bool = True) -> list[dict]:
    init_db()
    with connect() as con:
        sql = "SELECT station_id,name,slug,source_url,active,discovered_at,updated_at FROM airplay_stations"
        params: tuple = ()
        if active_only:
            sql += " WHERE active=1"
        sql += " ORDER BY name COLLATE NOCASE, station_id"
        rows = con.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def _match_song_id(con: sqlite3.Connection, artist: str, title: str) -> int | None:
    """Best-effort match of an airplay credit to an existing chart song."""
    akey = normalize(artist)
    tkey = normalize(title)
    if not tkey:
        return None
    exact = con.execute(
        "SELECT id FROM songs WHERE artist_key=? AND title_key=? LIMIT 1",
        (akey, tkey),
    ).fetchone()
    if exact:
        return int(exact["id"])
    anchor = artist_anchor(artist)
    if not anchor:
        return None
    candidates = con.execute(
        "SELECT id,artist FROM songs WHERE title_key=? ORDER BY id",
        (tkey,),
    ).fetchall()
    for row in candidates:
        if artist_anchor(str(row["artist"])) == anchor:
            return int(row["id"])
    return None


def airplay_window_exists(station_id: int, play_date: date | str, start_hour: int) -> bool:
    init_db()
    d = play_date.isoformat() if isinstance(play_date, date) else str(play_date)
    with connect() as con:
        row = con.execute(
            "SELECT success FROM airplay_windows WHERE station_id=? AND play_date=? AND start_hour=?",
            (int(station_id), d, int(start_hour)),
        ).fetchone()
        return bool(row and row["success"])


def store_airplay_window(
    station_id: int,
    station_name: str,
    play_date: date | str,
    start_hour: int,
    plays: Iterable[dict],
    source_url: str = "",
    *,
    success: bool = True,
    message: str = "",
) -> int:
    """Replace one two-hour station window atomically.

    Re-fetching the same window is safe: prior rows in that interval are removed
    and the newly parsed rows are inserted with a uniqueness guard.
    """
    init_db()
    station_id = int(station_id)
    start_hour = int(start_hour) % 24
    d = date.fromisoformat(play_date) if isinstance(play_date, str) else play_date
    end_hour = (start_hour + 2) % 24
    start_dt = datetime.combine(d, dt_time(start_hour, 0))
    end_dt = start_dt + timedelta(hours=2)
    now = _utcnow()
    rows = list(plays)

    with connect() as con:
        station_label = str(station_name or f"Stacja {station_id}")
        cur_station = con.execute(
            "UPDATE airplay_stations SET name=?,updated_at=? WHERE station_id=?",
            (station_label, now, station_id),
        )
        if int(cur_station.rowcount or 0) == 0:
            con.execute(
                """INSERT INTO airplay_stations(station_id,name,slug,source_url,active,discovered_at,updated_at)
                   VALUES(?,?,?,?,1,?,?)""",
                (station_id, station_label, "", "", now, now),
            )
        con.execute(
            "DELETE FROM airplay_plays WHERE station_id=? AND played_at>=? AND played_at<?",
            (station_id, start_dt.isoformat(timespec="minutes"), end_dt.isoformat(timespec="minutes")),
        )
        inserted = 0
        for play in rows:
            artist = str(play.get("artist") or "").strip()
            title = str(play.get("title") or "").strip()
            played_at = str(play.get("played_at") or "").strip()
            if not artist or not title or not played_at:
                continue
            artist_key = artist_anchor(artist) or normalize(artist)
            title_key = normalize(title)
            if not title_key:
                continue
            song_id = None
            cur = con.execute(
                """INSERT OR IGNORE INTO airplay_plays(
                       station_id,played_at,artist,title,artist_key,title_key,song_id,source_url,retrieved_at
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    station_id, played_at, artist, title, artist_key, title_key, song_id,
                    str(play.get("source_url") or source_url or ""), now,
                ),
            )
            inserted += int(cur.rowcount or 0)
        con.execute(
            "DELETE FROM airplay_windows WHERE station_id=? AND play_date=? AND start_hour=?",
            (station_id, d.isoformat(), start_hour),
        )
        con.execute(
            """INSERT INTO airplay_windows(station_id,play_date,start_hour,end_hour,fetched_at,play_count,source_url,success,message)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                station_id, d.isoformat(), start_hour, end_hour, now, inserted,
                str(source_url or ""), int(bool(success)), str(message or "")[:1000],
            ),
        )
        return inserted


def airplay_summary(station_ids: Iterable[int], start_date: date | str, end_date: date | str) -> list[dict]:
    """Aggregate exact stored spins independently from chart/notowania data."""
    init_db()
    ids = sorted({int(x) for x in station_ids})
    if not ids:
        return []
    start = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
    end = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
    if end < start:
        start, end = end, start
    start_ts = datetime.combine(start, dt_time.min).isoformat(timespec="minutes")
    end_ts = datetime.combine(end + timedelta(days=1), dt_time.min).isoformat(timespec="minutes")
    placeholders = ",".join("?" for _ in ids)
    with connect() as con:
        rows = con.execute(
            f"""SELECT p.artist_key,p.title_key,p.station_id,s.name AS station_name,
                       MAX(p.artist) AS artist,MAX(p.title) AS title,
                       COUNT(*) AS spins,MAX(p.played_at) AS last_play
                FROM airplay_plays p
                JOIN airplay_stations s ON s.station_id=p.station_id
                WHERE p.station_id IN ({placeholders}) AND p.played_at>=? AND p.played_at<?
                GROUP BY p.artist_key,p.title_key,p.station_id
                ORDER BY spins DESC""",
            (*ids, start_ts, end_ts),
        ).fetchall()
        station_rows = [dict(r) for r in rows]

    grouped: dict[tuple[str, str], dict] = {}
    for r in station_rows:
        key = (str(r["artist_key"]), str(r["title_key"]))
        g = grouped.setdefault(key, {
            "artist_key": key[0],
            "title_key": key[1],
            "artist": str(r.get("artist") or ""),
            "title": str(r.get("title") or ""),
            "spins": 0,
            "stations_count": 0,
            "max_station_spins": 0,
            "top_station": "",
            "last_play": "",
        })
        spins = int(r.get("spins") or 0)
        g["spins"] += spins
        g["stations_count"] += 1
        if spins > int(g["max_station_spins"]):
            g["max_station_spins"] = spins
            g["top_station"] = str(r.get("station_name") or "")
            g["artist"] = str(r.get("artist") or g["artist"])
            g["title"] = str(r.get("title") or g["title"])
        last_play = str(r.get("last_play") or "")
        if last_play > str(g["last_play"] or ""):
            g["last_play"] = last_play
    out = []
    for g in grouped.values():
        stations = max(1, int(g["stations_count"]))
        g["avg_per_station"] = round(float(g["spins"]) / stations, 1)
        out.append(g)
    out.sort(key=lambda r: (-int(r["spins"]), -int(r["stations_count"]), str(r["artist"]).casefold(), str(r["title"]).casefold()))
    return out


def airplay_track_detail(
    station_ids: Iterable[int],
    start_date: date | str,
    end_date: date | str,
    artist_key: str,
    title_key: str,
    *,
    history_limit: int = 2000,
) -> dict:
    """Break one airplay track down by station/day and return recent exact plays."""
    init_db()
    ids = sorted({int(x) for x in station_ids})
    if not ids or not str(title_key or "").strip():
        return {"total_spins": 0, "stations_count": 0, "first_play": None, "last_play": None, "stations": [], "daily": [], "plays": []}
    start = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
    end = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
    if end < start:
        start, end = end, start
    start_ts = datetime.combine(start, dt_time.min).isoformat(timespec="minutes")
    end_ts = datetime.combine(end + timedelta(days=1), dt_time.min).isoformat(timespec="minutes")
    placeholders = ",".join("?" for _ in ids)
    common_where = f"p.station_id IN ({placeholders}) AND p.played_at>=? AND p.played_at<? AND p.artist_key=? AND p.title_key=?"
    params = (*ids, start_ts, end_ts, str(artist_key), str(title_key))
    with connect() as con:
        station_rows = [dict(r) for r in con.execute(
            f"""SELECT s.name AS station,COUNT(*) AS spins,
                       COUNT(DISTINCT substr(p.played_at,1,10)) AS active_days,
                       MIN(p.played_at) AS first_play,MAX(p.played_at) AS last_play
                FROM airplay_plays p JOIN airplay_stations s ON s.station_id=p.station_id
                WHERE {common_where}
                GROUP BY p.station_id,s.name
                ORDER BY spins DESC,s.name COLLATE NOCASE""",
            params,
        ).fetchall()]
        daily_rows = [dict(r) for r in con.execute(
            f"""SELECT substr(p.played_at,1,10) AS play_date,s.name AS station,COUNT(*) AS spins
                FROM airplay_plays p JOIN airplay_stations s ON s.station_id=p.station_id
                WHERE {common_where}
                GROUP BY play_date,p.station_id,s.name
                ORDER BY play_date,s.name COLLATE NOCASE""",
            params,
        ).fetchall()]
        play_rows = [dict(r) for r in con.execute(
            f"""SELECT p.played_at,s.name AS station
                FROM airplay_plays p JOIN airplay_stations s ON s.station_id=p.station_id
                WHERE {common_where}
                ORDER BY p.played_at DESC,p.station_id
                LIMIT ?""",
            (*params, max(1, int(history_limit))),
        ).fetchall()]

    total = sum(int(r.get("spins") or 0) for r in station_rows)
    first_play = min((str(r.get("first_play") or "") for r in station_rows if r.get("first_play")), default=None)
    last_play = max((str(r.get("last_play") or "") for r in station_rows if r.get("last_play")), default=None)
    return {
        "total_spins": total,
        "stations_count": len(station_rows),
        "first_play": first_play,
        "last_play": last_play,
        "stations": station_rows,
        "daily": daily_rows,
        "plays": play_rows,
    }


def airplay_coverage(station_ids: Iterable[int] | None = None) -> dict:
    init_db()
    ids = sorted({int(x) for x in station_ids or []})
    where = ""
    params: tuple = ()
    if ids:
        placeholders = ",".join("?" for _ in ids)
        where = f" WHERE station_id IN ({placeholders})"
        params = tuple(ids)
    with connect() as con:
        row = con.execute(
            f"""SELECT COUNT(*) AS windows,
                       SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) AS ok_windows,
                       MIN(play_date) AS first_date,MAX(play_date) AS last_date,
                       COUNT(DISTINCT station_id) AS stations
                FROM airplay_windows{where}""",
            params,
        ).fetchone()
        plays_row = con.execute(
            f"SELECT COUNT(*) AS plays FROM airplay_plays{where}",
            params,
        ).fetchone()
        out = dict(row) if row else {}
        out["plays"] = int(plays_row["plays"] or 0) if plays_row else 0
        return out
