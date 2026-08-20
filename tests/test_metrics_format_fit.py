import radiocharts.db as db
import radiocharts.metrics as metrics


def test_format_fit_does_not_collapse_when_song_leaves_latest_chart(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "format-fit.db")
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    db.init_db()

    db.upsert_issue("RMF", "2026-01-01", "old", 20, [
        {"position": 1, "artist": "Artist", "title": "Evergreen"},
    ])
    # Move the source clock far forward without the song in the latest issue.
    db.upsert_issue("RMF", "2026-08-20", "latest", 20, [
        {"position": 20, "artist": "Someone Else", "title": "Current"},
    ])

    scores = metrics.compute_scores(as_of="2026-08-20")
    row = scores[scores["title"] == "Evergreen"].iloc[0]
    assert row["RMF_pos"] != row["RMF_pos"]  # NaN / not in latest issue
    # Historical source affinity survives chart exit; old current-strength based
    # format fit would be almost zero after ~7 months.
    assert float(row["format_fit"]) > 50


def test_source_stats_exposes_historical_format_affinity():
    rows = [{
        "chart_date": "2026-08-01",
        "chart_size": 20,
        "position": 1,
        "reported_weeks": 10,
        "reported_peak": 1,
    }]
    st = metrics._source_stats(rows, "2026-08-20")
    assert st["format_affinity"] > st["current_strength"]
    assert 0 <= st["format_affinity"] <= 100
