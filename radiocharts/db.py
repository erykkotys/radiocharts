from __future__ import annotations

import os
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

DB_PATH = Path(os.getenv("RADIOCHARTS_DB", "/app/data/radiocharts.db"))
if str(DB_PATH).startswith("/app/") and not Path("/app").exists():
    DB_PATH = Path(os.getenv("RADIOCHARTS_DB", str(Path(__file__).resolve().parent.parent / "data" / "radiocharts.db")))

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
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().replace("&", " and ").replace("`", "'")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


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
    with connect() as con:
        con.executescript(SCHEMA)
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
        # RMF demo issue 6180 shares the real RMF issue key and has already been
        # replaced by the real backfill/current collector.
        con.execute(
            """DELETE FROM chart_issues
               WHERE source='ZET' AND issue_key='ZET-2026-08-06'
                 AND source_url='manual seed from public chart'"""
        )


def get_or_create_song(con: sqlite3.Connection, artist: str, title: str, release_date: str | None = None) -> int:
    akey, tkey = normalize(artist), normalize(title)
    row = con.execute("SELECT id, release_date FROM songs WHERE artist_key=? AND title_key=?", (akey, tkey)).fetchone()
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
    seen_pos: dict[int, str] = {}
    seen_song: dict[tuple[str, str], int] = {}
    for e in rows:
        if "position" not in e or "artist" not in e or "title" not in e:
            raise ValueError(f"{source}: wpis bez position/artist/title: {e!r}")
        pos = int(e["position"])
        song_key = (normalize(str(e["artist"])), normalize(str(e["title"])))
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



def list_issues(source: str | None = None, limit: int = 1000) -> list[dict]:
    """Return stored chart issues newest first for archive browsing."""
    init_db()
    limit = max(1, min(int(limit), 5000))
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
