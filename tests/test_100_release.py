from pathlib import Path

import radiocharts.db as db

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "radiocharts/app.py").read_text(encoding="utf-8")
ANDROID = (ROOT / "android/RadioChartsAndroid/app/src/main/java/pl/radiocharts/mobile/MainActivity.kt").read_text(encoding="utf-8")
MANIFEST = (ROOT / "android/RadioChartsAndroid/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")


def _use_db(monkeypatch, path):
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    monkeypatch.setenv("RADIOCHARTS_AUTO_LIBRARY_SEED", "0")


def test_v1_status_is_the_listened_state_and_legacy_heard_is_retained(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "v1.db")
    db.init_db()
    with db.connect() as con:
        sid = db.get_or_create_song(con, "Artist", "Track")
    db.update_note(sid, False, "Watch", "note", downloaded=False)
    row = db.get_song(sid)
    assert row["heard"] == 1
    db.update_note(sid, True, "Nie słuchałem", "note", downloaded=False)
    row = db.get_song(sid)
    assert row["heard"] == 0
    with db.connect() as con:
        cols = {r[1] for r in con.execute("PRAGMA table_info(song_notes)")}
    assert "heard" in cols


def test_v101_web_restores_derived_listened_column_and_autosaves_status_downloaded():
    assert 'checkbox("Przesłuchany"' not in APP
    assert 'dashboard_only_unheard' not in APP
    assert '"heard", "✓"' in APP
    assert 'editable=False, sortable=True, filter=False, cellDataType="boolean"' in APP
    assert 'show["heard"] = show["status"].fillna("Nie słuchałem").astype(str).ne("Nie słuchałem")' in APP
    assert '"downloaded", "Downloaded"' in APP
    assert 'on_change=_save_status' in APP
    assert 'on_change=_save_downloaded' in APP
    assert 'st.form_submit_button("Zapisz"' in APP
    assert 'st.session_state[saved_note_key] = note' in APP


def test_v1_today_preset_exists_and_7d_remains_default():
    assert '"Dzisiaj (1d)",' in APP
    assert 'if label == "Dzisiaj (1d)":' in APP
    assert 'start = end_date' in APP
    assert 'default_preset="Ostatni tydzień"' in APP
    assert 'listOf("1d" to "1d","7d" to "7d","28d" to "28d","90d" to "3m")' in ANDROID
    assert 'var period by remember { mutableStateOf("7d") }' in ANDROID


def test_v1_android_song_editor_autosaves_status_and_downloaded_and_save_is_notes():
    assert 'Text("Przesłuchany")' not in ANDROID
    assert 'Text("Downloaded")' in ANDROID
    assert 'NotePatch(newStatus != "Nie słuchałem",newStatus,dl,s.note)' in ANDROID
    assert 'NotePatch(status != "Nie słuchałem",status,newDl,s.note)' in ANDROID
    assert 'NotePatch(status != "Nie słuchałem",status,dl,note)' in ANDROID
    assert 'Text(if(savingNote)"Zapisuję…" else "Zapisz")' in ANDROID
    assert 'Downloaded ${value.uppercase()}' in ANDROID


def test_v1_android_charts_follow_device_and_can_force_landscape():
    assert 'SCREEN_ORIENTATION_SENSOR_LANDSCAPE' not in ANDROID
    assert 'SCREEN_ORIENTATION_UNSPECIFIED' in ANDROID
    assert 'SCREEN_ORIENTATION_LANDSCAPE' in ANDROID
    assert '"⟳ Poziomo"' in ANDROID
    assert '"↕ Auto"' in ANDROID
    assert 'android:configChanges="orientation|screenSize"' in MANIFEST


def test_v101_versions():
    gradle = (ROOT / "android/RadioChartsAndroid/app/build.gradle.kts").read_text(encoding="utf-8")
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.0.2"
    assert 'versionCode = 13' in gradle
    assert 'versionName = "1.0.2"' in gradle
