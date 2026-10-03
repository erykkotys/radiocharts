from pathlib import Path

import radiocharts.db as db
import radiocharts.zetta2go as z2g

ROOT = Path(__file__).resolve().parents[1]


def _use_db(monkeypatch, path):
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    monkeypatch.setenv("RADIOCHARTS_AUTO_LIBRARY_SEED", "0")


def test_zetta_settings_saved_in_shared_db_override_legacy_env(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "settings.db")
    monkeypatch.setenv("ZETTA2GO_USERNAME", "old-env-user")
    monkeypatch.setenv("ZETTA2GO_PASSWORD", "old-env-pass")

    z2g.save_settings(
        username="eryk",
        password="sekret",
        base_url="https://zetta.local/Zetta2GO/",
        station_id="station-1",
        verify_tls=False,
        schedule_horizon_days=9,
        live_enabled=True,
        schedule_enabled=False,
    )
    cfg = z2g.settings()
    assert cfg.username == "eryk"
    assert cfg.password == "sekret"
    assert cfg.base_url == "https://zetta.local/Zetta2GO"
    assert cfg.station_id == "station-1"
    assert cfg.verify_tls is False
    assert cfg.schedule_horizon_days == 9
    assert cfg.live_enabled is True
    assert cfg.schedule_enabled is False

    stored = db.get_app_settings({"zetta2go.username", "zetta2go.password"})
    assert stored == {"zetta2go.username": "eryk", "zetta2go.password": "sekret"}


def test_zetta_settings_can_explicitly_clear_credentials(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "settings-clear.db")
    monkeypatch.setenv("ZETTA2GO_USERNAME", "old-env-user")
    monkeypatch.setenv("ZETTA2GO_PASSWORD", "old-env-pass")
    z2g.save_settings(username="", password="")
    cfg = z2g.settings()
    assert cfg.username == ""
    assert cfg.password == ""
    assert cfg.configured is False


def test_settings_page_and_dynamic_worker_contract():
    app = (ROOT / "radiocharts/app.py").read_text(encoding="utf-8")
    scheduler = (ROOT / "radiocharts/scheduler.py").read_text(encoding="utf-8")
    assert '("settings", "Ustawienia")' in app
    assert 'Login Zetta2GO' in app
    assert 'Hasło Zetta2GO' in app
    assert 'save_zetta2go_settings(' in app
    assert 'if zcfg.configured and zcfg.live_enabled:\n        scheduler.add_job' not in scheduler
    assert 'CronTrigger(minute="*", second=5' in scheduler
    assert 'CronTrigger(hour=23, minute=59, second=20' in scheduler
