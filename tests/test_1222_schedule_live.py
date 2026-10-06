from pathlib import Path

import radiocharts.db as db
import radiocharts.local_station as local_station
from radiocharts.local_station import ensure_song_links_current, events_for_day, import_gselector_export

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "radiocharts/app.py").read_text(encoding="utf-8")
DB = (ROOT / "radiocharts/db.py").read_text(encoding="utf-8")
LOCAL = (ROOT / "radiocharts/local_station.py").read_text(encoding="utf-8")
API = (ROOT / "radiocharts/api.py").read_text(encoding="utf-8")
ANDROID = (ROOT / "android/RadioChartsAndroid/app/src/main/java/pl/radiocharts/mobile/MainActivity.kt").read_text(encoding="utf-8")


def _use_db(monkeypatch, path):
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    monkeypatch.setenv("RADIOCHARTS_AUTO_LIBRARY_SEED", "0")


def _song(time: str, artist: str, title: str, ext: str) -> str:
    cols = [
        time, "CF1/FAMILIAR CURRENT", "3", "5", artist, title, "Stretch", "YES", "", "5", "2", "0",
        time, "", "03:00.0", "Male", ext, "0", "0", "False", time,
    ]
    return "\t".join(f'"{x}"' for x in cols)


def test_1222_nav_restores_data_before_manual_and_watched_uses_light_catalog():
    settings = APP.index('(\"settings\", \"Ustawienia\")')
    data = APP.index('(\"data\", \"Dane\")')
    manual = APP.index('(\"methodology\", \"Manual\")')
    assert settings < data < manual
    assert "def watched_song_catalog" in DB
    assert "base = pd.DataFrame(watched_song_catalog())" in APP
    assert "visible_ids = tuple(sorted" in APP
    assert "details = cached_basic_song_metrics(chart_rev, air_rev, visible_ids)" in APP


def test_1222_hour_jump_is_client_only_and_scoped_per_view():
    assert "def _render_local_hour_nav" in APP
    assert "window.parent.document" in APP
    assert "scrollIntoView" in APP
    assert 'data-target="now"' in APP
    assert "window.location" not in APP[APP.index("def _render_local_hour_nav"):APP.index("def _local_row_clock_for_live")]
    assert 'anchor_prefix=f"{key_prefix}-list"' in APP
    assert '_render_local_hour_nav("our-radio-compare"' in APP
    assert 'id="our-radio-compare-hour-' in APP


def test_1222_pending_played_is_not_authoritative_current():
    current_block = APP[APP.index("def _local_current_played_row"):APP.index("def _local_schedule_current_rows")]
    assert "for wanted in (2, 9)" in current_block
    assert "-3" not in current_block
    continuity = APP[APP.index("def _local_played_continuity_rows"):APP.index("def _local_traffic_block_html")]
    assert "status in {2,9}" in continuity
    assert "status == -3" in continuity
    assert "listOf(2, 9)" in ANDROID
    assert "in {2,9}" in API


def test_1222_traffic_parent_preview_and_white_song_link_contract():
    assert "rc-traffic-parent" in APP
    assert "rc-traffic-children" in APP
    assert "rc-local-time" in APP[APP.index("def _local_traffic_block_html"):APP.index("def _render_local_timeline_cards")]
    assert "window.top.__rcPlayPreview" in APP
    assert ".rc-local-song-link { color:var(--rc-song) !important" in APP
    assert "▶ = odsłuch 30 s" in APP


def test_1222_song_link_repair_creates_shared_stub_for_new_schedule_song(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "links.db")
    text = _song("10:00:00.0", "Brand New Artist", "Brand New Song", "NEW-1")
    import_gselector_export(text, filename="06.10_schedule.txt", kind="schedule", start_date="2026-10-06")
    before = events_for_day("schedule", "2026-10-06")
    assert before and before[0]["song_id"] is None
    result = ensure_song_links_current()
    after = events_for_day("schedule", "2026-10-06")
    assert result["linked"] == 1
    assert after[0]["song_id"] is not None
    song = db.get_song(int(after[0]["song_id"]))
    assert song and song["artist"] == "Brand New Artist" and song["title"] == "Brand New Song"


def test_1222_existing_song_matcher_uses_shared_identity_alias_layer():
    assert "db._match_song_id(con, artist, title)" in LOCAL
    assert '"emaus"' in LOCAL
    assert "db.get_or_create_song(con, artist, title)" in LOCAL


def test_1222_etm_diagnostics_preserve_native_gap_and_show_carry():
    assert '"zetta_gap_native_ms": asset.get("gap")' in LOCAL
    assert "Diagnostyka ETM — skąd bierze się różnica" in APP
    assert '"Carry RESET"' in APP
    assert '"Zetta"' in APP and '"Wynik"' in APP
    # No arbitrary clipping: legitimate evening overtimes must stay visible.
    etm_block = APP[APP.index("def _render_local_etm_page"):APP.index("def _local_status_symbol")]
    assert ".clip(" not in etm_block
