from datetime import date
from pathlib import Path

import radiocharts.db as db

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "radiocharts" / "app.py").read_text(encoding="utf-8")


def _db(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    monkeypatch.setenv("RADIOCHARTS_AUTO_LIBRARY_SEED", "0")
    db.init_db()


def test_0331_fast_airplay_spin_counts(tmp_path, monkeypatch):
    _db(monkeypatch, tmp_path)
    db.upsert_airplay_stations([
        {"station_id": 1, "name": "One"},
        {"station_id": 2, "name": "Two"},
    ])
    db.store_airplay_window(1, "One", "2026-08-20", 10, [
        {"played_at": "2026-08-20T10:05", "artist": "A", "title": "X"},
        {"played_at": "2026-08-20T10:45", "artist": "A", "title": "X"},
    ])
    db.store_airplay_window(2, "Two", "2026-08-20", 10, [
        {"played_at": "2026-08-20T10:15", "artist": "A", "title": "X"},
        {"played_at": "2026-08-20T10:35", "artist": "B", "title": "Y"},
    ])
    rows = db.airplay_spin_counts([1, 2], date(2026, 8, 20), date(2026, 8, 20))
    counts = {int(r["song_id"]): int(r["spins"]) for r in rows}
    assert sorted(counts.values()) == [1, 3]


def test_0331_song_airplay_grid_is_editable_and_charts_open():
    assert 'key=f"song_airplay_grid_{song_id}_{song_air_start}_{song_air_end}_' in APP
    chunk = APP.split('key=f"song_airplay_grid_{song_id}_{song_air_start}_{song_air_end}_', 1)[1][:420]
    assert 'editable_state=True' in chunk
    assert 'with st.expander("Szczegóły emisji per stacja i dzień", expanded=True):' in APP
    assert 'default_sources = available_sources' in APP


def test_0331_row_numbers_are_visual_and_enabled_in_three_main_tables():
    assert 'row_numbers: bool = False' in APP
    assert 'params.node.rowIndex + 1' in APP
    assert APP.count('row_numbers=True') >= 3


def test_0331_dashboard_has_selected_period_spins_and_airplay_is_decluttered():
    assert 'cached_airplay_spin_counts' in APP
    assert '"airplay_spins_period", "Emisje okres"' in APP
    assert '"airplay_spins_7d", "airplay_spins_period"' in APP
    assert 'st.caption(f"Zakres: {range_start} → {range_end}. Pełna zakończona doba' not in APP
    assert 'Raportujące stacje w tym zakresie:' not in APP
