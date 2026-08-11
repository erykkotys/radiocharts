import os
from pathlib import Path

import pytest

import radiocharts.db as db


def test_duplicate_song_is_rejected_before_write(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'test.db')
    db.init_db()
    with pytest.raises(ValueError, match='ten sam utwór'):
        db.upsert_issue('TEST', '2026-08-11', 'x', 100, [
            {'position': 1, 'artist': 'Artist', 'title': 'Song'},
            {'position': 2, 'artist': 'Artist', 'title': 'Song'},
        ])
    assert db.latest_issues() == []
