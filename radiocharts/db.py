from __future__ import annotations

import csv
import io
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
    downloaded INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_issue_source_date ON chart_issues(source, chart_date);
CREATE INDEX IF NOT EXISTS idx_entry_song ON chart_entries(song_id);
CREATE INDEX IF NOT EXISTS idx_song_title_key ON songs(title_key);
CREATE INDEX IF NOT EXISTS idx_song_artist_key ON songs(artist_key);
CREATE INDEX IF NOT EXISTS idx_entry_issue_song ON chart_entries(issue_id, song_id);

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


def _airplay_fk_points_to_station_id(con: sqlite3.Connection, table: str) -> bool:
    try:
        rows = con.execute(f"PRAGMA foreign_key_list({table})").fetchall()
    except Exception:
        return False
    return any(
        str(row["table"]) == "airplay_stations"
        and str(row["from"]) == "station_id"
        and str(row["to"]) == "station_id"
        for row in rows
    )


def _quarantine_legacy_airplay_daily(con: sqlite3.Connection) -> int:
    """Preserve and remove the obsolete ``airplay_daily`` table.

    Pre-0.3.x experimental databases could contain ``airplay_daily`` with a
    foreign key to ``airplay_stations(id)``.  The production station table uses
    ``station_id`` as its primary key, so once that parent is rebuilt SQLite can
    raise ``foreign key mismatch`` even while deleting an unrelated song (the
    delete cascades through the legacy child table).

    Current RadioCharts never reads ``airplay_daily``; daily statistics are
    derived from ``airplay_plays``.  To avoid throwing user data away we copy
    the table verbatim to a constraint-free legacy backup and then drop only the
    obsolete constrained table.
    """
    row = con.execute(
        "SELECT type FROM sqlite_master WHERE name='airplay_daily'"
    ).fetchone()
    if not row or str(row["type"]) != "table":
        return 0

    try:
        count = int(con.execute("SELECT COUNT(*) FROM airplay_daily").fetchone()[0])
    except Exception:
        count = 0

    # PRAGMA foreign_keys can be changed only outside an active transaction.
    con.commit()
    con.execute("PRAGMA foreign_keys=OFF")
    try:
        backup = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='airplay_daily_legacy_0315'"
        ).fetchone()
        if not backup:
            con.execute("CREATE TABLE airplay_daily_legacy_0315 AS SELECT * FROM airplay_daily")
        con.execute("DROP TABLE airplay_daily")
        con.commit()
    finally:
        con.execute("PRAGMA foreign_keys=ON")
    return count


def _airplay_schema_is_canonical(con: sqlite3.Connection) -> bool:
    """Return True only when the parent key really satisfies SQLite FK rules.

    Older experimental builds sometimes had ``airplay_stations(id PRIMARY KEY, ...)``
    and later merely *added* a ``station_id`` column.  A normal index on that
    column is not enough for a referenced parent key, so SQLite reports
    ``foreign key mismatch`` on every insert into airplay_windows/airplay_plays.
    """
    station_info = con.execute("PRAGMA table_info(airplay_stations)").fetchall()
    station_cols = {str(r["name"]): r for r in station_info}
    if "station_id" not in station_cols or int(station_cols["station_id"]["pk"] or 0) != 1:
        return False

    required_plays = {"id", "station_id", "played_at", "artist", "title", "artist_key", "title_key", "song_id", "retrieved_at"}
    required_windows = {"station_id", "play_date", "start_hour", "end_hour", "fetched_at", "play_count", "success", "message"}
    if not required_plays.issubset(_table_columns(con, "airplay_plays")):
        return False
    if not required_windows.issubset(_table_columns(con, "airplay_windows")):
        return False
    if not _airplay_fk_points_to_station_id(con, "airplay_plays"):
        return False
    if not _airplay_fk_points_to_station_id(con, "airplay_windows"):
        return False
    return True


def _legacy_expr(columns: set[str], column: str, default_sql: str) -> str:
    return column if column in columns else default_sql


def _rebuild_airplay_tables(con: sqlite3.Connection) -> None:
    """Rebuild all three airplay tables into one canonical FK-safe schema.

    This is intentionally a preservation migration: rows from partial/legacy
    tables are copied through TEMP backups, child rows with an unknown station
    get a placeholder parent, and no chart/notowania tables are touched.
    """
    station_cols = _table_columns(con, "airplay_stations")
    play_cols = _table_columns(con, "airplay_plays")
    window_cols = _table_columns(con, "airplay_windows")

    # PRAGMA foreign_keys can only be changed outside an active transaction.
    con.commit()
    con.execute("PRAGMA foreign_keys=OFF")
    try:
        con.executescript(
            """
            DROP TABLE IF EXISTS temp._rc_airplay_stations_backup;
            DROP TABLE IF EXISTS temp._rc_airplay_plays_backup;
            DROP TABLE IF EXISTS temp._rc_airplay_windows_backup;
            """
        )

        if "station_id" in station_cols:
            station_id_expr = "CASE WHEN station_id IS NULL OR station_id=0 THEN -rowid ELSE station_id END"
        elif "id" in station_cols:
            station_id_expr = "CASE WHEN id IS NULL OR id=0 THEN -rowid ELSE id END"
        else:
            station_id_expr = "-rowid"
        name_expr = _legacy_expr(station_cols, "name", "''")
        slug_expr = _legacy_expr(station_cols, "slug", "''")
        station_url_expr = _legacy_expr(station_cols, "source_url", "''")
        active_expr = _legacy_expr(station_cols, "active", "1")
        discovered_expr = _legacy_expr(station_cols, "discovered_at", "''")
        updated_expr = _legacy_expr(station_cols, "updated_at", "''")
        con.execute(
            f"""CREATE TEMP TABLE _rc_airplay_stations_backup AS
                SELECT {station_id_expr} AS station_id,
                       COALESCE(NULLIF({name_expr},''), 'Stacja ' || {station_id_expr}) AS name,
                       COALESCE({slug_expr},'') AS slug,
                       COALESCE({station_url_expr},'') AS source_url,
                       COALESCE({active_expr},1) AS active,
                       COALESCE({discovered_expr},'') AS discovered_at,
                       COALESCE({updated_expr},'') AS updated_at
                FROM airplay_stations"""
        )

        play_id_expr = _legacy_expr(play_cols, "id", "rowid")
        play_station_expr = _legacy_expr(play_cols, "station_id", "NULL")
        played_expr = _legacy_expr(play_cols, "played_at", "''")
        artist_expr = _legacy_expr(play_cols, "artist", "''")
        title_expr = _legacy_expr(play_cols, "title", "''")
        artist_key_expr = _legacy_expr(play_cols, "artist_key", "''")
        title_key_expr = _legacy_expr(play_cols, "title_key", "''")
        song_id_expr = _legacy_expr(play_cols, "song_id", "NULL")
        play_url_expr = _legacy_expr(play_cols, "source_url", "''")
        retrieved_expr = _legacy_expr(play_cols, "retrieved_at", "''")
        con.execute(
            f"""CREATE TEMP TABLE _rc_airplay_plays_backup AS
                SELECT {play_id_expr} AS id,{play_station_expr} AS station_id,
                       COALESCE({played_expr},'') AS played_at,
                       COALESCE({artist_expr},'') AS artist,
                       COALESCE({title_expr},'') AS title,
                       COALESCE({artist_key_expr},'') AS artist_key,
                       COALESCE({title_key_expr},'') AS title_key,
                       {song_id_expr} AS song_id,
                       COALESCE({play_url_expr},'') AS source_url,
                       COALESCE({retrieved_expr},'') AS retrieved_at
                FROM airplay_plays"""
        )

        window_station_expr = _legacy_expr(window_cols, "station_id", "NULL")
        play_date_expr = _legacy_expr(window_cols, "play_date", "''")
        start_hour_expr = _legacy_expr(window_cols, "start_hour", "0")
        end_hour_expr = _legacy_expr(window_cols, "end_hour", "0")
        fetched_expr = _legacy_expr(window_cols, "fetched_at", "''")
        play_count_expr = _legacy_expr(window_cols, "play_count", "0")
        window_url_expr = _legacy_expr(window_cols, "source_url", "''")
        success_expr = _legacy_expr(window_cols, "success", "1")
        message_expr = _legacy_expr(window_cols, "message", "''")
        con.execute(
            f"""CREATE TEMP TABLE _rc_airplay_windows_backup AS
                SELECT {window_station_expr} AS station_id,
                       COALESCE({play_date_expr},'') AS play_date,
                       COALESCE({start_hour_expr},0) AS start_hour,
                       COALESCE({end_hour_expr},0) AS end_hour,
                       COALESCE({fetched_expr},'') AS fetched_at,
                       COALESCE({play_count_expr},0) AS play_count,
                       COALESCE({window_url_expr},'') AS source_url,
                       COALESCE({success_expr},1) AS success,
                       COALESCE({message_expr},'') AS message
                FROM airplay_windows"""
        )

        con.executescript(
            """
            DROP TABLE IF EXISTS airplay_windows;
            DROP TABLE IF EXISTS airplay_plays;
            DROP TABLE IF EXISTS airplay_stations;

            CREATE TABLE airplay_stations (
                station_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                slug TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                discovered_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE airplay_plays (
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
            CREATE TABLE airplay_windows (
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
        )

        con.execute(
            """INSERT OR REPLACE INTO airplay_stations(station_id,name,slug,source_url,active,discovered_at,updated_at)
               SELECT station_id,name,slug,source_url,active,discovered_at,updated_at
               FROM _rc_airplay_stations_backup
               WHERE station_id IS NOT NULL AND station_id<>0"""
        )
        # Preserve orphan child rows by creating a minimal parent rather than
        # silently deleting their history.
        for backup in ("_rc_airplay_plays_backup", "_rc_airplay_windows_backup"):
            con.execute(
                f"""INSERT OR IGNORE INTO airplay_stations(station_id,name,slug,source_url,active,discovered_at,updated_at)
                    SELECT DISTINCT b.station_id,'Stacja ' || b.station_id,'','',1,'',''
                    FROM {backup} b
                    LEFT JOIN airplay_stations s ON s.station_id=b.station_id
                    WHERE b.station_id IS NOT NULL AND b.station_id<>0 AND s.station_id IS NULL"""
            )

        con.execute(
            """INSERT OR IGNORE INTO airplay_plays(
                   id,station_id,played_at,artist,title,artist_key,title_key,song_id,source_url,retrieved_at
               )
               SELECT b.id,b.station_id,b.played_at,b.artist,b.title,b.artist_key,b.title_key,
                      CASE WHEN sng.id IS NULL THEN NULL ELSE b.song_id END,
                      b.source_url,b.retrieved_at
               FROM _rc_airplay_plays_backup b
               LEFT JOIN songs sng ON sng.id=b.song_id
               WHERE b.station_id IS NOT NULL AND b.station_id<>0
                 AND b.played_at<>'' AND b.artist<>'' AND b.title<>''"""
        )
        con.execute(
            """INSERT OR REPLACE INTO airplay_windows(
                   station_id,play_date,start_hour,end_hour,fetched_at,play_count,source_url,success,message
               )
               SELECT station_id,play_date,start_hour,end_hour,fetched_at,play_count,source_url,success,message
               FROM _rc_airplay_windows_backup
               WHERE station_id IS NOT NULL AND station_id<>0 AND play_date<>''"""
        )
        con.executescript(
            """
            DROP TABLE IF EXISTS temp._rc_airplay_stations_backup;
            DROP TABLE IF EXISTS temp._rc_airplay_plays_backup;
            DROP TABLE IF EXISTS temp._rc_airplay_windows_backup;
            """
        )
        con.commit()
    finally:
        con.execute("PRAGMA foreign_keys=ON")


def _ensure_airplay_schema(con: sqlite3.Connection) -> int:
    """Upgrade old/partial airplay experiments to the production schema.

    Returns the number of rows preserved from the obsolete ``airplay_daily``
    table, if such a table existed.
    """
    quarantined_daily = _quarantine_legacy_airplay_daily(con)
    if not _airplay_schema_is_canonical(con):
        _rebuild_airplay_tables(con)

    # Defensive additive migration for any future/hand-edited database that is
    # structurally close enough not to require a full rebuild.
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

    con.execute("CREATE INDEX IF NOT EXISTS idx_airplay_stations_station_id ON airplay_stations(station_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_airplay_plays_time_station ON airplay_plays(played_at, station_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_airplay_plays_station_time ON airplay_plays(station_id, played_at)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_airplay_plays_track ON airplay_plays(title_key, artist_key)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_airplay_plays_song ON airplay_plays(song_id, played_at)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_airplay_windows_date ON airplay_windows(play_date, station_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_airplay_windows_station_date ON airplay_windows(station_id, play_date)")
    return quarantined_daily


def _link_airplay_songs(con: sqlite3.Connection) -> int:
    """Attach every stored spin to the shared ``songs`` catalogue.

    Airplay is still a separate *metric* from chart positions, but the musical
    object is shared: one song_id means one preview, note/status and chart
    history wherever the track is encountered.
    """
    missing_keys = con.execute(
        """SELECT id,artist,title FROM airplay_plays
           WHERE artist_key='' OR title_key='' OR artist_key IS NULL OR title_key IS NULL"""
    ).fetchall()
    for row in missing_keys:
        con.execute(
            "UPDATE airplay_plays SET artist_key=?,title_key=? WHERE id=?",
            (artist_anchor(str(row["artist"])) or normalize(str(row["artist"])), normalize(str(row["title"])), int(row["id"])),
        )

    groups = con.execute(
        """SELECT artist_key,title_key,MAX(artist) AS artist,MAX(title) AS title
           FROM airplay_plays
           WHERE title_key<>''
           GROUP BY artist_key,title_key"""
    ).fetchall()
    linked = 0
    for row in groups:
        artist = str(row["artist"] or "").strip()
        title = str(row["title"] or "").strip()
        if not artist or not title:
            continue
        song_id = get_or_create_song(con, artist, title)
        cur = con.execute(
            """UPDATE airplay_plays SET song_id=?
               WHERE artist_key=? AND title_key=? AND (song_id IS NULL OR song_id<>?)""",
            (song_id, str(row["artist_key"]), str(row["title_key"]), song_id),
        )
        linked += int(cur.rowcount or 0)
    return linked


def _relink_airplay_unique_chart_titles(con: sqlite3.Connection) -> int:
    """Relink safe RDS/title aliases to one chart-backed song.

    The 0.3.14 implementation scanned every distinct airplay title (tens of
    thousands on a populated database) and was accidentally executed twice on
    first startup.  This version works from the much smaller chart-title set
    and inspects only airplay titles that look like metadata-suffixed aliases.
    """
    chart_rows = con.execute(
        """SELECT DISTINCT s.id,s.title,s.title_key
           FROM songs s JOIN chart_entries e ON e.song_id=s.id
           WHERE s.title_key<>''"""
    ).fetchall()
    exact_map: dict[str, set[int]] = {}
    anchor_map: dict[str, set[int]] = {}
    for row in chart_rows:
        sid = int(row["id"])
        tkey = str(row["title_key"] or "")
        exact_map.setdefault(tkey, set()).add(sid)
        anchor = title_anchor(str(row["title"] or ""))
        if anchor:
            anchor_map.setdefault(anchor, set()).add(sid)

    changed = 0

    # Exact normalized titles: iterate chart titles, not the whole airplay
    # catalogue. This keeps first startup fast even with hundreds of thousands
    # of stored spins.
    for tkey, ids in exact_map.items():
        if len(ids) != 1 or not (len(tkey) >= 8 or len(tkey.split()) >= 2):
            continue
        target = next(iter(ids))
        cur = con.execute(
            "UPDATE airplay_plays SET song_id=? WHERE title_key=? AND (song_id IS NULL OR song_id<>?)",
            (target, tkey, target),
        )
        changed += int(cur.rowcount or 0)

    # Non-exact aliases only need Python anchoring when the displayed RDS title
    # contains a suffix that title_anchor() can actually strip.
    aliases = con.execute(
        """SELECT DISTINCT title,title_key FROM airplay_plays
           WHERE title_key<>'' AND (
               title LIKE '%(%' OR title LIKE '%[%' OR
               lower(title) LIKE '%radio edit%' OR
               lower(title) LIKE '%single edit%' OR
               lower(title) LIKE '%remaster%'
           )"""
    ).fetchall()
    for alias in aliases:
        raw_title = str(alias["title"] or "")
        tkey = str(alias["title_key"] or "")
        anchor = title_anchor(raw_title)
        if not anchor or anchor == tkey:
            continue
        anchored = anchor_map.get(anchor, set())
        distinctive = len(anchor) >= 6 or len(anchor.split()) >= 2
        if len(anchored) != 1 or not distinctive:
            continue
        target = next(iter(anchored))
        cur = con.execute(
            "UPDATE airplay_plays SET song_id=? WHERE title_key=? AND (song_id IS NULL OR song_id<>?)",
            (target, tkey, target),
        )
        changed += int(cur.rowcount or 0)

    # Do not delete catalogue rows here.  Apart from being unnecessary for the
    # relink itself, that cleanup can trigger cascades through obsolete tables
    # in pre-production databases and made startup both slower and fragile.
    return changed


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().replace("ł", "l").replace("&", " and ").replace("`", "'")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def title_anchor(value: str) -> str:
    """Normalize a title while removing common non-title RDS suffixes."""
    raw = str(value or "").strip()
    # Parenthetical/bracket suffixes with a year/project/version are metadata in
    # many playlists, not part of the recording title.
    raw = re.sub(
        r"\s*[\(\[][^\)\]]*(?:19|20)\d{2}[^\)\]]*[\)\]]\s*$",
        "", raw, flags=re.IGNORECASE,
    )
    raw = re.sub(
        r"\s*[\(\[][^\)\]]*(?:meskie\s+granie|męskie\s+granie|radio\s+edit|single\s+edit|remaster(?:ed)?)[^\)\]]*[\)\]]\s*$",
        "", raw, flags=re.IGNORECASE,
    )
    raw = re.sub(r"\s+[-–—]\s*(?:radio\s+edit|single\s+edit|remaster(?:ed)?).*?$", "", raw, flags=re.IGNORECASE)
    return normalize(raw)


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
        downloaded = any(bool(n["downloaded"]) for n in notes)
        chosen = notes[0] if notes else None
        note_texts = []
        for n in notes:
            txt = str(n["note"] or "").strip()
            if txt and txt not in note_texts:
                note_texts.append(txt)
        if notes:
            status = str(chosen["status"] or "Nie słuchałem")
            con.execute(
                """INSERT INTO song_notes(song_id,heard,status,downloaded,note,updated_at) VALUES(?,?,?,?,?,?)
                   ON CONFLICT(song_id) DO UPDATE SET heard=excluded.heard,status=excluded.status,downloaded=excluded.downloaded,note=excluded.note,updated_at=excluded.updated_at""",
                (cid, int(heard), status, int(downloaded), "\n---\n".join(note_texts), chosen["updated_at"]),
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
            # Airplay and chart history share the same musical entity.  Preserve
            # any existing spin links when consolidating aliases.
            try:
                con.execute("UPDATE airplay_plays SET song_id=? WHERE song_id=?", (cid, did))
            except sqlite3.OperationalError:
                pass
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


def _purge_eska_jingles(con: sqlite3.Connection) -> dict:
    """Delete RDS/jingle rows where artist or title contains the standalone token ``eska``.

    We intentionally match the normalized *word* rather than substring, so names
    such as ``Kreska`` are not removed. Window play_count is repaired only for
    affected 2h windows.
    """
    token_sql = "(" \
        "artist_key='eska' OR artist_key LIKE 'eska %' OR artist_key LIKE '% eska' OR artist_key LIKE '% eska %' " \
        "OR title_key='eska' OR title_key LIKE 'eska %' OR title_key LIKE '% eska' OR title_key LIKE '% eska %'" \
        ")"
    con.execute("DROP TABLE IF EXISTS temp._rc_eska_windows")
    con.execute(
        f"""CREATE TEMP TABLE _rc_eska_windows AS
            SELECT DISTINCT station_id,substr(played_at,1,10) AS play_date,
                   CAST(CAST(substr(played_at,12,2) AS INTEGER)/2 AS INTEGER)*2 AS start_hour
            FROM airplay_plays WHERE {token_sql}"""
    )
    plays_before = int(con.execute(f"SELECT COUNT(*) FROM airplay_plays WHERE {token_sql}").fetchone()[0] or 0)
    con.execute(f"DELETE FROM airplay_plays WHERE {token_sql}")

    # Recalculate only windows touched by the purge so diagnostics stay honest.
    con.execute(
        """UPDATE airplay_windows
           SET play_count=(
             SELECT COUNT(*) FROM airplay_plays p
             WHERE p.station_id=airplay_windows.station_id
               AND substr(p.played_at,1,10)=airplay_windows.play_date
               AND CAST(CAST(substr(p.played_at,12,2) AS INTEGER)/2 AS INTEGER)*2=airplay_windows.start_hour
           )
           WHERE EXISTS (
             SELECT 1 FROM _rc_eska_windows x
             WHERE x.station_id=airplay_windows.station_id
               AND x.play_date=airplay_windows.play_date
               AND x.start_hour=airplay_windows.start_hour
           )"""
    )
    songs_before = int(con.execute(
        """SELECT COUNT(*) FROM songs
           WHERE artist_key='eska' OR artist_key LIKE 'eska %' OR artist_key LIKE '% eska' OR artist_key LIKE '% eska %'
              OR title_key='eska' OR title_key LIKE 'eska %' OR title_key LIKE '% eska' OR title_key LIKE '% eska %'"""
    ).fetchone()[0] or 0)
    con.execute(
        """DELETE FROM songs
           WHERE artist_key='eska' OR artist_key LIKE 'eska %' OR artist_key LIKE '% eska' OR artist_key LIKE '% eska %'
              OR title_key='eska' OR title_key LIKE 'eska %' OR title_key LIKE '% eska' OR title_key LIKE '% eska %'"""
    )
    con.execute("DROP TABLE IF EXISTS temp._rc_eska_windows")
    return {"plays": plays_before, "songs": songs_before}


def init_db() -> None:
    global _INITIALIZED_DB_PATH
    current_path = str(DB_PATH)
    required_markers = {
        "song_alias_merge_v1",
        "billboard_metadata_reset_v1",
        "billboard_metadata_reset_v2",
        "source_checks_v1",
        "airplay_schema_v2",
        "airplay_schema_v3",
        "airplay_daily_legacy_v1",
        "airplay_link_songs_v1",
        "airplay_chart_title_relink_v1",
        "airplay_chart_title_relink_v2",
        "status_taxonomy_v2",
        "status_taxonomy_v3",
        "song_downloaded_v1",
        "airplay_dead_station_cleanup_v1",
        "airplay_eska_jingle_cleanup_v1",
    }
    if _INITIALIZED_DB_PATH == current_path and DB_PATH.exists():
        # Hot-path for a running web/worker process. Migrations are checked once
        # per process at startup; repeatedly opening SQLite here used to add
        # measurable latency because nearly every read helper calls init_db().
        return

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
                    quarantined_daily = _ensure_airplay_schema(con)

                    # Lightweight migrations for existing MVP databases.
                    cols = {row["name"] for row in con.execute("PRAGMA table_info(chart_entries)").fetchall()}
                    if "reported_weeks" not in cols:
                        con.execute("ALTER TABLE chart_entries ADD COLUMN reported_weeks INTEGER")
                    if "reported_peak" not in cols:
                        con.execute("ALTER TABLE chart_entries ADD COLUMN reported_peak INTEGER")

                    note_cols = {row["name"] for row in con.execute("PRAGMA table_info(song_notes)").fetchall()}
                    if "downloaded" not in note_cols:
                        con.execute("ALTER TABLE song_notes ADD COLUMN downloaded INTEGER NOT NULL DEFAULT 0")
                    con.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('song_downloaded_v1','done')")

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

                    status_mig = con.execute("SELECT value FROM app_meta WHERE key='status_taxonomy_v2'").fetchone()
                    if not status_mig:
                        status_map = {
                            "Ignore": "Poza formatem",
                            "Candidate": "CF Candidate",
                            "Current": "Baza CF2",
                            "Current Familiar": "Baza CF1",
                            "Recurrent": "Baza R1",
                            "Poza bazą": "Baza Hold",
                        }
                        for old_status, new_status in status_map.items():
                            con.execute(
                                "UPDATE song_notes SET status=? WHERE status=?",
                                (new_status, old_status),
                            )
                        con.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('status_taxonomy_v2','done')")

                    status_mig_v3 = con.execute("SELECT value FROM app_meta WHERE key='status_taxonomy_v3'").fetchone()
                    if not status_mig_v3:
                        status_map_v3 = {
                            "Candidate": "CF1 Candidate",
                            "CF Candidate": "CF1 Candidate",
                        }
                        for old_status, new_status in status_map_v3.items():
                            con.execute(
                                "UPDATE song_notes SET status=? WHERE status=?",
                                (new_status, old_status),
                            )
                        con.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('status_taxonomy_v3','done')")

                    # 0.3.26: seed the current local radio library once.  This
                    # makes songs that exist only in the station database visible
                    # in RadioCharts and aligns their status with the radio
                    # category.  The same parser is also exposed in Dane for
                    # future manual syncs of a fresh export.
                    seed_mode = os.getenv("RADIOCHARTS_AUTO_LIBRARY_SEED", "auto").strip().lower()
                    seed_enabled = seed_mode in {"1", "true", "yes", "on"} or (
                        seed_mode == "auto" and str(DB_PATH).replace("\\", "/").startswith("/app/data/")
                    )
                    if seed_enabled:
                        radio_seed = con.execute("SELECT value FROM app_meta WHERE key='radio_library_seed_20260825_v1'").fetchone()
                        if not radio_seed:
                            seed_path = Path(__file__).resolve().parent / "data" / "radio_library_seed_20260825.tsv"
                            seed_value = "missing"
                            if seed_path.exists():
                                try:
                                    seed_text = seed_path.read_text(encoding="utf-8-sig")
                                except UnicodeDecodeError:
                                    seed_text = seed_path.read_text(encoding="cp1250")
                                seed_rows, seed_parse = parse_radio_library_tsv(seed_text)
                                seed_result = _sync_radio_library_rows(con, seed_rows)
                                seed_value = (
                                    f"rows={seed_parse['rows']};added={seed_result['added']};"
                                    f"matched={seed_result['matched']};updated={seed_result['status_updated']}"
                                )
                            con.execute(
                                "INSERT OR REPLACE INTO app_meta(key,value) VALUES('radio_library_seed_20260825_v1',?)",
                                (seed_value,),
                            )

                    dead_station_mig = con.execute("SELECT value FROM app_meta WHERE key='airplay_dead_station_cleanup_v1'").fetchone()
                    if not dead_station_mig:
                        # 2026-01-01..2026-04-30 backfill: these stations returned
                        # zero plays in every successfully checked 2h window.
                        dead_names = ("Brak nazwy #7", "Freee", "RDN Małopolska", "Radiofonia", "Łódź Extra")
                        placeholders = ",".join("?" for _ in dead_names)
                        con.execute(
                            f"UPDATE airplay_stations SET active=0,updated_at=? WHERE name IN ({placeholders})",
                            (_utcnow(), *dead_names),
                        )
                        con.execute(
                            "INSERT OR REPLACE INTO app_meta(key,value) VALUES('airplay_dead_station_cleanup_v1','done')"
                        )

                    eska_cleanup = con.execute("SELECT value FROM app_meta WHERE key='airplay_eska_jingle_cleanup_v1'").fetchone()
                    if not eska_cleanup:
                        removed = _purge_eska_jingles(con)
                        con.execute(
                            "INSERT OR REPLACE INTO app_meta(key,value) VALUES('airplay_eska_jingle_cleanup_v1',?)",
                            (f"plays={removed['plays']};songs={removed['songs']}",),
                        )

                    con.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('source_checks_v1','done')")
                    con.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('airplay_schema_v2','done')")
                    con.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('airplay_schema_v3','done')")
                    con.execute(
                        "INSERT OR REPLACE INTO app_meta(key,value) VALUES('airplay_daily_legacy_v1',?)",
                        (str(quarantined_daily),),
                    )
                    airplay_link = con.execute("SELECT value FROM app_meta WHERE key='airplay_link_songs_v1'").fetchone()
                    if not airplay_link:
                        linked = _link_airplay_songs(con)
                        con.execute(
                            "INSERT OR REPLACE INTO app_meta(key,value) VALUES('airplay_link_songs_v1',?)",
                            (str(linked),),
                        )
                    alias_link = con.execute("SELECT value FROM app_meta WHERE key='airplay_chart_title_relink_v1'").fetchone()
                    alias_link_v2 = con.execute("SELECT value FROM app_meta WHERE key='airplay_chart_title_relink_v2'").fetchone()
                    if not alias_link or not alias_link_v2:
                        # Run the current relinker exactly once. 0.3.14 could run
                        # the same expensive pass twice when both markers were
                        # absent on an upgraded database.
                        relinked = _relink_airplay_unique_chart_titles(con)
                        value = str(relinked)
                        con.execute(
                            "INSERT OR REPLACE INTO app_meta(key,value) VALUES('airplay_chart_title_relink_v1',?)",
                            (value,),
                        )
                        con.execute(
                            "INSERT OR REPLACE INTO app_meta(key,value) VALUES('airplay_chart_title_relink_v2',?)",
                            (value,),
                        )
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


RADIO_LIBRARY_CATEGORIES = ("R2", "R1", "CF2", "CF1", "F1", "G1", "G2", "SP1", "SP2", "NB")


def radio_library_status(category: str) -> str:
    cat = str(category or "").strip().upper()
    if cat not in RADIO_LIBRARY_CATEGORIES:
        raise ValueError(f"Nieobsługiwana kategoria bazy radia: {category!r}")
    return f"Baza {cat}"


def parse_radio_library_tsv(text: str) -> tuple[list[dict], dict]:
    """Parse the station-library export used by the user's radio database.

    Expected columns are ``Active, Cat, Pack, Ver, Title, Artist, Album, Runtime``.
    Only Cat/Title/Artist are required for the sync itself.  The parser is kept
    deliberately strict about category codes so a typo cannot silently create a
    new status taxonomy.
    """
    raw = str(text or "").lstrip("\ufeff")
    first_line = raw.splitlines()[0] if raw.splitlines() else ""
    delimiter = "\t" if "\t" in first_line else ","
    reader = csv.DictReader(io.StringIO(raw), delimiter=delimiter)
    headers = {str(h or "").strip() for h in (reader.fieldnames or [])}
    required = {"Cat", "Title", "Artist"}
    missing = sorted(required - headers)
    if missing:
        raise ValueError("Brak wymaganych kolumn: " + ", ".join(missing))

    rows: list[dict] = []
    categories: dict[str, int] = {}
    skipped = 0
    unsupported: dict[str, int] = {}
    for src in reader:
        cat = str(src.get("Cat") or "").strip().upper()
        artist = str(src.get("Artist") or "").strip()
        title = str(src.get("Title") or "").strip()
        if not artist or not title or not cat:
            skipped += 1
            continue
        if cat not in RADIO_LIBRARY_CATEGORIES:
            unsupported[cat or "(brak)"] = unsupported.get(cat or "(brak)", 0) + 1
            continue
        categories[cat] = categories.get(cat, 0) + 1
        rows.append({
            "active": str(src.get("Active") or "").strip(),
            "category": cat,
            "artist": artist,
            "title": title,
            "album": str(src.get("Album") or "").strip(),
            "runtime": str(src.get("Runtime") or "").strip(),
        })
    return rows, {
        "rows": len(rows),
        "skipped": skipped,
        "unsupported": unsupported,
        "categories": categories,
    }


def _sync_radio_library_rows(con: sqlite3.Connection, rows: Iterable[dict]) -> dict:
    """Add missing radio-library songs and make the radio category authoritative.

    Existing heard/notatka state is preserved.  ``downloaded`` is set because a
    song present in this export is, by definition, already in the local radio
    library.  The status is updated to ``Baza <Cat>``.
    """
    added = matched = status_updated = downloaded_marked = 0
    processed = 0
    for src in rows:
        artist = str(src.get("artist") or "").strip()
        title = str(src.get("title") or "").strip()
        cat = str(src.get("category") or "").strip().upper()
        if not artist or not title or cat not in RADIO_LIBRARY_CATEGORIES:
            continue
        processed += 1
        existing_id = _match_song_id(con, artist, title)
        if existing_id is not None:
            song_id = int(existing_id)
            matched += 1
        else:
            song_id = get_or_create_song(con, artist, title)
            added += 1
        desired = radio_library_status(cat)
        note = con.execute(
            "SELECT heard,status,downloaded,note,updated_at FROM song_notes WHERE song_id=?",
            (int(song_id),),
        ).fetchone()
        now = _utcnow()
        if note:
            old_status = str(note["status"] or "Nie słuchałem")
            old_downloaded = bool(note["downloaded"])
            if old_status != desired or not old_downloaded:
                con.execute(
                    "UPDATE song_notes SET status=?,downloaded=1,updated_at=? WHERE song_id=?",
                    (desired, now, int(song_id)),
                )
            if old_status != desired:
                status_updated += 1
            if not old_downloaded:
                downloaded_marked += 1
        else:
            con.execute(
                "INSERT INTO song_notes(song_id,heard,status,downloaded,note,updated_at) VALUES(?,?,?,?,?,?)",
                (int(song_id), 0, desired, 1, "", now),
            )
            status_updated += 1
            downloaded_marked += 1
    return {
        "processed": processed,
        "added": added,
        "matched": matched,
        "status_updated": status_updated,
        "downloaded_marked": downloaded_marked,
    }


def sync_radio_library_tsv(text: str) -> dict:
    """Synchronize one uploaded radio-library TSV with the persistent DB."""
    rows, parsed = parse_radio_library_tsv(text)
    init_db()
    with connect() as con:
        result = _sync_radio_library_rows(con, rows)
    return {**parsed, **result}


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


def update_note(song_id: int, heard: bool, status: str, note: str, downloaded: bool | None = None) -> None:
    init_db()
    with connect() as con:
        if downloaded is None:
            existing = con.execute("SELECT downloaded FROM song_notes WHERE song_id=?", (int(song_id),)).fetchone()
            downloaded = bool(existing["downloaded"]) if existing else False
        con.execute(
            """INSERT INTO song_notes(song_id,heard,status,downloaded,note,updated_at) VALUES(?,?,?,?,?,?)
               ON CONFLICT(song_id) DO UPDATE SET heard=excluded.heard,status=excluded.status,downloaded=excluded.downloaded,note=excluded.note,updated_at=excluded.updated_at""",
            (song_id, int(heard), status, int(bool(downloaded)), note, _utcnow()),
        )



def chart_revision() -> str:
    """Cache key for chart-derived metrics only; note/status edits do not invalidate it."""
    init_db()
    with connect() as con:
        row = con.execute(
            """SELECT
                 COALESCE((SELECT MAX(retrieved_at) FROM chart_issues),'') AS charts,
                 COALESCE((SELECT MAX(id) FROM chart_entries),0) AS max_entry_id,
                 COALESCE((SELECT MAX(id) FROM chart_issues),0) AS max_issue_id"""
        ).fetchone()
        return f"{row['charts']}|{row['max_entry_id']}|{row['max_issue_id']}"


def list_songs() -> list[dict]:
    """Shared song catalogue used by charts and airplay views."""
    init_db()
    with connect() as con:
        rows = con.execute(
            """SELECT s.id AS song_id,s.artist,s.title,s.release_date,
                      COALESCE(n.heard,0) AS heard,
                      COALESCE(n.status,'Nie słuchałem') AS status,
                      COALESCE(n.downloaded,0) AS downloaded,
                      COALESCE(n.note,'') AS note,
                      n.updated_at
               FROM songs s
               LEFT JOIN song_notes n ON n.song_id=s.id
               ORDER BY s.artist COLLATE NOCASE,s.title COLLATE NOCASE,s.id"""
        ).fetchall()
        return [dict(r) for r in rows]


def get_song(song_id: int) -> dict | None:
    """Fetch one shared song row with live user state."""
    init_db()
    with connect() as con:
        row = con.execute(
            """SELECT s.id AS song_id,s.artist,s.title,s.release_date,s.artist_key,s.title_key,
                      COALESCE(n.heard,0) AS heard,COALESCE(n.status,'Nie słuchałem') AS status,
                      COALESCE(n.downloaded,0) AS downloaded,
                      COALESCE(n.note,'') AS note,n.updated_at
               FROM songs s LEFT JOIN song_notes n ON n.song_id=s.id WHERE s.id=?""",
            (int(song_id),),
        ).fetchone()
        return dict(row) if row else None


def song_catalog_revision() -> str:
    """Small cache key for the useful song picker catalogue.

    The airplay scraper can discover tens of thousands of raw RDS credits.  They
    should not make every Utwór page serialize a 50k-option selector.  The picker
    therefore contains chart-backed songs plus anything the user has manually
    rated/noted; an airplay-only song opened directly is added to the selector by
    the UI for that request.
    """
    init_db()
    with connect() as con:
        row = con.execute(
            """SELECT
                 COALESCE((SELECT MAX(id) FROM chart_entries),0) AS e,
                 COALESCE((SELECT MAX(updated_at) FROM song_notes),'') AS n"""
        ).fetchone()
    return f"{int(row['e'] or 0)}|{row['n'] or ''}"


def song_catalog() -> list[dict]:
    """Compact catalogue used by the native searchable Utwór selector.

    Airplay-only raw credits remain accessible from Emisje and by direct song
    URL.  Once a user rates/notes one, it automatically joins this picker too.
    """
    init_db()
    with connect() as con:
        rows = con.execute(
            """SELECT s.id AS song_id,s.artist,s.title
               FROM songs s
               WHERE EXISTS (SELECT 1 FROM chart_entries e WHERE e.song_id=s.id)
                  OR EXISTS (SELECT 1 FROM song_notes n WHERE n.song_id=s.id)
               ORDER BY s.artist COLLATE NOCASE,s.title COLLATE NOCASE,s.id"""
        ).fetchall()
        return [dict(r) for r in rows]


def canonical_song_id(song_id: int) -> int:
    """Resolve a safe chart-backed alias for one song, if one exists."""
    init_db()
    with connect() as con:
        row = con.execute("SELECT id,title,title_key FROM songs WHERE id=?", (int(song_id),)).fetchone()
        if not row:
            return int(song_id)
        has_chart = con.execute("SELECT 1 FROM chart_entries WHERE song_id=? LIMIT 1", (int(song_id),)).fetchone()
        if has_chart:
            return int(song_id)

        tkey = str(row['title_key'] or '')
        if len(tkey) >= 8 or len(tkey.split()) >= 2:
            candidates = con.execute(
                """SELECT DISTINCT e.song_id FROM chart_entries e JOIN songs s ON s.id=e.song_id
                   WHERE s.title_key=? LIMIT 2""", (tkey,),
            ).fetchall()
            if len(candidates) == 1:
                return int(candidates[0]['song_id'])

        anchor = title_anchor(str(row['title'] or ''))
        suffix_was_removed = bool(anchor and anchor != tkey)
        distinctive = bool(anchor) and (len(anchor) >= (6 if suffix_was_removed else 8) or len(anchor.split()) >= 2)
        if distinctive:
            matches = con.execute(
                """SELECT DISTINCT e.song_id FROM chart_entries e JOIN songs s ON s.id=e.song_id
                   WHERE s.title_key=? LIMIT 2""", (anchor,),
            ).fetchall()
            if len(matches) == 1:
                return int(matches[0]['song_id'])
        return int(song_id)


def load_notes() -> list[dict]:
    """Small live overlay for user state; intentionally separate from expensive chart metrics."""
    init_db()
    with connect() as con:
        rows = con.execute(
            "SELECT song_id,heard,status,downloaded,note,updated_at FROM song_notes"
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
                      COALESCE(n.downloaded,0) AS downloaded,
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
            # Discovery must not silently re-enable stations that the user
            # deliberately disabled after confirming they return no playlist
            # data.  Existing active state is therefore preserved; ``active``
            # is used only for newly discovered stations.
            existing = con.execute(
                "SELECT station_id FROM airplay_stations WHERE station_id=?",
                (station_id,),
            ).fetchone()
            if existing:
                con.execute(
                    """UPDATE airplay_stations
                       SET name=?,slug=?,source_url=?,updated_at=?
                       WHERE station_id=?""",
                    (name, slug, source_url, now, station_id),
                )
            else:
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


def set_airplay_station_active(station_ids: Iterable[int], active: bool) -> int:
    """Enable/disable stations without deleting their already collected data."""
    init_db()
    ids = sorted({int(x) for x in station_ids})
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    with connect() as con:
        cur = con.execute(
            f"UPDATE airplay_stations SET active=?,updated_at=? WHERE station_id IN ({placeholders})",
            (int(bool(active)), _utcnow(), *ids),
        )
        return int(cur.rowcount or 0)


def airplay_revision() -> str:
    """Cheap cache key for airplay-derived UI summaries."""
    init_db()
    with connect() as con:
        row = con.execute(
            """SELECT COALESCE(MAX(fetched_at),'') AS fetched,
                      COALESCE(MAX(play_date),'') AS play_date,
                      COUNT(*) AS windows,
                      COALESCE((SELECT MAX(updated_at) FROM airplay_stations),'') AS stations_updated
               FROM airplay_windows WHERE success=1"""
        ).fetchone()
    if not row:
        return ""
    return f"{row['fetched']}|{row['play_date']}|{row['windows']}|{row['stations_updated']}"


def latest_chart_positions() -> list[dict]:
    """Latest saved position per source/song, without computing full scores."""
    init_db()
    with connect() as con:
        rows = con.execute(
            """SELECT e.song_id,i.source,e.position,i.chart_date
               FROM chart_entries e
               JOIN chart_issues i ON i.id=e.issue_id
               JOIN (
                   SELECT source,MAX(chart_date) AS chart_date
                   FROM chart_issues GROUP BY source
               ) latest ON latest.source=i.source AND latest.chart_date=i.chart_date
               ORDER BY i.source,e.position"""
        ).fetchall()
        return [dict(r) for r in rows]


def chart_archive_summary() -> list[dict]:
    """What is physically stored in the chart archive, source by source."""
    init_db()
    with connect() as con:
        rows = con.execute(
            """SELECT i.source,
                      COUNT(DISTINCT i.id) AS issues,
                      MIN(i.chart_date) AS first_date,
                      MAX(i.chart_date) AS last_date,
                      COUNT(e.id) AS entries,
                      COUNT(DISTINCT e.song_id) AS songs
               FROM chart_issues i
               LEFT JOIN chart_entries e ON e.issue_id=i.id
               GROUP BY i.source
               ORDER BY i.source"""
        ).fetchall()
        return [dict(r) for r in rows]


def airplay_station_coverage(
    station_ids: Iterable[int],
    start_date: date | str,
    end_date: date | str,
) -> list[dict]:
    """Coverage/playlist health for every selected station in a date range.

    ``plays`` comes from stored window play_count, so a station with many
    successful windows but zero plays is distinguishable from a station that
    simply has not been downloaded yet.
    """
    init_db()
    ids = sorted({int(x) for x in station_ids})
    if not ids:
        return []
    start = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
    end = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
    if end < start:
        start, end = end, start
    placeholders = ",".join("?" for _ in ids)
    with connect() as con:
        rows = con.execute(
            f"""SELECT s.station_id,s.name,s.active,
                       SUM(CASE WHEN w.success=1 THEN 1 ELSE 0 END) AS ok_windows,
                       SUM(CASE WHEN w.success=1 AND w.play_count=0 THEN 1 ELSE 0 END) AS zero_windows,
                       SUM(CASE WHEN w.success=1 AND w.play_count>0 THEN 1 ELSE 0 END) AS nonempty_windows,
                       COALESCE(SUM(CASE WHEN w.success=1 THEN w.play_count ELSE 0 END),0) AS plays,
                       MIN(CASE WHEN w.success=1 THEN w.play_date END) AS first_date,
                       MAX(CASE WHEN w.success=1 THEN w.play_date END) AS last_date
                FROM airplay_stations s
                LEFT JOIN airplay_windows w
                  ON w.station_id=s.station_id AND w.play_date>=? AND w.play_date<=?
                WHERE s.station_id IN ({placeholders})
                GROUP BY s.station_id,s.name,s.active
                ORDER BY s.name COLLATE NOCASE,s.station_id""",
            (start.isoformat(), end.isoformat(), *ids),
        ).fetchall()
        return [dict(r) for r in rows]


def airplay_presence_summary(
    station_ids: Iterable[int] | None = None,
    *,
    days: int = 7,
    end_date: date | str | None = None,
) -> dict:
    """Recent radio breadth per song.

    Radio Presence is intentionally simple and auditable: the percentage of
    *reporting* selected stations (stations that returned at least one play in
    the window) that played the song at least once.  It is kept separate from
    chart-derived Familiarity and Momentum.
    """
    init_db()
    ids = sorted({int(x) for x in station_ids or []})
    days = max(1, int(days))
    with connect() as con:
        if end_date is None:
            row = con.execute(
                "SELECT MAX(substr(played_at,1,10)) AS d FROM airplay_plays"
            ).fetchone()
            if not row or not row["d"]:
                return {"start_date": None, "end_date": None, "days": days, "reporting_stations": 0, "rows": []}
            end = date.fromisoformat(str(row["d"]))
        else:
            end = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
        start = end - timedelta(days=days - 1)
        start_ts = datetime.combine(start, dt_time.min).isoformat(timespec="minutes")
        end_ts = datetime.combine(end + timedelta(days=1), dt_time.min).isoformat(timespec="minutes")
        clauses = ["p.played_at>=?", "p.played_at<?"]
        params: list[object] = [start_ts, end_ts]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            clauses.append(f"p.station_id IN ({placeholders})")
            params.extend(ids)
        else:
            clauses.append("s.active=1")
        where = " AND ".join(clauses)
        reporting = con.execute(
            f"""SELECT COUNT(DISTINCT p.station_id) AS n
                 FROM airplay_plays p JOIN airplay_stations s ON s.station_id=p.station_id
                 WHERE {where}""",
            tuple(params),
        ).fetchone()
        reporting_stations = int(reporting["n"] or 0) if reporting else 0
        rows = con.execute(
            f"""SELECT p.song_id,MAX(p.artist) AS artist,MAX(p.title) AS title,
                       COUNT(*) AS spins,COUNT(DISTINCT p.station_id) AS stations_count,
                       MAX(p.played_at) AS last_play
                FROM airplay_plays p JOIN airplay_stations s ON s.station_id=p.station_id
                WHERE {where} AND p.song_id IS NOT NULL
                GROUP BY p.song_id
                ORDER BY stations_count DESC,spins DESC""",
            tuple(params),
        ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        st_count = int(item.get("stations_count") or 0)
        spins = int(item.get("spins") or 0)
        reach = (100.0 * st_count / reporting_stations) if reporting_stations else 0.0
        per_station_day = spins / max(1, st_count) / days
        # Rotation intensity distinguishes a daily gold (~1/station/day) from a
        # hot recurrent/current (~6+ plays/station/day). Breadth remains dominant.
        rotation = min(100.0, 100.0 * per_station_day / 6.0)
        item["radio_reach"] = round(reach, 1)
        item["radio_rotation"] = round(rotation, 1)
        item["radio_presence"] = round(0.70 * reach + 0.30 * rotation, 1)
        item["airplay_spins_per_day"] = round(spins / days, 1)
        item["airplay_spins_per_station_day"] = round(per_station_day, 2)
        out.append(item)
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "days": days,
        "reporting_stations": reporting_stations,
        "rows": out,
    }


def airplay_song_presence(
    song_id: int,
    station_ids: Iterable[int] | None = None,
    *,
    days: int = 7,
    end_date: date | str | None = None,
) -> dict:
    """Efficient recent radio signal for one song.

    Unlike :func:`airplay_presence_summary`, this does not group every discovered
    airplay title, so the Utwór page stays fast on a large database.
    """
    init_db()
    ids = sorted({int(x) for x in station_ids or []})
    days = max(1, int(days))
    sid = canonical_song_id(int(song_id))
    with connect() as con:
        if end_date is None:
            row = con.execute("SELECT MAX(substr(played_at,1,10)) AS d FROM airplay_plays").fetchone()
            if not row or not row["d"]:
                return {"song_id": sid, "days": days, "reporting_stations": 0}
            end = date.fromisoformat(str(row["d"]))
        else:
            end = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
        start = end - timedelta(days=days - 1)
        start_ts = datetime.combine(start, dt_time.min).isoformat(timespec="minutes")
        end_ts = datetime.combine(end + timedelta(days=1), dt_time.min).isoformat(timespec="minutes")
        clauses = ["p.played_at>=?", "p.played_at<?"]
        params: list[object] = [start_ts, end_ts]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            clauses.append(f"p.station_id IN ({placeholders})")
            params.extend(ids)
        else:
            clauses.append("s.active=1")
        where = " AND ".join(clauses)
        rep = con.execute(
            f"""SELECT COUNT(DISTINCT p.station_id) AS n
                 FROM airplay_plays p JOIN airplay_stations s ON s.station_id=p.station_id
                 WHERE {where}""", tuple(params)
        ).fetchone()
        reporting = int(rep["n"] or 0) if rep else 0
        row = con.execute(
            f"""SELECT COUNT(*) AS spins,COUNT(DISTINCT p.station_id) AS stations_count,
                       MAX(p.played_at) AS last_play
                 FROM airplay_plays p JOIN airplay_stations s ON s.station_id=p.station_id
                 WHERE {where} AND p.song_id=?""", (*params, sid)
        ).fetchone()
    spins = int(row["spins"] or 0) if row else 0
    stations = int(row["stations_count"] or 0) if row else 0
    reach = 100.0 * stations / reporting if reporting else 0.0
    per_station_day = spins / max(1, stations) / days
    rotation = min(100.0, 100.0 * per_station_day / 6.0)
    return {
        "song_id": sid, "start_date": start.isoformat(), "end_date": end.isoformat(), "days": days,
        "reporting_stations": reporting, "stations_count": stations, "spins": spins,
        "radio_reach": round(reach, 1), "radio_rotation": round(rotation, 1),
        "radio_presence": round(0.70 * reach + 0.30 * rotation, 1),
        "airplay_spins_per_day": round(spins / days, 1),
        "airplay_spins_per_station_day": round(per_station_day, 2),
        "last_play": row["last_play"] if row else None,
    }


def _match_song_id(con: sqlite3.Connection, artist: str, title: str) -> int | None:
    """Best-effort match of an airplay credit to an existing chart/shared song."""
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

    anchor_artist = artist_anchor(artist)
    candidates = con.execute(
        "SELECT id,artist FROM songs WHERE title_key=? ORDER BY id", (tkey,),
    ).fetchall()
    if anchor_artist:
        for row in candidates:
            if artist_anchor(str(row["artist"])) == anchor_artist:
                return int(row["id"])

    # Exact title-only fallback when exactly one chart-backed recording owns a
    # reasonably distinctive title.
    if len(tkey) >= 8 or len(tkey.split()) >= 2:
        chart_candidates = con.execute(
            """SELECT DISTINCT e.song_id FROM chart_entries e JOIN songs s ON s.id=e.song_id
               WHERE s.title_key=? LIMIT 2""", (tkey,),
        ).fetchall()
        if len(chart_candidates) == 1:
            return int(chart_candidates[0]["song_id"])

    # RDS often appends a project/version suffix to the title. Match the stripped
    # title only when it uniquely identifies one chart song.
    tanchor = title_anchor(title)
    suffix_was_removed = bool(tanchor and tanchor != tkey)
    distinctive = bool(tanchor) and (len(tanchor) >= (6 if suffix_was_removed else 8) or len(tanchor.split()) >= 2)
    if distinctive:
        matches = con.execute(
            """SELECT DISTINCT s.id,s.artist FROM songs s JOIN chart_entries e ON e.song_id=s.id
               WHERE s.title_key=? LIMIT 3""", (tanchor,),
        ).fetchall()
        if anchor_artist:
            artist_matches = [r for r in matches if artist_anchor(str(r["artist"] or "")) == anchor_artist]
            if len({int(r['id']) for r in artist_matches}) == 1:
                return int(artist_matches[0]['id'])
        ids = {int(r['id']) for r in matches}
        if len(ids) == 1:
            return next(iter(ids))
    return None


def airplay_window_exists(
    station_id: int,
    play_date: date | str,
    start_hour: int,
    *,
    require_completed_capture: bool = False,
    tz_name: str = "Europe/Warsaw",
) -> bool:
    """Return True when a successful 2h window is already stored.

    With ``require_completed_capture`` we also verify that the row was fetched
    *after* the end of that public 2-hour block.  Older builds allowed a
    backfill of the current day to request future blocks; those empty rows were
    then marked successful and would be skipped forever.  A completed-capture
    check makes such prematurely stored rows self-healing on the next catch-up.
    """
    init_db()
    d_obj = date.fromisoformat(play_date) if isinstance(play_date, str) else play_date
    d = d_obj.isoformat()
    with connect() as con:
        row = con.execute(
            "SELECT success,fetched_at FROM airplay_windows WHERE station_id=? AND play_date=? AND start_hour=?",
            (int(station_id), d, int(start_hour)),
        ).fetchone()
    if not row or not bool(row["success"]):
        return False
    if not require_completed_capture:
        return True
    fetched_raw = str(row["fetched_at"] or "").strip()
    if not fetched_raw:
        return False
    try:
        fetched_at = datetime.fromisoformat(fetched_raw.replace("Z", "+00:00"))
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        tz = ZoneInfo(tz_name)
        end_local = datetime.combine(d_obj, dt_time(int(start_hour) % 24, 0), tzinfo=tz) + timedelta(hours=2)
        return fetched_at.astimezone(timezone.utc) >= end_local.astimezone(timezone.utc)
    except Exception:
        return False


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
            artist_norm = normalize(artist)
            title_norm = normalize(title)
            if "eska" in artist_norm.split() or "eska" in title_norm.split():
                continue
            artist_key = artist_anchor(artist) or artist_norm
            title_key = title_norm
            if not title_key:
                continue
            song_id = _match_song_id(con, artist, title) or get_or_create_song(con, artist, title)
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
    """Aggregate stored spins by canonical song_id.

    Aggregation is kept inside SQLite. Older builds returned one Python row per
    song *per station* and grouped those in Python; on a 300k-play database that
    made the Emisje page noticeably slower and allocated a large intermediate
    object.
    """
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
            f"""WITH per_station AS (
                    SELECT p.song_id,p.station_id,st.name AS station_name,
                           COUNT(*) AS station_spins,MAX(p.played_at) AS station_last
                    FROM airplay_plays p
                    JOIN airplay_stations st ON st.station_id=p.station_id
                    WHERE p.station_id IN ({placeholders})
                      AND p.played_at>=? AND p.played_at<? AND p.song_id IS NOT NULL
                    GROUP BY p.song_id,p.station_id
                ), ranked AS (
                    SELECT *,ROW_NUMBER() OVER(
                        PARTITION BY song_id ORDER BY station_spins DESC,station_name COLLATE NOCASE
                    ) AS rn
                    FROM per_station
                ), totals AS (
                    SELECT song_id,SUM(station_spins) AS spins,COUNT(*) AS stations_count,
                           MAX(station_spins) AS max_station_spins,MAX(station_last) AS last_play
                    FROM per_station GROUP BY song_id
                ), chart_first AS (
                    SELECT ce.song_id,MIN(i.chart_date) AS first_chart_date
                    FROM chart_entries ce JOIN chart_issues i ON i.id=ce.issue_id
                    GROUP BY ce.song_id
                )
                SELECT t.song_id,s.artist,s.title,s.release_date,s.artist_key,s.title_key,
                       cf.first_chart_date,
                       t.spins,t.stations_count,t.max_station_spins,
                       COALESCE(r.station_name,'') AS top_station,t.last_play,
                       ROUND(1.0*t.spins/CASE WHEN t.stations_count>0 THEN t.stations_count ELSE 1 END,1) AS avg_per_station
                FROM totals t JOIN songs s ON s.id=t.song_id
                LEFT JOIN ranked r ON r.song_id=t.song_id AND r.rn=1
                LEFT JOIN chart_first cf ON cf.song_id=t.song_id
                ORDER BY t.spins DESC,t.stations_count DESC,s.artist COLLATE NOCASE,s.title COLLATE NOCASE""",
            (*ids, start_ts, end_ts),
        ).fetchall()
        return [dict(r) for r in rows]


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


def airplay_track_detail_by_song(
    station_ids: Iterable[int],
    start_date: date | str,
    end_date: date | str,
    song_id: int,
    *,
    history_limit: int = 2000,
) -> dict:
    """Break one canonical song down by station/day.

    Grouping by song_id avoids fragmented results when different stations use
    different artist-credit strings for the same recording.
    """
    init_db()
    ids = sorted({int(x) for x in station_ids})
    if not ids:
        return {"total_spins":0,"stations_count":0,"first_play":None,"last_play":None,"stations":[],"daily":[],"plays":[]}
    sid = canonical_song_id(int(song_id))
    start = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
    end = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
    if end < start:
        start, end = end, start
    start_ts = datetime.combine(start, dt_time.min).isoformat(timespec="minutes")
    end_ts = datetime.combine(end + timedelta(days=1), dt_time.min).isoformat(timespec="minutes")
    placeholders = ",".join("?" for _ in ids)
    where = f"p.station_id IN ({placeholders}) AND p.played_at>=? AND p.played_at<? AND p.song_id=?"
    params = (*ids, start_ts, end_ts, sid)
    with connect() as con:
        station_rows = [dict(r) for r in con.execute(
            f"""SELECT s.name AS station,COUNT(*) AS spins,COUNT(DISTINCT substr(p.played_at,1,10)) AS active_days,
                       MIN(p.played_at) AS first_play,MAX(p.played_at) AS last_play
                FROM airplay_plays p JOIN airplay_stations s ON s.station_id=p.station_id
                WHERE {where} GROUP BY p.station_id,s.name ORDER BY spins DESC,s.name COLLATE NOCASE""", params
        ).fetchall()]
        daily_rows = [dict(r) for r in con.execute(
            f"""SELECT substr(p.played_at,1,10) AS play_date,s.name AS station,COUNT(*) AS spins
                FROM airplay_plays p JOIN airplay_stations s ON s.station_id=p.station_id
                WHERE {where} GROUP BY play_date,p.station_id,s.name ORDER BY play_date,s.name COLLATE NOCASE""", params
        ).fetchall()]
        play_rows = [dict(r) for r in con.execute(
            f"""SELECT p.played_at,s.name AS station FROM airplay_plays p
                JOIN airplay_stations s ON s.station_id=p.station_id WHERE {where}
                ORDER BY p.played_at DESC,p.station_id LIMIT ?""", (*params, max(1,int(history_limit)))
        ).fetchall()]
    total = sum(int(r.get('spins') or 0) for r in station_rows)
    first_play = min((str(r.get('first_play') or '') for r in station_rows if r.get('first_play')), default=None)
    last_play = max((str(r.get('last_play') or '') for r in station_rows if r.get('last_play')), default=None)
    return {"total_spins":total,"stations_count":len(station_rows),"first_play":first_play,"last_play":last_play,"stations":station_rows,"daily":daily_rows,"plays":play_rows,"song_id":sid}


def airplay_coverage(
    station_ids: Iterable[int] | None = None,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
) -> dict:
    """Return stored airplay coverage, optionally limited to an inclusive date range."""
    init_db()
    ids = sorted({int(x) for x in station_ids or []})
    clauses: list[str] = []
    params_list: list = []
    if ids:
        placeholders = ",".join("?" for _ in ids)
        clauses.append(f"station_id IN ({placeholders})")
        params_list.extend(ids)
    start = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
    end = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
    if start and end and end < start:
        start, end = end, start
    if start:
        clauses.append("play_date>=?")
        params_list.append(start.isoformat())
    if end:
        clauses.append("play_date<=?")
        params_list.append(end.isoformat())
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params = tuple(params_list)

    # airplay_plays has no play_date column; use timestamp bounds there.
    play_clauses: list[str] = []
    play_params: list = []
    if ids:
        placeholders = ",".join("?" for _ in ids)
        play_clauses.append(f"station_id IN ({placeholders})")
        play_params.extend(ids)
    if start:
        play_clauses.append("played_at>=?")
        play_params.append(datetime.combine(start, dt_time.min).isoformat(timespec="minutes"))
    if end:
        play_clauses.append("played_at<?")
        play_params.append(datetime.combine(end + timedelta(days=1), dt_time.min).isoformat(timespec="minutes"))
    play_where = (" WHERE " + " AND ".join(play_clauses)) if play_clauses else ""

    with connect() as con:
        row = con.execute(
            f"""SELECT COUNT(*) AS windows,
                       SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) AS ok_windows,
                       SUM(CASE WHEN success=1 AND play_count=0 THEN 1 ELSE 0 END) AS zero_windows,
                       MIN(play_date) AS first_date,MAX(play_date) AS last_date,
                       COUNT(DISTINCT station_id) AS stations
                FROM airplay_windows{where}""",
            params,
        ).fetchone()
        plays_row = con.execute(
            f"SELECT COUNT(*) AS plays FROM airplay_plays{play_where}",
            tuple(play_params),
        ).fetchone()
        out = dict(row) if row else {}
        out["plays"] = int(plays_row["plays"] or 0) if plays_row else 0
        return out
