from pathlib import Path


def test_android_has_native_emaus_navigation_and_tabs():
    root = Path(__file__).resolve().parents[1]
    main = (root / "android/RadioChartsAndroid/app/src/main/java/pl/radiocharts/mobile/MainActivity.kt").read_text(encoding="utf-8")
    api = (root / "android/RadioChartsAndroid/app/src/main/java/pl/radiocharts/mobile/Api.kt").read_text(encoding="utf-8")
    assert '"emaus" to "Schedule"' in main
    assert 'listOf("Scheduled", "ETM", "Played", "Porównanie", "Utwory", "Import")' in main
    assert 'composable("emaus")' in main
    assert 'LocalRadioScreen(store, previewVm)' in main
    assert 'localRadioDates' in api
    assert 'localRadioEvents' in api
    assert 'localRadioCompare' in api
    assert 'localRadioSongStats' in api
    assert 'zettaTest' in api
    assert 'zettaLive' in api
    assert 'zettaSchedule' in api


def test_local_radio_compare_api_accepts_hour_and_android_actions_exist():
    root = Path(__file__).resolve().parents[1]
    api = (root / "radiocharts/api.py").read_text(encoding="utf-8")
    assert 'hour: int | None = Query(default=None, ge=0, le=23)' in api
    assert 'local_compare_hour(service_date, hour)' in api
    assert '@app.post("/api/v1/local-radio/zetta/test")' in api
    assert '@app.post("/api/v1/local-radio/zetta/live")' in api
    assert '@app.post("/api/v1/local-radio/zetta/schedule")' in api
