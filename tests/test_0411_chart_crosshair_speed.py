from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "radiocharts/app.py").read_text(encoding="utf-8")
DB = (ROOT / "radiocharts/db.py").read_text(encoding="utf-8")
ANDROID = (ROOT / "android/RadioChartsAndroid/app/src/main/java/pl/radiocharts/mobile/MainActivity.kt").read_text(encoding="utf-8")


def test_web_chart_uses_per_trace_custom_data_and_unified_crosshair():
    assert 'custom_data=["position"]' in APP
    assert 'hovermode="x unified"' in APP
    assert 'hoverformat="%d.%m.%Y"' in APP
    assert 'spikemode="across"' in APP
    assert 'fig.update_traces(customdata=plot_df[["position"]]' not in APP


def test_android_crosshair_selects_date_and_lists_all_points():
    assert 'var selectedDate by remember(points)' in ANDROID
    assert 'points.filter{it.chart_date==d}' in ANDROID
    assert '"${p.source}  #${p.position}"' in ANDROID
    assert 'drawLine(Color.White.copy(alpha=0.42f)' in ANDROID
    assert 'MetricTiny("Peak"' in ANDROID or 'MetricTiny("Peak ${peakPoint.source}"' in ANDROID
    assert 'shortChartDate(peakPoint.chart_date)' in ANDROID


def test_web_navigation_heavy_metadata_is_cached():
    assert 'def cached_airplay_stations(' in APP
    assert 'def cached_airplay_coverage(' in APP
    assert 'def cached_airplay_station_coverage(' in APP
    assert 'def cached_radio_library_catalog(' in APP
    assert 'CHART_REV = chart_revision()' in APP
    assert 'AIR_REV = airplay_revision()' in APP


def test_first_chart_date_queries_do_not_group_entire_chart_archive():
    library_block = DB[DB.index('def radio_library_catalog'):DB.index('def radio_library_overview')]
    summary_block = DB[DB.index('def airplay_summary'):DB.index('def airplay_track_detail')]
    assert 'WHERE ce.song_id=s.id' in library_block
    assert 'GROUP BY ce.song_id' not in library_block
    assert 'WHERE ce2.song_id=t.song_id' in summary_block
    assert 'GROUP BY ce.song_id' not in summary_block


def test_versions_0411():
    gradle=(ROOT/'android/RadioChartsAndroid/app/build.gradle.kts').read_text(encoding='utf-8')
    assert 'versionCode = 13' in gradle
    assert 'versionName = "1.0.2"' in gradle
    assert (ROOT/'VERSION').read_text(encoding='utf-8').strip() == '1.0.2'
