from __future__ import annotations

import importlib
from datetime import date


def test_mobile_api_dashboard_and_note(tmp_path, monkeypatch):
    monkeypatch.setenv("RADIOCHARTS_DB", str(tmp_path / "api.db"))
    import radiocharts.db as db
    import radiocharts.metrics as metrics
    import radiocharts.api as api
    importlib.reload(db)
    importlib.reload(metrics)
    importlib.reload(api)

    db.init_db()
    db.upsert_issue("RMF", "2026-08-25", "rmf-1", 20, [{"position": 1, "artist": "Test Artist", "title": "Test Song"}])
    rows = api.songs(mode="dashboard", search="Test", statuses=[], downloaded="any", sort="popularity", descending=True, start=None, end=None, station_ids=None, limit=50, offset=0)
    assert rows["total"] == 1
    song_id = rows["items"][0]["song_id"]
    assert rows["items"][0]["RMF_pos"] == 1

    updated = api.patch_song(song_id, api.NotePatch(heard=True, status="Watch", downloaded=True, note="mobile"))
    assert updated["ok"] is True
    assert updated["song"]["heard"] is True
    assert updated["song"]["downloaded"] is True
    assert updated["song"]["note"] == "mobile"


def test_mobile_api_meta_has_statuses(tmp_path, monkeypatch):
    monkeypatch.setenv("RADIOCHARTS_DB", str(tmp_path / "api2.db"))
    import radiocharts.db as db
    import radiocharts.api as api
    importlib.reload(db)
    importlib.reload(api)
    data = api.meta()
    assert "Baza CF1" in data["base_statuses"]
    assert "CF1 Candidate" in data["candidate_statuses"]
