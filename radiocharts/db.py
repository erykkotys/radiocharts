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


def upsert_issue(source: str, chart_date: str | date, issue_key: str, chart_size: int, entries: Iterable[dict], source_url: str | None = None) -> int:
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
