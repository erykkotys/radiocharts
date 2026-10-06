from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "radiocharts/app.py").read_text(encoding="utf-8")
DB = (ROOT / "radiocharts/db.py").read_text(encoding="utf-8")
ANDROID = (ROOT / "android/RadioChartsAndroid/app/src/main/java/pl/radiocharts/mobile/MainActivity.kt").read_text(encoding="utf-8")


def test_1221_main_web_nav_order_and_labels():
    expected = [
        '("dashboard", "Dashboard")',
        '("archive", "Notowania")',
        '("airplay", "Emisje")',
        '("watched", "Watched")',
        '("song", "Utwór")',
        '("library", "Baza")',
        '("our_radio", "Schedule")',
        '("settings", "Ustawienia")',
        '("data", "Dane")',
        '("methodology", "Manual")',
    ]
    positions = [APP.index(item) for item in expected]
    assert positions == sorted(positions)


def test_1221_watched_combines_chart_and_airplay_and_freezes_membership():
    assert "def monitoring_song_catalog" in DB
    assert "EXISTS (SELECT 1 FROM chart_entries" in DB
    assert "EXISTS (SELECT 1 FROM airplay_plays" in DB
    assert 'snapshot_key = "watched_page_snapshot_v1"' in APP
    assert 'status.isin(set(CANDIDATE_STATUSES))' in APP
    assert 'status.eq("Watch")' in APP
    assert 'status.eq("Nie słuchałem")' in APP
    assert '.head(50)' in APP
    assert '"tracked_ids"' in APP and '"unheard_ids"' in APP


def test_1221_watched_reuses_editable_song_grid_and_schedule_label_android():
    assert 'key="watched_tracked_grid"' in APP
    assert 'key="watched_unheard_grid"' in APP
    assert 'editable_state=True' in APP
    assert '"emaus" to "Schedule"' in ANDROID
